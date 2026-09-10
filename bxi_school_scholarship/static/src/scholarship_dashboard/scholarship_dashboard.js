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

const TYPE_COLORS = [CHART_COLORS.blue, CHART_COLORS.green, CHART_COLORS.orange, CHART_COLORS.pink, CHART_COLORS.purple];

const KPI_DEFS = [
    { key: "total_scholarships_active", label: "Total Scholarships Active", icon: "fa-graduation-cap", color: "blue", format: "number" },
    { key: "total_recipients", label: "Total Recipients", icon: "fa-users", color: "green", format: "number" },
    { key: "total_amount_disbursed", label: "Total Amount Disbursed", icon: "fa-inr", color: "orange", format: "currency" },
    { key: "budget_utilization", label: "Budget Utilization", icon: "fa-line-chart", color: "purple", format: "percent" },
];

const STAT_DEFS = [
    { key: "average_per_student", label: "Average Scholarship Per Student", format: "currency" },
    { key: "highest_amount", label: "Highest Scholarship Amount", format: "currency" },
    { key: "applications_pending", label: "Applications Pending", format: "number" },
];

export class ScholarshipDashboard extends Component {
    static template = "bxi_school_scholarship.ScholarshipDashboard";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.kpiDefs = KPI_DEFS;
        this.statDefs = STAT_DEFS;
        this.canvasRefs = {
            typeDistribution: useRef("typeDistribution"),
            classWiseRecipients: useRef("classWiseRecipients"),
            monthlyTrend: useRef("monthlyTrend"),
        };
        this.charts = {};
        this.state = useState({
            loading: true,
            kpis: {},
            studentList: [],
            chartsData: {},
            topPrograms: [],
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
        const data = await this.orm.call("bxi.scholarship.dashboard", "get_dashboard_data", []);
        this.state.kpis = data.kpis;
        this.state.studentList = data.student_list;
        this.state.chartsData = data.charts;
        this.state.topPrograms = data.top_programs;
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

    coverageLabel(row) {
        return row.coverage_type === "percentage" ? `${row.coverage_percentage}%` : this.formatAmount(row.fixed_amount);
    }

    statusBadgeClass(status) {
        return {
            approved: "o_scholarship_badge_success",
            pending: "o_scholarship_badge_warning",
            rejected: "o_scholarship_badge_danger",
            draft: "o_scholarship_badge_info",
        }[status] || "o_scholarship_badge_info";
    }

    activityBadgeClass(kind) {
        return `o_scholarship_badge_${kind}`;
    }

    async viewAllStudents() {
        await this.action.doAction("bxi_school_scholarship.action_student_scholarship");
    }

    async openRecord(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "bxi.student.scholarship",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async exportFullReport() {
        const reportAction = await this.orm.call("bxi.scholarship.dashboard", "action_export_full_report", []);
        await this.action.doAction(reportAction);
    }

    renderCharts() {
        const data = this.state.chartsData;
        if (!data.type_distribution) {
            return;
        }
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

        this.charts.classWiseRecipients = new Chart(this.canvasRefs.classWiseRecipients.el, {
            type: "bar",
            data: {
                labels: data.class_wise_recipients.labels,
                datasets: [{
                    label: "Recipients",
                    data: data.class_wise_recipients.values,
                    backgroundColor: CHART_COLORS.blue,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });

        this.charts.monthlyTrend = new Chart(this.canvasRefs.monthlyTrend.el, {
            type: "line",
            data: {
                labels: data.monthly_disbursement_trend.labels,
                datasets: [{
                    label: "Disbursed",
                    data: data.monthly_disbursement_trend.values,
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

registry.category("actions").add("bxi_scholarship_dashboard_client_action", ScholarshipDashboard);
