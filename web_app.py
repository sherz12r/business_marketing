"""Responsive web dashboard for cPanel/Passenger and local use."""

from __future__ import annotations

import hmac
import json
from contextlib import closing
import os
import signal
import sqlite3
import subprocess
import sys
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from app_paths import get_app_dir
from campaign import campaign_stats, load_location_catalog, seed_target_areas
from process_utils import process_running
from progress_tracker import (
    EVENT_EMAIL_SENT,
    EVENT_FORM_PREFILLED,
    EVENT_WEBSITE_OPENED,
    EVENT_WHATSAPP_SENT,
    ensure_database,
    outreach_stats,
)

APP_DIR = Path(get_app_dir())
CONFIG_PATH = APP_DIR / "config.json"
RUNTIME_DIR = APP_DIR / "data" / "runtime"
STATE_PATH = RUNTIME_DIR / "web_job.json"
LOG_PATH = RUNTIME_DIR / "web_job.log"

app = Flask(__name__)


@app.after_request
def disable_api_cache(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def load_config():
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(config):
    """Persist dashboard settings without leaving a partially written JSON file."""
    temporary = CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=4) + "\n", encoding="utf-8")
    temporary.replace(CONFIG_PATH)


def data_dir():
    path = Path(load_config().get("data_dir", "data"))
    return path if path.is_absolute() else APP_DIR / path


def authenticated():
    expected_user = os.environ.get("DASHBOARD_USERNAME", "admin")
    expected_password = os.environ.get("DASHBOARD_PASSWORD", "")
    if not expected_password and request.remote_addr in {"127.0.0.1", "::1"}:
        return True
    auth = request.authorization
    return bool(
        expected_password
        and auth
        and hmac.compare_digest(auth.username or "", expected_user)
        and hmac.compare_digest(auth.password or "", expected_password)
    )


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if authenticated():
            return view(*args, **kwargs)
        if not os.environ.get("DASHBOARD_PASSWORD"):
            return Response(
                "Remote access requires the DASHBOARD_PASSWORD environment variable.",
                status=503,
            )
        return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="Marketing Bot"'})

    return wrapped


def read_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(state):
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)


def job_status():
    state = read_state()
    running = process_running(state.get("pid"))
    if state and not running and state.get("status") == "running":
        state["status"] = "finished"
        state["finished_at"] = datetime.now().isoformat(timespec="seconds")
        write_state(state)
    state["running"] = running
    return state


def database():
    target = data_dir() / "outreach.sqlite3"
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(target))
    connection.row_factory = sqlite3.Row
    ensure_database(connection)
    return connection


@app.get("/")
@require_auth
def index():
    return render_template("dashboard.html")


@app.get("/api/dashboard")
@require_auth
def dashboard_data():
    with closing(database()) as connection:
        config = load_config()
        campaign_config = config.get("campaign", {})
        if isinstance(campaign_config, dict) and campaign_config.get("enabled"):
            try:
                catalog_path = Path(campaign_config.get("locations_file", "locations/uae.json"))
                if not catalog_path.is_absolute():
                    catalog_path = APP_DIR / catalog_path
                seed_target_areas(
                    connection,
                    load_location_catalog(
                        catalog_path,
                        country=str(campaign_config.get("country", "")),
                    ),
                )
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        rows = connection.execute(
            """SELECT o.*, t.country area_country, t.region area_region,
                t.city area_city, t.area area_name,
                MAX(CASE WHEN e.event_type = ? THEN e.created_at END) email_sent_at,
                MAX(CASE WHEN e.event_type = ? THEN e.created_at END) whatsapp_sent_at
               FROM outreach o LEFT JOIN outreach_events e ON e.business_key=o.business_key
               LEFT JOIN target_areas t ON t.area_key=o.area_key
              GROUP BY o.business_key ORDER BY COALESCE(o.updated_at, '') DESC LIMIT 250""",
            (EVENT_EMAIL_SENT, EVENT_WHATSAPP_SENT),
        ).fetchall()
        totals, run = outreach_stats(connection)
        campaign = campaign_stats(connection)
        areas = [dict(row) for row in connection.execute(
            """SELECT position,country,region,city,area,status,businesses_found,
                      businesses_processed,messages_sent,last_error
               FROM target_areas ORDER BY country,position,area_key"""
        ).fetchall()]

    leads = []
    for row in rows:
        leads.append({
            "key": row["business_key"],
            "name": row["business_name"] or "Unnamed business",
            "website": row["website"] or "",
            "emails": parse_list(row["emails"]),
            "phones": parse_list(row["phones"]),
            "status": row["status"] or "draft_ready",
            "channel_status": json.loads(row["channel_status"] or "{}"),
            "form_prefilled": bool(row["form_prefilled"]),
            "last_error": row["last_error"] or "",
            "updated": row["updated_at"] or "",
            "country": row["area_country"] or "",
            "region": row["area_region"] or "",
            "city": row["area_city"] or "",
            "area": row["area_name"] or "",
            "email_sent": bool(row["email_sent_at"]) or row["status"] in {"email_sent", "fallback_sent"},
            "whatsapp_sent": bool(row["whatsapp_sent_at"]) or row["status"] in {"whatsapp_sent", "fallback_sent"},
        })
    stats = {**totals, "leads": totals['businesses']}
    return jsonify({"stats": stats, "run": run, "campaign": campaign, "areas": areas,
                    "leads": leads, "job": job_status()})



