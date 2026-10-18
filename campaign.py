"""Location-campaign catalog loading and persistent area queue helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


def area_key(country: str, region: str, city: str, area: str) -> str:
    value = "|".join(
        str(item or "").strip().casefold()
        for item in (country, region, city, area)
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_location_catalog(path: Path, country: str = "") -> list[dict]:
    """Flatten a country/region/city JSON catalog into ordered search areas."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    catalog_country = str(raw.get("country") or country or "").strip()
    if not catalog_country:
        raise ValueError("Location catalog must define a country")

    locations = []
    position = 0
    for region_item in raw.get("regions", []):
        region = str(region_item.get("name") or "").strip()
        for city_item in region_item.get("cities", []):
            city = str(city_item.get("name") or "").strip()
            areas = city_item.get("areas") or [city]
            for item in areas:
                area = str(item or "").strip()
                if not area:
                    continue
                position += 1
                locations.append({
                    "area_key": area_key(catalog_country, region, city, area),
                    "country": catalog_country,
                    "region": region,
                    "city": city,
                    "area": area,
                    "position": position,
                })
    if not locations:
        raise ValueError(f"Location catalog contains no areas: {path}")
    return locations


def seed_target_areas(connection, locations: list[dict]) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    before = connection.total_changes
    connection.executemany(
        """INSERT OR IGNORE INTO target_areas (
            area_key,country,region,city,area,position,status,updated_at
        ) VALUES (?,?,?,?,?,?, 'pending', ?)""",
        [
            (
                item["area_key"], item["country"], item["region"],
                item["city"], item["area"], item["position"], now,
            )
            for item in locations
        ],
    )
    connection.commit()
    return connection.total_changes - before


def next_target_area(connection):
    return connection.execute(
        """SELECT * FROM target_areas
           WHERE status IN ('pending','in_progress','blocked')
           ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'blocked' THEN 1 ELSE 2 END,
                    position, area_key
           LIMIT 1"""
    ).fetchone()


def campaign_stats(connection) -> dict:
    counts = dict(connection.execute(
        "SELECT status,COUNT(*) FROM target_areas GROUP BY status"
    ).fetchall())
    total = sum(counts.values())
    sent = connection.execute(
        """SELECT COUNT(*) FROM outreach_events
           WHERE area_key<>'' AND event_type IN ('whatsapp_sent','email_sent')"""
    ).fetchone()[0]
    current = connection.execute(
        """SELECT country,region,city,area,status,businesses_found,
                  businesses_processed,messages_sent,last_error
           FROM target_areas
           WHERE status IN ('in_progress','blocked')
           ORDER BY updated_at DESC LIMIT 1"""
    ).fetchone()
    return {
        "total": total,
        "pending": counts.get("pending", 0),
        "in_progress": counts.get("in_progress", 0),
        "completed": counts.get("completed", 0),
        "blocked": counts.get("blocked", 0),
        "messages_sent": sent,
        "current": dict(current) if current else None,
    }
