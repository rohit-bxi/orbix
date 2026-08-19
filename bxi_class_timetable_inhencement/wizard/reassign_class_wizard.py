from odoo import _, fields, models
from odoo.exceptions import ValidationError


class BxiReassignClassWizard(models.TransientModel):
    _name = 'bxi.reassign.class.wizard'
    _description = 'Reassign Teacher to a Different Class'

    teacher_id = fields.Many2one('op.faculty', required=True)
    current_course_id = fields.Many2one('op.course', string='Current Class', required=True)
    current_batch_id = fields.Many2one('op.batch', string='Current Section', required=True,
                                        domain="[('course_id', '=', current_course_id)]")
    new_course_id = fields.Many2one('op.course', string='New Class', required=True)
    new_batch_id = fields.Many2one('op.batch', string='New Section', required=True,
                                    domain="[('course_id', '=', new_course_id)]")

    def action_reassign(self):
        self.ensure_one()
        current_timetable = self.env['bxi.timetable'].search([
            ('course_id', '=', self.current_course_id.id),
            ('batch_id', '=', self.current_batch_id.id),
        ], limit=1)
        lines = current_timetable.line_ids.filtered(
            lambda line: line.teacher_id == self.teacher_id) if current_timetable else self.env['bxi.timetable.line']
        if not lines:
            raise ValidationError(_('%(teacher)s has no periods in this Class/Section.',
                                     teacher=self.teacher_id.name))
        if current_timetable.locked:
            raise ValidationError(_('This timetable is locked. Unlock it before making changes.'))

        destination = self.env['bxi.timetable']._get_or_create(self.new_course_id.id, self.new_batch_id.id)
        if destination.locked:
            raise ValidationError(_('The destination timetable is locked. Unlock it before making changes.'))

        occupied_slots = {(line.day, line.timing_id.id) for line in destination.line_ids}
        conflicts = lines.filtered(lambda line: (line.day, line.timing_id.id) in occupied_slots)
        if conflicts:
            raise ValidationError(_(
                'Cannot reassign: the destination Class/Section already has periods scheduled '
                'at the same day/time as %(teacher)s.', teacher=self.teacher_id.name))

        lines.write({'timetable_id': destination.id})
