# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Admin dashboard - fees: every student's fee lines in one filterable
table, collection by class/section, the defaulters list, and the fee
categories structures are built from. School-wide KPIs and trends stay on
/dashboards/fees; structures and payments on /fees/*.

A student's class/section is their running enrollment - fee lines raised
from a fee structure don't carry one - falling back to the class/section
stored on the fee line."""
from odoo import http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth

from ..models.res_users import PERMISSION_GROUPS
from .common import (
    atomic, check_selection, date_str, is_true, parse_date, parse_pagination, parse_sort, ref, resolve_record,
    running_enrollments,
)
from .dashboard import _allowed
from .fee import _detail_dict

GROUPS = PERMISSION_GROUPS['fee_staff']
SORTS = {
    'due_date': 'date', 'student': 'student_id', 'total_payable': 'total_payable', 'amount_paid': 'amount_paid',
    'amount_pending': 'amount_pending', 'days_overdue': 'days_overdue', 'status': 'collection_status',
}
DEFAULTER_SORTS = ('overdue_amount', 'days_overdue', 'oldest_due_date', 'student')
OVERDUE = Domain('days_overdue', '>', 0) & Domain('amount_pending', '>', 0)
MONEY = ['total_payable:sum', 'amount_paid:sum', 'amount_pending:sum']


def _forbidden():
    return api_error('Not authorized for fee administration.', status=403, code='forbidden')


def _student_ref(student):
    return {'id': student.id, 'name': student.name, 'gr_no': student.gr_no or None}


def _fee_domain(env, params):
    """(domain, error) for the filters /admin/fees, /by-class and
    /defaulters share. Cancelled lines are left out unless ?state= asks."""
    Detail = env['op.student.fees.details']
    domain = Domain.TRUE
    if params.get('state'):
        error = check_selection(Detail, 'state', params['state'])
        if error:
            return None, error
        domain &= Domain('state', '=', params['state'])
    else:
        domain &= Domain('state', '!=', 'cancel')
    if params.get('collection_status'):
        error = check_selection(Detail, 'collection_status', params['collection_status'])
        if error:
            return None, error
        domain &= Domain('collection_status', '=', params['collection_status'])
    for param, field in (('student_id', 'student_id'), ('structure_id', 'structure_id'),
                         ('academic_year_id', 'structure_id.academic_year_id')):
        if params.get(param):
            value, error = parse_int(params[param], param)
            if error:
                return None, error
            domain &= Domain(field, '=', value)
    for param, field in (('course_id', 'course_id'), ('batch_id', 'batch_id')):
        if params.get(param):
            value, error = parse_int(params[param], param)
            if error:
                return None, error
            domain &= Domain('student_id.course_detail_ids', 'any', [('state', '=', 'running'), (field, '=', value)]) \
                | Domain(field, '=', value)
    if params.get('category_id'):
        category, error = resolve_record(env, 'bxi.fee.category', params['category_id'], 'category_id')
        if error:
            return None, error
        domain &= Domain('product_id', '=', category.product_id.id)
    if is_true(params.get('overdue')):
        domain &= OVERDUE
    for param, operator in (('due_from', '>='), ('due_to', '<=')):
        if params.get(param):
            value, error = parse_date(params[param], param)
            if error:
                return None, error
            domain &= Domain('date', operator, value)
    if params.get('q'):
        domain &= Domain('student_id.name', 'ilike', params['q']) | Domain('student_id.gr_no', 'ilike', params['q'])
    return domain, None


def _money(payable, paid, pending):
    return {
        'total_payable': payable,
        'amount_paid': paid,
        'amount_pending': pending,
        'collection_percentage': round(100.0 * paid / payable, 1) if payable else 0.0,
    }


def _category_dict(category):
    return {
        'id': category.id,
        'name': category.name,
        'code': category.code or None,
        'product': ref(category.product_id),
        'default_frequency': category.default_frequency,
        'is_refundable': category.is_refundable,
        'sequence': category.sequence,
        'active': category.active,
    }


class BxiApiSupportAdminFeesController(http.Controller):

    @http.route('/api/v1/admin/fees', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_fees(self, sort=None, **kwargs):
        """Fee lines across all students. Filters: student_id, course_id,
        batch_id, structure_id, category_id, academic_year_id, state,
        collection_status, overdue=1, due_from/due_to, q (student name or
        registration number). The summary covers every matching line."""
        env = request.env
        if not _allowed(env.user, GROUPS):
            return _forbidden()
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        order, error = parse_sort(sort, SORTS, 'due_date desc')
        if error:
            return error
        domain, error = _fee_domain(env, kwargs)
        if error:
            return error
        Detail = env['op.student.fees.details'].sudo()
        total = Detail.search_count(domain)
        details = Detail.search(domain, limit=limit, offset=offset,
                                order='%s %s, id %s' % (SORTS[order[0]], order[1], order[1]))
        enrollments = running_enrollments(env, details.student_id)
        items = []
        for detail in details:
            enrollment = enrollments.get(detail.student_id.id)
            items.append(dict(
                _detail_dict(detail),
                student=_student_ref(detail.student_id),
                **{'class': ref(enrollment.course_id if enrollment else detail.course_id)},
                section=ref(enrollment.batch_id if enrollment else detail.batch_id),
                currency=detail.currency_id.name,
            ))
        [(payable, paid, pending)] = Detail._read_group(domain, [], MONEY)
        [(overdue,)] = Detail._read_group(domain & OVERDUE, [], ['amount_pending:sum'])
        payable, paid, pending, overdue = payable or 0.0, paid or 0.0, pending or 0.0, overdue or 0.0
        return api_response({
            'items': items,
            'summary': dict(
                _money(payable, paid, pending),
                overdue_amount=overdue,
                lines=total,
                by_status={status: count for status, count in
                           Detail._read_group(domain, ['collection_status'], ['__count'])},
                currency=env.company.currency_id.name,
            ),
        }, meta={'total': total, 'limit': limit, 'offset': offset})

    @http.route('/api/v1/admin/fees/by-class', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def fees_by_class(self, group_by='class', **kwargs):
        """Collection per class, or per section with ?group_by=section:
        students billed, payable, collected, pending, overdue and the
        collection percentage. Takes the /admin/fees filters."""
        env = request.env
        if not _allowed(env.user, GROUPS):
            return _forbidden()
        if group_by not in ('class', 'section'):
            return api_error('group_by must be class or section.', status=400, code='invalid_group_by')
        domain, error = _fee_domain(env, kwargs)
        if error:
            return error
        Detail = env['op.student.fees.details'].sudo()
        rows = Detail._read_group(domain, ['student_id'], MONEY)
        overdue = dict(Detail._read_group(domain & OVERDUE, ['student_id'], ['amount_pending:sum']))
        students = env['op.student'].sudo().browse([student.id for student, *_ in rows])
        enrollments = running_enrollments(env, students)
        groups = {}
        for student, payable, paid, pending in rows:
            enrollment = enrollments.get(student.id)
            course = enrollment.course_id if enrollment else env['op.course']
            batch = enrollment.batch_id if enrollment and group_by == 'section' else env['op.batch']
            group = groups.setdefault((course.id, batch.id), {
                'class': ref(course), 'section': ref(batch),
                'students': 0, 'payable': 0.0, 'paid': 0.0, 'pending': 0.0, 'overdue': 0.0,
            })
            group['students'] += 1
            group['payable'] += payable
            group['paid'] += paid
            group['pending'] += pending
            group['overdue'] += overdue.get(student, 0.0)
        items = [dict(
            {'class': g['class'], 'section': g['section'], 'students': g['students']},
            **_money(g['payable'], g['paid'], g['pending']),
            overdue_amount=g['overdue'],
        ) for g in groups.values()]
        # Classes by name, sections within them; students with no running
        # enrollment ("class": null) last.
        items.sort(key=lambda i: (i['class'] is None, (i['class'] or {}).get('name') or '',
                                  (i['section'] or {}).get('name') or ''))
        return api_response({
            'group_by': group_by,
            'items': items,
            'summary': dict(
                _money(sum(g['payable'] for g in groups.values()), sum(g['paid'] for g in groups.values()),
                       sum(g['pending'] for g in groups.values())),
                overdue_amount=sum(g['overdue'] for g in groups.values()),
                students=len(rows),
                currency=env.company.currency_id.name,
            ),
        })

    @http.route('/api/v1/admin/fees/defaulters', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def defaulters(self, min_days=None, sort=None, **kwargs):
        """One row per student with an overdue balance: amount, oldest due
        date, most days overdue and the parents to call. ?min_days= keeps
        lines at least that late; takes the /admin/fees filters."""
        env = request.env
        if not _allowed(env.user, GROUPS):
            return _forbidden()
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        order, error = parse_sort(sort, DEFAULTER_SORTS, 'overdue_amount desc')
        if error:
            return error
        domain, error = _fee_domain(env, kwargs)
        if error:
            return error
        domain &= OVERDUE
        if min_days:
            min_days, error = parse_int(min_days, 'min_days')
            if error:
                return error
            domain &= Domain('days_overdue', '>=', min_days)
        rows = env['op.student.fees.details'].sudo()._read_group(
            domain, ['student_id'], ['amount_pending:sum', 'date:min', 'days_overdue:max', '__count'])
        sort_keys = {
            'overdue_amount': lambda r: r[1],
            'days_overdue': lambda r: r[3],
            'oldest_due_date': lambda r: r[2],
            'student': lambda r: r[0].name or '',
        }
        rows.sort(key=sort_keys[order[0]], reverse=order[1] == 'desc')
        page = rows[offset:offset + limit]
        students = env['op.student'].sudo().browse([row[0].id for row in page])
        enrollments = running_enrollments(env, students)
        parents = env['op.parent'].sudo().search([('student_ids', 'in', students.ids)])
        items = []
        for student, amount, oldest, days, count in page:
            enrollment = enrollments.get(student.id)
            items.append({
                'student': _student_ref(student),
                'class': ref(enrollment.course_id) if enrollment else None,
                'section': ref(enrollment.batch_id) if enrollment else None,
                'overdue_amount': amount,
                'overdue_lines': count,
                'oldest_due_date': date_str(oldest),
                'days_overdue': days,
                'parents': [{
                    'id': parent.id,
                    'name': parent.name.name,
                    'relationship': parent.relationship_id.name or None,
                    'mobile': parent.mobile or None,
                    'email': parent.email or None,
                } for parent in parents.filtered(lambda p: student in p.student_ids)],
            })
        return api_response({
            'items': items,
            'summary': {
                'students': len(rows),
                'overdue_amount': sum(row[1] for row in rows),
                'currency': env.company.currency_id.name,
            },
        }, meta={'total': len(rows), 'limit': limit, 'offset': offset})

    # -- fee categories -----------------------------------------------------------

    def _category_vals(self, payload):
        env = request.env
        vals = {}
        if 'name' in payload:
            if not payload['name']:
                return None, api_error('name cannot be empty.', status=400, code='missing_name')
            vals['name'] = payload['name']
        if 'code' in payload:
            vals['code'] = payload['code'] or False
        if 'product_id' in payload:
            product, error = resolve_record(env, 'product.product', payload['product_id'], 'product_id')
            if error:
                return None, error
            if not product:
                return None, api_error('product_id cannot be empty.', status=400, code='missing_product_id')
            vals['product_id'] = product.id
        if 'default_frequency' in payload:
            error = check_selection(env['bxi.fee.category'], 'default_frequency', payload['default_frequency'])
            if error:
                return None, error
            vals['default_frequency'] = payload['default_frequency']
        if 'sequence' in payload:
            vals['sequence'], error = parse_int(payload['sequence'], 'sequence')
            if error:
                return None, error
        for key in ('is_refundable', 'active'):
            if key in payload:
                vals[key] = bool(payload[key])
        return vals, None

    def _get_category(self, category_id):
        category = request.env['bxi.fee.category'].sudo().with_context(active_test=False).browse(category_id)
        if not category.exists():
            return None, api_error('Fee category not found.', status=404, code='not_found')
        return category, None

    @http.route('/api/v1/admin/fee-categories', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_categories(self, q=None, active='1', **kwargs):
        """Fee categories (?active=0 archived, all both), each with how
        many fee structures use it."""
        env = request.env
        if not _allowed(env.user, GROUPS):
            return _forbidden()
        domain = Domain.TRUE if active == 'all' else Domain('active', '=', active not in ('0', 'false'))
        if q:
            domain &= Domain('name', 'ilike', q) | Domain('code', 'ilike', q)
        categories = env['bxi.fee.category'].sudo().with_context(active_test=False).search(domain)
        usage = dict(env['bxi.fee.structure.category.line'].sudo()._read_group(
            [('category_id', 'in', categories.ids)], ['category_id'], ['structure_id:count_distinct']))
        return api_response({'items': [
            dict(_category_dict(c), structure_count=usage.get(c, 0)) for c in categories
        ]}, meta={'total': len(categories)})

    @http.route('/api/v1/admin/fee-categories', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_category(self, **kwargs):
        """{"name", "product_id", "code"?, "default_frequency"?,
        "is_refundable"?, "sequence"?}. The product carries the income
        account the category's fees are booked to (see the staff-only
        service-products master)."""
        if not _allowed(request.env.user, GROUPS):
            return _forbidden()
        payload = request.get_json_data() or {}
        for required in ('name', 'product_id'):
            if not payload.get(required):
                return api_error(f'{required} is required.', status=400, code=f'missing_{required}')
        vals, error = self._category_vals(payload)
        if error:
            return error
        category, error = atomic(lambda: request.env['bxi.fee.category'].sudo().create(vals))
        if error:
            return error
        return api_response(_category_dict(category), status=201)

    @http.route('/api/v1/admin/fee-categories/<int:category_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_category(self, category_id, **kwargs):
        """Any create field, plus "active": false to archive."""
        if not _allowed(request.env.user, GROUPS):
            return _forbidden()
        category, error = self._get_category(category_id)
        if error:
            return error
        vals, error = self._category_vals(request.get_json_data() or {})
        if error:
            return error
        _, error = atomic(lambda: category.write(vals))
        if error:
            return error
        return api_response(_category_dict(category))