@app.get("/api/settings")
@require_auth
def get_settings():
    return jsonify(load_config())


@app.put("/api/settings")
@require_auth
def update_settings():
    config = request.get_json(silent=True)
    if not isinstance(config, dict):
        return jsonify({"error": "Settings must be a JSON object."}), 400
    try:
        save_config(config)
    except OSError as exc:
        return jsonify({"error": f"Could not save config.json: {exc}"}), 500
    return jsonify({"ok": True})


def parse_list(value):
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return [part.strip() for part in str(value or "").split(";") if part.strip()]


@app.post("/api/jobs/start")
@require_auth
def start_job():
    current = job_status()
    if current.get("running"):
        return jsonify({"error": "An automation job is already running."}), 409

    mode = (request.get_json(silent=True) or {}).get("mode", "full")
    arguments = {
        "full": [],
        "pending-email": ["--pending-email"],
        "pending-whatsapp": ["--pending-whatsapp"],
    }
    if mode not in arguments:
        return jsonify({"error": "Unknown automation mode."}), 400

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = LOG_PATH.open("w", encoding="utf-8", buffering=1)
    command = [sys.executable, "-u", str(APP_DIR / "main.py"), *arguments[mode]]
    options = {
        "cwd": str(APP_DIR),
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
        # Browser visibility follows the headless value in config.json.
        "env": {**os.environ},
    }
    if os.name != "nt":
        options["start_new_session"] = True
    process = subprocess.Popen(command, **options)
    log_handle.close()
    state = {
        "pid": process.pid,
        "mode": mode,
        "status": "running",
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_state(state)
    return jsonify({**state, "running": True}), 202


@app.post("/api/jobs/stop")
@require_auth
def stop_job():
    state = job_status()
    pid = state.get("pid")
    if not state.get("running") or not pid:
        return jsonify({"error": "No dashboard automation is running."}), 409
    try:
        if os.name == "nt":
            os.kill(pid, signal.SIGTERM)
        else:
            os.killpg(pid, signal.SIGTERM)
        state.update(status="stopping", stopped_at=datetime.now().isoformat(timespec="seconds"))
        write_state(state)
        return jsonify({"ok": True})
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/jobs/log")
@require_auth
def job_log():
    log_path = LOG_PATH
    # Direct main.py runs write to the daily log instead of web_job.log.
    if not job_status().get("running"):
        daily_log = APP_DIR / "logs" / f"Marketing_{datetime.now():%Y-%m-%d}.log"
        if daily_log.exists():
            log_path = daily_log
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return jsonify({
            "lines": lines[-500:],
            "job": job_status(),
            "updated": log_path.stat().st_mtime_ns,
        })
    except OSError:
        return jsonify({"lines": [], "job": job_status()})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), debug=False)
