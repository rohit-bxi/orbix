# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Common documents (paras 2.4/2.6) plus one entry per RTE_CATEGORIES value
# used to satisfy category-specific checklists (paras 7.2.1/7.2.2).
DOC_TYPES = [
    ('photo', 'Applicant Photograph'),
    ('address_proof', 'Address Proof'),
    ('birth_cert', 'Birth/Age Certificate'),
    ('income_cert', 'Income Certificate'),
    ('category_cert', 'Caste/Category Certificate'),
    ('disability_cert', 'Disability Certificate'),
    ('orphan_declaration', 'Orphan Declaration (Orphanage)'),
    ('hiv_cancer_report', 'HIV/Cancer Diagnostic Centre Report'),
    ('war_widow_cert', 'War Widow Certificate'),
    ('bpl_card', 'BPL Card'),
    ('ward_change_cert', 'Ward Delimitation Certificate (Appendix-5)'),
]

VERIFICATION_STATUSES = [
    ('pending', 'Pending'),
    ('verified', 'Verified'),
    ('rejected', 'Rejected'),
]


class RteDocument(models.Model):
    _name = 'rte.document'
    _description = 'RTE Admission Document'
    _order = 'id'

    admission_id = fields.Many2one(
        'op.admission', string='Admission', required=True, ondelete='cascade')
    doc_type = fields.Selection(DOC_TYPES, string='Document Type', required=True)
    document = fields.Binary(string='Document', attachment=True)
    document_filename = fields.Char(string='File Name')
    issue_date = fields.Date(
        string='Issue Date',
        help='Date the document was issued. Must not be later than the '
             'lottery draw date for the batch the applicant is drawn in '
             '(para 4.7).')
    verification_status = fields.Selection(
        VERIFICATION_STATUSES, string='Verification Status',
        default='pending', required=True)
    remarks = fields.Char(string='Remarks')

    @api.constrains('issue_date', 'admission_id')
    def _check_issue_date_before_lottery(self):
        """Para 4.7: documents issued on or after the lottery draw date
        are not valid. Only checked once the applicant has actually been
        drawn in a batch with a recorded draw_date."""
        for document in self:
            if not document.issue_date:
                continue
            results = self.env['rte.lottery.result'].search([
                ('admission_id', '=', document.admission_id.id),
                ('batch_id.draw_date', '!=', False),
            ])
            for result in results:
                draw_date = result.batch_id.draw_date.date()
                if document.issue_date >= draw_date:
                    raise ValidationError(_(
                        'Document "%s" is dated %s, which is on or after '
                        'the lottery draw date (%s) for this applicant. '
                        'Documents must predate the lottery (para 4.7).')
                        % (document.doc_type, document.issue_date, draw_date))
