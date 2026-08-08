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

            google_url = (
                "https://www.google.com/search"
                "?q=business+near+me"
                "&hl=en"
            )

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
                input("first website ")
                # results.append(
                #     result
                # )

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
                    model="gpt-5.5",
                    input=content,
                    text={
                        "format": {
                            "type": "json_object"
                        }
                    }
                )

                response = response.output_text

                self.log("writing ai response")
                self.log(response)

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

                try:
                    analysis = json.loads(response)

                except json.JSONDecodeError as e:
                    print("JSON parsing failed")
                    print("Error:", e)
                    print("Raw response:")
                    print(repr(response))
                    raise

                # ----------------------------------------------------
                # Save JSON using your existing function
                # ----------------------------------------------------

                self.save_file(
                    analysis,
                    f"{domain}_{filename}"
                )

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

            browser = p.chromium.launch(
                headless=False
            )

            context = browser.new_context(
                permissions=[
                    "clipboard-read",
                    "clipboard-write"
                ]
            )

            page = context.new_page()

            page.goto(
                "https://chat.openai.com"
            )

            page.wait_for_timeout(5000)

            editor = page.locator(
                "[contenteditable='true']"
            )

            editor.wait_for(
                state="visible",
                timeout=30000
            )

            # editor.fill(content)
            editor.click()

            page.keyboard.insert_text(content)

            # time.sleep(3)
            page.wait_for_timeout(5000)

            page.keyboard.press("Enter")

            page.wait_for_timeout(10000)

            copy_button = page.locator(
                'button[aria-label="Copy response"]'
            ).last

            copy_button.wait_for(
                state="visible",
                timeout=30000
            )

            copy_button.scroll_into_view_if_needed()

            copy_button.click()

            page.wait_for_timeout(1000)

            response = page.evaluate(
                "navigator.clipboard.readText()"
            )

            self.log("writing ai response")
            self.log(response)

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

            try:
                analysis = json.loads(response)

            except json.JSONDecodeError as e:

                print("JSON parsing failed")
                print("Error:", e)
                print("Raw response:")
                print(repr(response))

                raise

            self.save_file(
                analysis,
                f"{domain}_{filename}"
            )

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

            browser.close()

            return response



    def generate_website_proposal(self, website):
        """
        Generate a professional website-development proposal
        based on the business information.
        """

        company_name = website.get("name", "")
        website_url = website.get("url", "")

        prompt = f"""
    You are helping a professional website development company
    write a short business introduction for a potential client.

    Business name:
    {company_name}

    Website:
    {website_url}

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
    - Do not include a fake phone number, email address or website.
    - Do not include a subject line unless specifically requested.

    Return ONLY the proposal text.
    """

        return self.ask_ai(
            prompt,
            domain=company_name,
            filename="proposal"
        )





        
if __name__ == "__main__":
    print("[Marketing Bot] Launching Automation...")
    automation = Automation()
    print("[Marketing Bot] Session ended.")

