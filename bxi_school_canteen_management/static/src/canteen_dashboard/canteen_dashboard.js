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

const STATUS_COLORS = [CHART_COLORS.blue, CHART_COLORS.orange, CHART_COLORS.orange, CHART_COLORS.orange, CHART_COLORS.green, CHART_COLORS.red];

const KPI_DEFS = [
    { key: "orders_today", label: "Orders Today", icon: "fa-cutlery", color: "blue", format: "number" },
    { key: "orders_in_progress", label: "Orders In Progress", icon: "fa-clock-o", color: "orange", format: "number" },
    { key: "today_revenue", label: "Today's Revenue", icon: "fa-inr", color: "green", format: "currency" },
    { key: "order_completion_rate", label: "Order Completion Rate", icon: "fa-line-chart", color: "purple", format: "percent" },
];

const STAT_DEFS = [
    { key: "total_wallet_balance", label: "Total Wallet Balance", format: "currency" },
    { key: "low_balance_wallet_count", label: "Low Balance Wallets", format: "number" },
    { key: "monthly_topup_amount", label: "Monthly Top-ups", format: "currency" },
];

const STATE_LABELS = {
    draft: "Draft",
    confirmed: "Confirmed",
    preparing: "Preparing",
    ready: "Ready",
    served: "Served",
    cancelled: "Cancelled",
};

export class CanteenDashboard extends Component {
    static template = "bxi_school_canteen_management.CanteenDashboard";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.kpiDefs = KPI_DEFS;
        this.statDefs = STAT_DEFS;
        this.canvasRefs = {
            statusDistribution: useRef("statusDistribution"),
            bestSellingItems: useRef("bestSellingItems"),
            monthlyTrend: useRef("monthlyTrend"),
        };
        this.charts = {};
        this.state = useState({
            loading: true,
            kpis: {},
            orderList: [],
            chartsData: {},
            lowBalanceWallets: [],
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
        const data = await this.orm.call("bxi.canteen.dashboard", "get_dashboard_data", []);
        this.state.kpis = data.kpis;
        this.state.orderList = data.order_list;
        this.state.chartsData = data.charts;
        this.state.lowBalanceWallets = data.low_balance_wallets;
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
            draft: "o_canteen_badge_info",
            confirmed: "o_canteen_badge_warning",
            preparing: "o_canteen_badge_warning",
            ready: "o_canteen_badge_warning",
            served: "o_canteen_badge_success",
            cancelled: "o_canteen_badge_danger",
        }[state] || "o_canteen_badge_info";
    }

    activityBadgeClass(kind) {
        return `o_canteen_badge_${kind}`;
    }

    async viewAllOrders() {
        await this.action.doAction("bxi_school_canteen_management.action_canteen_order");
    }

    async openRecord(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "bxi.canteen.order",
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
                    label: "Orders",
                    data: data.status_distribution.values,
                    backgroundColor: STATUS_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });

        this.charts.bestSellingItems = new Chart(this.canvasRefs.bestSellingItems.el, {
            type: "bar",
            data: {
                labels: data.best_selling_items.labels,
                datasets: [{
                    label: "Quantity Sold",
                    data: data.best_selling_items.values,
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
                    label: "Revenue",
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

registry.category("actions").add("bxi_canteen_dashboard_client_action", CanteenDashboard);
