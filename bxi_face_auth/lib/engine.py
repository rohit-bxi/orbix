# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).

"""Server-side face analysis for face login.

Detection is OpenCV Zoo's YuNet (MIT) and recognition is SFace (Apache-2.0),
both run through OpenCV's own FaceDetectorYN / FaceRecognizerSF wrappers.
Pretrained InsightFace models are deliberately not used: their licence is
non-commercial research only.

Nothing here imports Odoo, so the engine can be exercised on its own.
OpenCV is imported lazily: a server that lacks it must still be able to
load the Odoo registry, and face routes then answer 503 instead.
"""

import io
import logging
import os
import threading
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps

_logger = logging.getLogger(__name__)

DETECTOR_FILE = 'face_detection_yunet_2023mar.onnx'
RECOGNIZER_FILE = 'face_recognition_sface_2021dec.onnx'
# Optional passive anti-spoof model (Silent-Face MiniFASNet convention:
# 80x80 BGR crop of the face box scaled by ANTISPOOF_SCALE, 3-class
# softmax, class 1 = real face). Used only if the file is present.
ANTISPOOF_FILE = 'face_antispoof_minifasnet.onnx'
ANTISPOOF_SCALE = 2.7
ANTISPOOF_INPUT = 80

MODEL_VERSION = 'yunet-2023mar+sface-2021dec'
EMBEDDING_SIZE = 128

MAX_INPUT_PIXELS = 40_000_000   # refuse decompression bombs before decoding
ANALYSIS_MAX_SIDE = 1280        # detection runs on at most this size
STORED_MAX_SIDE = 640           # size of the copy kept for staff review
MIN_DETECTION_SCORE = 0.80
MIN_FACE_PIXELS = 80            # face box width in the analysed image
# A second face whose box is at least this share of the main face's area
# means two people are in front of the camera.
SECOND_FACE_AREA_RATIO = 0.20
# Variance of the Laplacian on the aligned 112x112 crop; below this the
# face is too blurred to identify reliably.
MIN_SHARPNESS = 25.0


