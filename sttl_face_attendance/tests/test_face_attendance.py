# -*- coding: utf-8 -*-
import base64

from odoo.tests import HttpCase, tagged

from odoo.addons.sttl_face_attendance.controllers import attendance_controller

PIXEL = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='


@tagged('post_install', '-at_install')
class TestFaceAttendance(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({'name': 'Face Test Employee'})
        cls.company = cls.env.company
        cls.company.attendance_kiosk_key = 'face-test-kiosk-key'

    def setUp(self):
        super().setUp()
        attendance_controller._images_attempts.clear()

    def test_register_face_strips_data_uri(self):
        self.assertTrue(self.employee.register_face('data:image/png;base64,' + PIXEL))
        self.assertTrue(self.employee.image_1920)
        self.assertEqual(base64.b64decode(self.employee.image_1920)[:4], b'\x89PNG')

    def test_register_face_rejects_bad_input(self):
        self.assertFalse(self.employee.register_face(''))
        self.assertFalse(self.employee.register_face('data:image/png;base64,not-an-image!!'))
        self.assertFalse(self.employee.image_1920 and base64.b64decode(self.employee.image_1920)[:4] == b'\x89PNG')

    def test_parent_photo_goes_to_partner(self):
        partner = self.env['res.partner'].create({'name': 'Face Test Parent'})
        relationship = self.env['op.parent.relationship'].search([], limit=1) or \
            self.env['op.parent.relationship'].create({'name': 'Guardian'})
        parent = self.env['op.parent'].create({'name': partner.id, 'relationship_id': relationship.id})
        self.assertTrue(parent.register_face(PIXEL))
        self.assertTrue(partner.image_1920)

    def test_open_capture_action(self):
        action = self.employee.new_employee_image()
        self.assertEqual(action['tag'], 'new_employee_image')
        self.assertEqual(action['params'], {'res_model': 'hr.employee', 'res_id': self.employee.id})

    def _images(self, token, employee_id=None):
        params = {'token': token}
        if employee_id:
            params['employee_id'] = employee_id
        resp = self.url_open('/employee/images', json={'jsonrpc': '2.0', 'method': 'call', 'params': params})
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()['result']

    def test_kiosk_images_need_the_kiosk_key(self):
        self.employee.register_face(PIXEL)
        self.assertEqual(self._images('wrong-key'), [])
        rows = self._images('face-test-kiosk-key', self.employee.id)
        self.assertEqual([r['employee_id'] for r in rows], [self.employee.id])
        self.assertTrue(rows[0]['image'])

    def test_kiosk_images_rate_limited(self):
        for _attempt in range(attendance_controller._IMAGES_RATE_MAX):
            self._images('wrong-key')
        # Even with the right key, the 11th call within a minute gets nothing.
        self.assertEqual(self._images('face-test-kiosk-key', self.employee.id), [])
