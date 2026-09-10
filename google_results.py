"""Google discovery: snapshot results before opening tabs; paginate observed controls."""

from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException


SNAPSHOT_SCRIPT = r"""
const visible = e => !!(e.getClientRects().length);
const links = root => Array.from(root.querySelectorAll('a[href]'));
const website = a => /website/i.test((a.innerText || '')+' '+(a.getAttribute('aria-label') || '')+' '+(a.dataset.itemId || '')) || a.matches('a[data-item-id="authority"]');
const cards = Array.from(document.querySelectorAll('div.w7Dbne, div.Nv2PK, div.VkpGBb, [data-cid]'))
  .filter(visible).filter((e,i,all) => !all.some(other => other !== e && e.contains(other)));
const results = cards.map(card => {
  const heading = card.querySelector('.dbg0pd .OSrXXb, .qBF1Pd, .dbg0pd, [role="heading"], h3');
  const detail = card.querySelector('a.hfpxzc, a[href*="/maps/place/"], a[href*="ludocid="], a[href*="/localservices/profile"]');
  const site = links(card).find(website);
  return {name: heading ? heading.innerText.trim() : (detail?.getAttribute('aria-label') || ''),
    url: site?.href || '', text: card.innerText, detail_url: detail?.href || '',
    phones: links(card).filter(a=>a.href.startsWith('tel:')).map(a=>a.href.slice(4))};
});
// Organic results still matter when a three-card local pack is present.
for (const a of links(document)) {
  if (!visible(a) || cards.some(c=>c.contains(a))) continue;
  const h = a.querySelector('h3');
  if (h || website(a)) results.push({name:h?.innerText.trim() || '',url:a.href,text:'',phones:[]});
}
return results;
"""


