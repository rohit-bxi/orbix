# -*- coding: utf-8 -*-
# Copyright (c) 2026 BXI Technology Pvt. Ltd. All Rights Reserved.
# License OPL-1 (Odoo Proprietary License v1.0, see LICENSE file for full text).
"""Status emails to a student's family (refunds, fee exemptions). There is
no SMS provider yet, so "SMS notification" ticks are delivered by email."""
import logging

from markupsafe import Markup, escape

from odoo import _, models

_logger = logging.getLogger(__name__)


class BxiFamilyMailMixin(models.AbstractModel):
    _name = 'bxi.family.mail.mixin'
    _description = 'Email the Student Family'

    def _bxi_family_emails(self):
        """The chosen parent's email, else every parent's of the student,
        else the student's own."""
        self.ensure_one()
        parents = self.parent_id or self.student_id.parent_ids
        emails = [(p.name.email or '').strip() for p in parents.sudo()]
        emails = [e for e in emails if e]
        if not emails and self.student_id.sudo().partner_id.email:
            emails = [self.student_id.sudo().partner_id.email.strip()]
        return list(dict.fromkeys(emails))

    def _bxi_email_family(self, subject, intro, rows=(), note=None):
        """Queue one email to the family: `intro` paragraph, then a table
        of (label, value) `rows` and an optional `note`. A note on the
        record says who it went to. Returns True when it was queued."""
        self.ensure_one()
        emails = self._bxi_family_emails()
        if not emails:
            self.message_post(body=_('No email sent: the student and parents have no email address.'))
            return False
        company = self.company_id or self.env.company
        body = Markup('<div style="font-family: Arial, sans-serif; font-size: 14px;">'
                      '<p>Dear Parent/Guardian,</p><p>%s</p>') % intro
        if rows:
            body += Markup('<table style="border-collapse: collapse;">')
            for label, value in rows:
                if value in (None, False, ''):
                    continue
                body += Markup('<tr><td style="padding: 2px 12px 2px 0; color: #555;">%s</td>'
                               '<td style="padding: 2px 0;"><strong>%s</strong></td></tr>') % (label, value)
            body += Markup('</table>')
        if note:
            body += Markup('<p>%s</p>') % Markup('<br/>').join(escape(line) for line in str(note).splitlines())
        body += Markup('<p>Regards,<br/>%s</p></div>') % (company.name or '')
        email_from = company.email_formatted or self.env['ir.mail_server'].sudo()._get_default_from_address() \
            or self.env.user.email_formatted or False
        self.env['mail.mail'].sudo().create({
            'subject': subject,
            'email_to': ','.join(emails),
            'email_from': email_from,
            'body_html': body,
            'model': self._name,
            'res_id': self.id,
            'auto_delete': True,
        })
        self.message_post(body=_('Email "%(subject)s" sent to %(to)s.', subject=subject, to=', '.join(emails)))
        return True
