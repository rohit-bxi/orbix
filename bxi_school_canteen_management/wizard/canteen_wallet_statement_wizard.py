from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class CanteenWalletStatementWizard(models.TransientModel):
    _name = 'bxi.canteen.wallet.statement.wizard'
    _description = 'Canteen Wallet Statement'

    patron_type = fields.Selection([
        ('student', 'Student'),
        ('faculty', 'Teacher'),
    ], required=True, default='student')
    student_id = fields.Many2one('op.student')
    faculty_id = fields.Many2one('op.faculty')
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)

    def statement_report(self):
        self.ensure_one()
        patron = self.student_id if self.patron_type == 'student' else self.faculty_id
        if not patron:
            raise ValidationError(_('Please select a patron.'))
        wallet = patron.wallet_ids[:1]

        opening_balance = 0.0
        rows = []
        if wallet:
            opening_txns = self.env['bxi.canteen.wallet.transaction'].search([
                ('wallet_id', '=', wallet.id),
                ('state', '=', 'posted'),
                ('date', '<', self.date_from),
            ])
            opening_balance = sum(opening_txns.mapped('amount'))

            period_txns = self.env['bxi.canteen.wallet.transaction'].search([
                ('wallet_id', '=', wallet.id),
                ('state', '=', 'posted'),
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
            ], order='date')

            running = opening_balance
            for txn in period_txns:
                running += txn.amount
                rows.append({
                    'date': txn.date.strftime('%m/%d/%Y %I:%M %p'),
                    'transaction_type': dict(txn._fields['transaction_type'].selection).get(txn.transaction_type),
                    'amount': txn.amount,
                    'running_balance': running,
                    'note': txn.note or '',
                })

        datas = {
            'patron_name': patron.name,
            'from_date': self.date_from,
            'to_date': self.date_to,
            'opening_balance': opening_balance,
            'closing_balance': rows[-1]['running_balance'] if rows else opening_balance,
            'all_data': rows,
        }
        return self.env.ref('bxi_school_canteen_management.action_report_canteen_wallet_statement').report_action(self, data=datas)
