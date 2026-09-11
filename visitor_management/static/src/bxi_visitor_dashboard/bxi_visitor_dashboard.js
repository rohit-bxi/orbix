import { Component, onWillStart, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

const CHART_COLORS = {
    blue: "#4f46e5",
    purple: "#7c5cff",
    green: "#16a34a",
    orange: "#f59e0b",
    pink: "#ec4899",
    red: "#dc2626",
};

const TYPE_COLORS = [CHART_COLORS.blue, CHART_COLORS.green, CHART_COLORS.orange, CHART_COLORS.pink];

const KPI_DEFS = [
    { key: "visits_today", label: "Visits Today", icon: "fa-users", color: "blue", format: "number" },
    { key: "currently_checked_in", label: "Currently Checked In", icon: "fa-sign-in", color: "green", format: "number" },
    { key: "checked_out_today", label: "Checked Out Today", icon: "fa-sign-out", color: "orange", format: "number" },
    { key: "checkout_rate", label: "Checkout Rate", icon: "fa-line-chart", color: "purple", format: "percent" },
];

const STAT_DEFS = [
    { key: "avg_visit_duration_minutes", label: "Avg. Visit Duration (min)", format: "number" },
    { key: "repeat_visitors", label: "Repeat Visitors", format: "number" },
    { key: "overstayed_visitors", label: "Overstayed Visitors", format: "number" },
];

const STATE_LABELS = {
    draft: "Draft",
    checkin: "Checked In",
    checkout: "Checked Out",
};

export class BxiVisitorDashboard extends Component {
    static template = "visitor_management.BxiVisitorDashboard";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.kpiDefs = KPI_DEFS;
        this.statDefs = STAT_DEFS;
        this.canvasRefs = {
            statusDistribution: useRef("statusDistribution"),
            typeDistribution: useRef("typeDistribution"),
            departmentWise: useRef("departmentWise"),
            monthlyTrend: useRef("monthlyTrend"),
        };
        this.charts = {};
        this.state = useState({
            loading: true,
            kpis: {},
            visitList: [],
            chartsData: {},
            topHosts: [],
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
        const data = await this.orm.call("bxi.visitor.dashboard", "get_dashboard_data", []);
        this.state.kpis = data.kpis;
        this.state.visitList = data.visit_list;
        this.state.chartsData = data.charts;
        this.state.topHosts = data.top_hosts;
        this.state.stats = data.stats;
        this.state.recentActivity = data.recent_activity;
        this.state.loading = false;
    }

    formatKpi(def) {
        const kpi = this.state.kpis[def.key];
        if (!kpi) {
            return "-";
        }
        if (def.format === "percent") {
            return `${kpi.value}%`;
        }
        return kpi.value;
    }

    formatStat(def) {
        const stat = this.state.stats[def.key];
        return stat === undefined ? "-" : stat;
    }

    stateLabel(state) {
        return STATE_LABELS[state] || state;
    }

    statusBadgeClass(state) {
        return {
            draft: "o_visitor_badge_info",
            checkin: "o_visitor_badge_warning",
            checkout: "o_visitor_badge_success",
        }[state] || "o_visitor_badge_info";
    }

    activityBadgeClass(kind) {
        return `o_visitor_badge_${kind}`;
    }

    async viewAllVisits() {
        await this.action.doAction("visitor_management.action_visit");
    }

    async openRecord(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "visit.data",
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
            type: "bar",
            data: {
                labels: data.status_distribution.labels,
                datasets: [{
                    label: "Visits",
                    data: data.status_distribution.values,
                    backgroundColor: TYPE_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });

        this.charts.typeDistribution = new Chart(this.canvasRefs.typeDistribution.el, {
            type: "pie",
            data: {
                labels: data.type_distribution.labels,
                datasets: [{
                    data: data.type_distribution.values,
                    backgroundColor: TYPE_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false },
        });

        this.charts.departmentWise = new Chart(this.canvasRefs.departmentWise.el, {
            type: "bar",
            data: {
                labels: data.department_wise.labels,
                datasets: [{
                    label: "Visits",
                    data: data.department_wise.values,
                    backgroundColor: CHART_COLORS.blue,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });

        this.charts.monthlyTrend = new Chart(this.canvasRefs.monthlyTrend.el, {
            type: "line",
            data: {
                labels: data.monthly_visit_trend.labels,
                datasets: [{
                    label: "Visits",
                    data: data.monthly_visit_trend.values,
                    borderColor: CHART_COLORS.blue,
                    backgroundColor: "rgba(79, 70, 229, 0.15)",
                    fill: true,
                    tension: 0.35,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });
    }
}

registry.category("actions").add("bxi_visitor_dashboard_client_action", BxiVisitorDashboard);
