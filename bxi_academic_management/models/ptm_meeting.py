from odoo import fields, models


class BxiPtmMeeting(models.Model):
    _name = 'bxi.ptm.meeting'
    _description = 'Parent-Teacher Meeting'
    _inherit = ['mail.thread']
    _order = 'date desc, time desc'

    name = fields.Char('PTM Name', required=True, tracking=True)
    date = fields.Date('Date', required=True, tracking=True)
    time = fields.Float('Time', required=True, tracking=True)
    venue = fields.Char('Venue', required=True, tracking=True)
    class_ids = fields.Many2many('op.course', string='Classes', required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
