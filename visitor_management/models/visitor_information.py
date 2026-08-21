from datetime import datetime
import re

# from AptUrl.Helpers import _
from odoo import _
from odoo import tools
from odoo import fields, models, api
from odoo.exceptions import ValidationError


class Visitor(models.Model):
    _name = 'visitor.data'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Visitor data'
    _rec_name = 'v_name'
    _order = "visitor_seq desc"

    # Track Visibility for any changes
    I_AM = fields.Selection(
        [('buyer', 'Buyer'), ('guest', 'Guest'), ('supplier', 'Supplier'), ('delivery', 'Delivery')], required=True)
    v_name = fields.Char(string="Name", required=True, tracking=True)
    v_company = fields.Char(string="Company", required=True, tracking=True)
    # Char, not Integer: a 10-digit mobile number (e.g. 9876543210) overflows
    # Postgres's 32-bit int4 column outright, and Integer also silently drops
    # any leading zero / '+' country-code prefix a real phone number can have.
    v_phn = fields.Char(string="Phone Number", required=True, tracking=True)
    v_email = fields.Char(string="E-mail", tracking=True)
    # v_purpose = fields.Text(string="Purpose")
    v_gender = fields.Selection([('male', 'Male'), ('female', 'Female')], default='male', string="Gender",
                                required=True)
    v_image = fields.Binary(string='Take Photo')
    v_address = fields.Char(string="Address")
    visitor_seq = fields.Char(string='sequence', required=True, copy=False,
                              index=True,
                              default=lambda self: _('New'))
    channel = fields.Many2one('discuss.channel')
    # appoint_count = fields.Integer(string='Appointment', computed='get_appoint_count')

    # @api.depends('v_name')
    # def get_appoint_count(self):
    #     for rec in self:
    #         count = self.env['visitor.data'].search_count([('v_name' '=', self.id)])
    #         rec.appoint_count = count

    # ##################Phone number Validations################################

    @api.constrains('v_phn')
    def check_phn(self):
        for rec in self:
            digits = re.sub(r'\D', '', rec.v_phn or '')
            if len(digits) < 7 or len(digits) > 15:
                raise ValidationError(_("Enter a valid phone number (7 to 15 digits)."))
        return True

    ################################################################################
    # # Sequence method
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('visitor_seq', _('New')) == _('New'):
                vals['visitor_seq'] = self.env['ir.sequence'].next_by_code('visitor.data.sequence') or _('New')
        result = super(Visitor, self).create(vals_list)
        return result

    ###################################################################################################

    # appointment count section
    def visitor_appointment(self):
        return {
            'name': _('Appointment'),
            'domain': [('v_name', '=', self.id)],
            'view_type': 'form',
            'res_model': 'visitor.data',
            'view_id': False,
            'view_mode': 'list,form',
            'type': 'ir.actions.act_window',
        }

    def action_mail(self):
        # print("mail")
        template_id = self.env.ref('visitor_management.email_template').id
        # print(template_id)
        template = self.env['mail.template'].browse(template_id)
        template.send_mail(self.id, force_send=True)

    # @api.model
    # def get_appoint_count(self):
    #     count = self.env['visitor.data'].search_count([('v_phn', '+', 'v_phn')])
    #     self.appoint_count = count

    @api.onchange('v_email')
    def validate_mail(self):
        if self.v_email:
            match = re.match(r'^[_a-z0-9-]+(\.[_a-z0-9-]+)*@[a-z0-9-]+(\.[a-z0-9-]+)*(\.[a-z]{2,4})$', self.v_email)
            if match == None:
                raise ValidationError('Not a valid E-mail ID')


class Visit(models.Model):
    _name = 'visit.data'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Visitor Check-In/Check-Out'
    _rec_name = 'v_name'

    v_name = fields.Many2one(comodel_name="visitor.data", string="Name", required=True, )
    v_image = fields.Binary(related='v_name.v_image', string="Image")
    v_gender = fields.Selection(related='v_name.v_gender', string="Gender")
    I_AM = fields.Selection(related='v_name.I_AM', string="Type")
    v_phn = fields.Char(related='v_name.v_phn', string="Phone")
    v_address = fields.Char(related='v_name.v_address', string="Address")
    v_company = fields.Char(related='v_name.v_company', string="Company")
    v_email = fields.Char(related='v_name.v_email', string="E-mail")
    v_purpose = fields.Text(string="Purpose")
    entry_count = fields.Integer(string="Total Entry")

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    image_1920 = fields.Image(related='employee_id.image_1920', string="Photo")
    work_phone = fields.Char(related='employee_id.work_phone', string="Phone")
    work_email = fields.Char(related='employee_id.work_email', string="Email")
    dept = fields.Many2one(related='employee_id.department_id', string="Department")
    job_title = fields.Char(related='employee_id.job_title', string=" Job Position")
    check_in_date = fields.Datetime(string='Check-In', default=lambda self: datetime.today(), readonly=True)
    check_out_date = fields.Datetime(string='Check-Out', )
    # check_out = fields.Boolean(string="Check-Out")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('checkin', 'Check-In'),
        ('checkout', 'Check-Out'),
    ], default='draft', tracking=True)

    def check_in_action(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError(_('This visit is already checked in.'))
        if self.v_name:
            visitor_data = self.env['visit.data'].search([('v_name', '=', self.v_name.id)])
            for rec in visitor_data:
                rec.entry_count = len(visitor_data)
        for rec in self:
            rec.state = 'checkin'

    def check_out_action(self):
        for rec in self:
            if rec.state != 'checkin':
                raise ValidationError(_('Only a checked-in visit can be checked out.'))
            rec.write({
                'state': 'checkout',
                'check_out_date': fields.Datetime.now(),
            })

    def visitor_entry_count(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Visitor',
            'view_mode': 'list,form',
            'res_model': 'visit.data',
            'domain': [('v_name', '=', self.v_name.v_name)],
            'context': "{'create': False}",
            'target': 'current'
        }

    # def check_out(self):
    #     self.date = datetime.date.today()
    #     self.check_out_date = datetime.datetime.today().strftime('%Y-%m-%d')