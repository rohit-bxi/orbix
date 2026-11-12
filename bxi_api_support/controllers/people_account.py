# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Account & Security for teachers, students and parents.

Blocks accepted by the create/update bodies in people.py, and by the
per-person routes below:

  "account": {"create_login": true, "username": "...", "password": "..."?,
              "active": true, "send_credentials": true, "channel": "email" | "sms"}
      Every password the office sets - typed or generated - is a one-time
      password: it must be changed at first sign-in and expires (see
      bxi_api res.users). "send_credentials" sends the username and the
      one-time password; when the server generated it and it could not be
      sent, the response carries it once as credentials.one_time_password.
  "face": {"enabled": true, "image": "<base64>" | "images": [...],
           "consent_reference": "..."?}
      Needs a login. Enrols the photo for face sign-in/attendance
      (bxi_face_auth); "enabled": false revokes it.
  "id_verification": {"document": "<base64>" | {"data", "filename"} |
                      "documents": [...], "doc_type": "aadhaar" | ...}
      Image or PDF, sent for review (status "pending").
  "documents" (teachers): [{"doc_type": "aadhaar" | "cv" | "certificate" |
                            "other", "name"?, "file": "<base64>", "filename"?}]
"""
import base64
import binascii

from odoo import fields, http
from odoo.http import request
from odoo.tools.mimetypes import guess_mimetype

from odoo.addons.bxi_api.controllers.auth import (
    MAX_UPLOAD_BYTES, api_error, api_file_response, api_response, parse_request, require_auth,
)

from ..models.people_service import CREDENTIAL_CHANNELS, PeopleError
from .common import atomic, check_selection, ref

# Who may add and edit people records.
MANAGER_GROUPS = (
    'openeducat_core.group_op_back_office_admin',
    'bxi_academic_management.group_academic_manager',
    'base.group_system',
)
KIND_MODELS = {'teachers': 'op.faculty', 'students': 'op.student', 'parents': 'op.parent'}
KINDS = 'any("teachers", "students", "parents")'


def is_manager(user):
    return any(user.has_group(group) for group in MANAGER_GROUPS)


def _is_id_reviewer(user):
    return is_manager(user) or user.has_group('bxi_identity_verification.group_identity_reviewer')


def transaction(func):
    """atomic(func), also turning a PeopleError raised half-way into its
    error envelope - after the savepoint rolled everything back."""
    try:
        return atomic(func)
    except PeopleError as exc:
        return None, exc.to_response()


def _dt(value):
    return fields.Datetime.to_string(value) if value else None


# -- files ------------------------------------------------------------------------------


def _file_entry(entry, field, index=0):
    """({name, content, mimetype}, error) from a base64 string or an object
    {"data" | "file", "filename" | "name"?}. Images and PDFs only."""
    name = None
    if isinstance(entry, dict):
        name = entry.get('filename') or entry.get('name')
        entry = entry.get('data') or entry.get('file')
    if not isinstance(entry, str) or not entry:
        return None, api_error('%s must be a base64 file.' % field, status=400, code='invalid_%s' % field)
    if entry.startswith('data:') and ';base64,' in entry:
        entry = entry.split(';base64,', 1)[1]
    try:
        content = base64.b64decode(''.join(entry.split()), validate=True)
    except (binascii.Error, ValueError):
        return None, api_error('%s must be a base64 file.' % field, status=400, code='invalid_%s' % field)
    return _checked_file({'name': name, 'content': content}, field, index)


def _checked_file(file, field, index=0):
    content = file['content']
    if not content:
        return None, api_error('%s is empty.' % field, status=400, code='invalid_%s' % field)
    if len(content) > MAX_UPLOAD_BYTES:
        return None, api_error('Each file must be %s MB or smaller.' % (MAX_UPLOAD_BYTES // (1024 * 1024)),
                               status=413, code='file_too_large')
    mimetype = guess_mimetype(content)
    if not (mimetype.startswith('image/') or mimetype == 'application/pdf'):
        return None, api_error('%s must be an image or a PDF.' % field, status=400, code='invalid_file_type')
    extension = 'pdf' if mimetype == 'application/pdf' else mimetype.split('/')[-1]
    return {'name': file.get('name') or '%s-%s.%s' % (field, index + 1, extension), 'content': content,
            'mimetype': mimetype}, None


# -- parsing ----------------------------------------------------------------------------


def parse_account(payload):
    """(account or None, error) from payload["account"]."""
    raw = payload.get('account')
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        return None, api_error('account must be an object.', status=400, code='invalid_account')
    account = {}
    if raw.get('username') is not None:
        username = str(raw['username']).strip()
        if not username:
            return None, api_error('account.username cannot be blank.', status=400, code='missing_username')
        account['username'] = username
    if raw.get('password'):
        problem = request.env['res.users']._bxi_password_problem(raw['password'])
        if problem:
            return None, api_error(problem, status=400, code='invalid_password')
        account['password'] = str(raw['password']).strip()
    if 'active' in raw:
        account['active'] = bool(raw['active'])
    create_login = raw.get('create_login')
    account['create_login'] = bool(create_login) if create_login is not None \
        else bool(account.get('username') or account.get('password'))
    if raw.get('send_credentials'):
        channel, error = parse_channel(raw.get('channel'))
        if error:
            return None, error
        account.update(send_credentials=True, channel=channel)
    return account, None


def parse_channel(channel):
    channel = channel or 'email'
    if channel not in CREDENTIAL_CHANNELS:
        return None, api_error('channel must be email or sms (WhatsApp is not configured).', status=400,
                               code='invalid_channel')
    return channel, None


def parse_face(payload):
    raw = payload.get('face')
    if raw is None:
        return None, None
    if not isinstance(raw, dict) or not isinstance(raw.get('enabled'), bool):
        return None, api_error('face must be an object with "enabled": true or false.', status=400,
                               code='invalid_face')
    return raw, None


def parse_id_verification(payload, files=()):
    """(id_verification or None, error). `files` are multipart uploads
    ([{name, content, mimetype}]) from the dedicated route."""
    raw = payload.get('id_verification') if 'id_verification' in payload else None
    if raw is None and not files:
        return None, None
    raw = raw or {}
    if not isinstance(raw, dict):
        return None, api_error('id_verification must be an object.', status=400, code='invalid_id_verification')
    entries = raw.get('documents') or ([raw['document']] if raw.get('document') else [])
    if not isinstance(entries, list):
        return None, api_error('id_verification.documents must be a list.', status=400, code='invalid_document')
    checked = []
    for index, entry in enumerate(entries):
        file, error = _file_entry(entry, 'document', index)
        if error:
            return None, error
        checked.append(file)
    for index, file in enumerate(files):
        file, error = _checked_file(file, 'document', index)
        if error:
            return None, error
        checked.append(file)
    if not checked:
        return None, api_error('id_verification.document is required.', status=400, code='missing_document')
    doc_type = raw.get('doc_type') or payload.get('doc_type') or False
    if doc_type:
        error = check_selection(request.env['op.student'], 'id_document_type', doc_type, key='doc_type')
        if error:
            return None, error
    return {'files': checked, 'doc_type': doc_type}, None


def parse_documents(entries):
    """(documents, error) for teacher documents."""
    if entries is None:
        return None, None
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return None, api_error('documents must be a list.', status=400, code='invalid_documents')
    Document = request.env['bxi.faculty.document']
    documents = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            return None, api_error('Each document must be an object.', status=400, code='invalid_documents')
        doc_type = entry.get('doc_type') or 'other'
        error = check_selection(Document, 'doc_type', doc_type, key='doc_type')
        if error:
            return None, error
        file, error = _file_entry(entry, 'file', index)
        if error:
            return None, error
        documents.append({'doc_type': doc_type, 'name': entry.get('name') or file['name'], 'file': file})
    return documents, None


# -- applying (inside a transaction) -------------------------------------------------------


def _guard_target(user):
    if user and user.has_group('base.group_system') and not request.env.user.has_group('base.group_system'):
        raise PeopleError("Only an administrator can change an administrator's login.", 'forbidden', status=403)


def set_active(user, active):
    if not active and user == request.env.user:
        raise PeopleError("You can't deactivate your own login.", 'cannot_deactivate_self')
    user.sudo().active = active
    if not active:
        request.env['bxi.api.token'].sudo()._revoke_all_for_user(user)


def apply_account(record, account):
    """Create/update the person's login from a parsed account block.
    Returns the credentials still to deliver after the transaction
    ({user, password, generated, channel}) or None."""
    if not account:
        return None
    service = request.env['bxi.people.service']
    user = record.user_id.sudo()
    _guard_target(user)
    password, generated = None, False
    if not user:
        if not account['create_login']:
            raise PeopleError('This person has no login yet: send account.create_login true.', 'no_account')
        login = account.get('username') or service._partner(record).email
        if not login:
            raise PeopleError('account.username is required.', 'missing_username')
        user = service._create_login(record, login.strip())
        password = user._bxi_set_temporary_password(account.get('password'))
        generated = not account.get('password')
    else:
        if account.get('username') and account['username'] != user.login:
            if service._login_taken(account['username'], user):
                raise PeopleError('This username is already taken.', 'login_taken', status=409)
            user.write({'login': account['username']})
        if account.get('password'):
            password = user._bxi_set_temporary_password(account['password'])
    if 'active' in account and account['active'] != user.active:
        set_active(user, account['active'])
    if account.get('send_credentials'):
        if not password:
            password, generated = user._bxi_set_temporary_password(), True
        return {'user': user, 'password': password, 'generated': generated, 'channel': account['channel']}
    if generated:
        return {'user': user, 'password': password, 'generated': True, 'channel': None}
    return None


def apply_face(record, face):
    if face is None:
        return
    user = record.user_id.sudo()
    if not user:
        raise PeopleError('Create a login first: face recognition signs in to an account.', 'no_account')
    request.env['bxi.people.service']._apply_face(record, user, face)


def apply_id_verification(record, id_verification):
    if id_verification:
        record.sudo()._submit_id_documents(id_verification['files'], id_verification['doc_type'])


def apply_documents(faculty, documents):
    Document = request.env['bxi.faculty.document'].sudo()
    created = Document
    for document in documents or ():
        created |= Document.create({
            'faculty_id': faculty.id,
            'doc_type': document['doc_type'],
            'name': document['name'],
            'file': base64.b64encode(document['file']['content']),
            'filename': document['file']['name'],
        })
    return created


def deliver(record, delivery):
    """Send pending credentials (after the transaction succeeded) and
    describe the outcome for the response."""
    if not delivery:
        return None
    if delivery['channel']:
        result = request.env['bxi.people.service']._send_credentials(
            record, delivery['user'], delivery['password'], delivery['channel'])
    else:
        result = {'channel': None, 'sent': False, 'reason': 'not_requested'}
    if delivery['generated'] and not result['sent']:
        # Shown once, so the office can hand it over in person.
        result['one_time_password'] = delivery['password']
    return result


# -- response shapes ----------------------------------------------------------------------


def account_dict(record):
    user = record.user_id.sudo()
    if not user:
        return {'has_login': False, 'username': None, 'active': False, 'must_change_password': False,
                'one_time_password_expires_at': None, 'last_login': None}
    return {
        'has_login': True,
        'username': user.login,
        'active': user.active,
        'must_change_password': user.bxi_must_change_password,
        'one_time_password_expires_at': _dt(user.bxi_temp_password_expires_at)
        if user.bxi_must_change_password else None,
        'last_login': _dt(user.login_date),
    }


def id_verification_dict(record):
    record = record.sudo()
    return {
        'status': record.id_document_status,
        'doc_type': record.id_document_type or None,
        'submitted_at': _dt(record.id_document_submitted_at),
        'verified_at': _dt(record.id_document_verified_at),
        'notes': record.id_document_notes or None,
        'documents': [{'id': a.id, 'name': a.name, 'mimetype': a.mimetype} for a in record.id_document_ids],
    }


def document_dict(document):
    return {
        'id': document.id,
        'doc_type': document.doc_type,
        'name': document.name,
        'filename': document.filename or None,
        'mimetype': document.mimetype or None,
        'size': document.file_size,
        'uploaded_at': _dt(document.create_date),
        'uploaded_by': ref(document.create_uid),
    }


def security_dict(record):
    user = record.user_id.sudo()
    return {
        'account': account_dict(record),
        'face': request.env['bxi.people.service']._face_status(user) if user else None,
        'id_verification': id_verification_dict(record),
    }


class BxiApiSupportPeopleAccountController(http.Controller):

    @staticmethod
    def _record(kind, record_id, reviewer=False):
        user = request.env.user
        if not (_is_id_reviewer(user) if reviewer else is_manager(user)):
            return None, api_error('Not authorized to manage this person.', status=403, code='forbidden')
        record = request.env[KIND_MODELS[kind]].sudo().with_context(active_test=False).browse(record_id)
        if not record.exists():
            return None, api_error('Person not found.', status=404, code='not_found')
        return record, None

    @staticmethod
    def _response(record, credentials=None):
        data = security_dict(record)
        if credentials is not None:
            data['credentials'] = credentials
        return api_response(data)

    # -- account --------------------------------------------------------------------

    @http.route('/api/v1/<%s:kind>/<int:record_id>/account' % KINDS, type='http', auth='public',
                methods=['GET'], csrf=False)
    @require_auth
    def get_account(self, kind, record_id, **kwargs):
        """Login, face-recognition and ID-verification state."""
        record, error = self._record(kind, record_id)
        if error:
            return error
        return self._response(record)

    @http.route('/api/v1/<%s:kind>/<int:record_id>/account' % KINDS, type='http', auth='public',
                methods=['POST'], csrf=False)
    @require_auth
    def update_account(self, kind, record_id, **kwargs):
        """The "account" block on its own: create the login, rename it,
        set a one-time password, enable/disable sign-in, send credentials."""
        record, error = self._record(kind, record_id)
        if error:
            return error
        account, error = parse_account({'account': request.get_json_data() or {}})
        if error:
            return error
        delivery, error = transaction(lambda: apply_account(record, account))
        if error:
            return error
        return self._response(record, deliver(record, delivery))

    @http.route('/api/v1/<%s:kind>/<int:record_id>/account/status' % KINDS, type='http', auth='public',
                methods=['POST'], csrf=False)
    @require_auth
    def account_status(self, kind, record_id, **kwargs):
        """{"active": true | false}: whether the person can sign in. Turning
        it off also ends every app session."""
        record, error = self._record(kind, record_id)
        if error:
            return error
        payload = request.get_json_data() or {}
        if not isinstance(payload.get('active'), bool):
            return api_error('active must be true or false.', status=400, code='invalid_active')
        if not record.user_id:
            return api_error('This person has no login yet.', status=400, code='no_account')

        def apply():
            _guard_target(record.user_id.sudo())
            set_active(record.user_id, payload['active'])

        _, error = transaction(apply)
        if error:
            return error
        return self._response(record)

    @http.route('/api/v1/<%s:kind>/<int:record_id>/account/reset-password' % KINDS, type='http', auth='public',
                methods=['POST'], csrf=False)
    @require_auth
    def reset_password(self, kind, record_id, **kwargs):
        """{"password"?, "send_credentials"?, "channel"?}: a new one-time
        password (typed, or generated), signing the person out everywhere."""
        record, error = self._record(kind, record_id)
        if error:
            return error
        payload = request.get_json_data() or {}
        account, error = parse_account({'account': dict(
            password=payload.get('password'), send_credentials=payload.get('send_credentials'),
            channel=payload.get('channel'), create_login=False)})
        if error:
            return error
        if not record.user_id:
            return api_error('This person has no login yet.', status=400, code='no_account')

        def apply():
            user = record.user_id.sudo()
            _guard_target(user)
            password = user._bxi_set_temporary_password(account.get('password'))
            return {'user': user, 'password': password, 'generated': not account.get('password'),
                    'channel': account.get('channel')}

        delivery, error = transaction(apply)
        if error:
            return error
        return self._response(record, deliver(record, delivery))

    @http.route('/api/v1/<%s:kind>/<int:record_id>/account/send-credentials' % KINDS, type='http',
                auth='public', methods=['POST'], csrf=False)
    @require_auth
    def send_credentials(self, kind, record_id, **kwargs):
        """{"channel": "email" | "sms"}: issue a new one-time password and
        send it with the username (passwords are never stored readable, so
        sending credentials always means a fresh one-time password)."""
        record, error = self._record(kind, record_id)
        if error:
            return error
        channel, error = parse_channel((request.get_json_data() or {}).get('channel'))
        if error:
            return error
        if not record.user_id:
            return api_error('This person has no login yet.', status=400, code='no_account')

        def apply():
            user = record.user_id.sudo()
            _guard_target(user)
            return {'user': user, 'password': user._bxi_set_temporary_password(), 'generated': True,
                    'channel': channel}

        delivery, error = transaction(apply)
        if error:
            return error
        return self._response(record, deliver(record, delivery))

    # -- face -----------------------------------------------------------------------

    @http.route('/api/v1/<%s:kind>/<int:record_id>/face' % KINDS, type='http', auth='public',
                methods=['POST'], csrf=False)
    @require_auth
    def set_face(self, kind, record_id, **kwargs):
        """The "face" block on its own."""
        record, error = self._record(kind, record_id)
        if error:
            return error
        face, error = parse_face({'face': request.get_json_data()})
        if error:
            return error
        _, error = transaction(lambda: apply_face(record, face))
        if error:
            return error
        return self._response(record)

    # -- ID verification ------------------------------------------------------------

    @http.route('/api/v1/<%s:kind>/<int:record_id>/id-verification' % KINDS, type='http', auth='public',
                methods=['POST'], csrf=False)
    @require_auth
    def submit_id_verification(self, kind, record_id, **kwargs):
        """The "id_verification" block as JSON, or multipart: file part(s)
        plus an optional doc_type field. Replaces earlier ID documents."""
        record, error = self._record(kind, record_id)
        if error:
            return error
        payload, files, error = parse_request()
        if error:
            return error
        if files:
            id_verification, error = parse_id_verification(
                {'id_verification': {'doc_type': payload.get('doc_type')}}, files)
        else:
            id_verification, error = parse_id_verification({'id_verification': payload})
        if error:
            return error
        _, error = transaction(lambda: apply_id_verification(record, id_verification))
        if error:
            return error
        return self._response(record)

    @http.route('/api/v1/<%s:kind>/<int:record_id>/id-verification/review' % KINDS, type='http',
                auth='public', methods=['POST'], csrf=False)
    @require_auth
    def review_id_verification(self, kind, record_id, **kwargs):
        """{"decision": "verify" | "reject", "notes"?} - office or identity
        reviewers, for a document waiting for review."""
        record, error = self._record(kind, record_id, reviewer=True)
        if error:
            return error
        payload = request.get_json_data() or {}
        decision = payload.get('decision')
        if decision not in ('verify', 'reject'):
            return api_error('decision must be verify or reject.', status=400, code='invalid_decision')
        if record.id_document_status != 'pending':
            return api_error('There is no ID document waiting for review.', status=400, code='invalid_transition')

        def apply():
            if 'notes' in payload:
                record.id_document_notes = payload['notes'] or False
            if decision == 'verify':
                record.action_verify_id_document()
            else:
                record.action_reject_id_document()

        _, error = transaction(apply)
        if error:
            return error
        return self._response(record)

    @http.route('/api/v1/<%s:kind>/<int:record_id>/id-verification/documents/<int:attachment_id>' % KINDS,
                type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def id_document_file(self, kind, record_id, attachment_id, **kwargs):
        record, error = self._record(kind, record_id, reviewer=True)
        if error:
            return error
        attachment = record.id_document_ids.filtered(lambda a: a.id == attachment_id)
        if not attachment:
            return api_error('Document not found.', status=404, code='not_found')
        return api_file_response(attachment.raw, attachment.name, attachment.mimetype or 'application/octet-stream')

    # -- teacher documents ----------------------------------------------------------

    @staticmethod
    def _faculty(faculty_id, write=False):
        faculty = request.env['op.faculty'].sudo().with_context(active_test=False).browse(faculty_id)
        if not faculty.exists():
            return None, api_error('Teacher not found.', status=404, code='not_found')
        user = request.env.user
        if not (is_manager(user) or (not write and faculty.user_id == user)):
            return None, api_error('Not authorized for this teacher.', status=403, code='forbidden')
        return faculty, None

    @http.route('/api/v1/teachers/<int:faculty_id>/documents', type='http', auth='public', methods=['GET'],
                csrf=False)
    @require_auth
    def list_documents(self, faculty_id, doc_type=None, **kwargs):
        faculty, error = self._faculty(faculty_id)
        if error:
            return error
        documents = faculty.document_ids
        if doc_type:
            documents = documents.filtered(lambda d: d.doc_type == doc_type)
        return api_response({'documents': [document_dict(d) for d in documents]})

    @http.route('/api/v1/teachers/<int:faculty_id>/documents', type='http', auth='public', methods=['POST'],
                csrf=False)
    @require_auth
    def upload_documents(self, faculty_id, **kwargs):
        """JSON {"documents": [...]} (or one document object), or multipart:
        file part(s) plus doc_type and name fields."""
        faculty, error = self._faculty(faculty_id, write=True)
        if error:
            return error
        payload, files, error = parse_request()
        if error:
            return error
        if files:
            doc_type = payload.get('doc_type') or 'other'
            error = check_selection(request.env['bxi.faculty.document'], 'doc_type', doc_type, key='doc_type')
            if error:
                return error
            documents = []
            for index, file in enumerate(files):
                file, error = _checked_file(file, 'file', index)
                if error:
                    return error
                documents.append({'doc_type': doc_type, 'name': payload.get('name') or file['name'], 'file': file})
        else:
            documents, error = parse_documents(payload.get('documents', payload or None))
            if error:
                return error
        if not documents:
            return api_error('documents is required.', status=400, code='missing_documents')
        created, error = transaction(lambda: apply_documents(faculty, documents))
        if error:
            return error
        return api_response({'documents': [document_dict(d) for d in created]}, status=201)

    @http.route('/api/v1/teachers/<int:faculty_id>/documents/<int:document_id>', type='http', auth='public',
                methods=['GET'], csrf=False)
    @require_auth
    def download_document(self, faculty_id, document_id, **kwargs):
        faculty, error = self._faculty(faculty_id)
        if error:
            return error
        document = faculty.document_ids.filtered(lambda d: d.id == document_id)
        if not document:
            return api_error('Document not found.', status=404, code='not_found')
        content = base64.b64decode(document.with_context(bin_size=False).file or b'')
        return api_file_response(content, document.filename or document.name,
                                 document.mimetype or 'application/octet-stream')

    @http.route('/api/v1/teachers/<int:faculty_id>/documents/<int:document_id>/delete', type='http',
                auth='public', methods=['POST'], csrf=False)
    @require_auth
    def delete_document(self, faculty_id, document_id, **kwargs):
        faculty, error = self._faculty(faculty_id, write=True)
        if error:
            return error
        document = faculty.document_ids.filtered(lambda d: d.id == document_id)
        if not document:
            return api_error('Document not found.', status=404, code='not_found')
        document.unlink()
        return api_response({'deleted': True, 'id': document_id})
