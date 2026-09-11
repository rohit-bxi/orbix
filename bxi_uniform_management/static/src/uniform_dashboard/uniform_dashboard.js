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
    { key: "orders_today", label: "Orders Today", icon: "fa-shopping-bag", color: "blue", format: "number" },
    { key: "orders_pending_issue", label: "Pending Issue", icon: "fa-clock-o", color: "orange", format: "number" },
    { key: "total_amount_today", label: "Today's Order Value", icon: "fa-inr", color: "green", format: "currency" },
    { key: "issue_completion_rate", label: "Issue Completion Rate", icon: "fa-line-chart", color: "purple", format: "percent" },
];

const STAT_DEFS = [
    { key: "low_stock_item_count", label: "Low Stock Items", format: "number" },
    { key: "orders_issued_month", label: "Orders Issued This Month", format: "number" },
    { key: "pending_invoices", label: "Pending Invoices", format: "number" },
];

const STATE_LABELS = {
    draft: "Draft",
    confirmed: "Confirmed",
    issued: "Issued",
    cancelled: "Cancelled",
};

export class UniformDashboard extends Component {
    static template = "bxi_uniform_management.UniformDashboard";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.kpiDefs = KPI_DEFS;
        this.statDefs = STAT_DEFS;
        this.canvasRefs = {
            statusDistribution: useRef("statusDistribution"),
            topProducts: useRef("topProducts"),
            monthlyTrend: useRef("monthlyTrend"),
        };
        this.charts = {};
        this.state = useState({
            loading: true,
            kpis: {},
            orderList: [],
            chartsData: {},
            lowStockItems: [],
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
        const data = await this.orm.call("bxi.uniform.dashboard", "get_dashboard_data", []);
        this.state.kpis = data.kpis;
        this.state.orderList = data.order_list;
        this.state.chartsData = data.charts;
        this.state.lowStockItems = data.low_stock_items;
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
        return stat === undefined ? "-" : stat;
    }

    stateLabel(state) {
        return STATE_LABELS[state] || state;
    }

    statusBadgeClass(state) {
        return {
            draft: "o_uniform_badge_info",
            confirmed: "o_uniform_badge_warning",
            issued: "o_uniform_badge_success",
            cancelled: "o_uniform_badge_danger",
        }[state] || "o_uniform_badge_info";
    }

    activityBadgeClass(kind) {
        return `o_uniform_badge_${kind}`;
    }

    async viewAllOrders() {
        await this.action.doAction("bxi_uniform_management.action_uniform_order");
    }

    async openRecord(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "bxi.uniform.order",
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

        this.charts.topProducts = new Chart(this.canvasRefs.topProducts.el, {
            type: "bar",
            data: {
                labels: data.top_products.labels,
                datasets: [{
                    label: "Quantity Ordered",
                    data: data.top_products.values,
                    backgroundColor: CHART_COLORS.blue,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false, indexAxis: "y",
                plugins: { legend: { display: false } },
            },
        });

        this.charts.monthlyTrend = new Chart(this.canvasRefs.monthlyTrend.el, {
            type: "line",
            data: {
                labels: data.monthly_revenue_trend.labels,
                datasets: [{
                    label: "Order Value",
                    data: data.monthly_revenue_trend.values,
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

registry.category("actions").add("bxi_uniform_dashboard_client_action", UniformDashboard);
