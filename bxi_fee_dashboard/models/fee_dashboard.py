# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

MONTH_WINDOW = 6


class FeeDashboard(models.AbstractModel):
    """Server-side aggregation for the Fees Dashboard client action. Every
    number returned here is a live query against the models the other fee
    modules already maintain - nothing is cached or precomputed, so the
    dashboard always reflects the same data the underlying list views show.
    """
    _name = 'bxi.fee.dashboard'
    _description = 'Fees Dashboard'

    @api.model
    def get_dashboard_data(self):
        return {
            'kpis': self._get_kpis(),
            'charts': {
                'online_vs_offline': self._get_online_vs_offline(),
                'monthly_collection_trend': self._get_monthly_collection_trend(),
                'scholarship_distribution': self._get_scholarship_distribution(),
                'refund_trends': self._get_refund_trends(),
            },
            'recent_activity': self._get_recent_activity(),
        }

    def _month_bounds(self, months_ago=0):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1) - relativedelta(months=months_ago)
        month_end = month_start + relativedelta(months=1) - relativedelta(days=1)
        return month_start, month_end

    def _pct_change(self, current, previous):
        if not previous:
            return 100.0 if current else 0.0
        return round((current - previous) / abs(previous) * 100.0, 1)

    def _get_kpis(self):
        FeesDetail = self.env['op.student.fees.details'].sudo()
        Refund = self.env['bxi.student.refund.request'].sudo()
        Scholarship = self.env['bxi.student.scholarship'].sudo()
        ExemptionRequest = self.env['bxi.fee.exemption.request'].sudo()
        PaymentOrder = self.env['bxi.payment.order'].sudo()

        this_month_start, _unused = self._month_bounds(0)
        last_month_start, last_month_end = self._month_bounds(1)

        active_lines = FeesDetail.search([('state', '!=', 'cancel')])
        total_collected = sum(active_lines.mapped('amount_paid'))
        total_pending = sum(active_lines.filtered(lambda l: l.collection_status != 'paid').mapped('amount_pending'))
        total_payable = sum(active_lines.mapped('total_payable'))
        collection_efficiency = (total_collected / total_payable * 100.0) if total_payable else 0.0

        collected_this_month = sum(active_lines.filtered(
            lambda l: l.date and l.date >= this_month_start).mapped('amount_paid'))
        collected_last_month = sum(active_lines.filtered(
            lambda l: l.date and last_month_start <= l.date <= last_month_end).mapped('amount_paid'))

        total_refunds = sum(Refund.search([('status', '=', 'completed')]).mapped('refund_amount'))
        refunds_this_month = sum(Refund.search([
            ('status', '=', 'completed'), ('request_date', '>=', this_month_start)]).mapped('refund_amount'))
        refunds_last_month = sum(Refund.search([
            ('status', '=', 'completed'),
            ('request_date', '>=', last_month_start), ('request_date', '<=', last_month_end),
        ]).mapped('refund_amount'))

        scholarships_count = Scholarship.search_count([('approval_status', '=', 'approved'), ('active', '=', True)])

        manual_approvals = (
            Refund.search_count([('status', 'in', ('pending_review', 'under_review'))])
            + ExemptionRequest.search_count([('status', 'in', ('pending_review', 'under_review'))])
            + Scholarship.search_count([('approval_status', '=', 'pending')])
        )

        online_payments_count = PaymentOrder.search_count([('status', '=', 'paid')])
        online_payments_last_month = PaymentOrder.search_count([
            ('status', '=', 'paid'),
            ('create_date', '>=', last_month_start), ('create_date', '<=', last_month_end),
        ])
        online_payments_this_month = PaymentOrder.search_count([
            ('status', '=', 'paid'), ('create_date', '>=', this_month_start),
        ])

        receipts_generated = FeesDetail.search_count([('invoice_state', '=', 'posted')])

        # 'change' is only populated where a genuine period-over-period query
        # is possible from the fields these models actually store (no
        # separate ledger/snapshot history exists to derive one for
        # point-in-time balances like pending amount or collection
        # efficiency) - the client hides the trend badge when it is None
        # instead of showing a fabricated number.
        return {
            'total_fees_collected': {
                'value': total_collected,
                'change': self._pct_change(collected_this_month, collected_last_month),
            },
            'pending_payments': {
                'value': total_pending,
                'change': None,
            },
            'total_refunds': {
                'value': total_refunds,
                'change': self._pct_change(refunds_this_month, refunds_last_month),
            },
            'scholarships': {
                'value': scholarships_count,
                'change': None,
            },
            'manual_approvals': {
                'value': manual_approvals,
                'change': None,
            },
            'online_payments': {
                'value': online_payments_count,
                'change': self._pct_change(online_payments_this_month, online_payments_last_month),
            },
            'receipts_generated': {
                'value': receipts_generated,
                'change': None,
            },
            'collection_efficiency': {
                'value': round(collection_efficiency, 1),
                'change': None,
            },
        }

    def _get_online_vs_offline(self):
        FeesDetail = self.env['op.student.fees.details'].sudo()
        paid_lines = FeesDetail.search([('state', '!=', 'cancel'), ('amount_paid', '>', 0)])
        online_amount = sum(paid_lines.filtered(lambda l: l.payment_mode == 'online').mapped('amount_paid'))
        offline_amount = sum(paid_lines.filtered(lambda l: l.payment_mode != 'online').mapped('amount_paid'))
        return {'online': online_amount, 'offline': offline_amount}

    def _get_monthly_collection_trend(self):
        FeesDetail = self.env['op.student.fees.details'].sudo()
        labels, values = [], []
        for i in range(MONTH_WINDOW - 1, -1, -1):
            month_start, month_end = self._month_bounds(i)
            lines = FeesDetail.search([
                ('state', '!=', 'cancel'), ('date', '>=', month_start), ('date', '<=', month_end),
            ])
            labels.append(month_start.strftime('%b'))
            values.append(sum(lines.mapped('amount_paid')))
        return {'labels': labels, 'values': values}

    def _get_scholarship_distribution(self):
        Scholarship = self.env['bxi.student.scholarship'].sudo()
        groups = Scholarship._read_group(
            [('approval_status', '=', 'approved'), ('active', '=', True)],
            groupby=['scholarship_type'], aggregates=['__count'])
        type_labels = dict(Scholarship._fields['scholarship_type'].selection)
        return {
            'labels': [type_labels.get(scholarship_type, scholarship_type) for scholarship_type, _c in groups],
            'values': [count for _t, count in groups],
        }

    def _get_refund_trends(self):
        Refund = self.env['bxi.student.refund.request'].sudo()
        labels, values = [], []
        for i in range(MONTH_WINDOW - 1, -1, -1):
            month_start, month_end = self._month_bounds(i)
            refunds = Refund.search([
                ('status', '=', 'completed'), ('request_date', '>=', month_start), ('request_date', '<=', month_end),
            ])
            labels.append(month_start.strftime('%b'))
            values.append(sum(refunds.mapped('refund_amount')))
        return {'labels': labels, 'values': values}

    def _get_recent_activity(self):
        activities = []
        Refund = self.env['bxi.student.refund.request'].sudo()
        Scholarship = self.env['bxi.student.scholarship'].sudo()
        ExemptionRequest = self.env['bxi.fee.exemption.request'].sudo()
        PaymentOrder = self.env['bxi.payment.order'].sudo()

        status_kind = {
            'completed': 'success', 'approved': 'success', 'paid': 'success',
            'rejected': 'danger', 'failed': 'danger',
            'pending_review': 'warning', 'under_review': 'warning', 'pending': 'warning',
        }

        for refund in Refund.search([], order='write_date desc', limit=5):
            activities.append({
                'title': 'Refund %s' % (dict(Refund._fields['status'].selection).get(refund.status, refund.status)),
                'user': refund.approved_by.name or refund.assigned_to.name or '',
                'date': refund.write_date,
                'kind': status_kind.get(refund.status, 'info'),
            })
        for scholarship in Scholarship.search([], order='write_date desc', limit=5):
            activities.append({
                'title': 'Scholarship %s' % dict(
                    Scholarship._fields['approval_status'].selection).get(
                    scholarship.approval_status, scholarship.approval_status),
                'user': scholarship.approved_by.name or '',
                'date': scholarship.write_date,
                'kind': status_kind.get(scholarship.approval_status, 'info'),
            })
        for exemption in ExemptionRequest.search([], order='write_date desc', limit=5):
            activities.append({
                'title': 'Fee exemption %s' % dict(
                    ExemptionRequest._fields['status'].selection).get(exemption.status, exemption.status),
                'user': exemption.approved_by.name or exemption.rejected_by.name or '',
                'date': exemption.write_date,
                'kind': status_kind.get(exemption.status, 'info'),
            })
        for order in PaymentOrder.search([], order='write_date desc', limit=5):
            activities.append({
                'title': 'Online payment %s' % dict(
                    PaymentOrder._fields['status'].selection).get(order.status, order.status),
                'user': order.user_id.name or '',
                'date': order.write_date,
                'kind': status_kind.get(order.status, 'info'),
            })

        activities.sort(key=lambda a: a['date'], reverse=True)
        for activity in activities:
            activity['date'] = fields.Datetime.to_string(activity['date'])
        return activities[:8]
