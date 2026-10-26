from odoo import fields, models, api

HEALTH_ROLES = [
    ('nurse', 'Nurse'),
    ('doctor', 'Doctor'),
    ('other', 'Other'),
]


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    is_health_staff = fields.Boolean(
        string='Is Health Staff', compute='_compute_is_health_staff', store=True)
    health_role = fields.Selection(HEALTH_ROLES, string='Health Role')
    license_no = fields.Char(string='Medical License No.')

    @api.depends('user_id.all_group_ids')
    def _compute_is_health_staff(self):
        health_staff_group = self.env.ref('op_health_center.group_health_staff', raise_if_not_found=False)
        for employee in self:
            employee.is_health_staff = bool(
                health_staff_group and employee.user_id and health_staff_group in employee.user_id.all_group_ids)


class HrEmployeePublic(models.Model):
    """Declared public so non-HR logins can still read employee records:
    the ORM prefetches every stored hr.employee column, and any not present
    here makes hr.employee refuse the whole read (e.g. a teacher's Time Off
    calendar). None of these are medical data - those live on the patient
    mixins, not here."""
    _inherit = 'hr.employee.public'

    is_health_staff = fields.Boolean(string='Is Health Staff', readonly=True)
    health_role = fields.Selection(HEALTH_ROLES, string='Health Role', readonly=True)
    license_no = fields.Char(string='Medical License No.', readonly=True)
