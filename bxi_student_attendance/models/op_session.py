from odoo import api, fields, models


class OpSession(models.Model):
    _inherit = 'op.session'

    timetable_line_id = fields.Many2one(
        'bxi.timetable.line', string='Timetable Period',
        ondelete='set null', index=True)
    session_date = fields.Date(
        compute='_compute_session_date', store=True, index=True)

    _unique_timetable_line_session_date = models.Constraint(
        'unique(timetable_line_id, session_date)',
        'A session already exists for this timetable period on this date.')

    @api.depends('start_datetime')
    def _compute_session_date(self):
        for session in self:
            session.session_date = (
                session.start_datetime.date() if session.start_datetime else False
            )

    @api.model
    def _generate_from_timetable(self, target_date):
        """Materialise op.session rows for `target_date` from the
        recurring `bxi.timetable.line` weekly schedule, so date-specific
        attendance (and the "today's periods" / "missing attendance"
        views) have a concrete period to attach to.

        Idempotent per (timetable_line_id, session_date) — safe to
        re-run for a date that already has some or all of its sessions.
        Lines without both a Subject and a Teacher are skipped: those
        are required on op.session and an unfilled slot in the
        timetable isn't a real class yet.
        """
        weekday = target_date.strftime('%A').lower()
        lines = self.env['bxi.timetable.line'].search([('day', '=', weekday)])
        if not lines:
            return self.browse()
        existing = self.search([
            ('timetable_line_id', 'in', lines.ids),
            ('session_date', '=', target_date),
        ])
        existing_line_ids = set(existing.timetable_line_id.ids)
        vals_list = []
        for line in lines:
            if line.id in existing_line_ids:
                continue
            if not (line.subject_id and line.teacher_id):
                continue
            start, end = line.timing_id._to_datetime(target_date)
            vals_list.append({
                'timetable_line_id': line.id,
                'course_id': line.timetable_id.course_id.id,
                'batch_id': line.timetable_id.batch_id.id,
                'subject_id': line.subject_id.id,
                'faculty_id': line.teacher_id.id,
                'timing_id': line.timing_id.id,
                'start_datetime': start,
                'end_datetime': end,
                'state': 'confirm',
            })
        if not vals_list:
            return self.browse()
        return self.with_context(no_calendar_sync=True, dont_notify=True).create(vals_list)

    @api.model
    def _cron_generate_today_sessions(self):
        self._generate_from_timetable(fields.Date.context_today(self))
