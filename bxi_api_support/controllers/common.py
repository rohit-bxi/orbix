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

from odoo import fields
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, parse_int


def school_context(env):
    """The caller's student/parent/teacher records and classes - see
    res.users._bxi_school_context."""
    return env.user._bxi_school_context()


def audience_domain(env, audiences_by_role, specific_value='specific_class'):
    """Domain restricting a `target_audience` model (announcements,
    notices, events) to what the caller is meant to see.

    `audiences_by_role` maps a role ('student', 'parent', 'teacher',
    'staff', or '*' for everyone) to the target_audience values that role
    receives. On top of those, a `specific_value` item is visible when one
    of its classes/sections (empty = all) is a class the caller's own or
    linked students are in or - for staff - teaches.
    """
    user = env.user
    context = school_context(env)
    roles = set(user._bxi_roles(context))
    allowed = set()
    for role, values in audiences_by_role.items():
        if role == '*' or role in roles:
            allowed |= set(values)
    courses = env['op.course']
    batches = env['op.batch']
    if roles & {'student', 'parent'}:
        courses |= context['family_courses']
        batches |= context['family_batches']
    if roles & {'teacher', 'staff'}:
        courses |= context['teaching_courses']
        batches |= context['teaching_batches']
    domain = Domain('target_audience', 'in', sorted(allowed))
    if courses:
        domain |= Domain.AND([
            Domain('target_audience', '=', specific_value),
            Domain('course_ids', '=', False) | Domain('course_ids', 'in', courses.ids),
            Domain('batch_ids', '=', False) | Domain('batch_ids', 'in', batches.ids),
        ])
    return domain


def is_staff(env):
    return env.user._bxi_is_staff()


def ref(record):
    """many2one-style {id, name} for a JSON body, or None."""
    return {'id': record.id, 'name': record.display_name} if record else None


def running_enrollment(student):
    return student.course_detail_ids.filtered(lambda line: line.state == 'running')[:1]


# Staff who may open any student's records (profile, homework, results,
# library, transport...): the student's own teachers are allowed
# separately, by section.
STUDENT_STAFF_GROUPS = (
    'bxi_academic_management.group_academic_coordinator',
    'bxi_academic_management.group_academic_manager',
    'openeducat_core.group_op_back_office_admin',
    'openeducat_admission.group_op_admission_user',
    'op_health_center.group_health_staff',
    'op_health_center.group_health_manager',
    'base.group_system',
)


def can_view_student(env, student):
    """Family (the student or their parent), the teachers of the student's
    current section, and the office staff in STUDENT_STAFF_GROUPS."""
    context = school_context(env)
    if student in context['students']:
        return True
    if any(env.user.has_group(group) for group in STUDENT_STAFF_GROUPS):
        return True
    enrollment = running_enrollment(student)
    return bool(enrollment and enrollment.batch_id in context['teaching_batches'])


def session_students(session):
    """A period's roster: its own students, or - for periods generated
    before the timetable generator started filling them in - everyone
    currently enrolled in its section."""
    if session.student_ids or not session.batch_id:
        return session.student_ids
    return session.env['op.student.course'].sudo().search([
        ('batch_id', '=', session.batch_id.id), ('state', '=', 'running'),
    ]).student_id


def get_viewable_student(env, student_id, allow=None):
    """Resolve a student_id (path/query/payload value) to an op.student
    (sudo) the caller may see - can_view_student, or `allow(env, student)`
    when given. Returns (student, None) or (None, api_error(...))."""
    if not student_id:
        return None, api_error('student_id is required.', status=400, code='missing_student_id')
    student_id, error = parse_int(student_id, 'student_id')
    if error:
        return None, error
    student = env['op.student'].sudo().browse(student_id)
    if not student.exists():
        return None, api_error('Student not found.', status=404, code='not_found')
    if not (allow or can_view_student)(env, student):
        return None, api_error('Not authorized for this student.', status=403, code='forbidden')
    return student, None


def parse_ids(values, field_name):
    """(list of ints, None) or (None, api_error(...)) for a JSON id list."""
    if not isinstance(values, (list, tuple)):
        return None, api_error('%s must be a list of ids.' % field_name, status=400, code='invalid_%s' % field_name)
    ids = []
    for value in values:
        value, error = parse_int(value, field_name)
        if error:
            return None, error
        ids.append(value)
    return ids, None


def parse_amount(value, field_name='amount'):
    """(float > 0, None) or (None, api_error(...)) for a money amount."""
    if value is None or value == '':
        return None, api_error('%s is required.' % field_name, status=400, code='missing_%s' % field_name)
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None, api_error('%s must be a number.' % field_name, status=400, code='invalid_%s' % field_name)
    if amount <= 0:
        return None, api_error('%s must be greater than zero.' % field_name, status=400, code='invalid_%s' % field_name)
    return amount, None


def date_str(value):
    """Date/Datetime (or False) -> ISO string or None, for JSON bodies."""
    if not value:
        return None
    if hasattr(value, 'hour'):
        return fields.Datetime.to_string(value)
    return fields.Date.to_string(value)


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
