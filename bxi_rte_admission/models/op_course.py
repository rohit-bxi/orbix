# -*- coding: utf-8 -*-

import math

from odoo import api, fields, models
from odoo.exceptions import ValidationError

RTE_ENTRY_CLASSES = [
    ('pp3', 'Pre Primary 3+ (PP.3+)'),
    ('pp4', 'Pre Primary 4+ (PP.4+)'),
    ('pp5', 'Pre Primary 5+ (PP.5+)'),
    ('first', 'First'),
]

# Age, in completed years, a child must have reached to enter this class
# (Disha-Nirdesh 2026-27, para 2.3).
RTE_ENTRY_CLASS_MIN_AGE = {
    'pp3': 3,
    'pp4': 4,
    'pp5': 5,
    'first': 6,
}

CATCHMENT_AREA_TYPES = [
    ('urban', 'Urban (Local Body)'),
    ('rural', 'Rural (Gram Panchayat)'),
]

# Para 4.1: a boys-only or girls-only school can only admit that gender
# under RTE too; co-ed schools have no restriction.
RTE_GENDER_RESTRICTIONS = [
    ('co_ed', 'Co-Educational'),
    ('boys', 'Boys Only'),
    ('girls', 'Girls Only'),
]


class OpCourse(models.Model):
    _inherit = 'op.course'

    total_intake = fields.Integer(
        string='Total Intake', default=0,
        help='Total number of seats available for this course.')
    rte_seats_manual = fields.Integer(
        string='RTE Seats (Manual Override)', default=0,
        help='Set a value here to override the auto-computed 25% RTE '
             'reservation. Leave 0 to use the computed value.')
    rte_seats = fields.Integer(
        string='RTE Seats', compute='_compute_rte_seats', store=True,
        help='Seats reserved under RTE Section 12(1)(c). Auto-computed as '
             '25% of Total Intake unless manually overridden.')
    rte_entry_class = fields.Selection(
        RTE_ENTRY_CLASSES, string='RTE Entry Class',
        help='Entry-level class this course represents for RTE admission '
             '(para 2.3). Leave blank to skip age-band validation.')
    catchment_area_type = fields.Selection(
        CATCHMENT_AREA_TYPES, string='Catchment Area Type',
        help='Whether the school\'s neighbourhood (catchment) is defined '
             'by an urban local body ward or a rural gram panchayat '
             'village (para 2.1).')
    catchment_urban_body = fields.Char(
        string='Urban Local Body',
        help='Nagar Nigam / Nagar Parishad / Nagar Palika the school\'s '
             'ward falls under.')
    catchment_ward = fields.Char(
        string='School Ward No.',
        help='Ward in which the school itself is located (urban).')
    catchment_gram_panchayat = fields.Char(
        string='Gram Panchayat',
        help='Gram Panchayat the school\'s village falls under (rural).')
    catchment_village = fields.Char(
        string='School Village',
        help='Village in which the school itself is located (rural).')
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        related='company_id.currency_id', readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)
    reimbursement_rate = fields.Monetary(
        string='Reimbursement Rate (per RTE seat)', currency_field='currency_id',
        help='Amount reimbursed by the State/Government per RTE seat '
             'admitted under this course.')
    rte_active = fields.Boolean(
        string='RTE Active', default=False,
        help='Enable RTE Section 12(1)(c) admissions for this course.')
    rte_gender_restriction = fields.Selection(
        RTE_GENDER_RESTRICTIONS, string='Gender Admitted', default='co_ed',
        required=True,
        help='Boys-only and girls-only schools may only admit that '
             'gender under RTE as well (para 4.1).')

    @api.depends('total_intake', 'rte_seats_manual')
    def _compute_rte_seats(self):
        quota_percentage = float(self.env['ir.config_parameter'].sudo().get_param(
            'bxi_rte_admission.quota_percentage', default='25.0'))
        for course in self:
            if course.rte_seats_manual:
                course.rte_seats = course.rte_seats_manual
            else:
                # Round half up (not Python's banker's rounding) since this
                # is a statutory seat-reservation count, not a display value.
                course.rte_seats = int(math.floor(
                    (course.total_intake or 0) * (quota_percentage / 100.0) + 0.5))

    @api.constrains('total_intake', 'rte_seats_manual')
    def _check_rte_seat_values(self):
        for course in self:
            if course.total_intake < 0:
                raise ValidationError('Total Intake cannot be negative.')
            if course.rte_seats_manual < 0:
                raise ValidationError('RTE Seats (Manual Override) cannot be negative.')

    @api.constrains('catchment_area_type', 'catchment_ward', 'catchment_village',
                     'catchment_gram_panchayat', 'catchment_urban_body')
    def _check_catchment_fields(self):
        for course in self:
            if course.catchment_area_type == 'urban' and not (
                    course.catchment_ward and course.catchment_urban_body):
                raise ValidationError(
                    'Urban schools require both a Ward No. and an Urban '
                    'Local Body for the RTE catchment area.')
            if course.catchment_area_type == 'rural' and not (
                    course.catchment_village and course.catchment_gram_panchayat):
                raise ValidationError(
                    'Rural schools require both a Village and a Gram '
                    'Panchayat for the RTE catchment area.')
