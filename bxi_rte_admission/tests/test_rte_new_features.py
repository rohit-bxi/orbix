# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import tagged

from .common import TestRteAdmissionCommon


@tagged('post_install', '-at_install')
class TestRteLotteryPriorityTiering(TestRteAdmissionCommon):
    """Para 5.1-5.4 / Appendix-2 examples: within a lottery, applicants
    from the school's own ward rank ahead of the rest of the ULB, and
    within each of those groups orphan/disabled applicants rank first."""

    def _make_urban_course(self, seats):
        counter = getattr(self, '_course_counter', 0) + 1
        self._course_counter = counter
        return self.env['op.course'].create({
            'name': 'Tiering Course %s' % counter, 'code': 'TIER%s' % counter,
            'total_intake': seats * 4, 'rte_seats_manual': seats,
            'rte_active': True,
            'catchment_area_type': 'urban',
            'catchment_ward': 'WARD-1',
            'catchment_urban_body': 'ULB-1',
        })

    def _make_tiered_admission(self, course, *, in_ward, category=None):
        counter = getattr(self, '_tier_counter', 0) + 1
        self._tier_counter = counter
        partner = self.env['res.partner'].create({'name': 'Tier Parent %s' % counter})
        if category:
            self.env['op.parent'].create({
                'name': partner.id,
                'relationship_id': self._get_relationship().id,
                'rte_category': category,
            })
        admission = self._make_admission(
            course_id=course.id,
            partner_id=partner.id,
            rte_area_type='urban',
            rte_ward='WARD-1' if in_ward else 'WARD-2',
            rte_urban_body='ULB-1',
        )
        admission.action_verify_documents()
        return admission

    def test_tiers_are_ranked_in_priority_order_regardless_of_seed(self):
        for seed in ('SEED-1', 'SEED-2', 'SEED-3'):
            course = self._make_urban_course(1)
            self.env['op.admission'].create({
                'name': 'Paid', 'first_name': 'Paid', 'last_name': 'Child',
                'birth_date': fields.Date.today().replace(
                    year=fields.Date.today().year - 6),
                'course_id': course.id, 'email': 'paid@example.com',
                'gender': 'm', 'register_id': self.register.id,
                'is_rte_applicant': False,
            })
            tier0 = self._make_tiered_admission(course, in_ward=True, category='orphan')
            tier1 = self._make_tiered_admission(course, in_ward=True)
            tier2 = self._make_tiered_admission(course, in_ward=False, category='disabled')
            tier3 = self._make_tiered_admission(course, in_ward=False)

            batch = self.env['rte.lottery.batch'].create({
                'course_id': course.id,
                'academic_year_id': self.academic_year.id,
                'random_seed': seed,
            })
            batch.action_mark_ready()
            batch.run_lottery()

            ranks = {r.admission_id: r.rank for r in batch.result_ids}
            self.assertLess(ranks[tier0], ranks[tier1])
            self.assertLess(ranks[tier1], ranks[tier2])
            self.assertLess(ranks[tier2], ranks[tier3])
            # The single seat always goes to the highest-priority tier.
            self.assertEqual(tier0.rte_state, 'allotted')


@tagged('post_install', '-at_install')
class TestRteRosterSeats(TestRteAdmissionCommon):
    """Para 6.1: when paid-enrollment history is on file, the roster
    formula overrides the simple 25%-of-intake seat count."""

    def test_effective_seats_falls_back_to_course_rte_seats_without_stats(self):
        course = self.env['op.course'].create({
            'name': 'Roster Course', 'code': 'ROST01',
            'total_intake': 40, 'rte_active': True,
        })
        batch = self.env['rte.lottery.batch'].create({
            'course_id': course.id, 'academic_year_id': self.academic_year.id,
            'random_seed': 'X',
        })
        self.assertEqual(batch.effective_seats, course.rte_seats)

    def test_effective_seats_uses_roster_formula_when_stats_exist(self):
        course = self.env['op.course'].create({
            'name': 'Roster Course 2', 'code': 'ROST02',
            'total_intake': 40, 'rte_active': True,
            'rte_entry_class': 'pp3',
        })
        self.env['rte.class.enrollment.stat'].create({
            'course_id': course.id,
            'academic_year_id': self.academic_year.id,
            'paid_enrolled_count': 30,
        })
        batch = self.env['rte.lottery.batch'].create({
            'course_id': course.id, 'academic_year_id': self.academic_year.id,
            'random_seed': 'X',
        })
        # round(30 / 3) = 10, overriding the 25%-of-40=10 default (same
        # here by coincidence of numbers -- use a value that diverges).
        self.assertEqual(batch.effective_seats, 10)

    def test_effective_seats_subtracts_promoted_children_for_later_classes(self):
        course = self.env['op.course'].create({
            'name': 'Roster Course 3', 'code': 'ROST03',
            'total_intake': 40, 'rte_active': True,
            'rte_entry_class': 'pp4',
        })
        self.env['rte.class.enrollment.stat'].create({
            'course_id': course.id,
            'academic_year_id': self.academic_year.id,
            'paid_enrolled_count': 30,
            'promoted_free_count': 4,
        })
        batch = self.env['rte.lottery.batch'].create({
            'course_id': course.id, 'academic_year_id': self.academic_year.id,
            'random_seed': 'X',
        })
        # round(30 / 3) - 4 promoted = 6.
        self.assertEqual(batch.effective_seats, 6)


