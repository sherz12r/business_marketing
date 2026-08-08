from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from datetime import datetime, date, timedelta
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc
from tkinter import messagebox
from email.mime import text
from random import uniform
from time import sleep
import tkinter as tk
import sys
import os, json, sys
import asyncio
import csv
import re
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError






try:
    from cloakbrowser.download import ensure_binary
    from cloakbrowser.config import get_chromium_version, get_default_stealth_args

    _HAS_CLOAK = True
except ImportError:
    _HAS_CLOAK = False


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
        browser_mode = "headless (no window)" if self.headless else "visible"
        self._log(f"Opening Chrome browser — {browser_mode}...")
        try:
            self.driver = self.get_driver(headless=self.headless)
        except Exception as e:
            self._log(f"Error connecting Chromium: {e}")
            self.driver = self.get_driver_default(headless=self.headless)

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
                self._log("Browser Quited.")
                sys.exit(1)
        except Exception:
            pass
        self.driver = None


    
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
            limit=20
        )

        self._log(
            f"Automation completed. "
            f"Total websites processed: {len(results)}"
        )

        # Debug pause if you want
        # input("Press Enter to close browser...")

        self._close_browser_safely()



    def search_business(self):
        self._log("Searching business...")
        self.random_sleep()
        self.wait = WebDriverWait(self.driver, 30)
        # 1. Capture main window BEFORE navigation
        try:
            self.driver.get("https://www.google.com/search?q=business+near+me&sca_esv=32b8bdd6e2d39944&hl=en&udm=1&lsack=Vjl3auavCsLj7_UPgdyI2AE&sa=X&ved=2ahUKEwjmsoy1m5GWAxXC8bsIHQEuAhsQjGp6BAguEAA&biw=1904&bih=380&dpr=1")
            # self.driver.get("https://www.google.com/search?q=business+near+me&hl=en")
            self._log("Login successfully.")
            

        except Exception as e:
            self._log(f"could not login Error: {e}")


    # =========================================================
    # SEARCH BUSINESS ON GOOGLE
    # =========================================================

    def search_business(self):

        self._log("Searching business...")

        self.random_sleep()

        self.wait = WebDriverWait(
            self.driver,
            30
        )

        try:

            google_url = (
                "https://www.google.com/search?"
                "q=business+near+me"
            )

            self.driver.get(google_url)

            self._log(
                "Google search page opened successfully."
            )

            # Wait for Google results
            try:

                self.wait.until(
                    EC.presence_of_element_located(
                        (By.TAG_NAME, "body")
                    )
                )

            except TimeoutException:

                self._log(
                    "Google page loaded but body was not found."
                )

            return self.driver

        except Exception as e:

            self._log(
                f"Error opening Google: {e}"
            )

            return None


    # =========================================================
    # GOOGLE RESULTS
    # =========================================================

    def get_google_websites(self, page):

        self._log(
            "Finding website links from Google..."
        )

        if page is None:

            self._log(
                "Google page is None."
            )

            return []

        websites = []
        seen = set()

        try:

            # Selenium:
            # Find all <a href=""> elements
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

                    # Only HTTP / HTTPS
                    if not href.startswith(
                        ("http://", "https://")
                    ):
                        continue

                    parsed = urlparse(href)

                    domain = parsed.netloc.lower()

                    # Remove Google domains
                    if (
                        "google.com" in domain
                        or "google.ae" in domain
                        or "googleusercontent.com" in domain
                    ):
                        continue

                    # Remove Google tracking/ad URLs
                    if "/aclk" in href:
                        continue

                    # Remove Google Maps
                    if "google.com/maps" in href:
                        continue

                    # Remove duplicates
                    if href in seen:
                        continue

                    seen.add(href)

                    # Store as dictionary
                    # because process_website()
                    # expects website["url"]
                    websites.append({
                        "name": "",
                        "url": href
                    })

                except Exception as e:

                    self._log(
                        f"Error reading Google link: {e}"
                    )

            self._log(
                f"Found {len(websites)} website links."
            )

            return websites

        except Exception as e:

            self._log(
                f"Error finding Google websites: {e}"
            )

            return []


    # =========================================================
    # OPEN WEBSITE
    # =========================================================

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

        try:

            # Save current tab
            original_window = self.driver.current_window_handle

            # Selenium 4:
            # Open a new tab
            self.driver.switch_to.new_window(
                "tab"
            )

            # Open website
            self.driver.get(url)

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
                    f"Page body timeout: {url}"
                )

            # Small random delay
            self.random_sleep()

            return {
                "window_handle": self.driver.current_window_handle,
                "original_window": original_window
            }

        except Exception as e:

            self._log(
                f"Error opening {url}: {e}"
            )

            # Try to close current tab
            try:
                if len(self.driver.window_handles) > 1:
                    self.driver.close()
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

            emails = sorted(
                set(
                    email_regex.findall(
                        text
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

            numbers = phone_regex.findall(
                text
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

        self.write_log_header(
            f"Processing: {url}"
        )

        result = {
            "name": name,
            "website": url,
            "contact_page": "",
            "emails": [],
            "phones": []
        }

        # Open website in new tab
        tab_info = self.open_website(
            website
        )

        if not tab_info:

            return result

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

            result["emails"] = emails

            result["phones"] = phones

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
                if current_window in self.driver.window_handles:

                    self.driver.switch_to.window(
                        current_window
                    )

                    self.driver.close()

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

                results.append(
                    result
                )

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

if __name__ == "__main__":
    print("[Marketing Bot] Launching Automation...")
    automation = Automation()
    print("[Marketing Bot] Session ended.")

