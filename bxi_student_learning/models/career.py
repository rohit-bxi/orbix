# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Career guidance (the dashboard's "Career Recommendations"): each career
names the subjects it leans on; a student's match is the weighted average
of their own results in those subjects. Rules, not AI - the school edits
the careers and weights."""
from collections import defaultdict

from odoo import api, fields, models

DEMAND = [('high', 'High Demand'), ('growing', 'Growing'), ('stable', 'Stable')]
MIN_RESULTS = 1


class BxiCareer(models.Model):
    _name = 'bxi.career'
    _description = 'Career'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    description = fields.Text(translate=True)
    icon = fields.Char(help='Icon name the app shows, e.g. palette, scale, heart, code.')
    demand = fields.Selection(DEMAND, default='stable', required=True)
    sequence = fields.Integer(default=10)
    subject_line_ids = fields.One2many('bxi.career.subject', 'career_id', string='Subjects')
    active = fields.Boolean(default=True)

    _unique_name = models.Constraint('unique(name)', 'This career already exists.')

    @api.model
    def _bxi_recommend(self, student, limit=4):
        """[{career, match, matched_subjects}] best first, from the student's
        subject percentages. Careers with no matching subject result are
        left out."""
        scores = student._bxi_subject_scores()
        if not scores:
            return []
        result = []
        for career in self.sudo().search([]):
            weighted, weights, matched = 0.0, 0.0, []
            total_weight = sum(career.subject_line_ids.mapped('weight')) or 1.0
            for line in career.subject_line_ids:
                keyword = (line.keyword or '').strip().lower()
                hits = [pct for name, pct in scores.items() if keyword and keyword in name.lower()]
                if not hits:
                    continue
                weighted += line.weight * (sum(hits) / len(hits))
                weights += line.weight
                matched.append(line.keyword)
            if weights:
                # Scaled by how much of the career's subject mix the results
                # cover: a top mark in the one subject that matched must not
                # beat a career the student's results back on every side.
                coverage = weights / total_weight
                match = (weighted / weights) * (0.5 + 0.5 * coverage)
                result.append({'career': career, 'match': round(match), 'matched_subjects': matched})
        result.sort(key=lambda row: (-row['match'], row['career'].sequence, row['career'].name))
        return result[:limit]


class BxiCareerSubject(models.Model):
    _name = 'bxi.career.subject'
    _description = 'Career Subject Weight'

    career_id = fields.Many2one('bxi.career', required=True, ondelete='cascade', index=True)
    keyword = fields.Char('Subject Keyword', required=True,
                          help='Matched in subject names, ignoring case, e.g. "Math" matches "Mathematics".')
    weight = fields.Float(default=1.0, required=True)


class OpStudent(models.Model):
    _inherit = 'op.student'

    def _bxi_subject_scores(self):
        """{subject name: average %} from published exam marks and graded
        online tests."""
        self.ensure_one()
        totals = defaultdict(list)
        for line in self.env['op.result.line'].sudo().search([('student_id', '=', self.id)]):
            exam = line.exam_id
            if exam.subject_id and exam.total_marks:
                totals[exam.subject_id.name].append(100.0 * line.marks / exam.total_marks)
        if 'bxi.assessment.submission' in self.env:
            submissions = self.env['bxi.assessment.submission'].sudo().search(
                [('student_id', '=', self.id), ('status', 'in', ('auto_graded', 'reviewed'))])
            for submission in submissions:
                subject = submission.exam_id.subject_id
                if subject and submission.max_score:
                    totals[subject.name].append(100.0 * submission.total_score / submission.max_score)
        return {name: round(sum(values) / len(values), 1) for name, values in totals.items()
                if len(values) >= MIN_RESULTS}
