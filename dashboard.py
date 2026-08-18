from __future__ import annotations

import json
import os
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import quote_plus, urlparse
import tkinter as tk

from app_paths import get_app_dir
from progress_tracker import (
    EVENT_EMAIL_SENT,
    EVENT_FORM_PREFILLED,
    EVENT_WEBSITE_OPENED,
    EVENT_WHATSAPP_SENT,
    ensure_database,
    record_event,
)


APP_DIR = Path(get_app_dir())
CONFIG_PATH = APP_DIR / "config.json"
LOG_DIR = APP_DIR / "logs"

COLORS = {
    "bg": "#0b1020",
    "panel": "#11182a",
    "panel_2": "#162033",
    "panel_3": "#1b2940",
    "line": "#26344f",
    "text": "#edf4ff",
    "muted": "#94a3b8",
    "accent": "#2dd4bf",
    "accent_2": "#38bdf8",
    "warning": "#fbbf24",
    "danger": "#fb7185",
    "good": "#86efac",
    "white": "#ffffff",
}


def read_json(path):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def parse_json_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass
    parts = re.split(r";|,", text)
    return [part.strip() for part in parts if part.strip()]


def shorten(value, limit=56):
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def join_short(items, limit=2):
    items = [str(item).strip() for item in items if str(item).strip()]
    if not items:
        return "-"
    visible = items[:limit]
    suffix = "" if len(items) <= limit else f" +{len(items) - limit}"
    return shorten("; ".join(visible), 52) + suffix


def domain_from_url(url):
    try:
        host = urlparse(url).netloc
        return host.removeprefix("www.") or url
    except Exception:
        return url or "Untitled lead"


def open_path(path):
    path = Path(path)
    if not path.exists():
        messagebox.showinfo("Not found", f"{path.name} does not exist yet.")
        return
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        webbrowser.open(path.resolve().as_uri())


class MarketingDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Marketing Bot Dashboard")
        self.geometry("1260x820")
        self.minsize(1080, 700)
        self.configure(bg=COLORS["bg"])

        self.config_data = {}
        self.rows = []
        self.row_by_key = {}
        self.process = None
        self.output_queue = queue.Queue()

        self.status_var = tk.StringVar(value="Ready")
        self.config_summary_var = tk.StringVar(value="")
        self.search_var = tk.StringVar(value="")
        self.selected_title_var = tk.StringVar(value="Select a lead")
        self.selected_meta_var = tk.StringVar(value="Choose a row to review actions.")
        self.progress_text_var = tk.StringVar(value="0 of 0 target leads")
        self.progress_value = tk.DoubleVar(value=0)
        self.stat_vars = {}

        self.configure_styles()
        self.build_layout()
        self.search_var.trace_add("write", lambda *_: self.apply_filter())

        self.load_data()
        self.load_recent_log_file()
        self.after(250, self.poll_process_output)
        self.after(3000, self.auto_refresh)

    def configure_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Dashboard.Treeview",
            background=COLORS["panel"],
            fieldbackground=COLORS["panel"],
            foreground=COLORS["text"],
            borderwidth=0,
            rowheight=32,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Dashboard.Treeview.Heading",
            background=COLORS["panel_3"],
            foreground=COLORS["muted"],
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Dashboard.Treeview",
            background=[("selected", COLORS["accent_2"])],
            foreground=[("selected", COLORS["bg"])],
        )
        style.configure(
            "Dashboard.Horizontal.TProgressbar",
            troughcolor=COLORS["panel_3"],
            background=COLORS["accent"],
            bordercolor=COLORS["panel_3"],
            lightcolor=COLORS["accent"],
            darkcolor=COLORS["accent"],
            thickness=12,
        )

    def build_layout(self):
        shell = tk.Frame(self, bg=COLORS["bg"], padx=22, pady=18)
        shell.pack(fill="both", expand=True)

        self.build_header(shell)
        self.build_stats(shell)
        self.build_body(shell)

    def build_header(self, parent):
        header = tk.Frame(parent, bg=COLORS["bg"])
        header.pack(fill="x", pady=(0, 16))
        header.grid_columnconfigure(0, weight=1)

        title_stack = tk.Frame(header, bg=COLORS["bg"])
        title_stack.grid(row=0, column=0, sticky="ew")

        tk.Label(
            title_stack,
            text="Marketing Bot Dashboard",
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 24, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_stack,
            textvariable=self.config_summary_var,
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        actions = tk.Frame(header, bg=COLORS["bg"])
        actions.grid(row=0, column=1, sticky="e")

        self.run_button = self.make_button(actions, "Run Bot", self.start_bot, COLORS["accent"])
        self.run_button.pack(side="left", padx=(0, 8))
        self.finish_button = self.make_button(actions, "Finish Review", self.finish_review, COLORS["warning"])
        self.finish_button.pack(side="left", padx=(0, 8))
        self.stop_button = self.make_button(actions, "Stop", self.stop_bot, COLORS["danger"])
        self.stop_button.pack(side="left", padx=(0, 8))
        self.refresh_button = self.make_button(actions, "Refresh", self.load_data, COLORS["panel_3"])
        self.refresh_button.pack(side="left")

        self.status_label = tk.Label(
            header,
            textvariable=self.status_var,
            bg=COLORS["panel"],
            fg=COLORS["accent"],
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=6,
        )
        self.status_label.grid(row=1, column=1, sticky="e", pady=(10, 0))

    def build_stats(self, parent):
        stats = tk.Frame(parent, bg=COLORS["bg"])
        stats.pack(fill="x", pady=(0, 16))
        cards = [
            ("websites_opened", "Websites Opened", COLORS["accent"]),
            ("forms_prefilled", "Forms Filled", COLORS["good"]),
            ("emails_sent", "Emails Sent", COLORS["accent_2"]),
            ("whatsapp_sent", "WhatsApp Sent", COLORS["warning"]),
            ("drafts_ready", "Drafts Ready", "#c084fc"),
            ("contacts_found", "Contacts Found", "#fda4af"),
        ]
        for index, (key, label, accent) in enumerate(cards):
            stats.grid_columnconfigure(index, weight=1)
            card = tk.Frame(
                stats,
                bg=COLORS["panel"],
                padx=16,
                pady=14,
                highlightthickness=1,
                highlightbackground=COLORS["line"],
            )
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 8, 0))
            value = tk.StringVar(value="0")
            self.stat_vars[key] = value
            tk.Label(card, text=label, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
            tk.Label(card, textvariable=value, bg=COLORS["panel"], fg=accent, font=("Segoe UI", 24, "bold")).pack(anchor="w", pady=(6, 0))

    def build_body(self, parent):
        body = tk.Frame(parent, bg=COLORS["bg"])
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self.build_table(body)
        self.build_side_panel(body)

    def build_table(self, parent):
        panel = tk.Frame(parent, bg=COLORS["panel"], padx=14, pady=14, highlightthickness=1, highlightbackground=COLORS["line"])
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        panel.grid_rowconfigure(2, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        top = tk.Frame(panel, bg=COLORS["panel"])
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        tk.Label(top, text="Outreach Pipeline", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 15, "bold")).grid(row=0, column=0, sticky="w")
        tk.Button(
            top,
            text="Open Drafts CSV",
            command=self.open_drafts_csv,
            bg=COLORS["panel_3"],
            fg=COLORS["text"],
            relief="flat",
            padx=10,
            pady=5,
            cursor="hand2",
        ).grid(row=0, column=1, sticky="e")

        search = tk.Entry(
            panel,
            textvariable=self.search_var,
            bg=COLORS["panel_2"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            font=("Segoe UI", 10),
        )
        search.grid(row=1, column=0, sticky="ew", pady=(12, 10), ipady=8)
        search.insert(0, "")

        columns = ("business", "website", "emails", "phones", "form", "email", "whatsapp", "status", "updated")
        self.tree = ttk.Treeview(panel, columns=columns, show="headings", style="Dashboard.Treeview")
        headings = {
            "business": ("Business", 170),
            "website": ("Website", 210),
            "emails": ("Emails", 150),
            "phones": ("Phones", 140),
            "form": ("Form", 70),
            "email": ("Email", 78),
            "whatsapp": ("WhatsApp", 90),
            "status": ("Status", 95),
            "updated": ("Updated", 120),
        }
        for column, (label, width) in headings.items():
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=60, stretch=column in {"business", "website"})

        self.tree.grid(row=2, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

    def build_side_panel(self, parent):
        side = tk.Frame(parent, bg=COLORS["bg"])
        side.grid(row=0, column=1, sticky="nsew")
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(3, weight=1)

        selected = self.card(side, row=0)
        tk.Label(selected, textvariable=self.selected_title_var, bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 14, "bold"), wraplength=270, justify="left").pack(anchor="w")
        tk.Label(selected, textvariable=self.selected_meta_var, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=270, justify="left").pack(anchor="w", pady=(8, 12))

        action_grid = tk.Frame(selected, bg=COLORS["panel"])
        action_grid.pack(fill="x")
        self.action_buttons = {
            "website": self.make_button(action_grid, "Open Website", self.open_selected_website, COLORS["panel_3"]),
            "contact": self.make_button(action_grid, "Open Contact", self.open_selected_contact, COLORS["panel_3"]),
            "email": self.make_button(action_grid, "Mark Email Sent", self.mark_email_sent, COLORS["accent_2"]),
            "whatsapp": self.make_button(action_grid, "Open WhatsApp", self.open_whatsapp_review, COLORS["warning"]),
            "whatsapp_sent": self.make_button(action_grid, "Mark WhatsApp Sent", self.mark_whatsapp_sent, COLORS["accent"]),
        }
        for index, button in enumerate(self.action_buttons.values()):
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0 if index % 2 == 0 else 8, 0), pady=(0, 8))
        action_grid.grid_columnconfigure(0, weight=1)
        action_grid.grid_columnconfigure(1, weight=1)

        progress = self.card(side, row=1)
        tk.Label(progress, text="Run Progress", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Progressbar(progress, variable=self.progress_value, maximum=100, style="Dashboard.Horizontal.TProgressbar").pack(fill="x", pady=(12, 8))
        tk.Label(progress, textvariable=self.progress_text_var, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w")

        activity = self.card(side, row=2)
        tk.Label(activity, text="Recent Activity", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 13, "bold")).pack(anchor="w")
        self.activity_text = tk.Text(activity, height=8, bg=COLORS["panel"], fg=COLORS["muted"], insertbackground=COLORS["text"], relief="flat", wrap="word", font=("Segoe UI", 9))
        self.activity_text.pack(fill="both", expand=True, pady=(8, 0))
        self.activity_text.configure(state="disabled")

        logs = self.card(side, row=3)
        tk.Label(logs, text="Live Log", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 13, "bold")).pack(anchor="w")
        self.log_text = tk.Text(logs, bg=COLORS["panel"], fg=COLORS["muted"], insertbackground=COLORS["text"], relief="flat", wrap="word", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text.configure(state="disabled")

    def card(self, parent, row):
        frame = tk.Frame(parent, bg=COLORS["panel"], padx=14, pady=14, highlightthickness=1, highlightbackground=COLORS["line"])
        frame.grid(row=row, column=0, sticky="nsew", pady=(0, 14))
        return frame

    def make_button(self, parent, text, command, color):
        fg = COLORS["bg"] if color in {COLORS["accent"], COLORS["accent_2"], COLORS["warning"], COLORS["good"]} else COLORS["text"]
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=color,
            fg=fg,
            activebackground=color,
            activeforeground=fg,
            relief="flat",
            padx=12,
            pady=8,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )

    def data_dir(self):
        self.config_data = read_json(CONFIG_PATH)
        raw = self.config_data.get("data_dir", "data")
        path = Path(raw)
        if not path.is_absolute():
            path = APP_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def db_path(self):
        return self.data_dir() / "outreach.sqlite3"

    def connect(self):
        connection = sqlite3.connect(str(self.db_path()))
        connection.row_factory = sqlite3.Row
        ensure_database(connection)
        return connection

    def load_data(self):
        try:
            with self.connect() as connection:
                raw_rows = self.fetch_rows(connection)
                self.rows = [self.normalize_row(row) for row in raw_rows]
                self.row_by_key = {row["business_key"]: row for row in self.rows}
                stats = self.fetch_stats(connection, self.rows)
                activity = self.fetch_activity(connection)

            query = self.config_data.get("search_query", "business near me")
            limit = self.config_data.get("limit", 0)
            self.config_summary_var.set(f"Search: {query} | Target: {limit} leads | Data: {self.data_dir().name}")
            self.update_stats(stats)
            self.populate_activity(activity)
            self.apply_filter()
            self.status_var.set("Ready" if not self.is_running() else "Automation running")
        except Exception as exc:
            self.status_var.set(f"Dashboard error: {exc}")

    def fetch_rows(self, connection):
        return connection.execute(
            """SELECT
                o.*,
                MAX(CASE WHEN e.event_type = ? THEN e.created_at END) AS email_sent_at,
                MAX(CASE WHEN e.event_type = ? THEN e.created_at END) AS whatsapp_sent_at
            FROM outreach o
            LEFT JOIN outreach_events e ON e.business_key = o.business_key
            GROUP BY o.business_key
            ORDER BY COALESCE(o.updated_at, '') DESC"""
            ,
            (EVENT_EMAIL_SENT, EVENT_WHATSAPP_SENT),
        ).fetchall()

    def normalize_row(self, row):
        emails = parse_json_list(row["emails"])
        phones = parse_json_list(row["phones"])
        website = row["website"] or ""
        name = row["business_name"] or domain_from_url(website)
        contact_page = row["contact_page"] or ""
        proposal = row["proposal"] or ""
        status = row["status"] or "draft_ready"
        updated_at = row["updated_at"] or ""
        email_sent_at = row["email_sent_at"] or ""
        whatsapp_sent_at = row["whatsapp_sent_at"] or ""
        return {
            "business_key": row["business_key"],
            "business_name": name,
            "website": website,
            "contact_page": contact_page,
            "emails": emails,
            "phones": phones,
            "proposal": proposal,
            "form_prefilled": bool(row["form_prefilled"]),
            "status": status,
            "updated_at": updated_at,
            "email_sent_at": email_sent_at,
            "whatsapp_sent_at": whatsapp_sent_at,
            "haystack": " ".join([name, website, contact_page, " ".join(emails), " ".join(phones), status]).lower(),
        }

    def fetch_stats(self, connection, rows):
        event_counts = {
            row["event_type"]: row["count"]
            for row in connection.execute(
                "SELECT event_type, COUNT(*) AS count FROM outreach_events GROUP BY event_type"
            ).fetchall()
        }
        websites_fallback = sum(1 for row in rows if row["website"])
        forms_fallback = sum(1 for row in rows if row["form_prefilled"])
        email_status_fallback = sum(1 for row in rows if row["status"] in {"sent", "submitted", "email_sent", "fallback_sent"})
        whatsapp_status_fallback = sum(1 for row in rows if row["status"] in {"whatsapp_sent", "fallback_sent"})
        contacts_found = sum(1 for row in rows if row["emails"] or row["phones"])
        drafts_ready = sum(1 for row in rows if row["status"] == "draft_ready")
        limit = max(1, int(self.config_data.get("limit", len(rows) or 1)))
        processed = len(rows)
        return {
            "websites_opened": max(event_counts.get(EVENT_WEBSITE_OPENED, 0), websites_fallback),
            "forms_prefilled": max(event_counts.get(EVENT_FORM_PREFILLED, 0), forms_fallback),
            "emails_sent": max(event_counts.get(EVENT_EMAIL_SENT, 0), email_status_fallback),
            "whatsapp_sent": max(event_counts.get(EVENT_WHATSAPP_SENT, 0), whatsapp_status_fallback),
            "drafts_ready": drafts_ready,
            "contacts_found": contacts_found,
            "processed": processed,
            "limit": limit,
            "progress": min(100, processed / limit * 100),
        }

    def fetch_activity(self, connection):
        return connection.execute(
            """SELECT event_type, business_name, website, created_at
               FROM outreach_events
               ORDER BY created_at DESC
               LIMIT 10"""
        ).fetchall()

    def update_stats(self, stats):
        for key, var in self.stat_vars.items():
            var.set(str(stats.get(key, 0)))
        self.progress_value.set(stats.get("progress", 0))
        self.progress_text_var.set(f"{stats.get('processed', 0)} of {stats.get('limit', 0)} target leads")

    def populate_activity(self, rows):
        labels = {
            EVENT_WEBSITE_OPENED: "Website opened",
            EVENT_FORM_PREFILLED: "Form filled",
            EVENT_EMAIL_SENT: "Email sent",
            EVENT_WHATSAPP_SENT: "WhatsApp sent",
        }
        lines = []
        for row in rows:
            title = row["business_name"] or domain_from_url(row["website"])
            label = labels.get(row["event_type"], row["event_type"])
            created = self.format_time(row["created_at"])
            lines.append(f"{created}  {label}\n{shorten(title, 42)}")
        if not lines:
            lines = ["No progress events yet."]
        self.set_text(self.activity_text, "\n\n".join(lines))

    def apply_filter(self):
        if not hasattr(self, "tree"):
            return
        query = self.search_var.get().strip().lower()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self.rows:
            if query and query not in row["haystack"]:
                continue
            email_state = "Sent" if row["email_sent_at"] else ("Ready" if row["emails"] else "-")
            whatsapp_state = "Sent" if row["whatsapp_sent_at"] else ("Ready" if row["phones"] else "-")
            values = (
                shorten(row["business_name"], 28),
                shorten(row["website"], 38),
                join_short(row["emails"]),
                join_short(row["phones"]),
                "Yes" if row["form_prefilled"] else "No",
                email_state,
                whatsapp_state,
                row["status"],
                self.format_time(row["updated_at"]),
            )
            self.tree.insert("", "end", iid=row["business_key"], values=values)

    def on_tree_select(self, _event=None):
        row = self.selected_row()
        if not row:
            self.selected_title_var.set("Select a lead")
            self.selected_meta_var.set("Choose a row to review actions.")
            return
        self.selected_title_var.set(row["business_name"])
        parts = [
            f"Status: {row['status']}",
            f"Form: {'filled' if row['form_prefilled'] else 'not filled'}",
            f"Email: {'sent' if row['email_sent_at'] else 'not sent'}",
            f"WhatsApp: {'sent' if row['whatsapp_sent_at'] else 'not sent'}",
        ]
        self.selected_meta_var.set("\n".join(parts))

    def selected_row(self):
        if not hasattr(self, "tree"):
            return None
        selected = self.tree.selection()
        if not selected:
            return None
        return self.row_by_key.get(selected[0])

    def mark_email_sent(self):
        row = self.selected_row()
        if not row:
            return
        if not row["emails"]:
            proceed = messagebox.askyesno("No email found", "This lead has no discovered email. Mark it as sent anyway?")
            if not proceed:
                return
        self.record_manual_event(row, EVENT_EMAIL_SENT, "Marked email as sent from dashboard")

    def mark_whatsapp_sent(self):
        row = self.selected_row()
        if not row:
            return
        if not row["phones"]:
            proceed = messagebox.askyesno("No phone found", "This lead has no discovered phone. Mark WhatsApp as sent anyway?")
            if not proceed:
                return
        self.record_manual_event(row, EVENT_WHATSAPP_SENT, "Marked WhatsApp as sent from dashboard")

    def record_manual_event(self, row, event_type, details):
        with self.connect() as connection:
            created = record_event(
                connection,
                event_type,
                row["business_key"],
                {"name": row["business_name"], "website": row["website"]},
                details=details,
            )
        self.status_var.set("Progress marked" if created else "Already marked")
        self.load_data()

    def open_selected_website(self):
        row = self.selected_row()
        if row and row["website"]:
            webbrowser.open(row["website"])

    def open_selected_contact(self):
        row = self.selected_row()
        if row and row["contact_page"]:
            webbrowser.open(row["contact_page"])

    def open_whatsapp_review(self):
        row = self.selected_row()
        if not row:
            return
        url = self.whatsapp_url(row)
        if not url:
            messagebox.showinfo("Not ready", "This lead needs a phone number and proposal text first.")
            return
        webbrowser.open(url)

    def whatsapp_url(self, row):
        phone = next((item for item in row["phones"] if re.sub(r"\D", "", item)), "")
        digits = re.sub(r"\D", "", phone)
        if not digits or not row["proposal"]:
            return ""
        return f"https://wa.me/{digits}?text={quote_plus(row['proposal'])}"

    def open_drafts_csv(self):
        open_path(self.data_dir() / "outreach_drafts.csv")

    def start_bot(self):
        if self.is_running():
            self.status_var.set("Automation already running")
            return
        self.clear_log()
        self.append_log("Starting automation...")
        try:
            self.process = subprocess.Popen(
                [sys.executable, str(APP_DIR / "main.py")],
                cwd=str(APP_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            threading.Thread(target=self.read_process_output, daemon=True).start()
            self.status_var.set("Automation running")
        except Exception as exc:
            self.process = None
            messagebox.showerror("Could not start bot", str(exc))
            self.status_var.set("Start failed")

    def read_process_output(self):
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            self.output_queue.put(line.rstrip())
        self.output_queue.put("__PROCESS_ENDED__")

    def poll_process_output(self):
        try:
            while True:
                item = self.output_queue.get_nowait()
                if item == "__PROCESS_ENDED__":
                    code = self.process.poll() if self.process else None
                    self.append_log(f"Automation ended with code {code}.")
                    self.status_var.set("Ready")
                    self.load_data()
                else:
                    self.append_log(item)
                    if "press Enter to close the browser" in item:
                        self.status_var.set("Review the filled forms, then click Finish Review")
        except queue.Empty:
            pass

        if self.process and self.process.poll() is not None:
            self.process = None
            self.status_var.set("Ready")
        self.after(250, self.poll_process_output)

    def finish_review(self):
        if not self.is_running() or not self.process or not self.process.stdin:
            return
        try:
            self.process.stdin.write("\n")
            self.process.stdin.flush()
            self.status_var.set("Review finished")
        except Exception as exc:
            self.status_var.set(f"Could not finish review: {exc}")

    def stop_bot(self):
        if not self.is_running() or not self.process:
            return
        if not messagebox.askyesno("Stop automation", "Stop the running automation now?"):
            return
        self.process.terminate()
        self.status_var.set("Stopping automation")

    def is_running(self):
        return self.process is not None and self.process.poll() is None

    def auto_refresh(self):
        self.load_data()
        self.after(3000, self.auto_refresh)

    def load_recent_log_file(self):
        if not LOG_DIR.exists():
            return
        logs = sorted(LOG_DIR.glob("Marketing_*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not logs:
            return
        try:
            lines = logs[0].read_text(encoding="utf-8", errors="replace").splitlines()
            self.set_text(self.log_text, "\n".join(lines[-80:]))
        except Exception:
            pass

    def append_log(self, line):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", str(line) + "\n")
        self.log_text.see("end")
        content = self.log_text.get("1.0", "end").splitlines()
        if len(content) > 300:
            self.log_text.delete("1.0", f"{len(content) - 260}.0")
        self.log_text.configure(state="disabled")

    def clear_log(self):
        self.set_text(self.log_text, "")

    def set_text(self, widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def format_time(self, value):
        if not value:
            return "-"
        try:
            parsed = datetime.fromisoformat(str(value))
            return parsed.strftime("%b %d %H:%M")
        except Exception:
            return shorten(value, 16)

    def on_close(self):
        if self.is_running():
            if not messagebox.askyesno("Automation running", "Close the dashboard and stop the running automation?"):
                return
            self.process.terminate()
        self.destroy()


if __name__ == "__main__":
    app = MarketingDashboard()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
