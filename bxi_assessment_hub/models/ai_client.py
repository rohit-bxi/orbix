# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
import json
import logging
import re
import time

import requests

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

OPENROUTER_CHAT_URL = 'https://openrouter.ai/api/v1/chat/completions'
DEFAULT_MODEL = 'anthropic/claude-sonnet-5'
QUESTION_TYPES = ('mcq', 'short_answer', 'long_answer')
MAX_QUESTIONS_PER_REQUEST = 5
# Weaker/free models don't always ignore instructions because a request was
# too big - sometimes a retry with the identical prompt simply succeeds
# where the previous (stochastic) generation didn't. Try a couple of times
# at each batch size before shrinking or giving up.
MAX_ATTEMPTS_PER_BATCH_SIZE = 2
CONNECT_TIMEOUT_SECONDS = 10
CHUNK_READ_TIMEOUT_SECONDS = 30
# A hard wall-clock cap on the whole call, kept safely under Odoo's default
# 120s worker real-time limit: requests' own `timeout` only resets on each
# byte received, so a slowly-trickling (but never fully silent) response can
# otherwise run indefinitely and get the whole worker killed/reloaded by
# Odoo's watchdog instead of failing cleanly here.
CALL_HARD_DEADLINE_SECONDS = 90


class BxiAiContentError(UserError):
    """Raised for failures caused by the AI's output itself (truncated,
    empty, or unparseable) rather than transport/auth/billing failures.
    Callers that can retry with a smaller request (e.g. fewer questions
    per call) catch this specifically instead of UserError in general, so
    a systemic failure (bad key, no credit, network down) still aborts
    immediately instead of being retried pointlessly.
    """


