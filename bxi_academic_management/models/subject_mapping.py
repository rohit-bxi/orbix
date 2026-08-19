from odoo import api, fields, models


class BxiSubjectMapping(models.Model):
    _name = 'bxi.subject.mapping'
    _description = 'Subject Mapping (Subject / Class / Teacher / Curriculum)'
    _order = 'curriculum_id, class_id, subject_id'
    _rec_name = 'display_name'

    subject_id = fields.Many2one('op.subject', string='Subject', required=True)
    class_id = fields.Many2one('op.course', string='Class', required=True)
    teacher_id = fields.Many2one('op.faculty', string='Teacher Name', required=True)
    curriculum_id = fields.Many2one('bxi.curriculum', string='Curriculum', required=True)
    active = fields.Boolean(default=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _unique_subject_class_curriculum = models.Constraint(
        'unique(subject_id, class_id, curriculum_id)',
        'This Subject is already mapped for this Class and Curriculum.',
    )

    @api.depends('subject_id', 'class_id', 'teacher_id')
    def _compute_display_name(self):
        for mapping in self:
            mapping.display_name = '%s - %s - %s' % (
                mapping.subject_id.name or '',
                mapping.class_id.name or '',
                mapping.teacher_id.name or '',
            )
