from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


@tagged('post_install', '-at_install')
class TestAcademicManagement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.board = cls.env['bxi.board'].create({'name': 'CBSE'})
        cls.course = cls.env['op.course'].create({
            'name': 'Class 10', 'code': 'C10',
        })
        cls.course_2 = cls.env['op.course'].create({
            'name': 'Class 9', 'code': 'C9',
        })
        cls.subject = cls.env['op.subject'].create({
            'name': 'Mathematics', 'code': 'MATH',
        })
        cls.teacher = cls.env['op.faculty'].create({
            'first_name': 'Amit', 'last_name': 'Kumar',
            'birth_date': '1985-01-01', 'gender': 'male',
        })
        cls.curriculum = cls.env['bxi.curriculum'].create({
            'name': 'Main Curriculum',
            'board_id': cls.board.id,
            'description': 'Primary curriculum for Class 10',
        })

    # --- bxi.board ---

    def test_board_unique_name(self):
        with self.assertRaises(Exception):
            self.env['bxi.board'].create({'name': 'CBSE'})

    # --- bxi.curriculum ---

    def test_curriculum_unique_name_board(self):
        with self.assertRaises(Exception):
            self.env['bxi.curriculum'].create({
                'name': 'Main Curriculum',
                'board_id': self.board.id,
                'description': 'Duplicate',
            })

    def test_curriculum_same_name_different_board_allowed(self):
        other_board = self.env['bxi.board'].create({'name': 'ICSE'})
        curriculum = self.env['bxi.curriculum'].create({
            'name': 'Main Curriculum',
            'board_id': other_board.id,
            'description': 'Different board, same name is fine',
        })
        self.assertTrue(curriculum.id)

    def test_curriculum_assign_classes_action(self):
        self.curriculum.class_ids = [(6, 0, [self.course.id, self.course_2.id])]
        action = self.curriculum.action_open_assign_classes()
        self.assertEqual(action['res_model'], 'bxi.curriculum')
        self.assertEqual(action['res_id'], self.curriculum.id)
        self.assertEqual(len(self.curriculum.class_ids), 2)

    # --- bxi.subject.mapping ---

    def test_subject_mapping_display_name_computed(self):
        mapping = self.env['bxi.subject.mapping'].create({
            'subject_id': self.subject.id,
            'class_id': self.course.id,
            'teacher_id': self.teacher.id,
            'curriculum_id': self.curriculum.id,
        })
        expected = '%s - %s - %s' % (self.subject.name, self.course.name, self.teacher.name)
        self.assertEqual(mapping.display_name, expected)

    def test_subject_mapping_unique_subject_class_curriculum(self):
        self.env['bxi.subject.mapping'].create({
            'subject_id': self.subject.id,
            'class_id': self.course.id,
            'teacher_id': self.teacher.id,
            'curriculum_id': self.curriculum.id,
        })
        with self.assertRaises(Exception):
            self.env['bxi.subject.mapping'].create({
                'subject_id': self.subject.id,
                'class_id': self.course.id,
                'teacher_id': self.teacher.id,
                'curriculum_id': self.curriculum.id,
            })

    def test_subject_mapping_same_subject_different_class_allowed(self):
        mapping_1 = self.env['bxi.subject.mapping'].create({
            'subject_id': self.subject.id,
            'class_id': self.course.id,
            'teacher_id': self.teacher.id,
            'curriculum_id': self.curriculum.id,
        })
        mapping_2 = self.env['bxi.subject.mapping'].create({
            'subject_id': self.subject.id,
            'class_id': self.course_2.id,
            'teacher_id': self.teacher.id,
            'curriculum_id': self.curriculum.id,
        })
        self.assertNotEqual(mapping_1.id, mapping_2.id)

    def test_subject_mapping_display_name_updates_on_teacher_change(self):
        mapping = self.env['bxi.subject.mapping'].create({
            'subject_id': self.subject.id,
            'class_id': self.course.id,
            'teacher_id': self.teacher.id,
            'curriculum_id': self.curriculum.id,
        })
        other_teacher = self.env['op.faculty'].create({
            'first_name': 'Sunita', 'last_name': 'Rao',
            'birth_date': '1980-05-05', 'gender': 'female',
        })
        mapping.teacher_id = other_teacher.id
        expected = '%s - %s - %s' % (self.subject.name, self.course.name, other_teacher.name)
        self.assertEqual(mapping.display_name, expected)

    # --- bxi.ptm.meeting ---

    def test_ptm_meeting_creation(self):
        meeting = self.env['bxi.ptm.meeting'].create({
            'name': 'Term 1 PTM',
            'start_datetime': '2026-09-15 10:30:00',
            'end_datetime': '2026-09-15 11:30:00',
            'venue': 'Main Hall',
            'class_ids': [(6, 0, [self.course.id, self.course_2.id])],
        })
        self.assertEqual(len(meeting.class_ids), 2)
        self.assertTrue(meeting.active)

    def test_ptm_meeting_end_before_start_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['bxi.ptm.meeting'].create({
                'name': 'Bad PTM',
                'start_datetime': '2026-09-15 11:30:00',
                'end_datetime': '2026-09-15 10:30:00',
                'venue': 'Main Hall',
                'class_ids': [(6, 0, [self.course.id])],
            })

    def test_ptm_meeting_computes_parents_and_teachers(self):
        student = self.env['op.student'].create({
            'first_name': 'Ptm', 'last_name': 'Kid', 'gr_no': 'PTM-001', 'gender': 'm',
        })
        batch = self.env['op.batch'].create({
            'name': 'PTM Batch', 'code': 'PTM-B1', 'course_id': self.course.id,
            'start_date': '2026-01-01', 'end_date': '2026-12-31',
        })
        self.env['op.student.course'].create({
            'student_id': student.id, 'course_id': self.course.id, 'batch_id': batch.id, 'state': 'running',
        })
        relationship = self.env['op.parent.relationship'].search([], limit=1) \
            or self.env['op.parent.relationship'].create({'name': 'Guardian'})
        parent = self.env['op.parent'].create({
            'name': self.env['res.partner'].create({'name': 'Ptm Parent', 'is_parent': True}).id,
            'relationship_id': relationship.id,
            'student_ids': [(6, 0, [student.id])],
        })
        self.env['bxi.subject.mapping'].create({
            'subject_id': self.subject.id, 'class_id': self.course.id,
            'teacher_id': self.teacher.id, 'curriculum_id': self.curriculum.id,
        })
        meeting = self.env['bxi.ptm.meeting'].create({
            'name': 'Term 1 PTM',
            'start_datetime': '2026-09-15 10:30:00',
            'end_datetime': '2026-09-15 11:30:00',
            'venue': 'Main Hall',
            'class_ids': [(6, 0, [self.course.id])],
        })
        self.assertIn(parent, meeting.parent_ids)
        self.assertIn(self.teacher, meeting.teacher_ids)

    def test_ptm_meeting_portal_parent_sees_only_own_childs_class(self):
        other_course = self.env['op.course'].create({'name': 'Other Class', 'code': 'PTM-OC'})
        student = self.env['op.student'].create({
            'first_name': 'Ptm', 'last_name': 'Kid2', 'gr_no': 'PTM-002', 'gender': 'f',
        })
        batch = self.env['op.batch'].create({
            'name': 'PTM Batch 2', 'code': 'PTM-B2', 'course_id': self.course.id,
            'start_date': '2026-01-01', 'end_date': '2026-12-31',
        })
        self.env['op.student.course'].create({
            'student_id': student.id, 'course_id': self.course.id, 'batch_id': batch.id, 'state': 'running',
        })
        parent_user = mail_new_test_user(
            self.env, login='ptm_parent', groups='base.group_portal', password='PtmParent1!')
        relationship = self.env['op.parent.relationship'].search([], limit=1) \
            or self.env['op.parent.relationship'].create({'name': 'Guardian'})
        self.env['op.parent'].create({
            'name': self.env['res.partner'].create({'name': 'Ptm Parent 2', 'is_parent': True}).id,
            'relationship_id': relationship.id,
            'user_id': parent_user.id,
            'student_ids': [(6, 0, [student.id])],
        })
        meeting_own = self.env['bxi.ptm.meeting'].create({
            'name': 'Own Class PTM',
            'start_datetime': '2026-09-15 10:30:00', 'end_datetime': '2026-09-15 11:30:00',
            'venue': 'Main Hall', 'class_ids': [(6, 0, [self.course.id])],
        })
        meeting_other = self.env['bxi.ptm.meeting'].create({
            'name': 'Other Class PTM',
            'start_datetime': '2026-09-16 10:30:00', 'end_datetime': '2026-09-16 11:30:00',
            'venue': 'Main Hall', 'class_ids': [(6, 0, [other_course.id])],
        })
        visible = self.env['bxi.ptm.meeting'].with_user(parent_user).search([])
        self.assertIn(meeting_own.id, visible.ids)
        self.assertNotIn(meeting_other.id, visible.ids)

    def test_ptm_meeting_teacher_sees_only_mapped_classes(self):
        other_course = self.env['op.course'].create({'name': 'Unmapped Class', 'code': 'PTM-UC'})
        teacher_user = mail_new_test_user(
            self.env, login='ptm_teacher', groups='openeducat_core.group_op_faculty', password='PtmTeacher1!')
        teacher = self.env['op.faculty'].create({
            'first_name': 'Ptm', 'last_name': 'Teacher', 'birth_date': '1985-01-01', 'gender': 'male',
            'user_id': teacher_user.id,
        })
        self.env['bxi.subject.mapping'].create({
            'subject_id': self.subject.id, 'class_id': self.course.id,
            'teacher_id': teacher.id, 'curriculum_id': self.curriculum.id,
        })
        meeting_mapped = self.env['bxi.ptm.meeting'].create({
            'name': 'Mapped Class PTM',
            'start_datetime': '2026-09-15 10:30:00', 'end_datetime': '2026-09-15 11:30:00',
            'venue': 'Main Hall', 'class_ids': [(6, 0, [self.course.id])],
        })
        meeting_unmapped = self.env['bxi.ptm.meeting'].create({
            'name': 'Unmapped Class PTM',
            'start_datetime': '2026-09-16 10:30:00', 'end_datetime': '2026-09-16 11:30:00',
            'venue': 'Main Hall', 'class_ids': [(6, 0, [other_course.id])],
        })
        visible = self.env['bxi.ptm.meeting'].with_user(teacher_user).search([])
        self.assertIn(meeting_mapped.id, visible.ids)
        self.assertNotIn(meeting_unmapped.id, visible.ids)

    # --- op.media inherited curriculum_id ---

    def test_media_curriculum_link(self):
        author = self.env['op.author'].create({'name': 'Test Author'})
        publisher = self.env['op.publisher'].create({'name': 'Test Publisher'})
        genre = self.env['op.media.genre'].create({'name': 'Textbook'})
        media = self.env['op.media'].create({
            'name': 'Algebra Textbook',
            'author_ids': [(6, 0, [author.id])],
            'publisher_ids': [(6, 0, [publisher.id])],
            'genre_id': genre.id,
            'curriculum_id': self.curriculum.id,
        })
        self.assertEqual(media.curriculum_id, self.curriculum)
