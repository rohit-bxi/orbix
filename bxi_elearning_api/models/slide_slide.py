# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Smart Book chapter extras for the app's reader: Read / Listen / Watch
versions of one chapter, read time, level and learning objectives. The
chapter text, title and objectives are translatable (Odoo translations), so
one chapter carries its other-language versions."""
from odoo import fields, models

LEVELS = [('beginner', 'Beginner'), ('intermediate', 'Intermediate'), ('advanced', 'Advanced')]


class SlideSlide(models.Model):
    _inherit = 'slide.slide'

    bxi_audio = fields.Binary('Audio (Listen)', attachment=True,
                              help='Optional narration for "Listen". Without it the app reads the text aloud '
                                   'with the phone\'s own text-to-speech.')
    bxi_audio_filename = fields.Char('Audio File Name')
    bxi_video_url = fields.Char('Video URL (Watch)',
                                help='Optional video of this chapter for "Watch", e.g. a YouTube link.')
    bxi_read_minutes = fields.Integer('Read Time (minutes)',
                                      help='Shown as "15 min read". Left empty, the lesson duration is used.')
    bxi_level = fields.Selection(LEVELS, string='Level', default='beginner')
    bxi_learning_objectives = fields.Text('Learning Objectives', translate=True, help='One objective per line.')
