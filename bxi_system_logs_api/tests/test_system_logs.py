from datetime import timedelta

from odoo import fields as odoo_fields
from odoo.tests import HttpCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged('post_install', '-at_install')
class TestBxiSystemLogsApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_user = mail_new_test_user(
            cls.env, login='logs_admin', groups='base.group_system', password='AdminPass1!')
        cls.staff_user = mail_new_test_user(
            cls.env, login='logs_staff', groups='base.group_user', password='StaffPass1!')

        cls.partner = cls.env['res.partner'].create({'name': 'Tracked Partner'})
        field = cls.env['ir.model.fields'].search([('model', '=', 'res.partner'), ('name', '=', 'name')], limit=1)
        message = cls.env['mail.message'].create({
            'model': 'res.partner', 'res_id': cls.partner.id, 'author_id': cls.admin_user.partner_id.id,
        })
        cls.env['mail.tracking.value'].create({
            'field_id': field.id, 'mail_message_id': message.id,
            'old_value_char': 'Old Name', 'new_value_char': 'Tracked Partner',
        })

    def _headers(self, login, password):
        resp = self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})
        return {'Authorization': f'Bearer {resp.json()["data"]["token"]}'}

    def test_requires_full_admin_access(self):
        resp = self.url_open('/api/v1/admin/system-logs', headers=self._headers('logs_staff', 'StaffPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_requires_auth(self):
        resp = self.url_open('/api/v1/admin/system-logs')
        self.assertEqual(resp.status_code, 401)

    def test_admin_sees_entries_with_expected_shape(self):
        resp = self.url_open('/api/v1/admin/system-logs', headers=self._headers('logs_admin', 'AdminPass1!'))
        self.assertEqual(resp.status_code, 200)
        entries = resp.json()['data']['entries']
        self.assertTrue(len(entries) >= 1)
        entry = next(e for e in entries if e['model'] == 'res.partner' and e['res_id'] == self.partner.id)
        self.assertEqual(entry['old_value'], 'Old Name')
        self.assertEqual(entry['new_value'], 'Tracked Partner')

    def test_filter_by_model_and_res_id(self):
        resp = self.url_open(
            f'/api/v1/admin/system-logs?model=res.partner&res_id={self.partner.id}',
            headers=self._headers('logs_admin', 'AdminPass1!'))
        entries = resp.json()['data']['entries']
        self.assertTrue(all(e['model'] == 'res.partner' and e['res_id'] == self.partner.id for e in entries))

    def test_filter_by_unrelated_model_returns_nothing(self):
        resp = self.url_open(
            '/api/v1/admin/system-logs?model=nonexistent.model.xyz', headers=self._headers('logs_admin', 'AdminPass1!'))
        entries = resp.json()['data']['entries']
        self.assertEqual(entries, [])

    def test_limit_is_capped(self):
        resp = self.url_open(
            '/api/v1/admin/system-logs?limit=99999', headers=self._headers('logs_admin', 'AdminPass1!'))
        self.assertEqual(resp.status_code, 200)

    def test_invalid_token_is_rejected(self):
        resp = self.url_open(
            '/api/v1/admin/system-logs', headers={'Authorization': 'Bearer not-a-real-token'})
        self.assertEqual(resp.status_code, 401)

    def test_filter_by_res_id_only(self):
        resp = self.url_open(
            f'/api/v1/admin/system-logs?res_id={self.partner.id}',
            headers=self._headers('logs_admin', 'AdminPass1!'))
        self.assertEqual(resp.status_code, 200)
        entries = resp.json()['data']['entries']
        self.assertTrue(entries)
        self.assertTrue(all(e['res_id'] == self.partner.id for e in entries))

    def test_filter_by_date_range(self):
        future_from = odoo_fields.Datetime.to_string(
            odoo_fields.Datetime.now() + timedelta(days=1))
        resp = self.url_open(
            f'/api/v1/admin/system-logs?date_from={future_from}',
            headers=self._headers('logs_admin', 'AdminPass1!'))
        self.assertEqual(resp.status_code, 200)
        entries = resp.json()['data']['entries']
        self.assertEqual(entries, [])

        past_from = odoo_fields.Datetime.to_string(
            odoo_fields.Datetime.now() - timedelta(days=1))
        resp = self.url_open(
            f'/api/v1/admin/system-logs?date_from={past_from}&model=res.partner&res_id={self.partner.id}',
            headers=self._headers('logs_admin', 'AdminPass1!'))
        self.assertEqual(resp.status_code, 200)
        entries = resp.json()['data']['entries']
        self.assertTrue(any(e['res_id'] == self.partner.id for e in entries))

    def test_date_to_excludes_future_entries(self):
        past_to = odoo_fields.Datetime.to_string(
            odoo_fields.Datetime.now() - timedelta(days=1))
        resp = self.url_open(
            f'/api/v1/admin/system-logs?date_to={past_to}&model=res.partner&res_id={self.partner.id}',
            headers=self._headers('logs_admin', 'AdminPass1!'))
        self.assertEqual(resp.status_code, 200)
        entries = resp.json()['data']['entries']
        self.assertFalse(any(e['res_id'] == self.partner.id for e in entries))

    def test_pagination_offset(self):
        field = self.env['ir.model.fields'].search(
            [('model', '=', 'res.partner'), ('name', '=', 'name')], limit=1)
        message = self.env['mail.message'].create({
            'model': 'res.partner', 'res_id': self.partner.id, 'author_id': self.admin_user.partner_id.id,
        })
        self.env['mail.tracking.value'].create({
            'field_id': field.id, 'mail_message_id': message.id,
            'old_value_char': 'Tracked Partner', 'new_value_char': 'Renamed Partner',
        })

        headers = self._headers('logs_admin', 'AdminPass1!')
        full_resp = self.url_open(
            f'/api/v1/admin/system-logs?model=res.partner&res_id={self.partner.id}', headers=headers)
        full_entries = full_resp.json()['data']['entries']
        self.assertTrue(len(full_entries) >= 2)

        offset_resp = self.url_open(
            f'/api/v1/admin/system-logs?model=res.partner&res_id={self.partner.id}&offset=1', headers=headers)
        offset_entries = offset_resp.json()['data']['entries']
        self.assertEqual(offset_entries, full_entries[1:])

    def test_results_ordered_by_id_desc(self):
        field = self.env['ir.model.fields'].search(
            [('model', '=', 'res.partner'), ('name', '=', 'name')], limit=1)
        message = self.env['mail.message'].create({
            'model': 'res.partner', 'res_id': self.partner.id, 'author_id': self.admin_user.partner_id.id,
        })
        newest = self.env['mail.tracking.value'].create({
            'field_id': field.id, 'mail_message_id': message.id,
            'old_value_char': 'A', 'new_value_char': 'B',
        })

        resp = self.url_open(
            f'/api/v1/admin/system-logs?model=res.partner&res_id={self.partner.id}',
            headers=self._headers('logs_admin', 'AdminPass1!'))
        entries = resp.json()['data']['entries']
        self.assertEqual(entries[0]['id'], newest.id)
        ids = [e['id'] for e in entries]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_empty_result_set_shape(self):
        resp = self.url_open(
            '/api/v1/admin/system-logs?model=nonexistent.model.xyz',
            headers=self._headers('logs_admin', 'AdminPass1!'))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'])
        self.assertEqual(body['data']['entries'], [])
