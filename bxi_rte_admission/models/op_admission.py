# -*- coding: utf-8 -*-

from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .op_course import RTE_ENTRY_CLASS_MIN_AGE, CATCHMENT_AREA_TYPES

# Document types (rte.document DOC_TYPES) required in addition to the
# common set below, keyed by the applicant's op.parent.rte_category
# (paras 7.2.1/7.2.2). Advisory only -- see rte_missing_document_types.
RTE_COMMON_REQUIRED_DOC_TYPES = {'photo', 'address_proof', 'birth_cert'}
RTE_CATEGORY_REQUIRED_DOC_TYPES = {
    'weaker_section': {'income_cert'},
    'sc': {'category_cert'},
    'st': {'category_cert'},
    'orphan': {'orphan_declaration'},
    'hiv_cancer': {'hiv_cancer_report'},
    'war_widow': {'war_widow_cert'},
    'disabled': {'disability_cert'},
    'obc_sbc_income': {'category_cert', 'income_cert'},
    'bpl': {'bpl_card'},
}

# RTE states that mean "this child holds/held an RTE seat" for the
# one-application-only rule (para 4.4/Appendix-4 Q5).
RTE_ACTIVE_SEAT_STATES = ('allotted', 'confirmed', 'admitted')

RTE_STATES = [
    ('draft', 'Draft'),
    ('doc_verified', 'Documents Verified'),
    ('doc_rejected', 'Documents Rejected'),
    ('lottery_pending', 'Lottery Pending'),
    ('allotted', 'Allotted'),
    ('waitlisted', 'Waitlisted'),
    ('confirmed', 'Confirmed'),
    ('admitted', 'Admitted'),
    ('lapsed', 'Lapsed'),
]


