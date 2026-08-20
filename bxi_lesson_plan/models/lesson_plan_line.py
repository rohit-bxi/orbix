from odoo import fields, models


class BxiLessonPlanLine(models.Model):
    _name = 'bxi.lesson.plan.line'
    _description = 'Lesson Plan Line Item'
    _order = 'lesson_plan_id, sequence, id'

    lesson_plan_id = fields.Many2one('bxi.lesson.plan', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    line_type = fields.Selection([
        ('recall_question', 'Recall Question'),
        ('class_work', 'Class Work'),
        ('home_work', 'Home Work'),
        ('teaching_aid', 'Teaching Aid'),
        ('remark', 'Remark'),
    ], required=True)
    name = fields.Char('Description', required=True)
