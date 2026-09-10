"""Small persistence helpers for dashboard progress events."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional, Union
from process_utils import process_running


EVENT_WEBSITE_OPENED = "website_opened"
EVENT_FORM_PREFILLED = "form_prefilled"
EVENT_EMAIL_SENT = "email_sent"
EVENT_WHATSAPP_SENT = "whatsapp_sent"


def database_path(data_dir: Union[str, Path] = "data") -> Path:
    return Path(data_dir) / "outreach.sqlite3"


def ensure_outreach_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS outreach (
            business_key TEXT PRIMARY KEY,
            business_name TEXT,
            website TEXT,
            contact_page TEXT,
            emails TEXT,
            phones TEXT,
            proposal TEXT,
            form_prefilled INTEGER DEFAULT 0,
            status TEXT,
            updated_at TEXT
        )"""
    )
    columns = {row[1] for row in connection.execute('PRAGMA table_info(outreach)')}
    for name in ('channel_status', 'whatsapp_phones', 'last_error'):
        if name not in columns:
            connection.execute(f"ALTER TABLE outreach ADD COLUMN {name} TEXT DEFAULT ''")
    connection.commit()


def ensure_progress_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS outreach_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_key TEXT,
            business_name TEXT,
            website TEXT,
            event_type TEXT NOT NULL,
            details TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_outreach_events_type
           ON outreach_events(event_type, created_at)"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_outreach_events_business
           ON outreach_events(business_key, created_at)"""
    )
    # Repeat outreach can be allowed after the configured cooldown, so event
    # history must retain each later send rather than enforcing one event ever.
    connection.execute("DROP INDEX IF EXISTS idx_outreach_events_once_per_business_type")
    columns = {row[1] for row in connection.execute('PRAGMA table_info(outreach_events)')}
    for name, declaration in [('run_id', 'INTEGER'), ('recipient', "TEXT DEFAULT ''")]:
        if name not in columns:
            connection.execute(f'ALTER TABLE outreach_events ADD COLUMN {name} {declaration}')
    connection.execute('''CREATE TABLE IF NOT EXISTS outreach_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT, search_query TEXT,
        target INTEGER, started_at TEXT, finished_at TEXT, status TEXT,
        stop_reason TEXT DEFAULT '', pages INTEGER DEFAULT 0)''')
    connection.execute('''CREATE TABLE IF NOT EXISTS run_businesses (
        run_id INTEGER, business_key TEXT, is_new INTEGER, already_contacted INTEGER,
        processed INTEGER DEFAULT 0, status TEXT DEFAULT 'discovered',
        PRIMARY KEY (run_id, business_key))''')
    if 'pid' not in {row[1] for row in connection.execute('PRAGMA table_info(outreach_runs)')}:
        connection.execute('ALTER TABLE outreach_runs ADD COLUMN pid INTEGER')
    connection.commit()


def ensure_database(connection: sqlite3.Connection) -> None:
    ensure_outreach_schema(connection)
    ensure_progress_schema(connection)


def record_event(
    connection: sqlite3.Connection,
    event_type: str,
    business_key: str = "",
    result: Optional[Mapping[str, object]] = None,
    details: str = "",
    run_id: Optional[int] = None,
    recipient: str = "",
) -> bool:
    """Record a single progress event. Returns True when a new row is added."""

    result = result or {}
    ensure_progress_schema(connection)
    cursor = connection.execute(
        """INSERT INTO outreach_events (
            business_key, business_name, website, event_type, details, created_at, run_id, recipient
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            business_key or "",
            str(result.get("name") or result.get("business_name") or ""),
            str(result.get("website") or ""),
            event_type,
            details,
            datetime.now().isoformat(timespec="seconds"),
            run_id if run_id is not None else result.get('run_id'),
            recipient,
        ),
    )
    connection.commit()
    return cursor.rowcount > 0


def outreach_stats(connection):
    """One source of truth for both dashboards; totals never use a UI row limit."""
    rows = connection.execute('SELECT business_key, status, form_prefilled, emails, phones FROM outreach').fetchall()
    events = connection.execute('SELECT business_key, event_type, COUNT(*) FROM outreach_events GROUP BY business_key, event_type').fetchall()
    by_business = {}
    totals = {}
    for key, event, count in events:
        by_business.setdefault(key, {})[event] = count
        totals[event] = totals.get(event, 0) + count
    contacted = contacts = drafts = 0
    for key, status, form, emails, phones in rows:
        history = by_business.get(key, {})
        email = bool(history.get(EVENT_EMAIL_SENT)) or status in {'email_sent', 'fallback_sent'}
        whatsapp = bool(history.get(EVENT_WHATSAPP_SENT)) or status in {'whatsapp_sent', 'fallback_sent'}
        contacted += int(email or whatsapp or status in {'submitted', 'sent'})
        for event, legacy in [(EVENT_EMAIL_SENT, email), (EVENT_WHATSAPP_SENT, whatsapp), (EVENT_FORM_PREFILLED, form)]:
            if legacy and not history.get(event):
                totals[event] = totals.get(event, 0) + 1
        contacts += int(any(value and value not in ('[]', 'null') for value in (emails, phones)))
        drafts += int(status == 'draft_ready')
    stats = dict(businesses=len(rows), contacted=contacted, pending=len(rows)-contacted,
                 websites=totals.get(EVENT_WEBSITE_OPENED, 0), forms=totals.get(EVENT_FORM_PREFILLED, 0),
                 emails=totals.get(EVENT_EMAIL_SENT, 0), whatsapp=totals.get(EVENT_WHATSAPP_SENT, 0),
                 contacts=contacts, drafts=drafts)
    cursor = connection.execute('SELECT * FROM outreach_runs ORDER BY id DESC LIMIT 1')
    raw = cursor.fetchone()
    run = dict(zip([col[0] for col in cursor.description], raw)) if raw else {}
    if run:
        if run['status'] == 'running' and run.get('pid') and not process_running(run['pid']):
            run.update(status='interrupted', stop_reason='Automation stopped before the run completed')
        counts = connection.execute('''SELECT COUNT(*), COALESCE(SUM(is_new),0),
            COALESCE(SUM(already_contacted),0), COALESCE(SUM(processed),0),
            COALESCE(SUM(status='skipped_duplicate'),0),
            COALESCE(SUM(status IN ('error','website_error','draft_error')),0)
            FROM run_businesses WHERE run_id=?''', (run['id'],)).fetchone()
        run.update(dict(zip(('found','new','already_contacted','processed','skipped','failed'), counts)))
        run_events = dict(connection.execute('SELECT event_type, COUNT(*) FROM outreach_events WHERE run_id=? GROUP BY event_type', (run['id'],)).fetchall())
        run.update(websites=run_events.get(EVENT_WEBSITE_OPENED,0), forms=run_events.get(EVENT_FORM_PREFILLED,0),
                   emails=run_events.get(EVENT_EMAIL_SENT,0), whatsapp=run_events.get(EVENT_WHATSAPP_SENT,0))
    return stats, run
