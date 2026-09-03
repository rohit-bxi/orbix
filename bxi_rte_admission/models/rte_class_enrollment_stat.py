# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Order used to find "the previous entry class" when subtracting children
# already promoted on a free (RTE) seat, per the para 6.1 roster table.
PREVIOUS_ENTRY_CLASS = {
    'pp4': 'pp3',
    'pp5': 'pp4',
    'first': 'pp5',
}


class RteClassEnrollmentStat(models.Model):
    _name = 'rte.class.enrollment.stat'
    _description = 'RTE Paid-Enrollment Statistic (per course/entry class/session)'
    _order = 'academic_year_id desc'

    course_id = fields.Many2one(
        'op.course', string='Course', required=True, ondelete='cascade')
    entry_class = fields.Selection(
        related='course_id.rte_entry_class', string='Entry Class', store=True)
    academic_year_id = fields.Many2one(
        'op.academic.year', string='Academic Year', required=True)
    paid_enrolled_count = fields.Integer(
        string='Paid (Sashulk) New Enrollment',
        help='Number of fee-paying children newly admitted to this entry '
             'class in this session (para 6.1). Used, averaged over the '
             'last 3 sessions, to compute next session\'s free-seat count.')
    promoted_free_count = fields.Integer(
        string='Free Seat Children Promoted From Previous Class',
        help='Number of children who held a free (RTE) seat in the '
             'previous entry class and were promoted into this one this '
             'session (para 6.1). Subtracted from the computed free-seat '
             'count for PP.4+/PP.5+/First; leave 0 for PP.3+.')

    _unique_course_year = models.Constraint(
        'unique(course_id, academic_year_id)',
        'Only one enrollment statistic may be recorded per course per '
        'academic year.'
    )

    @api.constrains('paid_enrolled_count', 'promoted_free_count')
    def _check_non_negative(self):
        for stat in self:
            if stat.paid_enrolled_count < 0 or stat.promoted_free_count < 0:
                raise ValidationError(_(
                    'Enrollment counts cannot be negative.'))

    @api.model
    def _compute_roster_free_seats(self, course, academic_year):
        """Para 6.1 roster formula: free seats = round(avg-or-current paid
        enrollment over the last 3 sessions / 3), minus (for PP.4+/PP.5+/
        First) the number of free-seat children promoted from the previous
        class this session. Returns None if there isn't at least one
        enrollment statistic recorded for this course, so callers can fall
        back to the simple 25%-of-intake computation (``course.rte_seats``).
        """
        entry_class = course.rte_entry_class
        if not entry_class:
            return None
        stats = self.search([
            ('course_id', '=', course.id),
            ('academic_year_id.start_date', '<=', academic_year.start_date),
        ], order='academic_year_id desc', limit=3)
        if not stats:
            return None
        current_stat = stats.filtered(
            lambda s: s.academic_year_id == academic_year)
        history = stats - current_stat
        avg_paid = (sum(history.mapped('paid_enrolled_count')) / len(history)
                    if history else 0)
        current_paid = current_stat.paid_enrolled_count if current_stat else 0
        basis = max(avg_paid, current_paid)
        free_seats = round(basis / 3.0)

        previous_class = PREVIOUS_ENTRY_CLASS.get(entry_class)
        if previous_class:
            promoted = current_stat.promoted_free_count if current_stat else 0
            free_seats -= promoted
        return max(free_seats, 0)
