from odoo import _, fields, models


class BxiLessonPlanReviewWizard(models.TransientModel):
    _name = 'bxi.lesson.plan.review.wizard'
    _description = 'Review Lesson Plan'

    lesson_plan_id = fields.Many2one('bxi.lesson.plan', required=True)
    decision = fields.Selection([
        ('approved', 'Approve'),
        ('rejected', 'Request Revise'),
    ], required=True)
    feedback = fields.Text('Feedback')

    def action_confirm(self):
        self.ensure_one()
        self.lesson_plan_id.state = self.decision
        default_message = _('Lesson plan approved.') if self.decision == 'approved' \
            else _('Revision requested.')
        self.lesson_plan_id.message_post(body=self.feedback or default_message)
        return {'type': 'ir.actions.act_window_close'}
