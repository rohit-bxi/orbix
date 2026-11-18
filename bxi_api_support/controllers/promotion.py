# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Year-end promotion: move a whole section (or some of its students) to
another section, usually the next class, or mark them as passed out.
Each student's current enrolment is finished and a running one opened in
the new section, so attendance and results keep their history - the same
rule as the single-student transfer on /students/<id>/update.

Overdue fees are reported as a warning only; they never block a move."""
from odoo import http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

from ..models.people_service import MANAGER_GROUPS
from .common import atomic, ref, resolve_record, resolve_records, running_enrollments, json_body

MODES = ('promote', 'graduate')
ROLL_MODES = ('keep', 'renumber')
OVERDUE = Domain('days_overdue', '>', 0) & Domain('amount_pending', '>', 0)


def _forbidden():
    return api_error('Only the school office can promote students.', status=403, code='forbidden')


def _plan(env, payload):
    """Validate a promotion request and work out each student's move.
    Returns (plan, None) or (None, api_error(...)); a plan is a dict with
    the resolved records and one row per student (blockers per row)."""
    mode = payload.get('mode') or 'promote'
    if mode not in MODES:
        return None, api_error('mode must be one of promote, graduate.', status=400, code='invalid_mode')
    roll_mode = payload.get('roll_numbers') or 'keep'
    if roll_mode not in ROLL_MODES:
        return None, api_error('roll_numbers must be one of keep, renumber.', status=400, code='invalid_roll_numbers')
    if not payload.get('from_section_id'):
        return None, api_error('from_section_id is required.', status=400, code='missing_from_section_id')
    source, error = resolve_record(env, 'op.batch', payload['from_section_id'], 'from_section_id')
    if error:
        return None, error
    target = env['op.batch']
    if mode == 'promote':
        if not payload.get('to_section_id'):
            return None, api_error('to_section_id is required.', status=400, code='missing_to_section_id')
        target, error = resolve_record(env, 'op.batch', payload['to_section_id'], 'to_section_id')
        if error:
            return None, error
        if target == source:
            return None, api_error('The target section is the current section.', status=400, code='same_section')
    year, error = resolve_record(env, 'op.academic.year', payload.get('academic_year_id'), 'academic_year_id')
    if error:
        return None, error

    enrolments = env['op.student.course'].sudo().search(
        [('batch_id', '=', source.id), ('state', '=', 'running')], order='roll_number, id')
    rows = []
    if payload.get('student_ids'):
        students, error = resolve_records(env, 'op.student', payload['student_ids'], 'student_ids')
        if error:
            return None, error
        current = running_enrollments(env, students)
        for student in students:
            line = current.get(student.id)
            rows.append({'student': student, 'current': line if line and line.batch_id == source else None})
    else:
        rows = [{'student': line.student_id, 'current': line} for line in enrolments]

    overdue = dict((student.id, amount) for student, amount in env['op.student.fees.details'].sudo()._read_group(
        OVERDUE & Domain('student_id', 'in', [r['student'].id for r in rows]), ['student_id'], ['amount_pending:sum']))
    taken = set()
    next_roll = 1
    if target:
        in_target = env['op.student.course'].sudo().search([('batch_id', '=', target.id)])
        taken = {line.roll_number for line in in_target if line.roll_number}
        numeric = [int(n) for n in taken if str(n).isdigit()]
        next_roll = max(numeric or [0]) + 1
    ordered = sorted(rows, key=lambda r: (r['student'].name or '').lower()) if roll_mode == 'renumber' else rows
    for row in ordered:
        student, current = row['student'], row['current']
        row['blocker'] = None
        row['warnings'] = []
        if not current:
            row['blocker'] = 'not_in_section'
        elif target:
            previous = student.course_detail_ids.filtered(lambda l: l.batch_id == target)[:1]
            row['reopen'] = previous
            if previous:
                row['roll_number'] = previous.roll_number
            elif roll_mode == 'renumber':
                while str(next_roll) in taken:
                    next_roll += 1
                row['roll_number'] = str(next_roll)
                next_roll += 1
            else:
                row['roll_number'] = current.roll_number or False
                if not row['roll_number']:
                    row['blocker'] = 'missing_roll_number'
                elif row['roll_number'] in taken:
                    row['blocker'] = 'roll_number_taken'
            if row.get('roll_number') and not row['blocker']:
                taken.add(row['roll_number'])
        if overdue.get(student.id):
            row['warnings'].append({'code': 'fees_overdue', 'amount': overdue[student.id]})
    return {'mode': mode, 'source': source, 'target': target, 'year': year, 'rows': rows}, None


def _row_dict(row):
    current = row['current']
    return {
        'student': ref(row['student']),
        'gr_no': row['student'].gr_no or None,
        'current_roll_number': current.roll_number if current else None,
        'new_roll_number': row.get('roll_number') or None,
        'ok': not row['blocker'],
        'blocker': row['blocker'],
        'warnings': row['warnings'],
    }


def _summary(plan):
    rows = plan['rows']
    return {
        'mode': plan['mode'],
        'from_section': dict(ref(plan['source']), **{'class': ref(plan['source'].course_id)}),
        'to_section': dict(ref(plan['target']), **{'class': ref(plan['target'].course_id)}) if plan['target'] else None,
        'academic_year': ref(plan['year']),
        'students': len(rows),
        'ready': len([r for r in rows if not r['blocker']]),
        'blocked': len([r for r in rows if r['blocker']]),
        'with_overdue_fees': len([r for r in rows if r['warnings']]),
    }


def _move(env, plan, row):
    """Finish the student's enrolment and open (or reopen) the new one."""
    current = row['current']
    current.state = 'finished'
    target = plan['target']
    if not target:
        return
    if row.get('reopen'):
        row['reopen'].write({'state': 'running'})
        return
    same_class = current.course_id == target.course_id
    year = plan['year'] or current.academic_years_id
    env['op.student.course'].sudo().create({
        'student_id': row['student'].id,
        'course_id': target.course_id.id,
        'batch_id': target.id,
        'roll_number': row['roll_number'],
        'state': 'running',
        'academic_years_id': year.id,
        # A new academic year starts its own terms.
        'academic_term_id': current.academic_term_id.id if year == current.academic_years_id else False,
        'subject_ids': [(6, 0, current.subject_ids.ids if same_class else [])],
        'fees_term_id': current.fees_term_id.id if same_class else False,
    })


