from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class EventEvent(models.Model):
    _inherit = 'event.event'

    event_category = fields.Selection([
        ('sports_day', 'Sports Day'),
        ('annual_day', 'Annual Day'),
        ('ptm', 'Parent-Teacher Meeting'),
        ('workshop', 'Workshop'),
        ('field_trip', 'Field Trip'),
        ('open_house', 'Open House'),
        ('competition', 'Competition'),
        ('other', 'Other'),
    ], default='other', tracking=True)
    venue_id = fields.Many2one('bxi.event.venue', string='School Venue')
    academic_year_id = fields.Many2one('op.academic.year')
    academic_term_id = fields.Many2one('op.academic.term')

    target_audience = fields.Selection([
        ('all_students', 'All Students'),
        ('all_teachers', 'All Teachers'),
        ('all_parents', 'All Parents'),
        ('specific_class', 'Specific Class(es)'),
        ('everyone', 'Everyone'),
    ], default='specific_class')
    course_ids = fields.Many2many('op.course', string='Classes',
                                   help='Only used when Target Audience is Specific Class(es).')
    batch_ids = fields.Many2many('op.batch', string='Sections',
                                  help='Only used when Target Audience is Specific Class(es).')
    coordinator_ids = fields.Many2many(
        'op.faculty', 'event_event_coordinator_rel', 'event_id', 'faculty_id',
        string='Duty Teachers')

    is_paid_event = fields.Boolean()
    fee_product_id = fields.Many2one('product.product', string='Fee Product')
    requires_permission_slip = fields.Boolean(string='Requires Permission Slip')
    requires_transport = fields.Boolean(string='Offers Transport Add-on')

    over_capacity = fields.Boolean(compute='_compute_over_capacity')
    announcement_id = fields.Many2one('bxi.announcement', readonly=True, copy=False)

    @api.depends('venue_id.capacity', 'seats_max', 'seats_limited')
    def _compute_over_capacity(self):
        for event in self:
            event.over_capacity = bool(
                event.venue_id and event.seats_limited
                and event.venue_id.capacity and event.seats_max > event.venue_id.capacity)

    @api.constrains('venue_id', 'date_begin', 'date_end')
    def _check_venue_availability(self):
        for event in self.filtered('venue_id'):
            overlapping = self.search([
                ('id', '!=', event.id),
                ('venue_id', '=', event.venue_id.id),
                ('date_begin', '<', event.date_end),
                ('date_end', '>', event.date_begin),
                ('kanban_state', '!=', 'cancel'),
            ])
            if overlapping:
                raise ValidationError(_(
                    '%(venue)s is already booked for %(other)s at this time.',
                    venue=event.venue_id.name, other=overlapping[0].name))

    @api.constrains('is_paid_event', 'fee_product_id')
    def _check_fee_product(self):
        for event in self:
            if event.is_paid_event and not event.fee_product_id:
                raise ValidationError(_('Set a fee product before marking "%s" as a paid event.') % event.name)

    def action_view_registrations_to_certify(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Attendees',
            'res_model': 'event.registration',
            'view_mode': 'list,form',
            'domain': [('event_id', '=', self.id), ('state', '=', 'done')],
        }

    def action_open_bulk_registration_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bulk Register Students'),
            'res_model': 'event.bulk.registration.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_event_id': self.id},
        }

    def action_open_certificate_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate Participation Certificates'),
            'res_model': 'event.certificate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_event_id': self.id},
        }

    def action_generate_participation_certificates(self, certificate_type_id):
        Certificate = self.env['op.certificate']
        created = Certificate.browse()
        for event in self:
            attendees = event.registration_ids.filtered(
                lambda r: r.state == 'done' and r.student_id and not r.certificate_id)
            for reg in attendees:
                reg.certificate_id = Certificate.create({
                    'certificate_type_id': certificate_type_id,
                    'student_id': reg.student_id.id,
                    'remarks': _('Participation: %s') % event.name,
                    'event_registration_id': reg.id,
                })
                created |= reg.certificate_id
        if not created:
            raise UserError(_('No eligible attendees (checked-in students without a certificate already) were found.'))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Certificates',
            'res_model': 'op.certificate',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
        }

    def action_post_announcement(self):
        self.ensure_one()
        if self.announcement_id:
            return self._open_announcement()
        self.announcement_id = self.env['bxi.announcement'].create({
            'title': self.name,
            'category': 'event',
            'body': self.note or _('Join us for %s.') % self.name,
            'target_audience': self.target_audience,
            'course_ids': [(6, 0, self.course_ids.ids)],
            'batch_ids': [(6, 0, self.batch_ids.ids)],
        })
        return self._open_announcement()

    def _open_announcement(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Announcement',
            'res_model': 'bxi.announcement',
            'view_mode': 'form',
            'res_id': self.announcement_id.id,
        }
