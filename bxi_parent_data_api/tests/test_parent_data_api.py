from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged('post_install', '-at_install')
class TestBxiParentDataApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.student = cls.env['op.student'].create({
            'first_name': 'Dashboard', 'last_name': 'Kid', 'gr_no': 'DASH-001', 'gender': 'f',
        })

        cls.parent_user = mail_new_test_user(
            cls.env, login='dash_parent', groups='base.group_portal', password='ParentPass1!')
        cls.other_user = mail_new_test_user(
            cls.env, login='dash_other', groups='base.group_portal', password='OtherPass1!')
        cls.staff_user = mail_new_test_user(
            cls.env, login='dash_staff', groups='base.group_user', password='StaffPass1!')
        relationship = cls.env['op.parent.relationship'].search([], limit=1) or cls.env['op.parent.relationship'].create({
            'name': 'Guardian',
        })
        cls.parent = cls.env['op.parent'].create({
            'name': cls.env['res.partner'].create({'name': 'Dashboard Parent', 'is_parent': True}).id,
            'relationship_id': relationship.id,
            'user_id': cls.parent_user.id,
            'student_ids': [(6, 0, [cls.student.id])],
        })

        cls.course = cls.env['op.course'].create({'name': 'Grade 5', 'code': 'G5DASH'})
        cls.batch = cls.env['op.batch'].create({
            'name': 'Batch A', 'code': 'BADASH', 'course_id': cls.course.id,
            'end_date': fields.Date.today() + timedelta(days=180),
        })
        cls.subject = cls.env['op.subject'].create({'name': 'Mathematics', 'code': 'MATHDASH'})
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Dash', 'last_name': 'Teacher', 'birth_date': '1985-01-01', 'gender': 'female',
        })

        # -- attendance fixture ------------------------------------------------
        cls.attendance_register = cls.env['op.attendance.register'].create({
            'name': 'Reg', 'code': 'ARDASH', 'course_id': cls.course.id, 'batch_id': cls.batch.id,
        })
        cls.attendance_sheets = cls.env['op.attendance.sheet']
        today = fields.Date.today()
        for i, present in enumerate([True, True, False, True, False]):
            sheet = cls.env['op.attendance.sheet'].create({
                'register_id': cls.attendance_register.id,
                'attendance_date': today - timedelta(days=i),
            })
            cls.env['op.attendance.line'].create({
                'attendance_id': sheet.id,
                'student_id': cls.student.id,
                'present': present,
                'absent': not present,
            })
            cls.attendance_sheets |= sheet

        # -- timetable fixture ---------------------------------------------------
        cls.session_soon = cls.env['op.session'].create({
            'start_datetime': fields.Datetime.now() + timedelta(hours=2),
            'end_datetime': fields.Datetime.now() + timedelta(hours=3),
            'course_id': cls.course.id, 'batch_id': cls.batch.id, 'subject_id': cls.subject.id,
            'faculty_id': cls.faculty.id,
            'student_ids': [(6, 0, [cls.student.id])],
            'state': 'confirm',
        })
        cls.session_past = cls.env['op.session'].create({
            'start_datetime': fields.Datetime.now() - timedelta(days=2),
            'end_datetime': fields.Datetime.now() - timedelta(days=2) + timedelta(hours=1),
            'course_id': cls.course.id, 'batch_id': cls.batch.id, 'subject_id': cls.subject.id,
            'faculty_id': cls.faculty.id,
            'student_ids': [(6, 0, [cls.student.id])],
            'state': 'done',
        })

        # -- exam result fixture ---------------------------------------------------
        cls.exam_type = cls.env['op.exam.type'].create({'name': 'Unit Test', 'code': 'UTDASH'})
        cls.exam_session = cls.env['op.exam.session'].create({
            'name': 'Term 1', 'course_id': cls.course.id, 'batch_id': cls.batch.id,
            'exam_code': 'ESDASH', 'start_date': today, 'end_date': today, 'exam_type': cls.exam_type.id,
            'state': 'schedule',
        })
        cls.exam = cls.env['op.exam'].create({
            'session_id': cls.exam_session.id, 'subject_id': cls.subject.id, 'exam_code': 'EXDASH',
            'start_time': fields.Datetime.now(), 'end_time': fields.Datetime.now() + timedelta(hours=1),
            'name': 'Maths Term 1', 'total_marks': 100, 'min_marks': 35, 'state': 'done',
        })
        cls.result_template = cls.env['op.result.template'].create({
            'exam_session_id': cls.exam_session.id, 'name': 'Template',
        })
        cls.marksheet_register = cls.env['op.marksheet.register'].create({
            'exam_session_id': cls.exam_session.id, 'name': 'Marksheet Register',
            'result_template_id': cls.result_template.id, 'state': 'validated',
        })
        cls.marksheet_line = cls.env['op.marksheet.line'].create({
            'marksheet_reg_id': cls.marksheet_register.id, 'student_id': cls.student.id,
        })
        cls.env['op.result.line'].create({
            'marksheet_line_id': cls.marksheet_line.id, 'exam_id': cls.exam.id,
            'student_id': cls.student.id, 'marks': 82,
        })

    def _headers(self, login, password):
        resp = self.url_open('/api/v1/auth/login', json={'login': login, 'password': password})
        return {'Authorization': f'Bearer {resp.json()["data"]["token"]}'}

    # -- exam results ---------------------------------------------------------------

    def test_exam_results_returns_validated_marksheet(self):
        resp = self.url_open(
            f'/api/v1/parent/exam-results?student_id={self.student.id}',
            headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 200)
        results = resp.json()['data']['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['status'], 'pass')
        self.assertEqual(results[0]['subjects'][0]['marks'], 82)

    def test_exam_results_forbidden_for_unrelated_user(self):
        resp = self.url_open(
            f'/api/v1/parent/exam-results?student_id={self.student.id}',
            headers=self._headers('dash_other', 'OtherPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_exam_results_requires_auth(self):
        resp = self.url_open(f'/api/v1/parent/exam-results?student_id={self.student.id}')
        self.assertEqual(resp.status_code, 401)

    # -- attendance ---------------------------------------------------------------------

    def test_attendance_summary_computed_correctly(self):
        resp = self.url_open(
            f'/api/v1/parent/attendance?student_id={self.student.id}',
            headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 200)
        summary = resp.json()['data']['summary']
        self.assertEqual(summary['total'], 5)
        self.assertEqual(summary['present'], 3)
        self.assertEqual(summary['absent'], 2)
        self.assertEqual(summary['attendance_percentage'], 60.0)

    # -- timetable -----------------------------------------------------------------------

    def test_timetable_returns_only_future_sessions_by_default(self):
        resp = self.url_open(
            f'/api/v1/parent/timetable?student_id={self.student.id}',
            headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 200)
        sessions = resp.json()['data']['sessions']
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['id'], self.session_soon.id)

    # -- dashboard -----------------------------------------------------------------------

    def test_dashboard_aggregates_everything(self):
        resp = self.url_open(
            f'/api/v1/parent/dashboard?student_id={self.student.id}',
            headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertEqual(data['student']['id'], self.student.id)
        self.assertIn('fee_summary', data)
        self.assertEqual(data['attendance_last_30_days']['present'], 3)
        self.assertEqual(len(data['upcoming_sessions']), 1)
        self.assertEqual(data['latest_exam_result']['status'], 'pass')

    def test_dashboard_forbidden_for_unrelated_user(self):
        resp = self.url_open(
            f'/api/v1/parent/dashboard?student_id={self.student.id}',
            headers=self._headers('dash_other', 'OtherPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_missing_student_id_rejected(self):
        resp = self.url_open('/api/v1/parent/dashboard', headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 400)

    # -- shared auth/authorization gaps across all routes ----------------------------

    def test_exam_results_student_not_found(self):
        resp = self.url_open(
            '/api/v1/parent/exam-results?student_id=999999999',
            headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 404)

    def test_exam_results_missing_student_id(self):
        resp = self.url_open('/api/v1/parent/exam-results', headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 400)

    def test_exam_results_accessible_by_staff_user(self):
        resp = self.url_open(
            f'/api/v1/parent/exam-results?student_id={self.student.id}',
            headers=self._headers('dash_staff', 'StaffPass1!'))
        self.assertEqual(resp.status_code, 200)

    # -- attendance ---------------------------------------------------------------------

    def test_attendance_forbidden_for_unrelated_user(self):
        resp = self.url_open(
            f'/api/v1/parent/attendance?student_id={self.student.id}',
            headers=self._headers('dash_other', 'OtherPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_attendance_requires_auth(self):
        resp = self.url_open(f'/api/v1/parent/attendance?student_id={self.student.id}')
        self.assertEqual(resp.status_code, 401)

    def test_attendance_missing_student_id(self):
        resp = self.url_open('/api/v1/parent/attendance', headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 400)

    def test_attendance_student_not_found(self):
        resp = self.url_open(
            '/api/v1/parent/attendance?student_id=999999999',
            headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 404)

    def test_attendance_custom_date_range_narrows_records(self):
        today = fields.Date.today()
        date_from = fields.Date.to_string(today - timedelta(days=1))
        resp = self.url_open(
            f'/api/v1/parent/attendance?student_id={self.student.id}'
            f'&date_from={date_from}&date_to={fields.Date.to_string(today)}',
            headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 200)
        summary = resp.json()['data']['summary']
        # Only the two most recent attendance sheets (today, yesterday) fall in range.
        self.assertEqual(summary['total'], 2)

    # -- timetable -----------------------------------------------------------------------

    def test_timetable_forbidden_for_unrelated_user(self):
        resp = self.url_open(
            f'/api/v1/parent/timetable?student_id={self.student.id}',
            headers=self._headers('dash_other', 'OtherPass1!'))
        self.assertEqual(resp.status_code, 403)

    def test_timetable_requires_auth(self):
        resp = self.url_open(f'/api/v1/parent/timetable?student_id={self.student.id}')
        self.assertEqual(resp.status_code, 401)

    def test_timetable_missing_student_id(self):
        resp = self.url_open('/api/v1/parent/timetable', headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 400)

    def test_timetable_student_not_found(self):
        resp = self.url_open(
            '/api/v1/parent/timetable?student_id=999999999',
            headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 404)

    def test_timetable_custom_date_range_includes_past_session(self):
        date_from = fields.Datetime.to_string(fields.Datetime.now() - timedelta(days=3))
        date_to = fields.Datetime.to_string(fields.Datetime.now() - timedelta(days=1))
        resp = self.url_open(
            f'/api/v1/parent/timetable?student_id={self.student.id}'
            f'&date_from={date_from}&date_to={date_to}',
            headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 200)
        sessions = resp.json()['data']['sessions']
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]['id'], self.session_past.id)

    # -- dashboard -----------------------------------------------------------------------

    def test_dashboard_requires_auth(self):
        resp = self.url_open(f'/api/v1/parent/dashboard?student_id={self.student.id}')
        self.assertEqual(resp.status_code, 401)

    def test_dashboard_student_not_found(self):
        resp = self.url_open(
            '/api/v1/parent/dashboard?student_id=999999999',
            headers=self._headers('dash_parent', 'ParentPass1!'))
        self.assertEqual(resp.status_code, 404)

    def test_dashboard_accessible_by_staff_user(self):
        resp = self.url_open(
            f'/api/v1/parent/dashboard?student_id={self.student.id}',
            headers=self._headers('dash_staff', 'StaffPass1!'))
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_empty_state_for_student_with_no_data(self):
        bare_student = self.env['op.student'].create({
            'first_name': 'Bare', 'last_name': 'Kid', 'gr_no': 'DASH-002', 'gender': 'm',
        })
        resp = self.url_open(
            f'/api/v1/parent/dashboard?student_id={bare_student.id}',
            headers=self._headers('dash_staff', 'StaffPass1!'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertEqual(data['attendance_last_30_days']['total'], 0)
        self.assertEqual(data['attendance_last_30_days']['attendance_percentage'], 0.0)
        self.assertEqual(data['upcoming_sessions'], [])
        self.assertIsNone(data['latest_exam_result'])
