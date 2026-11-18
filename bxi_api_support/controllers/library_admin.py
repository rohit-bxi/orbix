# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Library back office (openeducat_library) for librarians: adding and
editing catalogue entries and their physical copies, library cards, late
fines (invoice, then settle or waive) and book purchase requests.
Circulation (issue/return/reservations) stays in library.py."""
from odoo import Command, fields, http
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth

from .common import (
    atomic, check_selection, date_str, parse_pagination, ref, resolve_record, resolve_records, school_context, json_body,
)
from .library import _is_library_staff, _loan_dict, _media_dict

FINE_PRODUCT_CODE = 'LIB-FINE'
PAID_STATES = ('paid', 'in_payment')
PURCHASE_ACTIONS = {'accept': 'act_accept', 'reject': 'act_reject'}


def _forbidden(message='Only library staff can do this.'):
    return api_error(message, status=403, code='forbidden')


def _named_records(env, model, ids_value, names_value, field_name):
    """Records from an id list and/or a list of names (missing names are
    created, so the office can type an author it hasn't added yet).
    Returns (records, None) or (None, api_error(...))."""
    records = env[model].sudo()
    if ids_value:
        records, error = resolve_records(env, model, ids_value, field_name)
        if error:
            return None, error
    if names_value:
        if not isinstance(names_value, list):
            return None, api_error(f'{field_name} names must be a list.', status=400, code=f'invalid_{field_name}')
        Model = env[model].sudo()
        for name in names_value:
            name = str(name or '').strip()
            if not name:
                continue
            records |= Model.search([('name', '=ilike', name)], limit=1) or Model.create({'name': name})
    return records, None


def _media_vals(env, payload, media=None):
    """(vals, error) for an op.media create/write."""
    vals = {}
    if 'title' in payload:
        if not payload['title']:
            return None, api_error('title cannot be empty.', status=400, code='missing_title')
        vals['name'] = payload['title']
    for key, model, names_key in (('author_ids', 'op.author', 'authors'),
                                  ('publisher_ids', 'op.publisher', 'publishers')):
        if key in payload or names_key in payload:
            records, error = _named_records(env, model, payload.get(key), payload.get(names_key), key)
            if error:
                return None, error
            if not records:
                return None, api_error(f'At least one of {key} or {names_key} is required.', status=400,
                                       code=f'missing_{key}')
            vals[key] = [Command.set(records.ids)]
    for key, model, field in (('genre_id', 'op.media.genre', 'genre_id'),
                              ('media_type_id', 'op.media.type', 'media_type_id')):
        if key in payload:
            record, error = resolve_record(env, model, payload[key], key)
            if error:
                return None, error
            if key == 'genre_id' and not record:
                return None, api_error('genre_id is required.', status=400, code='missing_genre_id')
            vals[field] = record.id or False
    for key, model, field in (('class_ids', 'op.course', 'course_ids'), ('subject_ids', 'op.subject', 'subject_ids')):
        if key in payload:
            records, error = resolve_records(env, model, payload[key], key)
            if error:
                return None, error
            vals[field] = [Command.set(records.ids)]
    for key in ('isbn', 'edition', 'description', 'shelf_location', 'internal_code', 'allocation'):
        if key in payload:
            vals[key] = payload[key] or False
    for key, field in (('publish_year', 'publish_year'), ('pages', 'number_of_pages'),
                       ('total_copies', 'total_copies')):
        if key in payload:
            value, error = parse_int(payload[key] or 0, key)
            if error:
                return None, error
            if value < 0:
                return None, api_error(f'{key} cannot be negative.', status=400, code=f'invalid_{key}')
            vals[field] = value
    if payload.get('language'):
        error = check_selection(env['op.media'], 'language', payload['language'])
        if error:
            return None, error
        vals['language'] = payload['language']
    Media = env['op.media'].sudo().with_context(active_test=False)
    for key in ('isbn', 'internal_code'):
        if vals.get(key):
            domain = [(key, '=', vals[key])] + ([('id', '!=', media.id)] if media else [])
            if Media.search_count(domain):
                return None, api_error(f"{key} '{vals[key]}' is already used by another book.", status=400,
                                       code=f'duplicate_{key}')
    return vals, None


def _unit_dict(unit):
    return {'id': unit.id, 'name': unit.name, 'barcode': unit.barcode or None, 'state': unit.state,
            'active': unit.active}


def _card_dict(card):
    return {
        'id': card.id,
        'number': card.number,
        'type': card.type,
        'student': ref(card.student_id),
        'teacher': ref(card.faculty_id),
        'card_type': {'id': card.library_card_type_id.id, 'name': card.library_card_type_id.name,
                      'books_allowed': card.library_card_type_id.allow_media,
                      'loan_days': card.library_card_type_id.duration,
                      'fine_per_day': card.library_card_type_id.penalty_amt_per_day},
        'issue_date': date_str(card.issue_date),
        'active': card.active,
    }


def _fine_dict(movement):
    invoice = movement.invoice_id
    return dict(_loan_dict(movement), **{
        'borrower': ref(movement.student_id or movement.faculty_id),
        'borrower_type': movement.type,
        'fine_settled': movement.state == 'return_done',
        'invoice': {
            'id': invoice.id, 'name': invoice.name, 'amount': invoice.amount_total,
            'amount_due': invoice.amount_residual, 'payment_state': invoice.payment_state,
        } if invoice else None,
    })


def _purchase_dict(purchase):
    return {
        'id': purchase.id,
        'request_no': purchase.request_no,
        'title': purchase.name,
        'author': purchase.author,
        'edition': purchase.edition or None,
        'publisher': purchase.publisher or None,
        'class': ref(purchase.course_ids),
        'subject': ref(purchase.subject_ids),
        'media_type': ref(purchase.media_type_id),
        'requested_by': ref(purchase.requested_id),
        'request_date': date_str(purchase.request_date),
        'state': purchase.state,
    }


def _fine_product(env):
    """The service product a late fine is invoiced as: openeducat's own
    (demo data only), else one this API keeps under code LIB-FINE."""
    product = env.ref('openeducat_library.op_product_7', raise_if_not_found=False)
    if product:
        return product.sudo()
    Product = env['product.product'].sudo().with_context(active_test=False)
    return Product.search([('default_code', '=', FINE_PRODUCT_CODE)], limit=1) or Product.create({
        'name': 'Library Fine', 'default_code': FINE_PRODUCT_CODE, 'type': 'service', 'sale_ok': True,
        'purchase_ok': False, 'list_price': 0.0,
    })


class BxiApiSupportLibraryAdminController(http.Controller):

    def _media(self, media_id):
        media = request.env['op.media'].sudo().with_context(active_test=False).browse(media_id)
        if not media.exists():
            return None, api_error('Book not found.', status=404, code='not_found')
        return media, None

    def _loan(self, movement_id):
        movement = request.env['op.media.movement'].sudo().browse(movement_id)
        if not movement.exists():
            return None, api_error('Loan not found.', status=404, code='not_found')
        return movement, None

    # -- catalogue --------------------------------------------------------------

    @http.route('/api/v1/library/catalog', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_media(self, **kwargs):
        """{"title", "genre_id", "author_ids" and/or "authors" (names),
        "publisher_ids" and/or "publishers" (names), "isbn"?, "edition"?,
        "media_type_id"?, "language"?, "publish_year"?, "pages"?,
        "shelf_location"?, "internal_code"?, "description"?, "class_ids"?,
        "subject_ids"?, "total_copies"? (copies are created to match)}."""
        env = request.env
        if not _is_library_staff(env.user):
            return _forbidden()
        payload = json_body() or {}
        if not payload.get('title'):
            return api_error('title is required.', status=400, code='missing_title')
        if not payload.get('genre_id'):
            return api_error('genre_id is required.', status=400, code='missing_genre_id')
        for key, names_key in (('author_ids', 'authors'), ('publisher_ids', 'publishers')):
            if not payload.get(key) and not payload.get(names_key):
                return api_error(f'{key} or {names_key} is required.', status=400, code=f'missing_{key}')
        vals, error = _media_vals(env, payload)
        if error:
            return error
        media, error = atomic(lambda: env['op.media'].sudo().create(vals))
        if error:
            return error
        return api_response(dict(_media_dict(media, detail=True), copies=[_unit_dict(u) for u in media.unit_ids]),
                            status=201)

    @http.route('/api/v1/library/catalog/<int:media_id>/update', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def update_media(self, media_id, **kwargs):
        """Any create field, plus "active". Lowering total_copies archives
        copies that are on the shelf; it fails while too many are out."""
        env = request.env
        if not _is_library_staff(env.user):
            return _forbidden()
        media, error = self._media(media_id)
        if error:
            return error
        payload = json_body() or {}
        vals, error = _media_vals(env, payload, media)
        if error:
            return error
        if 'active' in payload:
            vals['active'] = bool(payload['active'])
        # The model syncs copies against the active ones only.
        _, error = atomic(lambda: media.with_context(active_test=True).write(vals))
        if error:
            return error
        return api_response(dict(_media_dict(media, detail=True), copies=[_unit_dict(u) for u in media.unit_ids]))

    @http.route('/api/v1/library/catalog/<int:media_id>/units', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_units(self, media_id, **kwargs):
        if not _is_library_staff(request.env.user):
            return _forbidden()
        media, error = self._media(media_id)
        if error:
            return error
        units = media.with_context(active_test=False).unit_ids
        return api_response({'media': {'id': media.id, 'title': media.name},
                             'copies': [_unit_dict(u) for u in units.sorted('id')]})

    @http.route('/api/v1/library/catalog/<int:media_id>/units', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def add_units(self, media_id, **kwargs):
        """{"count"? (default 1), "barcodes"? [...]} - add physical copies.
        With barcodes, one copy per barcode carries that label; otherwise
        each copy gets the next number from the library sequence."""
        env = request.env
        if not _is_library_staff(env.user):
            return _forbidden()
        media, error = self._media(media_id)
        if error:
            return error
        payload = json_body() or {}
        barcodes = payload.get('barcodes') or []
        if not isinstance(barcodes, list):
            return api_error('barcodes must be a list.', status=400, code='invalid_barcodes')
        barcodes = [str(b).strip() for b in barcodes if str(b or '').strip()]
        if len(set(barcodes)) != len(barcodes):
            return api_error('barcodes contains duplicates.', status=400, code='duplicate_barcode')
        count, error = parse_int(payload.get('count') or len(barcodes) or 1, 'count')
        if error:
            return error
        if barcodes and count != len(barcodes):
            return api_error('count must match the number of barcodes.', status=400, code='invalid_count')
        if not 1 <= count <= 500:
            return api_error('count must be between 1 and 500.', status=400, code='invalid_count')
        Unit = env['op.media.unit'].sudo().with_context(active_test=False)
        taken = Unit.search([('barcode', 'in', barcodes)]).mapped('barcode') if barcodes else []
        if taken:
            return api_error('Barcode already used: %s.' % ', '.join(taken), status=400, code='duplicate_barcode')

        def add():
            existing = len(media.unit_ids)
            units = Unit.create([{'media_id': media.id, 'name': f'{media.name} - Copy {existing + i + 1}'}
                                 for i in range(count)])
            for unit, barcode in zip(units, barcodes):
                unit.barcode = barcode  # the model's create always numbers from its sequence
            # Keep the copy counter in step with the active copies, so a later
            # total_copies edit works from here (archived copies don't count).
            active_media = media.with_context(active_test=True)
            active_media.invalidate_recordset(['unit_ids'])
            active_media.write({'total_copies': len(active_media.unit_ids)})
            return units

        units, error = atomic(add)
        if error:
            return error
        return api_response({'media': _media_dict(media), 'added': [_unit_dict(u) for u in units]}, status=201)

    # -- library cards -----------------------------------------------------------

    @http.route('/api/v1/library/cards', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_cards(self, student_id=None, teacher_id=None, q=None, **kwargs):
        if not _is_library_staff(request.env.user):
            return _forbidden()
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = Domain.TRUE
        for param, value, field in (('student_id', student_id, 'student_id'), ('teacher_id', teacher_id, 'faculty_id')):
            if value:
                value, error = parse_int(value, param)
                if error:
                    return error
                domain &= Domain(field, '=', value)
        if q:
            domain &= Domain('number', 'ilike', q) | Domain('partner_id.name', 'ilike', q)
        Card = request.env['op.library.card'].sudo()
        cards = Card.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response({'cards': [_card_dict(c) for c in cards]},
                            meta={'total': Card.search_count(domain), 'limit': limit, 'offset': offset})

    @http.route('/api/v1/library/cards', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_card(self, **kwargs):
        """{"student_id" or "teacher_id", "card_type_id", "issue_date"?} -
        one active card per borrower."""
        env = request.env
        if not _is_library_staff(env.user):
            return _forbidden()
        payload = json_body() or {}
        if bool(payload.get('student_id')) == bool(payload.get('teacher_id')):
            return api_error('Send either student_id or teacher_id.', status=400, code='missing_borrower')
        if payload.get('student_id'):
            borrower, error = resolve_record(env, 'op.student', payload['student_id'], 'student_id')
            card_type, field = 'student', 'student_id'
        else:
            borrower, error = resolve_record(env, 'op.faculty', payload['teacher_id'], 'teacher_id')
            card_type, field = 'faculty', 'faculty_id'
        if error:
            return error
        if not payload.get('card_type_id'):
            return api_error('card_type_id is required.', status=400, code='missing_card_type_id')
        kind, error = resolve_record(env, 'op.library.card.type', payload['card_type_id'], 'card_type_id')
        if error:
            return error
        if env['op.library.card'].sudo().search_count([(field, '=', borrower.id)]):
            return api_error('This borrower already has a library card.', status=409, code='card_exists')
        vals = {'type': card_type, field: borrower.id, 'partner_id': borrower.partner_id.id,
                'library_card_type_id': kind.id}
        if payload.get('issue_date'):
            vals['issue_date'] = fields.Date.to_date(payload['issue_date'])
        card, error = atomic(lambda: env['op.library.card'].sudo().create(vals))
        if error:
            return error
        return api_response(_card_dict(card), status=201)

    # -- fines -------------------------------------------------------------------

    @http.route('/api/v1/library/fines', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_fines(self, status='unsettled', student_id=None, **kwargs):
        """Returned loans that carry a late fine. ?status=unsettled
        (default), settled or all."""
        if not _is_library_staff(request.env.user):
            return _forbidden()
        if status not in ('unsettled', 'settled', 'all'):
            return api_error('status must be one of unsettled, settled, all.', status=400, code='invalid_status')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = Domain('penalty', '>', 0)
        if status == 'unsettled':
            domain &= Domain('state', '=', 'return')
        elif status == 'settled':
            domain &= Domain('state', '=', 'return_done')
        else:
            domain &= Domain('state', 'in', ('return', 'return_done'))
        if student_id:
            student_id, error = parse_int(student_id, 'student_id')
            if error:
                return error
            domain &= Domain('student_id', '=', student_id)
        Movement = request.env['op.media.movement'].sudo()
        loans = Movement.search(domain, limit=limit, offset=offset, order='actual_return_date desc, id desc')
        all_unsettled = Movement.search(Domain('penalty', '>', 0) & Domain('state', '=', 'return'))
        return api_response({
            'fines': [_fine_dict(m) for m in loans],
            'summary': {'unsettled_count': len(all_unsettled),
                        'unsettled_amount': sum(all_unsettled.mapped('penalty')),
                        'currency': request.env.company.currency_id.name},
        }, meta={'total': Movement.search_count(domain), 'limit': limit, 'offset': offset})

    @http.route('/api/v1/library/loans/<int:movement_id>/fine-invoice', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def fine_invoice(self, movement_id, **kwargs):
        """Raise and post a customer invoice for a returned loan's fine, to
        the student (or teacher). Pay it like any other invoice, then call
        settle-fine."""
        env = request.env
        if not _is_library_staff(env.user):
            return _forbidden()
        movement, error = self._loan(movement_id)
        if error:
            return error
        if movement.state != 'return' or movement.penalty <= 0:
            return api_error('Only a returned loan with an unsettled fine can be invoiced.', status=400,
                             code='no_fine')
        if movement.invoice_id and movement.invoice_id.state != 'cancel':
            return api_error('This fine was already invoiced.', status=409, code='already_invoiced')
        partner = (movement.student_id or movement.faculty_id).partner_id or movement.library_card_id.partner_id
        if not partner:
            return api_error('The borrower has no contact to invoice.', status=400, code='no_partner')
        product = _fine_product(env)

        def create():
            invoice = env['account.move'].sudo().create({
                'move_type': 'out_invoice',
                'partner_id': partner.id,
                'invoice_date': fields.Date.context_today(movement),
                'invoice_line_ids': [Command.create({
                    'product_id': product.id,
                    'name': f'Library fine - {movement.media_id.name}',
                    'quantity': 1.0,
                    'price_unit': movement.penalty,
                    'tax_ids': [Command.clear()],
                })],
            })
            invoice.action_post()
            movement.invoice_id = invoice
            return invoice

        _, error = atomic(create)
        if error:
            return error
        return api_response(_fine_dict(movement), status=201)

    @http.route('/api/v1/library/loans/<int:movement_id>/settle-fine', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def settle_fine(self, movement_id, **kwargs):
        """{"waive"?: true, "note"?} - close a returned loan's fine. Without
        waive, its invoice must be paid. Waiving cancels an unpaid invoice."""
        env = request.env
        if not _is_library_staff(env.user):
            return _forbidden()
        movement, error = self._loan(movement_id)
        if error:
            return error
        if movement.state != 'return':
            return api_error('This loan has no unsettled fine.', status=400, code='no_fine')
        payload = json_body()
        payload = payload or {}
        invoice = movement.invoice_id
        waive = bool(payload.get('waive'))
        if not waive and not (invoice and invoice.payment_state in PAID_STATES):
            return api_error('The fine is not paid yet. Pay its invoice first, or waive it.', status=400,
                             code='fine_unpaid')

        def settle():
            if waive and invoice and invoice.state == 'posted' and invoice.payment_state not in PAID_STATES:
                invoice.button_draft()
                invoice.button_cancel()
            movement.state = 'return_done'
            note = 'Library fine waived' if waive else 'Library fine paid'
            if payload.get('note'):
                note = f"{note}: {payload['note']}"
            movement.message_post(body=note, author_id=env.user.partner_id.id)

        _, error = atomic(settle)
        if error:
            return error
        return api_response(_fine_dict(movement))

    # -- purchase requests -------------------------------------------------------

    @http.route('/api/v1/library/purchase-requests', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_purchases(self, state=None, **kwargs):
        """Library staff see every request; a teacher sees their own."""
        env = request.env
        staff = _is_library_staff(env.user)
        if not staff and not school_context(env)['faculty']:
            return _forbidden('Only teachers and library staff can see book purchase requests.')
        limit, offset, error = parse_pagination(kwargs)
        if error:
            return error
        domain = Domain.TRUE if staff else Domain('requested_id', '=', env.user.partner_id.id)
        if state:
            error = check_selection(env['op.media.purchase'], 'state', state)
            if error:
                return error
            domain &= Domain('state', '=', state)
        Purchase = env['op.media.purchase'].sudo()
        purchases = Purchase.search(domain, limit=limit, offset=offset, order='id desc')
        return api_response({'requests': [_purchase_dict(p) for p in purchases]},
                            meta={'total': Purchase.search_count(domain), 'limit': limit, 'offset': offset})

    @http.route('/api/v1/library/purchase-requests', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_purchase(self, **kwargs):
        """{"title", "author", "class_id", "subject_id", "edition"?,
        "publisher"?, "media_type_id"?} - a teacher (or librarian) asks the
        library to buy a book. It is submitted straight away."""
        env = request.env
        if not _is_library_staff(env.user) and not school_context(env)['faculty']:
            return _forbidden('Only teachers and library staff can request book purchases.')
        payload = json_body() or {}
        for key in ('title', 'author', 'class_id', 'subject_id'):
            if not payload.get(key):
                return api_error(f'{key} is required.', status=400, code=f'missing_{key}')
        vals = {'name': payload['title'], 'author': payload['author'], 'edition': payload.get('edition') or False,
                'publisher': payload.get('publisher') or False, 'requested_id': env.user.partner_id.id}
        for key, model, field in (('class_id', 'op.course', 'course_ids'), ('subject_id', 'op.subject', 'subject_ids'),
                                  ('media_type_id', 'op.media.type', 'media_type_id')):
            record, error = resolve_record(env, model, payload.get(key), key)
            if error:
                return error
            vals[field] = record.id or False

        def create():
            purchase = env['op.media.purchase'].sudo().create(vals)
            purchase.act_requested()
            return purchase

        purchase, error = atomic(create)
        if error:
            return error
        return api_response(_purchase_dict(purchase), status=201)

    @http.route('/api/v1/library/purchase-requests/<int:purchase_id>/<any("accept", "reject"):action>',
                type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def review_purchase(self, purchase_id, action, **kwargs):
        if not _is_library_staff(request.env.user):
            return _forbidden('Only library staff can review purchase requests.')
        purchase = request.env['op.media.purchase'].sudo().browse(purchase_id)
        if not purchase.exists():
            return api_error('Purchase request not found.', status=404, code='not_found')
        if purchase.state != 'request':
            return api_error('Only a submitted request can be reviewed.', status=400, code='invalid_transition')
        _, error = atomic(lambda: getattr(purchase, PURCHASE_ACTIONS[action])())
        if error:
            return error
        return api_response(_purchase_dict(purchase))
