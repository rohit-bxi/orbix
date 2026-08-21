CODE_BY_XML_ID = {
    'certificate_type_transfer': 'TC',
    'certificate_type_completion': 'CC',
    'certificate_type_merit': 'MRT',
    'certificate_type_conduct': 'CDT',
    'certificate_type_participation': 'PTC',
}


def migrate(cr, version):
    # Runs before this module's own models are registered, so query the
    # tables directly instead of going through the ORM.
    for xml_id, code in CODE_BY_XML_ID.items():
        cr.execute(
            "SELECT 1 FROM ir_model_data WHERE module = %s AND name = %s",
            ('bxi_certificate_management', xml_id),
        )
        if cr.fetchone():
            continue
        cr.execute("SELECT id FROM op_certificate_type WHERE code = %s LIMIT 1", (code,))
        row = cr.fetchone()
        if row:
            cr.execute(
                "INSERT INTO ir_model_data (name, module, model, res_id, noupdate) "
                "VALUES (%s, %s, %s, %s, %s)",
                (xml_id, 'bxi_certificate_management', 'op.certificate.type', row[0], False),
            )
