from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys
from datetime import datetime, date, timedelta
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc
from email.message import EmailMessage
from random import uniform
from time import sleep
import smtplib
import mimetypes
import sys
import os, json, sys
import asyncio
import csv
import re
import base64
import sqlite3
import hashlib
from pathlib import Path
from urllib.parse import quote_plus
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
from google_results import GoogleResultsMixin
from outreach_channels import OutreachChannelsMixin
from outreach_text import clean_outreach_message
from app_paths import get_app_dir
from campaign import load_location_catalog, seed_target_areas
from progress_tracker import (
    EVENT_EMAIL_SENT,
    EVENT_FORM_PREFILLED,
    EVENT_WEBSITE_OPENED,
    EVENT_WHATSAPP_SENT,
    ensure_database,
    outreach_stats,
    record_event,
)



try:
    from cloakbrowser.download import ensure_binary
    from cloakbrowser.config import get_chromium_version, get_default_stealth_args

    _HAS_CLOAK = True
except ImportError:
    _HAS_CLOAK = False


load_dotenv()


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


PROPOSAL_SERVICES = [
    "Website Development",
    "E-commerce / Online Stores",
    "Online Appointment and Booking Systems",
    "Website Redesign",
    "Responsive Mobile-Friendly Websites",
    "SEO & Digital Marketing",
    "Logo Design",
    "Business Email Setup",
    "Accounting Software",
    "POS Solutions",
    "Restaurant POS and Website Ordering Integration",
    "Quotations, Invoicing, Expense, and Profit/Loss Reporting",
    "CRM and Customer Management Solutions",
    "Inventory Management Solutions",
    "E-Invoicing Software",
    "Website Maintenance & Support",
    "Domain & Hosting Setup",
    "Custom Business Software",
]


PARTNER_BUSINESS_PATTERNS = (
    r"\bsoftware (?:company|development|developer|solutions?|services?)\b",
    r"\bcustom software\b",
    r"\b(?:it|information technology) (?:company|consulting|consultancy|solutions?|services?|support)\b",
    r"\bweb(?:site)? (?:design|development|developer|agency|solutions?)\b",
    r"\b(?:mobile )?app development\b",
    r"\bdigital marketing\b",
    r"\b(?:marketing|advertising|seo|social media|branding|creative) agency\b",
    r"\binternet marketing service\b",
    r"\bmarketing consultant\b",
    r"\btechnology (?:company|consulting|consultancy|solutions?|services?)\b",
)


class SafePromptValues(dict):
    def __missing__(self, key):
        return "{" + str(key) + "}"


