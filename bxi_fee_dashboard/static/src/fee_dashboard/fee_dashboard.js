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

const KPI_DEFS = [
    { key: "total_fees_collected", label: "Total Fees Collected", icon: "fa-inr", color: "green", format: "currency" },
    { key: "pending_payments", label: "Pending Payments", icon: "fa-clock-o", color: "orange", format: "currency" },
    { key: "total_refunds", label: "Total Refunds", icon: "fa-refresh", color: "blue", format: "currency" },
    { key: "scholarships", label: "Scholarships", icon: "fa-graduation-cap", color: "green", format: "number" },
    { key: "manual_approvals", label: "Manual Approvals", icon: "fa-file-text-o", color: "red", format: "number" },
    { key: "online_payments", label: "Online Payments", icon: "fa-credit-card", color: "blue", format: "number" },
    { key: "receipts_generated", label: "Receipt Generated", icon: "fa-file-text", color: "blue", format: "number" },
    { key: "collection_efficiency", label: "Collection Efficiency", icon: "fa-line-chart", color: "green", format: "percent" },
];

const TILE_DEFS = [
    { label: "Fee Structure", icon: "fa-sitemap", action: "bxi_fee_management.action_fee_structure_category_overview" },
    { label: "Fee Collection", icon: "fa-money", action: "bxi_fee_management.action_fee_collection" },
    { label: "Scholarships", icon: "fa-graduation-cap", action: "bxi_school_scholarship.action_student_scholarship" },
    { label: "Refunds", icon: "fa-refresh", action: "bxi_student_refund_management.action_refund_request" },
    { label: "Fee Exceptions", icon: "fa-shield", action: "bxi_fee_exemption_management.action_fee_exemption_request" },
    { label: "Payment Report", icon: "fa-bar-chart", action: "bxi_fee_dashboard.action_fee_payment_report" },
    { label: "Receipt Generator", icon: "fa-file-text-o", action: "bxi_fee_dashboard.action_fee_receipt_generator" },
    { label: "Online Payment Gateway", icon: "fa-credit-card", action: "bxi_online_fee_payment.action_bxi_payment_order" },
];

const QUICK_ACTION_DEFS = [
    { label: "Create Fee Structure", icon: "fa-plus", color: "blue", action: "bxi_fee_management.action_fee_structure" },
    { label: "Add Scholarship", icon: "fa-graduation-cap", color: "orange", action: "bxi_school_scholarship.action_student_scholarship" },
    { label: "Generate Receipt", icon: "fa-file-text-o", color: "blue", action: "bxi_fee_dashboard.action_fee_receipt_generator" },
    { label: "Approve Refund", icon: "fa-refresh", color: "green", action: "bxi_student_refund_management.action_refund_bulk_wizard" },
    { label: "Send Reminder", icon: "fa-paper-plane", color: "blue", action: "bxi_fee_management.action_fee_collection" },
    { label: "Create Exemption", icon: "fa-shield", color: "blue", action: "bxi_fee_exemption_management.action_fee_exemption_request" },
];

export class FeeDashboard extends Component {
    static template = "bxi_fee_dashboard.FeeDashboard";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.kpiDefs = KPI_DEFS;
        this.tileDefs = TILE_DEFS;
        this.quickActionDefs = QUICK_ACTION_DEFS;
        this.canvasRefs = {
            onlineVsOffline: useRef("onlineVsOffline"),
            monthlyTrend: useRef("monthlyTrend"),
            scholarshipDistribution: useRef("scholarshipDistribution"),
            refundTrends: useRef("refundTrends"),
        };
        this.charts = {};
        this.state = useState({
            loading: true,
            kpis: {},
            chartsData: {},
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
        const data = await this.orm.call("bxi.fee.dashboard", "get_dashboard_data", []);
        this.state.kpis = data.kpis;
        this.state.chartsData = data.charts;
        this.state.recentActivity = data.recent_activity;
        this.state.loading = false;
    }

    formatKpi(def) {
        const kpi = this.state.kpis[def.key];
        if (!kpi) {
            return "-";
        }
        if (def.format === "currency") {
            return formatCurrency(kpi.value, user.activeCompany.currency_id, { humanReadable: true });
        }
        if (def.format === "percent") {
            return `${kpi.value}%`;
        }
        return kpi.value;
    }

    kpiChange(def) {
        return this.state.kpis[def.key] && this.state.kpis[def.key].change;
    }

    async openAction(actionXmlId) {
        await this.action.doAction(actionXmlId);
    }

    renderCharts() {
        const data = this.state.chartsData;
        if (!data.online_vs_offline) {
            return;
        }
        this.charts.onlineVsOffline = new Chart(this.canvasRefs.onlineVsOffline.el, {
            type: "pie",
            data: {
                labels: ["Online", "Offline"],
                datasets: [{
                    data: [data.online_vs_offline.online, data.online_vs_offline.offline],
                    backgroundColor: [CHART_COLORS.blue, CHART_COLORS.purple],
                }],
            },
            options: { responsive: true, maintainAspectRatio: false },
        });

        this.charts.monthlyTrend = new Chart(this.canvasRefs.monthlyTrend.el, {
            type: "line",
            data: {
                labels: data.monthly_collection_trend.labels,
                datasets: [{
                    label: "Collected",
                    data: data.monthly_collection_trend.values,
                    borderColor: CHART_COLORS.blue,
                    backgroundColor: "rgba(79, 70, 229, 0.15)",
                    fill: true,
                    tension: 0.35,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false },
        });

        this.charts.scholarshipDistribution = new Chart(this.canvasRefs.scholarshipDistribution.el, {
            type: "bar",
            data: {
                labels: data.scholarship_distribution.labels,
                datasets: [{
                    label: "Scholarships",
                    data: data.scholarship_distribution.values,
                    backgroundColor: [CHART_COLORS.green, CHART_COLORS.orange, CHART_COLORS.pink, CHART_COLORS.blue, CHART_COLORS.purple],
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });

        this.charts.refundTrends = new Chart(this.canvasRefs.refundTrends.el, {
            type: "line",
            data: {
                labels: data.refund_trends.labels,
                datasets: [{
                    label: "Refunds",
                    data: data.refund_trends.values,
                    borderColor: CHART_COLORS.purple,
                    backgroundColor: "rgba(124, 92, 255, 0.15)",
                    tension: 0.35,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });
    }
}

registry.category("actions").add("bxi_fee_dashboard_client_action", FeeDashboard);
