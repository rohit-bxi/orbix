# -*- coding: utf-8 -*-

{
    'name': 'Orbix API Support',
    'version': '19.0.5.0.0',
    'category': 'Education',
    'summary': 'REST API for the Orbix mobile app across every Orbix school process',
    'description': """
        Orbix API Support
        ====================
        Backend-only, consumed via the Orbix API layer (bxi_api). Extends
        the existing `/api/v1/...` surface (auth, payments, messaging,
        identity, notifications, library requests, parent data, settings,
        system logs) to the day-to-day workflows of every Orbix module.
        Endpoints are thin wrappers around the action_*/get_*/wizard
        methods the underlying modules already ship; the only model-level
        additions are the /auth/me school profile, canteen top-ups as a
        Razorpay payment purpose, app push-notification hooks and a
        single-student hall ticket report.

        Phase 1: fee collection, fee exemptions, refunds, scholarships and
        student attendance.
        Phase 2: digital assessments, curriculum/PTM, lesson plans,
        timetable administration and RTE admission.
        Phase 3: certificates, announcements, notices and student
        onboarding.
        Phase 4: canteen, uniform, transport and the health-center/lab
        ancillary-ops modules.
        Mobile app: profile & master data, devices and the notification
        inbox (FCM), audience-filtered feeds, homework, offline exams,
        library circulation, events, calendar, the teacher app (today,
        classes, bulk attendance, leave, activity log), admissions,
        people, visitors, dashboards and elective registration.
    """,
    'author': 'BXI Technology Pvt. Ltd.',
    'maintainer': 'BXI Technology Pvt. Ltd.',
    'website': 'https://bxitech.com/',
    'depends': [
        'base',
        'bxi_api',
        # Phase 1
        'bxi_fee_management',
        'bxi_fee_exemption_management',
        'bxi_student_refund_management',
        'bxi_school_scholarship',
        'bxi_student_attendance',
        # Phase 2
        'bxi_assessment_hub',
        'bxi_academic_management',
        'bxi_lesson_plan',
        'bxi_class_timetable_inhencement',
        'bxi_rte_admission',
        # Phase 3
        'bxi_certificate_management',
        'bxi_school_announcement',
        'bxi_school_notice',
        'bxi_student_onboarding',
        # Phase 4
        'bxi_school_canteen_management',
        'bxi_uniform_management',
        'bxi_school_transport_bus_management',
        'op_health_center',
        'op_student_lab_management',
        # Mobile-app foundation and day-to-day processes
        'bxi_notification_gateway',
        'bxi_online_fee_payment',
        'bxi_parent_teacher_messaging',
        'openeducat_exam',
        'openeducat_assignment',
        'bxi_school_event_management',
        'visitor_management',
    ],
    'data': [
        'data/ir_cron_data.xml',
        'report/hall_ticket.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'OPL-1',
}
