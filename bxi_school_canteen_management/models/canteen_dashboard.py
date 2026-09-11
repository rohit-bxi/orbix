# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from collections import Counter

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

MONTH_WINDOW = 6
ORDER_LIST_LIMIT = 10
BEST_SELLERS_LIMIT = 8
LOW_BALANCE_LIMIT = 5
RECENT_ACTIVITY_LIMIT = 8

ORDER_STATUS_KIND = {
    'draft': 'info',
    'confirmed': 'warning',
    'preparing': 'warning',
    'ready': 'warning',
    'served': 'success',
    'cancelled': 'danger',
}
TRANSACTION_KIND = {
    'topup': 'success',
    'order_payment': 'info',
    'refund': 'warning',
    'adjustment': 'info',
}


class CanteenDashboard(models.AbstractModel):
    """Server-side aggregation for the Canteen Dashboard client action.
    Every number here is a live query against bxi.canteen.order /
    bxi.canteen.wallet / bxi.canteen.wallet.transaction - nothing is
    cached, so the dashboard always matches the underlying list views.
    """
    _name = 'bxi.canteen.dashboard'
    _description = 'Canteen Dashboard'

    def _month_bounds(self, months_ago=0):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1) - relativedelta(months=months_ago)
        month_end = month_start + relativedelta(months=1) - relativedelta(days=1)
        return month_start, month_end

    @api.model
    def get_dashboard_data(self):
        Order = self.env['bxi.canteen.order'].sudo()
        orders = Order.search([])
        return {
            'kpis': self._get_kpis(orders),
            'order_list': self._get_order_list(Order),
            'charts': {
                'status_distribution': self._get_status_distribution(orders),
                'wallet_health': self._get_wallet_health(),
                'best_selling_items': self._get_best_selling_items(orders),
                'monthly_revenue_trend': self._get_monthly_revenue_trend(orders),
            },
            'low_balance_wallets': self._get_low_balance_wallets(),
            'stats': self._get_secondary_stats(),
            'recent_activity': self._get_recent_activity(),
        }

    def _get_kpis(self, orders):
        today = fields.Date.context_today(self)
        tomorrow = today + relativedelta(days=1)
        orders_today = orders.filtered(
            lambda o: o.order_datetime and today <= o.order_datetime.date() < tomorrow)
        orders_in_progress = orders.filtered(lambda o: o.state in ('confirmed', 'preparing', 'ready'))
        today_revenue = sum(orders_today.filtered(lambda o: o.state != 'cancelled').mapped('total_amount'))
        served_today = orders_today.filtered(lambda o: o.state == 'served')
        return {
            'orders_today': {'value': len(orders_today)},
            'orders_in_progress': {'value': len(orders_in_progress)},
            'today_revenue': {'value': today_revenue},
            'order_completion_rate': {
                'value': round(len(served_today) / len(orders_today) * 100.0, 1) if orders_today else 0.0,
            },
        }

    def _get_order_list(self, Order):
        records = Order.search([], order='write_date desc', limit=ORDER_LIST_LIMIT)
        return [{
            'id': o.id,
            'patron_name': o.patron_name or '',
            'total_amount': o.total_amount,
            'state': o.state,
            'order_datetime': fields.Datetime.to_string(o.order_datetime) if o.order_datetime else '',
        } for o in records]

    def _get_status_distribution(self, orders):
        status_labels = dict(orders._fields['state'].selection)
        counter = Counter(orders.mapped('state'))
        ordered = [key for key, _label in orders._fields['state'].selection if key in counter]
        return {
            'labels': [status_labels.get(k, k) for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_wallet_health(self):
        Wallet = self.env['bxi.canteen.wallet'].sudo()
        total = Wallet.search_count([])
        low = Wallet.search_count([('is_low_balance', '=', True)])
        return {'total': total, 'low_balance': low, 'healthy': max(total - low, 0)}

    def _get_best_selling_items(self, orders):
        Line = self.env['bxi.canteen.order.line'].sudo()
        lines = Line.search([('order_id', 'in', orders.filtered(lambda o: o.state != 'cancelled').ids)])
        counter = Counter()
        for line in lines:
            counter[line.product_id.name] += line.quantity
        ordered = sorted(counter, key=lambda k: counter[k], reverse=True)[:BEST_SELLERS_LIMIT]
        return {
            'labels': ordered,
            'values': [round(counter[k], 1) for k in ordered],
        }

    def _get_monthly_revenue_trend(self, orders):
        labels, values = [], []
        non_cancelled = orders.filtered(lambda o: o.state != 'cancelled')
        for i in range(MONTH_WINDOW - 1, -1, -1):
            month_start, month_end = self._month_bounds(i)
            month_records = non_cancelled.filtered(
                lambda o: o.order_datetime and month_start <= o.order_datetime.date() <= month_end)
            labels.append(month_start.strftime('%b'))
            values.append(sum(month_records.mapped('total_amount')))
        return {'labels': labels, 'values': values}

    def _get_low_balance_wallets(self):
        Wallet = self.env['bxi.canteen.wallet'].sudo()
        wallets = Wallet.search([('is_low_balance', '=', True)], order='balance asc', limit=LOW_BALANCE_LIMIT)
        return [{
            'patron_name': w.patron_name or '',
            'balance': w.balance,
            'threshold': w.low_balance_threshold,
        } for w in wallets]

    def _get_secondary_stats(self):
        Wallet = self.env['bxi.canteen.wallet'].sudo()
        Transaction = self.env['bxi.canteen.wallet.transaction'].sudo()
        month_start, _month_end = self._month_bounds(0)
        next_month_start = month_start + relativedelta(months=1)

        total_wallet_balance = sum(Wallet.search([]).mapped('balance'))
        low_balance_wallet_count = Wallet.search_count([('is_low_balance', '=', True)])
        monthly_topups = Transaction.search([
            ('transaction_type', '=', 'topup'),
            ('state', '=', 'posted'),
            ('date', '>=', month_start),
            ('date', '<', next_month_start),
        ])
        return {
            'total_wallet_balance': total_wallet_balance,
            'low_balance_wallet_count': low_balance_wallet_count,
            'monthly_topup_amount': sum(monthly_topups.mapped('amount')),
        }

    def _get_recent_activity(self):
        activities = []

        Order = self.env['bxi.canteen.order'].sudo()
        order_labels = dict(Order._fields['state'].selection)
        for order in Order.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Order %s (%s) - %s' % (
                    order.name, order.patron_name or '', order_labels.get(order.state, order.state)),
                'date': fields.Datetime.to_string(order.write_date),
                'kind': ORDER_STATUS_KIND.get(order.state, 'info'),
            })

        Transaction = self.env['bxi.canteen.wallet.transaction'].sudo()
        transaction_labels = dict(Transaction._fields['transaction_type'].selection)
        for txn in Transaction.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': '%s (%s) - %s' % (
                    transaction_labels.get(txn.transaction_type, txn.transaction_type),
                    txn.wallet_id.patron_name or '', txn.name),
                'date': fields.Datetime.to_string(txn.write_date),
                'kind': TRANSACTION_KIND.get(txn.transaction_type, 'info'),
            })

        activities.sort(key=lambda a: a['date'], reverse=True)
        return activities[:RECENT_ACTIVITY_LIMIT]
