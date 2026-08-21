from odoo import _, api, fields, models

CATEGORIES = [
    ('event', 'Event'),
    ('staff', 'Staff'),
    ('holiday', 'Holiday'),
    ('academic', 'Academic'),
    ('general', 'General'),
    ('emergency', 'Emergency'),
]

AUDIENCES = [
    ('all_students', 'All Students'),
    ('all_teachers', 'All Teachers'),
    ('all_parents', 'All Parents'),
    ('specific_class', 'Specific Class'),
    ('everyone', 'Everyone'),
]

PRIORITIES = [
    ('low', 'Low'),
    ('normal', 'Normal'),
    ('high', 'High'),
    ('urgent', 'Urgent'),
]


class Announcement(models.Model):
    _name = 'bxi.announcement'
    _description = 'School Announcement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default=lambda self: _('New'))
    title = fields.Char(required=True, tracking=True)
    category = fields.Selection(CATEGORIES, required=True, default='general', tracking=True)
    body = fields.Text(string='Message Body', required=True)
    priority = fields.Selection(PRIORITIES, default='normal', required=True, tracking=True)

    target_audience = fields.Selection(AUDIENCES, required=True, default='all_students', tracking=True)
    course_ids = fields.Many2many(
        'op.course', string='Classes',
        help='Only used when Target Audience is Specific Class. Leave empty for every class.')
    batch_ids = fields.Many2many(
        'op.batch', string='Sections',
        help='Only used when Target Audience is Specific Class. Leave empty for every section.')

    channel_in_app = fields.Boolean(string='In-App', default=True)
    channel_email = fields.Boolean(string='Email', default=True)
    channel_sms = fields.Boolean(string='SMS')
    channel_push = fields.Boolean(string='Push')

    schedule_date = fields.Datetime(
        string='Schedule',
        help='Leave empty to publish immediately on confirm. Set a future date/time to publish automatically then.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ], default='draft', required=True, tracking=True)
    published_date = fields.Datetime(readonly=True, copy=False)
    recipient_count = fields.Integer(compute='_compute_recipient_count', store=True)
    author_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.announcement') or _('New')
        return super().create(vals_list)

    @api.depends('target_audience', 'course_ids', 'batch_ids')
    def _compute_recipient_count(self):
        for announcement in self:
            announcement.recipient_count = len(announcement._resolve_recipient_partners())

    def _resolve_recipient_partners(self):
        self.ensure_one()
        Student = self.env['op.student']
        partners = self.env['res.partner']
        audience = self.target_audience
        if audience in ('all_students', 'everyone'):
            partners |= Student.search([]).mapped('partner_id')
        if audience in ('all_teachers', 'everyone'):
            partners |= self.env['op.faculty'].search([]).mapped('partner_id')
        if audience in ('all_parents', 'everyone'):
            partners |= self.env['op.parent'].search([]).mapped('name')
        if audience == 'specific_class':
            domain = [('state', '=', 'running')]
            if self.course_ids:
                domain.append(('course_id', 'in', self.course_ids.ids))
            if self.batch_ids:
                domain.append(('batch_id', 'in', self.batch_ids.ids))
            enrollments = self.env['op.student.course'].search(domain)
            partners |= enrollments.mapped('student_id.partner_id')
        return partners

    def action_publish(self):
        for announcement in self:
            if announcement.schedule_date and announcement.schedule_date > fields.Datetime.now():
                announcement.state = 'scheduled'
            else:
                announcement._do_publish()

    def action_reset_to_draft(self):
        self.write({'state': 'draft', 'published_date': False})

    def action_archive_announcement(self):
        self.write({'state': 'archived', 'active': False})

    def _do_publish(self):
        for announcement in self:
            announcement.write({'state': 'published', 'published_date': fields.Datetime.now()})
            announcement._dispatch_channels()

    def _dispatch_channels(self):
        self.ensure_one()
        partners = self._resolve_recipient_partners()
        if not partners:
            return
        if self.channel_in_app:
            # message_subscribe + a plain note makes the announcement visible in
            # each recipient's chatter/follower feed without going through
            # partner_ids= on message_post, which would additionally trigger
            # Odoo's own notification/email dispatch - channel_email below is
            # the single, explicit path for that instead.
            self.message_subscribe(partner_ids=partners.ids)
            self.message_post(
                body=self.body,
                subject=self.title,
                subtype_xmlid='mail.mt_note',
            )
        if self.channel_email:
            template = self.env.ref('bxi_school_announcement.mail_template_announcement', raise_if_not_found=False)
            if template:
                for partner in partners.filtered('email'):
                    template.send_mail(
                        self.id, force_send=False, email_values={'email_to': partner.email}, email_layout_xmlid=False)

    def _cron_publish_scheduled(self):
        due = self.search([
            ('state', '=', 'scheduled'),
            ('schedule_date', '<=', fields.Datetime.now()),
        ])
        due._do_publish()
