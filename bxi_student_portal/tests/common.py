# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from datetime import datetime, time, timedelta

from odoo import fields
from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.tests.common import TransactionCase


class TestStudentPortalCommon(TransactionCase):
    """Shared fixtures for bxi_student_portal (and bxi_parent_portal) tests.

    Builds the minimal academic/accounting graph the /my/academics/* portal
    pages read from - one course/batch/subject/faculty, plus small helper
    methods to create the per-model rows (attendance, session, marksheet,
    assignment, library movement, fee) each page renders. No demo data is
    relied upon, so this works on a bare test database.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._counter = 0

        cls._setup_accounting()

        cls.course = cls.env['op.course'].create({
            'name': 'Portal Test Course', 'code': 'PTC01',
        })
        cls.batch = cls.env['op.batch'].create({
            'name': 'Portal Test Batch', 'code': 'PTB01', 'course_id': cls.course.id,
            'end_date': fields.Date.today() + timedelta(days=180),
        })
        cls.subject = cls.env['op.subject'].create({
            'name': 'Portal Test Subject', 'code': 'PTS01',
        })
        cls.faculty = cls.env['op.faculty'].create({
            'first_name': 'Portal', 'last_name': 'Teacher',
            'birth_date': '1985-01-01', 'gender': 'female',
        })

    @classmethod
    def _setup_accounting(cls):
        company = cls.env.company
        cls.income_account = cls.env['account.account'].search(
            [('account_type', '=', 'income'), ('company_ids', 'in', company.id)], limit=1)
        if not cls.income_account:
            cls.income_account = cls.env['account.account'].create({
                'name': 'Portal Test Income', 'code': 'PTINC01', 'account_type': 'income',
                'company_ids': [(6, 0, [company.id])],
            })
        cls.sale_journal = cls.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1)
        if not cls.sale_journal:
            cls.sale_journal = cls.env['account.journal'].create({
                'name': 'Portal Test Sales Journal', 'type': 'sale', 'code': 'PTSJ01',
            })

    @classmethod
    def _next(cls):
        cls._counter += 1
        return cls._counter

    # ------------------------------------------------------------------
    # Core fixtures
    # ------------------------------------------------------------------
    @classmethod
    def _make_portal_user(cls, login_prefix='portal_user'):
        n = cls._next()
        return mail_new_test_user(
            cls.env, login='%s_%s' % (login_prefix, n), groups='base.group_portal',
            password='PortalPass1!')

    @classmethod
    def _make_student(cls, with_login=True, roll_number=None, **kwargs):
        n = cls._next()
        vals = {
            'first_name': 'Student', 'last_name': 'No%s' % n,
            'gender': 'm', 'gr_no': 'PTGR-%s' % n,
        }
        vals.update(kwargs)
        student = cls.env['op.student'].create(vals)
        if with_login:
            # Mirrors op.student.create_student_user(): the login shares the
            # student's own delegated partner_id, not a fresh one - portal
            # ir.rules on account.move (child_of user.commercial_partner_id)
            # only resolve correctly when the login and the student are the
            # same partner, exactly as production student logins are set up.
            portal_group = cls.env.ref('base.group_portal')
            user = cls.env['res.users'].create({
                'name': student.name,
                'login': 'student_%s@example.com' % n,
                'email': 'student_%s@example.com' % n,
                'partner_id': student.partner_id.id,
                'group_ids': [(6, 0, [portal_group.id])],
                'password': 'PortalPass1!',
            })
            student.user_id = user.id
        cls.env['op.student.course'].create({
            'student_id': student.id,
            'course_id': cls.course.id,
            'batch_id': cls.batch.id,
            'roll_number': roll_number,
        })
        return student

    # ------------------------------------------------------------------
    # Attendance
    # ------------------------------------------------------------------
    @classmethod
    def _make_attendance(cls, student, presents, state='done'):
        """presents: list of booleans, one per attendance line (True=present)."""
        n = cls._next()
        register = cls.env['op.attendance.register'].create({
            'name': 'Portal Attendance Register %s' % n, 'code': 'PTAR%s' % n,
            'course_id': cls.course.id, 'batch_id': cls.batch.id,
        })
        today = fields.Date.today()
        lines = cls.env['op.attendance.line']
        for i, present in enumerate(presents):
            sheet = cls.env['op.attendance.sheet'].create({
                'register_id': register.id,
                'attendance_date': today - timedelta(days=i),
                'state': state,
            })
            lines |= cls.env['op.attendance.line'].create({
                'attendance_id': sheet.id,
                'student_id': student.id,
                'present': present,
                'absent': not present,
            })
        return lines

    # ------------------------------------------------------------------
    # Timetable
    # ------------------------------------------------------------------
    @classmethod
    def _make_session(cls, student, start_datetime, end_datetime=None, state='confirm'):
        return cls.env['op.session'].create({
            'start_datetime': start_datetime,
            'end_datetime': end_datetime or start_datetime + timedelta(hours=1),
            'course_id': cls.course.id, 'batch_id': cls.batch.id, 'subject_id': cls.subject.id,
            'faculty_id': cls.faculty.id,
            'student_ids': [(6, 0, [student.id])],
            'state': state,
        })

    # ------------------------------------------------------------------
    # Exams / marksheets
    # ------------------------------------------------------------------
    @classmethod
    def _make_marksheet(cls, student, marks, total_marks=100, register_state='validated'):
        n = cls._next()
        exam_type = cls.env['op.exam.type'].create({'name': 'Portal Exam Type %s' % n, 'code': 'PTET%s' % n})
        # Each fixture gets its own calendar day: op.exam._check_overlapping_times
        # forbids two exams on the same subject with overlapping
        # start_time/end_time windows, and _check_date_time requires the
        # exam's start/end to fall within its session's start_date/end_date.
        exam_day = fields.Date.today() + timedelta(days=n)
        exam_session = cls.env['op.exam.session'].create({
            'name': 'Portal Exam Session %s' % n, 'course_id': cls.course.id, 'batch_id': cls.batch.id,
            'exam_code': 'PTES%s' % n, 'start_date': exam_day, 'end_date': exam_day, 'exam_type': exam_type.id,
            'state': 'schedule',
        })
        start_time = datetime.combine(exam_day, time(9, 0))
        exam = cls.env['op.exam'].create({
            'session_id': exam_session.id, 'subject_id': cls.subject.id, 'exam_code': 'PTEX%s' % n,
            'start_time': start_time, 'end_time': start_time + timedelta(hours=1),
            'name': 'Portal Exam %s' % n, 'total_marks': total_marks, 'min_marks': 35, 'state': 'done',
        })
        result_template = cls.env['op.result.template'].create({
            'exam_session_id': exam_session.id, 'name': 'Portal Result Template %s' % n,
        })
        marksheet_register = cls.env['op.marksheet.register'].create({
            'exam_session_id': exam_session.id, 'name': 'Portal Marksheet Register %s' % n,
            'result_template_id': result_template.id, 'state': register_state,
        })
        marksheet_line = cls.env['op.marksheet.line'].create({
            'marksheet_reg_id': marksheet_register.id, 'student_id': student.id,
        })
        cls.env['op.result.line'].create({
            'marksheet_line_id': marksheet_line.id, 'exam_id': exam.id,
            'student_id': student.id, 'marks': marks,
        })
        return marksheet_line

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------
    @classmethod
    def _make_assignment(cls, allocation_students, state='publish',
                          issued_date=None, submission_date=None):
        n = cls._next()
        assignment_type = cls.env['grading.assignment.type'].create({
            'name': 'Portal Assignment Type %s' % n, 'code': 'PTAT%s' % n,
        })
        issued_date = issued_date or fields.Datetime.now()
        submission_date = submission_date or (fields.Datetime.now() + timedelta(days=7))
        return cls.env['op.assignment'].create({
            'name': 'Portal Assignment %s' % n,
            'course_id': cls.course.id,
            'batch_id': cls.batch.id,
            'assignment_type': assignment_type.id,
            'faculty_id': cls.faculty.id,
            'description': 'Portal test assignment.',
            'issued_date': issued_date,
            'submission_date': submission_date,
            'state': state,
            'allocation_ids': [(6, 0, allocation_students.ids)],
        })

    @classmethod
    def _make_assignment_submission(cls, assignment, student, state='submit'):
        return cls.env['op.assignment.sub.line'].create({
            'assignment_id': assignment.id,
            'student_id': student.id,
            'state': state,
        })

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------
    @classmethod
    def _library_setup(cls):
        if getattr(cls, '_library_media', None):
            return
        n = cls._next()
        author = cls.env['op.author'].create({'name': 'Portal Test Author %s' % n})
        publisher = cls.env['op.publisher'].create({'name': 'Portal Test Publisher %s' % n})
        genre = cls.env['op.media.genre'].create({'name': 'Portal Test Genre %s' % n})
        cls._library_media = cls.env['op.media'].create({
            'name': 'Portal Test Book %s' % n,
            'genre_id': genre.id,
            'author_ids': [(6, 0, [author.id])],
            'publisher_ids': [(6, 0, [publisher.id])],
        })
        card_type = cls.env['op.library.card.type'].create({
            'name': 'Portal Test Card Type %s' % n, 'allow_media': 5,
            'duration': 14, 'penalty_amt_per_day': 1.0,
        })
        cls._library_card_type = card_type

    @classmethod
    def _make_library_movement(cls, student, issued_date=None, return_date=None,
                                actual_return_date=None):
        cls._library_setup()
        n = cls._next()
        media_unit = cls.env['op.media.unit'].create({
            'name': 'Portal Test Unit %s' % n, 'media_id': cls._library_media.id,
        })
        library_card = cls.env['op.library.card'].create({
            'partner_id': student.partner_id.id,
            'library_card_type_id': cls._library_card_type.id,
            'type': 'student', 'student_id': student.id,
        })
        issued_date = issued_date or fields.Date.today()
        return_date = return_date or (issued_date + timedelta(days=14))
        return cls.env['op.media.movement'].create({
            'media_id': cls._library_media.id,
            'media_unit_id': media_unit.id,
            'type': 'student',
            'student_id': student.id,
            'library_card_id': library_card.id,
            'issued_date': issued_date,
            'return_date': return_date,
            'actual_return_date': actual_return_date,
        })

    # ------------------------------------------------------------------
    # Fees
    # ------------------------------------------------------------------
    @classmethod
    def _make_fee_invoice(cls, student, amount, invoice_state='posted'):
        invoice = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': student.partner_id.id,
            'journal_id': cls.sale_journal.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Portal Test Fee',
                'account_id': cls.income_account.id,
                'price_unit': amount,
                'quantity': 1.0,
                'tax_ids': [(5, 0, 0)],
            })],
        })
        if invoice_state == 'posted':
            invoice.action_post()
        elif invoice_state == 'cancel':
            invoice.button_cancel()
        return cls.env['op.student.fees.details'].create({
            'student_id': student.id,
            'amount': amount,
            'date': fields.Date.today(),
            'invoice_id': invoice.id,
        })
