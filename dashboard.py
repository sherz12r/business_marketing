from __future__ import annotations

import json
from contextlib import closing
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import quote_plus, urlparse
import tkinter as tk

from app_paths import get_app_dir
from campaign import campaign_stats
from process_utils import process_running
from outreach_text import clean_outreach_message
from progress_tracker import (
    EVENT_EMAIL_SENT,
    EVENT_FORM_PREFILLED,
    EVENT_LINKEDIN_SENT,
    EVENT_WEBSITE_OPENED,
    EVENT_WHATSAPP_SENT,
    ensure_database,
    outreach_stats,
    record_event,
)


APP_DIR = Path(get_app_dir())
CONFIG_PATH = APP_DIR / "config.json"
LOG_DIR = APP_DIR / "logs"
WEB_JOB_STATE_PATH = APP_DIR / "data" / "runtime" / "web_job.json"

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

DEFAULT_PROPOSAL_PROMPT = """You are helping a professional software and digital-services company
write a short business introduction for a potential client.

Business name:
{business_name}

Website:
{website_url}

Search/category context:
{business_context}

Sender company:
{company_name}

Our company provides:

{services}

Write a professional and friendly proposal that can be used
as a draft for a website contact form.

IMPORTANT:

- Do not pretend that we know the company's specific problems.
- Do not make false claims about their current website.
- Do not say that we noticed problems unless they are explicitly provided.
- Keep it relatively short.
- Sound human, professional and helpful.
- Do not use excessive marketing language.
- Do not use emojis.
- Do not mention that AI wrote the message.
- After the greeting, start the first sentence with "We". Do not open with
  "Our team at [company name]" and do not repeat the sender company name in
  the message body; use we, us, and our instead.
- Invite them to contact us if they are interested.
- Mention that we can discuss their requirements and provide suitable recommendations.
- Infer the likely industry from the business name and profile context.
- Mention only services that are genuinely relevant to that type of business,
  such as website work, integrations, custom software, accounting, POS, CRM,
  inventory, e-commerce, booking, automation, maintenance, SEO, or marketing.
- Do not write a generic list or imply that every service is suitable.
- For an ordinary business, propose one cohesive solution tailored to its
  likely industry. Explain how the components work together in practical,
  customer-friendly language instead of merely listing services. Mention three
  to five relevant capabilities and the workflow or business value they can
  support, without assuming that the business currently lacks them or claiming
  guaranteed results.
- For a restaurant, cafe, or catering business, offer an integrated solution
  such as a POS connected to the website, online menu and direct customer
  ordering, kitchen/order workflow, inventory control, and sales reporting.
  Explain that website orders can flow into the same operational system.
- For a general business without a clearer industry-specific match, offer an
  invoicing and accounting solution covering quotations, invoices, expenses,
  customer balances, profit-and-loss reporting, and management reports.
- Keep the proposal focused and readable, normally around 120 to 180 words.
- End by asking whether they are interested in website improvements, a tailored
  business-management solution, or both.
- If the target is itself a software, IT, web, advertising, or marketing
  provider, treat it as a potential partner and propose collaboration rather
  than selling website development or ordinary client services.
- When confirmed website-audit observations are provided, mention only those
  observations as internal evidence, but describe them to the customer only
  as broad improvement areas such as SEO, accessibility, mobile usability, or
  website security. Do not reveal exact issues, element names, or counts, and
  do not give a detailed technical solution.
- Do not include sender contact details such as contact name, email, phone, website, or a contact-us block.
- Do not include a subject line unless specifically requested.

Return ONLY the proposal text."""

DEFAULT_LINKEDIN_TEMPLATE = """{greeting}

I came across {business_name}{business_type_phrase}{role_phrase}. {proposal_summary}

Would you be open to connecting for a brief conversation?

{sender_signature}"""

DEFAULT_CONFIG = {
    "headless": False,
    "chrome_profile_dir": "chrome_profile",
    "chrome_binary": "",
    "chatgpt_profile_dir": "chatgpt_profile",
    "search_query": "business near me",
    "limit": 10,
    "google_max_pages": 20,
    "openai_model": "gpt-5.5",
    "use_browser_ai": True,
    "data_dir": "data",
    "review_mode": True,
    "keep_prefilled_tabs_open": True,
    "skip_previously_processed": True,
    "reprocess_after_days": 40,
    "campaign": {
        "enabled": False,
        "country": "United Arab Emirates",
        "locations_file": "locations/uae.json",
        "query_template": "businesses in {area}, {city}, {region}, {country}",
        "businesses_per_area": 25,
        "max_areas_per_run": 1,
        "never_repeat_contacted": True,
    },
    "message_focus": "website_audit_and_software",
    "proposal_prompt": DEFAULT_PROPOSAL_PROMPT,
    "ignore_urls": [],
    "company_name": "",
    "company_website": "",
    "contact_name": "",
    "contact_email": "",
    "contact_phone": "",
    "default_country_code": "971",
    "website_forms": {
        "include_contact_details": True,
    },
    "whatsapp": {
        "enabled": True,
        "auto_send": False,
        "include_contact_details": True,
        "open_for_review": True,
        "keep_tabs_open": False,
        "reuse_tab": True,
        "send_pause_min_seconds": 12,
        "send_pause_max_seconds": 25,
        "send_timeout_seconds": 30,
        "login_timeout_seconds": 180,
        "invalid_number_pause_seconds": 10,
        "default_country_code": "971",
        "ignore_phone_prefixes": [],
        "send_image": False,
        "image_only": False,
        "image_path": "",
    },
    "linkedin": {
        "enabled": True,
        "include_contact_details": True,
        "search_keywords": "Co Founder and CEO",
        "max_message_chars": 600,
        "message_template": DEFAULT_LINKEDIN_TEMPLATE,
    },
    "email": {
        "enabled": True,
        "auto_send": True,
        "include_contact_details": True,
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_username": "",
        "smtp_password": "",
        "from_email": "",
        "from_name": "",
        "subject": "Software and digital services proposal",
        "send_to_all_found": False,
        "use_tls": True,
        "use_ssl": False,
        "send_image": False,
        "image_only": False,
        "image_path": "",
    },
}

