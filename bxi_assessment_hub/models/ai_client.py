# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import json
import logging
import re

import requests

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

OPENROUTER_CHAT_URL = 'https://openrouter.ai/api/v1/chat/completions'
DEFAULT_MODEL = 'anthropic/claude-sonnet-5'
QUESTION_TYPES = ('mcq', 'short_answer', 'long_answer')


class BxiAiClient(models.AbstractModel):
    """Thin wrapper around OpenRouter's chat-completions API: generates exam
    questions for the AI Assignment flow and grades a student's free-text
    answer for the Auto-Grading flow.

    Unlike bxi.msg91.client (which silently degrades on failure since a
    failed SMS shouldn't block anything else), both operations here are
    synchronous actions a user is actively waiting on, so failures are
    raised as UserError with a clear message rather than swallowed.
    """
    _name = 'bxi.ai.client'
    _description = 'AI Assessment Client (OpenRouter)'

    def _get_config(self):
        ICP = self.env['ir.config_parameter'].sudo()
        api_key = (ICP.get_param('bxi_assessment_hub.anthropic_api_key') or '').strip()
        return {
            'api_key': api_key,
            'model': ICP.get_param('bxi_assessment_hub.anthropic_model') or DEFAULT_MODEL,
        }

    def _call(self, prompt, max_tokens=2000):
        config = self._get_config()
        if not config['api_key']:
            raise UserError(_('AI is not configured. Add an API key under Settings > Assessments & Exams.'))
        try:
            response = requests.post(
                OPENROUTER_CHAT_URL,
                headers={
                    'Authorization': 'Bearer %s' % config['api_key'],
                    'content-type': 'application/json',
                },
                json={
                    'model': config['model'],
                    'max_tokens': max_tokens,
                    'messages': [{'role': 'user', 'content': prompt}],
                },
                timeout=60,
            )
        except requests.RequestException:
            _logger.exception('OpenRouter API request failed.')
            raise UserError(_('Could not reach the AI service. Please try again.'))

        if response.status_code >= 400:
            _logger.error('OpenRouter API error %s: %s', response.status_code, response.text)
            detail = self._extract_error_message(response)
            if detail:
                raise UserError(
                    _('The AI service returned an error (%(code)s): %(detail)s') % {
                        'code': response.status_code, 'detail': detail,
                    })
            raise UserError(_('The AI service returned an error (%s). Please try again.') % response.status_code)

        try:
            choice = response.json()['choices'][0]
            message = choice['message']
        except (KeyError, IndexError, ValueError):
            _logger.exception('Unexpected OpenRouter API response shape: %s', response.text)
            raise UserError(_('The AI service returned an unexpected response.'))

        # Some (especially free-tier reasoning) models leave "content" empty
        # and put their actual output under "reasoning" instead.
        text = message.get('content') or message.get('reasoning')
        if not text:
            _logger.error('OpenRouter response had no usable content: %s', response.text)
            raise UserError(_('The AI service returned an empty response. Please try again.'))

        try:
            return self._extract_json(text)
        except UserError:
            if choice.get('finish_reason') in ('length', 'max_tokens'):
                raise UserError(_(
                    'The AI response was cut off before it finished (too long for the '
                    'configured limit). Try requesting fewer questions at a time.'))
            raise

    @staticmethod
    def _extract_error_message(response):
        try:
            error = response.json().get('error')
        except ValueError:
            return False
        if isinstance(error, dict):
            return error.get('message') or False
        if isinstance(error, str):
            return error
        return False

    @staticmethod
    def _extract_json(text):
        text = text.strip()

        candidates = [text]
        fenced = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
        if fenced:
            candidates.append(fenced.group(1).strip())

        # Some (especially free/weaker) models wrap the JSON in commentary
        # instead of returning it alone despite being asked to; fall back to
        # the outermost {...} or [...] span found anywhere in the text.
        for open_char, close_char in (('[', ']'), ('{', '}')):
            start = text.find(open_char)
            end = text.rfind(close_char)
            if start != -1 and end != -1 and end > start:
                candidates.append(text[start:end + 1])

        for candidate in candidates:
            try:
                return json.loads(candidate)
            except ValueError:
                continue

        _logger.error('Could not parse JSON from AI response: %s', text)
        raise UserError(_('The AI service returned a response that could not be understood.'))

    def generate_questions(self, course_name, subject_name, topic, difficulty, count):
        prompt = (
            'You are helping a school teacher create an exam. Generate exactly %(count)d exam '
            'questions for class "%(course)s", subject "%(subject)s", on the topic "%(topic)s", '
            'at %(difficulty)s difficulty.\n\n'
            'Respond with ONLY a JSON array (no markdown, no commentary), where each item has:\n'
            '- "question_type": one of "mcq", "short_answer", "long_answer"\n'
            '- "question_text": string\n'
            '- "marks": number\n'
            '- "sample_answer_keywords": string (required for short_answer/long_answer, used later '
            'to auto-grade student responses; omit or leave empty for mcq)\n'
            '- "options": for mcq only, an array of exactly 4 objects {"option_text": string, '
            '"is_correct": boolean}, with exactly one is_correct true\n'
            'Mix question types unless the topic clearly calls for only one kind.'
        ) % {
            'count': count, 'course': course_name, 'subject': subject_name,
            'topic': topic, 'difficulty': difficulty,
        }
        # Each question (esp. mcq with 4 options, or long_answer with keyword
        # lists) can run several hundred tokens; scale the budget with count
        # so larger requests don't get cut off mid-response.
        data = self._call(prompt, max_tokens=min(8000, 300 * count + 800))
        if not isinstance(data, list) or not data:
            raise UserError(_('The AI service did not return any questions. Please try again.'))

        rows = []
        for item in data:
            if not isinstance(item, dict):
                continue
            question_type = item.get('question_type')
            if question_type not in QUESTION_TYPES:
                continue
            question_text = (item.get('question_text') or '').strip()
            if not question_text:
                continue
            entry = {
                'question_type': question_type,
                'question_text': question_text,
                'marks': float(item.get('marks') or 1),
                'sample_answer_keywords': item.get('sample_answer_keywords') or False,
            }
            if question_type == 'mcq':
                options = []
                for option in item.get('options') or []:
                    if not isinstance(option, dict):
                        continue
                    text = (option.get('option_text') or '').strip()
                    if text:
                        options.append({'option_text': text, 'is_correct': bool(option.get('is_correct'))})
                if len(options) < 2 or len([o for o in options if o['is_correct']]) != 1:
                    continue
                entry['options'] = options
            rows.append(entry)

        if not rows:
            raise UserError(_(
                'The AI service response could not be turned into valid questions. Please try again.'))
        return rows

    def grade_answer(self, question_text, sample_answer_keywords, student_answer, max_marks, strictness):
        prompt = (
            "You are grading a student's exam answer. Maximum marks: %(max_marks)s. "
            'Grading strictness: %(strictness)s (lenient = give credit for partial/approximate '
            'understanding, strict = require precise, complete answers).\n\n'
            'Question: %(question)s\n'
            'Reference answer / key concepts: %(reference)s\n'
            'Student answer: %(answer)s\n\n'
            'Respond with ONLY a JSON object (no markdown, no commentary): '
            '{"awarded_marks": number between 0 and %(max_marks)s, "rationale": short string '
            'explaining the score}.'
        ) % {
            'max_marks': max_marks, 'strictness': strictness, 'question': question_text,
            'reference': sample_answer_keywords or '(none provided)', 'answer': student_answer,
        }
        data = self._call(prompt, max_tokens=500)
        if not isinstance(data, dict) or 'awarded_marks' not in data:
            raise UserError(_('The AI service response could not be understood as a grade.'))
        try:
            awarded = float(data['awarded_marks'])
        except (TypeError, ValueError):
            raise UserError(_('The AI service returned a non-numeric grade.'))
        awarded = max(0.0, min(float(max_marks), awarded))
        return {'awarded_marks': awarded, 'rationale': data.get('rationale') or ''}
