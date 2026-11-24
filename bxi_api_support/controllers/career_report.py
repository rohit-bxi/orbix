# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""The Career Pathway report: daily screen time, apps used, productivity
score, primary interest, app category analysis and careers matched from
the student's app usage and their own results.

App usage is opt-in (bxi_student_learning.bxi.device.usage): a parent or
the school office records consent first; the student's app then sends
daily minutes per app category - never app names. Without consent the
report still recommends careers from the student's results."""
from collections import defaultdict
from datetime import timedelta

from odoo import fields, http
from odoo.http import request

from odoo.addons.bxi_api.controllers.auth import api_error, api_response, parse_int, require_auth
from odoo.addons.bxi_student_learning.models.device_usage import (
    INTEREST_LABELS, MAX_DAY_MINUTES, PRODUCTIVE_CATEGORIES, USAGE_CATEGORIES,
)

from .common import STUDENT_STAFF_GROUPS, date_str, get_app_student, json_body, school_context

CATEGORY_LABELS = dict(USAGE_CATEGORIES)
UPLOAD_BACK_DAYS = 7
MAX_REPORT_DAYS = 30
FULL_MATCH_SHARE = 0.4  # this share of screen time in a career's categories = 100 %
TOP_CAREERS = 4


def _is_office(env):
    return any(env.user.has_group(group) for group in STUDENT_STAFF_GROUPS)


def _family_or_office(env, student):
    """Usage data is private: the family and office staff only - not
    every teacher of the section."""
    return student in school_context(env)['students'] or _is_office(env)


def _is_parent_of(env, student):
    return bool(env['op.parent'].sudo().search_count([('user_id', '=', env.user.id), ('student_ids', 'in', student.id)]))


def _consent_dict(student):
    student = student.sudo()
    return {
        'consent': student.bxi_usage_consent,
        'given_by': {'id': student.bxi_usage_consent_by.id, 'name': student.bxi_usage_consent_by.name}
        if student.bxi_usage_consent_by else None,
        'date': date_str(student.bxi_usage_consent_date),
    }


def _usage_summary(rows, days):
    """Screen-time cards and the category analysis from usage rows."""
    total = sum(rows.mapped('minutes'))
    by_category, apps_by_day = defaultdict(int), defaultdict(int)
    for row in rows:
        by_category[row.category] += row.minutes
        apps_by_day[row.date] += row.app_count
    days_with_data = len(set(rows.mapped('date')))
    ranked = sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0]))
    top = next((cat for cat, _m in ranked if cat != 'other'), ranked[0][0] if ranked else None)
    return total, by_category, {
        'days': days,
        'days_with_data': days_with_data,
        'daily_screen_time_hours': round(total / days_with_data / 60, 1) if days_with_data else None,
        'apps_used_per_day': round(sum(apps_by_day.values()) / days_with_data) if days_with_data else None,
        'productivity_score': round(100.0 * sum(by_category[c] for c in PRODUCTIVE_CATEGORIES) / total)
        if total else None,
        'primary_interest': {'key': top, 'label': INTEREST_LABELS.get(top), 'category': CATEGORY_LABELS.get(top)}
        if top else None,
        'category_analysis': [{
            'category': cat, 'label': CATEGORY_LABELS[cat], 'minutes': minutes,
            'percentage': round(100.0 * minutes / total, 1) if total else 0.0,
        } for cat, minutes in ranked],
    }


def _careers(env, student, total, by_category):
    """Careers matched from both signals: app usage (share of screen time
    in the career's categories) and results (bxi.career rules); a career
    with both gets their average. A career's first usage category is its
    main one: without any time there, usage does not point to it."""
    by_results = {row['career'].id: row for row in env['bxi.career'].sudo()._bxi_recommend(student, limit=100)}
    result = []
    for career in env['bxi.career'].sudo().search([]):
        scores, reasons, sources, share = [], [], [], 0.0
        categories = career._bxi_usage_categories()
        if total and categories and by_category.get(categories[0]):
            minutes = sum(by_category.get(cat, 0) for cat in categories)
            if minutes:
                share = minutes / total
                scores.append(min(100, round(100.0 * share / FULL_MATCH_SHARE)))
                best = max(categories, key=lambda cat: by_category.get(cat, 0))
                reasons.append('High use of %s apps' % CATEGORY_LABELS.get(best, best).split(' &')[0].lower())
                sources.append('usage')
        rules = by_results.get(career.id)
        if rules:
            scores.append(rules['match'])
            reasons.append('Your results in %s' % ', '.join(rules['matched_subjects']))
            sources.append('results')
        if not scores:
            continue
        result.append({
            'id': career.id, 'name': career.name, 'description': career.description or None,
            'icon': career.icon or None, 'demand': career.demand,
            'match': round(sum(scores) / len(scores)), 'reason': '; '.join(reasons),
            'sources': sources, '_share': share,
        })
    # Equal matches (e.g. several capped at 100 %): the larger real share of
    # screen time first.
    result.sort(key=lambda row: (-row['match'], -row['_share'], row['name']))
    for row in result:
        del row['_share']
    return result[:TOP_CAREERS]