SETTINGS_SECTIONS = [
    (
        "Run",
        [
            {"path": ("search_query",), "label": "Search Query", "type": "text"},
            {"path": ("limit",), "label": "Lead Limit", "type": "int", "min": 1},
            {"path": ("google_max_pages",), "label": "Google Page Limit", "type": "int", "min": 1},
            {"path": ("headless",), "label": "Headless Browser", "type": "bool"},
            {"path": ("review_mode",), "label": "Review Mode", "type": "bool"},
            {"path": ("keep_prefilled_tabs_open",), "label": "Keep Prefilled Tabs Open", "type": "bool"},
            {"path": ("skip_previously_processed",), "label": "Skip Previously Processed", "type": "bool"},
            {"path": ("reprocess_after_days",), "label": "Allow Again After Days", "type": "int", "min": 1},
            {"path": ("data_dir",), "label": "Data Folder", "type": "text"},
            {"path": ("chrome_profile_dir",), "label": "Chrome Profile Folder", "type": "text"},
            {"path": ("chrome_binary",), "label": "Chrome Executable (Optional)", "type": "file"},
            {"path": ("chatgpt_profile_dir",), "label": "ChatGPT Profile Folder", "type": "text"},
            {"path": ("openai_model",), "label": "OpenAI Model", "type": "text"},
        ],
    ),
    (
        "Campaign",
        [
            {"path": ("campaign", "enabled"), "label": "Enable Area Campaign", "type": "bool"},
            {"path": ("campaign", "country"), "label": "Country", "type": "text"},
            {"path": ("campaign", "locations_file"), "label": "Locations Catalog", "type": "text"},
            {"path": ("campaign", "query_template"), "label": "Google Query Template", "type": "text"},
            {"path": ("campaign", "businesses_per_area"), "label": "New Businesses Per Area Attempt", "type": "int", "min": 1},
            {"path": ("campaign", "max_areas_per_run"), "label": "Areas Per Run (0 = All)", "type": "int", "min": 0},
            {"path": ("campaign", "never_repeat_contacted"), "label": "Never Repeat Contacted Businesses", "type": "bool"},
        ],
    ),
    (
        "AI Prompt",
        [
            {
                "path": ("message_focus",),
                "label": "Message Content",
                "type": "select",
                "options": [
                    ("website_audit_and_software", "Website audit + software proposal"),
                    ("website_audit_only", "Website audit / website services only"),
                    ("software_proposal_only", "Software proposal only"),
                ],
            },
            {"path": ("proposal_prompt",), "label": "Proposal Prompt", "type": "textarea", "height": 24},
            {"path": ("use_browser_ai",), "label": "Use Browser AI When API Key Is Missing", "type": "bool"},
        ],
    ),
    (
        "Company",
        [
            {"path": ("company_name",), "label": "Company Name", "type": "text"},
            {"path": ("company_website",), "label": "Company Website", "type": "text"},
            {"path": ("contact_name",), "label": "Contact Name", "type": "text"},
            {"path": ("contact_email",), "label": "Contact Email", "type": "text"},
            {"path": ("contact_phone",), "label": "Contact Phone", "type": "text"},
            {"path": ("default_country_code",), "label": "Default Country Code", "type": "text"},
        ],
    ),
    (
        "Website Forms",
        [
            {"path": ("website_forms", "include_contact_details"), "label": "Include Contact Details", "type": "bool"},
        ],
    ),
    (
        "Ignore URLs",
        [
            {"path": ("ignore_urls",), "label": "Ignored Domains / URLs", "type": "list", "height": 18},
        ],
    ),
    (
        "WhatsApp",
        [
            {"path": ("whatsapp", "enabled"), "label": "Enabled", "type": "bool"},
            {"path": ("whatsapp", "auto_send"), "label": "Auto Send", "type": "bool"},
            {"path": ("whatsapp", "send_image"), "label": "Send Image Only (No AI Message)", "type": "bool"},
            {"path": ("whatsapp", "image_path"), "label": "Image File", "type": "file"},
            {"path": ("whatsapp", "include_contact_details"), "label": "Include Contact Details", "type": "bool"},
            {"path": ("whatsapp", "open_for_review"), "label": "Open For Review", "type": "bool"},
            {"path": ("whatsapp", "keep_tabs_open"), "label": "Keep Tabs Open", "type": "bool"},
            {"path": ("whatsapp", "reuse_tab"), "label": "Reuse One WhatsApp Tab", "type": "bool"},
            {"path": ("whatsapp", "send_pause_min_seconds"), "label": "Minimum Pause After Send", "type": "int", "min": 0},
            {"path": ("whatsapp", "send_pause_max_seconds"), "label": "Maximum Pause After Send", "type": "int", "min": 0},
            {"path": ("whatsapp", "send_timeout_seconds"), "label": "Send Timeout Seconds", "type": "int", "min": 1},
            {"path": ("whatsapp", "login_timeout_seconds"), "label": "First Login Timeout Seconds", "type": "int", "min": 10},
            {"path": ("whatsapp", "invalid_number_pause_seconds"), "label": "Invalid Number Pause Seconds", "type": "int", "min": 0},
            {"path": ("whatsapp", "default_country_code"), "label": "Default Country Code", "type": "text"},
            {"path": ("whatsapp", "ignore_phone_prefixes"), "label": "Ignored Phone Prefixes", "type": "list", "height": 5},
        ],
    ),
    (
        "LinkedIn",
        [
            {"path": ("linkedin", "enabled"), "label": "Enabled", "type": "bool"},
            {"path": ("linkedin", "include_contact_details"), "label": "Use Shared Company Contact Details", "type": "bool"},
            {"path": ("linkedin", "search_keywords"), "label": "People Search Keywords", "type": "text"},
            {"path": ("linkedin", "max_message_chars"), "label": "Maximum Draft Characters", "type": "int", "min": 100, "max": 5000},
            {"path": ("linkedin", "message_template"), "label": "Message Template", "type": "textarea", "height": 14},
        ],
    ),
    (
        "Email",
        [
            {"path": ("email", "enabled"), "label": "Enabled", "type": "bool"},
            {"path": ("email", "auto_send"), "label": "Auto Send", "type": "bool"},
            {"path": ("email", "send_image"), "label": "Attach Image", "type": "bool"},
            {"path": ("email", "image_only"), "label": "Send Image Instead of Message", "type": "bool"},
            {"path": ("email", "image_path"), "label": "Image File", "type": "file"},
            {"path": ("email", "include_contact_details"), "label": "Include Contact Details", "type": "bool"},
            {"path": ("email", "smtp_host"), "label": "SMTP Host", "type": "text"},
            {"path": ("email", "smtp_port"), "label": "SMTP Port", "type": "int", "min": 1, "max": 65535},
            {"path": ("email", "smtp_username"), "label": "SMTP Username", "type": "text"},
            {"path": ("email", "smtp_password"), "label": "SMTP Password", "type": "password"},
            {"path": ("email", "from_email"), "label": "From Email", "type": "text"},
            {"path": ("email", "from_name"), "label": "From Name", "type": "text"},
            {"path": ("email", "subject"), "label": "Subject", "type": "text"},
            {"path": ("email", "send_to_all_found"), "label": "Send To All Found", "type": "bool"},
            {"path": ("email", "use_tls"), "label": "Use TLS", "type": "bool"},
            {"path": ("email", "use_ssl"), "label": "Use SSL", "type": "bool"},
        ],
    ),
]


def read_json(path):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def write_json(path, data):
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4)
        handle.write("\n")


def merge_config(defaults, current):
    merged = json.loads(json.dumps(defaults))
    if not isinstance(current, dict):
        return merged
    for key, value in current.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_config_value(config, path, default=""):
    current = config
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def set_config_value(config, path, value):
    current = config
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[path[-1]] = value


def to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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


def normalize_linkedin_url(value):
    """Return a safe LinkedIn URL without accepting arbitrary destinations."""
    text = str(value or "").strip()
    if not text:
        return ""
    if not re.match(r"^https?://", text, flags=re.IGNORECASE):
        text = "https://" + text.lstrip("/")
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        raise ValueError("Enter a linkedin.com profile URL.")
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Enter a valid LinkedIn profile URL.")
    return text


def linkedin_people_search_url(keywords):
    search_text = str(keywords or "").strip() or "Co Founder and CEO"
    return (
        "https://www.linkedin.com/search/results/people/"
        f"?keywords={quote_plus(search_text)}&origin=SWITCH_SEARCH_VERTICAL"
    )


