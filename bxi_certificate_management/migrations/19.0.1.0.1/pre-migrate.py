from odoo import api, SUPERUSER_ID

CODE_BY_XML_ID = {
    'certificate_type_transfer': 'TC',
    'certificate_type_completion': 'CC',
    'certificate_type_merit': 'MRT',
    'certificate_type_conduct': 'CDT',
    'certificate_type_participation': 'PTC',
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    data_model = env['ir.model.data']
    type_model = env['op.certificate.type']

    for xml_id, code in CODE_BY_XML_ID.items():
        if data_model.search_count([('module', '=', 'bxi_certificate_management'), ('name', '=', xml_id)]):
            continue
        existing = type_model.search([('code', '=', code)], limit=1)
        if existing:
            data_model.create({
                'module': 'bxi_certificate_management',
                'name': xml_id,
                'model': 'op.certificate.type',
                'res_id': existing.id,
            })