class Automation(GoogleResultsMixin, OutreachChannelsMixin):
    
    def write_log_header(self, title, width=70):
        self._log("=" * width)
        self._log(title.center(width))
        self._log("=" * width)

    
    def _log(self, message):
        print(f"[Marketing Bot] {message}", flush=True)

        # Skip file logging when started from dashboard.py
        if sys.argv[0].endswith("dashboard.py"):
            return

        from session_logger import append_log_line

        try:
            SCRIPT_DIR = get_app_dir()
            append_log_line(message, SCRIPT_DIR)
        except OSError:
            pass

    def __init__(self, mode="full", retry_business_key=""):
        self.config_path = Path(get_app_dir()) / 'config.json'
        self.config = self.read_json(str(self.config_path))
        self.mode = mode
        

        if self.config:
            self.write_log_header("Marketing Bot started.")
            self._log("Settings loaded from config.json.")
        else:
            self._log("Warning: config.json is missing or empty — check your dashboard settings.")

        headless_override = os.environ.get("AUTOMATION_HEADLESS")
        self.headless = (
            str(headless_override).strip().lower() in {"1", "true", "yes", "on"}
            if headless_override is not None
            else bool(self.config.get('headless', False))
        )
        self.limit = max(1, int(self.config.get('limit', 10)))
        self.search_query = str(self.config.get('search_query', 'business near me')).strip()
        self.data_dir = Path(self.config.get('data_dir', 'data')).expanduser()
        if not self.data_dir.is_absolute():
            self.data_dir = Path(get_app_dir()) / self.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.data_dir / 'outreach.sqlite3')
        self.db.row_factory = sqlite3.Row
        ensure_database(self.db)
        self.run_id = self.db.execute(
            "INSERT INTO outreach_runs(mode,search_query,target,started_at,status,pid) VALUES (?,?,?,?,?,?)",
            (mode, self.search_query, self.limit, datetime.now().isoformat(timespec="seconds"), "running", os.getpid())
        ).lastrowid
        self.db.commit()
        self.driver = None
        self.whatsapp_login_wait_used = False
        self.whatsapp_window = None
        self.current_area = {}

        if self.mode in {"pending-email", "retry-email"}:
            try:
                if self.mode == "retry-email":
                    self.process_retry_channel("email", retry_business_key)
                    reason = "Email retry checked"
                else:
                    self.process_pending_channel("email")
                    reason = "Pending email queue checked"
                self.finish_run("completed", reason)
            except Exception as exc:
                self.finish_run("failed", str(exc))
                raise
            finally:
                self.db.close()
            return

        browser_mode = "headless (no window)" if self.headless else "visible"
        self._log(f"Opening Chrome browser — {browser_mode}...")
        configured_profile = Path(
            self.config.get("chrome_profile_dir", "chrome_profile")
        ).expanduser()
        if not configured_profile.is_absolute():
            configured_profile = Path(get_app_dir()) / configured_profile
        configured_profile.mkdir(parents=True, exist_ok=True)
        self.chrome_profile_dir = str(configured_profile.resolve())
        self._log(f"Using persistent Chrome profile: {self.chrome_profile_dir}")
        try:
            self.driver = self.get_driver(
                profile_dir=self.chrome_profile_dir,
                headless=self.headless
            )
        except Exception as e:
            self._log(f"Error connecting Chromium: {e}")
            self.driver = self.get_driver_default(
                profile_dir=self.chrome_profile_dir,
                headless=self.headless
            )

        self.driver.set_page_load_timeout(45)
        self._log("Browser ready.")
        self.iframe_found = False
        if self.mode in {"pending-whatsapp", "retry-whatsapp"}:
            try:
                if self.mode == "retry-whatsapp":
                    self.process_retry_channel("whatsapp", retry_business_key)
                    reason = "WhatsApp retry checked"
                else:
                    self.process_pending_channel("whatsapp")
                    reason = "Pending WhatsApp queue checked"
                self.finish_run("completed", reason)
            except Exception as exc:
                self.finish_run("failed", str(exc))
                raise
            finally:
                self._close_browser_safely()
        else:
            self.start_automation()

    def process_pending_channel(self, channel):
        """Send drafts that do not yet have a sent event for one channel."""
        if channel == "email" and not self.email_sending_enabled():
            self._log("Pending email run skipped: email sending is disabled in settings.")
            return 0
        event_type = EVENT_WHATSAPP_SENT if channel == "whatsapp" else EVENT_EMAIL_SENT
        rows = self.db.execute(
            """SELECT o.*,
                      (o.status IN ('email_sent', 'fallback_sent')
                       OR EXISTS(SELECT 1 FROM outreach_events e
                             WHERE e.business_key = o.business_key
                               AND e.event_type = ?)) AS email_sent,
                      (o.status IN ('whatsapp_sent', 'fallback_sent')
                       OR EXISTS(SELECT 1 FROM outreach_events e
                             WHERE e.business_key = o.business_key
                               AND e.event_type = ?)) AS whatsapp_sent
               FROM outreach o
              WHERE NOT EXISTS (
                    SELECT 1 FROM outreach_events pending
                     WHERE pending.business_key = o.business_key
                       AND pending.event_type = ?)
                AND (CASE WHEN ? = ?
                          THEN o.status NOT IN ('whatsapp_sent', 'fallback_sent')
                          ELSE o.status NOT IN ('email_sent', 'fallback_sent')
                     END)
              ORDER BY COALESCE(o.updated_at, '') ASC""",
            (
                EVENT_EMAIL_SENT, EVENT_WHATSAPP_SENT, event_type,
                event_type, EVENT_WHATSAPP_SENT,
            ),
        ).fetchall()

        self._log(f"Found {len(rows)} pending {channel} draft(s).")
        section = self.config.setdefault(channel, {})
        if isinstance(section, dict):
            section["auto_send"] = True

        sent_count = 0
        for index, row in enumerate(rows, start=1):
            result = self.stored_result(row)
            business_key = row[0]
            self.register_candidate(business_key, {'name': result['name'], 'url': result['website']})
            self._log(
                f"[{index}/{len(rows)}] Sending pending {channel} for "
                f"{result['name'] or result['website'] or business_key}."
            )
            try:
                sent = getattr(self, f'send_{channel}_message')(result, business_key)
            except Exception as exc:
                sent = self.channel_outcome(result, channel, 'failed', str(exc))
            self.db.execute('UPDATE run_businesses SET processed=1,status=? WHERE run_id=? AND business_key=?',
                            ('sent' if sent else 'error', self.run_id, business_key))
            self.update_result_status(result)
            self.save_outreach(business_key, result)
            sent_count += int(sent)

        self._log(
            f"Pending {channel} run completed: {sent_count} sent, "
            f"{len(rows) - sent_count} skipped or failed."
        )

    def process_retry_channel(self, channel, business_key):
        """Retry one saved draft without regenerating its proposal."""
        if channel == "email" and not self.email_sending_enabled():
            self._log("Email retry skipped: email sending is disabled in settings.")
            return False
        if not business_key:
            raise ValueError("A business key is required for a retry")
        row = self.db.execute(
            """SELECT o.*,
                      (o.status IN ('email_sent', 'fallback_sent')
                       OR EXISTS(SELECT 1 FROM outreach_events e
                             WHERE e.business_key=o.business_key AND e.event_type=?)) email_sent,
                      (o.status IN ('whatsapp_sent', 'fallback_sent')
                       OR EXISTS(SELECT 1 FROM outreach_events e
                             WHERE e.business_key=o.business_key AND e.event_type=?)) whatsapp_sent
                 FROM outreach o WHERE o.business_key=?""",
            (EVENT_EMAIL_SENT, EVENT_WHATSAPP_SENT, business_key),
        ).fetchone()
        if not row:
            raise ValueError("Lead not found")
        result = self.stored_result(row)
        if not result["proposal"].strip():
            raise ValueError("Lead has no saved generated message")
        result["_manual_retry"] = True
        section = self.config.setdefault(channel, {})
        if isinstance(section, dict):
            section["auto_send"] = True
        self.register_candidate(business_key, {"name": result["name"], "url": result["website"]})
        self._log(f"Retrying saved {channel} message for {result['name'] or result['website'] or business_key}.")
        try:
            sent = getattr(self, f"send_{channel}_message")(result, business_key)
        except Exception as exc:
            sent = self.channel_outcome(result, channel, "failed", str(exc))
        self.db.execute(
            "UPDATE run_businesses SET processed=1,status=? WHERE run_id=? AND business_key=?",
            ("sent" if sent else "error", self.run_id, business_key),
        )
        self.update_result_status(result)
        self.save_outreach(business_key, result)
        self._log(f"Saved {channel} retry result: {'sent' if sent else 'not sent'}.")
        return sent

    def stored_result(self, row):
        """Rehydrate a stored lead, including both persisted channel outcomes."""
        try:
            channel_status = json.loads(row["channel_status"] or "{}")
        except (TypeError, ValueError):
            channel_status = {}
        return {
            "name": row["business_name"] or "",
            "website": row["website"] or "",
            "contact_page": row["contact_page"] or "",
            "emails": self.parse_stored_list(row["emails"]),
            "phones": self.parse_stored_list(row["phones"]),
            "proposal": row["proposal"] or "",
            "form_prefilled": bool(row["form_prefilled"]),
            "status": row["status"] or "draft_ready",
            "email_sent": bool(row["email_sent"]),
            "whatsapp_sent": bool(row["whatsapp_sent"]),
            "channel_status": channel_status if isinstance(channel_status, dict) else {},
            "whatsapp_phones": self.parse_stored_list(row["whatsapp_phones"]),
            "area_key": row["area_key"] or "",
            "last_error": row["last_error"] or "",
            "run_id": self.run_id,
        }

    @staticmethod
    def parse_stored_list(value):
        if not value:
            return []
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            return [part.strip() for part in str(value).split(";") if part.strip()]

    def element_exists(self, selector: str, timeout: int = 30) -> bool:
        by = By.XPATH if selector.startswith("/") or selector.startswith("(") else By.CSS_SELECTOR
        try:
            WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((by, selector)))
            return True
        except:
            return False

    def read_json(self, file_path):
        """ Read JSON configuration file."""

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)

        except Exception as e:
            self._log(f"JSON read error: {e}")
            self._log(f"File path: {file_path}")
            return {}

    @staticmethod
    def get_driver(profile_dir: str = "./chrome_profile", headless: bool = False) -> uc.Chrome:

        options = uc.ChromeOptions()

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        options.add_argument("--disable-gpu")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")

        # 🔥 IMPORTANT: allow popups
        options.add_argument("--disable-popup-blocking") 
        options.add_argument("--disable-notifications")

        # keep same session (recommended for popups)
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--profile-directory=Default")

        #avoid automation detection issue
        options.add_argument("--start-maximized")
        if headless:
            options.add_argument("--headless=new")

        kwargs = {}
        if _HAS_CLOAK:
            options.binary_location = ensure_binary()
            for arg in get_default_stealth_args():
                options.add_argument(arg)
            kwargs["version_main"] = int(get_chromium_version().split(".")[0])

        return uc.Chrome(options=options, **kwargs)

    @staticmethod
    def get_driver_default(profile_dir="./chrome_profile" , headless=False):
        options = Options()

         # Use existing Chrome profile
        profile_dir = os.path.abspath(profile_dir)
        options.add_argument(f"--user-data-dir={profile_dir}")

        options.add_argument("--profile-directory=Default")

        # Stability options
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        # Browser behavior
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--start-maximized")

        # Optional: headless mode
        if headless:
            options.add_argument("--headless=new")

        return webdriver.Chrome(options=options)


    def random_sleep(self):
        sleep(uniform(1.2, 5.8))


    def _close_browser_safely(self) -> None:
        try:
            if self.driver:
                self.driver.quit()
                self._log("Browser closed.")
        except Exception:
            pass
        self.driver = None
        try:
            self.db.close()
        except Exception:
            pass


    
    # =========================================================
    # START AUTOMATION
    # =========================================================

    def finish_run(self, status, reason):
        self.db.execute("UPDATE outreach_runs SET status=?,stop_reason=?,finished_at=? WHERE id=?",
                        (status, reason, datetime.now().isoformat(timespec="seconds"), self.run_id))
        self.db.commit()

    def start_automation(self):
        self._log("Automation run started.")
        try:
            campaign_config = self.config.get("campaign", {})
            if isinstance(campaign_config, dict) and campaign_config.get("enabled"):
                results = self.run_location_campaign(campaign_config)
            else:
                google_page = self.search_business()
                if google_page is None:
                    raise RuntimeError("Could not open Google")
                results = self.process_all_websites(google_page, limit=self.limit)
            _, run = outreach_stats(self.db)
            self._log(f"Run finished: {run.get('found', 0)} found, {run.get('new', 0)} new, "
                      f"{run.get('already_contacted', 0)} already contacted, {run.get('processed', 0)} processed, "
                      f"{run.get('whatsapp', 0)} WhatsApp sent, {run.get('emails', 0)} emails sent. "
                      f"{run.get('stop_reason', '')}")
            if (not self.headless and self.config.get('review_mode', True)
                    and self.config.get('keep_prefilled_tabs_open', True)
                    and any(item.get('form_prefilled') for item in results)):
                try:
                    input("Review the prefilled contact-form tabs, then press Enter to close the browser...")
                except EOFError:
                    self._log("No interactive input available; closing review tabs.")
        except Exception as exc:
            self.finish_run('failed', str(exc))
            raise
        finally:
            self._close_browser_safely()

    def run_location_campaign(self, campaign_config):
        """Process an ordered, persistent country/city/area campaign queue."""
        catalog_value = str(campaign_config.get("locations_file", "locations/uae.json")).strip()
        catalog_path = Path(catalog_value).expanduser()
        if not catalog_path.is_absolute():
            catalog_path = Path(get_app_dir()) / catalog_path
        country = str(campaign_config.get("country", "United Arab Emirates")).strip()
        locations = load_location_catalog(catalog_path, country=country)
        added = seed_target_areas(self.db, locations)
        self._log(
            f"Territory campaign loaded: {len(locations)} areas, {added} newly queued."
        )

        max_areas = max(0, int(campaign_config.get("max_areas_per_run", 1)))
        per_area_limit = max(1, int(campaign_config.get("businesses_per_area", self.limit)))
        query_template = str(campaign_config.get(
            "query_template", "businesses in {area}, {city}, {region}, {country}"
        )).strip()
        queue = self.db.execute(
            """SELECT * FROM target_areas
               WHERE country=? AND status IN ('pending','in_progress','blocked')
               ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'blocked' THEN 1 ELSE 2 END,
                        position, area_key""",
            (country,),
        ).fetchall()
        if max_areas:
            queue = queue[:max_areas]
        self.db.execute(
            "UPDATE outreach_runs SET search_query=?,target=? WHERE id=?",
            (f"Area campaign: {country}", per_area_limit * len(queue), self.run_id),
        )
        self.db.commit()

        all_results = []
        campaign_status = "completed"
        stop_reason = "No pending campaign areas"
        for row in queue:
            area = dict(row)
            self.current_area = area
            try:
                query = query_template.format_map(SafePromptValues(area)).strip()
            except Exception:
                query = f"businesses in {area['area']}, {area['city']}, {area['country']}"
            self.search_query = query
            now = datetime.now().isoformat(timespec="seconds")
            self.db.execute(
                """UPDATE target_areas SET status='in_progress',attempt_count=attempt_count+1,
                          last_query=?,started_at=CASE WHEN started_at='' THEN ? ELSE started_at END,
                          updated_at=?,last_error=''
                   WHERE area_key=?""",
                (query, now, now, area["area_key"]),
            )
            self.db.commit()
            self._log(
                f"Campaign area {area['position']}/{len(locations)}: "
                f"{area['area']}, {area['city']}, {area['region']}"
            )

            google_page = self.search_business()
            if google_page is None:
                raise RuntimeError("Could not open Google")
            area_results = self.process_all_websites(
                google_page,
                limit=per_area_limit,
                finalize_run=False,
            )
            all_results.extend(area_results)
            outcome = getattr(self, "last_search_outcome", {})
            reason = outcome.get("reason", "Search stopped")
            area_status = "in_progress"
            if outcome.get("status") == "blocked":
                area_status = "blocked"
                campaign_status = "blocked"
            elif (
                reason.startswith("No next Google page")
                or reason.startswith("Google returned a repeated")
                or reason.startswith("Google page limit reached")
            ):
                area_status = "completed"

            found = self.db.execute(
                "SELECT COUNT(DISTINCT business_key) FROM run_businesses WHERE area_key=?",
                (area["area_key"],),
            ).fetchone()[0]
            processed = self.db.execute(
                """SELECT COUNT(DISTINCT business_key) FROM run_businesses
                   WHERE area_key=? AND processed=1""", (area["area_key"],)
            ).fetchone()[0]
            sent = self.db.execute(
                """SELECT COUNT(*) FROM outreach_events
                   WHERE area_key=? AND event_type IN (?,?)""",
                (area["area_key"], EVENT_WHATSAPP_SENT, EVENT_EMAIL_SENT),
            ).fetchone()[0]
            finished = datetime.now().isoformat(timespec="seconds")
            self.db.execute(
                """UPDATE target_areas SET status=?,businesses_found=?,businesses_processed=?,
                          messages_sent=?,completed_at=?,updated_at=?,last_error=?
                   WHERE area_key=?""",
                (
                    area_status, found, processed, sent,
                    finished if area_status == "completed" else "", finished,
                    reason if area_status == "blocked" else "", area["area_key"],
                ),
            )
            self.db.commit()
            self._log(
                f"Area status: {area_status}; {found} businesses stored, "
                f"{sent} messages sent. {reason}"
            )
            stop_reason = f"Campaign paused after {area['area']}: {reason}"
            # Preserve a strict geographic queue: do not advance to the next
            # area until the current area's accessible Google result pages
            # have been exhausted.
            if area_status != "completed":
                break

        self.current_area = {}
        self.finish_run(campaign_status, stop_reason)
        return all_results


    def open_website(self, website):

        """
        Opens a website in a NEW browser tab.
        """

        url = website.get(
            "url",
            ""
        )

        if not url:

            self._log(
                "Website URL is empty."
            )

            return None

        self._log(
            f"Opening website: {url}"
        )

        original_window = None

        try:

            # Save current tab
            original_window = (
                self.driver.current_window_handle
            )

            # Open new tab
            self.driver.switch_to.new_window(
                "tab"
            )

            # Open website
            self.driver.get(url)

            # Wait for body
            try:

                WebDriverWait(
                    self.driver,
                    15
                ).until(
                    EC.presence_of_element_located(
                        (By.TAG_NAME, "body")
                    )
                )

            except TimeoutException:

                self._log(
                    f"Page body timeout: {url}"
                )

            self.random_sleep()

            return {
                "window_handle":
                    self.driver.current_window_handle,

                "original_window":
                    original_window
            }

        except Exception as e:

            self._log(
                f"Error opening {url}: "
                f"{type(e).__name__}: {e}"
            )

            # Close failed tab
            try:

                if len(self.driver.window_handles) > 1:

                    self.driver.close()

                    if original_window:
                        self.driver.switch_to.window(
                            original_window
                        )

            except Exception:
                pass

            return None

    # =========================================================
    # FIND CONTACT PAGE
    # =========================================================

    def find_contact_page(self, page):

        """
        Search the current website for a Contact page.
        """

        self._log(
            "Searching for Contact page..."
        )

        contact_keywords = [
            "contact",
            "contact us",
            "contact-us",
            "contactus",
            "get in touch",
            "reach us"
        ]

        candidates = []

        try:

            current_url = page.current_url

            # Selenium
            links = page.find_elements(
                By.CSS_SELECTOR,
                "a[href]"
            )

            for link in links:

                try:

                    href = link.get_attribute(
                        "href"
                    )

                    if not href:
                        continue

                    # Get visible text
                    try:

                        text = link.text.strip().lower()

                    except Exception:

                        text = ""

                    href_lower = href.lower()

                    # Combine visible text and URL
                    value = (
                        f"{text} {href_lower}"
                    )

                    # Check contact keywords
                    if not any(
                        keyword in value
                        for keyword in contact_keywords
                    ):
                        continue

                    # Convert relative URL
                    contact_url = urljoin(
                        current_url,
                        href
                    )

                    # Only HTTP / HTTPS
                    if not contact_url.startswith(
                        ("http://", "https://")
                    ):
                        continue

                    # Remove duplicates
                    if contact_url not in candidates:

                        candidates.append(
                            contact_url
                        )

                except Exception:

                    continue

            if not candidates:

                self._log(
                    "Contact page not found."
                )

                return None

            # Usually first contact link
            contact_url = candidates[0]

            self._log(
                f"Contact page found: {contact_url}"
            )

            return contact_url

        except Exception as e:

            self._log(
                f"Error finding contact page: {e}"
            )

            return None


    # =========================================================
    # EMAIL EXTRACTION
    # =========================================================

    def find_emails(self, page):

        email_regex = re.compile(
            r"\b[A-Za-z0-9._%+-]+"
            r"@[A-Za-z0-9.-]+\."
            r"[A-Za-z]{2,}\b"
        )

        try:

            # Get entire page text
            body = WebDriverWait(
                page,
                10
            ).until(
                EC.presence_of_element_located(
                    (By.TAG_NAME, "body")
                )
            )

            text = body.text

            href_text = []
            for link in page.find_elements(By.CSS_SELECTOR, "a[href]"):
                href = link.get_attribute("href") or ""
                if href.startswith("mailto:"):
                    href_text.append(href)

            emails = sorted(
                set(
                    email_regex.findall(
                        text + " " + " ".join(href_text)
                    )
                )
            )

            return emails

        except Exception as e:

            self._log(
                f"Email extraction error: {e}"
            )

            return []


    # =========================================================
    # PHONE EXTRACTION
    # =========================================================

    def find_phone_numbers(self, page):

        phone_regex = re.compile(
            r"(?<!\d)"
            r"(?:\+?\d{1,3}[\s.-]?)?"
            r"(?:\(?\d{2,4}\)?[\s.-]?)?"
            r"\d{3,4}[\s.-]?\d{3,4}"
            r"(?!\d)"
        )

        try:

            body = WebDriverWait(
                page,
                10
            ).until(
                EC.presence_of_element_located(
                    (By.TAG_NAME, "body")
                )
            )

            text = body.text

            href_text = []
            for link in page.find_elements(By.CSS_SELECTOR, "a[href]"):
                href = link.get_attribute("href") or ""
                if (
                    href.startswith("tel:")
                    or "wa.me/" in href
                    or "whatsapp.com/send" in href
                ):
                    href_text.append(href)

            numbers = phone_regex.findall(
                text + " " + " ".join(href_text)
            )

            cleaned = []

            for number in numbers:

                number = re.sub(
                    r"\s+",
                    " ",
                    number
                ).strip()

                digits = re.sub(
                    r"\D",
                    "",
                    number
                )

                # Avoid tiny numbers
                if len(digits) < 7:
                    continue

                # Avoid duplicates
                if number not in cleaned:

                    cleaned.append(
                        number
                    )

            return cleaned

        except Exception as e:

            self._log(
                f"Phone extraction error: {e}"
            )

            return []

    def find_whatsapp_numbers(self, page):
        numbers = []

        try:
            links = page.find_elements(By.CSS_SELECTOR, "a[href]")

            for link in links:
                href = link.get_attribute("href") or ""
                href_lower = href.lower()

                if (
                    "wa.me/" not in href_lower
                    and "whatsapp.com/send" not in href_lower
                    and "api.whatsapp.com/send" not in href_lower
                ):
                    continue

                parsed = urlparse(href)
                candidate = ""

                if "wa.me" in parsed.netloc:
                    candidate = parsed.path.strip("/")
                else:
                    match = re.search(r"(?:phone=)(\+?\d+)", href)
                    if match:
                        candidate = match.group(1)

                digits = re.sub(r"\D", "", candidate)

                if len(digits) >= 7 and candidate not in numbers:
                    numbers.append(candidate)

        except Exception as e:
            self._log(
                f"WhatsApp link extraction error: {e}"
            )

        return numbers

    def extract_phone_numbers(self, text):
        matches = re.findall(
            r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}(?!\d)",
            text or ""
        )
        return list(dict.fromkeys(
            value.strip() for value in matches
            if len(re.sub(r"\D", "", value)) >= 7
        ))

    def audit_current_website(self):
        """Return conservative, observable homepage findings for outreach."""
        try:
            facts = self.driver.execute_script(r"""
                const attr = (selector, name) => document.querySelector(selector)?.getAttribute(name) || '';
                const images = Array.from(document.images || []);
                const forms = Array.from(document.forms || []);
                const resources = Array.from(document.querySelectorAll('img[src],script[src],link[href]'));
                return {
                    url: location.href,
                    title: (document.title || '').trim(),
                    description: attr('meta[name="description" i]', 'content').trim(),
                    canonical: attr('link[rel="canonical" i]', 'href').trim(),
                    viewport: attr('meta[name="viewport" i]', 'content').trim(),
                    lang: (document.documentElement.getAttribute('lang') || '').trim(),
                    h1Count: document.querySelectorAll('h1').length,
                    imageCount: images.length,
                    imagesMissingAlt: images.filter(img => !img.hasAttribute('alt') || !img.alt.trim()).length,
                    insecureForms: forms.filter(form => (form.action || '').toLowerCase().startsWith('http://')).length,
                    mixedResources: resources.filter(element => {
                        const value = element.getAttribute('src') || element.getAttribute('href') || '';
                        return location.protocol === 'https:' && value.toLowerCase().startsWith('http://');
                    }).length
                };
            """) or {}
        except Exception as exc:
            self._log(f"Website audit could not be completed: {exc}")
            return []

        findings = []
        url = str(facts.get("url", "") or "")
        title = str(facts.get("title", "") or "").strip()
        description = str(facts.get("description", "") or "").strip()
        if url.lower().startswith("http://"):
            findings.append("The homepage is served over HTTP rather than HTTPS.")
        if not title:
            findings.append("The homepage does not provide a page title for search results.")
        elif len(title) < 20:
            findings.append("The homepage title is very short and may not describe the business clearly in search results.")
        elif len(title) > 65:
            findings.append("The homepage title is long and may be truncated in search results.")
        if not description:
            findings.append("The homepage has no meta description for search-result summaries.")
        elif len(description) < 70:
            findings.append("The homepage meta description is very short.")
        elif len(description) > 165:
            findings.append("The homepage meta description is long and may be truncated in search results.")
        if not str(facts.get("viewport", "") or "").strip():
            findings.append("The homepage is missing a mobile viewport declaration, which can affect mobile presentation.")
        h1_count = int(facts.get("h1Count", 0) or 0)
        if h1_count == 0:
            findings.append("The homepage has no main H1 heading.")
        elif h1_count > 1:
            findings.append(f"The homepage contains {h1_count} H1 headings, which weakens the page hierarchy.")
        if not str(facts.get("canonical", "") or "").strip():
            findings.append("The homepage does not declare a canonical URL.")
        if not str(facts.get("lang", "") or "").strip():
            findings.append("The page language is not declared in the HTML.")
        image_count = int(facts.get("imageCount", 0) or 0)
        missing_alt = int(facts.get("imagesMissingAlt", 0) or 0)
        if image_count and missing_alt:
            findings.append(f"{missing_alt} of {image_count} homepage images are missing descriptive alt text.")
        insecure_forms = int(facts.get("insecureForms", 0) or 0)
        if insecure_forms:
            findings.append(f"{insecure_forms} form(s) submit to an insecure HTTP address.")
        mixed_resources = int(facts.get("mixedResources", 0) or 0)
        if mixed_resources:
            findings.append(f"The HTTPS page loads {mixed_resources} resource(s) over insecure HTTP.")
        return findings[:6]


    # =========================================================
    # PROCESS ONE WEBSITE
    # =========================================================

    def process_website(self, website):

        name = website.get(
            "name",
            ""
        )

        url = website.get(
            "url",
            ""
        )

        profile_phones = list(dict.fromkeys(website.get("phones", [])))
        has_website = bool(
            url
            or website.get("has_website")
            or website.get("website_redirect_url")
        )

        self._log(
            f"Processing: {url}"
        )

        result = {
            "name": name,
            "website": url,
            "business_context": (
                website.get("profile_text")
                or website.get("category")
                or self.search_query
                or ""
            ),
            "contact_page": "",
            "emails": list(dict.fromkeys(website.get("emails", []))),
            "phones": profile_phones[:],
            "proposal": "",
            "form_prefilled": False,
            "email_sent": False,
            "whatsapp_sent": False,
            "status": "processing",
            "run_id": getattr(self, "run_id", None),
            "channel_status": {},
            "whatsapp_phones": website.get("whatsapp_phones", [])
        }
        result.update({
            key: website.get(key, "")
            for key in ("area_key", "country", "region", "city", "area")
        })

        business_key = self.business_key(website)
        if self.was_previously_processed(business_key):
            self._log(f"Skipping previously processed business: {name or url}")
            result["status"] = "skipped_duplicate"
            return result

        # Check the Google Business Profile phone before writing a message.
        # When a website exists, delay generation/sending until its homepage
        # has been audited so the outreach can cite real observations.
        if profile_phones:
            self._log(
                f"Google profile phone found for {name or 'business'}; "
                "checking WhatsApp before preparing the message."
            )
            try:
                if has_website:
                    self.preflight_whatsapp(result, business_key)
                else:
                    self.attempt_preferred_outreach(result, website, business_key)
            except Exception as exc:
                result["last_error"] = str(exc)
                self._log(f"Google-profile outreach error: {exc}")
            whatsapp_status = result.get("channel_status", {}).get("whatsapp", {}).get("status")
            terminal = (
                result.get("whatsapp_sent")
                or result.get("email_sent")
                or whatsapp_status in {"uncertain", "review", "already_sent"}
                or not has_website
            )
            if terminal:
                self.update_result_status(result)
                self.save_outreach(business_key, result)
                if result.get("proposal"):
                    self.append_draft(result)
                return result
            # Keep an interrupted preflight eligible for a future retry until
            # the website email fallback has actually been checked.
            result["status"] = "processing"
            self.save_outreach(business_key, result)
            self._log("Opening the business website for contact discovery and a homepage audit.")

        # Resolve opaque Google /goto Website buttons only when the listing is
        # ready for contact discovery and homepage analysis.
        redirect_url = website.get("website_redirect_url", "")
        if not url and redirect_url:
            resolved_url = self.resolve_google_website(redirect_url) or ""
            if resolved_url:
                website["url"] = resolved_url
                url = resolved_url
                result["website"] = resolved_url

        if url and self.is_ignored_url(url):
            self._log(f"Skipping configured ignored URL: {url}")
            result["status"] = "ignored_url"
            return result

        if not url:
            try:
                self.attempt_preferred_outreach(result, website, business_key)
                self.update_result_status(result)
                self.save_outreach(business_key, result)
                if result.get("proposal"):
                    self.append_draft(result)
            except Exception as exc:
                result["status"] = "draft_error"
                result["last_error"] = str(exc)
                self.save_outreach(business_key, result)
                self._log(f"Draft generation error: {exc}")
            return result

        # Open website in new tab
        tab_info = self.open_website(
            website
        )

        if not tab_info:
            result['last_error'] = 'Website could not be opened'
            try:
                self.attempt_preferred_outreach(result, website, business_key)
            except Exception as exc:
                self._log(f'Outreach error: {exc}')
            self.update_result_status(result)
            result['status'] = 'website_error'
            self.save_outreach(business_key, result)
            return result

        try:
            record_event(
                self.db,
                EVENT_WEBSITE_OPENED,
                business_key,
                result,
                details="Website tab opened by automation",
            )
        except Exception as exc:
            self._log(f"Progress event error: {exc}")

        original_window = tab_info[
            "original_window"
        ]

        current_window = tab_info[
            "window_handle"
        ]

        try:

            # Make sure we are on website tab
            self.driver.switch_to.window(
                current_window
            )

            # -----------------------------------------
            # CHECK HOMEPAGE
            # -----------------------------------------

            self._log(
                "Checking homepage..."
            )

            emails = self.find_emails(
                self.driver
            )

            phones = self.find_phone_numbers(
                self.driver
            )

            whatsapp_numbers = self.find_whatsapp_numbers(
                self.driver
            )

            result["whatsapp_phones"] = whatsapp_numbers
            result["emails"] = emails

            result["phones"] = sorted(
                set(
                    result["phones"] + phones
                    + whatsapp_numbers
                )
            )

            self._log(
                f"Emails found: {emails}"
            )

            self._log(
                f"Phones found: {phones}"
            )

            audit_findings = self.audit_current_website()
            website["audit_findings"] = audit_findings
            result["website_audit"] = audit_findings
            if audit_findings:
                self._log(
                    "Website audit findings: " + " | ".join(audit_findings)
                )
            else:
                self._log("Website audit found no safely reportable homepage issues.")

            # -----------------------------------------
            # FIND CONTACT PAGE
            # -----------------------------------------

            contact_url = self.find_contact_page(
                self.driver
            )

            if contact_url:

                result["contact_page"] = (
                    contact_url
                )

                self._log(
                    "Opening contact page..."
                )

                try:

                    self.driver.get(
                        contact_url
                    )

                    # Wait for page
                    try:

                        WebDriverWait(
                            self.driver,
                            15
                        ).until(
                            EC.presence_of_element_located(
                                (By.TAG_NAME, "body")
                            )
                        )

                    except TimeoutException:

                        self._log(
                            "Contact page body timeout."
                        )

                    self.random_sleep()

                    # ---------------------------------
                    # EXTRACT CONTACT PAGE INFORMATION
                    # ---------------------------------

                    contact_emails = (
                        self.find_emails(
                            self.driver
                        )
                    )

                    contact_phones = (
                        self.find_phone_numbers(
                            self.driver
                        )
                    )

                    contact_whatsapp_numbers = (
                        self.find_whatsapp_numbers(
                            self.driver
                        )
                    )

                    # Merge emails
                    result["emails"] = sorted(
                        set(
                            result["emails"]
                            + contact_emails
                        )
                    )

                    result["whatsapp_phones"] = list(dict.fromkeys(result["whatsapp_phones"] + contact_whatsapp_numbers))

                    # Merge phones
                    result["phones"] = sorted(
                        set(
                            result["phones"]
                            + contact_phones
                            + contact_whatsapp_numbers
                        )
                    )

                    self._log(
                        f"Contact emails: {contact_emails}"
                    )

                    self._log(
                        f"Contact phones: {contact_phones}"
                    )

                    

                except Exception as e:

                    self._log(
                        f"Contact page error: {e}"
                    )

            # Prepare every channel supported by this lead. A website can use
            # its contact form even when no email address is discovered.
            try:
                self.attempt_preferred_outreach(result, website, business_key)

                if result.get("proposal"):
                    contact_name = self.get_config_or_env(
                        "contact_name",
                        "CONTACT_US_NAME"
                    ).strip()
                    contact_email = self.get_config_or_env(
                        "contact_email",
                        "CONTACT_US_EMAIL"
                    ).strip()
                    contact_phone = self.get_config_or_env(
                        "contact_phone",
                        "CONTACT_US_PHONE"
                    ).strip()

                    self._log(
                        f"Contact name configured: {bool(contact_name)}"
                    )

                    self._log(
                        f"Contact email configured: {bool(contact_email)}"
                    )

                    self._log(
                        f"Contact phone configured: {bool(contact_phone)}"
                    )

                    include_form_contact_details = self.get_bool_setting(
                        "website_forms",
                        "include_contact_details",
                        default=True
                    )
                    form_message = self.channel_message(
                        result,
                        "website_forms"
                    )

                    form_found = self.fill_contact_form(
                        name=contact_name if include_form_contact_details else "",
                        email=contact_email if include_form_contact_details else "",
                        phone=contact_phone if include_form_contact_details else "",
                        message=form_message
                    )

                    if form_found:

                        self._log(
                            "Contact form filled successfully."
                        )

                        result["form_prefilled"] = True
                        submission_status = getattr(
                            self, "last_form_submission_status", "review"
                        )
                        try:
                            record_event(
                                self.db,
                                EVENT_FORM_PREFILLED,
                                business_key,
                                result,
                                details=(
                                    "Contact form submission confirmed"
                                    if submission_status == "submitted"
                                    else "Contact form submit clicked; confirmation unavailable"
                                    if submission_status == "clicked_unconfirmed"
                                    else "Contact form submission blocked by validation"
                                    if submission_status == "validation_failed"
                                    else "Contact form filled; submit control unavailable"
                                    if submission_status == "not_submitted"
                                    else "Contact form prefilled for review"
                                ),
                            )
                        except Exception as exc:
                            self._log(f"Progress event error: {exc}")
                        if submission_status == "review":
                            self._log("Review mode: form prefilled but not submitted.")
            except Exception as e:
                self._log(
                    f"Outreach preparation error: {e}"
                )

            # -----------------------------------------
            # FINAL RESULT
            # -----------------------------------------

            if (
                result["emails"]
                or result["phones"]
            ):

                self._log(
                    "✓ Contact information found"
                )
            else:

                self._log(
                    "✗ No contact information found"
                )

            self.update_result_status(result)
            self.save_outreach(business_key, result)
            if result.get("proposal"):
                self.append_draft(result)
            return result

        except Exception as e:

            self._log(f"Website processing error: {e}")
            result['status'] = 'error'
            result['last_error'] = str(e)
            try:
                self.attempt_preferred_outreach(result, website, business_key)
            except Exception as outreach_exc:
                self._log(f"Fallback outreach error: {outreach_exc}")
            self.save_outreach(business_key, result)
            return result

        finally:

            # -----------------------------------------
            # CLOSE WEBSITE TAB
            # -----------------------------------------

            try:

                # Make sure website tab is active
                keep_open = (
                    result.get("form_prefilled", False)
                    and bool(self.config.get("keep_prefilled_tabs_open", True))
                )
                if current_window in self.driver.window_handles and not keep_open:

                    self.driver.switch_to.window(
                        current_window
                    )

                    self.driver.close()
                elif keep_open:
                    self._log("Kept the prefilled contact-form tab open for review.")

            except Exception as e:

                self._log(
                    f"Error closing website tab: {e}"
                )

            # -----------------------------------------
            # RETURN TO GOOGLE TAB
            # -----------------------------------------

            try:

                if (
                    original_window
                    in self.driver.window_handles
                ):

                    self.driver.switch_to.window(
                        original_window
                    )

            except Exception as e:

                self._log(
                    f"Error returning to Google tab: {e}"
                )


    # =========================================================
    # PROCESS ALL WEBSITES
    # =========================================================


    def register_candidate(self, key, website):
        row = self.db.execute("SELECT status FROM outreach WHERE business_key=?", (key,)).fetchone()
        contacted = bool(self.db.execute("SELECT 1 FROM outreach_events WHERE business_key=? AND event_type IN (?,?) LIMIT 1",
                         (key, EVENT_EMAIL_SENT, EVENT_WHATSAPP_SENT)).fetchone()) or bool(row and row[0] in {'email_sent','whatsapp_sent','fallback_sent','submitted','sent'})
        area_key = website.get('area_key') or getattr(self, 'current_area', {}).get('area_key', '')
        self.db.execute("INSERT OR IGNORE INTO run_businesses(run_id,business_key,is_new,already_contacted,area_key) VALUES(?,?,?,?,?)",
                        (self.run_id, key, int(not row), int(contacted), area_key))
        self.db.execute("INSERT OR IGNORE INTO outreach(business_key,business_name,website,phones,status,area_key) VALUES(?,?,?,?,?,?)",
                        (key, website.get('name',''), website.get('url',''), json.dumps(website.get('phones',[])), 'discovered', area_key))
        self.db.commit()

    def process_all_websites(self, google_page, limit=20, finalize_run=True):
        results, seen_candidates, seen_pages = [], set(), set()
        processed = 0
        reason, run_status = 'Google page limit reached', 'completed'
        google_window = self.driver.current_window_handle
        max_pages = max(1, int(self.config.get('google_max_pages', 20)))
        for page_number in range(1, max_pages + 1):
            self.driver.switch_to.window(google_window)
            if self.google_is_blocked():
                reason, run_status = 'Google requires consent or CAPTCHA; resolve it in the browser and run again', 'blocked'
                break
            websites = self.get_google_websites(google_page)
            fingerprint = tuple(sorted(self.business_key(site) for site in websites))
            # Empty pages can have a valid next page. Nonempty repeated pages cannot add work.
            if fingerprint and fingerprint in seen_pages:
                reason = 'Google returned a repeated results page'
                break
            seen_pages.add(fingerprint)
            self.db.execute('UPDATE outreach_runs SET pages=? WHERE id=?', (page_number, self.run_id))
            self.db.commit()
            self._log(f'Google page {page_number}: {len(websites)} candidates; {processed}/{limit} processed.')
            for website in websites:
                current_area = getattr(self, 'current_area', {})
                if current_area:
                    website.update({
                        key: current_area.get(key, "")
                        for key in ("area_key", "country", "region", "city", "area")
                    })
                # Stable saved names let a previously phone-only listing retain its history.
                matching = self.db.execute("SELECT business_key FROM outreach WHERE lower(business_name)=? AND (website IS NULL OR website='') LIMIT 1",
                                           ((website.get('name') or '').strip().lower(),)).fetchone()
                key = matching[0] if matching else self.business_key(website)
                if key in seen_candidates:
                    continue
                seen_candidates.add(key)
                website['_business_key'] = key
                self.register_candidate(key, website)
                if processed >= limit:
                    continue
                try:
                    if not self.was_previously_processed(key):
                        website = self.enrich_google_business(website)
                    result = self.process_website(website)
                except Exception as exc:
                    result = dict(name=website.get('name',''), website=website.get('url',''),
                                  phones=website.get('phones',[]), status='error', last_error=str(exc),
                                  run_id=self.run_id, area_key=website.get('area_key',''))
                    self.save_outreach(key, result)
                    self._log(f"Business processing failed; continuing: {exc}")
                checked = result.get('status') not in {'skipped_duplicate','ignored_url'}
                processed += int(checked)
                self.db.execute('UPDATE run_businesses SET processed=?, status=? WHERE run_id=? AND business_key=?',
                                (int(checked), result.get('status','error'), self.run_id, key))
                self.db.commit()
                results.append(result)
                self.driver.switch_to.window(google_window)
            if processed >= limit:
                reason = 'Configured business limit reached'
                break
            if page_number == max_pages:
                break
            if not self.go_to_next_google_page():
                reason = 'No next Google page or additional business results'
                break
        self.last_search_outcome = {
            "status": run_status,
            "reason": reason,
            "processed": processed,
            "pages": page_number,
        }
        if finalize_run:
            self.finish_run(run_status, reason)
        return results


    def resolve_google_website(self, google_url):
        original_window = None
        original_handles = set()
        final_url = ""

        try:
            original_window = self.driver.current_window_handle
            original_handles = set(self.driver.window_handles)
            self._log("Resolving Google website link...")
            self.driver.switch_to.new_window("tab")
            self.driver.get(google_url)

            try:
                WebDriverWait(self.driver, 15).until(
                    lambda d: d.current_url.startswith(("http://", "https://"))
                )
            except TimeoutException:
                self._log("Timeout while resolving Google website.")

            final_url = self.driver.current_url
            self._log(f"Resolved URL: {final_url}")
        except Exception as exc:
            # A Google redirect can close its temporary tab.  Treat that as a
            # failed resolution, restore the results tab in finally, and keep
            # the overall automation run alive.
            self._log(f"Error resolving Google website: {exc}")
        finally:
            try:
                current_handles = list(self.driver.window_handles)
            except Exception:
                current_handles = []

            for handle in [h for h in current_handles if h not in original_handles]:
                try:
                    self.driver.switch_to.window(handle)
                    self.driver.close()
                except Exception:
                    pass

            try:
                remaining = list(self.driver.window_handles)
                if original_window in remaining:
                    self.driver.switch_to.window(original_window)
                elif remaining:
                    self.driver.switch_to.window(remaining[0])
            except Exception:
                pass

        if not final_url:
            return None
        host = (urlparse(final_url).hostname or "").lower()
        if host == "google.com" or host.endswith(".google.com") or host == "google.ae" or host.endswith(".google.ae"):
            self._log(f"Still on Google, ignoring: {final_url}")
            return None
        return final_url


    def _find_chatgpt_editor(self, page):
        selectors = [
            "textarea#mobile-composer-prompt",
            "textarea[data-mobile-composer-prompt]",
            "textarea[name='prompt'][aria-label='Chat with ChatGPT']",
            "form[action*='/unauth-mweb/conversation'] textarea[name='prompt']",
            "textarea.wm-composer-textarea",
            "textarea[data-testid='prompt-textarea']",
            "#prompt-textarea",
            "textarea[name='prompt']",
            "[data-testid='composer-root'] [contenteditable='true']",
            "div.ProseMirror[contenteditable='true']",
            "[contenteditable='true'][role='textbox']",
            "[contenteditable='true']",
        ]

        for selector in selectors:
            editor = page.locator(selector).last
            try:
                editor.wait_for(state="visible", timeout=7000)
                return editor
            except Exception:
                continue

        raise Exception(
            "ChatGPT prompt box was not found. Sign in in the opened "
            "ChatGPT window, then run again, or set OPENAI_API_KEY in .env."
        )

    def _chatgpt_editor_has_text(self, editor):
        try:
            value = editor.input_value(timeout=1000)
        except Exception:
            try:
                value = editor.inner_text(timeout=1000)
            except Exception:
                value = ""
        return bool(str(value).strip())

    def _set_chatgpt_editor_text(self, page, editor, content):
        try:
            editor.evaluate(
                """(element, text) => {
                    const proto = element instanceof HTMLTextAreaElement
                        ? HTMLTextAreaElement.prototype
                        : HTMLInputElement.prototype;
                    const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
                    if (descriptor && descriptor.set) {
                        descriptor.set.call(element, text);
                    } else {
                        element.value = text;
                    }
                    element.dispatchEvent(new InputEvent('input', {
                        bubbles: true,
                        inputType: 'insertText',
                        data: text
                    }));
                    element.dispatchEvent(new Event('change', { bubbles: true }));
                    element.dispatchEvent(new KeyboardEvent('keyup', {
                        bubbles: true,
                        key: ' ',
                        code: 'Space'
                    }));
                }""",
                content
            )
            page.wait_for_timeout(800)
            return self._chatgpt_editor_has_text(editor)
        except Exception:
            return False

    def _paste_chatgpt_prompt(self, page, editor, content):
        editor.click()
        if self._set_chatgpt_editor_text(page, editor, content):
            return

        try:
            page.evaluate(
                "(text) => navigator.clipboard.writeText(text)",
                content
            )
            page.keyboard.press("Control+V")
            page.wait_for_timeout(1000)
        except Exception:
            pass

        if self._chatgpt_editor_has_text(editor):
            return

        try:
            editor.fill(content)
            page.wait_for_timeout(1000)
        except Exception:
            editor.click()
            page.keyboard.insert_text(content)
            page.wait_for_timeout(1000)

    def _send_chatgpt_prompt(self, page):
        selectors = [
            "button[data-composer-submit]",
            "button.wm-composer-submitButton",
            "form[action*='/unauth-mweb/conversation'] button[type='submit']",
            "button[data-testid='send-button']",
            "button[aria-label='Send prompt']",
            "button[aria-label='Send message']",
        ]

        for selector in selectors:
            button = page.locator(selector).last
            try:
                button.wait_for(state="visible", timeout=5000)
                for _ in range(20):
                    if button.is_enabled():
                        button.click()
                        return
                    page.wait_for_timeout(250)
            except Exception:
                continue

        try:
            page.locator(
                "form[action*='/unauth-mweb/conversation']"
            ).evaluate(
                "form => form.requestSubmit ? form.requestSubmit() : form.submit()"
            )
            return
        except Exception:
            pass

        page.keyboard.press("Enter")

    def _assistant_response_count(self, page):
        try:
            return page.locator('[data-message-author-role="assistant"]').count()
        except Exception:
            return 0

    def _wait_for_chatgpt_generation(self, page):
        stop_selector = "button[data-testid='stop-button'], button[aria-label*='Stop']"
        try:
            page.locator(stop_selector).first.wait_for(
                state="hidden",
                timeout=120000
            )
        except Exception:
            pass
        page.wait_for_timeout(1500)

    def _read_chatgpt_response(self, page, previous_count):
        assistant_selector = '[data-message-author-role="assistant"]'
        try:
            page.wait_for_function(
                """(count) => document.querySelectorAll(
                    '[data-message-author-role="assistant"]'
                ).length > count""",
                previous_count,
                timeout=120000,
            )
        except Exception:
            pass

        self._wait_for_chatgpt_generation(page)

        responses = page.locator(assistant_selector)
        last_text = ""
        stable_reads = 0

        for _ in range(12):
            try:
                count = responses.count()
                if count:
                    response = responses.nth(count - 1)
                    content = response.locator(
                        ".markdown.prose, .markdown, [data-message-content]"
                    )
                    if content.count():
                        raw_text = content.last.inner_text(timeout=5000)
                    else:
                        raw_text = response.inner_text(timeout=5000)
                    text = clean_outreach_message(raw_text)
                    if text and text == last_text:
                        stable_reads += 1
                    else:
                        stable_reads = 0
                    last_text = text
                    if text and stable_reads >= 1:
                        return text
            except Exception:
                pass
            page.wait_for_timeout(1000)

        if last_text:
            return last_text

        copy_selector = (
            'button[aria-label="Copy response"], '
            'button[aria-label="Copy"], '
            'button[data-testid="copy-turn-action-button"]'
        )
        copy_button = page.locator(copy_selector).last
        copy_button.wait_for(state="visible", timeout=30000)
        copy_button.scroll_into_view_if_needed()
        copy_button.click()
        page.wait_for_timeout(1000)
        return clean_outreach_message(
            page.evaluate("navigator.clipboard.readText()")
        )

    def ask_ai(self, content, domain, filename, Image=False):

        # ============================================================
        # API MODE
        # ============================================================
        # If OPENAI_API_KEY exists, use OpenAI API.
        # Otherwise, use the existing Playwright method below.
        # ============================================================

        api_key = os.environ.get("OPENAI_API_KEY")

        if api_key:

            print("OPENAI_API_KEY found.")
            print("Using OpenAI API mode.")

            try:
                from openai import OpenAI

                client = OpenAI(api_key=api_key)

                # ----------------------------------------------------
                # Ask GPT-5.5 for the response
                # ----------------------------------------------------
                #
                # json_object is used because your existing code expects
                # the response to be JSON and then does json.loads().
                #
                # Your original content is passed directly without
                # changing it.
                # ----------------------------------------------------

                response = client.responses.create(
                    model=self.config.get("openai_model", "gpt-5.5"),
                    input=content
                )

                response = response.output_text

                self._log("Outreach draft received.")

                # ----------------------------------------------------
                # Make sure response exists
                # ----------------------------------------------------

                if response is None:
                    raise Exception("Response is None")

                response = response.strip()

                if not response:
                    raise Exception("Response is empty")

                # ----------------------------------------------------
                # Remove Markdown code fences if present
                # ----------------------------------------------------

                if response.startswith("```"):
                    lines = response.splitlines()

                    # Remove opening fence (``` or ```json)
                    if lines and lines[0].startswith("```"):
                        lines = lines[1:]

                    # Remove closing fence
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]

                    response = "\n".join(lines).strip()

                print("Response received:")
                print(response)

                # ----------------------------------------------------
                # Convert JSON response into Python object
                # ----------------------------------------------------

                # ----------------------------------------------------
                # IMAGE GENERATION
                # ----------------------------------------------------
                #
                # Only generate an image when Image=True.
                #
                # We use the same content as the image prompt.
                # ----------------------------------------------------


                if Image:

                    print("Image=True")
                    print("Generating image using OpenAI API...")

                    image_response = client.responses.create(
                        model="gpt-5.5",
                        input=content,
                        tools=[
                            {
                                "type": "image_generation"
                            }
                        ]
                    )

                    # ------------------------------------------------
                    # Find image_generation_call in the response
                    # ------------------------------------------------

                    image_data = None

                    for item in image_response.output:

                        print("Response item type:", getattr(item, "type", None))

                        if getattr(item, "type", None) == "image_generation_call":

                            # The SDK normally exposes the generated image
                            # as the "result" field.
                            image_data = getattr(item, "result", None)

                            print("Image result found:", bool(image_data))

                            if image_data:
                                break

                    # ------------------------------------------------
                    # If no image was found, print complete response
                    # ------------------------------------------------

                    if not image_data:

                        print("FULL OPENAI RESPONSE:")
                        print(image_response)

                        raise Exception(
                            "Image generation completed but no image data was returned."
                        )

                    # ------------------------------------------------
                    # Create pictures directory
                    # ------------------------------------------------

                    pictures_dir = os.path.join(
                        "data",
                        "pictures"
                    )

                    os.makedirs(
                        pictures_dir,
                        exist_ok=True
                    )

                    # ------------------------------------------------
                    # Keep your existing filename variables
                    # ------------------------------------------------

                    filename = f"{domain}_{filename}.png"

                    filepath = os.path.join(
                        pictures_dir,
                        filename
                    )

                    # ------------------------------------------------
                    # Decode base64 image and save it
                    # ------------------------------------------------

                    try:

                        image_bytes = base64.b64decode(image_data)

                        with open(filepath, "wb") as f:
                            f.write(image_bytes)

                        print("Saved:", filepath)

                    except Exception as e:

                        print("Error decoding image:")
                        print(e)

                        raise

                    print("Saved:", filepath)

                # ----------------------------------------------------
                # Return exactly as your original function did
                # ----------------------------------------------------

                return response

            except Exception as e:

                print("OpenAI API error:")
                print(str(e))

                # Do NOT silently switch to Playwright here.
                #
                # This is intentional:
                # If an API key exists but the API fails, you should
                # know about the API error rather than accidentally
                # running the browser version.
                #
                raise

        # ============================================================
        # EXISTING PLAYWRIGHT MODE
        # ============================================================
        #
        # No OPENAI_API_KEY was found.
        #
        # Your original method is used.
        # ============================================================

        print("OPENAI_API_KEY not found.")
        print("Using existing ChatGPT browser mode.")

        with sync_playwright() as p:

            profile_dir = Path(
                self.config.get("chatgpt_profile_dir", "chatgpt_profile")
            )

            if not profile_dir.is_absolute():
                profile_dir = self.data_dir / profile_dir

            profile_dir.mkdir(parents=True, exist_ok=True)

            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=self.headless,
                permissions=[
                    "clipboard-read",
                    "clipboard-write"
                ],
                viewport={
                    "width": 1280,
                    "height": 900
                }
            )

            page = context.pages[0] if context.pages else context.new_page()

            page.goto(
                "https://chatgpt.com/",
                wait_until="domcontentloaded",
                timeout=60000
            )

            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=30000
                )
            except Exception:
                pass

            page.wait_for_timeout(3000)

            try:
                editor = self._find_chatgpt_editor(page)
            except Exception:
                self._log(
                    "ChatGPT prompt box is not ready. If a sign-in page is "
                    "showing, complete sign-in in the ChatGPT window."
                )
                page.wait_for_timeout(120000)
                editor = self._find_chatgpt_editor(page)

            previous_count = self._assistant_response_count(page)

            self._paste_chatgpt_prompt(page, editor, content)
            self._send_chatgpt_prompt(page)

            response = self._read_chatgpt_response(
                page,
                previous_count
            )

            self._log("Outreach draft received.")

            # Make sure response exists
            if response is None:
                raise Exception("Response is None")

            response = response.strip()

            if not response:
                raise Exception("Response is empty")

            # Remove Markdown code fences if present
            if response.startswith("```"):

                lines = response.splitlines()

                # Remove opening fence (``` or ```json)
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]

                # Remove closing fence
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]

                response = "\n".join(lines).strip()

            print("Response received:")
            print(response)

            if Image:

                # Wait until ChatGPT finishes generating
                page.locator(
                    'button[aria-label="Stop generating"]'
                ).wait_for(
                    state="hidden"
                )

                # Wait until Download button exists
                download_btn = page.locator(
                    'button[aria-label="Download"]'
                ).last

                download_btn.wait_for(
                    state="visible",
                    timeout=120000
                )

                pictures_dir = os.path.join(
                    "data",
                    "pictures"
                )

                os.makedirs(
                    pictures_dir,
                    exist_ok=True
                )

                filename = f"{domain}_{filename}.png"

                filepath = os.path.join(
                    pictures_dir,
                    filename
                )

                # Download image
                with page.expect_download() as download_info:

                    download_btn.click()

                download = download_info.value

                download.save_as(
                    filepath
                )

                print("Saved:", filepath)

            context.close()

            return response



    def is_similar_service_business(self, website):
        """Identify software, IT, web, and marketing providers suitable for partnership."""
        context = " ".join((
            str(website.get("name", "") or ""),
            str(website.get("profile_text", "") or ""),
            str(website.get("category", "") or ""),
        )).lower()
        return any(re.search(pattern, context) for pattern in PARTNER_BUSINESS_PATTERNS)

    def generate_website_proposal(self, website):
        """
        Generate industry-aware outreach based on the business information and
        whether Google lists an existing website.
        """

        company_name = website.get("name", "")
        website_url = website.get("url", "")
        has_website = bool(
            website_url
            or website.get("has_website")
            or website.get("website_redirect_url")
        )
        business_context = website.get("profile_text") or self.search_query
        partnership_outreach = self.is_similar_service_business(website)
        audit_findings = [
            str(finding).strip()
            for finding in website.get("audit_findings", [])
            if str(finding).strip()
        ]
        our_company = self.config.get("company_name", "our web development company")
        prompt_template = str(
            self.config.get("proposal_prompt", "")
            or DEFAULT_PROPOSAL_PROMPT
        ).strip()
        prompt_values = SafePromptValues({
            "business_name": company_name,
            "website_url": website_url or (
                "Website is listed on the Google Business Profile"
                if has_website else "No website is listed"
            ),
            "business_context": business_context,
            "search_query": business_context,
            "company_name": our_company,
            "services": "\n".join(f"- {service}" for service in PROPOSAL_SERVICES),
            "audit_findings": "\n".join(f"- {finding}" for finding in audit_findings),
        })

        try:
            prompt = prompt_template.format_map(prompt_values)
        except Exception as exc:
            self._log(
                f"Proposal prompt format error: {exc}; using default prompt."
            )
            prompt = DEFAULT_PROPOSAL_PROMPT.format_map(prompt_values)

        if partnership_outreach:
            prompt += (
                "\n\nPARTNERSHIP OUTREACH REQUIREMENT:\n"
                "This business appears to provide software, IT, website, advertising, "
                "or digital-marketing services similar or complementary to ours. Do not "
                "pitch website creation, website improvement, or ordinary client services "
                "to them. Instead, write a concise business-opportunity message proposing "
                "a mutually beneficial partnership. Suitable ideas include reciprocal "
                "referrals, white-label delivery, subcontracting, overflow project support, "
                "and combining complementary expertise. Do not assume which arrangement "
                "they need; invite a brief discussion about possible collaboration."
            )
        elif not has_website:
            prompt += (
                "\n\nThis business has no website listed. Clearly and politely propose "
                "creating a new professional, modern website to upgrade their online "
                "presence. Also propose one dedicated software concept tailored to its "
                "industry that could streamline day-to-day operations. Ask whether they "
                "would like to discuss a new website, new or updated dedicated software, "
                "or both. Do not "
                "imply that they already have a website or currently lack suitable software."
            )
        else:
            prompt += f"\n\nWEBSITE REVIEW:\nWebsite checked: {website_url or 'Website URL listed on Google'}"
            if audit_findings:
                prompt += (
                    "\nConfirmed homepage observations (use these as the only source for "
                    "the website issues mentioned to the customer):\n"
                    + "\n".join(f"- {finding}" for finding in audit_findings)
                    + "\n\nWrite a concise outreach message that says the website review found "
                    "some issues and briefly names two or three of the confirmed issues. If "
                    "only one issue was confirmed, mention only that issue and do not say "
                    "that there are several. Translate each finding into clear, natural "
                    "business language; for example, say that the homepage is missing a "
                    "clear main heading or that its search-result description is missing. "
                    "Do not replace the specific issues with only a broad phrase such as "
                    "'SEO issues' or 'opportunities to improve.' Avoid raw HTML terminology, "
                    "metadata names, protocols, audit language, and exact item counts. Do not "
                    "provide a technical solution or step-by-step instructions. Explain that "
                    "our team can fix these website issues and invite them to discuss the work. "
                    "Do not invent additional issue categories. "
                    "Do not claim the site is hacked, vulnerable, unsafe, penalized, or "
                    "non-responsive unless the confirmed observations explicitly prove it. "
                    "After the website summary, propose one dedicated software concept "
                    "specific to this business type that could streamline its operations. "
                    "Mention only two or three relevant capabilities. End by asking whether "
                    "they would be interested in website improvements, new or updated "
                    "dedicated software, or both."
                )
            else:
                prompt += (
                    "\nNo specific issue was safely confirmed by the automated homepage "
                    "check. Do not invent an SEO, responsive-design, performance, or security "
                    "problem. Offer a deeper review and explain that we can fix any confirmed "
                    "website issues. Then propose one dedicated software concept specific to "
                    "this business type that could streamline its operations, and ask whether "
                    "they are interested in website improvements, new or updated dedicated "
                    "software, or both."
                )

        if partnership_outreach:
            prompt += (
                "\n\nKeep the partnership message short, focused, and peer-to-peer. "
                "Do not list or sell our normal services and do not treat this company "
                "as an ordinary sales prospect."
            )
        elif has_website:
            prompt += (
                "\n\nKeep the message focused on the specific, customer-friendly website "
                "issues supported by the review and one genuinely relevant dedicated-software "
                "idea. Do not replace the confirmed issues with generic SEO language, replace "
                "the tailored idea with a generic service list, or include a technical tutorial. "
                "Arrange the message professionally: website issues, tailored software "
                "opportunity, then a concise question about website improvements, new or "
                "updated software, or both."
            )
        else:
            prompt += (
                "\n\nTAILORING REQUIREMENT:\n"
                "Identify the business type from the business name and search/category context. "
                "Write a specific message for that type of business, not a generic marketing message. "
                "Select only the services from the provided service list that are realistically useful "
                "to this business, and briefly connect each service to a likely practical use without "
                "claiming the business currently has a problem. It may offer website updates or "
                "modifications, a new website when none is listed, custom software, accounting, POS, "
                "CRM, inventory, booking, e-commerce, integrations, automation, maintenance, SEO, or "
                "digital marketing when appropriate. Keep the result short, focused, and readable."
            )

        if not partnership_outreach and "website orders can flow into the same operational system" not in prompt.lower():
            prompt += (
                "\n\nINDUSTRY SOLUTION REQUIREMENT:\n"
                "Recommend one cohesive solution for the likely business type and explain, "
                "in practical terms, how its components can work together. Do not give only "
                "a generic service list. For a restaurant, cafe, or catering business, propose "
                "an integrated POS and website solution with an online menu, direct customer "
                "ordering, kitchen/order workflow, inventory control, and sales reporting; "
                "explain that website orders can flow into the same operational system. For "
                "a general business without a clearer industry match, propose an invoicing "
                "and accounting solution covering quotations, invoices, expenses, customer "
                "balances, profit-and-loss reporting, and management reports. For other "
                "industries, provide an equally concrete, relevant solution and explain its "
                "operational value. Keep the proposal around 120 to 180 words."
            )

        lower_prompt = prompt.lower()
        final_rules = []
        if "do not include sender contact details" not in lower_prompt:
            final_rules.append(
                "- Do not include sender contact details such as contact name, "
                "email, phone, website, or a contact-us block. Those details "
                "are added separately only for channels where they are enabled."
            )
        if "return only" not in lower_prompt:
            final_rules.append("- Return ONLY the proposal text.")
        if "our team at [company name]" not in lower_prompt:
            final_rules.append(
                "- After the greeting, start the first sentence with 'We'. Do not open "
                "with 'Our team at [company name]' and do not repeat the sender company "
                "name in the message body; use we, us, and our instead."
            )

        if final_rules:
            prompt = f"{prompt}\n\nFINAL RULES:\n" + "\n".join(final_rules)

        if not os.environ.get("OPENAI_API_KEY") and not bool(
            self.config.get("use_browser_ai", False)
        ):
            self._log("No OpenAI API key configured; using fast local outreach message.")
            return self.fallback_outreach_message(website)

        try:
            message = self.ask_ai(
                prompt,
                domain=company_name,
                filename="proposal"
            )
            message = clean_outreach_message(message)
            if not message:
                raise ValueError("Generated outreach message contained no sendable text")
            if audit_findings and self.audit_message_exposes_details(message):
                self._log(
                    "AI draft exposed technical audit details; using the customer-friendly issue summary."
                )
                return self.fallback_outreach_message(website)
            return message
        except Exception as exc:
            # Outreach should not stop solely because the optional AI service
            # or browser session is unavailable.  The local template preserves
            # the important website/no-website distinction and lets the bot
            # continue to WhatsApp.
            self._log(f"AI message generation unavailable; using local fallback: {exc}")
            return self.fallback_outreach_message(website)

    def fallback_outreach_message(self, website):
        business_name = str(website.get("name", "") or "").strip()
        greeting = f"Hello {business_name} team," if business_name else "Hello,"
        if self.is_similar_service_business(website):
            return (
                f"{greeting}\n\n"
                "We work in software and digital services and would be interested in "
                "exploring a mutually beneficial business opportunity with your team. "
                "Depending on our respective strengths, we could potentially collaborate "
                "through reciprocal referrals, white-label delivery, subcontracting, "
                "overflow project support, or complementary expertise.\n\n"
                "If this is of interest, we would be happy to have a brief conversation "
                "to understand each other's capabilities and discuss where collaboration "
                "could create value for both businesses."
            )
        has_website = bool(
            website.get("url")
            or website.get("has_website")
            or website.get("website_redirect_url")
        )
        if has_website:
            website_url = str(website.get("url", "") or "").strip()
            software_idea = self.business_software_suggestion(website)
            findings = [
                str(finding).strip()
                for finding in website.get("audit_findings", [])
                if str(finding).strip()
            ][:4]
            if findings:
                customer_issues = self.audit_customer_issues(findings)[:3]
                if len(customer_issues) == 1:
                    review_text = (
                        "we identified an issue: " + customer_issues[0]
                    )
                else:
                    issues_text = ", ".join(customer_issues[:-1]) + f", and {customer_issues[-1]}"
                    review_text = "we identified several issues, including " + issues_text
                return (
                    f"{greeting}\n\n"
                    f"During a brief review of {website_url or 'your website'}, {review_text}.\n\n"
                    "Our team can fix these website issues and improve the site's clarity, "
                    "usability, and online presence.\n\n"
                    f"We can also develop {software_idea} to help streamline your day-to-day "
                    "operations. Would you be interested in discussing website improvements, "
                    "new or updated dedicated software, or both?"
                )
            return (
                f"{greeting}\n\n"
                f"We took a brief look at {website_url or 'your website'}. Our automated "
                "homepage check did not confirm a specific issue that would be fair to "
                "claim without a deeper review. We can perform a closer website review "
                "and update any confirmed SEO, mobile-usability, performance, or security-"
                "baseline issues.\n\n"
                f"We can also develop {software_idea} to help streamline your day-to-day "
                "operations. Would you be interested in discussing website improvements, "
                "new or updated dedicated software, or both?"
            )

        software_idea = self.business_software_suggestion(website)
        return (
            f"{greeting}\n\n"
            "Your Google Business Profile does not currently show a website. We can "
            "create a professional, mobile-friendly website to upgrade your online presence, "
            "with clear service information, contact details, location, and online "
            "booking or enquiry features where useful.\n\n"
            f"We can also develop {software_idea} to help streamline your day-to-day "
            "operations. Would you be interested in discussing a new website, new or "
            "updated dedicated software, or both?"
        )

    @staticmethod
    def business_software_suggestion(website):
        """Return one concise software concept tailored to the likely business type."""
        context = " ".join(
            str(website.get(key, "") or "")
            for key in ("name", "profile_text", "business_context", "search_query")
        ).lower()
        suggestions = (
            (("travel", "tour", "holiday", "visa"),
             "a dedicated travel-operations platform for enquiries, bookings, itineraries, and customer follow-up"),
            (("hotel", "resort", "hospitality"),
             "a tailored hospitality platform for reservations, guest requests, and operational reporting"),
            (("restaurant", "cafe", "cafeteria", "catering"),
             "an integrated restaurant solution that connects a POS with website ordering, "
             "menu management, kitchen and order tracking, inventory control, and sales reports, "
             "so online and in-store orders can be handled in one workflow"),
            (("salon", "spa", "beauty", "barber"),
             "a dedicated salon-management platform for appointments, staff schedules, customer records, and reminders"),
            (("clinic", "medical", "dental", "health"),
             "a tailored clinic-administration platform for appointments, customer communication, and operational reporting"),
            (("real estate", "property", "properties", "broker"),
             "a dedicated property-management and CRM platform for listings, enquiries, viewings, and lead follow-up"),
            (("logistics", "cargo", "courier", "transport", "delivery"),
             "a tailored logistics platform for bookings, shipment tracking, customer updates, and operational reporting"),
            (("construction", "contracting", "engineering"),
             "a dedicated project-operations platform for quotations, job progress, documents, and management reporting"),
            (("school", "training", "education", "academy", "institute"),
             "a tailored education platform for enrolment, schedules, student communication, and payment tracking"),
            (("consult", "business setup", "advisory", "accounting"),
             "a dedicated client-operations platform for enquiries, cases, documents, tasks, and follow-up"),
            (("trading", "retail", "shop", "store", "wholesale"),
             "a tailored business-management platform for sales, inventory, purchasing, and customer follow-up"),
            (("maintenance", "cleaning", "repair", "technical service"),
             "a dedicated service-management platform for enquiries, quotations, job scheduling, and customer follow-up"),
        )
        for keywords, suggestion in suggestions:
            if any(keyword in context for keyword in keywords):
                return suggestion
        return (
            "an integrated invoicing and accounting system for quotations, invoices, "
            "expenses, customer balances, profit-and-loss reporting, and management reports"
        )

    @staticmethod
    def audit_improvement_areas(findings):
        """Convert internal audit evidence into safe customer-facing categories."""
        category_checks = (
            ("mobile usability", ("viewport", "mobile")),
            ("website security and visitor trust", ("http", "https", "insecure", "mixed resource")),
            ("accessibility and user experience", ("alt text", "language", "accessibility")),
            (
                "SEO and search visibility",
                ("page title", "title", "meta description", "h1", "canonical", "search result", "seo"),
            ),
        )
        joined = " ".join(str(finding).lower() for finding in findings)
        areas = [
            label
            for label, keywords in category_checks
            if any(keyword in joined for keyword in keywords)
        ]
        return areas or ["overall website quality"]

    @staticmethod
    def audit_customer_issues(findings):
        """Translate confirmed audit findings into concise customer-friendly issues."""
        issue_checks = (
            (("served over http",), "the site is not using a secure connection"),
            (("does not provide a page title",), "the homepage is missing a search-result title"),
            (("title is very short",), "the homepage title does not clearly describe the business"),
            (("title is long",), "the homepage title may be cut off in search results"),
            (("no meta description",), "the homepage is missing a search-result description"),
            (("meta description is very short",), "the search-result description is too brief"),
            (("meta description is long",), "the search-result description may be cut off"),
            (("mobile viewport",), "mobile display settings are missing, which can affect phone usability"),
            (("no main h1 heading",), "the homepage is missing a clear main heading"),
            (("h1 headings",), "the homepage has an unclear main-heading structure"),
            (("canonical url",), "search engines are not given a preferred homepage address"),
            (("language is not declared",), "the page language is not specified for browsers and accessibility tools"),
            (("missing descriptive alt text",), "some homepage images are missing accessibility descriptions"),
            (("form", "insecure http"), "a website form sends information through an insecure connection"),
            (("loads", "resource", "insecure http"), "some page content loads through an insecure connection"),
        )
        issues = []
        for finding in findings:
            text = str(finding or "").lower()
            issue = next(
                (label for keywords, label in issue_checks if all(keyword in text for keyword in keywords)),
                "a confirmed homepage element needs attention",
            )
            if issue not in issues:
                issues.append(issue)
        return issues

    @staticmethod
    def audit_message_exposes_details(message):
        """Reject AI drafts that leak technical audit details or exact item counts."""
        text = str(message or "").lower()
        technical_detail = re.search(
            r"\b(?:h1|meta description|page title|canonical(?: url)?|alt text|"
            r"viewport|html (?:tag|attribute)|mixed (?:content|resources?)|"
            r"insecure http|http protocol|https protocol)\b",
            text,
        )
        exact_count = re.search(
            r"\b\d+\s+(?:of\s+\d+\s+)?(?:images?|headings?|forms?|resources?|items?)\b",
            text,
        )
        return bool(technical_detail or exact_count)

    def contact_details_block(self):
        lines = []
        company = str(
            self.config.get("company_name", "")
            or ""
        ).strip()
        contact_name = self.get_config_or_env(
            "contact_name",
            "CONTACT_US_NAME"
        ).strip()
        contact_email = self.get_config_or_env(
            "contact_email",
            "CONTACT_US_EMAIL"
        ).strip()
        contact_phone = self.get_config_or_env(
            "contact_phone",
            "CONTACT_US_PHONE"
        ).strip()
        company_website = str(
            self.config.get("company_website", "")
            or ""
        ).strip()

        for label, value in [
            ("Company", company),
            ("Contact", contact_name),
            ("Email", contact_email),
            ("Phone", contact_phone),
            ("Website", company_website),
        ]:
            if value:
                lines.append(f"{label}: {value}")

        if not lines:
            return ""

        return "Contact details:\n" + "\n".join(lines)

    def channel_message(self, result, section):
        message = clean_outreach_message(
            result.get("proposal", "")
            or ""
        )

        if not message:
            return ""

        include_contact_details = self.get_bool_setting(
            section,
            "include_contact_details",
            default=True
        )

        if not include_contact_details:
            return message

        contact_details = self.contact_details_block()
        if not contact_details:
            return message

        return f"{message}\n\n{contact_details}"


    def get_config_or_env(self, config_key, env_key, default=""):
        value = self.config.get(config_key)

        if value is not None and str(value).strip():
            return str(value)

        return os.environ.get(env_key, default)

    def get_section_setting(self, section, key, default=None, env_key=None):
        section_config = self.config.get(section, {})

        if isinstance(section_config, dict):
            value = section_config.get(key)
            if value is not None and str(value).strip():
                return value

        flat_key = f"{section}_{key}"
        value = self.config.get(flat_key)

        if value is not None and str(value).strip():
            return value

        if env_key:
            value = os.environ.get(env_key)
            if value is not None and str(value).strip():
                return value

        return default

    def get_bool_setting(self, section, key, default=False, env_key=None):
        value = self.get_section_setting(
            section,
            key,
            default=default,
            env_key=env_key
        )

        if isinstance(value, bool):
            return value

        if value is None:
            return bool(default)

        return str(value).strip().lower() in {
            "1",
            "true",
            "yes",
            "on"
        }

    def normalize_whatsapp_phone(self, phone):
        digits = re.sub(
            r"\D",
            "",
            phone or ""
        )

        if not digits:
            return ""

        if digits.startswith("00"):
            digits = digits[2:]

        country_code = str(
            self.get_section_setting(
                "whatsapp",
                "default_country_code",
                default=self.config.get("default_country_code", "971")
            )
        ).strip()

        if digits.startswith("0") and country_code:
            digits = country_code + digits[1:]
        elif len(digits) <= 9 and country_code:
            digits = country_code + digits

        return digits

    def primary_whatsapp_phone(self, result):
        for phone in result.get("phones", []):
            digits = self.normalize_whatsapp_phone(
                phone
            )

            ignored_prefixes = self.get_section_setting(
                "whatsapp",
                "ignore_phone_prefixes",
                default=[]
            )
            if isinstance(ignored_prefixes, str):
                ignored_prefixes = [ignored_prefixes]

            normalized_prefixes = [
                re.sub(r"\D", "", str(prefix))
                for prefix in ignored_prefixes
                if str(prefix).strip()
            ]
            if any(
                digits.startswith(prefix)
                for prefix in normalized_prefixes
                if prefix
            ):
                self._log(
                    f"Skipping WhatsApp for ignored landline number: {phone}"
                )
                continue

            if 10 <= len(digits) <= 15:
                return digits

        return ""

    def check_whatsapp_phone(self, phone):
        """Open a WhatsApp chat without composing a message and verify it exists."""
        reuse_tab = self.get_bool_setting(
            "whatsapp", "reuse_tab", default=True
        )
        send_timeout = max(10, int(self.get_section_setting(
            "whatsapp", "send_timeout_seconds", default=30
        )))
        login_timeout = max(10, int(self.get_section_setting(
            "whatsapp", "login_timeout_seconds", default=180
        )))
        timeout = login_timeout if not self.whatsapp_login_wait_used else send_timeout
        original_window = None
        whatsapp_window = None

        try:
            original_window = self.driver.current_window_handle
            existing = getattr(self, "whatsapp_window", None)
            if reuse_tab and existing in self.driver.window_handles:
                whatsapp_window = existing
                self.driver.switch_to.window(whatsapp_window)
                self._log("Reusing the existing WhatsApp tab for number validation.")
            else:
                self.driver.switch_to.new_window("tab")
                whatsapp_window = self.driver.current_window_handle
                if reuse_tab:
                    self.whatsapp_window = whatsapp_window

            # Deliberately omit the text query parameter. Message generation
            # happens only after WhatsApp confirms that this chat is usable.
            self.driver.get(f"https://web.whatsapp.com/send?phone={phone}")

            def chat_state(driver):
                unavailable = self.whatsapp_unavailable_reason(driver)
                if unavailable:
                    self.pause_before_invalid_whatsapp_continue()
                    self.dismiss_whatsapp_unavailable_dialog(driver)
                    return ("not_on_whatsapp", unavailable)
                selectors = (
                    "#main footer [contenteditable='true']",
                    "#main footer",
                    "[data-testid='conversation-panel-wrapper'] footer",
                )
                for selector in selectors:
                    try:
                        if any(element.is_displayed() for element in driver.find_elements(By.CSS_SELECTOR, selector)):
                            return ("available", "WhatsApp chat is available")
                    except Exception:
                        continue
                return False

            state, reason = WebDriverWait(
                self.driver, timeout, poll_frequency=0.15
            ).until(chat_state)
            self.whatsapp_login_wait_used = True
            return state, reason
        except TimeoutException:
            unavailable = self.whatsapp_unavailable_reason()
            if unavailable:
                self.pause_before_invalid_whatsapp_continue()
                self.dismiss_whatsapp_unavailable_dialog()
                self.whatsapp_login_wait_used = True
                return "not_on_whatsapp", unavailable
            return "failed", "WhatsApp chat did not become ready; login may be required"
        except Exception as exc:
            return "failed", str(exc)
        finally:
            try:
                if (
                    not reuse_tab
                    and whatsapp_window
                    and whatsapp_window in self.driver.window_handles
                ):
                    self.driver.switch_to.window(whatsapp_window)
                    self.driver.close()
                if original_window and original_window in self.driver.window_handles:
                    self.driver.switch_to.window(original_window)
            except Exception:
                pass

    def preflight_whatsapp(self, result, business_key):
        """Return the first confirmed WhatsApp number without creating a message."""
        if not self.get_bool_setting("whatsapp", "enabled", default=True):
            self.channel_outcome(result, "whatsapp", "disabled", "Disabled in settings")
            return ""
        if self.recent_channel_events(business_key, EVENT_WHATSAPP_SENT):
            result["whatsapp_sent"] = True
            self.channel_outcome(result, "whatsapp", "already_sent", "Within configured contact cooldown")
            return ""
        if self.recent_channel_events(business_key, "whatsapp_uncertain"):
            self.channel_outcome(result, "whatsapp", "uncertain", "Previous click was not confirmed; review WhatsApp before retrying")
            return ""

        numbers, usable, candidates = self.whatsapp_candidates(result)
        if not candidates:
            if usable and self.never_repeat_contacted():
                self.channel_outcome(result, "whatsapp", "duplicate_recipient", "All usable numbers were contacted previously")
            else:
                self.channel_outcome(result, "whatsapp", "no_phone", "No usable phone number found")
            return ""

        checked = result.setdefault("_whatsapp_checked_numbers", {})
        saw_failure = False
        last_reason = ""
        for phone in candidates:
            cached = checked.get(phone)
            if cached:
                state, reason = cached.get("status", "failed"), cached.get("reason", "")
            else:
                self._log(f"Checking whether {phone} is available on WhatsApp before writing a message.")
                state, reason = self.check_whatsapp_phone(phone)
                checked[phone] = {"status": state, "reason": reason}

            if state == "available":
                result["_verified_whatsapp_phone"] = phone
                self.channel_outcome(result, "whatsapp", "available", reason)
                return phone
            saw_failure = saw_failure or state == "failed"
            last_reason = reason or last_reason

        status = "failed" if saw_failure else "not_on_whatsapp"
        self.channel_outcome(
            result,
            "whatsapp",
            status,
            last_reason or "No discovered number is registered on WhatsApp",
        )
        return ""

    def attempt_preferred_outreach(self, result, website, business_key):
        """Use every available channel, with WhatsApp sufficient on its own."""
        verified = result.get("_verified_whatsapp_phone", "")
        if not result.get("_whatsapp_attempted") and not verified:
            verified = self.preflight_whatsapp(result, business_key)

        email_enabled = self.email_sending_enabled()
        email_recipients = self.email_recipients(result) if email_enabled else []
        has_website = bool(
            website.get("url")
            or website.get("has_website")
            or website.get("website_redirect_url")
        )
        if not email_enabled:
            self.channel_outcome(result, "email", "disabled", "Disabled in settings")
        elif not email_recipients:
            self.channel_outcome(result, "email", "no_email", "No email address found")
        if not verified and not email_recipients and not has_website:
            return False

        if not result.get("proposal"):
            self._log("A deliverable contact channel was found; generating the outreach message.")
            result["proposal"] = self.generate_website_proposal(website) or ""
        if not result.get("proposal"):
            return False

        sent_any = False
        if verified and not result.get("_whatsapp_attempted"):
            result["_whatsapp_attempted"] = True
            sent = self.send_whatsapp_message(result, business_key)
            if sent:
                result["whatsapp_sent"] = True
                sent_any = True

        # Email is an additional channel, not a fallback. If an address was
        # discovered, attempt it even when WhatsApp succeeded or needs review.
        if email_enabled and email_recipients:
            sent = self.send_email_message(result, business_key)
            if sent:
                result["email_sent"] = True
                sent_any = True
        return sent_any


    def channel_image_path(self, section):
        if not self.get_bool_setting(section, "send_image", default=False):
            return None
        raw_path = str(self.get_section_setting(section, "image_path", default="") or "").strip()
        if not raw_path:
            self._log(f"{section.title()} image is enabled but no image file is selected.")
            return None
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = Path(get_app_dir()) / path
        if not path.is_file():
            self._log(f"{section.title()} image file was not found: {path}")
            return None
        return path.resolve()

    def update_result_status(self, result):
        if result.get("email_sent") and result.get("whatsapp_sent"):
            result["status"] = "fallback_sent"
        elif result.get("email_sent"):
            result["status"] = "email_sent"
        elif result.get("whatsapp_sent"):
            result["status"] = "whatsapp_sent"
        elif result.get("channel_status", {}).get("whatsapp", {}).get("status") == "not_on_whatsapp":
            result["status"] = "not_on_whatsapp"
        else:
            result["status"] = "draft_ready" if result.get('proposal') else "draft_error"

    def _send_whatsapp_to_phone(self, result, business_key):
        if not self.get_bool_setting(
            "whatsapp",
            "enabled",
            default=True
        ):
            return self.channel_outcome(result, "whatsapp", "disabled", "Disabled in settings")

        message = (
            self.channel_message(
                result,
                "whatsapp"
            )
            or ""
        ).strip()
        send_image = self.get_bool_setting("whatsapp", "send_image", default=False)
        image_path = self.channel_image_path("whatsapp")

        phone = self.primary_whatsapp_phone(
            result
        )

        if not phone:
            return self.channel_outcome(result, "whatsapp", "no_phone", "No usable phone number")

        if not message and not image_path:
            return self.channel_outcome(result, "whatsapp", "no_message", "No proposal or image available")

        if send_image and not image_path:
            return self.channel_outcome(result, "whatsapp", "configuration_missing", "Select a valid image file")

        auto_send = self.get_bool_setting(
            "whatsapp",
            "auto_send",
            default=False
        )

        open_for_review = self.get_bool_setting(
            "whatsapp",
            "open_for_review",
            default=True
        )
        reuse_tab = auto_send and self.get_bool_setting(
            "whatsapp",
            "reuse_tab",
            default=True,
        )

        if not auto_send and not open_for_review:
            return self.channel_outcome(result, "whatsapp", "review", "Auto send is off")

        # Enabling WhatsApp images always sends the image by itself. The AI
        # proposal remains available for forms/email but is not sent as a
        # WhatsApp caption or separate message.
        outgoing_text = "" if send_image else message
        url = f"https://web.whatsapp.com/send?phone={phone}"
        if outgoing_text:
            url += f"&text={quote_plus(outgoing_text)}"

        original_window = None
        whatsapp_window = None
        send_timeout = max(30, int(self.get_section_setting(
            "whatsapp", "send_timeout_seconds", default=30
        )))
        login_timeout = max(10, int(self.get_section_setting(
            "whatsapp", "login_timeout_seconds", default=180
        )))
        button_timeout = login_timeout if not self.whatsapp_login_wait_used else send_timeout
        message_sent = False

        try:
            original_window = self.driver.current_window_handle
            existing_whatsapp = getattr(self, "whatsapp_window", None)
            if reuse_tab and existing_whatsapp in self.driver.window_handles:
                whatsapp_window = existing_whatsapp
                self.driver.switch_to.window(whatsapp_window)
                self._log("Reusing the existing WhatsApp tab.")
            else:
                self.driver.switch_to.new_window("tab")
                whatsapp_window = self.driver.current_window_handle
                if reuse_tab:
                    self.whatsapp_window = whatsapp_window
            self.driver.get(url)

            WebDriverWait(
                self.driver,
                send_timeout
            ).until(
                EC.presence_of_element_located(
                    (By.TAG_NAME, "body")
                )
            )

            self._log(
                f"WhatsApp opened for {phone}."
            )

            if not self.whatsapp_login_wait_used:
                self._log(
                    f"Waiting up to {login_timeout} seconds for the first WhatsApp login..."
                )

            if image_path:
                if not self.upload_whatsapp_image(image_path, timeout=button_timeout):
                    return self.channel_outcome(result, 'whatsapp', 'failed', 'Image upload failed')
                self._log(f"WhatsApp image attached: {image_path.name}")

            if not auto_send:
                return self.channel_outcome(result, 'whatsapp', 'review', 'Content opened for review; auto send is off')

            send_button = self.find_whatsapp_send_button(timeout=button_timeout)

            if not send_button:
                self.whatsapp_login_wait_used = True
                unavailable_reason = self.whatsapp_unavailable_reason()
                if unavailable_reason:
                    self.pause_before_invalid_whatsapp_continue()
                    self.dismiss_whatsapp_unavailable_dialog()
                    return self.channel_outcome(
                        result,
                        'whatsapp',
                        'not_on_whatsapp',
                        unavailable_reason,
                    )
                return self.channel_outcome(result, 'whatsapp', 'failed', 'Chat not ready, number unavailable, or WhatsApp login required')

            self.whatsapp_login_wait_used = True
            previous_ids = self.whatsapp_outgoing_ids()
            send_button.click()
            result['_whatsapp_send_clicked'] = True
            if not self.wait_for_whatsapp_confirmation(previous_ids, send_timeout):
                record_event(self.db, 'whatsapp_uncertain', business_key, result,
                             details='Send clicked but no new sent message was confirmed', recipient=phone)
                return self.channel_outcome(result, 'whatsapp', 'uncertain', 'Send clicked; confirmation timed out. Review the chat before retrying')
            message_sent = True
            result["whatsapp_sent"] = True
            record_event(
                self.db,
                EVENT_WHATSAPP_SENT,
                business_key,
                result,
                details="WhatsApp image sent" if image_path else "WhatsApp message confirmed sent",
                recipient=phone
            )
            self._log("WhatsApp image sent." if image_path else "WhatsApp message sent.")
            pause_min = max(0.0, float(self.get_section_setting(
                "whatsapp", "send_pause_min_seconds", default=0
            )))
            pause_max = max(pause_min, float(self.get_section_setting(
                "whatsapp", "send_pause_max_seconds", default=pause_min
            )))
            if pause_max:
                delay = uniform(pause_min, pause_max)
                self._log(f"Pausing {delay:.1f} seconds before the next WhatsApp contact.")
                sleep(delay)
            return True

        except Exception as e:
            if result.get('_whatsapp_send_clicked'):
                record_event(self.db, 'whatsapp_uncertain', business_key, result, details=str(e), recipient=phone)
            return self.channel_outcome(result, 'whatsapp', 'failed', str(e))

        finally:
            keep_tab_open = self.get_bool_setting(
                "whatsapp",
                "keep_tabs_open",
                default=not auto_send
            )

            try:
                if (
                    whatsapp_window
                    and whatsapp_window in self.driver.window_handles
                    and not keep_tab_open
                    and not reuse_tab
                    and (message_sent or (auto_send and not result.get('_whatsapp_send_clicked')))
                ):
                    self.driver.switch_to.window(
                        whatsapp_window
                    )
                    self.driver.close()

                if (
                    original_window
                    and original_window in self.driver.window_handles
                ):
                    self.driver.switch_to.window(
                        original_window
                    )

            except Exception:
                pass

    def upload_whatsapp_image(self, image_path, timeout=30):
        try:
            # Wait for the chat composer/login to become ready.
            WebDriverWait(self.driver, timeout).until(
                lambda driver: driver.find_elements(By.CSS_SELECTOR, "footer, [contenteditable='true']")
            )
            for by, selector in [
                (By.CSS_SELECTOR, "button[aria-label='Attach']"),
                (By.XPATH, "//*[@role='button' and @title='Attach']"),
                (By.XPATH, "//span[@data-icon='plus-rounded']/ancestor::*[@role='button'][1]"),
            ]:
                try:
                    button = self.driver.find_element(by, selector)
                    self.driver.execute_script("arguments[0].click();", button)
                    break
                except Exception:
                    continue

            upload = WebDriverWait(self.driver, timeout).until(
                lambda driver: next((
                    item for item in driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                    if "image" in (item.get_attribute("accept") or "").lower()
                ), False)
            )
            upload.send_keys(str(image_path))
            WebDriverWait(self.driver, timeout).until(
                lambda driver: self.find_whatsapp_send_button(timeout=1)
            )
            return True
        except Exception as exc:
            self._log(f"Could not attach WhatsApp image: {exc}")
            return False

    def find_whatsapp_send_button(self, timeout=10):
        selectors = [
            (By.CSS_SELECTOR, "button[aria-label='Send']"),
            (By.CSS_SELECTOR, "button[data-testid='compose-btn-send']"),
            (By.XPATH, "//span[@data-icon='send']/ancestor::button[1]"),
            (By.XPATH, "//*[@role='button' and .//span[@data-icon='send']]"),
        ]

        def first_clickable(driver):
            for by, selector in selectors:
                try:
                    for element in driver.find_elements(by, selector):
                        if element.is_displayed() and element.is_enabled():
                            return element
                except Exception:
                    continue
            # Stop waiting as soon as WhatsApp explicitly rejects the number.
            if self.whatsapp_unavailable_reason(driver):
                return "number-unavailable"
            return False

        try:
            result = WebDriverWait(
                self.driver,
                timeout
            ).until(first_clickable)
            return None if result == "number-unavailable" else result
        except TimeoutException:
            return None

    def whatsapp_unavailable_reason(self, driver=None):
        driver = driver or self.driver
        try:
            text = str(driver.execute_script(
                "return (document.body && document.body.innerText || '').toLowerCase();"
            ) or "").lower()
        except Exception:
            return ""

        markers = (
            "phone number shared via url is invalid",
            "phone number isn't on whatsapp",
            "phone number is not on whatsapp",
            "not a valid whatsapp number",
            "couldn't find this phone number",
            "could not find this phone number",
        )
        dynamic_number_error = re.search(
            r"\b(?:the\s+)?(?:phone\s+)?number\b.{0,60}\b(?:isn't|is not)\s+on\s+whatsapp\b",
            text,
            flags=re.DOTALL,
        )
        if any(marker in text for marker in markers) or dynamic_number_error:
            return "Number is invalid or not registered on WhatsApp; skipped"
        return ""

    def pause_before_invalid_whatsapp_continue(self):
        """Leave WhatsApp's invalid-number notice visible for review."""
        try:
            seconds = max(0, int(self.get_section_setting(
                "whatsapp", "invalid_number_pause_seconds", default=10
            )))
        except (TypeError, ValueError):
            seconds = 10
        if seconds:
            self._log(
                f"Number is not on WhatsApp; keeping the notice visible for "
                f"{seconds} second(s) before continuing."
            )
            sleep(seconds)

    def dismiss_whatsapp_unavailable_dialog(self, driver=None):
        """Close WhatsApp's invalid-number modal so the reused tab is ready."""
        driver = driver or self.driver
        selectors = (
            (By.XPATH, "//*[@role='dialog']//*[@role='button' and normalize-space()='OK']"),
            (By.XPATH, "//*[@role='dialog']//button[normalize-space()='OK']"),
            (By.XPATH, "//*[@role='button' and normalize-space()='OK']"),
            (By.XPATH, "//button[normalize-space()='OK']"),
        )
        for by, selector in selectors:
            try:
                for button in driver.find_elements(by, selector):
                    if button.is_displayed() and button.is_enabled():
                        try:
                            button.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", button)
                        self._log("WhatsApp invalid-number dialog dismissed; moving on.")
                        return True
            except Exception:
                continue
        return False


    def email_recipients(self, result):
        emails = list(
            dict.fromkeys(
                email.strip()
                for email in result.get("emails", [])
                if email and "@" in email
            )
        )

        if not self.get_bool_setting(
            "email",
            "send_to_all_found",
            default=False
        ):
            return emails[:1]

        return emails

    def _send_email_message(self, result, business_key):
        # Defense in depth for callers that bypass send_email_message().
        if not self.email_sending_enabled():
            return self.channel_outcome(result, "email", "disabled", "Disabled in settings")

        auto_send = self.get_bool_setting(
            "email",
            "auto_send",
            default=False
        )

        recipients = result.get('_email_recipients', self.email_recipients(result))

        if not recipients:
            return self.channel_outcome(result, "email", "no_email", "No email address found")

        message = (
            self.channel_message(
                result,
                "email"
            )
            or ""
        ).strip()
        image_path = self.channel_image_path("email")
        image_only = self.get_bool_setting("email", "image_only", default=False)

        if not message and not image_path:
            return self.channel_outcome(result, "email", "no_message", "No proposal or image available")
        if image_only and not image_path:
            return self.channel_outcome(result, "email", "configuration_missing", "Select a valid image file")

        if not auto_send:
            return self.channel_outcome(result, 'email', 'review', 'Auto send is off')

        smtp_host = self.get_section_setting(
            "email",
            "smtp_host",
            default="",
            env_key="SMTP_HOST"
        )
        smtp_port = int(
            self.get_section_setting(
                "email",
                "smtp_port",
                default=587,
                env_key="SMTP_PORT"
            )
        )
        smtp_username = self.get_section_setting(
            "email",
            "smtp_username",
            default="",
            env_key="SMTP_USERNAME"
        )
        smtp_password = self.get_section_setting(
            "email",
            "smtp_password",
            default="",
            env_key="SMTP_PASSWORD"
        )
        from_email = self.get_section_setting(
            "email",
            "from_email",
            default=self.config.get("contact_email", ""),
            env_key="SMTP_FROM_EMAIL"
        )
        from_name = self.get_section_setting(
            "email",
            "from_name",
            default=self.config.get("company_name", ""),
            env_key="SMTP_FROM_NAME"
        )
        subject = self.get_section_setting(
            "email",
            "subject",
            default="Software and digital services proposal"
        )

        if not smtp_host or not from_email:
            return self.channel_outcome(result, 'email', 'configuration_missing', 'SMTP host and sender email are required')

        email = EmailMessage()
        email["Subject"] = str(subject)
        email["From"] = (
            f"{from_name} <{from_email}>"
            if from_name
            else str(from_email)
        )
        email["To"] = ", ".join(
            recipients
        )
        email.set_content("" if image_only else message)
        if image_path:
            mime_type, _ = mimetypes.guess_type(str(image_path))
            major, minor = (mime_type or "application/octet-stream").split("/", 1)
            email.add_attachment(
                image_path.read_bytes(),
                maintype=major,
                subtype=minor,
                filename=image_path.name,
            )

        use_ssl = self.get_bool_setting(
            "email",
            "use_ssl",
            default=False
        )
        use_tls = self.get_bool_setting(
            "email",
            "use_tls",
            default=True
        )

        try:
            if use_ssl:
                server = smtplib.SMTP_SSL(
                    smtp_host,
                    smtp_port,
                    timeout=45
                )
            else:
                server = smtplib.SMTP(
                    smtp_host,
                    smtp_port,
                    timeout=45
                )

            with server:
                server.ehlo()

                if use_tls and not use_ssl:
                    server.starttls()
                    server.ehlo()

                if smtp_username:
                    server.login(
                        smtp_username,
                        smtp_password
                    )

                refused = server.send_message(email) or {}

            accepted = [address for address in recipients if address not in refused]
            for address in accepted:
                record_event(self.db, EVENT_EMAIL_SENT, business_key, result,
                             details='SMTP accepted message', recipient=address.lower())
            result['email_sent'] = bool(accepted)
            self.channel_outcome(result, 'email', 'partial_sent' if refused else 'sent',
                                 f'{len(accepted)} accepted by SMTP; {len(refused)} refused')
            return bool(accepted)

        except Exception as e:
            return self.channel_outcome(result, 'email', 'failed', str(e))


    def is_ignored_url(self, url):
        """Match a URL against configured domains, URLs, or URL fragments."""
        candidate = (url or "").strip().lower()
        if not candidate:
            return False

        parsed_candidate = urlparse(candidate)
        candidate_host = parsed_candidate.netloc.removeprefix("www.")
        candidate_path = parsed_candidate.path.rstrip("/")

        ignored = self.config.get("ignore_urls", [])
        if isinstance(ignored, str):
            ignored = [ignored]

        for value in ignored:
            pattern = str(value or "").strip().lower().rstrip("/")
            if not pattern:
                continue

            parsed_pattern = urlparse(
                pattern if "://" in pattern else f"//{pattern}"
            )
            pattern_host = parsed_pattern.netloc.removeprefix("www.")
            pattern_path = parsed_pattern.path.rstrip("/")

            host_matches = (
                candidate_host == pattern_host
                or candidate_host.endswith(f".{pattern_host}")
            )
            if host_matches and (
                not pattern_path
                or candidate_path == pattern_path
                or candidate_path.startswith(f"{pattern_path}/")
            ):
                return True

        return False

    def business_key(self, website):
        """Return a stable domain/name key for deduplication."""
        if website.get("_business_key"):
            return website["_business_key"]
        url = website.get("url", "").strip().lower()
        name = website.get("name", "").strip().lower()
        parsed = urlparse(url) if url else None
        value = (parsed.netloc.removeprefix("www.") if parsed else "") or name
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def was_previously_processed(self, business_key):
        if not bool(
            self.config.get("skip_previously_processed", True)
        ):
            return False

        campaign = self.config.get("campaign", {})
        never_repeat = isinstance(campaign, dict) and bool(
            campaign.get("never_repeat_contacted", True)
        )
        if never_repeat and self.db.execute(
            """SELECT 1 FROM outreach_events
               WHERE business_key=? AND event_type IN (?,?) LIMIT 1""",
            (business_key, EVENT_WHATSAPP_SENT, EVENT_EMAIL_SENT),
        ).fetchone():
            self._log("Skipping business because a message was already sent previously.")
            return True

        row = self.db.execute(
            "SELECT updated_at, status FROM outreach WHERE business_key = ?", (business_key,)
        ).fetchone()
        if not row or row[1] in {"discovered", "error", "website_error", "draft_error", "processing"}:
            return False

        cooldown_days = max(1, int(self.config.get("reprocess_after_days", 40)))
        try:
            last_processed = datetime.fromisoformat(str(row[0] or ""))
            age = datetime.now() - last_processed
            if age < timedelta(days=cooldown_days):
                remaining = max(1, cooldown_days - age.days)
                self._log(
                    f"Skipping business processed recently; eligible again in "
                    f"about {remaining} day(s)."
                )
                return True
            return False
        except (TypeError, ValueError):
            # Old records without a usable timestamp remain protected rather
            # than risking an immediate duplicate message.
            self._log("Skipping previously processed business with no valid timestamp.")
            return True

    def save_outreach(self, business_key, result):
        result["proposal"] = clean_outreach_message(result.get("proposal", ""))
        self.db.execute(
            '''INSERT INTO outreach (
                business_key, business_name, website, contact_page, emails,
                phones, proposal, form_prefilled, status, updated_at, area_key,
                business_context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(business_key) DO UPDATE SET
                business_name=excluded.business_name, website=excluded.website,
                contact_page=excluded.contact_page, emails=excluded.emails,
                phones=excluded.phones, proposal=excluded.proposal,
                form_prefilled=excluded.form_prefilled, status=excluded.status,
                updated_at=excluded.updated_at,
                area_key=CASE WHEN outreach.area_key='' THEN excluded.area_key ELSE outreach.area_key END,
                business_context=CASE
                    WHEN excluded.business_context<>'' THEN excluded.business_context
                    ELSE outreach.business_context
                END''',
            (
                business_key, result.get("name", ""), result.get("website", ""),
                result.get("contact_page", ""), json.dumps(result.get("emails", [])),
                json.dumps(result.get("phones", [])), result.get("proposal", ""),
                int(result.get("form_prefilled", False)), result.get("status", "draft_ready"),
                datetime.now().isoformat(timespec="seconds"), result.get("area_key", ""),
                result.get("business_context", "")
            )
        )
        self.db.execute('UPDATE outreach SET channel_status=?,whatsapp_phones=?,last_error=? WHERE business_key=?',
                        (json.dumps(result.get('channel_status', {})), json.dumps(result.get('whatsapp_phones', [])),
                         result.get('last_error',''), business_key))
        self.db.commit()

    def append_draft(self, result):
        """Export each prepared outreach item and its send/review state."""
        path = self.data_dir / "outreach_drafts.csv"
        exists = path.exists()
        message = result.get("proposal", "")
        whatsapp_message = self.channel_message(
            result,
            "whatsapp"
        )
        phone = (result.get("phones") or [""])[0]
        digits = re.sub(r"\D", "", phone)
        whatsapp_url = ""
        if digits and whatsapp_message:
            whatsapp_url = f"https://wa.me/{digits}?text={quote_plus(whatsapp_message)}"
        fields = ["business_name", "website", "contact_page", "emails", "phones",
                  "proposal", "form_prefilled", "whatsapp_sent", "email_sent",
                  "whatsapp_review_url", "status"]
        with path.open("a", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            if not exists:
                writer.writeheader()
            writer.writerow({
                "business_name": result.get("name", ""),
                "website": result.get("website", ""),
                "contact_page": result.get("contact_page", ""),
                "emails": "; ".join(result.get("emails", [])),
                "phones": "; ".join(result.get("phones", [])),
                "proposal": message,
                "form_prefilled": result.get("form_prefilled", False),
                "whatsapp_sent": result.get("whatsapp_sent", False),
                "email_sent": result.get("email_sent", False),
                "whatsapp_review_url": whatsapp_url,
                "status": result.get("status", "draft_ready")
            })

    def normalize_text(self, text):
        """
        Normalize text so that comparisons are easier.
        """

        if not text:
            return ""

        text = str(text).lower()

        # Replace common separators with spaces
        text = re.sub(r"[_\-]+", " ", text)

        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text)

        return text.strip()


    def get_element_information(self, element):
        """
        Collect all useful information from a form element.

        This helps us identify fields even when websites
        use different names.
        """

        values = []

        try:
            attributes = [
                "name",
                "id",
                "placeholder",
                "aria-label",
                "autocomplete",
                "title",
                "type"
            ]

            for attribute in attributes:

                try:

                    value = element.get_attribute(
                        attribute
                    )

                    if value:
                        values.append(
                            self.normalize_text(value)
                        )

                except Exception:
                    pass

            # -----------------------------------------
            # Get associated label
            # -----------------------------------------

            try:

                element_id = element.get_attribute("id")

                if element_id:

                    labels = self.driver.find_elements(
                        By.XPATH,
                        f"//label[@for='{element_id}']"
                    )

                    for label in labels:

                        try:

                            label_text = label.text

                            if label_text:
                                values.append(
                                    self.normalize_text(
                                        label_text
                                    )
                                )

                        except Exception:
                            pass

            except Exception:
                pass

            # -----------------------------------------
            # Get parent/container text
            # -----------------------------------------

            try:

                parent = element.find_element(
                    By.XPATH,
                    "./ancestor::*[self::div or self::p or self::label][1]"
                )

                parent_text = parent.text

                if parent_text:

                    values.append(
                        self.normalize_text(
                            parent_text
                        )
                    )

            except Exception:
                pass

        except Exception:
            pass

        # Remove empty values
        values = [
            value
            for value in values
            if value
        ]

        return " ".join(values)



    def find_contact_form(self):
        """
        Find a likely contact form on the current page.
        """

        self._log("Looking for contact form...")

        try:
            forms = self.driver.find_elements(
                By.TAG_NAME,
                "form"
            )

            if not forms:
                self._log("No form tags found; scanning page fields.")
                try:
                    body = self.driver.find_element(
                        By.TAG_NAME,
                        "body"
                    )
                    forms = [body]
                except Exception:
                    return None

            # First try to find a form that looks like a contact form
            for form in forms:

                try:
                    form_text = form.text.lower()

                    # Check inputs inside this form
                    inputs = form.find_elements(
                        By.CSS_SELECTOR,
                        "input, textarea, select, [contenteditable='true']"
                    )

                    field_names = []

                    for field in inputs:

                        try:
                            field_name = (
                                field.get_attribute("name")
                                or ""
                            ).lower()

                            field_id = (
                                field.get_attribute("id")
                                or ""
                            ).lower()

                            placeholder = (
                                field.get_attribute("placeholder")
                                or ""
                            ).lower()

                            aria_label = (
                                field.get_attribute("aria-label")
                                or ""
                            ).lower()

                            field_names.append(
                                f"{field_name} "
                                f"{field_id} "
                                f"{placeholder} "
                                f"{aria_label}"
                            )

                        except Exception:
                            continue

                    combined = (
                        form_text
                        + " "
                        + " ".join(field_names)
                    )

                    contact_words = [
                        "contact",
                        "message",
                        "email",
                        "phone",
                        "enquiry",
                        "inquiry",
                        "your-name",
                        "your-email"
                    ]

                    matches = sum(
                        1
                        for word in contact_words
                        if word in combined
                    )

                    if matches >= 2:

                        self._log(
                            "Contact form found."
                        )

                        return form

                except Exception as e:

                    self._log(
                        f"Error checking form: {e}"
                    )

            # If we couldn't identify one specifically,
            # use the first form that contains an email field.
            for form in forms:

                try:

                    email_fields = form.find_elements(
                        By.CSS_SELECTOR,
                        "input[type='email'], input[name*='email' i], "
                        "input[id*='email' i], input[placeholder*='email' i]"
                    )

                    if email_fields:

                        self._log(
                            "Form with email field found."
                        )

                        return form

                except Exception:
                    continue

            for form in forms:

                try:

                    message_fields = form.find_elements(
                        By.CSS_SELECTOR,
                        "textarea, [contenteditable='true'], "
                        "input[name*='message' i], input[id*='message' i], "
                        "input[placeholder*='message' i], "
                        "input[name*='comment' i], input[id*='comment' i], "
                        "input[placeholder*='comment' i]"
                    )

                    if message_fields:

                        self._log(
                            "Form with message field found."
                        )

                        return form

                except Exception:
                    continue

            for form in forms:

                try:

                    fields = form.find_elements(
                        By.CSS_SELECTOR,
                        "input, textarea, select, [contenteditable='true']"
                    )

                    visible_fields = []

                    for field in fields:

                        field_type = (
                            field.get_attribute("type")
                            or ""
                        ).lower()

                        if field_type == "hidden":
                            continue

                        try:
                            if not field.is_displayed():
                                continue
                        except Exception:
                            pass

                        visible_fields.append(field)

                    if len(visible_fields) >= 2:

                        self._log(
                            "Generic form fields found."
                        )

                        return form

                except Exception:
                    continue

            self._log(
                "Contact form not found."
            )

            return None

        except Exception as e:

            self._log(
                f"Error finding contact form: {e}"
            )

            return None


    def find_form_field(
        self,
        form,
        keywords,
        field_type=None
    ):
        """
        Find a form field using multiple methods.

        Checks:
        - name
        - id
        - placeholder
        - aria-label
        - label text
        """

        if form is None:
            return None

        try:

            # -----------------------------------------
            # Get all possible form fields
            # -----------------------------------------

            fields = form.find_elements(
                By.CSS_SELECTOR,
                "input, textarea, select, [contenteditable='true']"
            )

            if not fields:
                return None

            # -----------------------------------------
            # Normalize keywords
            # -----------------------------------------

            normalized_keywords = []

            for keyword in keywords:

                if keyword:

                    normalized_keywords.append(
                        keyword.lower().replace(
                            "_",
                            "-"
                        ).replace(
                            " ",
                            "-"
                        )
                    )

            # -----------------------------------------
            # Check every field
            # -----------------------------------------

            for field in fields:

                try:

                    # Ignore hidden fields
                    field_type_value = (
                        field.get_attribute("type")
                        or ""
                    ).lower()

                    if field_type_value == "hidden":
                        continue

                    # ---------------------------------
                    # Field attributes
                    # ---------------------------------

                    name = (
                        field.get_attribute("name")
                        or ""
                    ).lower()

                    field_id = (
                        field.get_attribute("id")
                        or ""
                    ).lower()

                    placeholder = (
                        field.get_attribute(
                            "placeholder"
                        )
                        or ""
                    ).lower()

                    aria_label = (
                        field.get_attribute(
                            "aria-label"
                        )
                        or ""
                    ).lower()

                    # ---------------------------------
                    # Get associated label
                    # ---------------------------------

                    label_text = ""

                    try:

                        field_id_value = (
                            field.get_attribute("id")
                        )

                        if field_id_value:

                            labels = form.find_elements(
                                By.CSS_SELECTOR,
                                f"label[for='{field_id_value}']"
                            )

                            if labels:

                                label_text = (
                                    labels[0].text
                                    or ""
                                ).lower()

                    except Exception:
                        pass

                    # ---------------------------------
                    # Also check parent label
                    # ---------------------------------

                    try:

                        parent_label = field.find_element(
                            By.XPATH,
                            "./ancestor::label[1]"
                        )

                        if parent_label:

                            label_text += " " + (
                                parent_label.text
                                or ""
                            ).lower()

                    except Exception:
                        pass

                    # ---------------------------------
                    # Combine everything
                    # ---------------------------------

                    values = [
                        name,
                        field_id,
                        placeholder,
                        aria_label,
                        label_text,
                        field.get_attribute("class") or "",
                        field.get_attribute("title") or "",
                        self.get_element_information(field)
                    ]

                    combined = " ".join(
                        values
                    )

                    # Normalize
                    combined = (
                        combined
                        .replace("_", "-")
                        .replace(" ", "-")
                    )

                    # ---------------------------------
                    # Field type matching
                    # ---------------------------------

                    if field_type:

                        if field_type == "email":

                            if field_type_value != "email":

                                # Still allow fields whose
                                # name clearly says email
                                if "email" not in combined:
                                    continue

                        elif field_type == "tel":

                            if field_type_value not in [
                                "tel",
                                "text"
                            ]:

                                if not any(
                                    x in combined
                                    for x in [
                                        "phone",
                                        "telephone",
                                        "mobile",
                                        "tel"
                                    ]
                                ):
                                    continue

                        elif field_type == "textarea":

                            tag_name = field.tag_name.lower()
                            is_contenteditable = (
                                field.get_attribute("contenteditable")
                                or ""
                            ).lower() == "true"

                            if (
                                tag_name != "textarea"
                                and not is_contenteditable
                            ):
                                message_like_input = (
                                    tag_name == "input"
                                    and field_type_value in [
                                        "",
                                        "text",
                                        "search"
                                    ]
                                    and any(
                                        x in combined
                                        for x in [
                                            "message",
                                            "comment",
                                            "enquiry",
                                            "inquiry",
                                            "description",
                                            "details"
                                        ]
                                    )
                                )

                                if not message_like_input:
                                    continue

                    # ---------------------------------
                    # Keyword matching
                    # ---------------------------------

                    for keyword in normalized_keywords:

                        if keyword in combined:

                            self._log(
                                f"Matched field: "
                                f"name='{name}', "
                                f"id='{field_id}', "
                                f"placeholder='{placeholder}'"
                            )

                            return field

                except Exception:
                    continue

            return None

        except Exception as e:

            self._log(
                f"find_form_field error: {e}"
            )

            return None

    def fill_field_value(self, field, value):
        """
        Fill normal inputs, textareas, selects, and contenteditable fields.
        """

        value = str(value or "").strip()
        if not value:
            return False

        try:
            tag_name = field.tag_name.lower()
            is_contenteditable = (
                field.get_attribute("contenteditable")
                or ""
            ).lower() == "true"

            field.click()

            if is_contenteditable:
                try:
                    self.driver.execute_script(
                        "arguments[0].innerText = '';"
                        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));",
                        field
                    )
                except Exception:
                    field.send_keys(Keys.CONTROL, "a")
                    field.send_keys(Keys.BACKSPACE)

                field.send_keys(value)
                return True

            if tag_name != "select":
                try:
                    field.clear()
                except Exception:
                    field.send_keys(Keys.CONTROL, "a")
                    field.send_keys(Keys.BACKSPACE)

            field.send_keys(value)
            return True

        except Exception as e:
            self._log(
                f"Field fill error: {e}"
            )
            return False


    def submit_contact_form(self, form):
        """Submit a filled contact form once and wait briefly for an outcome."""
        before_url = str(getattr(self.driver, "current_url", "") or "")
        submit_button = None
        selectors = (
            "button[type='submit']",
            "input[type='submit']",
            "button[name*='submit' i]",
            "button[id*='submit' i]",
            "button[class*='submit' i]",
            "button[name*='send' i]",
            "button[id*='send' i]",
            "button[aria-label*='send' i]",
            "button[title*='send' i]",
        )

        for selector in selectors:
            try:
                for candidate in form.find_elements(By.CSS_SELECTOR, selector):
                    if candidate.is_displayed() and candidate.is_enabled():
                        submit_button = candidate
                        break
            except Exception:
                continue
            if submit_button:
                break

        if not submit_button:
            try:
                text_buttons = form.find_elements(
                    By.XPATH,
                    ".//*[self::button or @role='button']["
                    "contains(translate(normalize-space(.), "
                    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'send') or "
                    "contains(translate(normalize-space(.), "
                    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'submit') or "
                    "contains(translate(normalize-space(.), "
                    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'enquire') or "
                    "contains(translate(normalize-space(.), "
                    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'request quote')]"
                )
                submit_button = next(
                    (button for button in text_buttons
                     if button.is_displayed() and button.is_enabled()),
                    None,
                )
            except Exception:
                submit_button = None

        clicked = False
        if submit_button:
            try:
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});",
                    submit_button,
                )
            except Exception:
                pass
            try:
                submit_button.click()
                clicked = True
            except Exception:
                try:
                    self.driver.execute_script("arguments[0].click();", submit_button)
                    clicked = True
                except Exception as exc:
                    self._log(f"Contact form submit-button error: {exc}")
        else:
            # requestSubmit preserves browser validation and submit handlers.
            try:
                clicked = bool(self.driver.execute_script(
                    """
                    const form = arguments[0];
                    if (!form || !form.requestSubmit) return false;
                    form.requestSubmit();
                    return true;
                    """,
                    form,
                ))
            except Exception as exc:
                self._log(f"Contact form submit control not found: {exc}")

        if not clicked:
            self._log("Contact form was filled, but no usable submit control was found.")
            return "not_submitted"

        self._log("Contact form submit action triggered.")
        success_selectors = (
            ".wpcf7-mail-sent-ok",
            ".wpcf7-response-output",
            ".wpforms-confirmation-container",
            ".elementor-message-success",
            ".form-success",
            ".success-message",
            ".alert-success",
            "[role='alert']",
        )
        success_words = ("thank", "success", "sent", "received", "submitted")

        def submission_outcome(driver):
            try:
                if before_url and str(driver.current_url or "") != before_url:
                    return "submitted"
            except Exception:
                return "submitted"

            try:
                invalid = driver.execute_script(
                    "return !!(arguments[0] && arguments[0].querySelector(':invalid'));",
                    form,
                )
                if invalid:
                    return "validation_failed"
            except Exception:
                # A detached form usually means an AJAX submission replaced it.
                return "submitted"

            for selector in success_selectors:
                try:
                    for element in driver.find_elements(By.CSS_SELECTOR, selector):
                        text = str(element.text or "").strip().lower()
                        if element.is_displayed() and any(word in text for word in success_words):
                            return "submitted"
                except Exception:
                    continue
            return False

        try:
            outcome = WebDriverWait(self.driver, 10, poll_frequency=0.25).until(
                submission_outcome
            )
        except TimeoutException:
            outcome = "clicked_unconfirmed"
        except Exception as exc:
            self._log(f"Contact form confirmation check error: {exc}")
            outcome = "clicked_unconfirmed"

        if outcome == "submitted":
            self._log("Contact form submission confirmed.")
        elif outcome == "validation_failed":
            self._log("Contact form submission was blocked by a required field or validation.")
        else:
            self._log("Contact form was clicked once, but the website showed no clear confirmation.")
        return outcome


    def fill_contact_form(
        self,
        name,
        email,
        phone,
        message,
        subject="Website Enquiry"
    ):
        """
        Generic contact form filler.

        Attempts to work with different website
        contact forms by detecting fields using:

        - name
        - id
        - placeholder
        - aria-label
        - label
        """

        self._log(
            "Looking for contact form..."
        )

        form = self.find_contact_form()

        if not form:

            self._log(
                "Contact form not found."
            )

            return False

        self._log(
            "Contact form found."
        )

        filled_count = 0
        message_filled = False

        # =====================================================
        # NAME
        # =====================================================

        try:

            name_field = self.find_form_field(
                form,
                [
                    "name",
                    "full-name",
                    "fullname",
                    "your-name",
                    "your_name",
                    "first-name",
                    "firstname"
                ]
            )

            if name_field:

                if self.fill_field_value(
                    name_field,
                    name
                ):

                    filled_count += 1

                    self._log(
                        "Name field filled."
                    )

            else:

                self._log(
                    "Name field not found."
                )

        except Exception as e:

            self._log(
                f"Name field error: {e}"
            )

        # =====================================================
        # EMAIL
        # =====================================================

        try:

            email_field = self.find_form_field(
                form,
                [
                    "email",
                    "e-mail",
                    "your-email",
                    "your_email",
                    "email-address",
                    "emailaddress"
                ],
                field_type="email"
            )

            if email_field:

                if self.fill_field_value(
                    email_field,
                    email
                ):

                    filled_count += 1

                    self._log(
                        "Email field filled."
                    )

            else:

                self._log(
                    "Email field not found."
                )

        except Exception as e:

            self._log(
                f"Email field error: {e}"
            )

        # =====================================================
        # PHONE
        # =====================================================

        try:

            phone_field = self.find_form_field(
                form,
                [
                    "phone",
                    "telephone",
                    "mobile",
                    "tel",
                    "contact-number",
                    "contactnumber",
                    "contact-phone",
                    "your-phone",
                    "your_phone",
                    "phone-number",
                    "phonenumber"
                ],
                field_type="tel"
            )

            if phone_field:

                if self.fill_field_value(
                    phone_field,
                    phone
                ):

                    filled_count += 1

                    self._log(
                        "Phone field filled."
                    )

            else:

                self._log(
                    "Phone field not found."
                )

        except Exception as e:

            self._log(
                f"Phone field error: {e}"
            )

        # =====================================================
        # SUBJECT
        # =====================================================

        try:

            subject_field = self.find_form_field(
                form,
                [
                    "subject",
                    "your-subject",
                    "your_subject",
                    "topic",
                    "title"
                ]
            )

            if subject_field:

                if self.fill_field_value(
                    subject_field,
                    subject
                ):

                    filled_count += 1

                    self._log(
                        "Subject field filled."
                    )

            else:

                self._log(
                    "Subject field not found."
                )

        except Exception as e:

            self._log(
                f"Subject field error: {e}"
            )

        # =====================================================
        # MESSAGE
        # =====================================================

        try:

            message_field = self.find_form_field(
                form,
                [
                    "message",
                    "comment",
                    "comments",
                    "enquiry",
                    "inquiry",
                    "your-message",
                    "your_message",
                    "message-body",
                    "description",
                    "details"
                ],
                field_type="textarea"
            )

            if message_field:

                if self.fill_field_value(
                    message_field,
                    message
                ):

                    filled_count += 1

                    message_filled = True
                    self._log("Message field filled.")

            else:

                self._log(
                    "Message field not found."
                )

        except Exception as e:

            self._log(
                f"Message field error: {e}"
            )

        # =====================================================
        # RESULT
        # =====================================================

        self._log(
            f"Form fields filled: {filled_count}"
        )

        if not message_filled:

            self._log(
                "✗ Could not fill any form fields."
            )

            return False

        self._log(
            f"✓ Successfully filled "
            f"{filled_count} form fields."
        )

        if bool(self.config.get("review_mode", True)):
            self.last_form_submission_status = "review"
            return True

        self.last_form_submission_status = self.submit_contact_form(form)

        return True

    



        
if __name__ == "__main__":
    mode = "full"
    retry_business_key = ""
    if "--pending-whatsapp" in sys.argv:
        mode = "pending-whatsapp"
    elif "--pending-email" in sys.argv:
        mode = "pending-email"
    elif "--retry-whatsapp" in sys.argv:
        mode = "retry-whatsapp"
        retry_business_key = sys.argv[sys.argv.index("--retry-whatsapp") + 1]
    elif "--retry-email" in sys.argv:
        mode = "retry-email"
        retry_business_key = sys.argv[sys.argv.index("--retry-email") + 1]
    print(f"[Marketing Bot] Launching {mode}...", flush=True)
    automation = Automation(mode=mode, retry_business_key=retry_business_key)
    print("[Marketing Bot] Session ended.", flush=True)

