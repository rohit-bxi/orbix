# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The Career Pathway report's app-usage data. Opt-in only: nothing is
stored until a parent (or the school office) records consent for the
student, and withdrawing consent deletes what was stored. Only daily
minutes per app category and a count of apps are kept - never app names,
websites or content."""
from datetime import timedelta

from odoo import api, fields, models

USAGE_CATEGORIES = [
    ('education', 'Education & Learning'),
    ('reading', 'Reading & Reference'),
    ('productivity', 'Productivity & Tools'),
    ('development', 'Development & Programming'),
    ('design', 'Design & Creative'),
    ('social', 'Social Media & Communication'),
    ('entertainment', 'Video & Entertainment'),
    ('games', 'Games'),
    ('other', 'Other'),
]
PRODUCTIVE_CATEGORIES = ('education', 'reading', 'productivity', 'development', 'design')
# Category -> the "Primary Interest" card's word.
INTEREST_LABELS = {
    'education': 'Learning', 'reading': 'Reading', 'productivity': 'Productivity', 'development': 'Tech',
    'design': 'Creative', 'social': 'Social', 'entertainment': 'Media', 'games': 'Gaming', 'other': 'Mixed',
}
MAX_DAY_MINUTES = 24 * 60
KEEP_DAYS = 90


class BxiDeviceUsage(models.Model):
    _name = 'bxi.device.usage'
    _description = 'Student App Usage (per day and category)'
    _order = 'date desc, category'

    student_id = fields.Many2one('op.student', required=True, index=True, ondelete='cascade')
    date = fields.Date(required=True, index=True)
    category = fields.Selection(USAGE_CATEGORIES, required=True)
    minutes = fields.Integer(required=True, default=0)
    app_count = fields.Integer('Apps Used', default=0)

    _unique_day_category = models.Constraint('unique(student_id, date, category)',
                                             'One usage row per student, day and category.')
    _minutes_range = models.Constraint('CHECK(minutes >= 0 AND minutes <= 1440)',
                                       'Minutes must be between 0 and 1440.')

    @api.model
    def _bxi_record_day(self, student, day, rows):
        """Replace `student`'s usage for `day` with `rows`
        ([{category, minutes, app_count}])."""
        self.sudo().search([('student_id', '=', student.id), ('date', '=', day)]).unlink()
        return self.sudo().create([{'student_id': student.id, 'date': day, **row} for row in rows])

    @api.autovacuum
    def _gc_old_usage(self):
        self.sudo().search([('date', '<', fields.Date.today() - timedelta(days=KEEP_DAYS))]).unlink()


class OpStudent(models.Model):
    _inherit = 'op.student'

    bxi_usage_consent = fields.Boolean('App Usage Consent', copy=False, readonly=True,
                                       help='A parent or the school office agreed that the app may send this '
                                            'student\'s daily app-category usage for the Career Pathway report.')
    bxi_usage_consent_by = fields.Many2one('res.users', 'Consent Given By', copy=False, readonly=True)
    bxi_usage_consent_date = fields.Datetime('Consent Date', copy=False, readonly=True)

    def _bxi_set_usage_consent(self, consent, user):
        self.ensure_one()
        self.sudo().write({
            'bxi_usage_consent': consent,
            'bxi_usage_consent_by': user.id if consent else False,
            'bxi_usage_consent_date': fields.Datetime.now() if consent else False,
        })
        if not consent:
            self.env['bxi.device.usage'].sudo().search([('student_id', '=', self.id)]).unlink()


class BxiCareer(models.Model):
    _inherit = 'bxi.career'

    usage_categories = fields.Char(
        'App Usage Categories',
        help='Comma-separated app categories that point to this career in the Career Pathway report, '
             'e.g. "development,productivity". Keys: %s.' % ', '.join(key for key, _label in USAGE_CATEGORIES))

    def _bxi_usage_categories(self):
        self.ensure_one()
        return {c.strip() for c in (self.usage_categories or '').split(',') if c.strip()}

    @api.model
    def _bxi_seed_usage_categories(self):
        """Usage categories for the starter careers, set only where empty
        so the school's own edits survive upgrades."""
        starters = {
            'career_design': 'design', 'career_technical': 'development,productivity',
            'career_research': 'education,reading', 'career_teaching': 'education,reading',
            'career_lawyer': 'reading,social', 'career_ca': 'productivity', 'career_healthcare': 'education',
        }
        for xmlid, categories in starters.items():
            career = self.env.ref('bxi_student_learning.%s' % xmlid, raise_if_not_found=False)
            if career and not career.usage_categories:
                career.usage_categories = categories
