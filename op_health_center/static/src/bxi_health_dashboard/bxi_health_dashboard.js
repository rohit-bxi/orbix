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

const STATUS_COLORS = [
    CHART_COLORS.blue, CHART_COLORS.orange, CHART_COLORS.orange, CHART_COLORS.green,
    CHART_COLORS.blue, CHART_COLORS.red,
];
const FITNESS_COLORS = [CHART_COLORS.green, CHART_COLORS.red, CHART_COLORS.orange];

const KPI_DEFS = [
    { key: "visits_today", label: "Visits Today", icon: "fa-calendar-check-o", color: "blue", format: "number" },
    { key: "visits_month", label: "Visits This Month", icon: "fa-stethoscope", color: "green", format: "number" },
    { key: "open_cases", label: "Open Cases", icon: "fa-clock-o", color: "orange", format: "number" },
    { key: "checkup_compliance", label: "Checkup Compliance", icon: "fa-heart-o", color: "purple", format: "percent" },
];

const STAT_DEFS = [
    { key: "active_alert_count", label: "Active Medical Alerts", format: "number" },
    { key: "upcoming_vaccination_count", label: "Vaccinations Due (30 days)", format: "number" },
    { key: "overdue_followups", label: "Overdue Follow-ups", format: "number" },
];

const STATE_LABELS = {
    draft: "Draft",
    confirmed: "Confirmed",
    under_treatment: "Under Treatment",
    resolved: "Resolved",
    referred: "Referred",
    cancelled: "Cancelled",
};

export class BxiHealthDashboard extends Component {
    static template = "op_health_center.BxiHealthDashboard";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.kpiDefs = KPI_DEFS;
        this.statDefs = STAT_DEFS;
        this.canvasRefs = {
            visitStatusDistribution: useRef("visitStatusDistribution"),
            fitnessDistribution: useRef("fitnessDistribution"),
            monthlyTrend: useRef("monthlyTrend"),
        };
        this.charts = {};
        this.state = useState({
            loading: true,
            kpis: {},
            visitList: [],
            chartsData: {},
            topVaccines: [],
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
        const data = await this.orm.call("bxi.health.dashboard", "get_dashboard_data", []);
        this.state.kpis = data.kpis;
        this.state.visitList = data.visit_list;
        this.state.chartsData = data.charts;
        this.state.topVaccines = data.top_vaccines;
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
            draft: "o_health2_badge_info",
            confirmed: "o_health2_badge_warning",
            under_treatment: "o_health2_badge_warning",
            resolved: "o_health2_badge_success",
            referred: "o_health2_badge_info",
            cancelled: "o_health2_badge_danger",
        }[state] || "o_health2_badge_info";
    }

    activityBadgeClass(kind) {
        return `o_health2_badge_${kind}`;
    }

    async viewAllVisits() {
        await this.action.doAction("op_health_center.action_health_visit");
    }

    async openRecord(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "op.health.visit",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    renderCharts() {
        const data = this.state.chartsData;
        if (!data.visit_status_distribution) {
            return;
        }
        this.charts.visitStatusDistribution = new Chart(this.canvasRefs.visitStatusDistribution.el, {
            type: "bar",
            data: {
                labels: data.visit_status_distribution.labels,
                datasets: [{
                    label: "Visits",
                    data: data.visit_status_distribution.values,
                    backgroundColor: STATUS_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });

        this.charts.fitnessDistribution = new Chart(this.canvasRefs.fitnessDistribution.el, {
            type: "pie",
            data: {
                labels: data.fitness_distribution.labels,
                datasets: [{
                    data: data.fitness_distribution.values,
                    backgroundColor: FITNESS_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false },
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

registry.category("actions").add("bxi_health_dashboard_client_action", BxiHealthDashboard);
