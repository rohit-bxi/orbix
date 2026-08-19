from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class OpBatchClassManager(models.Model):
    _inherit = 'op.batch'

    capacity = fields.Integer('Capacity')
    class_teacher_id = fields.Many2one('op.faculty', string='Assign Teacher')
    description = fields.Text('Description')

    def _generate_batch_code(self, course_id, name):
        course = self.env['op.course'].browse(course_id)
        base = ('%s-%s' % (course.code, name)).upper().replace(' ', '-')
        code = base
        suffix = 1
        while self.search_count([('code', '=', code)]):
            suffix += 1
            code = '%s-%s' % (base, suffix)
        return code

    def _get_default_academic_year_dates(self):
        today = fields.Date.context_today(self)
        year = self.env['op.academic.year'].search([
            ('start_date', '<=', today), ('end_date', '>=', today),
        ], limit=1)
        if not year:
            year = self.env['op.academic.year'].search([], order='start_date desc', limit=1)
        if year:
            return year.start_date, year.end_date
        return today, today + relativedelta(years=1)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') and vals.get('course_id') and vals.get('name'):
                vals['code'] = self._generate_batch_code(vals['course_id'], vals['name'])
            if not vals.get('start_date') or not vals.get('end_date'):
                start_date, end_date = self._get_default_academic_year_dates()
                vals.setdefault('start_date', start_date)
                vals.setdefault('end_date', end_date)
        return super().create(vals_list)
