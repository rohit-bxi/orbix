# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
from collections import Counter

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

MONTH_WINDOW = 6
REGISTRATION_LIST_LIMIT = 10
TOP_ROUTES_LIMIT = 5
RECENT_ACTIVITY_LIMIT = 8

REGISTRATION_STATUS_KIND = {
    'draft': 'info',
    'confirmed': 'warning',
    'active': 'success',
    'cancelled': 'danger',
}
ROUTE_STATUS_KIND = {
    'draft': 'info',
    'active': 'success',
    'archived': 'danger',
}
DRIVER_STATUS_KIND = {
    'active': 'success',
    'on_leave': 'warning',
    'suspended': 'danger',
}


class TransportDashboard(models.AbstractModel):
    """Server-side aggregation for the Transport / Bus Management Dashboard
    client action. Every number here is a live query against fleet.vehicle /
    bxi.transport.route / bxi.transport.registration / bxi.transport.driver -
    nothing is cached, so the dashboard always matches the underlying list
    views.
    """
    _name = 'bxi.transport.dashboard'
    _description = 'Transport Dashboard'

    def _month_bounds(self, months_ago=0):
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1) - relativedelta(months=months_ago)
        month_end = month_start + relativedelta(months=1) - relativedelta(days=1)
        return month_start, month_end

    @api.model
    def get_dashboard_data(self):
        Route = self.env['bxi.transport.route'].sudo()
        Registration = self.env['bxi.transport.registration'].sudo()
        active_routes = Route.search([('state', '=', 'active')])
        registrations = Registration.search([])
        return {
            'kpis': self._get_kpis(active_routes, registrations),
            'registration_list': self._get_registration_list(Registration),
            'charts': {
                'status_distribution': self._get_status_distribution(registrations),
                'route_wise_registrations': self._get_route_wise_registrations(active_routes),
                'monthly_registration_trend': self._get_monthly_registration_trend(registrations),
                'seat_allocation': self._get_seat_allocation(active_routes),
            },
            'top_routes': self._get_top_routes(active_routes),
            'stats': self._get_secondary_stats(registrations),
            'recent_activity': self._get_recent_activity(),
        }

    def _get_kpis(self, active_routes, registrations):
        Vehicle = self.env['fleet.vehicle'].sudo()
        total_buses = Vehicle.search_count([('is_school_bus', '=', True)])
        total_capacity = sum(active_routes.mapped('capacity'))
        seats_filled = total_capacity - sum(active_routes.mapped('seats_available'))
        active_registrations = len(registrations.filtered(lambda r: r.state in ('confirmed', 'active')))
        return {
            'total_active_buses': {'value': total_buses},
            'total_active_routes': {'value': len(active_routes)},
            'active_registrations': {'value': active_registrations},
            'seat_utilization': {
                'value': round(seats_filled / total_capacity * 100.0, 1) if total_capacity else 0.0,
            },
        }

    def _get_registration_list(self, Registration):
        records = Registration.search([], order='write_date desc', limit=REGISTRATION_LIST_LIMIT)
        return [{
            'id': r.id,
            'student_name': r.student_id.name,
            'route_name': r.route_id.name,
            'stop_name': r.stop_id.name,
            'fee_amount': r.fee_amount,
            'state': r.state,
        } for r in records]

    def _get_status_distribution(self, registrations):
        status_labels = dict(registrations._fields['state'].selection)
        counter = Counter(registrations.mapped('state'))
        ordered = [key for key, _label in registrations._fields['state'].selection if key in counter]
        return {
            'labels': [status_labels.get(k, k) for k in ordered],
            'values': [counter[k] for k in ordered],
        }

    def _get_route_wise_registrations(self, active_routes):
        routes = active_routes.sorted(key=lambda r: r.registration_count, reverse=True)
        return {
            'labels': [route.name for route in routes],
            'values': [route.registration_count for route in routes],
        }

    def _get_monthly_registration_trend(self, registrations):
        labels, values = [], []
        for i in range(MONTH_WINDOW - 1, -1, -1):
            month_start, month_end = self._month_bounds(i)
            month_records = registrations.filtered(
                lambda r: r.create_date and month_start <= r.create_date.date() <= month_end)
            labels.append(month_start.strftime('%b'))
            values.append(len(month_records))
        return {'labels': labels, 'values': values}

    def _get_seat_allocation(self, active_routes):
        total_capacity = sum(active_routes.mapped('capacity'))
        seats_remaining = sum(active_routes.mapped('seats_available'))
        seats_filled = total_capacity - seats_remaining
        return {
            'total_capacity': total_capacity,
            'seats_filled': seats_filled,
            'seats_remaining': max(seats_remaining, 0),
        }

    def _get_top_routes(self, active_routes):
        rows = [{
            'name': route.name,
            'capacity': route.capacity,
            'registrations': route.registration_count,
            'utilization': round(
                route.registration_count / route.capacity * 100.0, 1) if route.capacity else 0.0,
        } for route in active_routes]
        rows.sort(key=lambda r: r['registrations'], reverse=True)
        return rows[:TOP_ROUTES_LIMIT]

    def _get_secondary_stats(self, registrations):
        Driver = self.env['bxi.transport.driver'].sudo()
        pending_invoices = len(registrations.filtered(
            lambda r: r.invoice_id and r.invoice_payment_state not in ('paid', 'in_payment')))
        expiring_drivers = Driver.search_count([('license_expiring_soon', '=', True), ('active', '=', True)])
        monthly_revenue = sum(registrations.filtered(
            lambda r: r.state in ('confirmed', 'active')).mapped('fee_amount'))
        return {
            'pending_invoices': pending_invoices,
            'expiring_licenses': expiring_drivers,
            'monthly_fee_revenue': monthly_revenue,
        }

    def _get_recent_activity(self):
        activities = []

        Registration = self.env['bxi.transport.registration'].sudo()
        registration_labels = dict(Registration._fields['state'].selection)
        for reg in Registration.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Registration %s (%s) - %s' % (
                    reg.name, reg.student_id.name, registration_labels.get(reg.state, reg.state)),
                'date': fields.Datetime.to_string(reg.write_date),
                'kind': REGISTRATION_STATUS_KIND.get(reg.state, 'info'),
            })

        Route = self.env['bxi.transport.route'].sudo()
        route_labels = dict(Route._fields['state'].selection)
        for route in Route.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Route %s - %s' % (route.name, route_labels.get(route.state, route.state)),
                'date': fields.Datetime.to_string(route.write_date),
                'kind': ROUTE_STATUS_KIND.get(route.state, 'info'),
            })

        Driver = self.env['bxi.transport.driver'].sudo()
        driver_labels = dict(Driver._fields['status'].selection)
        for driver in Driver.search([], order='write_date desc', limit=RECENT_ACTIVITY_LIMIT):
            activities.append({
                'title': 'Driver %s - %s' % (driver.name, driver_labels.get(driver.status, driver.status)),
                'date': fields.Datetime.to_string(driver.write_date),
                'kind': DRIVER_STATUS_KIND.get(driver.status, 'info'),
            })

        activities.sort(key=lambda a: a['date'], reverse=True)
        return activities[:RECENT_ACTIVITY_LIMIT]
