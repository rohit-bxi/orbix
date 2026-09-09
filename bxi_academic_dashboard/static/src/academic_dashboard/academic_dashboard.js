import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const KPI_DEFS = [
    { key: "total_curriculum", label: "Total Curriculum", icon: "fa-book", color: "blue" },
    { key: "upcoming_events", label: "Upcoming Events", icon: "fa-calendar", color: "green" },
    { key: "pending_approvals", label: "Pending Approvals", icon: "fa-file-text-o", color: "orange" },
    { key: "lesson_plans", label: "Lesson Plans", icon: "fa-line-chart", color: "purple" },
];

const TABS = [
    { key: "curriculum", label: "Curriculum" },
    { key: "lesson_plan", label: "Lesson Plan" },
    { key: "calendar", label: "Academic Calendar" },
];

const APPROVAL_LABELS = { draft: "Draft", approved: "Approved", rejected: "Rejected" };
const LESSON_STATE_LABELS = { pending: "Pending", approved: "Approved", rejected: "Rejected" };

export class AcademicDashboard extends Component {
    static template = "bxi_academic_dashboard.AcademicDashboard";

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.kpiDefs = KPI_DEFS;
        this.tabs = TABS;
        this.approvalLabels = APPROVAL_LABELS;
        this.lessonStateLabels = LESSON_STATE_LABELS;
        this.state = useState({
            activeTab: "curriculum",
            searchTerm: "",
            kpis: {},
            curricula: [],
            lessonPlans: [],
            calendarEvents: [],
        });

        onWillStart(() => this.loadData());
    }

    async loadData() {
        const data = await this.orm.call("bxi.academic.dashboard", "get_dashboard_data", []);
        this.state.kpis = data.kpis;
        this.state.curricula = data.curricula;
        this.state.lessonPlans = data.lesson_plans;
        this.state.calendarEvents = data.calendar_events;
    }

    get filteredCurricula() {
        const term = this.state.searchTerm.trim().toLowerCase();
        if (!term) {
            return this.state.curricula;
        }
        return this.state.curricula.filter((curriculum) =>
            curriculum.name.toLowerCase().includes(term)
            || (curriculum.board || "").toLowerCase().includes(term)
            || curriculum.classes.some((cls) => cls.toLowerCase().includes(term))
        );
    }

    setTab(key) {
        this.state.activeTab = key;
    }

    async openAction(actionXmlId) {
        await this.action.doAction(actionXmlId);
    }

    async openCurriculum(curriculumId) {
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "bxi.curriculum",
            res_id: curriculumId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async callCurriculumAction(curriculumId, methodName) {
        await this.orm.call("bxi.curriculum", methodName, [[curriculumId]]);
        await this.loadData();
    }

    async openCurriculumFormAction(curriculumId, methodName) {
        const result = await this.orm.call("bxi.curriculum", methodName, [[curriculumId]]);
        await this.action.doAction(result);
    }
}

registry.category("actions").add("bxi_academic_dashboard_client_action", AcademicDashboard);
