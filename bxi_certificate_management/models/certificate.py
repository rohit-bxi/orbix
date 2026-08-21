import base64
import uuid

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OpCertificate(models.Model):
    _name = 'op.certificate'
    _description = 'Student Certificate'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'certificate_number'
    _order = 'issue_date desc, id desc'

    certificate_number = fields.Char(readonly=True, copy=False)
    certificate_type_id = fields.Many2one(
        'op.certificate.type', string='Certificate Type',
        required=True, tracking=True)
    type_requires_approval = fields.Boolean(related='certificate_type_id.requires_approval')
    student_id = fields.Many2one(
        'op.student', string='Student', required=True,
        ondelete='cascade', tracking=True)
    course_id = fields.Many2one('op.course', string='Course')
    batch_id = fields.Many2one('op.batch', string='Batch')
    subject_id = fields.Many2one(
        'op.subject', string='Subject',
        help="Optional. Set for subject-wise certificates such as merit certificates.")
    issue_date = fields.Date(default=fields.Date.context_today, tracking=True)
    expiry_date = fields.Date(compute='_compute_expiry_date', store=True, readonly=False)
    issued_by = fields.Many2one(
        'res.users', string='Issued By', default=lambda self: self.env.user)
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    verification_code = fields.Char(
        readonly=True, copy=False, default=lambda self: str(uuid.uuid4()))
    attachment_id = fields.Many2one('ir.attachment', readonly=True, copy=False)
    remarks = fields.Text(help="Internal note, e.g. purpose of issue.")
    revoke_reason = fields.Text(readonly=True, copy=False)
    reminder_sent = fields.Boolean(copy=False)
    expiring_soon = fields.Boolean(
        copy=False,
        help="Set when the certificate is issued and its expiry date falls within 30 days. "
             "Refreshed daily by cron and on issue.")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('generated', 'Generated'),
        ('issued', 'Issued'),
        ('revoked', 'Revoked'),
        ('expired', 'Expired'),
    ], default='draft', tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    _unique_certificate_verification_code = models.Constraint(
        'unique(verification_code)', 'Verification code must be unique!')

    @api.depends('issue_date', 'certificate_type_id.validity_months')
    def _compute_expiry_date(self):
        for rec in self:
            months = rec.certificate_type_id.validity_months
            rec.expiry_date = (
                rec.issue_date + relativedelta(months=months)
                if rec.issue_date and months else False)

    @api.onchange('student_id')
    def _onchange_student_id(self):
        if self.student_id and self.student_id.course_detail_ids:
            course_detail = self.student_id.course_detail_ids.filtered(
                lambda line: line.state == 'running') or self.student_id.course_detail_ids[:1]
            self.course_id = course_detail[:1].course_id
            self.batch_id = course_detail[:1].batch_id

    def action_generate(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            if not rec.certificate_number:
                rec.certificate_number = self.env['ir.sequence'].next_by_code(
                    rec.certificate_type_id.sequence_id.code)
            rec.state = 'generated'

    def action_issue(self):
        for rec in self:
            if rec.state not in ('generated',):
                raise UserError(_('Only a generated certificate can be issued.'))
            if rec.certificate_type_id.requires_approval and not rec.approved_by:
                raise UserError(_(
                    'This certificate type requires manager approval before it can be issued.'))
            rec.attachment_id = rec._generate_pdf_attachment()
            rec.state = 'issued'
            rec._refresh_expiring_soon()

    def action_approve(self):
        for rec in self:
            rec.approved_by = self.env.user

    def action_reset_to_draft(self):
        self.write({'state': 'draft', 'certificate_number': False})

    def action_print(self):
        self.ensure_one()
        return self.env.ref('bxi_certificate_management.action_report_certificate').report_action(self)

    def _generate_pdf_attachment(self):
        self.ensure_one()
        report = self.env.ref('bxi_certificate_management.action_report_certificate')
        pdf_content, _content_type = report.sudo()._render_qweb_pdf(
            'bxi_certificate_management.certificate_pdf_template', res_ids=self.ids)
        attachment = self.env['ir.attachment'].sudo().create({
            'name': f'{self.certificate_number or self.certificate_type_id.name}.pdf',
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        return attachment

    def action_revoke(self, reason):
        self.ensure_one()
        self.write({'state': 'revoked', 'revoke_reason': reason})
        self.message_post(body=_('Certificate revoked. Reason: %s') % reason)

    def action_open_revoke_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Revoke Certificate'),
            'res_model': 'op.certificate.revoke.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_certificate_id': self.id},
        }

    def _refresh_expiring_soon(self):
        today = fields.Date.context_today(self)
        horizon = today + relativedelta(days=30)
        for rec in self:
            rec.expiring_soon = bool(
                rec.state == 'issued' and rec.expiry_date
                and today <= rec.expiry_date <= horizon)

    def _cron_expire_certificates(self):
        today = fields.Date.context_today(self)
        horizon = today + relativedelta(days=30)

        expired = self.search([
            ('state', '=', 'issued'),
            ('expiry_date', '!=', False),
            ('expiry_date', '<', today),
        ])
        expired.write({'state': 'expired', 'expiring_soon': False})

        expiring_soon = self.search([
            ('state', '=', 'issued'),
            ('expiry_date', '!=', False),
            ('expiry_date', '>=', today),
            ('expiry_date', '<=', horizon),
        ])
        stale = self.search([('expiring_soon', '=', True), ('id', 'not in', expiring_soon.ids)])
        stale.write({'expiring_soon': False})
        expiring_soon.write({'expiring_soon': True})

    def _cron_send_expiry_reminders(self):
        today = fields.Date.context_today(self)
        reminder_horizon = today + relativedelta(days=30)
        template = self.env.ref(
            'bxi_certificate_management.mail_template_certificate_expiry', raise_if_not_found=False)
        if not template:
            return
        due = self.search([
            ('state', '=', 'issued'),
            ('reminder_sent', '=', False),
            ('expiry_date', '!=', False),
            ('expiry_date', '<=', reminder_horizon),
            ('expiry_date', '>=', today),
        ])
        for rec in due:
            if rec.student_id.email:
                template.send_mail(rec.id, force_send=False)
            rec.reminder_sent = True
