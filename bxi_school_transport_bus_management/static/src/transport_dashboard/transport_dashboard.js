import { Component, onWillStart, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { formatCurrency } from "@web/core/currency";
import { user } from "@web/core/user";

const CHART_COLORS = {
    blue: "#4f46e5",
    purple: "#7c5cff",
    green: "#16a34a",
    orange: "#f59e0b",
    pink: "#ec4899",
    red: "#dc2626",
};

const STATUS_COLORS = [CHART_COLORS.blue, CHART_COLORS.orange, CHART_COLORS.green, CHART_COLORS.red];

const KPI_DEFS = [
    { key: "total_active_buses", label: "Total Active Buses", icon: "fa-bus", color: "blue", format: "number" },
    { key: "total_active_routes", label: "Active Routes", icon: "fa-road", color: "green", format: "number" },
    { key: "active_registrations", label: "Active Registrations", icon: "fa-users", color: "orange", format: "number" },
    { key: "seat_utilization", label: "Seat Utilization", icon: "fa-line-chart", color: "purple", format: "percent" },
];

const STAT_DEFS = [
    { key: "pending_invoices", label: "Pending Transport Invoices", format: "number" },
    { key: "expiring_licenses", label: "Licenses Expiring Soon", format: "number" },
    { key: "monthly_fee_revenue", label: "Active Monthly Fee Revenue", format: "currency" },
];

const STATE_LABELS = {
    draft: "Draft",
    confirmed: "Confirmed",
    active: "Active",
    cancelled: "Cancelled",
};

export class TransportDashboard extends Component {
    static template = "bxi_school_transport_bus_management.TransportDashboard";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.kpiDefs = KPI_DEFS;
        this.statDefs = STAT_DEFS;
        this.canvasRefs = {
            statusDistribution: useRef("statusDistribution"),
            routeWiseRegistrations: useRef("routeWiseRegistrations"),
            monthlyTrend: useRef("monthlyTrend"),
        };
        this.charts = {};
        this.state = useState({
            loading: true,
            kpis: {},
            registrationList: [],
            chartsData: {},
            topRoutes: [],
            stats: {},
            recentActivity: [],
        });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadData();
        });
        onMounted(() => this.renderCharts());
        onWillUnmount(() => {
            Object.values(this.charts).forEach((chart) => chart && chart.destroy());
        });
    }

    async loadData() {
        const data = await this.orm.call("bxi.transport.dashboard", "get_dashboard_data", []);
        this.state.kpis = data.kpis;
        this.state.registrationList = data.registration_list;
        this.state.chartsData = data.charts;
        this.state.topRoutes = data.top_routes;
        this.state.stats = data.stats;
        this.state.recentActivity = data.recent_activity;
        this.state.loading = false;
    }

    formatAmount(value) {
        return formatCurrency(value || 0, user.activeCompany.currency_id, { humanReadable: true });
    }

    formatKpi(def) {
        const kpi = this.state.kpis[def.key];
        if (!kpi) {
            return "-";
        }
        if (def.format === "currency") {
            return this.formatAmount(kpi.value);
        }
        if (def.format === "percent") {
            return `${kpi.value}%`;
        }
        return kpi.value;
    }

    formatStat(def) {
        const stat = this.state.stats[def.key];
        if (stat === undefined) {
            return "-";
        }
        if (def.format === "currency") {
            return this.formatAmount(stat);
        }
        return stat;
    }

    stateLabel(state) {
        return STATE_LABELS[state] || state;
    }

    statusBadgeClass(state) {
        return {
            draft: "o_transport_badge_info",
            confirmed: "o_transport_badge_warning",
            active: "o_transport_badge_success",
            cancelled: "o_transport_badge_danger",
        }[state] || "o_transport_badge_info";
    }

    activityBadgeClass(kind) {
        return `o_transport_badge_${kind}`;
    }

    async viewAllRegistrations() {
        await this.action.doAction("bxi_school_transport_bus_management.action_transport_registration");
    }

    async openRecord(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "bxi.transport.registration",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    renderCharts() {
        const data = this.state.chartsData;
        if (!data.status_distribution) {
            return;
        }
        this.charts.statusDistribution = new Chart(this.canvasRefs.statusDistribution.el, {
            type: "pie",
            data: {
                labels: data.status_distribution.labels,
                datasets: [{
                    data: data.status_distribution.values,
                    backgroundColor: STATUS_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false },
        });

        this.charts.routeWiseRegistrations = new Chart(this.canvasRefs.routeWiseRegistrations.el, {
            type: "bar",
            data: {
                labels: data.route_wise_registrations.labels,
                datasets: [{
                    label: "Registrations",
                    data: data.route_wise_registrations.values,
                    backgroundColor: CHART_COLORS.blue,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });

        this.charts.monthlyTrend = new Chart(this.canvasRefs.monthlyTrend.el, {
            type: "line",
            data: {
                labels: data.monthly_registration_trend.labels,
                datasets: [{
                    label: "Registrations",
                    data: data.monthly_registration_trend.values,
                    borderColor: CHART_COLORS.green,
                    backgroundColor: "rgba(22, 163, 74, 0.15)",
                    fill: true,
                    tension: 0.35,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });
    }
}

registry.category("actions").add("bxi_transport_dashboard_client_action", TransportDashboard);