class GoogleResultsMixin:
    def google_is_blocked(self):
        url = self.driver.current_url
        return '/sorry/' in url or bool(self.driver.find_elements(
            By.CSS_SELECTOR, '#captcha-form, iframe[src*="recaptcha"], form[action*="consent"]'))

    def wait_for_google_results(self):
        try:
            WebDriverWait(self.driver, 20).until(lambda d: self.google_is_blocked() or d.find_elements(
                By.CSS_SELECTOR, 'div.w7Dbne, div.Nv2PK, div.VkpGBb, #search h3, #rso h3, #pnnext, [role="feed"]'))
        except TimeoutException:
            self._log('Google result readiness timed out; checking the page and its pagination controls.')

    def search_business(self):
        self._log(f'Searching Google for: {self.search_query}')
        self.driver.get('https://www.google.com/search?' + urlencode({'q': self.search_query, 'hl': 'en'}))
        self.wait_for_google_results()
        if self.limit > 3 and not self.google_is_blocked():
            expanded = False
            for element in self.driver.find_elements(By.XPATH,
                    "//a[contains(@href,'tbm=lcl') or contains(@href,'udm=1') or contains(.,'More places') or contains(.,'More businesses')] | //*[@role='button'][contains(.,'More places') or contains(.,'More businesses')]"):
                if element.is_displayed():
                    element.click()
                    self.wait_for_google_results()
                    expanded = True
                    break
            if not expanded:
                # Enter the expanded local list explicitly when the compact pack has no More link.
                self.driver.get('https://www.google.com/search?' + urlencode({'q': self.search_query, 'tbm': 'lcl', 'hl': 'en'}))
                self.wait_for_google_results()
            self._log('Reading expanded Google business results.')
        return self.driver

    def unwrap_google_url(self, value):
        value = urljoin(self.driver.current_url, value or '')
        for _ in range(4):
            parsed = urlparse(value)
            host = (parsed.hostname or '').lower()
            if not (host == 'google.com' or host.startswith('www.google.') or host.startswith('maps.google.')):
                return value if parsed.scheme in {'http', 'https'} else ''
            params = parse_qs(parsed.query)
            target = next((params[key][0] for key in ('url', 'q', 'adurl') if params.get(key) and params[key][0].startswith(('https://', 'http://'))), '')
            if target:
                value = target
            elif parsed.path == '/goto':
                return self.resolve_google_website(value) or ''
            else:
                return ''
        return ''

    def get_google_websites(self, page):
        # Copy strings atomically so redirect resolution cannot stale Selenium elements.
        snapshot = page.execute_script(SNAPSHOT_SCRIPT) or []
        found = {}
        for item in snapshot:
            url = self.unwrap_google_url(item.get('url', '')) if item.get('url') else ''
            if url and self.is_ignored_url(url):
                continue
            name = (item.get('name') or '').strip()
            if not url and not name:
                continue
            candidate = dict(name=name, url=url, detail_url=item.get('detail_url', ''),
                             phones=list(dict.fromkeys(item.get('phones', []) + self.extract_phone_numbers(item.get('text', '')))))
            key = self.business_key(candidate)
            if key in found:
                found[key]['phones'] = list(dict.fromkeys(found[key]['phones'] + candidate['phones']))
            else:
                found[key] = candidate
        return list(found.values())

    def enrich_google_business(self, website):
        """Read the selected business listing when its card hides website/phone details."""
        detail = website.get('detail_url')
        if not detail or (website.get('url') and website.get('phones')):
            return website
        original = self.driver.current_window_handle
        detail_window = None
        try:
            self.driver.switch_to.new_window('tab')
            detail_window = self.driver.current_window_handle
            self.driver.get(detail)
            WebDriverWait(self.driver, 15).until(lambda d: d.find_elements(By.CSS_SELECTOR,
                '[data-item-id="authority"], [data-item-id^="phone:"], a[href^="tel:"], h1'))
            info = self.driver.execute_script(r"""
                const root=document.querySelector('[role="main"]') || document.body;
                const site=root.querySelector('a[data-item-id="authority"], a[aria-label*="Website"], a[aria-label*="website"]');
                const phones=Array.from(root.querySelectorAll('[data-item-id^="phone:"], a[href^="tel:"]'))
                  .map(e=>e.getAttribute('href')?.replace('tel:','') || e.getAttribute('data-item-id').replace(/^phone:tel:/,''));
                return {url:site?.href || '', phones};
            """) or {}
            if info.get('url'):
                website['url'] = self.unwrap_google_url(info['url']) or website.get('url', '')
            website['phones'] = list(dict.fromkeys(website.get('phones', []) + info.get('phones', [])))
        except Exception as exc:
            self._log(f'Could not expand business details: {exc}')
        finally:
            if detail_window and detail_window in self.driver.window_handles:
                self.driver.switch_to.window(detail_window)
                self.driver.close()
            self.driver.switch_to.window(original)
        return website

    def google_page_signature(self):
        return self.driver.execute_script("return Array.from(document.querySelectorAll('div.w7Dbne, div.Nv2PK, div.VkpGBb, #search h3, #rso h3')).map(e=>e.innerText).join('|');") or ''

    def go_to_next_google_page(self):
        current_url = self.driver.current_url
        signature = self.google_page_signature()
        selectors = [(By.CSS_SELECTOR, '#pnnext, a[rel="next"], [aria-label="Next page"], [aria-label="Next"]'),
                     (By.XPATH, "//a[.//span[normalize-space()='Next']] | //button[normalize-space()='Next']")]
        for by, selector in selectors:
            for candidate in self.driver.find_elements(by, selector):
                if not candidate.is_displayed() or not candidate.is_enabled() or candidate.get_attribute('aria-disabled') == 'true':
                    continue
                href = candidate.get_attribute('href')
                if href:
                    self.driver.get(urljoin(current_url, href))
                else:
                    candidate.click()
                try:
                    # Local pagination often updates the list without changing the URL.
                    WebDriverWait(self.driver, 20).until(lambda d: d.current_url != current_url or self.google_page_signature() != signature)
                    self.wait_for_google_results()
                    return True
                except TimeoutException:
                    self._log('Google Next did not change the results.')
                    return False
        # Maps lists load the next batch by scrolling their feed.
        feeds = self.driver.find_elements(By.CSS_SELECTOR, '[role="feed"]')
        if feeds:
            self.driver.execute_script('arguments[0].scrollTop=arguments[0].scrollHeight;', feeds[0])
            try:
                WebDriverWait(self.driver, 10).until(lambda d: self.google_page_signature() != signature)
                return True
            except TimeoutException:
                pass
        self._log('No further Google results are available.')
        return False
