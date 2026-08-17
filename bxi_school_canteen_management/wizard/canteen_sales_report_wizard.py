from odoo import fields, models


class CanteenSalesReportWizard(models.TransientModel):
    _name = 'bxi.canteen.sales.report.wizard'
    _description = 'Canteen Daily Sales Report'

    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    state_filter = fields.Selection([
        ('all', 'All'),
        ('served', 'Served Only'),
        ('cancelled', 'Cancelled Only'),
    ], default='all', required=True)

    def sales_report(self):
        domain = [
            ('order_datetime', '>=', self.date_from),
            ('order_datetime', '<=', self.date_to),
        ]
        if self.state_filter != 'all':
            domain.append(('state', '=', self.state_filter))
        orders = self.env['bxi.canteen.order'].search(domain, order='order_datetime')

        all_data = [{
            'name': order.name,
            'order_datetime': order.order_datetime.strftime('%m/%d/%Y %I:%M %p'),
            'patron_name': order.patron_name,
            'patron_type': dict(order._fields['patron_type'].selection).get(order.patron_type),
            'total_amount': order.total_amount,
            'state': dict(order._fields['state'].selection).get(order.state),
        } for order in orders]

        datas = {
            'all_data': all_data,
            'from_date': self.date_from,
            'to_date': self.date_to,
            'grand_total': sum(orders.mapped('total_amount')),
        }
        return self.env.ref('bxi_school_canteen_management.action_report_canteen_sales').report_action(self, data=datas)
