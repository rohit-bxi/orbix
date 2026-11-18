# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.mail.tests.common import mail_new_test_user

from .common import ApiSupportHttpCase


@tagged('post_install', '-at_install')
class TestBxiApiSupportLibraryAdmin(ApiSupportHttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.librarian = mail_new_test_user(
            cls.env, login='libadm_librarian', password='LibPass1!',
            groups='base.group_user,openeducat_library.group_op_library_user')
        cls.teacher_user = mail_new_test_user(
            cls.env, login='libadm_teacher', password='TeacherPass1!',
            groups='base.group_user,openeducat_core.group_op_faculty')
        cls.parent_user = mail_new_test_user(
            cls.env, login='libadm_parent', password='ParentPass1!', groups='base.group_portal')
        cls.faculty = cls._create_faculty(cls.teacher_user, first_name='Libadm')
        cls.course, cls.batch = cls._create_class('LIBADM')
        cls.subject = cls.env['op.subject'].create({'name': 'Libadm Science', 'code': 'LIBADM-S'})
        cls.student = cls._create_student('LIBADM-001')
        cls._enroll(cls.student, cls.course, cls.batch)
        cls.parent = cls._create_parent(cls.parent_user, cls.student)
        cls.genre = cls.env['op.media.genre'].create({'name': 'Libadm Fiction'})
        cls.author = cls.env['op.author'].create({'name': 'Libadm Author'})
        cls.card_type = cls.env['op.library.card.type'].create({
            'name': 'Libadm Card', 'allow_media': 3, 'duration': 7, 'penalty_amt_per_day': 2.0})
        cls.env['product.product'].create({
            'name': 'Library Fine', 'default_code': 'LIB-FINE', 'type': 'service',
            'property_account_income_id': cls.income_account.id, 'taxes_id': [(5, 0, 0)],
        })

    def _lib(self):
        return self._headers('libadm_librarian', 'LibPass1!')

    def _post(self, path, payload=None, headers=None):
        return self.url_open(path, headers=headers or self._lib(), json=payload or {}, method='POST')

    def _book(self, **extra):
        return self._post('/api/v1/library/catalog', dict({
            'title': 'Libadm Atlas', 'genre_id': self.genre.id, 'author_ids': [self.author.id],
            'publishers': ['Libadm Press'], 'total_copies': 2, 'isbn': 'LIBADM-1'}, **extra))

    def test_access(self):
        for headers in (self._headers('libadm_teacher', 'TeacherPass1!'), self._headers('libadm_parent', 'ParentPass1!')):
            self.assertEqual(self._post('/api/v1/library/catalog', {'title': 'X'}, headers).status_code, 403)
            self.assertEqual(self.url_open('/api/v1/library/fines', headers=headers).status_code, 403)
            self.assertEqual(self.url_open('/api/v1/library/cards', headers=headers).status_code, 403)
        # Parents can't see or make purchase requests.
        parent = self._headers('libadm_parent', 'ParentPass1!')
        self.assertEqual(self.url_open('/api/v1/library/purchase-requests', headers=parent).status_code, 403)

    def test_catalog_create_update_and_copies(self):
        resp = self._book()
        self.assertEqual(resp.status_code, 201, resp.text)
        book = resp.json()['data']
        self.assertEqual(book['total_copies'], 2)
        self.assertEqual(len(book['copies']), 2)
        self.assertEqual(book['publishers'], ['Libadm Press'])
        self.assertEqual(self._book().json()['error']['code'], 'duplicate_isbn')
        self.assertEqual(self._post('/api/v1/library/catalog', {'title': 'No genre'}).json()['error']['code'],
                         'missing_genre_id')
        updated = self._post(f"/api/v1/library/catalog/{book['id']}/update",
                             {'shelf_location': 'B-2', 'authors': ['Second Writer']})
        self.assertEqual(updated.json()['data']['shelf_location'], 'B-2')
        self.assertEqual(updated.json()['data']['authors'], ['Second Writer'])
        added = self._post(f"/api/v1/library/catalog/{book['id']}/units", {'barcodes': ['LIBADM-BC1', 'LIBADM-BC2']})
        self.assertEqual(added.status_code, 201, added.text)
        self.assertEqual([u['barcode'] for u in added.json()['data']['added']], ['LIBADM-BC1', 'LIBADM-BC2'])
        self.assertEqual(added.json()['data']['media']['total_copies'], 4)
        self.assertEqual(self._post(f"/api/v1/library/catalog/{book['id']}/units", {'barcodes': ['LIBADM-BC1']})
                         .json()['error']['code'], 'duplicate_barcode')
        copies = self.url_open(f"/api/v1/library/catalog/{book['id']}/units", headers=self._lib()).json()['data']
        self.assertEqual(len(copies['copies']), 4)
        # Lowering the count archives a copy; adding one afterwards counts active copies only.
        lowered = self._post(f"/api/v1/library/catalog/{book['id']}/update", {'total_copies': 3})
        self.assertEqual(lowered.json()['data']['total_copies'], 3)
        self.assertEqual(len([c for c in lowered.json()['data']['copies'] if c['active']]), 3)
        again = self._post(f"/api/v1/library/catalog/{book['id']}/units", {'count': 1})
        self.assertEqual(again.json()['data']['media']['total_copies'], 4)
        media = self.env['op.media'].browse(book['id'])
        self.assertEqual(len(media.unit_ids), 4)
        self.assertEqual(len(media.with_context(active_test=False).unit_ids), 5)

    def test_cards(self):
        resp = self._post('/api/v1/library/cards', {'student_id': self.student.id, 'card_type_id': self.card_type.id})
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertEqual(resp.json()['data']['card_type']['loan_days'], 7)
        self.assertEqual(self._post('/api/v1/library/cards', {'student_id': self.student.id,
                                                             'card_type_id': self.card_type.id}).status_code, 409)
        teacher = self._post('/api/v1/library/cards', {'teacher_id': self.faculty.id, 'card_type_id': self.card_type.id})
        self.assertEqual(teacher.json()['data']['type'], 'faculty')
        self.assertEqual(self._post('/api/v1/library/cards', {'card_type_id': self.card_type.id}).json()['error']['code'],
                         'missing_borrower')
        listed = self.url_open(f'/api/v1/library/cards?student_id={self.student.id}', headers=self._lib()).json()
        self.assertEqual(listed['meta']['total'], 1)

    def _late_return(self):
        book = self._book().json()['data']
        self._post('/api/v1/library/cards', {'student_id': self.student.id, 'card_type_id': self.card_type.id})
        issued = self._post('/api/v1/library/issue', {
            'media_unit_id': book['copies'][0]['id'], 'student_id': self.student.id})
        self.assertEqual(issued.status_code, 201, issued.text)
        loan = issued.json()['data']
        late = fields.Date.to_string(fields.Date.today() + timedelta(days=10))
        self._post(f"/api/v1/library/loans/{loan['id']}/return", {'return_date': late})
        return loan['id']

    def test_fine_invoice_pay_and_settle(self):
        loan_id = self._late_return()
        fines = self.url_open('/api/v1/library/fines', headers=self._lib()).json()['data']
        self.assertEqual([f['id'] for f in fines['fines']], [loan_id])
        self.assertEqual(fines['summary']['unsettled_amount'], 6.0)  # 3 days late x 2.0
        self.assertEqual(self._post(f'/api/v1/library/loans/{loan_id}/settle-fine').json()['error']['code'],
                         'fine_unpaid')
        invoiced = self._post(f'/api/v1/library/loans/{loan_id}/fine-invoice')
        self.assertEqual(invoiced.status_code, 201, invoiced.text)
        invoice = invoiced.json()['data']['invoice']
        self.assertEqual(invoice['amount'], 6.0)
        self.assertEqual(self._post(f'/api/v1/library/loans/{loan_id}/fine-invoice').status_code, 409)
        move = self.env['account.move'].browse(invoice['id'])
        self.assertEqual(move.partner_id, self.student.partner_id)
        self.env['account.payment.register'].with_context(active_model='account.move', active_ids=move.ids).create(
            {'journal_id': self.cash_journal.id}).action_create_payments()
        settled = self._post(f'/api/v1/library/loans/{loan_id}/settle-fine')
        self.assertEqual(settled.status_code, 200, settled.text)
        self.assertTrue(settled.json()['data']['fine_settled'])
        self.assertEqual(self.url_open('/api/v1/library/fines', headers=self._lib()).json()['data']['fines'], [])

    def test_waive_fine_cancels_invoice(self):
        loan_id = self._late_return()
        invoice_id = self._post(f'/api/v1/library/loans/{loan_id}/fine-invoice').json()['data']['invoice']['id']
        waived = self._post(f'/api/v1/library/loans/{loan_id}/settle-fine', {'waive': True, 'note': 'First time'})
        self.assertEqual(waived.status_code, 200, waived.text)
        self.assertEqual(self.env['account.move'].browse(invoice_id).state, 'cancel')
        self.assertEqual(self._post(f'/api/v1/library/loans/{loan_id}/settle-fine', {'waive': True})
                         .json()['error']['code'], 'no_fine')

    def test_purchase_requests(self):
        teacher = self._headers('libadm_teacher', 'TeacherPass1!')
        created = self._post('/api/v1/library/purchase-requests', {
            'title': 'Libadm New Book', 'author': 'Someone', 'class_id': self.course.id,
            'subject_id': self.subject.id}, teacher)
        self.assertEqual(created.status_code, 201, created.text)
        request_id = created.json()['data']['id']
        self.assertEqual(created.json()['data']['state'], 'request')
        mine = self.url_open('/api/v1/library/purchase-requests', headers=teacher).json()['data']['requests']
        self.assertEqual([r['id'] for r in mine], [request_id])
        self.assertEqual(self._post(f'/api/v1/library/purchase-requests/{request_id}/accept', {}, teacher).status_code,
                         403)
        accepted = self._post(f'/api/v1/library/purchase-requests/{request_id}/accept')
        self.assertEqual(accepted.json()['data']['state'], 'accept')
        self.assertEqual(self._post(f'/api/v1/library/purchase-requests/{request_id}/reject').json()['error']['code'],
                         'invalid_transition')

    def test_masters(self):
        authors = self.url_open('/api/v1/masters/library-authors', headers=self._lib()).json()['data']['items']
        self.assertIn(self.author.id, [a['id'] for a in authors])
        types = self.url_open('/api/v1/masters/library-card-types', headers=self._lib()).json()['data']['items']
        self.assertIn(self.card_type.id, [t['id'] for t in types])
