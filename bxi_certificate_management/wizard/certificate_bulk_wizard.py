from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OpCertificateBulkWizard(models.TransientModel):
    _name = 'op.certificate.bulk.wizard'
    _description = 'Bulk Issue Certificates'

    certificate_type_id = fields.Many2one('op.certificate.type', string='Certificate Type', required=True)
    course_id = fields.Many2one('op.course', string='Course')
    batch_id = fields.Many2one('op.batch', string='Batch')
    issue_date = fields.Date(default=fields.Date.context_today, required=True)
    student_ids = fields.Many2many('op.student', string='Students')

    @api.onchange('course_id', 'batch_id')
    def _onchange_course_batch(self):
        if not self.course_id and not self.batch_id:
            self.student_ids = False
            return
        domain = [('state', '=', 'running')]
        if self.batch_id:
            domain.append(('batch_id', '=', self.batch_id.id))
        elif self.course_id:
            domain.append(('course_id', '=', self.course_id.id))
        course_details = self.env['op.student.course'].search(domain)
        self.student_ids = course_details.mapped('student_id')

    def action_create_certificates(self):
        self.ensure_one()
        if not self.student_ids:
            raise UserError(_('Select at least one student.'))
        certificates = self.env['op.certificate']
        for student in self.student_ids:
            course_detail = student.course_detail_ids.filtered(
                lambda line: line.state == 'running') or student.course_detail_ids[:1]
            certificates |= self.env['op.certificate'].create({
                'certificate_type_id': self.certificate_type_id.id,
                'student_id': student.id,
                'course_id': self.course_id.id or course_detail[:1].course_id.id,
                'batch_id': self.batch_id.id or course_detail[:1].batch_id.id,
                'issue_date': self.issue_date,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Certificates',
            'res_model': 'op.certificate',
            'view_mode': 'list,form',
            'domain': [('id', 'in', certificates.ids)],
        }
