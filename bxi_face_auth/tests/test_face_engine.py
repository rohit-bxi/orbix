# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import io
import math

import numpy as np
from PIL import Image

from odoo.tests import TransactionCase, tagged
from odoo.tests.common import BaseCase

from ..lib.engine import FaceError, embedding_from_bytes, embedding_to_bytes, normalize, yaw_from_landmarks
from ..lib.matching import check_liveness, decide


@tagged('post_install', '-at_install')
class TestFaceDecisions(BaseCase):

    def test_decide(self):
        self.assertEqual(decide({}, 0.5, 0.1), ('no_match', []))
        self.assertEqual(decide({1: 0.4, 2: 0.1}, 0.5, 0.1), ('no_match', []))
        self.assertEqual(decide({1: 0.8, 2: 0.3}, 0.5, 0.1), ('match', [1]))
        self.assertEqual(decide({1: 0.8, 2: 0.75}, 0.5, 0.1), ('ambiguous', []))
        # A rival below the threshold still counts for the gap: a lookalike
        # just under the bar means the top score isn't trustworthy either.
        self.assertEqual(decide({1: 0.55, 2: 0.49}, 0.5, 0.1), ('ambiguous', []))
        # Two accounts of one person are not rivals.
        self.assertEqual(decide({1: 0.8, 2: 0.78, 3: 0.2}, 0.5, 0.1, {1: {2}, 2: {1}}), ('select', [1, 2]))
        self.assertEqual(decide({1: 0.8, 2: 0.3}, 0.5, 0.1, {1: {2}}), ('match', [1]))

    def test_liveness(self):
        same = {'left': 0.8, 'right': 0.8}
        self.assertEqual(check_liveness({'center': 0.0, 'left': 0.3, 'right': -0.3}, same)[:2], (True, None))
        self.assertEqual(check_liveness({'center': 0.0, 'left': -0.3, 'right': 0.3}, same)[:2], (True, None))
        self.assertEqual(check_liveness({'center': 0.0, 'left': 0.05, 'right': -0.3}, same)[1], 'head_not_turned')
        self.assertEqual(check_liveness({'center': 0.0, 'left': 0.3, 'right': 0.4}, same)[1], 'head_not_turned')
        self.assertEqual(check_liveness({'center': 0.35, 'left': 0.6, 'right': 0.0}, same)[1], 'not_facing_camera')
        self.assertEqual(check_liveness({'center': 0.0, 'left': 0.3, 'right': -0.3},
                                        {'left': 0.8, 'right': 0.1})[1], 'face_changed')
        self.assertEqual(check_liveness({'center': 0.0, 'left': 0.3, 'right': -0.3}, same, [0.9, 0.2, 0.9], 0.8)[1],
                         'spoof_suspected')
        self.assertEqual(check_liveness({'center': 0.0, 'left': 0.3, 'right': -0.3}, same, [None, None], 0.8)[1], None)

    def test_yaw_is_roll_and_scale_invariant(self):
        right_eye, left_eye, nose = np.array([40.0, 50.0]), np.array([80.0, 50.0]), np.array([68.0, 75.0])
        yaw = yaw_from_landmarks(right_eye, left_eye, nose)
        self.assertAlmostEqual(yaw, 0.2)
        self.assertAlmostEqual(yaw_from_landmarks(right_eye, left_eye, np.array([60.0, 75.0])), 0.0)
        angle = math.radians(25)
        rotate = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
        moved = [rotate @ (point * 3.0) + 7 for point in (right_eye, left_eye, nose)]
        self.assertAlmostEqual(yaw_from_landmarks(*moved), yaw)

    def test_embedding_round_trip(self):
        vector = normalize(np.arange(128, dtype=np.float32) - 64)
        raw = embedding_to_bytes(vector)
        self.assertEqual(len(raw), 512)
        np.testing.assert_array_equal(embedding_from_bytes(raw), vector)


@tagged('post_install', '-at_install')
class TestFaceEngine(TransactionCase):
    """The real OpenCV engine and model files (no faces of real people
    ship with the tests; see README for checking accuracy)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            import cv2  # noqa: F401
        except ImportError:
            cls.skipTest(cls, 'OpenCV is not installed')
        cls.engine = cls.env['bxi.face.service']._get_engine()

    @staticmethod
    def _image(size=(640, 480), color=(200, 200, 200), mode='RGB', fmt='JPEG'):
        buf = io.BytesIO()
        Image.new(mode, size, color).save(buf, format=fmt)
        return buf.getvalue()

    def test_models_load(self):
        self.assertEqual(self.engine.model_version, 'yunet-2023mar+sface-2021dec')
        status = self.env['bxi.face.service']._engine_status()
        self.assertTrue(status['available'])

    def test_blank_photo_has_no_face(self):
        with self.assertRaises(FaceError) as caught:
            self.engine.analyze(self._image())
        self.assertEqual(caught.exception.code, 'no_face')

    def test_garbage_and_oversized_input(self):
        for data in (b'', b'definitely not an image'):
            with self.assertRaises(FaceError) as caught:
                self.engine.analyze(data)
            self.assertEqual(caught.exception.code, 'invalid_image')
        with self.assertRaises(FaceError) as caught:
            self.engine.analyze(self._image((6400, 6400), 0, 'L', 'PNG'))
        self.assertEqual(caught.exception.code, 'invalid_image')

    def test_recogniser_gives_unit_128_vector(self):
        crop = np.random.default_rng(1).integers(0, 255, (112, 112, 3), dtype=np.uint8)
        vector = normalize(self.engine._recognizer.feature(crop))
        self.assertEqual(vector.shape, (128,))
        self.assertAlmostEqual(float(np.linalg.norm(vector)), 1.0, places=5)
