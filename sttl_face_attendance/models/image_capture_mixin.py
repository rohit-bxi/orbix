# -*- coding: utf-8 -*-

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ImageCaptureMixin(models.AbstractModel):
    """Shared webcam "CLICK IMAGE" capture logic for hr.employee, op.student
    and op.faculty. Any model that inherits this mixin can open the capture
    widget via open_image_capture() and receives the captured photo through
    register_face()."""
    _name = 'sttl.image.capture.mixin'
    _description = 'Webcam Image Capture Mixin'

    def open_image_capture(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'new_employee_image',
            'params': {
                'res_model': self._name,
                'res_id': self.id,
            }
        }

    def register_face(self, image_data):
        """Save a captured photo. Returns True on success, False otherwise -
        callers must check this instead of assuming the write always
        succeeds, since a malformed data URI or write error must not be
        reported to the caller as "saved"."""
        if not image_data:
            _logger.warning("No image data provided.")
            return False
        if image_data.startswith('data:') and ';base64,' in image_data:
            image_data = image_data.split(';base64,', 1)[1]
        try:
            self.image_1920 = image_data
        except Exception as e:
            _logger.error("Error registering face: %s", str(e))
            return False
        _logger.info("Image saved successfully.")
        return True
