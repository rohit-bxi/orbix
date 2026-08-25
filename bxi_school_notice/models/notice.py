from odoo import _, api, fields, models

CATEGORIES = [
    ('event', 'Event'),
    ('academic', 'Academic'),
    ('general', 'General'),
    ('holiday', 'Holiday'),
    ('emergency', 'Emergency'),
]

AUDIENCES = [
    ('all_students', 'All Students'),
    ('all_classes', 'All Classes'),
    ('all_teachers', 'All Teachers'),
    ('all_parents', 'All Parents'),
    ('students_and_families', 'All Students and Families'),
    ('specific_class', 'Specific Class'),
]

# Fields that, when changed, warrant re-resolving the audience and re-sending
# the notification email rather than leaving recipients on stale content.
NOTIFY_FIELDS = {'title', 'body', 'category', 'target_audience', 'course_ids', 'batch_ids', 'expires_on'}


class Notice(models.Model):
    _name = 'bxi.notice'
    _description = 'School Notice'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'is_pinned desc, posted_date desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default=lambda self: _('New'))
    title = fields.Char(required=True, tracking=True)
    body = fields.Text(string='Message Body', required=True)
    category = fields.Selection(CATEGORIES, required=True, default='general', tracking=True)

    target_audience = fields.Selection(AUDIENCES, required=True, default='all_students', tracking=True)
    course_ids = fields.Many2many(
        'op.course', string='Classes',
        help='Only used when Target Audience is Specific Class. Leave empty for every class.')
    batch_ids = fields.Many2many(
        'op.batch', string='Sections',
        help='Only used when Target Audience is Specific Class. Leave empty for every section.')

    expires_on = fields.Date(string='Expires On')
    is_expired = fields.Boolean(compute='_compute_is_expired', search='_search_is_expired')
    is_pinned = fields.Boolean(string='Pinned')

    author_id = fields.Many2one('res.users', string='Posted By', default=lambda self: self.env.user, readonly=True)
    posted_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('bxi.notice') or _('New')
        notices = super().create(vals_list)
        notices._dispatch_email_notification()
        return notices

    def write(self, vals):
        should_notify = bool(NOTIFY_FIELDS & set(vals))
        res = super().write(vals)
        if should_notify:
            self._dispatch_email_notification()
        return res

    @api.depends('expires_on')
    def _compute_is_expired(self):
        today = fields.Date.today()
        for notice in self:
            notice.is_expired = bool(notice.expires_on and notice.expires_on < today)

    def _search_is_expired(self, operator, value):
        want_expired = (operator == '=') == bool(value)
        today = fields.Date.today()
        domain = [('expires_on', '<', today)]
        if want_expired:
            return domain
        return ['|', ('expires_on', '=', False), ('expires_on', '>=', today)]

    def action_toggle_pin(self):
        for notice in self:
            notice.is_pinned = not notice.is_pinned

    def _resolve_recipient_partners(self):
        self.ensure_one()
        Student = self.env['op.student']
        partners = self.env['res.partner']
        audience = self.target_audience
        if audience in ('all_students', 'all_classes', 'students_and_families'):
            partners |= Student.search([]).mapped('partner_id')
        if audience == 'all_teachers':
            partners |= self.env['op.faculty'].search([]).mapped('partner_id')
        if audience in ('all_parents', 'students_and_families'):
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

    def _dispatch_email_notification(self):
        template = self.env.ref('bxi_school_notice.mail_template_notice', raise_if_not_found=False)
        for notice in self:
            partners = notice._resolve_recipient_partners()
            if not partners:
                continue
            notice.message_subscribe(partner_ids=partners.ids)
            mailed_partners = partners.filtered('email')
            if template:
                for partner in mailed_partners:
                    template.send_mail(
                        notice.id, force_send=False,
                        email_values={'email_to': partner.email}, email_layout_xmlid=False)
            notice.message_post(
                body=_(
                    'Notice emailed to %(count)s of %(total)s recipient(s) for audience "%(audience)s".',
                    count=len(mailed_partners), total=len(partners),
                    audience=dict(AUDIENCES).get(notice.target_audience),
                ),
                subtype_xmlid='mail.mt_note',
            )