class BxiApiSupportPromotionController(http.Controller):

    def _allowed(self):
        user = request.env.user
        return any(user.has_group(group) for group in MANAGER_GROUPS)

    @http.route('/api/v1/admin/promotions/preview', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def preview(self, **kwargs):
        """{"from_section_id", "to_section_id" (promote), "mode"?:
        promote|graduate, "academic_year_id"?, "student_ids"? (default: the
        whole section), "roll_numbers"?: keep|renumber} - what would happen,
        without changing anything."""
        if not self._allowed():
            return _forbidden()
        plan, error = _plan(request.env, json_body() or {})
        if error:
            return error
        return api_response({'summary': _summary(plan), 'students': [_row_dict(r) for r in plan['rows']]})

    @http.route('/api/v1/admin/promotions', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def promote(self, **kwargs):
        """Same body as the preview. All students move or none do: a
        blocked student fails the whole request (400 promotion_blocked with
        the preview rows), unless "skip_blocked": true moves the rest."""
        env = request.env
        if not self._allowed():
            return _forbidden()
        payload = json_body() or {}
        plan, error = _plan(env, payload)
        if error:
            return error
        blocked = [r for r in plan['rows'] if r['blocker']]
        if blocked and not payload.get('skip_blocked'):
            return request.make_json_response({
                'success': False,
                'error': {'message': f'{len(blocked)} student(s) cannot be moved.', 'code': 'promotion_blocked'},
                'data': {'summary': _summary(plan), 'students': [_row_dict(r) for r in plan['rows']]},
            }, status=400)
        ready = [r for r in plan['rows'] if not r['blocker']]
        if not ready:
            return api_error('No students to move.', status=400, code='no_students')

        def run():
            for row in ready:
                _move(env, plan, row)

        _, error = atomic(run)
        if error:
            return error
        return api_response({
            'summary': dict(_summary(plan), moved=len(ready), skipped=len(blocked)),
            'students': [_row_dict(r) for r in plan['rows']],
        })
