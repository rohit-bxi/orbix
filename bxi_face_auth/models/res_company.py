# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields, models


class ResCompany(models.Model):
    """Face login settings, per school (company). Edited through
    /api/v1/admin/face/settings; see controllers/admin.py SETTINGS for the
    API names and limits."""
    _inherit = 'res.company'

    bxi_face_enabled = fields.Boolean(string='Face Login Enabled')
    bxi_face_allow_student = fields.Boolean(string='Face Login for Students', default=True)
    bxi_face_allow_teacher = fields.Boolean(string='Face Login for Teachers', default=True)
    bxi_face_allow_parent = fields.Boolean(string='Face Login for Parents', default=True)
    bxi_face_allow_staff = fields.Boolean(
        string='Face Login for Other Staff', default=False,
        help='Non-teaching staff and administrators. Off by default: an administrator '
             'account is worth more to an attacker than a face is hard to copy.')
    bxi_face_student_consent_required = fields.Boolean(
        string='Parent Consent Required for Students', default=True)
    bxi_face_student_course_ids = fields.Many2many(
        'op.course', 'bxi_face_company_course_rel', 'company_id', 'course_id',
        string='Face Login Classes', help='If set, only students in these classes may use face login.')
    bxi_face_kiosk_enabled = fields.Boolean(string='Face Login Kiosks', default=True)
    bxi_face_auto_identify = fields.Boolean(
        string='Face-only Login', default=True,
        help='Let the app log someone in from the face alone (no login hint): the whole school '
             'is searched with the stricter kiosk threshold and score gap.')
    bxi_face_match_threshold = fields.Float(
        string='Match Threshold (own phone)', default=0.45, digits=(3, 2),
        help='Minimum similarity (0-1) between the face and the account the app remembers.')
    bxi_face_kiosk_match_threshold = fields.Float(
        string='Match Threshold (kiosk)', default=0.55, digits=(3, 2),
        help='Minimum similarity when the whole school is searched; stricter, because the '
             'chance of a lookalike grows with the number of people enrolled.')
    bxi_face_kiosk_match_gap = fields.Float(
        string='Score Gap', default=0.10, digits=(3, 2),
        help='How far the best match must be ahead of the next person, else the face is '
             'treated as ambiguous and the user is sent to password/OTP login.')
    bxi_face_liveness_required = fields.Boolean(string='Liveness Check', default=True)
    bxi_face_antispoof_threshold = fields.Float(
        string='Anti-spoof Threshold', default=0.80, digits=(3, 2),
        help='Only used when a passive anti-spoof model is installed.')
    bxi_face_max_failures = fields.Integer(string='Failed Attempts Before Lockout', default=5)
    bxi_face_lockout_minutes = fields.Integer(string='Lockout (minutes)', default=15)
    bxi_face_student_validity_days = fields.Integer(
        string='Student Enrolment Valid (days)', default=365,
        help="Children's faces change; students re-enrol after this many days. 0 = never expires.")
    bxi_face_token_days = fields.Integer(string='Face Session Length (days)', default=30)
    bxi_face_attempt_retention_days = fields.Integer(string='Keep Login Attempts (days)', default=180)
    bxi_face_consent_version = fields.Char(
        string='Consent Text Version', default='1',
        help='Recorded with every consent, so you can tell which wording a parent agreed to.')
