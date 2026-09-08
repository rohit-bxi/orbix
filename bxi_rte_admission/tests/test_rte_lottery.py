# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import TestRteAdmissionCommon


@tagged('post_install', '-at_install')
class TestRteLottery(TestRteAdmissionCommon):
    """Tests for rte.lottery.batch.run_lottery().

    Eligibility, per the real ``run_lottery`` implementation, requires:
    is_rte_applicant = True, rte_state = 'doc_verified', and either
    course_id or a rte_preference_ids line pointing at the batch's course.
    """

    def _make_course(self, total_intake, **kwargs):
        vals = {
            'name': 'Lottery Course %s' % total_intake,
            'code': 'LC%s' % total_intake,
            'total_intake': total_intake,
            'rte_active': True,
        }
        vals.update(kwargs)
        course = self.env['op.course'].create(vals)
        # action_mark_ready requires at least one fee-paying (non-RTE)
        # admission on the course (para 9, point 09).
        self._make_admission(course_id=course.id, is_rte_applicant=False)
        return course

    def _make_eligible_admission(self, course, index):
        admission = self._make_admission(course_id=course.id)
        admission.action_verify_documents()
        self.assertEqual(admission.rte_state, 'doc_verified')
        return admission

    def _make_batch(self, course, seed, academic_year=None):
        return self.env['rte.lottery.batch'].create({
            'course_id': course.id,
            'academic_year_id': (academic_year or self.academic_year).id,
            'random_seed': seed,
        })

    def test_run_lottery_selects_exactly_rte_seats(self):
        course = self._make_course(8)  # rte_seats == 2
        self.assertEqual(course.rte_seats, 2)

        admissions = self.env['op.admission']
        for i in range(5):
            admissions |= self._make_eligible_admission(course, i)

        # A non-eligible applicant (documents not verified yet) must be
        # excluded from the draw entirely.
        ineligible = self._make_admission(course_id=course.id)
        self.assertEqual(ineligible.rte_state, 'draft')

        batch = self._make_batch(course, 'SEED-A')
        batch.action_mark_ready()
        self.assertEqual(batch.state, 'ready')
        batch.run_lottery()

        self.assertEqual(batch.state, 'run')
        self.assertTrue(batch.applicant_hash)
        self.assertTrue(batch.draw_date)
        self.assertEqual(len(batch.result_ids), 5)

        selected = batch.result_ids.filtered(lambda r: r.result_type == 'selected')
        waitlisted = batch.result_ids.filtered(lambda r: r.result_type == 'waitlisted')
        self.assertEqual(len(selected), 2)
        self.assertEqual(len(waitlisted), 3)

        # The ineligible applicant has no result and its rte_state is untouched.
        self.assertNotIn(ineligible, batch.result_ids.mapped('admission_id'))
        self.assertEqual(ineligible.rte_state, 'draft')

        # rte_state is synced on the eligible admissions.
        for result in selected:
            self.assertEqual(result.admission_id.rte_state, 'allotted')
        for result in waitlisted:
            self.assertEqual(result.admission_id.rte_state, 'waitlisted')

    def test_run_lottery_guarded_against_double_run(self):
        course = self._make_course(8)
        for i in range(3):
            self._make_eligible_admission(course, i)

        batch = self._make_batch(course, 'SEED-B')
        batch.action_mark_ready()
        batch.run_lottery()
        result_count = len(batch.result_ids)

        with self.assertRaises(UserError):
            batch.run_lottery()

        # No duplicate results were created by the guarded re-run attempt.
        self.assertEqual(len(batch.result_ids), result_count)
        self.assertEqual(batch.state, 'run')

    def test_run_lottery_requires_ready_state(self):
        course = self._make_course(8)
        self._make_eligible_admission(course, 0)
        batch = self._make_batch(course, 'SEED-C')
        # Still draft -- action_mark_ready was never called.
        with self.assertRaises(UserError):
            batch.run_lottery()

    def test_mark_ready_requires_draft_state(self):
        course = self._make_course(8)
        self._make_eligible_admission(course, 0)
        batch = self._make_batch(course, 'SEED-D')
        batch.action_mark_ready()
        with self.assertRaises(UserError):
            batch.action_mark_ready()

    def test_mark_ready_requires_rte_seats_configured(self):
        course = self._make_course(0)  # total_intake 0 -> rte_seats 0
        self.assertEqual(course.rte_seats, 0)
        batch = self._make_batch(course, 'SEED-E')
        with self.assertRaises(UserError):
            batch.action_mark_ready()

    def test_run_lottery_no_eligible_applicants_raises(self):
        course = self._make_course(8)
        batch = self._make_batch(course, 'SEED-F')
        batch.action_mark_ready()
        with self.assertRaises(UserError):
            batch.run_lottery()

    def test_publish_requires_run_state(self):
        course = self._make_course(8)
        self._make_eligible_admission(course, 0)
        batch = self._make_batch(course, 'SEED-G')
        with self.assertRaises(UserError):
            batch.action_publish()  # still draft
        batch.action_mark_ready()
        batch.run_lottery()
        batch.action_publish()
        self.assertEqual(batch.state, 'published')

    # -- Determinism / reproducibility ---------------------------------------

    def _selected_creation_indices(self, batch, admissions_in_creation_order):
        """Map each selected result back to the 0-based index of its
        admission in ``admissions_in_creation_order``, using the same
        application_number sort the real code uses to build its
        deterministic pre-shuffle ordering."""
        sorted_admissions = admissions_in_creation_order.sorted(
            key=lambda a: a.application_number or '')
        order_map = {a.id: idx for idx, a in enumerate(sorted_admissions)}
        selected_ids = batch.result_ids.filtered(
            lambda r: r.result_type == 'selected').mapped('admission_id').ids
        return sorted(order_map[aid] for aid in selected_ids)

    def test_same_seed_produces_same_selection_across_separate_runs(self):
        # Two independent courses/batches/applicant pools of identical
        # shape and the same seed must select the same relative positions
        # (by application-number rank) -- this is the auditability
        # guarantee the design doc calls for.
        course_1 = self._make_course(8)
        admissions_1 = self.env['op.admission']
        for i in range(6):
            admissions_1 |= self._make_eligible_admission(course_1, i)
        batch_1 = self._make_batch(course_1, 'REPRO-SEED-1')
        batch_1.action_mark_ready()
        batch_1.run_lottery()

        course_2 = self._make_course(8, code='LC8B')
        admissions_2 = self.env['op.admission']
        for i in range(6):
            admissions_2 |= self._make_eligible_admission(course_2, i)
        batch_2 = self._make_batch(course_2, 'REPRO-SEED-1')
        batch_2.action_mark_ready()
        batch_2.run_lottery()

        indices_1 = self._selected_creation_indices(batch_1, admissions_1)
        indices_2 = self._selected_creation_indices(batch_2, admissions_2)
        self.assertEqual(indices_1, indices_2)
        self.assertEqual(len(indices_1), course_1.rte_seats)

    def test_different_seed_can_produce_different_selection(self):
        # Not a strict guarantee for every seed pair, but with 8 applicants
        # and 2 seats it is extremely likely two arbitrary seeds diverge;
        # documents that the seed actually drives the outcome.
        course_1 = self._make_course(8)
        admissions_1 = self.env['op.admission']
        for i in range(8):
            admissions_1 |= self._make_eligible_admission(course_1, i)
        batch_1 = self._make_batch(course_1, 'SEED-X')
        batch_1.action_mark_ready()
        batch_1.run_lottery()

        course_2 = self._make_course(8, code='LC8B')
        admissions_2 = self.env['op.admission']
        for i in range(8):
            admissions_2 |= self._make_eligible_admission(course_2, i)
        batch_2 = self._make_batch(course_2, 'SEED-Y')
        batch_2.action_mark_ready()
        batch_2.run_lottery()

        indices_1 = self._selected_creation_indices(batch_1, admissions_1)
        indices_2 = self._selected_creation_indices(batch_2, admissions_2)
        self.assertNotEqual(indices_1, indices_2)

    def test_second_batch_for_same_course_and_year_blocked(self):
        # Guards against over-allotment: only one active (ready/run/
        # published) batch may exist per course/academic year at a time.
        course = self._make_course(8)
        for i in range(3):
            self._make_eligible_admission(course, i)

        batch_1 = self._make_batch(course, 'SEED-A')
        batch_1.action_mark_ready()

        batch_2 = self._make_batch(course, 'SEED-B')
        with self.assertRaises(UserError):
            batch_2.action_mark_ready()

    def test_batch_for_same_course_different_year_allowed(self):
        course = self._make_course(8)
        for i in range(3):
            self._make_eligible_admission(course, i)

        other_year = self.env['op.academic.year'].create({
            'name': 'RTE Test Year 2',
            'start_date': fields.Date.today().replace(
                year=fields.Date.today().year + 2),
            'end_date': fields.Date.today().replace(
                year=fields.Date.today().year + 3),
        })

        batch_1 = self._make_batch(course, 'SEED-A')
        batch_1.action_mark_ready()

        batch_2 = self._make_batch(course, 'SEED-B', academic_year=other_year)
        batch_2.action_mark_ready()
        self.assertEqual(batch_2.state, 'ready')

    def test_new_batch_allowed_after_previous_not_activated(self):
        # A second draft batch (never marked ready) does not block a new one.
        course = self._make_course(8)
        for i in range(3):
            self._make_eligible_admission(course, i)

        self._make_batch(course, 'SEED-A')  # left in draft
        batch_2 = self._make_batch(course, 'SEED-B')
        batch_2.action_mark_ready()
        self.assertEqual(batch_2.state, 'ready')
