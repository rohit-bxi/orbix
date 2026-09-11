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

const STATUS_COLORS = [
    CHART_COLORS.blue, CHART_COLORS.orange, CHART_COLORS.red, CHART_COLORS.purple,
    CHART_COLORS.green, CHART_COLORS.pink, "#0891b2", "#65a30d", "#6b7280",
];

const KPI_DEFS = [
    { key: "total_rte_applicants", label: "Total RTE Applicants", icon: "fa-users", color: "blue", format: "number" },
    { key: "total_seats_reserved", label: "Total RTE Seats Reserved", icon: "fa-child", color: "green", format: "number" },
    { key: "seats_filled", label: "Seats Allotted / Confirmed / Admitted", icon: "fa-check-circle", color: "orange", format: "number" },
    { key: "seat_utilization", label: "Seat Utilization", icon: "fa-line-chart", color: "purple", format: "percent" },
];

const STAT_DEFS = [
    { key: "reimbursement_pending_amount", label: "Reimbursement Pending", format: "currency" },
    { key: "reimbursement_paid_amount", label: "Reimbursement Paid", format: "currency" },
    { key: "open_grievances", label: "Open Grievances", format: "number" },
];

const STATE_LABELS = {
    draft: "Draft",
    doc_verified: "Documents Verified",
    doc_rejected: "Documents Rejected",
    lottery_pending: "Lottery Pending",
    allotted: "Allotted",
    waitlisted: "Waitlisted",
    confirmed: "Confirmed",
    admitted: "Admitted",
    lapsed: "Lapsed",
};

export class RteDashboard extends Component {
    static template = "bxi_rte_admission.RteDashboard";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.kpiDefs = KPI_DEFS;
        this.statDefs = STAT_DEFS;
        this.canvasRefs = {
            statusDistribution: useRef("statusDistribution"),
            categoryDistribution: useRef("categoryDistribution"),
            monthlyTrend: useRef("monthlyTrend"),
        };
        this.charts = {};
        this.state = useState({
            loading: true,
            kpis: {},
            applicationList: [],
            chartsData: {},
            topCourses: [],
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
        const data = await this.orm.call("bxi.rte.dashboard", "get_dashboard_data", []);
        this.state.kpis = data.kpis;
        this.state.applicationList = data.application_list;
        this.state.chartsData = data.charts;
        this.state.topCourses = data.top_courses;
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
            draft: "o_rte_badge_info",
            doc_verified: "o_rte_badge_success",
            doc_rejected: "o_rte_badge_danger",
            lottery_pending: "o_rte_badge_warning",
            allotted: "o_rte_badge_success",
            waitlisted: "o_rte_badge_warning",
            confirmed: "o_rte_badge_success",
            admitted: "o_rte_badge_success",
            lapsed: "o_rte_badge_danger",
        }[state] || "o_rte_badge_info";
    }

    activityBadgeClass(kind) {
        return `o_rte_badge_${kind}`;
    }

    async viewAllApplications() {
        await this.action.doAction("bxi_rte_admission.act_open_op_admission_rte_view");
    }

    async openRecord(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "op.admission",
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
                    label: "Applicants",
                    data: data.status_distribution.values,
                    backgroundColor: STATUS_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });

        this.charts.categoryDistribution = new Chart(this.canvasRefs.categoryDistribution.el, {
            type: "pie",
            data: {
                labels: data.category_distribution.labels,
                datasets: [{
                    data: data.category_distribution.values,
                    backgroundColor: STATUS_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false },
        });

        this.charts.monthlyTrend = new Chart(this.canvasRefs.monthlyTrend.el, {
            type: "line",
            data: {
                labels: data.monthly_application_trend.labels,
                datasets: [{
                    label: "Applications",
                    data: data.monthly_application_trend.values,
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

registry.category("actions").add("bxi_rte_dashboard_client_action", RteDashboard);
