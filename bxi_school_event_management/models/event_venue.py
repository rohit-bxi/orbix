from odoo import api, fields, models


class BxiEventVenue(models.Model):
    _name = 'bxi.event.venue'
    _description = 'Event Venue'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    building = fields.Char(help='Free-text location, e.g. "Block B, 2nd Floor".')
    capacity = fields.Integer()
    active = fields.Boolean(default=True)
    event_ids = fields.One2many('event.event', 'venue_id')
    event_count = fields.Integer(compute='_compute_event_count')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    _unique_venue_code = models.Constraint('unique(code)', 'Venue code must be unique!')

    @api.depends('event_ids')
    def _compute_event_count(self):
        for rec in self:
            rec.event_count = len(rec.event_ids)

    def action_view_events(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Events',
            'res_model': 'event.event',
            'view_mode': 'list,kanban,calendar,form',
            'domain': [('venue_id', '=', self.id)],
            'context': {'default_venue_id': self.id},
        }
