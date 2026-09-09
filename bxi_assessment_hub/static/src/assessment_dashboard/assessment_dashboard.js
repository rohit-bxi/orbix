import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

const KPI_DEFS = [
    { key: "total_exams_scheduled", label: "Total Exams Scheduled", icon: "fa-calendar", color: "orange" },
    { key: "assessments_defined", label: "Assessments Defined", icon: "fa-file-text-o", color: "blue" },
    { key: "evaluation_in_progress", label: "Evaluation in Progress", icon: "fa-clock-o", color: "green" },
    { key: "results_locked", label: "Results Locked", icon: "fa-lock", color: "red" },
];

const QUICK_ACTIONS = [
    { label: "Create Exam", action: { type: "ir.actions.act_window", res_model: "bxi.exam", views: [[false, "form"]], target: "current" } },
    { label: "Create Assessment Structure", action: "bxi_assessment_hub.action_exam_question_import_wizard" },
    { label: "Create Digital Exam", action: "bxi_assessment_hub.action_assessment_session_new" },
    { label: "Generate Assignment", action: "bxi_assessment_hub.action_ai_assignment_generate_wizard" },
];

const NAV_TILES = [
    { label: "Exam Planner", icon: "fa-calendar-check-o", action: "bxi_assessment_hub.action_assessment_session" },
    { label: "Assessment Structure", icon: "fa-file-text-o", action: "bxi_assessment_hub.action_exam" },
    { label: "Evaluation Tracker", icon: "fa-check-square-o", action: "bxi_assessment_hub.action_assessment_submission" },
    { label: "Digital Exams", icon: "fa-desktop", action: "bxi_assessment_hub.action_exam_published" },
    { label: "AI Assignment", icon: "fa-magic", action: "bxi_assessment_hub.action_ai_assignment_generate_wizard" },
    { label: "Auto Grading", icon: "fa-cogs", action: "bxi_assessment_hub.action_assessment_autograde_wizard" },
];

const STATUS_LABELS = { scheduled: "Scheduled", evaluating: "Evaluating", completed: "Completed" };

export class AssessmentDashboard extends Component {
    static template = "bxi_assessment_hub.AssessmentDashboard";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.kpiDefs = KPI_DEFS;
        this.quickActions = QUICK_ACTIONS;
        this.navTiles = NAV_TILES;
        this.statusLabels = STATUS_LABELS;
        this.chartRef = useRef("performanceChart");
        this.chart = null;
        this.state = useState({
            kpis: {},
            alerts: {},
            recentExams: [],
            performanceByClass: { labels: [], values: [] },
        });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadData();
        });
        onMounted(() => this.renderChart());
        onWillUnmount(() => {
            if (this.chart) {
                this.chart.destroy();
            }
        });
    }

    async loadData() {
        const data = await this.orm.call("bxi.assessment.dashboard", "get_dashboard_data", []);
        this.state.kpis = data.kpis;
        this.state.alerts = data.alerts;
        this.state.recentExams = data.recent_exams;
        this.state.performanceByClass = data.performance_by_class;
    }

    async runAction(action) {
        await this.action.doAction(action);
    }

    renderChart() {
        const data = this.state.performanceByClass;
        if (!this.chartRef.el) {
            return;
        }
        this.chart = new Chart(this.chartRef.el, {
            type: "bar",
            data: {
                labels: data.labels,
                datasets: [{
                    label: "Average Performance (out of 10)",
                    data: data.values,
                    backgroundColor: "#4f46e5",
                    borderRadius: 4,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { beginAtZero: true, max: 10 } },
                plugins: { legend: { display: false } },
            },
        });
    }
}

registry.category("actions").add("bxi_assessment_dashboard_client_action", AssessmentDashboard);
