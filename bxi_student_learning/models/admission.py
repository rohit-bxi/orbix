# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The app's Admission Application (Personal, Academic, Documents,
Statement, Review) on top of OpenEduCat admissions: who is filling it in,
which step they reached, the personal statement and the five document
slots. The application stays a draft until it is submitted."""
from odoo import fields, models

STEPS = [('personal', 'Personal'), ('academic', 'Academic'), ('documents', 'Documents'),
         ('statement', 'Statement'), ('review', 'Review')]

# slot -> (field, required, max files, label)
DOCUMENT_SLOTS = {
    'transcripts': ('bxi_transcript_ids', True, 5, 'Official Transcripts'),
    'test_scores': ('bxi_test_score_ids', True, 5, 'Standardized Test Scores'),
    'recommendations': ('bxi_recommendation_ids', True, 2, 'Letters of Recommendation'),
    'id_proof': ('bxi_id_proof_ids', True, 2, 'Government ID Proof'),
    'additional': ('bxi_additional_ids', False, 10, 'Additional Documents'),
}
REQUIRED_RECOMMENDATIONS = 2


def _attachments(relation, string):
    return fields.Many2many('ir.attachment', relation, 'admission_id', 'attachment_id', string=string, copy=False)


class OpAdmission(models.Model):
    _inherit = 'op.admission'

    bxi_applicant_user_id = fields.Many2one(
        'res.users', string='Applied From', index=True, copy=False,
        help='The app login that is filling in this application.')
    bxi_step = fields.Selection(STEPS, string='Application Step', default='personal', copy=False)
    bxi_statement = fields.Text('Personal Statement', copy=False)
    bxi_transcript_ids = _attachments('op_admission_bxi_transcript_rel', 'Official Transcripts')
    bxi_test_score_ids = _attachments('op_admission_bxi_test_score_rel', 'Standardized Test Scores')
    bxi_recommendation_ids = _attachments('op_admission_bxi_recommendation_rel', 'Letters of Recommendation')
    bxi_id_proof_ids = _attachments('op_admission_bxi_id_proof_rel', 'Government ID Proof')
    bxi_additional_ids = _attachments('op_admission_bxi_additional_rel', 'Additional Documents')

    def _bxi_missing_for_submit(self):
        """What still stops the application being submitted (step, key)."""
        self.ensure_one()
        missing = []
        for key in ('first_name', 'last_name', 'birth_date', 'email', 'mobile', 'gender'):
            if not self[key]:
                missing.append(('personal', key))
        for key in ('prev_institute_id', 'prev_course_id', 'prev_result'):
            if not self[key]:
                missing.append(('academic', key))
        for slot, (field, required, _max, _label) in DOCUMENT_SLOTS.items():
            needed = REQUIRED_RECOMMENDATIONS if slot == 'recommendations' else 1
            if required and len(self[field]) < needed:
                missing.append(('documents', slot))
        if not (self.bxi_statement or '').strip():
            missing.append(('statement', 'statement'))
        return missing