def find_chrome_executable(config):
    """Locate Chrome while allowing an explicit executable in Settings."""
    configured = str(config.get("chrome_binary", "") or "").strip()
    candidates = []
    if configured:
        configured_path = Path(configured).expanduser()
        if not configured_path.is_absolute():
            configured_path = APP_DIR / configured_path
        candidates.append(configured_path)

    for executable_name in ("chrome.exe", "chrome", "google-chrome", "chromium", "chromium-browser"):
        discovered = shutil.which(executable_name)
        if discovered:
            candidates.append(Path(discovered))

    if sys.platform.startswith("win"):
        for environment_name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(environment_name)
            if base:
                candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def proposal_summary_for_linkedin(proposal, limit=300):
    """Turn the existing analyzed proposal into a compact LinkedIn summary."""
    lines = []
    for raw_line in str(proposal or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("contact details:"):
            break
        if not lines and re.match(r"^(hi|hello|dear)\b", line, re.IGNORECASE):
            continue
        lines.append(line)
    text = " ".join(lines)
    if not text:
        return (
            "I would like to explore whether our software and digital services "
            "could support your business goals."
        )
    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary = " ".join(sentence for sentence in sentences[:2] if sentence).strip()
    return shorten(summary or text, limit)


def build_linkedin_message(row, config, contact_name="", contact_role="", business_type=""):
    linkedin_config = config.get("linkedin", {}) if isinstance(config, dict) else {}
    if not isinstance(linkedin_config, dict):
        linkedin_config = {}
    max_chars = max(100, min(5000, int(linkedin_config.get("max_message_chars", 600) or 600)))
    template = str(
        linkedin_config.get("message_template") or DEFAULT_LINKEDIN_TEMPLATE
    ).strip()
    first_name = str(contact_name or "").strip().split(" ", 1)[0]
    greeting = f"Hi {first_name}," if first_name else "Hello,"
    business_name = str(row.get("business_name") or "this business").strip()
    inferred_type = str(
        business_type
        or row.get("linkedin_business_type")
        or row.get("business_context")
        or ""
    ).replace("\n", " ").strip()
    if inferred_type.lower() in {"business near me", "businesses near me"}:
        inferred_type = ""
    inferred_type = shorten(inferred_type, 80)
    sender_name = str(config.get("contact_name", "") or "").strip()
    sender_company = str(config.get("company_name", "") or "").strip()
    sender_email = str(config.get("contact_email", "") or "").strip()
    sender_phone = str(config.get("contact_phone", "") or "").strip()
    sender_website = str(config.get("company_website", "") or "").strip()
    signature_lines = []
    if to_bool(linkedin_config.get("include_contact_details", True)):
        if sender_name:
            signature_lines.extend(["Best,", sender_name])
        elif sender_company:
            signature_lines.append("Regards,")
        if sender_company:
            signature_lines.append(sender_company)
        if sender_email:
            signature_lines.append(sender_email)
        if sender_phone:
            signature_lines.append(sender_phone)
        if sender_website:
            signature_lines.append(sender_website)
    sender_signature = "\n".join(signature_lines)
    values = {
        "greeting": greeting,
        "first_name": first_name,
        "contact_name": str(contact_name or "").strip(),
        "contact_role": str(contact_role or "").strip(),
        "role_phrase": (
            f" and noticed your role as {str(contact_role).strip()}"
            if str(contact_role or "").strip()
            else ""
        ),
        "business_name": business_name,
        "business_type": inferred_type,
        "business_type_phrase": f", which works in {inferred_type}" if inferred_type else "",
        "website": str(row.get("website") or "").strip(),
        "proposal_summary": proposal_summary_for_linkedin(row.get("proposal"), 320),
        "sender_name": sender_name,
        "sender_company": sender_company,
        "sender_email": sender_email,
        "sender_phone": sender_phone,
        "sender_website": sender_website,
        "sender_signature": sender_signature,
    }
    try:
        message = template.format(**values)
    except (KeyError, ValueError):
        message = DEFAULT_LINKEDIN_TEMPLATE.format(**values)
    if sender_signature and "{sender_signature}" not in template and sender_signature not in message:
        message = f"{message.rstrip()}\n\n{sender_signature}"
    message = re.sub(r"[ \t]+", " ", message)
    message = re.sub(r"\n{3,}", "\n\n", message).strip()
    if len(message) <= max_chars:
        return message
    if sender_signature and message.endswith(sender_signature):
        body = message[: -len(sender_signature)].rstrip()
        available = max_chars - len(sender_signature) - 5
        if available >= 40:
            clipped_body = body[:available].rstrip()
            if " " in clipped_body:
                clipped_body = clipped_body.rsplit(" ", 1)[0]
            return clipped_body.rstrip(".,;:") + "...\n\n" + sender_signature
    clipped = message[: max_chars - 3].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(".,;:") + "..."


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


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, config_data, save_callback):
        super().__init__(parent)
        self.parent = parent
        self.save_callback = save_callback
        self.raw_config = dict(config_data or {})
        self.config_data = merge_config(DEFAULT_CONFIG, self.raw_config)
        self.variables = {}
        self.text_widgets = {}

        self.title("Dashboard Settings")
        self.geometry("780x680")
        self.minsize(680, 540)
        self.configure(bg=COLORS["bg"])
        self.transient(parent)

        self.build_layout()
        self.load_values()
        self.grab_set()

    def build_layout(self):
        shell = tk.Frame(self, bg=COLORS["bg"], padx=18, pady=16)
        shell.pack(fill="both", expand=True)

        tk.Label(
            shell,
            text="Dashboard Settings",
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")

        self.notebook = ttk.Notebook(shell)
        self.notebook.pack(fill="both", expand=True, pady=(14, 14))

        for title, fields in SETTINGS_SECTIONS:
            tab = self.scrollable_tab(self.notebook)
            self.notebook.add(tab["outer"], text=title)
            self.build_fields(tab["inner"], fields)

        actions = tk.Frame(shell, bg=COLORS["bg"])
        actions.pack(fill="x")

        self.make_dialog_button(actions, "Open JSON", lambda: open_path(CONFIG_PATH), COLORS["panel_3"]).pack(side="left")
        self.make_dialog_button(actions, "Reload", self.reload_settings, COLORS["panel_3"]).pack(side="left", padx=(8, 0))
        self.make_dialog_button(actions, "Cancel", self.destroy, COLORS["panel_3"]).pack(side="right")
        self.make_dialog_button(actions, "Save Settings", self.save_settings, COLORS["accent"]).pack(side="right", padx=(0, 8))

    def scrollable_tab(self, parent):
        outer = tk.Frame(parent, bg=COLORS["panel"])
        canvas = tk.Canvas(outer, bg=COLORS["panel"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=COLORS["panel"], padx=16, pady=16)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def update_scroll_region(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def update_inner_width(event):
            canvas.itemconfigure(window_id, width=event.width)

        inner.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_inner_width)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind(
            "<Enter>",
            lambda _event: canvas.bind_all(
                "<MouseWheel>",
                lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"),
            ),
        )
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return {"outer": outer, "inner": inner}

    def build_fields(self, parent, fields):
        parent.grid_columnconfigure(1, weight=1)
        for row, field in enumerate(fields):
            label = tk.Label(
                parent,
                text=field["label"],
                bg=COLORS["panel"],
                fg=COLORS["muted"],
                font=("Segoe UI", 10, "bold"),
                anchor="w",
            )
            label.grid(row=row, column=0, sticky="nw", padx=(0, 14), pady=(8, 8))

            path_key = ".".join(field["path"])
            field_type = field["type"]

            if field_type == "bool":
                variable = tk.BooleanVar()
                widget = tk.Checkbutton(
                    parent,
                    variable=variable,
                    bg=COLORS["panel"],
                    activebackground=COLORS["panel"],
                    selectcolor=COLORS["panel_3"],
                    fg=COLORS["text"],
                    activeforeground=COLORS["text"],
                    relief="flat",
                )
                widget.grid(row=row, column=1, sticky="w", pady=(8, 8))
                self.variables[path_key] = (field, variable)
            elif field_type in {"list", "textarea"}:
                text = tk.Text(
                    parent,
                    height=field.get("height", 6),
                    bg=COLORS["panel_2"],
                    fg=COLORS["text"],
                    insertbackground=COLORS["text"],
                    relief="flat",
                    wrap="word",
                    font=("Consolas", 10),
                )
                text.grid(row=row, column=1, sticky="ew", pady=(8, 8), ipady=4)
                self.text_widgets[path_key] = (field, text)
            elif field_type == "select":
                variable = tk.StringVar()
                widget = ttk.Combobox(
                    parent,
                    textvariable=variable,
                    state="readonly",
                    values=[label for _value, label in field.get("options", [])],
                    font=("Segoe UI", 10),
                )
                widget.grid(row=row, column=1, sticky="ew", pady=(8, 8), ipady=4)
                self.variables[path_key] = (field, variable)
            else:
                variable = tk.StringVar()
                field_frame = tk.Frame(parent, bg=COLORS["panel"])
                field_frame.grid(row=row, column=1, sticky="ew", pady=(8, 8))
                field_frame.grid_columnconfigure(0, weight=1)
                widget = tk.Entry(
                    field_frame,
                    textvariable=variable,
                    bg=COLORS["panel_2"],
                    fg=COLORS["text"],
                    insertbackground=COLORS["text"],
                    relief="flat",
                    font=("Segoe UI", 10),
                    show="*" if field_type == "password" else "",
                )
                widget.grid(row=0, column=0, sticky="ew", ipady=7)
                if field_type == "file":
                    tk.Button(
                        field_frame, text="Browse...",
                        command=lambda target=variable: self.choose_image(target),
                        bg=COLORS["panel_3"], fg=COLORS["text"], relief="flat",
                        padx=10, pady=7, cursor="hand2",
                    ).grid(row=0, column=1, padx=(8, 0))
                self.variables[path_key] = (field, variable)

    def choose_image(self, variable):
        selected = filedialog.askopenfilename(
            parent=self,
            title="Select image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.gif *.webp"),
                ("All files", "*.*"),
            ],
        )
        if selected:
            variable.set(selected)

    def make_dialog_button(self, parent, text, command, color):
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

    def load_values(self):
        self.config_data = merge_config(DEFAULT_CONFIG, self.raw_config)
        for path_key, (field, variable) in self.variables.items():
            value = get_config_value(self.config_data, field["path"], "")
            if field["type"] == "bool":
                variable.set(to_bool(value))
            elif field["type"] == "select":
                labels = dict(field.get("options", []))
                variable.set(labels.get(str(value), next(iter(labels.values()), "")))
            else:
                variable.set("" if value is None else str(value))
        for path_key, (field, widget) in self.text_widgets.items():
            value = get_config_value(self.config_data, field["path"], [])
            widget.delete("1.0", "end")
            if field["type"] == "list" and isinstance(value, list):
                widget.insert("1.0", "\n".join(str(item) for item in value))
            elif value:
                widget.insert("1.0", str(value))

    def reload_settings(self):
        if not messagebox.askyesno("Reload settings", "Discard unsaved changes and reload config.json?"):
            return
        self.raw_config = read_json(CONFIG_PATH)
        self.load_values()

    def save_settings(self):
        try:
            new_config = self.collect_config()
            self.save_callback(new_config)
        except ValueError as exc:
            messagebox.showerror("Invalid setting", str(exc))
            return
        except Exception as exc:
            messagebox.showerror("Could not save settings", str(exc))
            return

        messagebox.showinfo("Settings saved", "Settings saved to config.json.")
        self.destroy()

    def collect_config(self):
        new_config = merge_config(DEFAULT_CONFIG, self.raw_config)

        for path_key, (field, variable) in self.variables.items():
            field_type = field["type"]
            raw_value = variable.get()

            if field_type == "bool":
                value = to_bool(raw_value)
            elif field_type == "int":
                text = str(raw_value).strip()
                if not text:
                    text = str(get_config_value(DEFAULT_CONFIG, field["path"], 0))
                try:
                    value = int(text)
                except ValueError as exc:
                    raise ValueError(f"{field['label']} must be a whole number.") from exc
                if "min" in field and value < field["min"]:
                    raise ValueError(f"{field['label']} must be at least {field['min']}.")
                if "max" in field and value > field["max"]:
                    raise ValueError(f"{field['label']} must be {field['max']} or lower.")
            elif field_type == "select":
                choices = {
                    label: option_value
                    for option_value, label in field.get("options", [])
                }
                if raw_value not in choices:
                    raise ValueError(f"Choose a valid value for {field['label']}.")
                value = choices[raw_value]
            else:
                value = str(raw_value).strip()

            set_config_value(new_config, field["path"], value)

        for path_key, (field, widget) in self.text_widgets.items():
            raw_text = widget.get("1.0", "end").strip()
            if field["type"] == "list":
                value = parse_settings_list(raw_text)
            else:
                value = raw_text
            set_config_value(new_config, field["path"], value)

        return new_config