class FaceError(Exception):
    """A photo that can't be used. `code` is the API error code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class FaceAnalysis:
    embedding: np.ndarray       # float32 (128,), L2-normalised
    yaw: float                  # ~0 facing the camera; sign = turn direction
    det_score: float
    face_pixels: int
    sharpness: float
    live_score: float           # None when no anti-spoof model is installed
    jpeg: bytes                 # downscaled, EXIF-free copy for storage


def cosine(a, b):
    return float(np.dot(a, b))


def normalize(vector):
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def embedding_to_bytes(embedding):
    return np.asarray(embedding, dtype='<f4').tobytes()


def embedding_from_bytes(raw):
    return np.frombuffer(raw, dtype='<f4').copy()


def yaw_from_landmarks(right_eye, left_eye, nose):
    """Horizontal offset of the nose tip from the midpoint of the eyes,
    measured along the eye line and divided by the eye distance, so head
    tilt (roll), distance and image size cancel out. A face turned about
    20 degrees gives roughly 0.2. A flat photo turned in front of the
    camera keeps its original value, because a print has no depth for the
    nose to move against: that is what makes the head-turn challenge a
    liveness check.
    """
    right_eye = np.asarray(right_eye, dtype=np.float64)
    left_eye = np.asarray(left_eye, dtype=np.float64)
    nose = np.asarray(nose, dtype=np.float64)
    eye_line = left_eye - right_eye
    distance = float(np.linalg.norm(eye_line))
    if not distance:
        return 0.0
    offset = nose - (right_eye + left_eye) / 2.0
    return float(np.dot(offset, eye_line / distance) / distance)


def _decode(image_bytes):
    if not image_bytes:
        raise FaceError('invalid_image', 'The image is empty.')
    try:
        image = Image.open(io.BytesIO(image_bytes))
        width, height = image.size
        if width * height > MAX_INPUT_PIXELS:
            raise FaceError('invalid_image', 'The image is too large.')
        image = ImageOps.exif_transpose(image)
        return image.convert('RGB')
    except FaceError:
        raise
    except Exception:
        raise FaceError('invalid_image', 'The image could not be read. Send a JPEG or PNG photo.')


def _downscaled(image, max_side):
    if max(image.size) <= max_side:
        return image
    copy = image.copy()
    copy.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return copy


class FaceEngine:

    def __init__(self, model_dir, antispoof_path=None):
        import cv2  # noqa: lazy, see module docstring
        try:
            # OpenCV 5's new DNN engine warns on every model load that it
            # ignores the (unused) preferable target.
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except AttributeError:
            pass
        # See bxi_face_auth/__init__.py: one thread keeps the worker's
        # address space small; requests are already parallel across workers.
        cv2.setNumThreads(1)
        self._cv2 = cv2
        self._lock = threading.Lock()
        detector_path = os.path.join(model_dir, DETECTOR_FILE)
        recognizer_path = os.path.join(model_dir, RECOGNIZER_FILE)
        self._detector = cv2.FaceDetectorYN.create(detector_path, '', (320, 320), 0.6, 0.3, 50)
        self._recognizer = cv2.FaceRecognizerSF.create(recognizer_path, '')
        self._antispoof = None
        antispoof_path = antispoof_path or os.path.join(model_dir, ANTISPOOF_FILE)
        if os.path.isfile(antispoof_path):
            self._antispoof = cv2.dnn.readNetFromONNX(antispoof_path)
            _logger.info('Face login: passive anti-spoof model loaded from %s', antispoof_path)
        self.model_version = MODEL_VERSION
        self.has_antispoof = self._antispoof is not None

    def analyze(self, image_bytes):
        """Return a FaceAnalysis for the one face in `image_bytes`, or
        raise FaceError (invalid_image, no_face, multiple_faces,
        poor_quality)."""
        cv2 = self._cv2
        image = _decode(image_bytes)
        analysed = _downscaled(image, ANALYSIS_MAX_SIDE)
        bgr = np.ascontiguousarray(np.asarray(analysed)[:, :, ::-1])
        height, width = bgr.shape[:2]

        with self._lock:
            self._detector.setInputSize((width, height))
            _, faces = self._detector.detect(bgr)
            faces = [] if faces is None else [f for f in faces if f[14] >= MIN_DETECTION_SCORE]
            if not faces:
                raise FaceError('no_face', 'No face was found. Face the camera in good light.')
            faces.sort(key=lambda f: f[2] * f[3], reverse=True)
            face = faces[0]
            if len(faces) > 1 and faces[1][2] * faces[1][3] >= SECOND_FACE_AREA_RATIO * face[2] * face[3]:
                raise FaceError('multiple_faces', 'More than one face is in the picture. Only one person may be in view.')
            face_pixels = int(min(face[2], face[3]))
            if face_pixels < MIN_FACE_PIXELS:
                raise FaceError('poor_quality', 'The face is too small. Hold the camera closer.')

            aligned = self._recognizer.alignCrop(bgr, face)
            gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            if sharpness < MIN_SHARPNESS:
                raise FaceError('poor_quality', 'The photo is blurred. Hold the camera still.')
            embedding = normalize(self._recognizer.feature(aligned))
            live_score = self._live_score(bgr, face) if self._antispoof is not None else None

        yaw = yaw_from_landmarks(face[4:6], face[6:8], face[8:10])
        stored = io.BytesIO()
        _downscaled(image, STORED_MAX_SIDE).save(stored, format='JPEG', quality=85)
        return FaceAnalysis(
            embedding=embedding,
            yaw=yaw,
            det_score=float(face[14]),
            face_pixels=face_pixels,
            sharpness=sharpness,
            live_score=live_score,
            jpeg=stored.getvalue(),
        )

    def _live_score(self, bgr, face):
        cv2 = self._cv2
        height, width = bgr.shape[:2]
        box_w, box_h = float(face[2]), float(face[3])
        scale = min(ANTISPOOF_SCALE, (height - 1) / box_h, (width - 1) / box_w)
        center_x, center_y = face[0] + box_w / 2, face[1] + box_h / 2
        new_w, new_h = box_w * scale, box_h * scale
        left = int(max(0, center_x - new_w / 2))
        top = int(max(0, center_y - new_h / 2))
        right = int(min(width - 1, center_x + new_w / 2))
        bottom = int(min(height - 1, center_y + new_h / 2))
        crop = cv2.resize(bgr[top:bottom + 1, left:right + 1], (ANTISPOOF_INPUT, ANTISPOOF_INPUT))
        blob = crop.astype(np.float32).transpose(2, 0, 1)[np.newaxis]
        self._antispoof.setInput(blob)
        logits = self._antispoof.forward().reshape(-1)
        exp = np.exp(logits - logits.max())
        return float(exp[1] / exp.sum())


_engine = None
_engine_lock = threading.Lock()


def get_engine(model_dir, antispoof_path=None):
    """The process-wide engine, created on first use (each Odoo worker
    process loads the models once, ~40 MB)."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = FaceEngine(model_dir, antispoof_path)
    return _engine
