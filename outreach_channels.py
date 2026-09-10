"""Channel isolation, send history protection, and persisted outcomes."""

from datetime import datetime, timedelta
from progress_tracker import EVENT_EMAIL_SENT, EVENT_WHATSAPP_SENT
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException


class OutreachChannelsMixin:
    def whatsapp_outgoing_ids(self):
        return self.driver.execute_script("return Array.from(document.querySelectorAll('.message-out [data-id], .message-out[data-id], [data-id^=\"true_\"]')).map(e=>e.getAttribute('data-id'));") or []

    def wait_for_whatsapp_confirmation(self, previous_ids, timeout):
        try:
            return bool(WebDriverWait(self.driver, timeout).until(lambda d: d.execute_script('''
                const old = new Set(arguments[0]);
                return Array.from(document.querySelectorAll('[data-id^="true_"]')).some(e =>
                  !old.has(e.getAttribute('data-id')) &&
                  !!e.querySelector('[data-icon="msg-check"], [data-icon="msg-dblcheck"], [data-icon="msg-dblcheck-ack"]'));
            ''', previous_ids)))
        except TimeoutException:
            return False

    def channel_outcome(self, result, channel, status, reason=''):
        result.setdefault('channel_status', {})[channel] = {'status': status, 'reason': reason}
        self._log(f'{channel.title()}: {status}' + (f' — {reason}' if reason else ''))
        return False

    def recent_channel_events(self, business_key, event_type):
        rows = self.db.execute('SELECT recipient,created_at FROM outreach_events WHERE business_key=? AND event_type=?',
                               (business_key, event_type)).fetchall()
        threshold = datetime.now() - timedelta(days=max(1, int(self.config.get('reprocess_after_days', 40))))
        recent = []
        for recipient, timestamp in rows:
            try:
                if datetime.fromisoformat(timestamp) < threshold:
                    continue
            except (TypeError, ValueError):
                pass  # Keep undated history protected.
            recent.append(recipient or '')
        if not rows:
            row = self.db.execute('SELECT status,updated_at FROM outreach WHERE business_key=?', (business_key,)).fetchone()
            legacy = {'email_sent','fallback_sent'} if event_type == EVENT_EMAIL_SENT else {'whatsapp_sent','fallback_sent'}
            if row and row[0] in legacy:
                try:
                    if datetime.fromisoformat(row[1]) < threshold:
                        return recent
                except (TypeError, ValueError):
                    pass
                recent.append('')
        return recent

    def run_fallback_channels(self, result, business_key, reason=''):
        self._log(f'Checking outreach channels: {reason}')
        sent = False
        for channel in ('whatsapp', 'email'):
            try:
                sent = getattr(self, f'send_{channel}_message')(result, business_key) or sent
            except Exception as exc:
                self.channel_outcome(result, channel, 'failed', str(exc))
            # Save after each channel; the next one may fail or the process may stop.
            self.save_outreach(business_key, result)
        return sent

    def send_whatsapp_message(self, result, business_key):
        if self.recent_channel_events(business_key, EVENT_WHATSAPP_SENT):
            result['whatsapp_sent'] = True
            return self.channel_outcome(result, 'whatsapp', 'already_sent', 'Within configured contact cooldown')
        if self.recent_channel_events(business_key, 'whatsapp_uncertain'):
            return self.channel_outcome(result, 'whatsapp', 'uncertain', 'Previous click was not confirmed; review WhatsApp before retrying')
        numbers = list(dict.fromkeys(result.get('whatsapp_phones', []) + result.get('phones', [])))
        candidates = []
        for number in numbers:
            normalized = self.primary_whatsapp_phone({'phones': [number]})
            if normalized and normalized not in candidates:
                candidates.append(normalized)
        if not candidates:
            return self.channel_outcome(result, 'whatsapp', 'no_phone', 'No usable number; check discovered contacts and ignored prefixes')
        original_phones = result.get('phones', [])
        try:
            for phone in candidates:
                result['phones'] = [phone]
                result['_whatsapp_send_clicked'] = False
                if self._send_whatsapp_to_phone(result, business_key):
                    self.channel_outcome(result, 'whatsapp', 'sent')
                    return True
                status = result.get('channel_status', {}).get('whatsapp', {}).get('status')
                if result.get('_whatsapp_send_clicked') or status in {'disabled','review','no_message','configuration_missing'}:
                    break
        finally:
            result['phones'] = original_phones
            result.pop('_whatsapp_send_clicked', None)
        return False

    def send_email_message(self, result, business_key):
        recent = self.recent_channel_events(business_key, EVENT_EMAIL_SENT)
        recipients = self.email_recipients(result)
        if '' in recent or (recipients and all(email.lower() in recent for email in recipients)):
            result['email_sent'] = True
            return self.channel_outcome(result, 'email', 'already_sent', 'Within configured contact cooldown')
        # Retry only recipients that SMTP has not already accepted.
        result['_email_recipients'] = [email for email in recipients if email.lower() not in recent]
        try:
            return self._send_email_message(result, business_key)
        finally:
            result.pop('_email_recipients', None)
