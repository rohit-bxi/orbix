# -*- coding: utf-8 -*-
from odoo import models, fields, api


class LabExperimentResult(models.Model):
    _name = 'lab.experiment.result'
    _description = 'Lab Experiment Result'
    _rec_name = 'student_id'

    session_id = fields.Many2one('lab.session', string='Session', required=True, ondelete='cascade')
    experiment_id = fields.Many2one('lab.experiment', string='Experiment', required=True)
    student_id = fields.Many2one('op.student', string='Student', required=True, ondelete='cascade')
    max_marks = fields.Float(related='experiment_id.max_marks', string='Max Marks')
    marks_obtained = fields.Float(string='Marks Obtained')
    grade = fields.Char(compute='_compute_grade', string='Grade', store=True)
    remark = fields.Char(string='Remark')

    @api.depends('marks_obtained', 'max_marks')
    def _compute_grade(self):
        for rec in self:
            if not rec.max_marks:
                rec.grade = ''
                continue
            pct = (rec.marks_obtained / rec.max_marks) * 100
            if pct >= 90:
                rec.grade = 'A+'
            elif pct >= 80:
                rec.grade = 'A'
            elif pct >= 70:
                rec.grade = 'B'
            elif pct >= 60:
                rec.grade = 'C'
            elif pct >= 40:
                rec.grade = 'D'
            else:
                rec.grade = 'F'
