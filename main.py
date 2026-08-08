from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from datetime import datetime, date, timedelta
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc
from collections import Counter
from tkinter import messagebox
from email.mime import text
from random import uniform
from time import sleep
import os, json, sys
import tkinter as tk
import traceback
import requests
import sys
import re


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
        self.wait = WebDriverWait(self.driver, 30)

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


    def start_automation(self):
        self._log("Automation run started.")

        self.search_business()
        
        self._close_browser_safely()


    def search_business(self):
        self._log("Searching business...")
        self.random_sleep()
        # 1. Capture main window BEFORE navigation
        try:
            self.driver.get("https://www.google.com/search?q=business+near+me&sca_esv=96d7376529677af8&sxsrf=APpeQntaiUKW_-OjB3WCqp1fKjKx1gfBjw%3A1786182427405&source=hp&ei=G_t2avuSFrWQ-d8Py8WVyQc&iflsig=ABILxe8AAAAAancJKwWty64InQtJYOKfmWpc4YfZtnNB&udm=1&oq=business+&gs_lp=Egdnd3Mtd2l6IglidXNpbmVzcyAqAggAMgcQIxjwBRgnMgoQABiABBiKBRhDMgoQABiABBiKBRhDMgoQABiABBiKBRhDMg0QABiABBiKBRhDGLEDMg0QABiABBiKBRhDGLEDMg0QLhiABBiKBRhDGLEDMgoQABiABBiKBRhDMgoQABiABBiKBRhDMgoQABiABBiKBRhDSPMeUKoKWOkUcAF4AJABAJgBkAKgAfgOqgEFMC40LjW4AQHIAQD4AQGYAgqgApsPqAIKwgIHECMY6gIYJ8ICChAjGPAFGOoCGCfCAg0QIxiiBxieBhjqAhgnwgIEECMYJ8ICFhAuGEMYgwEYxwEYsQMY0QMYgAQYigXCAgUQABiABMICCBAAGIAEGLEDwgILEAAYgAQYigUYsQPCAgUQLhiABMICDhAuGIAEGLEDGMcBGK8BwgIKEC4YgAQYigUYQ8ICExAuGIAEGIoFGEMYsQMYxwEY0QPCAhAQLhiABBiKBRhDGMcBGNEDwgILEAAYgAQYigUYkgPCAhAQABiABBiKBRhDGLEDGMkDmAMH8QVgll9H_YyVOJIHBTEuNC41oAeaU7IHBTAuNC41uAeTD8IHBTAuOS4xyAcYgAgB&sclient=gws-wiz")
            self._log("Login successfully.")


        except Exception as e:
            self._log(f"could not login Error: {e}")



if __name__ == "__main__":
    print("[Marketing Bot] Launching Automation...")
    automation = Automation()
    print("[Marketing Bot] Session ended.")

