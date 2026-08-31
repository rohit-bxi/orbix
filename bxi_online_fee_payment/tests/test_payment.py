from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.bxi_online_fee_payment.models.razorpay_client import RazorpayClient
from odoo.addons.mail.tests.common import mail_new_test_user

FAKE_RAZORPAY_ORDER = {'id': 'order_fake123'}


def _fake_create_order(self, amount, currency, receipt):
    return dict(FAKE_RAZORPAY_ORDER)


def _fake_create_order_failure(self, amount, currency, receipt):
    return None


@tagged('post_install', '-at_install')
class TestBxiOnlineFeePayment(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_accounting()

        cls.student = cls.env['op.student'].create({
            'first_name': 'Online', 'last_name': 'Payer', 'gr_no': 'PAY-001', 'gender': 'm',
        })
        cls.student.partner_id.property_account_receivable_id = cls.receivable_account

        cls.product = cls.env['product.product'].create({
            'name': 'Tuition Fee', 'lst_price': 1000.0,
            'property_account_income_id': cls.income_account.id, 'taxes_id': [(5, 0, 0)],
        })
        cls.fee_category = cls.env['bxi.fee.category'].create({
            'name': 'Tuition', 'code': 'TUIOP', 'product_id': cls.product.id, 'default_frequency': 'annual',
        })
        cls.structure = cls.env['op.fees.terms'].create({
            'name': 'Online Payment Structure', 'code': 'OPS001', 'fees_terms': 'fixed_date',
            'line_ids': [(0, 0, {'due_date': fields.Date.today(), 'value': 100.0})],
            'category_line_ids': [(0, 0, {
                'category_id': cls.fee_category.id, 'amount': 1000.0, 'frequency': 'annual',
            })],
            'installment_type': 'one_time', 'first_due_date': fields.Date.today(), 'allow_partial_payment': True,
        })
        cls.structure._sync_category_lines_to_elements()
        cls.detail = cls.env['op.student.fees.details'].create({
            'student_id': cls.student.id,
            'fees_line_id': cls.structure.line_ids[0].id,
            'product_id': cls.product.id,
            'amount': 1000.0,
            'date': fields.Date.today(),
            'state': 'draft',
        })
        # get_fee_payment_summary() only counts posted invoices (matches
        # its real-world contract - a draft fee line isn't a real
        # receivable yet), so the fixture needs an actual posted invoice.
        cls.detail.get_invoice()
        cls.detail.invoice_id.action_post()

        cls.env['ir.config_parameter'].sudo().set_param(
            'bxi_online_fee_payment.default_journal_id', str(cls.cash_journal.id))

        cls.parent_user = mail_new_test_user(
            cls.env, login='payer_parent', groups='base.group_portal', password='ParentPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='payer_other', groups='base.group_portal', password='OtherPass1!')
        relationship = cls.env['op.parent.relationship'].search([], limit=1) or cls.env['op.parent.relationship'].create({
            'name': 'Guardian',
        })
        cls.env['op.parent'].create({
            'name': cls.env['res.partner'].create({'name': 'Payer Parent', 'is_parent': True}).id,
            'relationship_id': relationship.id,
            'user_id': cls.parent_user.id,
            'student_ids': [(6, 0, [cls.student.id])],
        })

    @classmethod
    def _setup_accounting(cls):
        company = cls.env.company
        cls.income_account = cls.env['account.account'].search(
            [('account_type', '=', 'income'), ('company_ids', 'in', company.id)], limit=1)
        if not cls.income_account:
            cls.income_account = cls.env['account.account'].create({
                'name': 'Test Income', 'code': 'TINC04', 'account_type': 'income',
                'company_ids': [(6, 0, [company.id])],
            })
        cls.receivable_account = cls.env['account.account'].search(
            [('account_type', '=', 'asset_receivable'), ('company_ids', 'in', company.id)], limit=1)
        if not cls.receivable_account:
            cls.receivable_account = cls.env['account.account'].create({
                'name': 'Test Receivable', 'code': 'TREC04', 'account_type': 'asset_receivable',
                'reconcile': True, 'company_ids': [(6, 0, [company.id])],
            })
        cls.sale_journal = cls.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1)
        if not cls.sale_journal:
            cls.sale_journal = cls.env['account.journal'].create({
                'name': 'Test Sales Journal', 'type': 'sale', 'code': 'TSJ04',
            })
        cls.cash_journal = cls.env['account.journal'].search(
            [('type', '=', 'cash'), ('company_id', '=', company.id)], limit=1)
        if not cls.cash_journal:
            cls.cash_journal = cls.env['account.journal'].create({
                'name': 'Test Cash Journal', 'type': 'cash', 'code': 'TCJ04',
            })

    def _login_token(self, login, password):
        resp = self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})
        return resp.json()['data']['token']

    # -- summary ---------------------------------------------------------------

    def test_summary_requires_auth(self):
        resp = self.url_open(f'/api/v1/payments/summary?student_id={self.student.id}')
        self.assertEqual(resp.status_code, 401)

    def test_summary_accessible_to_linked_parent(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        resp = self.url_open(
            f'/api/v1/payments/summary?student_id={self.student.id}',
            headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data']['total_fee_amount'], 1000.0)

    def test_summary_forbidden_for_unrelated_user(self):
        token = self._login_token('payer_other', 'OtherPass1!')
        resp = self.url_open(
            f'/api/v1/payments/summary?student_id={self.student.id}',
            headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(resp.status_code, 403)

    def test_summary_missing_student_id_rejected(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        resp = self.url_open('/api/v1/payments/summary', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(resp.status_code, 400)

    def test_summary_unknown_student_not_found(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        missing_id = self.student.id + 1000000
        resp = self.url_open(
            f'/api/v1/payments/summary?student_id={missing_id}',
            headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(resp.status_code, 404)

    # -- create-order ------------------------------------------------------------

    @patch.object(RazorpayClient, 'create_order', _fake_create_order)
    def test_create_order_success(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        resp = self.url_open('/api/v1/payments/create-order', headers={'Authorization': f'Bearer {token}'}, json={
            'fees_detail_id': self.detail.id, 'amount': 500.0,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertEqual(data['razorpay_order_id'], 'order_fake123')
        self.assertEqual(data['amount'], 500.0)

    def test_create_order_forbidden_for_unrelated_user(self):
        token = self._login_token('payer_other', 'OtherPass1!')
        resp = self.url_open('/api/v1/payments/create-order', headers={'Authorization': f'Bearer {token}'}, json={
            'fees_detail_id': self.detail.id, 'amount': 500.0,
        })
        self.assertEqual(resp.status_code, 403)

    @patch.object(RazorpayClient, 'create_order', _fake_create_order)
    def test_create_order_amount_exceeds_pending_rejected(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        resp = self.url_open('/api/v1/payments/create-order', headers={'Authorization': f'Bearer {token}'}, json={
            'fees_detail_id': self.detail.id, 'amount': 999999.0,
        })
        self.assertEqual(resp.status_code, 400)

    @patch.object(RazorpayClient, 'create_order', _fake_create_order_failure)
    def test_create_order_gateway_failure_reported(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        resp = self.url_open('/api/v1/payments/create-order', headers={'Authorization': f'Bearer {token}'}, json={
            'fees_detail_id': self.detail.id, 'amount': 500.0,
        })
        self.assertEqual(resp.status_code, 502)

    def test_create_order_missing_fields_rejected(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        resp = self.url_open('/api/v1/payments/create-order', headers={'Authorization': f'Bearer {token}'}, json={
            'fees_detail_id': self.detail.id,
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_order_unknown_fee_line_not_found(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        missing_id = self.detail.id + 1000000
        resp = self.url_open('/api/v1/payments/create-order', headers={'Authorization': f'Bearer {token}'}, json={
            'fees_detail_id': missing_id, 'amount': 500.0,
        })
        self.assertEqual(resp.status_code, 404)

    # -- verify (client-reported) ------------------------------------------------

    @patch.object(RazorpayClient, 'create_order', _fake_create_order)
    @patch.object(RazorpayClient, 'verify_payment_signature', lambda self, o, p, s: True)
    def test_verify_correct_signature_reconciles_payment(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        headers = {'Authorization': f'Bearer {token}'}
        create_resp = self.url_open('/api/v1/payments/create-order', headers=headers, json={
            'fees_detail_id': self.detail.id, 'amount': 500.0,
        })
        order_id = create_resp.json()['data']['payment_order_id']

        verify_resp = self.url_open('/api/v1/payments/verify', headers=headers, json={
            'payment_order_id': order_id,
            'razorpay_payment_id': 'pay_fake123',
            'razorpay_signature': 'whatever-since-mocked',
        })
        self.assertEqual(verify_resp.status_code, 200)
        self.assertEqual(verify_resp.json()['data']['status'], 'paid')

        order = self.env['bxi.payment.order'].sudo().browse(order_id)
        self.assertEqual(order.status, 'paid')
        self.assertAlmostEqual(self.detail.amount_paid, 500.0)

    @patch.object(RazorpayClient, 'create_order', _fake_create_order)
    @patch.object(RazorpayClient, 'verify_payment_signature', lambda self, o, p, s: False)
    def test_verify_wrong_signature_rejected(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        headers = {'Authorization': f'Bearer {token}'}
        create_resp = self.url_open('/api/v1/payments/create-order', headers=headers, json={
            'fees_detail_id': self.detail.id, 'amount': 500.0,
        })
        order_id = create_resp.json()['data']['payment_order_id']

        verify_resp = self.url_open('/api/v1/payments/verify', headers=headers, json={
            'payment_order_id': order_id,
            'razorpay_payment_id': 'pay_fake123',
            'razorpay_signature': 'tampered',
        })
        self.assertEqual(verify_resp.status_code, 400)
        order = self.env['bxi.payment.order'].sudo().browse(order_id)
        self.assertEqual(order.status, 'failed')

    def test_verify_missing_fields_rejected(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        resp = self.url_open('/api/v1/payments/verify', headers={'Authorization': f'Bearer {token}'}, json={
            'payment_order_id': 1,
        })
        self.assertEqual(resp.status_code, 400)

    def test_verify_unknown_order_not_found(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        resp = self.url_open('/api/v1/payments/verify', headers={'Authorization': f'Bearer {token}'}, json={
            'payment_order_id': 999999,
            'razorpay_payment_id': 'pay_x',
            'razorpay_signature': 'sig',
        })
        self.assertEqual(resp.status_code, 404)

    @patch.object(RazorpayClient, 'create_order', _fake_create_order)
    def test_verify_order_belonging_to_other_user_not_found(self):
        parent_token = self._login_token('payer_parent', 'ParentPass1!')
        create_resp = self.url_open('/api/v1/payments/create-order', headers={'Authorization': f'Bearer {parent_token}'}, json={
            'fees_detail_id': self.detail.id, 'amount': 500.0,
        })
        order_id = create_resp.json()['data']['payment_order_id']

        other_token = self._login_token('payer_other', 'OtherPass1!')
        resp = self.url_open('/api/v1/payments/verify', headers={'Authorization': f'Bearer {other_token}'}, json={
            'payment_order_id': order_id,
            'razorpay_payment_id': 'pay_x',
            'razorpay_signature': 'sig',
        })
        self.assertEqual(resp.status_code, 404)

    @patch.object(RazorpayClient, 'create_order', _fake_create_order)
    @patch.object(RazorpayClient, 'verify_payment_signature', lambda self, o, p, s: True)
    def test_verify_already_paid_order_is_idempotent(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        headers = {'Authorization': f'Bearer {token}'}
        create_resp = self.url_open('/api/v1/payments/create-order', headers=headers, json={
            'fees_detail_id': self.detail.id, 'amount': 500.0,
        })
        order_id = create_resp.json()['data']['payment_order_id']

        payload = {
            'payment_order_id': order_id,
            'razorpay_payment_id': 'pay_fake123',
            'razorpay_signature': 'whatever-since-mocked',
        }
        first_resp = self.url_open('/api/v1/payments/verify', headers=headers, json=payload)
        self.assertEqual(first_resp.status_code, 200)
        self.assertAlmostEqual(self.detail.amount_paid, 500.0)

        # Re-submitting verify for an already-paid order must not
        # re-trigger reconciliation (which would double-pay the fee line).
        second_resp = self.url_open('/api/v1/payments/verify', headers=headers, json=payload)
        self.assertEqual(second_resp.status_code, 200)
        self.assertEqual(second_resp.json()['data']['status'], 'paid')
        self.assertAlmostEqual(self.detail.amount_paid, 500.0)

    # -- webhook -------------------------------------------------------------

    @patch.object(RazorpayClient, 'create_order', _fake_create_order)
    @patch.object(RazorpayClient, 'verify_webhook_signature', lambda self, body, sig: True)
    def test_webhook_reconciles_payment(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        create_resp = self.url_open('/api/v1/payments/create-order', headers={'Authorization': f'Bearer {token}'}, json={
            'fees_detail_id': self.detail.id, 'amount': 500.0,
        })
        order_id = create_resp.json()['data']['payment_order_id']

        webhook_resp = self.url_open('/api/v1/payments/webhook', headers={'X-Razorpay-Signature': 'sig'}, json={
            'payload': {'payment': {'entity': {'id': 'pay_webhook1', 'order_id': 'order_fake123'}}},
        })
        self.assertEqual(webhook_resp.status_code, 200)
        order = self.env['bxi.payment.order'].sudo().browse(order_id)
        self.assertEqual(order.status, 'paid')

    @patch.object(RazorpayClient, 'verify_webhook_signature', lambda self, body, sig: False)
    def test_webhook_bad_signature_rejected(self):
        resp = self.url_open('/api/v1/payments/webhook', headers={'X-Razorpay-Signature': 'bad'}, json={
            'payload': {'payment': {'entity': {'id': 'pay_x', 'order_id': 'order_fake123'}}},
        })
        self.assertEqual(resp.status_code, 400)

    @patch.object(RazorpayClient, 'verify_webhook_signature', lambda self, body, sig: True)
    def test_webhook_malformed_payload_rejected(self):
        resp = self.url_open('/api/v1/payments/webhook', headers={'X-Razorpay-Signature': 'sig'}, json={
            'payload': {'payment': {'entity': {}}},
        })
        self.assertEqual(resp.status_code, 400)

    @patch.object(RazorpayClient, 'verify_webhook_signature', lambda self, body, sig: True)
    def test_webhook_unknown_order_acknowledged_and_ignored(self):
        # A webhook for an order we don't know about (different feature, or
        # never created here) must still be acknowledged with 200 so
        # Razorpay does not keep retrying it.
        resp = self.url_open('/api/v1/payments/webhook', headers={'X-Razorpay-Signature': 'sig'}, json={
            'payload': {'payment': {'entity': {'id': 'pay_unknown', 'order_id': 'order_does_not_exist'}}},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['data']['ignored'])

    @patch.object(RazorpayClient, 'create_order', _fake_create_order)
    @patch.object(RazorpayClient, 'verify_webhook_signature', lambda self, body, sig: True)
    def test_webhook_replay_on_already_paid_order_is_idempotent(self):
        token = self._login_token('payer_parent', 'ParentPass1!')
        create_resp = self.url_open('/api/v1/payments/create-order', headers={'Authorization': f'Bearer {token}'}, json={
            'fees_detail_id': self.detail.id, 'amount': 500.0,
        })
        order_id = create_resp.json()['data']['payment_order_id']

        webhook_payload = {
            'payload': {'payment': {'entity': {'id': 'pay_webhook_replay', 'order_id': 'order_fake123'}}},
        }
        first_resp = self.url_open('/api/v1/payments/webhook', headers={'X-Razorpay-Signature': 'sig'}, json=webhook_payload)
        self.assertEqual(first_resp.status_code, 200)
        self.assertAlmostEqual(self.detail.amount_paid, 500.0)

        # Razorpay may deliver the same webhook more than once - replaying it
        # must not re-trigger reconciliation and double-pay the fee line.
        second_resp = self.url_open('/api/v1/payments/webhook', headers={'X-Razorpay-Signature': 'sig'}, json=webhook_payload)
        self.assertEqual(second_resp.status_code, 200)
        order = self.env['bxi.payment.order'].sudo().browse(order_id)
        self.assertEqual(order.status, 'paid')
        self.assertAlmostEqual(self.detail.amount_paid, 500.0)

    # -- reconciliation edge cases ------------------------------------------

    @patch.object(RazorpayClient, 'create_order', _fake_create_order)
    @patch.object(RazorpayClient, 'verify_payment_signature', lambda self, o, p, s: True)
    def test_verify_without_configured_journal_raises(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_online_fee_payment.default_journal_id', '')
        try:
            token = self._login_token('payer_parent', 'ParentPass1!')
            headers = {'Authorization': f'Bearer {token}'}
            create_resp = self.url_open('/api/v1/payments/create-order', headers=headers, json={
                'fees_detail_id': self.detail.id, 'amount': 500.0,
            })
            order_id = create_resp.json()['data']['payment_order_id']

            with self.assertRaises(Exception):
                self.env['bxi.payment.order'].sudo().browse(order_id)._mark_paid_from_client(
                    'pay_fake123', 'whatever-since-mocked')
        finally:
            self.env['ir.config_parameter'].sudo().set_param(
                'bxi_online_fee_payment.default_journal_id', str(self.cash_journal.id))


@tagged('post_install', '-at_install')
class TestBxiRazorpayClient(TransactionCase):
    """Unit tests for bxi.razorpay.client itself - the controller tests above
    mock this class out entirely, so its own config/HTTP-handling logic
    (never configured, gateway error responses, missing secrets) is
    otherwise untested.
    """

    def setUp(self):
        super().setUp()
        self.client = self.env['bxi.razorpay.client'].sudo()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('bxi_online_fee_payment.razorpay_key_id', '')
        ICP.set_param('bxi_online_fee_payment.razorpay_key_secret', '')
        ICP.set_param('bxi_online_fee_payment.razorpay_webhook_secret', '')

    def test_is_configured_false_when_keys_missing(self):
        self.assertFalse(self.client.is_configured())

    def test_is_configured_true_when_keys_present(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('bxi_online_fee_payment.razorpay_key_id', 'key_id')
        ICP.set_param('bxi_online_fee_payment.razorpay_key_secret', 'key_secret')
        self.assertTrue(self.client.is_configured())

    def test_create_order_returns_none_when_not_configured(self):
        self.assertIsNone(self.client.create_order(amount=100.0, currency='INR', receipt='r1'))

    @patch('odoo.addons.bxi_online_fee_payment.models.razorpay_client.requests.post')
    def test_create_order_returns_none_on_gateway_error_status(self, mock_post):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('bxi_online_fee_payment.razorpay_key_id', 'key_id')
        ICP.set_param('bxi_online_fee_payment.razorpay_key_secret', 'key_secret')
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = 'Bad Request'
        mock_post.return_value = mock_response

        self.assertIsNone(self.client.create_order(amount=100.0, currency='INR', receipt='r1'))

    @patch('odoo.addons.bxi_online_fee_payment.models.razorpay_client.requests.post')
    def test_create_order_converts_amount_to_minor_units(self, mock_post):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('bxi_online_fee_payment.razorpay_key_id', 'key_id')
        ICP.set_param('bxi_online_fee_payment.razorpay_key_secret', 'key_secret')
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'id': 'order_x'}
        mock_post.return_value = mock_response

        result = self.client.create_order(amount=123.45, currency='INR', receipt='r1')
        self.assertEqual(result['id'], 'order_x')
        self.assertEqual(mock_post.call_args.kwargs['json']['amount'], 12345)

    def test_verify_payment_signature_false_when_secret_missing(self):
        self.assertFalse(self.client.verify_payment_signature('order_1', 'pay_1', 'anything'))

    def test_verify_payment_signature_matches_expected_hmac(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'bxi_online_fee_payment.razorpay_key_secret', 'shhh')
        import hashlib
        import hmac
        expected = hmac.new(b'shhh', b'order_1|pay_1', hashlib.sha256).hexdigest()
        self.assertTrue(self.client.verify_payment_signature('order_1', 'pay_1', expected))
        self.assertFalse(self.client.verify_payment_signature('order_1', 'pay_1', 'wrong'))

    def test_verify_webhook_signature_false_when_secret_missing(self):
        self.assertFalse(self.client.verify_webhook_signature(b'{}', 'anything'))

    def test_verify_webhook_signature_matches_expected_hmac(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'bxi_online_fee_payment.razorpay_webhook_secret', 'whsecret')
        import hashlib
        import hmac
        body = b'{"event": "payment.captured"}'
        expected = hmac.new(b'whsecret', body, hashlib.sha256).hexdigest()
        self.assertTrue(self.client.verify_webhook_signature(body, expected))
        self.assertFalse(self.client.verify_webhook_signature(body, 'wrong'))
