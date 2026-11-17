# -*- coding: utf-8 -*-
"""Give media without a genre the genre "General".

op.media.genre_id is required, but media created before that (prod had 6,
and no genre at all) left the column NULL. Odoo then could not add the
NOT NULL constraint ("Missing not-null constraint on op.media.genre_id"
on every start), and those books could not be saved without first
creating a genre. Runs before the schema update so the constraint is
added in the same upgrade.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT count(*) FROM op_media WHERE genre_id IS NULL")
    missing = cr.fetchone()[0]
    if not missing:
        return
    cr.execute("SELECT id FROM op_media_genre WHERE name = 'General'")
    row = cr.fetchone()
    if row:
        genre_id = row[0]
    else:
        cr.execute("""
            INSERT INTO op_media_genre (name, create_uid, write_uid, create_date, write_date)
            VALUES ('General', 1, 1, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC')
            RETURNING id
        """)
        genre_id = cr.fetchone()[0]
    cr.execute("UPDATE op_media SET genre_id = %s WHERE genre_id IS NULL", (genre_id,))
    _logger.info('Library: set genre "General" on %s media that had none', missing)
