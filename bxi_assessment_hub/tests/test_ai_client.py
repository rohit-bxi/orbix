# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import json
from unittest.mock import MagicMock, patch

import requests

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAiClient(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('bxi_assessment_hub.anthropic_api_key', 'test-key')
        self.client = self.env['bxi.ai.client']

    def _mock_response(self, text, status_code=200):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = {'content': [{'text': text}]}
        response.text = text
        return response

    def test_get_config_defaults_model(self):
        config = self.client._get_config()
        self.assertEqual(config['api_key'], 'test-key')
        self.assertEqual(config['model'], 'claude-sonnet-5')

    def test_call_raises_when_not_configured(self):
        self.env['ir.config_parameter'].sudo().set_param('bxi_assessment_hub.anthropic_api_key', False)
        with self.assertRaises(UserError):
            self.client._call('prompt')

    def test_extract_json_plain(self):
        self.assertEqual(self.client._extract_json('{"a": 1}'), {'a': 1})

    def test_extract_json_markdown_fenced(self):
        self.assertEqual(self.client._extract_json('```json\n{"a": 1}\n```'), {'a': 1})

    def test_extract_json_invalid_raises(self):
        with self.assertRaises(UserError):
            self.client._extract_json('not json')

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_call_network_error_raises_user_error(self, mock_post):
        mock_post.side_effect = requests.RequestException('boom')
        with self.assertRaises(UserError):
            self.client._call('prompt')

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_generate_questions_success(self, mock_post):
        payload = [
            {'question_type': 'short_answer', 'question_text': 'Define X', 'marks': 2,
             'sample_answer_keywords': 'x definition'},
            {'question_type': 'mcq', 'question_text': 'Pick one', 'marks': 1, 'options': [
                {'option_text': 'A', 'is_correct': True},
                {'option_text': 'B', 'is_correct': False},
            ]},
        ]
        mock_post.return_value = self._mock_response(json.dumps(payload))
        rows = self.client.generate_questions('Class 10', 'Physics', 'Motion', 'medium', 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['question_type'], 'mcq')
        self.assertEqual(len(rows[1]['options']), 2)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_generate_questions_drops_invalid_mcq(self, mock_post):
        payload = [
            {'question_type': 'mcq', 'question_text': 'Bad mcq', 'marks': 1, 'options': [
                {'option_text': 'Only one', 'is_correct': True},
            ]},
        ]
        mock_post.return_value = self._mock_response(json.dumps(payload))
        with self.assertRaises(UserError):
            self.client.generate_questions('Class 10', 'Physics', 'Motion', 'medium', 1)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_generate_questions_http_error_raises(self, mock_post):
        mock_post.return_value = self._mock_response('', status_code=500)
        with self.assertRaises(UserError):
            self.client.generate_questions('Class 10', 'Physics', 'Motion', 'medium', 1)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_grade_answer_success(self, mock_post):
        mock_post.return_value = self._mock_response(json.dumps({'awarded_marks': 4, 'rationale': 'Good answer'}))
        result = self.client.grade_answer('What is X?', 'x definition', 'X is ...', 5, 'medium')
        self.assertEqual(result['awarded_marks'], 4)
        self.assertEqual(result['rationale'], 'Good answer')

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_grade_answer_clamps_to_max_marks(self, mock_post):
        mock_post.return_value = self._mock_response(json.dumps({'awarded_marks': 999, 'rationale': ''}))
        result = self.client.grade_answer('Q', 'ref', 'answer', 5, 'medium')
        self.assertEqual(result['awarded_marks'], 5)
