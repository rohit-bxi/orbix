from odoo import fields, models, api


class UniformPolicy(models.Model):
    _name = 'bxi.uniform.policy'
    _description = 'Uniform Policy (Required Set per Course/Gender/Season)'
    _rec_name = 'display_name'

    course_id = fields.Many2one('op.course', required=True)
    gender = fields.Selection([
        ('boy', 'Boy'),
        ('girl', 'Girl'),
        ('unisex', 'Unisex'),
    ], required=True, default='unisex')
    season = fields.Selection([
        ('summer', 'Summer'),
        ('winter', 'Winter'),
        ('all_season', 'All Season'),
        ('sports', 'Sports / PE'),
    ], required=True, default='all_season')
    line_ids = fields.One2many('bxi.uniform.policy.line', 'policy_id', string='Required Items')
    display_name = fields.Char(compute='_compute_display_name', store=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    _unique_course_gender_season = models.Constraint(
        'unique(course_id, gender, season)',
        'A uniform policy already exists for this Course, Gender and Season.',
    )

    @api.depends('course_id', 'gender', 'season')
    def _compute_display_name(self):
        for policy in self:
            policy.display_name = '%s - %s - %s' % (
                policy.course_id.name or '',
                dict(self._fields['gender'].selection).get(policy.gender, ''),
                dict(self._fields['season'].selection).get(policy.season, ''),
            )


class UniformPolicyLine(models.Model):
    _name = 'bxi.uniform.policy.line'
    _description = 'Uniform Policy Line'

    policy_id = fields.Many2one('bxi.uniform.policy', required=True, ondelete='cascade')
    product_tmpl_id = fields.Many2one(
        'product.template', string='Uniform Item', required=True,
        domain=[('is_uniform_item', '=', True)])
    quantity = fields.Float(default=1.0, required=True)
    is_mandatory = fields.Boolean(default=True)
