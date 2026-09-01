from odoo.tests import HttpCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged('post_install', '-at_install')
class TestBxiSettingsApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_user = mail_new_test_user(
            cls.env, login='settings_admin', groups='base.group_system', password='AdminPass1!')
        cls.staff_user = mail_new_test_user(
            cls.env, login='settings_staff', groups='base.group_user', password='StaffPass1!')

    def _headers(self, login, password):
        resp = self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})
        return {'Authorization': f'Bearer {resp.json()["data"]["token"]}'}

    def test_requires_full_admin_access(self):
        resp = self.url_open('/api/v1/admin/settings', headers=self._headers('settings_staff', 'StaffPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_requires_auth(self):
        resp = self.url_open('/api/v1/admin/settings')
        self.assertEqual(resp.status_code, 401)

    def test_get_settings_masks_secrets(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_notification_gateway.msg91_auth_key', 'super-secret-key')
        resp = self.url_open('/api/v1/admin/settings', headers=self._headers('settings_admin', 'AdminPass1!'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertEqual(data['notifications']['msg91_auth_key'], {'configured': True})
        self.assertNotIn('super-secret-key', resp.text)

    def test_get_settings_shows_non_secret_values_directly(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_notification_gateway.msg91_sender_id', 'ORBIX')
        resp = self.url_open('/api/v1/admin/settings', headers=self._headers('settings_admin', 'AdminPass1!'))
        self.assertEqual(resp.json()['data']['notifications']['msg91_sender_id'], 'ORBIX')

    def test_update_settings_writes_config_parameter(self):
        headers = self._headers('settings_admin', 'AdminPass1!')
        resp = self.url_open('/api/v1/admin/settings', headers=headers, json={
            'finance': {'razorpay_key_id': 'rzp_test_123'},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.env['ir.config_parameter'].sudo().get_param('bxi_online_fee_payment.razorpay_key_id'),
            'rzp_test_123')

    def test_update_rejects_unknown_group(self):
        resp = self.url_open('/api/v1/admin/settings', headers=self._headers('settings_admin', 'AdminPass1!'), json={
            'not_a_real_group': {'foo': 'bar'},
        })
        self.assertEqual(resp.status_code, 400)

    def test_update_rejects_unknown_field(self):
        resp = self.url_open('/api/v1/admin/settings', headers=self._headers('settings_admin', 'AdminPass1!'), json={
            'finance': {'not_a_real_field': 'x'},
        })
        self.assertEqual(resp.status_code, 400)

    def test_update_requires_full_admin_access(self):
        resp = self.url_open('/api/v1/admin/settings', headers=self._headers('settings_staff', 'StaffPass1!'), json={
            'finance': {'razorpay_key_id': 'nope'},
        })
        self.assertEqual(resp.status_code, 403)

    def test_requires_valid_token(self):
        resp = self.url_open('/api/v1/admin/settings', headers={'Authorization': 'Bearer not-a-real-token'})
        self.assertEqual(resp.status_code, 401)

    def test_get_settings_secret_not_configured(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_online_fee_payment.razorpay_key_secret', False)
        resp = self.url_open('/api/v1/admin/settings', headers=self._headers('settings_admin', 'AdminPass1!'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertEqual(data['finance']['razorpay_key_secret'], {'configured': False})

    def test_get_settings_includes_journal_field(self):
        resp = self.url_open('/api/v1/admin/settings', headers=self._headers('settings_admin', 'AdminPass1!'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertIn('online_payment_journal_id', data['finance'])

    def test_update_rejects_non_dict_group_payload(self):
        resp = self.url_open('/api/v1/admin/settings', headers=self._headers('settings_admin', 'AdminPass1!'), json={
            'finance': 'not-a-dict',
        })
        self.assertEqual(resp.status_code, 400)

    def test_update_settings_supports_multiple_groups_and_fields(self):
        headers = self._headers('settings_admin', 'AdminPass1!')
        resp = self.url_open('/api/v1/admin/settings', headers=headers, json={
            'notifications': {'msg91_sender_id': 'ORBIX2', 'msg91_otp_template_id': 'tmpl_1'},
            'finance': {'online_payment_journal_id': '5'},
        })
        self.assertEqual(resp.status_code, 200)
        updated = resp.json()['data']['updated']
        self.assertCountEqual(updated, [
            'notifications.msg91_sender_id',
            'notifications.msg91_otp_template_id',
            'finance.online_payment_journal_id',
        ])
        ICP = self.env['ir.config_parameter'].sudo()
        self.assertEqual(ICP.get_param('bxi_notification_gateway.msg91_sender_id'), 'ORBIX2')
        self.assertEqual(ICP.get_param('bxi_online_fee_payment.default_journal_id'), '5')

    def test_update_settings_null_value_clears_parameter(self):
        headers = self._headers('settings_admin', 'AdminPass1!')
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('bxi_notification_gateway.msg91_sender_id', 'ORBIX')
        resp = self.url_open('/api/v1/admin/settings', headers=headers, json={
            'notifications': {'msg91_sender_id': None},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ICP.get_param('bxi_notification_gateway.msg91_sender_id'))

    def test_update_settings_secret_then_masked_on_get(self):
        headers = self._headers('settings_admin', 'AdminPass1!')
        resp = self.url_open('/api/v1/admin/settings', headers=headers, json={
            'finance': {'razorpay_key_secret': 'sk_super_secret'},
        })
        self.assertEqual(resp.status_code, 200)
        get_resp = self.url_open('/api/v1/admin/settings', headers=headers)
        data = get_resp.json()['data']
        self.assertEqual(data['finance']['razorpay_key_secret'], {'configured': True})
        self.assertNotIn('sk_super_secret', get_resp.text)
