# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, require_auth


def _thread_participant_role(env, thread):
    user = env.user
    if thread.parent_id.user_id.id == user.id:
        return 'parent'
    if thread.teacher_id.user_id.id == user.id:
        return 'teacher'
    return None


def _resolve_thread(env, thread_id):
    thread = env['bxi.message.thread'].sudo().browse(int(thread_id))
    if not thread.exists():
        return None, api_error('Thread not found.', status=404, code='not_found')
    if not _thread_participant_role(env, thread):
        return None, api_error('Not authorized for this thread.', status=403, code='forbidden')
    return thread, None


class BxiParentTeacherMessagingController(http.Controller):

    @http.route('/api/v1/messages/threads', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_threads(self, **kwargs):
        user = request.env.user
        threads = request.env['bxi.message.thread'].sudo().search([
            '|', ('parent_id.user_id', '=', user.id), ('teacher_id.user_id', '=', user.id),
        ], order='last_message_at desc')

        result = []
        for thread in threads:
            last_message = thread.message_ids[-1:] if thread.message_ids else thread.message_ids
            result.append({
                'id': thread.id,
                'student': thread.student_id.display_name,
                'parent': thread.parent_id.display_name,
                'teacher': thread.teacher_id.display_name,
                'last_message': last_message.body if last_message else None,
                'last_message_at': thread.last_message_at.isoformat() if thread.last_message_at else None,
                'unread_count': thread._unread_count_for(user),
            })
        return api_response({'threads': result})

    @http.route('/api/v1/messages/threads', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def start_thread(self, **kwargs):
        payload = request.get_json_data()
        student_id = payload.get('student_id')
        teacher_id = payload.get('teacher_id')
        if not student_id or not teacher_id:
            return api_error('student_id and teacher_id are required.', status=400, code='missing_fields')

        user = request.env.user
        parent = request.env['op.parent'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not parent:
            return api_error('No parent record is linked to this account.', status=403, code='not_a_parent')
        student = request.env['op.student'].sudo().browse(int(student_id))
        teacher = request.env['op.faculty'].sudo().browse(int(teacher_id))
        if not student.exists() or not teacher.exists():
            return api_error('Student or teacher not found.', status=404, code='not_found')
        if student.id not in parent.student_ids.ids:
            return api_error('This student is not linked to your account.', status=403, code='forbidden')

        thread = request.env['bxi.message.thread']._get_or_create(student, parent, teacher)
        return api_response({'thread_id': thread.id})

    @http.route('/api/v1/messages/threads/<int:thread_id>/messages', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def list_messages(self, thread_id, **kwargs):
        thread, error = _resolve_thread(request.env, thread_id)
        if error:
            return error
        return api_response({
            'messages': [{
                'id': m.id,
                'sender_user_id': m.sender_user_id.id,
                'body': m.body,
                'create_date': m.create_date.isoformat(),
                'read_at': m.read_at.isoformat() if m.read_at else None,
            } for m in thread.message_ids],
        })

    @http.route('/api/v1/messages/threads/<int:thread_id>/messages', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def send_message(self, thread_id, **kwargs):
        thread, error = _resolve_thread(request.env, thread_id)
        if error:
            return error
        payload = request.get_json_data()
        body = (payload.get('body') or '').strip()
        if not body:
            return api_error('body is required.', status=400, code='missing_body')

        message = request.env['bxi.message'].sudo().create({
            'thread_id': thread.id, 'sender_user_id': request.env.user.id, 'body': body,
        })
        return api_response({'id': message.id, 'create_date': message.create_date.isoformat()})

    @http.route('/api/v1/messages/threads/<int:thread_id>/read', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def mark_read(self, thread_id, **kwargs):
        thread, error = _resolve_thread(request.env, thread_id)
        if error:
            return error
        thread._mark_read_for(request.env.user)
        return api_response({'marked_read': True})
