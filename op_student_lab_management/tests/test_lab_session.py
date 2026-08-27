from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestLabSession(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['op.course'].create({
            'name': 'Lab Course', 'code': 'LBC',
        })
        cls.batch = cls.env['op.batch'].create({
            'name': 'Lab Batch', 'code': 'LBB',
            'course_id': cls.course.id,
            'start_date': '2026-06-01', 'end_date': '2027-05-31',
        })
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Ada', 'last_name': 'Lovelace',
            'birth_date': '1980-01-01', 'gender': 'female',
        })
        cls.room = cls.env['lab.room'].create({
            'name': 'Physics Lab', 'code': 'PHY-1',
        })
        cls.student_1 = cls.env['op.student'].create({
            'first_name': 'Sam', 'last_name': 'One',
            'gr_no': 'LAB-001', 'gender': 'm',
            'course_detail_ids': [(0, 0, {
                'course_id': cls.course.id, 'batch_id': cls.batch.id,
            })],
        })
        cls.student_2 = cls.env['op.student'].create({
            'first_name': 'Sara', 'last_name': 'Two',
            'gr_no': 'LAB-002', 'gender': 'f',
            'course_detail_ids': [(0, 0, {
                'course_id': cls.course.id, 'batch_id': cls.batch.id,
            })],
        })

    def _make_session(self, start_time, end_time, room=None, faculty=None, students=None, date='2026-09-01'):
        return self.env['lab.session'].create({
            'room_id': (room or self.room).id,
            'course_id': self.course.id,
            'batch_id': self.batch.id,
            'faculty_id': (faculty or self.faculty).id,
            'date': date,
            'start_time': start_time,
            'end_time': end_time,
            'student_ids': [(6, 0, [s.id for s in (students or [])])],
        })

    # -- lab room -------------------------------------------------------

    def test_room_code_unique(self):
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['lab.room'].create({'name': 'Another Lab', 'code': 'PHY-1'})

    def test_room_session_count_computed(self):
        self._make_session(9.0, 10.0)
        self.assertEqual(self.room.session_count, 1)

    # -- session reference & booking conflicts --------------------------

    def test_session_sequence_assigned_on_create(self):
        session = self._make_session(9.0, 10.0)
        self.assertNotEqual(session.name, 'New')
        self.assertTrue(session.name)

    def test_end_time_before_start_time_blocked(self):
        with self.assertRaises(ValidationError):
            self._make_session(10.0, 9.0)

    def test_room_double_booking_blocked(self):
        self._make_session(9.0, 11.0)
        with self.assertRaises(ValidationError):
            self._make_session(10.0, 12.0)

    def test_room_adjacent_booking_allowed(self):
        self._make_session(9.0, 11.0)
        # Starts exactly when the first session ends: no overlap.
        session = self._make_session(11.0, 12.0)
        self.assertTrue(session)

    def test_room_conflict_ignored_when_cancelled(self):
        first = self._make_session(9.0, 11.0)
        first.action_cancel()
        # Should not raise since the earlier session is cancelled.
        session = self._make_session(9.0, 11.0)
        self.assertTrue(session)

    def test_faculty_double_booking_across_rooms_blocked(self):
        other_room = self.env['lab.room'].create({
            'name': 'Chemistry Lab', 'code': 'CHM-1',
        })
        self._make_session(9.0, 11.0)
        with self.assertRaises(ValidationError):
            self._make_session(10.0, 12.0, room=other_room)

    # -- onchange & attendance generation --------------------------------

    def test_onchange_batch_id_populates_students(self):
        session = self.env['lab.session'].new({
            'room_id': self.room.id, 'course_id': self.course.id,
            'batch_id': self.batch.id, 'faculty_id': self.faculty.id,
            'date': '2026-09-01', 'start_time': 9.0, 'end_time': 10.0,
        })
        session._onchange_batch_id()
        self.assertEqual(set(session.student_ids.ids), {self.student_1.id, self.student_2.id})

    def test_confirm_generates_attendance_for_all_students(self):
        session = self._make_session(9.0, 10.0, students=[self.student_1, self.student_2])
        session.action_confirm()
        self.assertEqual(session.state, 'confirmed')
        self.assertEqual(len(session.attendance_ids), 2)
        self.assertEqual(set(session.attendance_ids.mapped('status')), {'present'})

    def test_regenerate_attendance_removes_deselected_students(self):
        session = self._make_session(9.0, 10.0, students=[self.student_1, self.student_2])
        session.action_confirm()
        session.student_ids = [(6, 0, [self.student_1.id])]
        session._generate_attendance()
        self.assertEqual(session.attendance_ids.student_id, self.student_1)

    def test_attendance_unique_per_session_and_student(self):
        session = self._make_session(9.0, 10.0, students=[self.student_1])
        session.action_confirm()
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['lab.attendance'].create({
                'session_id': session.id, 'student_id': self.student_1.id,
            })

    def test_session_state_workflow(self):
        session = self._make_session(9.0, 10.0)
        self.assertEqual(session.state, 'draft')
        session.action_confirm()
        self.assertEqual(session.state, 'confirmed')
        session.action_start()
        self.assertEqual(session.state, 'in_progress')
        session.action_done()
        self.assertEqual(session.state, 'done')
        session.action_reset_draft()
        self.assertEqual(session.state, 'draft')