class OpAdmission(models.Model):
    _inherit = 'op.admission'

    is_rte_applicant = fields.Boolean(string='RTE Applicant')
    rte_preference_ids = fields.One2many(
        'rte.school.preference', 'admission_id', string='School Preferences')
    rte_document_ids = fields.One2many(
        'rte.document', 'admission_id', string='RTE Documents')
    rte_state = fields.Selection(
        RTE_STATES, string='RTE Status', default='draft', tracking=True)
    verified_by = fields.Many2one(
        'res.users', string='Verified By', copy=False)
    verification_date = fields.Datetime(
        string='Verification Date', copy=False)
    rejection_reason = fields.Text(string='Rejection Reason')
    confirmation_deadline = fields.Date(
        string='Confirmation Deadline',
        help='Date by which an Allotted RTE applicant must confirm the '
             'seat, else it is offered to the next waitlisted applicant.')
    doc_verification_deadline = fields.Date(
        string='Document Verification Deadline',
        help='SLA date by which RTE documents should be verified.')
    rte_area_type = fields.Selection(
        CATCHMENT_AREA_TYPES, string='Residence Area Type',
        help='Whether the applicant resides under an urban local body '
             'ward or a rural gram panchayat village (para 2.1).')
    rte_urban_body = fields.Char(
        string='Residence Urban Local Body')
    rte_ward = fields.Char(
        string='Residence Ward No.')
    rte_gram_panchayat = fields.Char(
        string='Residence Gram Panchayat')
    rte_village = fields.Char(
        string='Residence Village')
    rte_aadhaar_number = fields.Char(
        string='Aadhaar Number', size=12,
        help='Child\'s 12-digit Aadhaar number (para 4.3).')
    rte_aadhaar_enrollment_number = fields.Char(
        string='Aadhaar Enrolment Number', size=16,
        help='16-digit Aadhaar enrolment number, used when the Aadhaar '
             'number itself is not yet available (para 4.3).')
    rte_religion = fields.Char(
        string='Religion',
        help='Applicant\'s religion (Appendix-2 application form, field 1.7).')
    rte_caste_category = fields.Selection([
        ('sc', 'SC'),
        ('st', 'ST'),
        ('obc', 'OBC'),
        ('sbc', 'SBC'),
        ('gen', 'General'),
    ], string='Caste Category',
        help='General caste category (Appendix-2 form, field 1.6), '
             'distinct from the RTE weaker-section/disadvantaged-group '
             'category recorded on the parent record.')
    rte_cwsn_category = fields.Char(
        string='CWSN Special-Needs Category',
        help='Category of special need for a Child With Special Needs '
             '(Appendix-2 form, field 1.8), e.g. the specific disability. '
             'Applicable when the applicant is in the Disabled RTE category.')
    rte_father_aadhaar = fields.Char(
        string="Father's Aadhaar Number", size=12,
        help='Appendix-2 application form, field 2.2.')
    rte_mother_aadhaar = fields.Char(
        string="Mother's Aadhaar Number", size=12,
        help='Appendix-2 application form, field 2.4.')
    rte_guardian_aadhaar = fields.Char(
        string="Guardian's Aadhaar Number", size=12,
        help='Appendix-2 application form, field 2.6 (only when a '
             'guardian, rather than a parent, is applying on the child\'s '
             'behalf).')
    rte_pincode = fields.Char(
        string='Residence Pin Code',
        help='Appendix-2 application form, section 3.')
    rte_block = fields.Char(
        string='Residence Block',
        help='Appendix-2 application form, section 3.')
    rte_district = fields.Char(
        string='Residence District',
        help='Appendix-2 application form, section 3.')
    rte_dropout_date = fields.Date(
        string='Dropout Date', copy=False,
        help='Date the RTE-admitted child left the school, if applicable. '
             'Drives the installment proration on reimbursement claims '
             '(Appendix-4 Q1): only the first installment is reimbursed '
             'if this date falls on or before 31 August of the academic '
             'year the child was admitted in.')
    rte_is_voluntary_transfer = fields.Boolean(
        string='Voluntarily Transferred to Another School', copy=False,
        help='Set when the parent voluntarily moved the child to another '
             'school. Such a transfer forfeits any further fee '
             'reimbursement for this seat (Appendix-1).')
    rte_grievance_ids = fields.One2many(
        'rte.grievance', 'admission_id', string='Grievances')
    rte_parent_id = fields.Many2one(
        'op.parent', string='RTE Parent', compute='_compute_rte_parent_id',
        store=True,
        help='The op.parent record sharing this admission\'s partner, '
             'used to read the RTE category for the document checklist.')
    rte_missing_document_types = fields.Char(
        string='Missing Required Documents',
        compute='_compute_rte_missing_document_types',
        help='Document types still not attached (or not yet verified) '
             'for this applicant\'s category, per paras 7.2.1/7.2.2. '
             'Advisory -- does not block verification.')

    @api.depends('partner_id')
    def _compute_rte_parent_id(self):
        for admission in self:
            admission.rte_parent_id = self.env['op.parent'].search(
                [('name', '=', admission.partner_id.id)], limit=1
            ) if admission.partner_id else False

    def _get_rte_required_doc_types(self):
        self.ensure_one()
        required = set(RTE_COMMON_REQUIRED_DOC_TYPES)
        category = self.rte_parent_id.rte_category
        required |= RTE_CATEGORY_REQUIRED_DOC_TYPES.get(category, set())
        return required

    @api.depends('rte_parent_id.rte_category', 'rte_document_ids.doc_type',
                 'rte_document_ids.verification_status')
    def _compute_rte_missing_document_types(self):
        for admission in self:
            if not admission.is_rte_applicant:
                admission.rte_missing_document_types = False
                continue
            required = admission._get_rte_required_doc_types()
            attached = set(admission.rte_document_ids.filtered(
                lambda d: d.verification_status != 'rejected').mapped('doc_type'))
            missing = required - attached
            admission.rte_missing_document_types = ', '.join(sorted(missing)) or False

    @api.constrains('is_rte_applicant', 'rte_aadhaar_number',
                     'rte_aadhaar_enrollment_number')
    def _check_rte_aadhaar_required(self):
        for admission in self:
            if admission.is_rte_applicant and not (
                    admission.rte_aadhaar_number
                    or admission.rte_aadhaar_enrollment_number):
                raise ValidationError(_(
                    'Either an Aadhaar Number or an Aadhaar Enrolment '
                    'Number is required for an RTE application (para 4.3).'))

    @api.constrains('is_rte_applicant', 'rte_state', 'rte_aadhaar_number',
                     'rte_aadhaar_enrollment_number')
    def _check_rte_single_application(self):
        """Para 4.4: a child already holding (or having held) an RTE seat
        cannot apply again. Matched on Aadhaar number/enrolment number
        since that's the only stable per-child identifier captured."""
        for admission in self:
            if not admission.is_rte_applicant:
                continue
            if admission.rte_state not in RTE_ACTIVE_SEAT_STATES:
                continue
            domain = [
                ('id', '!=', admission.id),
                ('is_rte_applicant', '=', True),
                ('rte_state', 'in', RTE_ACTIVE_SEAT_STATES),
            ]
            id_domain = []
            if admission.rte_aadhaar_number:
                id_domain.append(('rte_aadhaar_number', '=', admission.rte_aadhaar_number))
            if admission.rte_aadhaar_enrollment_number:
                id_domain.append(
                    ('rte_aadhaar_enrollment_number', '=',
                     admission.rte_aadhaar_enrollment_number))
            if not id_domain:
                continue
            duplicate = self.search(domain + ['|'] * (len(id_domain) - 1) + id_domain, limit=1)
            if duplicate:
                raise ValidationError(_(
                    'This child (Aadhaar %s) already holds an RTE seat '
                    'under application %s and cannot apply again '
                    '(para 4.4).') % (
                        admission.rte_aadhaar_number
                        or admission.rte_aadhaar_enrollment_number,
                        duplicate.application_number))

    @api.constrains('is_rte_applicant', 'rte_area_type', 'rte_urban_body',
                     'rte_ward', 'rte_gram_panchayat', 'rte_village',
                     'course_id')
    def _check_rte_catchment_eligibility(self):
        """Para 2.1: a child residing outside the school's urban local
        body / gram panchayat is not eligible at all, regardless of
        ward/village. Only enforced once both the school and the
        applicant have their catchment fields filled in, so records
        created before this data is captured aren't retroactively
        blocked."""
        for admission in self:
            if not admission.is_rte_applicant:
                continue
            course = admission.course_id
            if not (course.catchment_area_type and admission.rte_area_type):
                continue
            if course.catchment_area_type != admission.rte_area_type:
                raise ValidationError(_(
                    'The applicant\'s residence area type (%s) does not '
                    'match the school\'s catchment area type (%s).')
                    % (admission.rte_area_type, course.catchment_area_type))
            if admission.rte_area_type == 'urban':
                if not admission.rte_urban_body:
                    continue
                if admission.rte_urban_body != course.catchment_urban_body:
                    raise ValidationError(_(
                        'This applicant resides outside the urban local '
                        'body (%s) served by %s and is not eligible for '
                        'an RTE seat there (para 2.1).')
                        % (course.catchment_urban_body, course.name))
            else:
                if not admission.rte_gram_panchayat:
                    continue
                if admission.rte_gram_panchayat != course.catchment_gram_panchayat:
                    raise ValidationError(_(
                        'This applicant resides outside the gram '
                        'panchayat (%s) served by %s and is not eligible '
                        'for an RTE seat there (para 2.1).')
                        % (course.catchment_gram_panchayat, course.name))

    @api.constrains('is_rte_applicant', 'birth_date', 'course_id')
    def _check_rte_age_band(self):
        """Para 2.3: each entry class has a fixed birth-date window,
        expressed relative to the academic year's start (1 April). Only
        enforced when the course declares an rte_entry_class, so courses
        that haven't been classified yet don't block admissions."""
        for admission in self:
            if not admission.is_rte_applicant or not admission.birth_date:
                continue
            entry_class = admission.course_id.rte_entry_class
            if not entry_class:
                continue
            academic_year = admission.register_id.academic_years_id
            if not academic_year or not academic_year.start_date:
                continue
            session_year = academic_year.start_date.year
            min_age = RTE_ENTRY_CLASS_MIN_AGE[entry_class]
            window_start = date(session_year - min_age - 1, 4, 1)
            window_end = date(session_year - min_age, 3, 31)
            if not (window_start <= admission.birth_date <= window_end):
                raise ValidationError(_(
                    'For %s, the applicant\'s date of birth must fall '
                    'between %s and %s (para 2.3). Given: %s.')
                    % (dict(admission.course_id._fields['rte_entry_class']
                            .selection)[entry_class],
                       window_start, window_end, admission.birth_date))

    def action_file_grievance(self, description):
        """Para 6.6/8.3: a parent dissatisfied with a document-verification
        decision can file an online grievance against it. Decided only on
        documents already on file -- no new documents may be attached."""
        self.ensure_one()
        if self.rte_state != 'doc_rejected':
            raise UserError(_(
                'A grievance can only be filed against a Rejected document '
                'verification decision.'))
        grievance = self.env['rte.grievance'].create({
            'admission_id': self.id,
            'description': description,
        })
        grievance.action_submit()
        return grievance

    def action_verify_documents(self):
        for admission in self:
            if admission.rte_state not in ('draft', 'doc_rejected'):
                raise UserError(_(
                    'Documents can only be verified from Draft or '
                    'Rejected status.'))
            admission.rte_document_ids.write({'verification_status': 'verified'})
            admission.write({
                'rte_state': 'doc_verified',
                'verified_by': self.env.user.id,
                'verification_date': fields.Datetime.now(),
                'rejection_reason': False,
            })
            admission.message_post(
                body=_('RTE documents verified by %s.') % self.env.user.name)

    def action_reject_documents(self):
        for admission in self:
            if admission.rte_state not in ('draft', 'doc_verified'):
                raise UserError(_(
                    'Documents can only be rejected from Draft or '
                    'Verified status.'))
            admission.rte_document_ids.write({'verification_status': 'rejected'})
            admission.write({
                'rte_state': 'doc_rejected',
                'verified_by': self.env.user.id,
                'verification_date': fields.Datetime.now(),
            })
            reason = admission.rejection_reason or _('No reason provided.')
            admission.message_post(
                body=_('RTE documents rejected by %s. Reason: %s')
                % (self.env.user.name, reason))

    def action_confirm_admission(self):
        for admission in self:
            if admission.rte_state not in ('allotted', 'waitlisted'):
                raise UserError(_(
                    'Only Allotted or Waitlisted applications can be '
                    'confirmed.'))
            admission.write({'rte_state': 'confirmed'})
            admission.message_post(
                body=_('RTE admission confirmed by %s.') % self.env.user.name)

    def action_mark_admitted(self):
        for admission in self:
            if admission.rte_state != 'confirmed':
                raise UserError(_(
                    'Only Confirmed applications can be marked Admitted.'))
            admission.write({'rte_state': 'admitted'})
            admission.message_post(
                body=_('RTE applicant marked Admitted by %s.') % self.env.user.name)

    def action_mark_lapsed(self):
        for admission in self:
            if admission.rte_state not in ('allotted', 'waitlisted', 'confirmed'):
                raise UserError(_(
                    'Only Allotted, Waitlisted or Confirmed applications '
                    'can be marked Lapsed.'))
            admission.write({'rte_state': 'lapsed'})
            admission.message_post(
                body=_('RTE application marked Lapsed by %s.') % self.env.user.name)

    @api.model
    def _cron_promote_waitlist(self):
        """Lapse Allotted applications past their confirmation deadline and
        promote the next Waitlisted result on the same lottery batch to
        Selected, allotting that applicant instead."""
        today = fields.Date.context_today(self)
        expired = self.search([
            ('rte_state', '=', 'allotted'),
            ('is_rte_applicant', '=', True),
            ('confirmation_deadline', '!=', False),
            ('confirmation_deadline', '<', today),
        ])
        for admission in expired:
            admission.action_mark_lapsed()
            result = self.env['rte.lottery.result'].search([
                ('admission_id', '=', admission.id),
                ('result_type', '=', 'selected'),
            ], limit=1)
            if not result:
                continue
            next_waitlisted = self.env['rte.lottery.result'].search([
                ('batch_id', '=', result.batch_id.id),
                ('result_type', '=', 'waitlisted'),
            ], order='rank', limit=1)
            if next_waitlisted:
                next_waitlisted.write({'result_type': 'selected'})
                next_waitlisted.admission_id.write({'rte_state': 'allotted'})
                next_waitlisted.admission_id.message_post(
                    body=_('Promoted from waitlist after seat %s lapsed.')
                    % admission.application_number)

    @api.model
    def _cron_confirmation_deadline_reminder(self):
        """Post a chatter reminder on Allotted RTE applications whose
        confirmation deadline is within the configured lead time
        (bxi_rte_admission.confirmation_reminder_days, default 3 days)."""
        today = fields.Date.context_today(self)
        lead_days = int(self.env['ir.config_parameter'].sudo().get_param(
            'bxi_rte_admission.confirmation_reminder_days', default='3'))
        upcoming = today + timedelta(days=lead_days)
        admissions = self.search([
            ('rte_state', '=', 'allotted'),
            ('is_rte_applicant', '=', True),
            ('confirmation_deadline', '!=', False),
            ('confirmation_deadline', '>=', today),
            ('confirmation_deadline', '<=', upcoming),
        ])
        for admission in admissions:
            admission.message_post(
                body=_('Reminder: confirmation deadline for this RTE '
                       'allotment is %s.') % admission.confirmation_deadline)

    @api.model
    def _cron_doc_verification_sla_alert(self):
        """Post a chatter alert on RTE applications still in Draft whose
        document verification SLA deadline has passed."""
        today = fields.Date.context_today(self)
        overdue = self.search([
            ('rte_state', '=', 'draft'),
            ('is_rte_applicant', '=', True),
            ('doc_verification_deadline', '!=', False),
            ('doc_verification_deadline', '<', today),
        ])
        for admission in overdue:
            admission.message_post(
                body=_('SLA alert: RTE document verification is overdue '
                       '(deadline was %s).') % admission.doc_verification_deadline)
