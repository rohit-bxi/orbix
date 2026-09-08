def migrate(cr, version):
    # Fresh installs have neither old column - nothing to backfill.
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'bxi_ptm_meeting' AND column_name IN ('date', 'time')
    """)
    if len(cr.fetchall()) < 2:
        return

    cr.execute("ALTER TABLE bxi_ptm_meeting ADD COLUMN IF NOT EXISTS start_datetime timestamp")
    cr.execute("ALTER TABLE bxi_ptm_meeting ADD COLUMN IF NOT EXISTS end_datetime timestamp")
    # time is stored as float hours (e.g. 10.5 = 10:30); end defaults to
    # start + 1h, matching the fixed duration action_convert_to_event already
    # assumed before this change.
    cr.execute("""
        UPDATE bxi_ptm_meeting
        SET start_datetime = date + (time || ' hours')::interval,
            end_datetime   = date + (time || ' hours')::interval + interval '1 hour'
        WHERE start_datetime IS NULL AND date IS NOT NULL
    """)
