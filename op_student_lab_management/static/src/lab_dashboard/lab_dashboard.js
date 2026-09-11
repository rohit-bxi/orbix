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

const STATUS_COLORS = [CHART_COLORS.blue, CHART_COLORS.orange, CHART_COLORS.orange, CHART_COLORS.green, CHART_COLORS.red];
const TYPE_COLORS = [CHART_COLORS.blue, CHART_COLORS.green, CHART_COLORS.orange, CHART_COLORS.pink, CHART_COLORS.purple];
const ATTENDANCE_COLORS = [CHART_COLORS.green, CHART_COLORS.red, CHART_COLORS.orange];

const KPI_DEFS = [
    { key: "sessions_today", label: "Sessions Today", icon: "fa-flask", color: "blue", format: "number" },
    { key: "sessions_in_progress", label: "Sessions In Progress", icon: "fa-clock-o", color: "orange", format: "number" },
    { key: "equipment_issued", label: "Equipment Issued", icon: "fa-wrench", color: "green", format: "number" },
    { key: "attendance_rate", label: "Attendance Rate", icon: "fa-line-chart", color: "purple", format: "percent" },
];

const STAT_DEFS = [
    { key: "avg_experiment_score_pct", label: "Avg. Experiment Score (%)", format: "number" },
    { key: "equipment_under_repair_count", label: "Equipment Under Repair", format: "number" },
    { key: "active_rooms_count", label: "Active Lab Rooms", format: "number" },
];

const STATE_LABELS = {
    draft: "Draft",
    confirmed: "Confirmed",
    in_progress: "In Progress",
    done: "Done",
    cancelled: "Cancelled",
};

export class LabDashboard extends Component {
    static template = "op_student_lab_management.LabDashboard";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.kpiDefs = KPI_DEFS;
        this.statDefs = STAT_DEFS;
        this.canvasRefs = {
            statusDistribution: useRef("statusDistribution"),
            labTypeDistribution: useRef("labTypeDistribution"),
            attendanceDistribution: useRef("attendanceDistribution"),
            monthlyTrend: useRef("monthlyTrend"),
        };
        this.charts = {};
        this.state = useState({
            loading: true,
            kpis: {},
            sessionList: [],
            chartsData: {},
            equipmentAttention: [],
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
        const data = await this.orm.call("lab.dashboard", "get_dashboard_data", []);
        this.state.kpis = data.kpis;
        this.state.sessionList = data.session_list;
        this.state.chartsData = data.charts;
        this.state.equipmentAttention = data.equipment_attention;
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
            draft: "o_lab_badge_info",
            confirmed: "o_lab_badge_warning",
            in_progress: "o_lab_badge_warning",
            done: "o_lab_badge_success",
            cancelled: "o_lab_badge_danger",
        }[state] || "o_lab_badge_info";
    }

    activityBadgeClass(kind) {
        return `o_lab_badge_${kind}`;
    }

    async viewAllSessions() {
        await this.action.doAction("op_student_lab_management.action_lab_session");
    }

    async openRecord(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "lab.session",
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
                    label: "Sessions",
                    data: data.status_distribution.values,
                    backgroundColor: STATUS_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });

        this.charts.labTypeDistribution = new Chart(this.canvasRefs.labTypeDistribution.el, {
            type: "pie",
            data: {
                labels: data.lab_type_distribution.labels,
                datasets: [{
                    data: data.lab_type_distribution.values,
                    backgroundColor: TYPE_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false },
        });

        this.charts.attendanceDistribution = new Chart(this.canvasRefs.attendanceDistribution.el, {
            type: "bar",
            data: {
                labels: data.attendance_distribution.labels,
                datasets: [{
                    label: "Attendance",
                    data: data.attendance_distribution.values,
                    backgroundColor: ATTENDANCE_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });

        this.charts.monthlyTrend = new Chart(this.canvasRefs.monthlyTrend.el, {
            type: "line",
            data: {
                labels: data.monthly_session_trend.labels,
                datasets: [{
                    label: "Sessions",
                    data: data.monthly_session_trend.values,
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

registry.category("actions").add("lab_dashboard_client_action", LabDashboard);