def parse_settings_list(value):
    if not value:
        return []
    text = str(value).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass
    return [part.strip() for part in re.split(r"[\n;,]+", text) if part.strip()]


class LinkedInLeadDialog(tk.Toplevel):
    """Human-reviewed LinkedIn draft editor; it never collects credentials."""

    def __init__(self, parent, row):
        super().__init__(parent)
        self.parent = parent
        self.row = row
        self.title(f"LinkedIn Campaign - {row['business_name']}")
        self.geometry("720x700")
        self.minsize(620, 560)
        self.configure(bg=COLORS["bg"])
        self.transient(parent)

        self.contact_name_var = tk.StringVar(value=row.get("linkedin_contact_name", ""))
        self.contact_role_var = tk.StringVar(value=row.get("linkedin_contact_role", ""))
        self.business_type_var = tk.StringVar(value=row.get("linkedin_business_type", ""))
        self.profile_url_var = tk.StringVar(value=row.get("linkedin_profile_url", ""))
        self.character_count_var = tk.StringVar(value="0 characters")

        self.build_layout()
        self.draft_text.insert("1.0", row.get("linkedin_draft", ""))
        self.draft_text.edit_modified(False)
        self.update_character_count()
        self.grab_set()

    def build_layout(self):
        shell = tk.Frame(self, bg=COLORS["bg"], padx=20, pady=18)
        shell.pack(fill="both", expand=True)

        tk.Label(
            shell,
            text="LinkedIn Campaign Draft",
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            shell,
            text=(
                f"{self.row['business_name']}\n"
                "Sign in directly on LinkedIn. This tool prepares the message but does not "
                "store credentials or send automatically."
            ),
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=650,
        ).pack(anchor="w", pady=(5, 14))

        fields = tk.Frame(shell, bg=COLORS["panel"], padx=14, pady=12)
        fields.pack(fill="x")
        fields.grid_columnconfigure(1, weight=1)
        entries = [
            ("Contact name", self.contact_name_var),
            ("Role (founder, owner, etc.)", self.contact_role_var),
            ("Business type", self.business_type_var),
            ("LinkedIn profile URL", self.profile_url_var),
        ]
        for index, (label, variable) in enumerate(entries):
            tk.Label(
                fields,
                text=label,
                bg=COLORS["panel"],
                fg=COLORS["muted"],
                font=("Segoe UI", 9, "bold"),
            ).grid(row=index, column=0, sticky="w", padx=(0, 12), pady=6)
            tk.Entry(
                fields,
                textvariable=variable,
                bg=COLORS["panel_2"],
                fg=COLORS["text"],
                insertbackground=COLORS["text"],
                relief="flat",
                font=("Segoe UI", 10),
            ).grid(row=index, column=1, sticky="ew", pady=6, ipady=6)

        draft_header = tk.Frame(shell, bg=COLORS["bg"])
        draft_header.pack(fill="x", pady=(14, 6))
        tk.Label(
            draft_header,
            text="Personalized message",
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")
        tk.Label(
            draft_header,
            textvariable=self.character_count_var,
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        ).pack(side="right")

        draft_frame = tk.Frame(shell, bg=COLORS["panel"])
        draft_frame.pack(fill="both", expand=True)
        self.draft_text = tk.Text(
            draft_frame,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            wrap="word",
            padx=12,
            pady=10,
            font=("Segoe UI", 10),
        )
        draft_scrollbar = ttk.Scrollbar(draft_frame, orient="vertical", command=self.draft_text.yview)
        self.draft_text.configure(yscrollcommand=draft_scrollbar.set)
        self.draft_text.pack(side="left", fill="both", expand=True)
        draft_scrollbar.pack(side="right", fill="y")
        self.draft_text.bind("<<Modified>>", self.update_character_count)

        tk.Label(
            shell,
            text=(
                "Generate uses the saved website/business analysis. Review every draft before "
                "copying it to LinkedIn."
            ),
            bg=COLORS["bg"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            wraplength=650,
            justify="left",
        ).pack(anchor="w", pady=(8, 12))

        actions = tk.Frame(shell, bg=COLORS["bg"])
        actions.pack(fill="x")
        self.parent.make_button(actions, "Generate Draft", self.generate_draft, COLORS["accent_2"]).pack(side="left")
        self.parent.make_button(actions, "Copy", self.copy_draft, COLORS["panel_3"]).pack(side="left", padx=(8, 0))
        self.parent.make_button(actions, "Close", self.destroy, COLORS["panel_3"]).pack(side="right")
        self.parent.make_button(actions, "Save", self.save, COLORS["accent"]).pack(side="right", padx=(0, 8))
        self.parent.make_button(actions, "Save & Open", self.save_and_open, COLORS["warning"]).pack(side="right", padx=(0, 8))

    def values(self):
        return {
            "contact_name": self.contact_name_var.get().strip(),
            "contact_role": self.contact_role_var.get().strip(),
            "business_type": self.business_type_var.get().strip(),
            "profile_url": self.profile_url_var.get().strip(),
            "draft": self.draft_text.get("1.0", "end").strip(),
        }

    def generate_draft(self):
        values = self.values()
        draft = self.parent.generate_linkedin_draft(
            self.row,
            values["contact_name"],
            values["contact_role"],
            values["business_type"],
        )
        self.draft_text.delete("1.0", "end")
        self.draft_text.insert("1.0", draft)
        self.draft_text.edit_modified(False)
        self.update_character_count()

    def update_character_count(self, _event=None):
        if not hasattr(self, "draft_text"):
            return
        count = len(self.draft_text.get("1.0", "end-1c"))
        self.character_count_var.set(f"{count} characters")
        self.draft_text.edit_modified(False)

    def save(self):
        try:
            saved = self.parent.save_linkedin_details(self.row, self.values())
        except ValueError as exc:
            messagebox.showerror("LinkedIn details", str(exc), parent=self)
            return False
        if saved:
            self.row = self.parent.row_by_key.get(self.row["business_key"], self.row)
        return saved

    def copy_draft(self):
        draft = self.draft_text.get("1.0", "end").strip()
        if not draft:
            messagebox.showinfo("No draft", "Generate or enter a message first.", parent=self)
            return
        self.parent.copy_to_clipboard(draft, "LinkedIn draft copied")

    def save_and_open(self):
        if not self.save():
            return
        profile_url = self.parent.row_by_key.get(
            self.row["business_key"], self.row
        ).get("linkedin_profile_url", "")
        if not profile_url:
            messagebox.showinfo(
                "Profile URL required",
                "Add the person's LinkedIn profile URL before opening it.",
                parent=self,
            )
            return
        self.parent.open_in_bot_chrome(
            profile_url,
            "LinkedIn profile opened for manual review",
        )


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
        self.settings_window = None
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
        # The embedded dashboard is taller than the viewport.  Wait until Tk
        # finishes its first geometry pass, then make sure it opens at the top.
        self.after_idle(self._scroll_page_to_top)
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
        page = tk.Frame(self, bg=COLORS["bg"])
        page.pack(fill="both", expand=True)

        self.page_canvas = tk.Canvas(
            page,
            bg=COLORS["bg"],
            highlightthickness=0,
            borderwidth=0,
        )
        page_scrollbar = ttk.Scrollbar(
            page,
            orient="vertical",
            command=self.page_canvas.yview,
        )
        self.page_canvas.configure(yscrollcommand=page_scrollbar.set)

        shell = tk.Frame(self.page_canvas, bg=COLORS["bg"], padx=22, pady=18)
        self.page_window = self.page_canvas.create_window(
            (0, 0),
            window=shell,
            anchor="nw",
        )

        self.page_canvas.pack(side="left", fill="both", expand=True)
        page_scrollbar.pack(side="right", fill="y")

        shell.bind("<Configure>", self._update_page_scroll_region)
        self.page_canvas.bind("<Configure>", self._resize_page_content)

        self.build_header(shell)
        self.build_stats(shell)
        self.build_body(shell)
        self._bind_page_mousewheel(shell)

    def _update_page_scroll_region(self, _event=None):
        """Keep the page scrollbar in sync with the dashboard's full height."""
        self.page_canvas.configure(scrollregion=self.page_canvas.bbox("all"))

    def _resize_page_content(self, event):
        """Make the scrollable dashboard track the available window width."""
        self.page_canvas.itemconfigure(self.page_window, width=event.width)

    def _scroll_page_to_top(self):
        self.page_canvas.configure(scrollregion=self.page_canvas.bbox("all"))
        self.page_canvas.yview_moveto(0.0)

    def _bind_page_mousewheel(self, widget):
        """Scroll the page from ordinary controls without hijacking nested lists."""
        nested_scrollers = (tk.Text, tk.Listbox, ttk.Treeview, tk.Canvas)
        if not isinstance(widget, nested_scrollers):
            widget.bind("<MouseWheel>", self._on_page_mousewheel, add="+")
        for child in widget.winfo_children():
            self._bind_page_mousewheel(child)

    def _on_page_mousewheel(self, event):
        if event.delta:
            units = -1 if event.delta > 0 else 1
            self.page_canvas.yview_scroll(units * 3, "units")
        return "break"

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

        self.run_button = self.make_button(
            actions,
            "Run WhatsApp Bot",
            self.start_bot,
            COLORS["accent"],
        )
        self.run_button.pack(side="left", padx=(0, 8))
        self.linkedin_run_button = self.make_button(
            actions,
            "Run LinkedIn Bot",
            self.launch_linkedin_browser,
            "#0a66c2",
        )
        self.linkedin_run_button.pack(side="left", padx=(0, 8))
        self.pending_whatsapp_button = self.make_button(
            actions, "Send Pending WhatsApp",
            lambda: self.start_bot("pending-whatsapp", "pending WhatsApp"),
            COLORS["warning"],
        )
        self.pending_whatsapp_button.pack(side="left", padx=(0, 8))
        self.pending_email_button = self.make_button(
            actions, "Send Pending Emails",
            lambda: self.start_bot("pending-email", "pending emails"),
            COLORS["accent_2"],
        )
        self.pending_email_button.pack(side="left", padx=(0, 8))
        self.finish_button = self.make_button(actions, "Finish Review", self.finish_review, COLORS["warning"])
        self.finish_button.pack(side="left", padx=(0, 8))
        self.stop_button = self.make_button(actions, "Stop", self.stop_bot, COLORS["danger"])
        self.settings_button = self.make_button(actions, "Settings", self.open_settings, COLORS["panel_3"])
        self.settings_button.pack(side="left", padx=(0, 8))
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
            ("businesses", "Businesses Found ? Total", COLORS["accent"]),
            ("contacted", "Contacted ? Total", COLORS["good"]),
            ("pending", "Not Contacted ? Total", COLORS["warning"]),
            ("websites", "Websites Opened ? Total", COLORS["accent"]),
            ("forms", "Forms Filled ? Total", COLORS["good"]),
            ("contacts", "With Contacts ? Total", COLORS["accent_2"]),
            ("new", "New ? Latest Run", COLORS["accent"]),
            ("already_contacted", "Already Contacted ? Run", COLORS["good"]),
            ("skipped", "Skipped ? Latest Run", COLORS["warning"]),
            ("failed", "Failed ? Latest Run", COLORS["danger"]),
            ("emails", "Emails Sent ? Total", COLORS["accent_2"]),
            ("whatsapp", "WhatsApp Sent ? Total", COLORS["warning"]),
            ("linkedin_drafts", "LinkedIn Drafts ? Total", "#60a5fa"),
            ("linkedin", "LinkedIn Sent ? Total", "#0a66c2"),
        ]
        for index, (key, label, accent) in enumerate(cards):
            stats.grid_columnconfigure(index % 6, weight=1)
            card = tk.Frame(
                stats,
                bg=COLORS["panel"],
                padx=16,
                pady=14,
                highlightthickness=1,
                highlightbackground=COLORS["line"],
            )
            card.grid(row=index // 6, column=index % 6, sticky="nsew", padx=(0 if index % 6 == 0 else 8, 0), pady=(0, 8))
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

        columns = (
            "business", "website", "emails", "phones", "form", "email",
            "whatsapp", "linkedin", "status", "updated",
        )
        self.tree = ttk.Treeview(panel, columns=columns, show="headings", style="Dashboard.Treeview")
        headings = {
            "business": ("Business", 170),
            "website": ("Website", 210),
            "emails": ("Emails", 150),
            "phones": ("Phones", 140),
            "form": ("Form", 70),
            "email": ("Email", 78),
            "whatsapp": ("WhatsApp", 90),
            "linkedin": ("LinkedIn", 90),
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
        horizontal_scrollbar = ttk.Scrollbar(panel, orient="horizontal", command=self.tree.xview)
        horizontal_scrollbar.grid(row=3, column=0, sticky="ew")
        self.tree.configure(
            yscrollcommand=scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )

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
            "linkedin_details": self.make_button(action_grid, "LinkedIn Details", self.open_linkedin_campaign, "#0a66c2"),
            "linkedin_open": self.make_button(action_grid, "Open LinkedIn", self.open_selected_linkedin, COLORS["panel_3"]),
            "linkedin_copy": self.make_button(action_grid, "Copy LinkedIn Draft", self.copy_selected_linkedin_draft, COLORS["accent_2"]),
            "linkedin_sent": self.make_button(action_grid, "Mark LinkedIn Sent", self.mark_linkedin_sent, COLORS["accent"]),
        }
        for index, button in enumerate(self.action_buttons.values()):
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0 if index % 2 == 0 else 8, 0), pady=(0, 8))
        action_grid.grid_columnconfigure(0, weight=1)
        action_grid.grid_columnconfigure(1, weight=1)

        progress = self.card(side, row=1)
        tk.Label(progress, text="Run Progress", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Progressbar(progress, variable=self.progress_value, maximum=100, style="Dashboard.Horizontal.TProgressbar").pack(fill="x", pady=(12, 8))
        tk.Label(progress, textvariable=self.progress_text_var, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=270, justify="left").pack(anchor="w")

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

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return
        self.config_data = read_json(CONFIG_PATH)
        self.settings_window = SettingsDialog(self, self.config_data, self.save_settings)

    def save_settings(self, config_data):
        write_json(CONFIG_PATH, config_data)
        self.config_data = config_data
        self.status_var.set("Settings saved")
        self.load_data()

    def contact_details_block(self, config):
        lines = []
        for label, key in [
            ("Company", "company_name"),
            ("Contact", "contact_name"),
            ("Email", "contact_email"),
            ("Phone", "contact_phone"),
            ("Website", "company_website"),
        ]:
            value = str(config.get(key, "") or "").strip()
            if value:
                lines.append(f"{label}: {value}")
        if not lines:
            return ""
        return "Contact details:\n" + "\n".join(lines)

    def channel_message(self, message, section):
        text = clean_outreach_message(message)
        if not text:
            return ""
        config = merge_config(DEFAULT_CONFIG, read_json(CONFIG_PATH))
        include_contact_details = to_bool(
            get_config_value(
                config,
                (section, "include_contact_details"),
                True
            )
        )
        if not include_contact_details:
            return text
        contact_details = self.contact_details_block(config)
        if not contact_details:
            return text
        return f"{text}\n\n{contact_details}"

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
            with closing(self.connect()) as connection:
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
                MAX(CASE WHEN e.event_type = ? THEN e.created_at END) AS whatsapp_sent_at,
                MAX(CASE WHEN e.event_type = ? THEN e.created_at END) AS linkedin_sent_at
            FROM outreach o
            LEFT JOIN outreach_events e ON e.business_key = o.business_key
            GROUP BY o.business_key
            ORDER BY COALESCE(o.updated_at, '') DESC"""
            ,
            (EVENT_EMAIL_SENT, EVENT_WHATSAPP_SENT, EVENT_LINKEDIN_SENT),
        ).fetchall()

    def normalize_row(self, row):
        emails = parse_json_list(row["emails"])
        phones = parse_json_list(row["phones"])
        website = row["website"] or ""
        name = row["business_name"] or domain_from_url(website)
        contact_page = row["contact_page"] or ""
        proposal = clean_outreach_message(row["proposal"])
        status = row["status"] or "draft_ready"
        updated_at = row["updated_at"] or ""
        email_sent_at = row["email_sent_at"] or ""
        whatsapp_sent_at = row["whatsapp_sent_at"] or ""
        linkedin_sent_at = row["linkedin_sent_at"] or ""
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
            "channel_status": json.loads(row["channel_status"] or "{}"),
            "updated_at": updated_at,
            "email_sent_at": email_sent_at,
            "whatsapp_sent_at": whatsapp_sent_at,
            "business_context": row["business_context"] or "",
            "linkedin_profile_url": row["linkedin_profile_url"] or "",
            "linkedin_contact_name": row["linkedin_contact_name"] or "",
            "linkedin_contact_role": row["linkedin_contact_role"] or "",
            "linkedin_business_type": row["linkedin_business_type"] or "",
            "linkedin_draft": row["linkedin_draft"] or "",
            "linkedin_updated_at": row["linkedin_updated_at"] or "",
            "linkedin_sent_at": linkedin_sent_at,
            "haystack": " ".join([
                name, website, contact_page, " ".join(emails), " ".join(phones), status,
                row["business_context"] or "", row["linkedin_profile_url"] or "",
                row["linkedin_contact_name"] or "", row["linkedin_contact_role"] or "",
                row["linkedin_business_type"] or "",
            ]).lower(),
        }

    def fetch_stats(self, connection, rows):
        totals, run = outreach_stats(connection)
        campaign = campaign_stats(connection)
        limit = max(1, int(run.get('target') or self.config_data.get('limit', 10)))
        processed = run.get('processed', 0)
        return {**totals, 'new': run.get('new',0), 'already_contacted': run.get('already_contacted',0),
                'skipped': run.get('skipped',0), 'failed': run.get('failed',0),
                'processed': processed, 'limit': limit, 'progress': min(100, processed / limit * 100),
                'run': run, 'campaign': campaign}

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
        run = stats.get('run', {})
        campaign = stats.get('campaign', {})
        current = campaign.get('current') or {}
        campaign_line = (
            f"Campaign: {campaign.get('completed',0)}/{campaign.get('total',0)} areas"
            + (f" | {current.get('area','')}" if current else "")
        )
        self.progress_text_var.set(
            f"{stats.get('processed', 0)} of {stats.get('limit', 0)} businesses processed\n"
            f"{campaign_line}\n"
            f"Found: {run.get('found',0)} | Pages: {run.get('pages',0)}\n"
            f"Run WhatsApp: {run.get('whatsapp',0)} | Emails: {run.get('emails',0)}\n"
            f"Run websites: {run.get('websites',0)} | Forms: {run.get('forms',0)}\n"
            f"{run.get('stop_reason') or run.get('status') or 'No recorded run yet'}")

    def populate_activity(self, rows):
        labels = {
            EVENT_WEBSITE_OPENED: "Website opened",
            EVENT_FORM_PREFILLED: "Form filled",
            EVENT_EMAIL_SENT: "Email sent",
            EVENT_WHATSAPP_SENT: "WhatsApp sent",
            EVENT_LINKEDIN_SENT: "LinkedIn sent",
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
        selected_keys = tuple(self.tree.selection())
        query = self.search_var.get().strip().lower()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self.rows:
            if query and query not in row["haystack"]:
                continue
            email_state = row['channel_status'].get('email',{}).get('status') or ("Sent" if row["email_sent_at"] else ("Ready" if row["emails"] else "-"))
            whatsapp_state = row['channel_status'].get('whatsapp',{}).get('status') or ("Sent" if row["whatsapp_sent_at"] else ("Ready" if row["phones"] else "-"))
            linkedin_state = row['channel_status'].get('linkedin',{}).get('status') or (
                "Sent" if row["linkedin_sent_at"] else (
                    "Draft" if row["linkedin_draft"] else (
                        "Profile" if row["linkedin_profile_url"] else "-"
                    )
                )
            )
            values = (
                shorten(row["business_name"], 28),
                shorten(row["website"], 38),
                join_short(row["emails"]),
                join_short(row["phones"]),
                "Yes" if row["form_prefilled"] else "No",
                email_state,
                whatsapp_state,
                linkedin_state,
                row["status"],
                self.format_time(row["updated_at"]),
            )
            self.tree.insert("", "end", iid=row["business_key"], values=values)
        restored = next((key for key in selected_keys if self.tree.exists(key)), "")
        if restored:
            self.tree.selection_set(restored)
            self.tree.focus(restored)
            self.on_tree_select()

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
            f"LinkedIn: {'sent' if row['linkedin_sent_at'] else ('draft ready' if row['linkedin_draft'] else 'not prepared')}",
        ]
        parts.extend(f"{channel.title()}: {outcome.get('status','pending')} ? {outcome.get('reason','')}"
                     for channel,outcome in row.get('channel_status',{}).items())
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

    def launch_linkedin_browser(self):
        """Open LinkedIn manually in a new Chrome window using the bot profile."""
        config = merge_config(DEFAULT_CONFIG, read_json(CONFIG_PATH))
        linkedin_config = config.get("linkedin", {})
        if not isinstance(linkedin_config, dict) or not to_bool(linkedin_config.get("enabled", True)):
            messagebox.showwarning(
                "LinkedIn disabled",
                "Enable the LinkedIn campaign workflow in Settings first.",
            )
            return
        search_keywords = str(
            linkedin_config.get("search_keywords", "Co Founder and CEO")
            or "Co Founder and CEO"
        ).strip()
        search_url = linkedin_people_search_url(search_keywords)
        self.open_in_bot_chrome(
            search_url,
            f"LinkedIn people search opened: {search_keywords}",
            config=config,
        )

    def open_in_bot_chrome(self, url, success_message, config=None):
        """Open a URL in the persistent Chrome profile shared by the bot."""
        config = config or merge_config(DEFAULT_CONFIG, read_json(CONFIG_PATH))
        chrome_executable = find_chrome_executable(config)
        if chrome_executable is None:
            messagebox.showerror(
                "Chrome not found",
                "Chrome could not be located. Choose the Chrome executable in "
                "Settings > Run, then try again.",
            )
            self.status_var.set("Chrome executable not found")
            return False

        profile_value = str(config.get("chrome_profile_dir", "chrome_profile") or "chrome_profile").strip()
        profile_path = Path(profile_value).expanduser()
        if not profile_path.is_absolute():
            profile_path = APP_DIR / profile_path
        profile_path.mkdir(parents=True, exist_ok=True)

        command = [
            str(chrome_executable),
            f"--user-data-dir={profile_path.resolve()}",
            "--profile-directory=Default",
            "--new-tab",
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
            str(url),
        ]
        try:
            subprocess.Popen(
                command,
                cwd=str(APP_DIR),
                close_fds=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
        except OSError as exc:
            messagebox.showerror("Could not open LinkedIn", str(exc))
            self.status_var.set("LinkedIn browser failed to open")
            return False
        self.status_var.set(success_message)
        return True

    def open_linkedin_campaign(self):
        config = merge_config(DEFAULT_CONFIG, read_json(CONFIG_PATH))
        linkedin_config = config.get("linkedin", {})
        if not isinstance(linkedin_config, dict) or not to_bool(linkedin_config.get("enabled", True)):
            messagebox.showwarning(
                "LinkedIn disabled",
                "Enable the LinkedIn campaign workflow in Settings first.",
            )
            return
        row = self.selected_row()
        if not row:
            row = next((item for item in self.rows if not item["linkedin_sent_at"]), None)
            if row and self.tree.exists(row["business_key"]):
                self.tree.selection_set(row["business_key"])
                self.tree.focus(row["business_key"])
                self.tree.see(row["business_key"])
                self.on_tree_select()
        if not row:
            messagebox.showinfo("LinkedIn campaign", "There are no available leads to prepare.")
            return
        LinkedInLeadDialog(self, row)

    def generate_linkedin_draft(self, row, contact_name="", contact_role="", business_type=""):
        config = merge_config(DEFAULT_CONFIG, read_json(CONFIG_PATH))
        return build_linkedin_message(
            row,
            config,
            contact_name=contact_name,
            contact_role=contact_role,
            business_type=business_type,
        )

    def save_linkedin_details(self, row, values):
        profile_url = normalize_linkedin_url(values.get("profile_url", ""))
        draft = str(values.get("draft", "")).strip()
        config = merge_config(DEFAULT_CONFIG, read_json(CONFIG_PATH))
        linkedin_config = config.get("linkedin", {})
        if not isinstance(linkedin_config, dict):
            linkedin_config = {}
        max_chars = max(100, min(5000, int(linkedin_config.get("max_message_chars", 600) or 600)))
        if len(draft) > max_chars:
            raise ValueError(
                f"The LinkedIn draft is {len(draft)} characters. The configured maximum is {max_chars}."
            )

        channel_status = dict(row.get("channel_status") or {})
        if row.get("linkedin_sent_at"):
            linkedin_status = "sent"
        elif draft:
            linkedin_status = "draft_ready"
        elif profile_url:
            linkedin_status = "profile_added"
        else:
            linkedin_status = "not_prepared"
        channel_status["linkedin"] = {
            "status": linkedin_status,
            "reason": "Manual review required before sending",
        }
        updated_at = datetime.now().isoformat(timespec="seconds")
        with closing(self.connect()) as connection:
            connection.execute(
                """UPDATE outreach SET
                       linkedin_profile_url=?, linkedin_contact_name=?,
                       linkedin_contact_role=?, linkedin_business_type=?,
                       linkedin_draft=?, linkedin_updated_at=?, channel_status=?
                   WHERE business_key=?""",
                (
                    profile_url,
                    str(values.get("contact_name", "")).strip(),
                    str(values.get("contact_role", "")).strip(),
                    str(values.get("business_type", "")).strip(),
                    draft,
                    updated_at,
                    json.dumps(channel_status),
                    row["business_key"],
                ),
            )
            connection.commit()
        self.status_var.set("LinkedIn campaign details saved")
        self.load_data()
        if self.tree.exists(row["business_key"]):
            self.tree.selection_set(row["business_key"])
            self.tree.focus(row["business_key"])
            self.on_tree_select()
        return True

    def open_selected_linkedin(self):
        row = self.selected_row()
        if not row:
            messagebox.showinfo("Select a lead", "Select a lead first.")
            return
        profile_url = row.get("linkedin_profile_url", "")
        if profile_url:
            self.open_in_bot_chrome(
                profile_url,
                "LinkedIn profile opened for manual review",
            )
            return
        query = f"{row['business_name']} CEO founder co-founder"
        self.open_in_bot_chrome(
            linkedin_people_search_url(query),
            "LinkedIn people search opened; save the selected profile URL",
        )

    def copy_selected_linkedin_draft(self):
        row = self.selected_row()
        if not row:
            messagebox.showinfo("Select a lead", "Select a lead first.")
            return
        draft = row.get("linkedin_draft", "")
        if not draft:
            messagebox.showinfo(
                "No LinkedIn draft",
                "Open LinkedIn Campaign and generate a draft first.",
            )
            return
        self.copy_to_clipboard(draft, "LinkedIn draft copied")

    def copy_to_clipboard(self, value, status_message="Copied"):
        self.clipboard_clear()
        self.clipboard_append(str(value))
        self.update_idletasks()
        self.status_var.set(status_message)

    def mark_linkedin_sent(self):
        row = self.selected_row()
        if not row:
            messagebox.showinfo("Select a lead", "Select a lead first.")
            return
        if row.get("linkedin_sent_at"):
            messagebox.showinfo("Already marked", "This LinkedIn message is already marked as sent.")
            return
        if not row.get("linkedin_profile_url") or not row.get("linkedin_draft"):
            messagebox.showinfo(
                "LinkedIn campaign not ready",
                "Save a LinkedIn profile URL and message draft before marking it as sent.",
            )
            return
        if not messagebox.askyesno(
            "Confirm LinkedIn message",
            "Only continue after you have manually sent this message on LinkedIn. Mark it as sent?",
        ):
            return

        channel_status = dict(row.get("channel_status") or {})
        channel_status["linkedin"] = {
            "status": "sent",
            "reason": "Confirmed manually in the dashboard",
        }
        with closing(self.connect()) as connection:
            created = record_event(
                connection,
                EVENT_LINKEDIN_SENT,
                row["business_key"],
                {"name": row["business_name"], "website": row["website"]},
                details="Marked LinkedIn as sent from dashboard",
                recipient=row["linkedin_profile_url"],
            )
            connection.execute(
                """UPDATE outreach
                   SET channel_status=?, linkedin_updated_at=?
                   WHERE business_key=?""",
                (
                    json.dumps(channel_status),
                    datetime.now().isoformat(timespec="seconds"),
                    row["business_key"],
                ),
            )
            connection.commit()
        self.status_var.set("LinkedIn message marked as sent" if created else "Already marked")
        self.load_data()

    def record_manual_event(self, row, event_type, details):
        with closing(self.connect()) as connection:
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
        self.open_in_bot_chrome(
            url,
            "WhatsApp opened in the shared Chrome window",
        )

    def whatsapp_url(self, row):
        phone = next((item for item in row["phones"] if re.sub(r"\D", "", item)), "")
        digits = re.sub(r"\D", "", phone)
        message = self.channel_message(
            row["proposal"],
            "whatsapp"
        )
        if not digits or not message:
            return ""
        return f"https://wa.me/{digits}?text={quote_plus(message)}"

    def open_drafts_csv(self):
        open_path(self.data_dir() / "outreach_drafts.csv")

    def start_bot(self, mode="full", label="automation"):
        if mode == "pending-email":
            email_config = read_json(CONFIG_PATH).get("email", {})
            if not isinstance(email_config, dict) or not to_bool(email_config.get("enabled", False)):
                messagebox.showwarning(
                    "Email sending disabled",
                    "Enable email sending in Settings before starting the pending email queue.",
                )
                self.status_var.set("Email sending is disabled")
                return
        if self.is_running():
            self.status_var.set("Automation already running")
            return
        other_run = self.active_web_dashboard_run()
        if other_run:
            messagebox.showwarning(
                "Automation already running",
                "Another automation was started from the web dashboard "
                f"(PID {other_run['pid']}). Stop it before starting this run."
            )
            self.status_var.set("Another automation is running")
            return
        self.clear_log()
        self.append_log(f"Starting {label}...")
        try:
            python_executable = Path(sys.executable)
            if os.name == "nt" and python_executable.name.lower() == "pythonw.exe":
                console_python = python_executable.with_name("python.exe")
                if console_python.exists():
                    python_executable = console_python
            command = [str(python_executable), "-u", str(APP_DIR / "main.py")]
            if mode != "full":
                command.append(f"--{mode}")
            process_environment = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",
            }
            # The desktop dashboard must respect config.json's headless setting,
            # not an override inherited from a previously launched web server.
            process_environment.pop("AUTOMATION_HEADLESS", None)
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.process = subprocess.Popen(
                command,
                cwd=str(APP_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=process_environment,
                creationflags=creation_flags,
            )
            threading.Thread(target=self.read_process_output, daemon=True).start()
            self.status_var.set(f"Running {label}")
            self.stop_button.pack(side="left", padx=(0, 8), before=self.settings_button)
        except Exception as exc:
            self.process = None
            messagebox.showerror("Could not start bot", str(exc))
            self.status_var.set("Start failed")

    def active_web_dashboard_run(self):
        try:
            state = json.loads(WEB_JOB_STATE_PATH.read_text(encoding="utf-8"))
            pid = int(state.get("pid", 0))
            if pid <= 0 or state.get("status") not in {"running", "stopping"}:
                return None
            if not process_running(pid):
                return None
            return {"pid": pid, "mode": state.get("mode", "automation")}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def read_process_output(self):
        process = self.process
        if not process or not process.stdout:
            return
        try:
            for line in iter(process.stdout.readline, ""):
                self.output_queue.put(("line", line.rstrip("\r\n")))
        except Exception as exc:
            self.output_queue.put(("line", f"Log reader error: {exc}"))
        finally:
            process.stdout.close()
            self.output_queue.put(("ended", process.wait()))

    def poll_process_output(self):
        try:
            while True:
                item = self.output_queue.get_nowait()
                kind, value = item
                if kind == "ended":
                    code = value
                    self.append_log(f"Automation ended with code {code}.")
                    self.status_var.set("Ready")
                    self.stop_button.pack_forget()
                    self.load_data()
                else:
                    self.append_log(value)
                    if "press Enter to close the browser" in value:
                        self.status_var.set("Review the filled forms, then click Finish Review")
        except queue.Empty:
            pass

        if self.process and self.process.poll() is not None:
            self.process = None
            self.status_var.set("Ready")
            self.stop_button.pack_forget()
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
