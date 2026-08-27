from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTransport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env['fleet.vehicle.model.brand'].create({'name': 'Test Brand'})
        model = cls.env['fleet.vehicle.model'].create({
            'name': 'Test Bus Model',
            'brand_id': brand.id,
            'vehicle_type': 'car',
        })
        cls.vehicle = cls.env['fleet.vehicle'].create({
            'model_id': model.id,
            'is_school_bus': True,
            'seats': 2,
        })
        cls.fee_product = cls.env['product.product'].create({
            'name': 'Transport Fee',
            'type': 'service',
            'list_price': 0.0,
        })
        cls.route = cls.env['bxi.transport.route'].create({
            'name': 'Route A',
            'code': 'RA',
            'vehicle_id': cls.vehicle.id,
            'fee_product_id': cls.fee_product.id,
            'fee_amount': 500.0,
            'state': 'active',
        })
        cls.stop_1 = cls.env['bxi.transport.route.stop'].create({
            'route_id': cls.route.id,
            'name': 'Stop 1',
            'fee_amount': 500.0,
        })
        cls.stop_2 = cls.env['bxi.transport.route.stop'].create({
            'route_id': cls.route.id,
            'name': 'Stop 2',
            'fee_amount': 600.0,
        })
        cls.student_1 = cls.env['op.student'].create({
            'first_name': 'John', 'last_name': 'Smith', 'gr_no': 'TRN-001', 'gender': 'm',
        })
        cls.student_2 = cls.env['op.student'].create({
            'first_name': 'Mary', 'last_name': 'Jones', 'gr_no': 'TRN-002', 'gender': 'f',
        })
        cls.student_3 = cls.env['op.student'].create({
            'first_name': 'Sam', 'last_name': 'Lee', 'gr_no': 'TRN-003', 'gender': 'm',
        })

    def _register(self, student, stop):
        return self.env['bxi.transport.registration'].create({
            'student_id': student.id,
            'route_id': self.route.id,
            'stop_id': stop.id,
        })

    def test_route_capacity_from_vehicle_seats(self):
        self.assertEqual(self.route.capacity, 2)
        self.assertEqual(self.route.seats_available, 2)

    def test_stop_must_belong_to_route(self):
        other_route = self.env['bxi.transport.route'].create({
            'name': 'Route B',
            'code': 'RB',
            'vehicle_id': self.vehicle.id,
            'fee_product_id': self.fee_product.id,
        })
        other_stop = self.env['bxi.transport.route.stop'].create({
            'route_id': other_route.id,
            'name': 'Other Stop',
        })
        with self.assertRaises(ValidationError):
            self.env['bxi.transport.registration'].create({
                'student_id': self.student_1.id,
                'route_id': self.route.id,
                'stop_id': other_stop.id,
            })

    def test_fee_amount_defaults_from_stop(self):
        reg = self._register(self.student_1, self.stop_1)
        self.assertEqual(reg.fee_amount, 500.0)
        reg_2 = self._register(self.student_2, self.stop_2)
        self.assertEqual(reg_2.fee_amount, 600.0)

    def test_duplicate_active_registration_blocked(self):
        self._register(self.student_1, self.stop_1)
        with self.assertRaises(ValidationError):
            self._register(self.student_1, self.stop_2)

    def test_seats_available_decreases_on_confirm(self):
        reg = self._register(self.student_1, self.stop_1)
        reg.action_confirm()
        self.assertEqual(self.route.seats_available, 1)

    def test_confirm_blocked_when_route_full(self):
        reg_1 = self._register(self.student_1, self.stop_1)
        reg_1.action_confirm()
        reg_2 = self._register(self.student_2, self.stop_2)
        reg_2.action_confirm()
        self.assertEqual(self.route.seats_available, 0)
        reg_3 = self._register(self.student_3, self.stop_1)
        with self.assertRaises(ValidationError):
            reg_3.action_confirm()

    def test_confirm_creates_invoice(self):
        reg = self._register(self.student_1, self.stop_1)
        reg.action_confirm()
        self.assertTrue(reg.invoice_id)
        self.assertEqual(reg.invoice_id.move_type, 'out_invoice')
        self.assertEqual(reg.state, 'confirmed')

    def test_confirm_without_fee_product_raises(self):
        route_no_fee = self.env['bxi.transport.route'].create({
            'name': 'Route C',
            'code': 'RC',
            'vehicle_id': self.vehicle.id,
            'fee_product_id': self.fee_product.id,
            'state': 'active',
        })
        stop = self.env['bxi.transport.route.stop'].create({
            'route_id': route_no_fee.id,
            'name': 'Stop C',
        })
        reg = self._register(self.student_1, stop)
        route_no_fee.fee_product_id = False
        with self.assertRaises(UserError):
            reg.action_confirm()

    def test_activate_blocked_until_invoice_paid(self):
        reg = self._register(self.student_1, self.stop_1)
        reg.action_confirm()
        with self.assertRaises(ValidationError):
            reg.action_activate()

    def test_cancel_resets_state_and_frees_seat(self):
        reg = self._register(self.student_1, self.stop_1)
        reg.action_confirm()
        self.assertEqual(self.route.seats_available, 1)
        reg.action_cancel()
        self.assertEqual(reg.state, 'cancelled')
        self.assertEqual(self.route.seats_available, 2)

    def test_route_code_unique(self):
        with self.assertRaises(Exception):
            self.env['bxi.transport.route'].create({
                'name': 'Duplicate Code Route',
                'code': 'RA',
                'vehicle_id': self.vehicle.id,
                'fee_product_id': self.fee_product.id,
            })

    def test_driver_license_expiring_soon_computed(self):
        partner = self.env['res.partner'].create({'name': 'Test Driver'})
        driver = self.env['bxi.transport.driver'].create({
            'partner_id': partner.id,
            'license_number': 'DL12345',
            'license_type': 'hmv',
            'license_expiry': fields.Date.today() + timedelta(days=10),
        })
        self.assertTrue(driver.license_expiring_soon)

    def test_driver_unique_partner(self):
        partner = self.env['res.partner'].create({'name': 'Another Driver'})
        self.env['bxi.transport.driver'].create({
            'partner_id': partner.id,
            'license_number': 'DL1',
            'license_type': 'lmv',
            'license_expiry': fields.Date.today() + timedelta(days=60),
        })
        with self.assertRaises(Exception):
            self.env['bxi.transport.driver'].create({
                'partner_id': partner.id,
                'license_number': 'DL2',
                'license_type': 'lmv',
                'license_expiry': fields.Date.today() + timedelta(days=90),
            })
