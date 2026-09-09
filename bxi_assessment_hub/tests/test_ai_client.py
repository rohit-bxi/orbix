# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import json
from unittest.mock import MagicMock, patch

import requests

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.bxi_assessment_hub.models.ai_client import BxiAiTimeoutError


@tagged('post_install', '-at_install')
class TestAiClient(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('bxi_assessment_hub.anthropic_api_key', 'test-key')
        self.client = self.env['bxi.ai.client']

    def _mock_response(self, text, status_code=200, finish_reason=None, reasoning=None):
        response = MagicMock()
        response.status_code = status_code
        message = {'content': text}
        if reasoning is not None:
            message['reasoning'] = reasoning
        choice = {'message': message}
        if finish_reason is not None:
            choice['finish_reason'] = finish_reason
        body = json.dumps({'choices': [choice]})
        response.iter_content.return_value = [body.encode('utf-8')]
        return response

    def _timeout_response(self):
        response = MagicMock()
        response.iter_content.side_effect = requests.exceptions.Timeout('exceeded hard deadline')
        return response

    def test_get_config_defaults_model(self):
        config = self.client._get_config()
        self.assertEqual(config['api_key'], 'test-key')
        self.assertEqual(config['model'], 'anthropic/claude-sonnet-5')

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

    def test_extract_json_with_surrounding_commentary(self):
        text = 'Sure, here are the questions:\n[{"a": 1}]\nLet me know if you need more!'
        self.assertEqual(self.client._extract_json(text), [{'a': 1}])

    def test_extract_json_salvages_truncated_array(self):
        text = '[{"a": 1}, {"b": 2}, {"c": "unterminated str'
        self.assertEqual(self.client._extract_json(text), [{'a': 1}, {'b': 2}])

    def test_extract_json_no_salvage_when_no_complete_item(self):
        with self.assertRaises(UserError):
            self.client._extract_json('[{"a": "unterminated str')

    def test_extract_json_salvages_truncated_object(self):
        text = '{"awarded_marks": 4, "rationale": "Good answer because it covers the key'
        self.assertEqual(
            self.client._extract_json(text),
            {'awarded_marks': 4, 'rationale': 'Good answer because it covers the key'})

    def test_extract_json_no_salvage_when_object_has_no_fields(self):
        with self.assertRaises(UserError):
            self.client._extract_json('{"awarded_ma')

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_call_network_error_raises_user_error(self, mock_post):
        mock_post.side_effect = requests.RequestException('boom')
        with self.assertRaises(UserError):
            self.client._call('prompt')

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.time.monotonic')
    def test_read_with_hard_deadline_raises_timeout_when_exceeded(self, mock_monotonic):
        # Exercise the deadline-checking loop directly rather than through
        # the full _call()/_get_config() path: _get_config() reads config
        # parameters via Odoo's ormcache, which also calls time.monotonic()
        # internally, so patching it globally around the full call would
        # non-deterministically consume side-effect values meant for this
        # test and make the test itself flaky, not the code under test.
        response = MagicMock()
        response.iter_content.return_value = [b'chunk-one', b'chunk-two']
        mock_monotonic.side_effect = [0, 1000]
        with self.assertRaises(requests.exceptions.Timeout):
            self.client._read_with_hard_deadline(response, 90)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_call_wraps_hard_deadline_timeout_as_timeout_error(self, mock_post):
        # Specifically BxiAiTimeoutError (a BxiAiContentError), not a plain
        # UserError: callers need to distinguish "too slow, shrink/retry"
        # from "broken connection, give up" failures.
        response = MagicMock()
        response.iter_content.side_effect = requests.exceptions.Timeout('exceeded hard deadline')
        mock_post.return_value = response
        with self.assertRaises(BxiAiTimeoutError):
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
    def test_call_raises_on_null_content(self, mock_post):
        mock_post.return_value = self._mock_response(None)
        with self.assertRaises(UserError):
            self.client._call('prompt')

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_call_falls_back_to_reasoning_field(self, mock_post):
        mock_post.return_value = self._mock_response(None, reasoning='{"a": 1}')
        self.assertEqual(self.client._call('prompt'), {'a': 1})

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_call_raises_clear_error_when_truncated(self, mock_post):
        truncated = '[{"question_type": "mcq", "question_text": "Wh'
        mock_post.return_value = self._mock_response(truncated, finish_reason='length')
        with self.assertRaisesRegex(UserError, 'cut off'):
            self.client._call('prompt')

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_generate_questions_scales_max_tokens_with_count(self, mock_post):
        mock_post.return_value = self._mock_response(json.dumps([
            {'question_type': 'short_answer', 'question_text': 'Q', 'marks': 1, 'sample_answer_keywords': 'k'},
        ]))
        self.client.generate_questions('Class 10', 'Physics', 'Motion', 'medium', 3)
        sent_json = mock_post.call_args.kwargs['json']
        self.assertEqual(sent_json['max_tokens'], 300 * 3 + 800)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_generate_questions_chunks_large_requests(self, mock_post):
        # More than MAX_QUESTIONS_PER_REQUEST (5): should be split into a
        # batch of 5 then a batch of 3, each sized/token-budgeted on its own.
        item = {'question_type': 'short_answer', 'question_text': 'Q', 'marks': 1, 'sample_answer_keywords': 'k'}
        mock_post.side_effect = [
            self._mock_response(json.dumps([item])),
            self._mock_response(json.dumps([item])),
        ]
        rows = self.client.generate_questions('Class 10', 'Physics', 'Motion', 'medium', 8)
        self.assertEqual(len(rows), 2)
        self.assertEqual(mock_post.call_count, 2)
        first_max_tokens = mock_post.call_args_list[0].kwargs['json']['max_tokens']
        second_max_tokens = mock_post.call_args_list[1].kwargs['json']['max_tokens']
        self.assertEqual(first_max_tokens, 300 * 5 + 800)
        self.assertEqual(second_max_tokens, 300 * 3 + 800)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_generate_questions_retries_before_shrinking(self, mock_post):
        # AI output is stochastic: a single content error at a given batch
        # size should trigger a plain retry at the SAME size first, not an
        # immediate shrink.
        truncated = '[{"question_type": "mcq", "question_text": "Wh'
        item = {'question_type': 'short_answer', 'question_text': 'Q', 'marks': 1, 'sample_answer_keywords': 'k'}

        mock_post.side_effect = [
            self._mock_response(truncated, finish_reason='length'),
            self._mock_response(json.dumps([item, item])),
        ]
        rows = self.client.generate_questions('Class 10', 'Physics', 'Motion', 'medium', 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(mock_post.call_count, 2)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_generate_questions_shrinks_batch_after_repeated_content_errors(self, mock_post):
        # Once a batch size has exhausted its retries (MAX_ATTEMPTS_PER_BATCH_SIZE),
        # it should shrink to a smaller batch rather than giving up outright.
        truncated = '[{"question_type": "mcq", "question_text": "Wh'
        item = {'question_type': 'short_answer', 'question_text': 'Q', 'marks': 1, 'sample_answer_keywords': 'k'}

        mock_post.side_effect = [
            self._mock_response(truncated, finish_reason='length'),  # batch=2, attempt 1
            self._mock_response(truncated, finish_reason='length'),  # batch=2, attempt 2 -> shrink to 1
            self._mock_response(json.dumps([item])),                 # batch=1
            self._mock_response(json.dumps([item])),                 # batch=1
        ]
        rows = self.client.generate_questions('Class 10', 'Physics', 'Motion', 'medium', 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(mock_post.call_count, 4)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_generate_questions_shrinks_immediately_on_timeout(self, mock_post):
        # Unlike other content errors, a timeout should skip the same-size
        # retry and shrink right away (retrying unchanged would just burn
        # another full timeout for the same result).
        item = {'question_type': 'short_answer', 'question_text': 'Q', 'marks': 1, 'sample_answer_keywords': 'k'}
        mock_post.side_effect = [
            self._timeout_response(),                  # batch=2, times out -> shrink immediately
            self._mock_response(json.dumps([item])),   # batch=1
            self._mock_response(json.dumps([item])),   # batch=1
        ]
        rows = self.client.generate_questions('Class 10', 'Physics', 'Motion', 'medium', 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(mock_post.call_count, 3)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_grade_answer_success(self, mock_post):
        mock_post.return_value = self._mock_response(json.dumps({'awarded_marks': 4, 'rationale': 'Good answer'}))
        result = self.client.grade_answer('What is X?', 'x definition', 'X is ...', 5, 'medium')
        self.assertEqual(result['awarded_marks'], 4)
        self.assertEqual(result['rationale'], 'Good answer')

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_grade_answer_recovers_from_truncated_rationale(self, mock_post):
        # The grading response got cut off mid-rationale (e.g. a reasoning
        # model burning its budget before finishing); the awarded_marks
        # field completed first, so it should still be usable via salvage
        # instead of raising the generic "cut off" error.
        truncated = '{"awarded_marks": 4, "rationale": "Good answer because it explains the'
        mock_post.return_value = self._mock_response(truncated, finish_reason='length')
        result = self.client.grade_answer('What is X?', 'x definition', 'X is ...', 5, 'medium')
        self.assertEqual(result['awarded_marks'], 4)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_grade_answer_clamps_to_max_marks(self, mock_post):
        mock_post.return_value = self._mock_response(json.dumps({'awarded_marks': 999, 'rationale': ''}))
        result = self.client.grade_answer('Q', 'ref', 'answer', 5, 'medium')
        self.assertEqual(result['awarded_marks'], 5)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_grade_answer_retries_on_content_error_then_succeeds(self, mock_post):
        # The model sometimes leaks non-JSON commentary (e.g. safety-check
        # or reasoning text) instead of the requested JSON; a plain retry
        # should recover rather than failing the grading outright.
        mock_post.side_effect = [
            self._mock_response('User Safety: safe'),
            self._mock_response(json.dumps({'awarded_marks': 3, 'rationale': 'ok'})),
        ]
        result = self.client.grade_answer('Q', 'ref', 'answer', 5, 'medium')
        self.assertEqual(result['awarded_marks'], 3)
        self.assertEqual(mock_post.call_count, 2)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_grade_answer_raises_after_exhausting_retries(self, mock_post):
        mock_post.return_value = self._mock_response('User Safety: safe')
        with self.assertRaises(UserError):
            self.client.grade_answer('Q', 'ref', 'answer', 5, 'medium')
        self.assertEqual(mock_post.call_count, 2)

    @patch('odoo.addons.bxi_assessment_hub.models.ai_client.requests.post')
    def test_grade_answer_raises_immediately_on_timeout(self, mock_post):
        # No smaller batch to fall back to for grading, so a timeout should
        # not be retried at all (it would just time out again identically).
        mock_post.return_value = self._timeout_response()
        with self.assertRaises(BxiAiTimeoutError):
            self.client.grade_answer('Q', 'ref', 'answer', 5, 'medium')
        self.assertEqual(mock_post.call_count, 1)
