# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth

ROLE_TAG_XMLIDS = {
    'student': 'bxi_teacher_support.tag_role_student',
    'parent': 'bxi_teacher_support.tag_role_parent',
    'teacher': 'bxi_teacher_support.tag_role_teacher',
}


def _resolve_role(env, user):
    """Resolve the logged-in user to a (role, partner) pair.

    Checks op.student / op.parent / op.faculty in turn since a single
    res.users can only be linked to one of them in practice.
    """
    student = env['op.student'].sudo().search([('user_id', '=', user.id)], limit=1)
    if student:
        return 'student', student.partner_id

    parent = env['op.parent'].sudo().search([('user_id', '=', user.id)], limit=1)
    if parent:
        return 'parent', parent.name

    faculty = env['op.faculty'].sudo().search([('user_id', '=', user.id)], limit=1)
    if faculty:
        return 'teacher', faculty.partner_id

    return None, user.partner_id


class BxiTeacherSupportController(http.Controller):

    @http.route('/api/v1/support/faqs', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_faqs(self, category=None, audience=None, **kwargs):
        domain = [('active', '=', True)]
        if category:
            domain.append(('category', '=', category))
        if audience:
            domain.append(('audience', 'in', ['all', audience]))
        faqs = request.env['bxi.faq'].sudo().search(domain, order='sequence, id')
        return api_response({
            'faqs': [{
                'id': f.id, 'question': f.question, 'answer': f.answer,
                'category': f.category, 'audience': f.audience,
            } for f in faqs],
        })

    @http.route('/api/v1/support/tickets', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_tickets(self, **kwargs):
        role, partner = _resolve_role(request.env, request.env.user)
        tickets = request.env['helpdesk.ticket'].sudo().search([
            ('partner_id', '=', partner.id),
        ], order='create_date desc')
        return api_response({
            'tickets': [{
                'id': t.id,
                'name': t.name,
                'stage': t.stage_id.display_name,
                'tags': t.tag_ids.mapped('name'),
                'create_date': t.create_date.isoformat(),
            } for t in tickets],
        })

    @http.route('/api/v1/support/tickets/<int:ticket_id>', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_ticket(self, ticket_id, **kwargs):
        role, partner = _resolve_role(request.env, request.env.user)
        ticket = request.env['helpdesk.ticket'].sudo().search([
            ('id', '=', ticket_id), ('partner_id', '=', partner.id),
        ], limit=1)
        if not ticket:
            return api_error('Ticket not found.', status=404, code='ticket_not_found')

        messages = ticket.message_ids.filtered(lambda m: m.message_type in ('comment', 'email')).sorted('date')
        return api_response({
            'id': ticket.id,
            'name': ticket.name,
            'description': ticket.description,
            'stage': ticket.stage_id.display_name,
            'tags': ticket.tag_ids.mapped('name'),
            'create_date': ticket.create_date.isoformat(),
            'messages': [{
                'id': m.id,
                'author': m.author_id.display_name,
                'body': m.body,
                'date': m.date.isoformat() if m.date else None,
            } for m in messages],
        })

    @http.route('/api/v1/support/tickets', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def create_ticket(self, **kwargs):
        payload = request.get_json_data()
        subject = (payload.get('subject') or '').strip()
        if not subject:
            return api_error('subject is required.', status=400, code='missing_subject')

        role, partner = _resolve_role(request.env, request.env.user)

        team = request.env.ref('bxi_teacher_support.helpdesk_team_teacher_support', raise_if_not_found=False)
        vals = {
            'name': subject,
            'description': payload.get('description') or '',
            'partner_id': partner.id,
        }
        if team:
            vals['team_id'] = team.id

        tag_ids = set()
        category_tag_id = payload.get('category_tag_id')
        if category_tag_id:
            tag_ids.add(int(category_tag_id))
        if role:
            role_tag = request.env.ref(ROLE_TAG_XMLIDS[role], raise_if_not_found=False)
            if role_tag:
                tag_ids.add(role_tag.id)
        if tag_ids:
            vals['tag_ids'] = [(6, 0, list(tag_ids))]

        ticket = request.env['helpdesk.ticket'].sudo().create(vals)
        return api_response({
            'id': ticket.id, 'name': ticket.name, 'stage': ticket.stage_id.display_name, 'role': role,
        })

    @http.route('/api/v1/support/tickets/<int:ticket_id>/reply', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def reply_ticket(self, ticket_id, **kwargs):
        payload = request.get_json_data()
        body = (payload.get('body') or '').strip()
        if not body:
            return api_error('body is required.', status=400, code='missing_body')

        role, partner = _resolve_role(request.env, request.env.user)
        ticket = request.env['helpdesk.ticket'].sudo().search([
            ('id', '=', ticket_id), ('partner_id', '=', partner.id),
        ], limit=1)
        if not ticket:
            return api_error('Ticket not found.', status=404, code='ticket_not_found')

        message = ticket.message_post(body=body, author_id=partner.id, message_type='comment')
        return api_response({'id': message.id, 'body': message.body})
