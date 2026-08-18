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
        try:
            if image_data.startswith('data:image/png;base64,'):
                image_data = image_data.split('base64,')[1]

            if image_data:
                self.image_1920 = image_data
                _logger.info("Image saved successfully.")
            else:
                _logger.warning("No image data provided.")
        except Exception as e:
            _logger.error("Error registering face: %s", str(e))