class BxiAiTimeoutError(BxiAiContentError):
    """A BxiAiContentError specifically caused by exceeding our own hard
    wall-clock deadline. Retrying at the same batch size would most likely
    just waste another full timeout interval for the same result, so
    callers should shrink the batch immediately instead of retrying
    unchanged first (unlike other content errors, where a fresh sample at
    the same size often just succeeds).
    """


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
                timeout=(CONNECT_TIMEOUT_SECONDS, CHUNK_READ_TIMEOUT_SECONDS),
                stream=True,
            )
            body = self._read_with_hard_deadline(response, CALL_HARD_DEADLINE_SECONDS)
        except requests.exceptions.Timeout:
            # A slow-but-otherwise-working response (free/shared model under
            # load) is exactly the kind of failure a smaller request tends
            # to fix, so let callers retry/shrink instead of aborting for
            # good - unlike a real connection failure, where retrying with
            # a smaller request wouldn't help.
            _logger.warning('OpenRouter request timed out after %ds.', CALL_HARD_DEADLINE_SECONDS)
            raise BxiAiTimeoutError(_(
                'The AI service took too long to respond. Please try again.'))
        except requests.RequestException:
            _logger.exception('OpenRouter API request failed.')
            raise UserError(_('Could not reach the AI service. Please try again.'))

        try:
            payload = json.loads(body)
        except ValueError:
            _logger.error('OpenRouter returned a non-JSON response (status %s): %s', response.status_code, body)
            raise UserError(_('The AI service returned an unexpected response.'))

        if response.status_code >= 400:
            _logger.error('OpenRouter API error %s: %s', response.status_code, body)
            detail = self._extract_error_message(payload)
            if detail:
                raise UserError(
                    _('The AI service returned an error (%(code)s): %(detail)s') % {
                        'code': response.status_code, 'detail': detail,
                    })
            raise UserError(_('The AI service returned an error (%s). Please try again.') % response.status_code)

        try:
            choice = payload['choices'][0]
            message = choice['message']
        except (KeyError, IndexError, TypeError):
            _logger.exception('Unexpected OpenRouter API response shape: %s', body)
            raise UserError(_('The AI service returned an unexpected response.'))

        # Some (especially free-tier reasoning) models leave "content" empty
        # and put their actual output under "reasoning" instead.
        text = message.get('content') or message.get('reasoning')
        if not text:
            _logger.error('OpenRouter response had no usable content: %s', body)
            raise BxiAiContentError(_('The AI service returned an empty response. Please try again.'))

        try:
            return self._extract_json(text)
        except UserError:
            if choice.get('finish_reason') in ('length', 'max_tokens'):
                raise BxiAiContentError(_(
                    'The AI response was cut off before it finished (too long for the '
                    'configured limit). Please try again.'))
            raise

    @staticmethod
    def _read_with_hard_deadline(response, seconds):
        """Read response.iter_content() but abort once `seconds` of total
        wall-clock time have passed, regardless of how the server paces its
        chunks. `timeout=` on the request only bounds the gap between
        reads, not the call as a whole, so a response that keeps trickling
        (but never goes fully silent) can otherwise run unbounded.
        """
        deadline = time.monotonic() + seconds
        chunks = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            chunks.extend(chunk)
            if time.monotonic() > deadline:
                raise requests.exceptions.Timeout(
                    'Response exceeded the %ds hard time limit before finishing.' % seconds)
        return chunks.decode('utf-8', errors='replace')

    @staticmethod
    def _extract_error_message(payload):
        error = payload.get('error') if isinstance(payload, dict) else None
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

        # The model may have been cut off mid-response (hit its output-length
        # limit) before finishing. Rather than discard everything, recover
        # whichever complete array items (or object fields) it did finish.
        salvaged = BxiAiClient._salvage_json_array(text)
        if salvaged:
            _logger.warning(
                'AI response was truncated; salvaged %d complete item(s) from it instead of failing.',
                len(salvaged))
            return salvaged

        salvaged_object = BxiAiClient._salvage_json_object(text)
        if salvaged_object:
            _logger.warning('AI response was truncated; salvaged a partial object from it instead of failing.')
            return salvaged_object

        _logger.error('Could not parse JSON from AI response: %s', text)
        raise BxiAiContentError(_('The AI service returned a response that could not be understood.'))

    @staticmethod
    def _salvage_json_array(text):
        """Given text starting with a JSON array that may be truncated
        partway through an element, return the complete leading elements
        (parsed), or None if not even one complete element could be found.
        """
        start = text.find('[')
        if start == -1:
            return None
        text = text[start:]

        depth = 0
        in_string = False
        escape = False
        last_complete_end = None
        for i, char in enumerate(text):
            if in_string:
                if escape:
                    escape = False
                elif char == '\\':
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char in '[{':
                depth += 1
            elif char in ']}':
                depth -= 1
                if depth == 1 and char == '}':
                    last_complete_end = i

        if last_complete_end is None:
            return None
        try:
            return json.loads(text[:last_complete_end + 1] + ']')
        except ValueError:
            return None

    @staticmethod
    def _salvage_json_object(text):
        """Given text starting with a JSON object that was truncated
        partway through (e.g. cut off mid-string in a trailing field, as
        happens to grade_answer's "rationale" text), close the open string
        and brackets and try to parse what's left. Returns None if the text
        wasn't actually a truncated object (already balanced, so a normal
        json.loads would have succeeded) or still can't be repaired.
        """
        start = text.find('{')
        if start == -1:
            return None
        array_start = text.find('[')
        if array_start != -1 and array_start < start:
            # The top-level structure is actually an array (e.g. a
            # truncated question list) - this "{" just belongs to its
            # first, incomplete element, not a standalone object.
            return None
        text = text[start:]

        stack = []
        in_string = False
        escape = False
        for char in text:
            if in_string:
                if escape:
                    escape = False
                elif char == '\\':
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char in '{[':
                stack.append('}' if char == '{' else ']')
            elif char in '}]':
                if stack:
                    stack.pop()
                if not stack:
                    return None  # already balanced; not actually truncated

        if not stack:
            return None
        repaired = text + ('"' if in_string else '') + ''.join(reversed(stack))
        try:
            return json.loads(repaired)
        except ValueError:
            return None

    @staticmethod
    def _build_question_prompt(course_name, subject_name, topic, difficulty, count):
        return (
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

    @staticmethod
    def _parse_question_rows(data):
        if not isinstance(data, list):
            return []

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
        return rows

    def generate_questions(self, course_name, subject_name, topic, difficulty, count):
        rows = []
        remaining = count
        batch_size = min(remaining, MAX_QUESTIONS_PER_REQUEST)
        attempts_at_size = 0
        while remaining > 0:
            want = min(remaining, batch_size)
            prompt = self._build_question_prompt(course_name, subject_name, topic, difficulty, want)
            try:
                # Each question (esp. mcq with 4 options, or long_answer with
                # keyword lists) can run several hundred tokens; scale the
                # budget with the batch size so it doesn't get cut off.
                data = self._call(prompt, max_tokens=min(8000, 300 * want + 800))
            except BxiAiContentError as exc:
                # A timeout at this batch size will likely just time out
                # again identically, so shrink right away instead of
                # burning another full timeout on an unchanged retry.
                attempts_at_size += 1
                if not isinstance(exc, BxiAiTimeoutError) and attempts_at_size < MAX_ATTEMPTS_PER_BATCH_SIZE:
                    continue  # AI output is stochastic; a plain retry often just works
                attempts_at_size = 0
                if batch_size > 1:
                    # The model (esp. a free/weaker one) couldn't reliably
                    # produce this many questions in one response; ask for
                    # fewer at a time instead of giving up entirely.
                    batch_size = max(1, batch_size // 2)
                    continue
                _logger.warning(
                    'Giving up on the remaining %d question(s) after repeated AI failures.', remaining)
                break

            attempts_at_size = 0
            rows.extend(self._parse_question_rows(data))
            remaining -= want

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
        # 500 tokens is enough for the JSON itself, but some (especially
        # free-tier reasoning) models spend a chunk of the budget on hidden
        # reasoning before ever emitting the answer; give it more headroom.
        data = None
        for attempt in range(MAX_ATTEMPTS_PER_BATCH_SIZE):
            try:
                data = self._call(prompt, max_tokens=1200)
                break
            except BxiAiContentError as exc:
                # Grading has no smaller batch to fall back to, so a timeout
                # would just recur identically - don't waste time retrying it.
                if isinstance(exc, BxiAiTimeoutError) or attempt + 1 >= MAX_ATTEMPTS_PER_BATCH_SIZE:
                    raise
        if not isinstance(data, dict) or 'awarded_marks' not in data:
            raise UserError(_('The AI service response could not be understood as a grade.'))
        try:
            awarded = float(data['awarded_marks'])
        except (TypeError, ValueError):
            raise UserError(_('The AI service returned a non-numeric grade.'))
        awarded = max(0.0, min(float(max_marks), awarded))
        return {'awarded_marks': awarded, 'rationale': data.get('rationale') or ''}
