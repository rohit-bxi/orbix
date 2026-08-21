from odoo import api, fields, models


class OpCertificateType(models.Model):
    _name = 'op.certificate.type'
    _description = 'Certificate Type'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="Short code, also used as the numbering prefix, e.g. TC, CC, MRT.")
    category = fields.Selection([
        ('academic', 'Academic'),
        ('achievement', 'Achievement'),
        ('participation', 'Participation'),
        ('transfer', 'Transfer'),
        ('conduct', 'Conduct'),
        ('other', 'Other'),
    ], string='Category', default='academic', required=True)
    sequence_id = fields.Many2one('ir.sequence', readonly=True, copy=False)
    validity_months = fields.Integer(
        string='Validity (Months)', default=0,
        help="Number of months the certificate stays valid after issue. 0 means it never expires.")
    requires_approval = fields.Boolean(
        string='Requires Approval',
        help="If set, a certificate of this type cannot be issued until a Certificate Manager approves it.")
    body_html = fields.Html(
        string='Custom Certificate Text',
        help="Optional custom wording for the printed certificate. Leave empty to use the default layout.")
    active = fields.Boolean(default=True)
    certificate_count = fields.Integer(compute='_compute_certificate_count')

    _unique_certificate_type_code = models.Constraint(
        'unique(code)', 'Certificate type code must be unique!')

    @api.depends()
    def _compute_certificate_count(self):
        counts = self.env['op.certificate']._read_group(
            [('certificate_type_id', 'in', self.ids)],
            ['certificate_type_id'], ['__count'])
        count_by_type = {type_.id: count for type_, count in counts}
        for rec in self:
            rec.certificate_count = count_by_type.get(rec.id, 0)

    @api.model_create_multi
    def create(self, vals_list):
        types = super().create(vals_list)
        for rec in types:
            if not rec.sequence_id:
                rec.sequence_id = self.env['ir.sequence'].sudo().create({
                    'name': f'Certificate - {rec.name}',
                    'code': f'op.certificate.{rec.code.lower()}',
                    'prefix': f'{rec.code}/%(year)s/',
                    'padding': 4,
                    'company_id': False,
                })
        return types

    def action_view_certificates(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Certificates',
            'res_model': 'op.certificate',
            'view_mode': 'list,form',
            'domain': [('certificate_type_id', '=', self.id)],
            'context': {'default_certificate_type_id': self.id},
        }