class BxiApiSupportCareerReportController(http.Controller):

    @http.route('/api/v1/student/career-report', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def career_report(self, student_id=None, days=None, **kwargs):
        """The Career Pathway screen. `days` (1-30, default 7) is the usage
        period. Without consent `usage` is null and careers come from
        results only."""
        env = request.env
        student, error = get_app_student(env, student_id, allow=_family_or_office)
        if error:
            return error
        days = days or 7
        days, error = parse_int(days, 'days')
        if error:
            return error
        if not 1 <= days <= MAX_REPORT_DAYS:
            return api_error('days must be between 1 and %s.' % MAX_REPORT_DAYS, status=400, code='invalid_days')
        usage, total, by_category = None, 0, {}
        if student.sudo().bxi_usage_consent:
            today = fields.Date.context_today(student)
            rows = env['bxi.device.usage'].sudo().search([
                ('student_id', '=', student.id), ('date', '>', today - timedelta(days=days)), ('date', '<=', today)])
            total, by_category, usage = _usage_summary(rows, days)
        return api_response({
            'student': {'id': student.id, 'name': student.name},
            'consent': _consent_dict(student),
            'usage': usage,
            'careers': _careers(env, student, total, by_category),
            'method': 'rules',
        })

    @http.route('/api/v1/student/usage/consent', type='http', auth='public', methods=['GET'], csrf=False)
    @require_auth
    def get_consent(self, student_id=None, **kwargs):
        student, error = get_app_student(request.env, student_id, allow=_family_or_office)
        if error:
            return error
        return api_response(_consent_dict(student))

    @http.route('/api/v1/student/usage/consent', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def set_consent(self, **kwargs):
        """{"student_id", "consent": true|false}. A parent or the office
        gives consent; the student may only withdraw it. Withdrawing
        deletes the usage already stored."""
        env = request.env
        payload = json_body()
        if not isinstance(payload, dict):
            return api_error('Send a JSON object.', status=400, code='invalid_payload')
        student, error = get_app_student(env, payload.get('student_id'), allow=_family_or_office)
        if error:
            return error
        consent = payload.get('consent')
        if not isinstance(consent, bool):
            return api_error('consent must be true or false.', status=400, code='invalid_value')
        if consent and not (_is_parent_of(env, student) or _is_office(env)):
            return api_error('Only a parent or the school office can give consent.', status=403,
                             code='parent_consent_required')
        student._bxi_set_usage_consent(consent, env.user)
        return api_response(_consent_dict(student))

    @http.route('/api/v1/student/usage', type='http', auth='public', methods=['POST'], csrf=False)
    @require_auth
    def upload_usage(self, **kwargs):
        """The student's app sends one day's usage: {"date": "2026-11-24"
        (default today, up to 7 days back), "categories": [{"category":
        "development", "minutes": 95, "app_count": 4}, ...]}. Sending a day
        again replaces it. Category keys: education, reading, productivity,
        development, design, social, entertainment, games, other."""
        env = request.env
        student = env['op.student'].sudo().search([('user_id', '=', env.user.id)], limit=1)
        if not student:
            return api_error('Only a student login can send app usage.', status=403, code='forbidden')
        if not student.bxi_usage_consent:
            return api_error('A parent has not agreed to share app usage yet.', status=403, code='consent_required')
        payload = json_body()
        if not isinstance(payload, dict):
            return api_error('Send a JSON object.', status=400, code='invalid_payload')
        today = fields.Date.context_today(student)
        try:
            day = fields.Date.to_date(payload.get('date')) if payload.get('date') else today
        except ValueError:
            return api_error('date must be YYYY-MM-DD.', status=400, code='invalid_date')
        if not today - timedelta(days=UPLOAD_BACK_DAYS) <= day <= today:
            return api_error('date must be within the last %s days.' % UPLOAD_BACK_DAYS, status=400,
                             code='invalid_date')
        categories = payload.get('categories')
        if not isinstance(categories, list) or not categories:
            return api_error('categories must be a non-empty list.', status=400, code='missing_categories')
        rows, seen = [], set()
        for item in categories:
            if not isinstance(item, dict) or item.get('category') not in CATEGORY_LABELS:
                return api_error('Unknown category: %s.' % (item.get('category') if isinstance(item, dict) else item),
                                 status=400, code='invalid_category')
            if item['category'] in seen:
                return api_error('Each category once per day.', status=400, code='duplicate_category')
            seen.add(item['category'])
            minutes, app_count = item.get('minutes'), item.get('app_count', 0)
            if not isinstance(minutes, int) or isinstance(minutes, bool) or not 0 <= minutes <= MAX_DAY_MINUTES \
                    or not isinstance(app_count, int) or isinstance(app_count, bool) or not 0 <= app_count <= 500:
                return api_error('minutes (0-1440) and app_count (0-500) must be whole numbers.', status=400,
                                 code='invalid_value')
            rows.append({'category': item['category'], 'minutes': minutes, 'app_count': app_count})
        if sum(row['minutes'] for row in rows) > MAX_DAY_MINUTES:
            return api_error('A day has at most 1440 minutes.', status=400, code='invalid_value')
        env['bxi.device.usage'].sudo()._bxi_record_day(student, day, rows)
        return api_response({'date': fields.Date.to_string(day), 'saved': len(rows)})