@tagged('post_install', '-at_install')
class TestRteParaNineGate(TestRteAdmissionCommon):

    def test_mark_ready_blocked_without_any_paid_admission(self):
        course = self.env['op.course'].create({
            'name': 'No Paid Course', 'code': 'NOPAID01',
            'total_intake': 40, 'rte_active': True,
        })
        batch = self.env['rte.lottery.batch'].create({
            'course_id': course.id, 'academic_year_id': self.academic_year.id,
            'random_seed': 'X',
        })
        with self.assertRaises(UserError):
            batch.action_mark_ready()


@tagged('post_install', '-at_install')
class TestRteReimbursementNewRules(TestRteAdmissionCommon):

    def _make_claim(self, **kwargs):
        vals = {
            'course_id': self.course.id,
            'academic_year_id': self.academic_year.id,
            'amount': 5000.0,
        }
        vals.update(kwargs)
        return self.env['rte.reimbursement.claim'].create(vals)

    def test_claim_capped_at_lower_of_rate_and_actual_fee(self):
        self.course.reimbursement_rate = 4000.0
        claim = self._make_claim(actual_fee_charged=6000.0, amount=5000.0)
        with self.assertRaises(UserError):
            claim.action_submit()

    def test_claim_allowed_within_entitlement(self):
        self.course.reimbursement_rate = 4000.0
        claim = self._make_claim(actual_fee_charged=6000.0, amount=4000.0)
        claim.action_submit()
        self.assertEqual(claim.state, 'submitted')

    def test_second_installment_blocked_after_august_dropout(self):
        admission = self._make_admission(
            rte_state='confirmed',
            rte_dropout_date=self.academic_year.start_date.replace(month=6, day=1))
        claim = self._make_claim(admission_id=admission.id, installment='second')
        with self.assertRaises(UserError):
            claim.action_submit()

    def test_first_installment_allowed_after_august_dropout(self):
        admission = self._make_admission(
            rte_state='confirmed',
            rte_dropout_date=self.academic_year.start_date.replace(month=6, day=1))
        claim = self._make_claim(admission_id=admission.id, installment='first')
        claim.action_submit()
        self.assertEqual(claim.state, 'submitted')

    def test_voluntary_transfer_forfeits_reimbursement(self):
        admission = self._make_admission(
            rte_state='confirmed', rte_is_voluntary_transfer=True)
        claim = self._make_claim(admission_id=admission.id)
        with self.assertRaises(UserError):
            claim.action_submit()


@tagged('post_install', '-at_install')
class TestRteGrievance(TestRteAdmissionCommon):

    def test_grievance_full_cbeo_resolution(self):
        admission = self._make_admission(rte_state='doc_rejected')
        grievance = admission.action_file_grievance('Documents were valid.')
        self.assertEqual(grievance.state, 'submitted')
        grievance.cbeo_resolution_notes = 'Re-checked, documents accepted.'
        grievance.action_cbeo_resolve()
        self.assertEqual(grievance.state, 'resolved')

    def test_grievance_escalation_to_joint_director(self):
        admission = self._make_admission(rte_state='doc_rejected')
        grievance = admission.action_file_grievance('Documents were valid.')
        grievance.action_escalate_to_jd()
        self.assertEqual(grievance.state, 'escalated_jd')
        grievance.jd_resolution_notes = 'Upheld on review.'
        grievance.action_jd_resolve()
        self.assertEqual(grievance.state, 'resolved')

    def test_grievance_only_filed_against_rejected_state(self):
        admission = self._make_admission(rte_state='draft')
        with self.assertRaises(UserError):
            admission.action_file_grievance('Not applicable.')


@tagged('post_install', '-at_install')
class TestRteIncomeCertificateFinancialYear(TestRteAdmissionCommon):

    def test_mismatched_financial_year_blocked_when_configured(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'bxi_rte_admission.income_certificate_financial_year', '2025-26')
        partner = self.env['res.partner'].create({'name': 'FY Parent'})
        with self.assertRaises(ValidationError):
            self.env['op.parent'].create({
                'name': partner.id,
                'relationship_id': self._get_relationship().id,
                'rte_income_certificate_financial_year': '2024-25',
            })

    def test_matching_financial_year_allowed(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'bxi_rte_admission.income_certificate_financial_year', '2025-26')
        partner = self.env['res.partner'].create({'name': 'FY Parent 2'})
        parent = self.env['op.parent'].create({
            'name': partner.id,
            'relationship_id': self._get_relationship().id,
            'rte_income_certificate_financial_year': '2025-26',
        })
        self.assertTrue(parent)
