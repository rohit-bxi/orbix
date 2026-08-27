from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


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
            'date': '2026-09-15',
            'time': 10.5,
            'venue': 'Main Hall',
            'class_ids': [(6, 0, [self.course.id, self.course_2.id])],
        })
        self.assertEqual(len(meeting.class_ids), 2)
        self.assertTrue(meeting.active)

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
