"""Small persistence helpers for dashboard progress events."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional, Union


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
    connection.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_outreach_events_once_per_business_type
           ON outreach_events(business_key, event_type)
           WHERE business_key IS NOT NULL AND business_key != ''"""
    )
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
) -> bool:
    """Record a single progress event. Returns True when a new row is added."""

    result = result or {}
    ensure_progress_schema(connection)
    cursor = connection.execute(
        """INSERT OR IGNORE INTO outreach_events (
            business_key, business_name, website, event_type, details, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)""",
        (
            business_key or "",
            str(result.get("name") or result.get("business_name") or ""),
            str(result.get("website") or ""),
            event_type,
            details,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    connection.commit()
    return cursor.rowcount > 0
