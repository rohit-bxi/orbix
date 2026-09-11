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

const STATUS_COLORS = [CHART_COLORS.blue, CHART_COLORS.green, CHART_COLORS.orange, CHART_COLORS.purple, CHART_COLORS.red];
const GENDER_COLORS = [CHART_COLORS.blue, CHART_COLORS.pink, CHART_COLORS.purple];

const KPI_DEFS = [
    { key: "total_students", label: "Total Students", icon: "fa-users", color: "blue", format: "number" },
    { key: "new_admissions_month", label: "New Admissions This Month", icon: "fa-user-plus", color: "green", format: "number" },
    { key: "onboarding_in_progress", label: "Onboarding In Progress", icon: "fa-hourglass-half", color: "orange", format: "number" },
    { key: "onboarding_completion_rate", label: "Onboarding Completion Rate", icon: "fa-line-chart", color: "purple", format: "percent" },
];

const STAT_DEFS = [
    { key: "students_with_medical_alert", label: "Students With Medical Alert", format: "number" },
    { key: "students_without_parent", label: "Students Without Parent Linked", format: "number" },
    { key: "students_missing_blood_group", label: "Missing Blood Group", format: "number" },
];

export class BxiStudentDashboard extends Component {
    static template = "bxi_student_onboarding.BxiStudentDashboard";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.kpiDefs = KPI_DEFS;
        this.statDefs = STAT_DEFS;
        this.canvasRefs = {
            enrollmentStatusDistribution: useRef("enrollmentStatusDistribution"),
            genderDistribution: useRef("genderDistribution"),
            courseWiseDistribution: useRef("courseWiseDistribution"),
            monthlyTrend: useRef("monthlyTrend"),
        };
        this.charts = {};
        this.state = useState({
            loading: true,
            kpis: {},
            studentList: [],
            chartsData: {},
            onboardingPipeline: [],
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
        const data = await this.orm.call("bxi.student.dashboard", "get_dashboard_data", []);
        this.state.kpis = data.kpis;
        this.state.studentList = data.student_list;
        this.state.chartsData = data.charts;
        this.state.onboardingPipeline = data.onboarding_pipeline;
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

    statusBadgeClass(status) {
        return {
            new_admission: "o_student_badge_info",
            active: "o_student_badge_success",
            transferred: "o_student_badge_warning",
            alumni: "o_student_badge_success",
            dropped: "o_student_badge_danger",
        }[status] || "o_student_badge_info";
    }

    onboardingBadgeClass(state) {
        return {
            basic_info: "o_student_badge_info",
            academic_info: "o_student_badge_warning",
            documents: "o_student_badge_warning",
            done: "o_student_badge_success",
        }[state] || "o_student_badge_info";
    }

    activityBadgeClass(kind) {
        return `o_student_badge_${kind}`;
    }

    async viewAllStudents() {
        await this.action.doAction("openeducat_core.act_open_op_student_view");
    }

    async viewAllOnboarding() {
        await this.action.doAction("bxi_student_onboarding.action_bxi_student_onboarding");
    }

    async openStudent(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "op.student",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async openOnboarding(id) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "bxi.student.onboarding",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    renderCharts() {
        const data = this.state.chartsData;
        if (!data.enrollment_status_distribution) {
            return;
        }
        this.charts.enrollmentStatusDistribution = new Chart(this.canvasRefs.enrollmentStatusDistribution.el, {
            type: "bar",
            data: {
                labels: data.enrollment_status_distribution.labels,
                datasets: [{
                    label: "Students",
                    data: data.enrollment_status_distribution.values,
                    backgroundColor: STATUS_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });

        this.charts.genderDistribution = new Chart(this.canvasRefs.genderDistribution.el, {
            type: "pie",
            data: {
                labels: data.gender_distribution.labels,
                datasets: [{
                    data: data.gender_distribution.values,
                    backgroundColor: GENDER_COLORS,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false },
        });

        this.charts.courseWiseDistribution = new Chart(this.canvasRefs.courseWiseDistribution.el, {
            type: "bar",
            data: {
                labels: data.course_wise_distribution.labels,
                datasets: [{
                    label: "Students",
                    data: data.course_wise_distribution.values,
                    backgroundColor: CHART_COLORS.blue,
                }],
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
        });

        this.charts.monthlyTrend = new Chart(this.canvasRefs.monthlyTrend.el, {
            type: "line",
            data: {
                labels: data.monthly_admission_trend.labels,
                datasets: [{
                    label: "Admissions",
                    data: data.monthly_admission_trend.values,
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

registry.category("actions").add("bxi_student_dashboard_client_action", BxiStudentDashboard);
