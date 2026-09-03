# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Para 4.8: a parent may rank at most 5 schools within their catchment area.
MAX_PREFERENCES = 5


class RteSchoolPreference(models.Model):
    _name = 'rte.school.preference'
    _description = 'RTE School/Course Preference'
    _order = 'sequence, id'

    admission_id = fields.Many2one(
        'op.admission', string='Admission', required=True, ondelete='cascade')
    course_id = fields.Many2one(
        'op.course', string='Course', required=True,
        domain=[('rte_active', '=', True)])
    sequence = fields.Integer(string='Preference Order', default=10)

    @api.constrains('admission_id')
    def _check_preference_limit(self):
        for admission in self.mapped('admission_id'):
            if len(admission.rte_preference_ids) > MAX_PREFERENCES:
                raise ValidationError(_(
                    'An applicant may rank at most %s school preferences '
                    '(para 4.8).') % MAX_PREFERENCES)

    @api.constrains('admission_id', 'course_id')
    def _check_preference_unique(self):
        for admission in self.mapped('admission_id'):
            course_ids = admission.rte_preference_ids.mapped('course_id.id')
            if len(course_ids) != len(set(course_ids)):
                raise ValidationError(_(
                    'The same school cannot be ranked twice in one '
                    'application.'))

    @api.constrains('course_id')
    def _check_preference_course_active(self):
        for preference in self:
            if not preference.course_id.rte_active:
                raise ValidationError(_(
                    '%s is not open for RTE admissions.')
                    % preference.course_id.name)

    @api.constrains('course_id', 'admission_id')
    def _check_preference_gender(self):
        """Para 4.1: a boys-only/girls-only school can only be ranked by
        an applicant of the matching gender."""
        for preference in self:
            restriction = preference.course_id.rte_gender_restriction
            gender = preference.admission_id.gender
            if not restriction or restriction == 'co_ed' or not gender:
                continue
            expected = 'm' if restriction == 'boys' else 'f'
            if gender != expected:
                raise ValidationError(_(
                    '%s only admits %s under RTE; this applicant\'s '
                    'gender does not match (para 4.1).')
                    % (preference.course_id.name,
                       'boys' if restriction == 'boys' else 'girls'))
