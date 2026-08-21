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
from tkinter import messagebox
from email.message import EmailMessage
from random import uniform
from time import sleep
import smtplib
import tkinter as tk
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
from progress_tracker import (
    EVENT_EMAIL_SENT,
    EVENT_FORM_PREFILLED,
    EVENT_WEBSITE_OPENED,
    EVENT_WHATSAPP_SENT,
    ensure_progress_schema,
    record_event,
)



try:
    from cloakbrowser.download import ensure_binary
    from cloakbrowser.config import get_chromium_version, get_default_stealth_args

    _HAS_CLOAK = True
except ImportError:
    _HAS_CLOAK = False


load_dotenv()


class Automation:
    
    def write_log_header(self, title, width=70):
        self._log("=" * width)
        self._log(title.center(width))
        self._log("=" * width)

    
    def _log(self, message):
        print(f"[Marketing Bot] {message}")

        # Skip file logging when started from dashboard.py
        if sys.argv[0].endswith("dashboard.py"):
            return

        from app_paths import get_app_dir
        from session_logger import append_log_line

        try:
            SCRIPT_DIR = get_app_dir()
            append_log_line(message, SCRIPT_DIR)
        except OSError:
            pass

    def __init__(self):
        self.config = self.read_json('config.json')
        

        if self.config:
            self.write_log_header("Marketing Bot started.")
            self._log("Settings loaded from config.json.")
        else:
            self._log("Warning: config.json is missing or empty — check your dashboard settings.")

        self.headless = bool(self.config.get('headless', False))
        self.limit = max(1, int(self.config.get('limit', 10)))
        self.search_query = str(self.config.get('search_query', 'business near me')).strip()
        self.data_dir = Path(self.config.get('data_dir', 'data'))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.data_dir / 'outreach.sqlite3')
        self.db.execute('''CREATE TABLE IF NOT EXISTS outreach (
            business_key TEXT PRIMARY KEY, business_name TEXT, website TEXT,
            contact_page TEXT, emails TEXT, phones TEXT, proposal TEXT,
            form_prefilled INTEGER DEFAULT 0, status TEXT, updated_at TEXT
        )''')
        ensure_progress_schema(self.db)
        self.db.commit()
        browser_mode = "headless (no window)" if self.headless else "visible"
        self._log(f"Opening Chrome browser — {browser_mode}...")
        from app_paths import get_app_dir
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

        self._log("Browser ready.")
        self.iframe_found = False

        self.start_automation()

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

    def start_automation(self):
        self._log("Automation run started.")

        # Open Google and search
        google_page = self.search_business()

        if google_page is None:
            self._log("Could not open Google.")
            return

        # Process websites
        results = self.process_all_websites(
            google_page,
            limit=self.limit
        )

        self._log(
            f"Automation completed. "
            f"Total websites processed: {len(results)}"
        )

        if (
            not self.headless
            and any(item.get("form_prefilled") for item in results)
        ):
            input(
                "Review the prefilled contact-form tabs. Submit only where appropriate, "
                "then press Enter to close the browser..."
            )

        # Debug pause if you want
        # input("Press Enter to close browser...")

        self._close_browser_safely()

    # =========================================================
    # SEARCH BUSINESS ON GOOGLE
    # =========================================================

    # def search_business(self):

    #     self._log("Searching business...")

    #     self.random_sleep()

    #     self.wait = WebDriverWait(
    #         self.driver,
    #         30
    #     )

    #     try:

    #         google_url = (
    #             "https://www.google.com/search?q=business+near+me&sca_esv=32b8bdd6e2d39944&hl=en&udm=1&lsack=Vjl3auavCsLj7_UPgdyI2AE&sa=X&ved=2ahUKEwjmsoy1m5GWAxXC8bsIHQEuAhsQjGp6BAguEAA&biw=1904&bih=380&dpr=1"
    #         )

    #         self.driver.get(google_url)

    #         self._log(
    #             "Google search page opened successfully."
    #         )
    #         # Wait for Google results
    #         try:

    #             self.wait.until(
    #                 EC.presence_of_element_located(
    #                     (By.TAG_NAME, "body")
    #                 )
    #             )

    #         except TimeoutException:

    #             self._log(
    #                 "Google page loaded but body was not found."
    #             )

    #         return self.driver

    #     except Exception as e:

    #         self._log(
    #             f"Error opening Google: {e}"
    #         )

    #         return None

    def search_business(self):

        self._log("Searching business...")

        self.random_sleep()

        self.wait = WebDriverWait(
            self.driver,
            30
        )

        try:

            google_url = "https://www.google.com/search?q=" + quote_plus(self.search_query)

            self._log(
                f"Opening Google: {google_url}"
            )

            self.driver.get(google_url)

            # Wait until page body exists
            self.wait.until(
                EC.presence_of_element_located(
                    (By.TAG_NAME, "body")
                )
            )

            self._log(
                "Google search page opened successfully."
            )

            # Give Google a little time to render
            self.random_sleep()

            return self.driver

        except TimeoutException:

            self._log(
                "Google page loaded but body was not found."
            )

            return None

        except Exception as e:

            self._log(
                f"Error opening Google: {type(e).__name__}: {e}"
            )

            return None


    def get_google_websites(self, page):

        self._log(
            "Finding business website links from Google..."
        )

        if page is None:

            self._log(
                "Google page is None."
            )

            return []

        websites = []
        seen = set()

        try:

            # =====================================================
            # METHOD 1
            # New Google local/business results
            #
            # Google now creates:
            #
            # /goto?url=XXXXXXXX
            #
            # instead of directly giving:
            #
            # https://example.com
            # =====================================================

            website_links = page.find_elements(
                By.XPATH,
                "//a[.//span[normalize-space()='Website']]"
            )

            self._log(
                f"Found {len(website_links)} Google Website buttons."
            )

            for link in website_links:

                try:

                    href = link.get_attribute("href")

                    if not href:
                        continue

                    # Convert relative URL to absolute Google URL
                    if href.startswith("/"):
                        href = urljoin(
                            self.driver.current_url,
                            href
                        )

                    self._log(
                        f"Google Website link: {href}"
                    )

                    # =================================================
                    # New Google /goto link
                    # =================================================

                    if "/goto?" in href:

                        website_url = self.resolve_google_website(
                            href
                        )

                    else:

                        # Old/direct format
                        website_url = href

                    if not website_url:
                        self._log(
                            "Could not resolve website URL."
                        )
                        continue

                    website_url = website_url.strip()

                    if not website_url.startswith(
                        ("http://", "https://")
                    ):
                        continue

                    if self.is_ignored_url(website_url):
                        self._log(f"Ignoring configured URL: {website_url}")
                        continue

                    # Parse domain
                    parsed = urlparse(website_url)

                    domain = parsed.netloc.lower()

                    # Remove www
                    if domain.startswith("www."):
                        domain = domain[4:]

                    # Ignore Google
                    if (
                        "google.com" in domain
                        or "google.ae" in domain
                        or "googleusercontent.com" in domain
                    ):
                        continue

                    # Remove duplicate domains
                    if domain in seen:
                        continue

                    seen.add(domain)

                    # Try to get business name
                    name = ""

                    try:

                        parent = link.find_element(
                            By.XPATH,
                            "./ancestor::div[contains(@class,'w7Dbne')][1]"
                        )

                        name_element = parent.find_element(
                            By.CSS_SELECTOR,
                            ".dbg0pd .OSrXXb"
                        )

                        name = name_element.text.strip()

                    except Exception:
                        pass

                    websites.append({
                        "name": name,
                        "url": website_url
                    })

                    self._log(
                        f"Website found: {name} -> {website_url}"
                    )

                except Exception as e:

                    self._log(
                        f"Error reading Website button: {e}"
                    )

            # =====================================================
            # METHOD 2
            # Fallback for older Google result format
            # =====================================================

            if not websites:

                self._log(
                    "No new-style Website buttons found."
                )

                self._log(
                    "Trying fallback method for older Google results..."
                )

                links = page.find_elements(
                    By.CSS_SELECTOR,
                    "a[href]"
                )

                self._log(
                    f"Google returned {len(links)} links."
                )

                for link in links:

                    try:

                        href = link.get_attribute("href")

                        if not href:
                            continue

                        # Direct HTTP links
                        if not href.startswith(
                            ("http://", "https://")
                        ):
                            continue

                        if self.is_ignored_url(href):
                            self._log(f"Ignoring configured URL: {href}")
                            continue

                        parsed = urlparse(href)

                        domain = parsed.netloc.lower()

                        if domain.startswith("www."):
                            domain = domain[4:]

                        # Ignore Google
                        if (
                            "google.com" in domain
                            or "google.ae" in domain
                            or "googleusercontent.com" in domain
                        ):
                            continue

                        # Ignore Maps
                        if "google.com/maps" in href:
                            continue

                        if domain in seen:
                            continue

                        seen.add(domain)

                        websites.append({
                            "name": "",
                            "url": href
                        })

                    except Exception as e:

                        self._log(
                            f"Fallback link error: {e}"
                        )

            self._log(
                f"Found {len(websites)} unique websites."
            )

            # Include visible Google business cards that have no website.
            # These can still be drafted for review when Google exposes a phone.
            known_names = {item.get("name", "").strip().lower() for item in websites}
            for card in page.find_elements(By.CSS_SELECTOR, "div.w7Dbne"):
                try:
                    name_nodes = card.find_elements(By.CSS_SELECTOR, ".dbg0pd .OSrXXb")
                    name = name_nodes[0].text.strip() if name_nodes else ""
                    if not name or name.lower() in known_names:
                        continue
                    text = card.text
                    phones = self.extract_phone_numbers(text)
                    websites.append({"name": name, "url": "", "phones": phones})
                    known_names.add(name.lower())
                except Exception:
                    continue

            return websites

        except Exception as e:

            self._log(
                f"Error finding Google websites: "
                f"{type(e).__name__}: {e}"
            )

            return []

    # =========================================================
    # OPEN WEBSITE
    # =========================================================

    # def open_website(self, website):

    #     """
    #     Opens a website in a NEW browser tab.
    #     """

    #     url = website.get(
    #         "url",
    #         ""
    #     )

    #     if not url:

    #         self._log(
    #             "Website URL is empty."
    #         )

    #         return None

    #     self._log(
    #         f"Opening website: {url}"
    #     )

    #     try:

    #         # Save current tab
    #         original_window = self.driver.current_window_handle

    #         # Selenium 4:
    #         # Open a new tab
    #         self.driver.switch_to.new_window(
    #             "tab"
    #         )

    #         # Open website
    #         self.driver.get(url)

    #         # Wait for page
    #         try:

    #             WebDriverWait(
    #                 self.driver,
    #                 15
    #             ).until(
    #                 EC.presence_of_element_located(
    #                     (By.TAG_NAME, "body")
    #                 )
    #             )

    #         except TimeoutException:

    #             self._log(
    #                 f"Page body timeout: {url}"
    #             )

    #         # Small random delay
    #         self.random_sleep()

    #         return {
    #             "window_handle": self.driver.current_window_handle,
    #             "original_window": original_window
    #         }

    #     except Exception as e:

    #         self._log(
    #             f"Error opening {url}: {e}"
    #         )

    #         # Try to close current tab
    #         try:
    #             if len(self.driver.window_handles) > 1:
    #                 self.driver.close()
    #                 self.driver.switch_to.window(
    #                     original_window
    #                 )
    #         except Exception:
    #             pass

    #         return None

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

        self._log(
            f"Processing: {url}"
        )

        result = {
            "name": name,
            "website": url,
            "contact_page": "",
            "emails": [],
            "phones": website.get("phones", []),
            "proposal": "",
            "form_prefilled": False,
            "email_sent": False,
            "whatsapp_sent": False,
            "status": "processing"
        }

        if url and self.is_ignored_url(url):
            self._log(f"Skipping configured ignored URL: {url}")
            result["status"] = "ignored_url"
            return result

        business_key = self.business_key(website)
        if self.was_previously_processed(business_key):
            self._log(f"Skipping previously processed business: {name or url}")
            result["status"] = "skipped_duplicate"
            return result

        if not url:
            self._log(f"No website listed for {name}; creating a website-service draft.")
            try:
                result["proposal"] = self.generate_website_proposal(website)
                self.run_fallback_channels(
                    result,
                    business_key,
                    reason="no website available"
                )
                self.update_result_status(result)
                self.save_outreach(business_key, result)
                self.append_draft(result)
            except Exception as exc:
                result["status"] = "draft_error"
                self._log(f"Draft generation error: {exc}")
            return result

        # Open website in new tab
        tab_info = self.open_website(
            website
        )

        if not tab_info:

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

            result["emails"] = emails

            result["phones"] = sorted(
                set(
                    phones
                    + whatsapp_numbers
                )
            )

            self._log(
                f"Emails found: {emails}"
            )

            self._log(
                f"Phones found: {phones}"
            )

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

            # -----------------------------------------
            # GENERATE PROPOSAL
            # -----------------------------------------

            try:

                self._log(
                    "Generating website proposal..."
                )

                proposal = self.generate_website_proposal(
                    website
                )

                if proposal:

                    self._log("Proposal generated:")
                    self._log(proposal)
                    result["proposal"] = proposal

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
                        try:
                            record_event(
                                self.db,
                                EVENT_FORM_PREFILLED,
                                business_key,
                                result,
                                details="Contact form prefilled for review",
                            )
                        except Exception as exc:
                            self._log(f"Progress event error: {exc}")
                        self._log("Review mode: form prefilled but not submitted.")

                    # WhatsApp and email are required outreach channels, not
                    # merely fallbacks for websites without a contact form.
                    # Attempt both after preparing the proposal regardless of
                    # whether a form was also filled successfully.
                    self.run_fallback_channels(
                        result,
                        business_key,
                        reason="proposal ready"
                    )

                else:

                    self._log(
                        "Could not generate proposal."
                    )

            except Exception as e:

                self._log(
                    f"Proposal generation error: {e}"
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
            self.append_draft(result)
            return result

        except Exception as e:

            self._log(
                f"Website processing error: {e}"
            )

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

    def process_all_websites(
        self,
        google_page,
        limit=20
    ):

        self._log(
            "PROCESSING GOOGLE RESULTS"
        )

        # -----------------------------------------
        # Get websites from Google
        # -----------------------------------------
        # self._log(google_page)
        # input("get_google_websites")
        websites = self.get_google_websites(
            google_page
        )

        if not websites:

            self._log(
                "No websites found from Google."
            )

            return []

        # Limit number during testing
        websites = websites[:limit]

        self._log(
            f"Processing {len(websites)} websites..."
        )

        results = []

        # -----------------------------------------
        # Process each website
        # -----------------------------------------

        for index, website in enumerate(
            websites,
            start=1
        ):

            url = website.get(
                "url",
                ""
            )

            self._log(
                f"[{index}/{len(websites)}] {url}"
            )

            try:

                result = self.process_website(
                    website
                )
                self._log(result)
                results.append(result)

            except Exception as e:

                self._log(
                    f"Error processing {url}: {e}"
                )

                # Still add a result
                results.append({
                    "name": website.get(
                        "name",
                        ""
                    ),
                    "website": url,
                    "contact_page": "",
                    "emails": [],
                    "phones": []
                })

        self._log(
            f"Finished processing "
            f"{len(results)} websites"
        )

        return results

    def resolve_google_website(self, google_url):

        original_window = None

        try:

            original_window = self.driver.current_window_handle

            self._log(
                f"Resolving Google website link..."
            )

            # Open the Google redirect in a new tab
            self.driver.switch_to.new_window("tab")

            self.driver.get(google_url)

            # Wait for navigation
            try:

                WebDriverWait(
                    self.driver,
                    15
                ).until(
                    lambda d: (
                        d.current_url.startswith("http://")
                        or d.current_url.startswith("https://")
                    )
                )

            except TimeoutException:

                self._log(
                    "Timeout while resolving Google website."
                )

            final_url = self.driver.current_url

            self._log(
                f"Resolved URL: {final_url}"
            )

            # Close temporary tab
            try:
                self.driver.close()
            except Exception:
                pass

            # Return to Google
            try:
                self.driver.switch_to.window(
                    original_window
                )
            except Exception:
                pass

            # Check whether we actually reached a real website
            if not final_url:
                return None

            if "google.com" in urlparse(
                final_url
            ).netloc.lower():

                self._log(
                    f"Still on Google, ignoring: {final_url}"
                )

                return None

            if "google.ae" in urlparse(
                final_url
            ).netloc.lower():

                return None

            return final_url

        except Exception as e:

            self._log(
                f"Error resolving Google website: {e}"
            )

            # Try to restore original tab
            try:

                if original_window:

                    if self.driver.current_window_handle != original_window:

                        try:
                            self.driver.close()
                        except Exception:
                            pass

                        self.driver.switch_to.window(
                            original_window
                        )

            except Exception:
                pass

            return None


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
                    text = responses.nth(count - 1).inner_text(timeout=5000).strip()
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
        return page.evaluate("navigator.clipboard.readText()")

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

                self._log("writing ai response")
                self._log(response)

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
                headless=False,
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

            self._log("writing ai response")
            self._log(response)

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



    def generate_website_proposal(self, website):
        """
        Generate a professional website-development proposal
        based on the business information.
        """

        company_name = website.get("name", "")
        website_url = website.get("url", "")
        business_context = self.search_query
        our_company = self.config.get("company_name", "our web development company")

        prompt = f"""
    You are helping a professional website development company
    write a short business introduction for a potential client.

    Business name:
    {company_name}

    Website:
    {website_url}

    Search/category context:
    {business_context}

    Sender company:
    {our_company}

    Our company provides:

    - Website Development
    - E-commerce / Online Stores
    - Website Redesign
    - Responsive Mobile-Friendly Websites
    - SEO & Digital Marketing
    - Logo Design
    - Business Email Setup
    - Accounting Software
    - POS Solutions
    - E-Invoicing Software
    - Website Maintenance & Support
    - Domain & Hosting Setup
    - Custom Business Software

    Write a professional and friendly proposal that can be used
    as a draft for a website contact form.

    IMPORTANT:

    - Do not pretend that we know the company's specific problems.
    - Do not make false claims about their current website.
    - Do not say that we noticed problems unless they are explicitly
    provided.
    - Keep it relatively short.
    - Sound human, professional and helpful.
    - Do not use excessive marketing language.
    - Do not use emojis.
    - Do not mention that AI wrote the message.
    - Invite them to contact us if they are interested.
    - Mention that we can discuss their requirements and provide
    suitable recommendations.
    - Do not include sender contact details such as contact name,
    email, phone, website, or a contact-us block. Those details are
    added separately only for channels where they are enabled.
    - Do not include a subject line unless specifically requested.

    Return ONLY the proposal text.
    """

        return self.ask_ai(
            prompt,
            domain=company_name,
            filename="proposal"
        ) 

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
        message = (
            result.get("proposal", "")
            or ""
        ).strip()

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

            if len(digits) >= 10:
                return digits

        return ""

    def run_fallback_channels(self, result, business_key, reason=""):
        self._log(
            f"Fallback outreach check started: {reason}"
        )

        whatsapp_sent = self.send_whatsapp_message(
            result,
            business_key
        )

        email_sent = self.send_email_message(
            result,
            business_key
        )

        return whatsapp_sent or email_sent

    def update_result_status(self, result):
        if result.get("email_sent") and result.get("whatsapp_sent"):
            result["status"] = "fallback_sent"
        elif result.get("email_sent"):
            result["status"] = "email_sent"
        elif result.get("whatsapp_sent"):
            result["status"] = "whatsapp_sent"
        else:
            result["status"] = "draft_ready"

    def send_whatsapp_message(self, result, business_key):
        if not self.get_bool_setting(
            "whatsapp",
            "enabled",
            default=True
        ):
            self._log("WhatsApp fallback disabled.")
            return False

        message = (
            self.channel_message(
                result,
                "whatsapp"
            )
            or ""
        ).strip()

        phone = self.primary_whatsapp_phone(
            result
        )

        if not phone:
            self._log("WhatsApp fallback skipped: no usable phone number.")
            return False

        if not message:
            self._log("WhatsApp fallback skipped: proposal message is empty.")
            return False

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

        if not auto_send and not open_for_review:
            self._log("WhatsApp fallback ready, but auto_send is off.")
            return False

        url = (
            f"https://web.whatsapp.com/send?"
            f"phone={phone}&text={quote_plus(message)}"
        )

        original_window = None
        whatsapp_window = None
        send_timeout = max(
            5,
            min(
                10,
                int(self.get_section_setting(
                    "whatsapp",
                    "send_timeout_seconds",
                    default=10
                ))
            )
        )

        try:
            original_window = self.driver.current_window_handle
            self.driver.switch_to.new_window("tab")
            whatsapp_window = self.driver.current_window_handle
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

            if not auto_send:
                self._log(
                    "WhatsApp auto_send is off; message left open for review."
                )
                return False

            send_button = self.find_whatsapp_send_button(
                timeout=send_timeout
            )

            if not send_button:
                self._log(
                    "WhatsApp send button not found. Log in to WhatsApp Web "
                    "or review the opened tab."
                )
                return False

            send_button.click()
            self.random_sleep()
            result["whatsapp_sent"] = True
            record_event(
                self.db,
                EVENT_WHATSAPP_SENT,
                business_key,
                result,
                details="WhatsApp message sent by fallback"
            )
            self._log("WhatsApp message sent.")
            return True

        except Exception as e:
            self._log(
                f"WhatsApp fallback error: {e}"
            )
            return False

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
            return False

        try:
            return WebDriverWait(
                self.driver,
                timeout
            ).until(first_clickable)
        except TimeoutException:
            return None


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

    def send_email_message(self, result, business_key):
        if not self.get_bool_setting(
            "email",
            "enabled",
            default=True
        ):
            self._log("Email fallback disabled.")
            return False

        auto_send = self.get_bool_setting(
            "email",
            "auto_send",
            default=False
        )

        recipients = self.email_recipients(
            result
        )

        if not recipients:
            self._log("Email fallback skipped: no email address found.")
            return False

        message = (
            self.channel_message(
                result,
                "email"
            )
            or ""
        ).strip()

        if not message:
            self._log("Email fallback skipped: proposal message is empty.")
            return False

        if not auto_send:
            self._log(
                "Email fallback ready, but auto_send is off."
            )
            return False

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
            default="Website development proposal"
        )

        if not smtp_host or not from_email:
            self._log(
                "Email fallback skipped: smtp_host and from_email are required."
            )
            return False

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
        email.set_content(
            message
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

                server.send_message(
                    email
                )

            result["email_sent"] = True
            record_event(
                self.db,
                EVENT_EMAIL_SENT,
                business_key,
                result,
                details=f"Email sent to {', '.join(recipients)}"
            )
            self._log(
                f"Email sent to {', '.join(recipients)}."
            )
            return True

        except Exception as e:
            self._log(
                f"Email fallback error: {e}"
            )
            return False


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

        row = self.db.execute(
            "SELECT status FROM outreach WHERE business_key = ?", (business_key,)
        ).fetchone()
        # A draft or a partial send is not complete. Retry it on the next run
        # so that both WhatsApp and email get a chance to be delivered.
        return bool(row and row[0] == "fallback_sent")

    def save_outreach(self, business_key, result):
        self.db.execute(
            '''INSERT INTO outreach (
                business_key, business_name, website, contact_page, emails,
                phones, proposal, form_prefilled, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(business_key) DO UPDATE SET
                business_name=excluded.business_name, website=excluded.website,
                contact_page=excluded.contact_page, emails=excluded.emails,
                phones=excluded.phones, proposal=excluded.proposal,
                form_prefilled=excluded.form_prefilled, status=excluded.status,
                updated_at=excluded.updated_at''',
            (
                business_key, result.get("name", ""), result.get("website", ""),
                result.get("contact_page", ""), json.dumps(result.get("emails", [])),
                json.dumps(result.get("phones", [])), result.get("proposal", ""),
                int(result.get("form_prefilled", False)), result.get("status", "draft_ready"),
                datetime.now().isoformat(timespec="seconds")
            )
        )
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

                    self._log(
                        "Message field filled."
                    )

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

        if filled_count == 0:

            self._log(
                "✗ Could not fill any form fields."
            )

            return False

        self._log(
            f"✓ Successfully filled "
            f"{filled_count} form fields."
        )

        return True

    



        
if __name__ == "__main__":
    print("[Marketing Bot] Launching Automation...")
    automation = Automation()
    print("[Marketing Bot] Session ended.")

