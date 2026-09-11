# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

"""Shared row-level scoping and pagination helpers for bxi_api_support
controllers.

Every domain in this module revolves around a student's own records. A
family login - the student's own account (op.student.user_id) or a
parent's account linked via op.parent (op.parent.user_id + student_ids) -
always sees only their own child's/own records; that part is universal
and handled by get_own_student_ids/user_can_access_student below.

What counts as "staff" is NOT universal, though, and callers must pass
their own `is_staff` check rather than rely on a default: bxi_parent_data_api
treats any regular backend user as trusted for its low-sensitivity reads
(exam results, attendance, timetable), but the underlying modules for
money/certificates/transport (fee, exemption, refund, scholarship,
certificate, transport, ...) each gate their own "see everything" ir.rule
behind a specific staff group, with a plain base.group_user login getting
only the self/family view. Passing no `is_staff` falls back to the
bxi_parent_data_api convention - only correct for that same class of
low-sensitivity data, not for anything financial or private.
"""

from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, parse_int


def get_own_student_ids(env):
    """Student ids the calling user may act on as "self": their own student
    account, or the children linked to their parent account.
    """
    user = env.user
    own_students = env['op.student'].sudo().search([('user_id', '=', user.id)])
    parent_students = env['op.parent'].sudo().search([('user_id', '=', user.id)]).student_ids
    return (own_students | parent_students).ids


def user_can_access_student(env, student, is_staff=None):
    """True if the calling user is staff or a family login linked to this
    specific student. `is_staff` defaults to "any regular backend user"
    (the bxi_parent_data_api convention) - pass a domain-specific check
    (e.g. `_is_fee_staff`) for anything more sensitive than that.
    """
    is_staff = is_staff or (lambda user: user.has_group('base.group_user'))
    if is_staff(env.user):
        return True
    return student.id in get_own_student_ids(env)


def get_own_faculty(env):
    """The op.faculty record linked to the calling user, or an empty
    recordset. Mirrors the `op.faculty.user_id` ownership field the
    academic/assessment/lesson-plan/timetable/lab modules already use in
    their own ir.rule domains (e.g. `teacher_id.user_id = user.id`).
    """
    return env['op.faculty'].sudo().search([('user_id', '=', env.user.id)], limit=1)


def get_authorized_student(payload_student_id, is_staff=None):
    """Resolve and authorize a student_id coming from a request payload or
    query string. `is_staff` is forwarded to user_can_access_student - pass
    a domain-specific staff check for anything sensitive (see module
    docstring). Returns (student, None) or (None, api_error(...)).
    """
    if not payload_student_id:
        return None, api_error('student_id is required.', status=400, code='missing_student_id')
    student_id, error = parse_int(payload_student_id, 'student_id')
    if error:
        return None, error
    student = request.env['op.student'].sudo().browse(student_id)
    if not student.exists():
        return None, api_error('Student not found.', status=404, code='not_found')
    if not user_can_access_student(request.env, student, is_staff=is_staff):
        return None, api_error('Not authorized for this student.', status=403, code='forbidden')
    return student, None


def safe_create(model, vals):
    """Create a record, translating a model-level @api.constrains failure
    (e.g. "refund amount cannot exceed total paid") into a 400 envelope
    instead of an unhandled ValidationError/UserError becoming a generic
    500 - the create()-time counterpart of call_action for action_* methods.
    Returns (record, None) or (None, api_error(...)).
    """
    try:
        return model.create(vals), None
    except UserError as exc:
        return None, api_error(str(exc), status=400, code='validation_error')


def parse_pagination(kwargs, default_limit=50, max_limit=200):
    """Parse limit/offset query params, clamping limit to max_limit.
    Returns (limit, offset, None) or (None, None, api_error(...)).
    """
    limit = default_limit
    offset = 0
    if kwargs.get('limit') is not None:
        limit, error = parse_int(kwargs['limit'], 'limit')
        if error:
            return None, None, error
        limit = max(1, min(limit, max_limit))
    if kwargs.get('offset') is not None:
        offset, error = parse_int(kwargs['offset'], 'offset')
        if error:
            return None, None, error
        offset = max(0, offset)
    return limit, offset, None
