import base64

from odoo import _, fields, http
from odoo.addons.portal.controllers import portal
from odoo.exceptions import MissingError
from odoo.http import content_disposition, request


class CertificateVerifyController(http.Controller):

    @http.route('/certificate/verify/<string:code>', type='http', auth='public', website=True, sitemap=False)
    def certificate_verify(self, code, **kw):
        certificate = request.env['op.certificate'].sudo().search(
            [('verification_code', '=', code)], limit=1)
        today = fields.Date.context_today(request.env['op.certificate'])
        status = 'not_found'
        if certificate:
            if certificate.state == 'revoked':
                status = 'revoked'
            elif certificate.state == 'expired' or (certificate.expiry_date and certificate.expiry_date < today):
                status = 'expired'
            elif certificate.state == 'issued':
                status = 'valid'
        return request.render('bxi_certificate_management.certificate_verify_page', {
            'certificate': certificate,
            'status': status,
        })


class CustomerPortal(portal.CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'certificate_count' in counters:
            values['certificate_count'] = request.env['op.certificate'].search_count(
                [('student_id.user_id', '=', request.env.user.id), ('state', '=', 'issued')])
        return values

    @http.route('/my/certificates', type='http', auth='user', website=True)
    def portal_my_certificates(self, **kw):
        certificates = request.env['op.certificate'].search(
            [('student_id.user_id', '=', request.env.user.id), ('state', '=', 'issued')],
            order='issue_date desc')
        return request.render('bxi_certificate_management.portal_my_certificates', {
            'certificates': certificates,
            'page_name': 'certificate',
        })

    @http.route('/my/certificates/<int:certificate_id>/download', type='http', auth='user')
    def portal_certificate_download(self, certificate_id, **kw):
        certificate = request.env['op.certificate'].search([
            ('id', '=', certificate_id),
            ('student_id.user_id', '=', request.env.user.id),
            ('state', '=', 'issued'),
        ], limit=1)
        if not certificate or not certificate.attachment_id:
            raise MissingError(_("This certificate is not available."))
        attachment = certificate.attachment_id.sudo()
        return request.make_response(
            base64.b64decode(attachment.datas),
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', content_disposition(attachment.name)),
            ])
