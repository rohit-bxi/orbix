# -*- coding: utf-8 -*-

import hashlib
import random
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class RteLotteryBatch(models.Model):
    _name = 'rte.lottery.batch'
    _description = 'RTE Lottery Batch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Batch Reference', required=True, copy=False, readonly=True,
        default=lambda self: _('New'))
    course_id = fields.Many2one(
        'op.course', string='Course', required=True, tracking=True)
    academic_year_id = fields.Many2one(
        'op.academic.year', string='Academic Year', required=True, tracking=True)
    draw_date = fields.Datetime(string='Draw Date')
    random_seed = fields.Char(
        string='Random Seed', required=True,
        default=lambda self: secrets.token_hex(16),
        help='Seed used to deterministically shuffle applicants. Keeping '
             'this value makes the draw reproducible/auditable. '
             'Auto-generated - the standard rte.lottery.wizard flow does '
             'not allow overriding it.')
    applicant_hash = fields.Char(
        string='Applicant List Hash', readonly=True, copy=False,
        help='SHA-256 hash of the sorted list of applicants included in '
             'the draw, recorded for audit purposes.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('ready', 'Ready'),
        ('run', 'Run'),
        ('published', 'Published'),
    ], string='Status', default='draft', required=True, tracking=True)
    result_ids = fields.One2many(
        'rte.lottery.result', 'batch_id', string='Results')
    effective_seats = fields.Integer(
        string='Effective Free Seats', compute='_compute_effective_seats',
        store=True,
        help='Free seats to allot for this batch: the para 6.1 roster '
             'formula (average/current paid enrollment over the last 3 '
             'sessions, minus children promoted from the previous class) '
             'when at least one rte.class.enrollment.stat is on file for '
             'the course, otherwise the course\'s simple computed/manual '
             'RTE Seats (25% of intake).')

    @api.depends('course_id', 'academic_year_id',
                 'course_id.rte_seats', 'course_id.rte_entry_class')
    def _compute_effective_seats(self):
        Stat = self.env['rte.class.enrollment.stat']
        for batch in self:
            roster_seats = None
            if batch.course_id and batch.academic_year_id:
                roster_seats = Stat._compute_roster_free_seats(
                    batch.course_id, batch.academic_year_id)
            batch.effective_seats = (
                roster_seats if roster_seats is not None
                else batch.course_id.rte_seats)

    @api.model
    def _get_priority_tier(self, admission, course):
        """Para 5.1-5.4 / Appendix-2 examples 1 & 2: within a lottery,
        applicants from the school's own ward (urban) or village (rural)
        rank ahead of the rest of the ULB/Gram Panchayat, and within each
        of those two groups orphan/disabled applicants (para 5.2) rank
        first. Returns 0 (highest priority) to 3 (lowest)."""
        in_pocket = False
        if course.catchment_area_type == 'urban':
            in_pocket = bool(
                admission.rte_ward and course.catchment_ward
                and admission.rte_ward == course.catchment_ward)
        elif course.catchment_area_type == 'rural':
            in_pocket = bool(
                admission.rte_village and course.catchment_village
                and admission.rte_village == course.catchment_village)
        is_priority_category = admission.rte_parent_id.rte_category in (
            'orphan', 'disabled')
        if in_pocket and is_priority_category:
            return 0
        if in_pocket:
            return 1
        if is_priority_category:
            return 2
        return 3

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'rte.lottery.batch') or _('New')
        return super().create(vals_list)

    def action_mark_ready(self):
        for batch in self:
            if batch.state != 'draft':
                raise UserError(_('Only Draft batches can be marked Ready.'))
            if not batch.effective_seats:
                raise UserError(_(
                    'Course %s has no RTE seats configured.')
                    % batch.course_id.name)
            non_rte_admission_count = self.env['op.admission'].search_count([
                ('course_id', '=', batch.course_id.id),
                ('is_rte_applicant', '=', False),
            ])
            if not non_rte_admission_count:
                raise UserError(_(
                    'Course %s has no fee-paying (non-RTE) admissions -- a '
                    'school with zero paid admissions in an entry class '
                    'cannot take RTE admissions in that class '
                    '(para 9, point 09).') % batch.course_id.name)
            other_active = self.search([
                ('id', '!=', batch.id),
                ('course_id', '=', batch.course_id.id),
                ('academic_year_id', '=', batch.academic_year_id.id),
                ('state', 'in', ('ready', 'run', 'published')),
            ])
            if other_active:
                raise UserError(_(
                    'Course %s already has an active lottery batch (%s) '
                    'for this academic year. Only one batch may be active '
                    'per course/year to avoid over-allotment beyond the '
                    'configured RTE seats.')
                    % (batch.course_id.name, other_active[0].name))
            batch.write({'state': 'ready'})

    def run_lottery(self):
        """Deterministically shuffle eligible RTE applicants for the
        batch's course using ``random_seed``, and write rte.lottery.result
        rows: the first ``effective_seats`` entries become 'selected', the
        rest 'waitlisted'. Applicants are first split into four priority
        tiers -- own ward/village + orphan/disabled, own ward/village,
        rest of ULB/GP + orphan/disabled, rest of ULB/GP (para 5.1-5.4) --
        and each tier is independently shuffled (in that order) before
        ranks are assigned, so priority applicants always rank ahead of
        non-priority ones within the same catchment tier. Never deletes/
        overwrites existing results; guarded against re-running a batch
        already 'run' or 'published'.
        """
        for batch in self:
            if batch.state not in ('ready',):
                raise UserError(_(
                    'The lottery can only be run on a Ready batch. '
                    'Batches already Run or Published cannot be re-run.'))
            if batch.result_ids:
                raise UserError(_(
                    'This batch already has lottery results.'))

            admissions = self.env['op.admission'].search([
                ('is_rte_applicant', '=', True),
                ('rte_state', '=', 'doc_verified'),
                '|',
                ('course_id', '=', batch.course_id.id),
                ('rte_preference_ids.course_id', '=', batch.course_id.id),
            ])
            if not admissions:
                raise UserError(_(
                    'No document-verified RTE applicants found for '
                    'course %s.') % batch.course_id.name)

            # Build a deterministic, auditable ordering: sort by a stable
            # key (application_number) then hash it before seeding the
            # shuffle so the draw is reproducible from the seed alone.
            sorted_admissions = admissions.sorted(key=lambda a: a.application_number or '')
            names = [a.application_number or str(a.id) for a in sorted_admissions]
            applicant_hash = hashlib.sha256(
                '|'.join(sorted(names)).encode('utf-8')).hexdigest()

            rng = random.Random(batch.random_seed)
            tiers = [[], [], [], []]
            for admission in sorted_admissions:
                tier = self._get_priority_tier(admission, batch.course_id)
                tiers[tier].append(admission)
            shuffled = []
            for tier_admissions in tiers:
                rng.shuffle(tier_admissions)
                shuffled.extend(tier_admissions)

            seats = batch.effective_seats or 0
            result_vals = []
            for rank, admission in enumerate(shuffled, start=1):
                preference_matched = 0
                prefs = admission.rte_preference_ids.sorted('sequence')
                for idx, pref in enumerate(prefs, start=1):
                    if pref.course_id.id == batch.course_id.id:
                        preference_matched = idx
                        break
                result_type = 'selected' if rank <= seats else 'waitlisted'
                result_vals.append({
                    'batch_id': batch.id,
                    'admission_id': admission.id,
                    'rank': rank,
                    'result_type': result_type,
                    'preference_matched': preference_matched,
                })

            self.env['rte.lottery.result'].create(result_vals)
            batch.write({
                'state': 'run',
                'draw_date': fields.Datetime.now(),
                'applicant_hash': applicant_hash,
            })
            for result in batch.result_ids:
                if result.result_type == 'selected':
                    result.admission_id._set_rte_allotted(course_id=batch.course_id.id)
                else:
                    result.admission_id.write({'rte_state': 'waitlisted'})
            batch.message_post(
                body=_('Lottery run for %s applicants. Seed: %s, Hash: %s')
                % (len(shuffled), batch.random_seed, applicant_hash))

    def action_publish(self):
        for batch in self:
            if batch.state != 'run':
                raise UserError(_('Only a Run batch can be Published.'))
            batch.write({'state': 'published'})
            batch.message_post(body=_('Lottery results published.'))
