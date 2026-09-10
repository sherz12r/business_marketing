"""Offline regression QA. No browser launch, AI request, or real message sending."""
import json
import os
import sqlite3
import shutil
import uuid
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from main import Automation
from progress_tracker import ensure_database, outreach_stats, record_event
import web_app


class OutreachTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parent
        work = test_root / ('qa-' + uuid.uuid4().hex)
        work.mkdir()
        assert work.resolve().parent == test_root
        self.addCleanup(lambda: shutil.rmtree(work))
        self.bot = Automation.__new__(Automation)
        self.bot.config = {'limit': 10, 'google_max_pages': 8, 'reprocess_after_days': 40,
                           'email': {'enabled': True, 'auto_send': True, 'smtp_host': 'smtp.test',
                                     'from_email': 'sender@example.test', 'smtp_username': '',
                                     'smtp_password': '', 'include_contact_details': False},
                           'whatsapp': {'enabled': True, 'auto_send': True, 'include_contact_details': False},
                           'website_forms': {'include_contact_details': True}}
        self.bot.data_dir = work
        self.bot.db = sqlite3.connect(self.bot.data_dir / 'outreach.sqlite3')
        self.bot.db.row_factory = sqlite3.Row
        self.addCleanup(self.bot.db.close)
        ensure_database(self.bot.db)
        self.bot.run_id = self.bot.db.execute("INSERT INTO outreach_runs(mode,target,status) VALUES('full',10,'running')").lastrowid
        self.bot.db.commit()
        self.bot.driver = MagicMock()
        self.bot.driver.current_url = 'https://www.google.com/search?q=salons'
        self.bot.driver.current_window_handle = 'google'
        self.bot.driver.window_handles = ['google', 'site']
        self.bot._log = MagicMock()
        self.bot.random_sleep = MagicMock()
        self.bot.whatsapp_login_wait_used = True
        self.bot.search_query = 'salons'
        self.bot.headless = True
        self.bot.limit = 10
        self.addCleanup(patch.stopall)
        patch('socket.create_connection', side_effect=AssertionError('Real networking is forbidden in QA')).start()

    def lead(self, name='Fixture Salon', **kwargs):
        return dict(name=name, website='https://fixture.test', proposal='Hello from our company.',
                    emails=['hello@fixture.test'], phones=['0501112222'], run_id=self.bot.run_id, **kwargs)

    def seed(self, name, status='draft_ready'):
        site = {'name': name, 'url': f'https://{name}.test'}
        key = self.bot.business_key(site)
        self.bot.save_outreach(key, dict(name=name, website=site['url'], proposal='Hello', status=status))
        return site, key

    def mock_pages(self, pages):
        self.bot.google_is_blocked = MagicMock(return_value=False)
        self.bot.get_google_websites = MagicMock(side_effect=pages)
        self.bot.go_to_next_google_page = MagicMock(side_effect=[True]*(len(pages)-1)+[False])
        self.bot.enrich_google_business = MagicMock(side_effect=lambda s:s)

    def test_more_than_three_with_empty_middle_page_and_prior_contacts(self):
        old, key = self.seed('old', 'whatsapp_sent')
        record_event(self.bot.db, 'whatsapp_sent', key)
        fresh = [{'name': f'n{i}', 'url': f'https://n{i}.test'} for i in range(7)]
        self.mock_pages([[old]+fresh[:3], [], fresh[3:]])
        def process(site):
            if site['name'] == 'old':
                return {'status':'skipped_duplicate'}
            result=self.lead(site['name']);result['status']='draft_ready'
            self.bot.save_outreach(self.bot.business_key(site), result)
            return result
        self.bot.process_website = MagicMock(side_effect=process)
        self.bot.process_all_websites(self.bot.driver, limit=7)
        totals, run = outreach_stats(self.bot.db)
        self.assertEqual((run['new'], run['processed'], run['skipped'], run['already_contacted']), (7,7,1,1))
        self.assertEqual(run['pages'],3)
        self.assertEqual(self.bot.go_to_next_google_page.call_count,2)

    def test_repeated_page_stops_without_reprocessing(self):
        site={'name':'a','url':'https://a.test'}
        self.mock_pages([[site],[site]])
        self.bot.process_website=MagicMock(return_value={'status':'draft_ready'})
        self.bot.process_all_websites(self.bot.driver)
        self.bot.process_website.assert_called_once()
        self.assertIn('repeated', outreach_stats(self.bot.db)[1]['stop_reason'])

    def test_failure_is_saved_and_next_business_runs(self):
        self.mock_pages([[{'name':name,'url':f'https://{name}.test'} for name in ['bad','good']]])
        self.bot.process_website=MagicMock(side_effect=[RuntimeError('broken site'),{'status':'draft_ready'}])
        self.bot.process_all_websites(self.bot.driver)
        self.assertEqual(outreach_stats(self.bot.db)[1]['failed'],1)
        self.assertEqual(outreach_stats(self.bot.db)[1]['processed'],2)
        self.assertEqual(self.bot.db.execute("SELECT last_error FROM outreach WHERE business_name='bad'").fetchone()[0],'broken site')

    def test_discovered_but_not_processed_is_not_skipped_next_time(self):
        site={'name':'queued','url':'https://queued.test'}
        key=self.bot.business_key(site)
        self.bot.register_candidate(key,site)
        self.assertFalse(self.bot.was_previously_processed(key))

    def test_captcha_stops_without_sending(self):
        self.bot.google_is_blocked=MagicMock(return_value=True)
        self.bot.process_website=MagicMock()
        self.bot.process_all_websites(self.bot.driver)
        self.bot.process_website.assert_not_called()
        self.assertEqual(outreach_stats(self.bot.db)[1]['status'],'blocked')

    def test_google_redirect_urls_are_unwrapped(self):
        self.assertEqual(self.bot.unwrap_google_url('/url?q=https%3A%2F%2Fsalon.test%2Fcontact&sa=U'), 'https://salon.test/contact')
        self.assertEqual(self.bot.unwrap_google_url('/goto?url=https%3A%2F%2Fsalon.test'), 'https://salon.test')
        self.assertEqual(self.bot.unwrap_google_url('https://www.google.com/maps'), '')

    def test_snapshot_merges_duplicate_domain_contacts(self):
        self.bot.driver.execute_script.return_value=[
            {'name':'Salon','url':'/url?q=https%3A%2F%2Fsalon.test','phones':['0501112222']},
            {'name':'Salon Home','url':'https://www.salon.test/','phones':['0503334444']},
            {'name':'No Site','url':'','phones':['0505556666']},
        ]
        found=self.bot.get_google_websites(self.bot.driver)
        self.assertEqual(len(found),2)
        self.assertEqual(found[0]['phones'],['0501112222','0503334444'])

    def test_pagination_supports_same_url_result_changes(self):
        button=MagicMock();button.get_attribute.side_effect=lambda key: None
        self.bot.driver.find_elements.return_value=[button]
        self.bot.google_page_signature=MagicMock(side_effect=['first','second'])
        self.bot.wait_for_google_results=MagicMock()
        self.assertTrue(self.bot.go_to_next_google_page())
        button.click.assert_called_once()

    def test_channels_are_independent(self):
        result=self.lead()
        self.bot.send_whatsapp_message=MagicMock(side_effect=RuntimeError('WA broke'))
        self.bot.send_email_message=MagicMock(return_value=True)
        self.assertTrue(self.bot.run_fallback_channels(result,'key'))
        self.bot.send_email_message.assert_called_once()
        saved=json.loads(self.bot.db.execute('SELECT channel_status FROM outreach').fetchone()[0])
        self.assertEqual(saved['whatsapp']['status'],'failed')

    def test_no_website_still_attempts_both_channels(self):
        self.bot.generate_website_proposal=MagicMock(return_value='Hello')
        self.bot.send_whatsapp_message=MagicMock(return_value=True)
        self.bot.send_email_message=MagicMock(return_value=False)
        self.bot.process_website({'name':'Phone only','phones':['0501112222']})
        self.bot.send_whatsapp_message.assert_called_once()
        self.bot.send_email_message.assert_called_once()

    def prepare_website(self):
        self.bot.open_website=MagicMock(return_value={'window_handle':'site','original_window':'google'})
        self.bot.find_emails=MagicMock(return_value=['hello@fixture.test'])
        self.bot.find_phone_numbers=MagicMock(return_value=['0503334444'])
        self.bot.find_whatsapp_numbers=MagicMock(return_value=['0505556666'])
        self.bot.find_contact_page=MagicMock(return_value=None)
        self.bot.generate_website_proposal=MagicMock(return_value='Hello')
        self.bot.run_fallback_channels=MagicMock()

    def test_form_exception_does_not_block_outreach_and_google_phone_is_retained(self):
        self.prepare_website()
        self.bot.fill_contact_form=MagicMock(side_effect=RuntimeError('Form broke'))
        result=self.bot.process_website({'name':'Salon','url':'https://fixture.test','phones':['0501112222']})
        self.bot.run_fallback_channels.assert_called_once()
        self.assertEqual(set(result['phones']),{'0501112222','0503334444','0505556666'})

    def test_filled_form_still_runs_outreach(self):
        self.prepare_website();self.bot.fill_contact_form=MagicMock(return_value=True)
        result=self.bot.process_website({'name':'Salon','url':'https://fixture.test'})
        self.assertTrue(result['form_prefilled'])
        self.bot.run_fallback_channels.assert_called_once()
        self.assertEqual(outreach_stats(self.bot.db)[0]['forms'],1)

    def test_failed_website_uses_google_phone(self):
        self.bot.open_website=MagicMock(return_value=None)
        self.bot.generate_website_proposal=MagicMock(return_value='Hello')
        self.bot.run_fallback_channels=MagicMock()
        result=self.bot.process_website({'name':'Unavailable','url':'https://fixture.test','phones':['0501112222']})
        self.bot.run_fallback_channels.assert_called_once()
        self.assertEqual(result['status'],'website_error')

    def test_form_requires_message_field(self):
        self.bot.find_contact_form=MagicMock(return_value=MagicMock())
        self.bot.find_form_field=MagicMock(side_effect=[MagicMock(),MagicMock(),None,None,None])
        self.bot.fill_field_value=MagicMock(return_value=True)
        self.assertFalse(self.bot.fill_contact_form('Sender','sender@example.test','','Hello'))

    def test_whatsapp_tries_second_number_without_losing_contacts(self):
        result=self.lead();result['phones']=['0501112222','0503334444']
        self.bot._send_whatsapp_to_phone=MagicMock(side_effect=[False,True])
        self.assertTrue(self.bot.send_whatsapp_message(result,'key'))
        self.assertEqual(self.bot._send_whatsapp_to_phone.call_count,2)
        self.assertEqual(result['phones'],['0501112222','0503334444'])

    def test_whatsapp_cooldown_protects_against_interrupted_save(self):
        record_event(self.bot.db,'whatsapp_sent','key',recipient='971501112222')
        self.bot._send_whatsapp_to_phone=MagicMock()
        result=self.lead()
        self.assertFalse(self.bot.send_whatsapp_message(result,'key'))
        self.bot._send_whatsapp_to_phone.assert_not_called()
        self.assertEqual(result['channel_status']['whatsapp']['status'],'already_sent')

    def test_whatsapp_click_without_confirmation_is_not_counted_or_retried(self):
        result=self.lead()
        self.bot.find_whatsapp_send_button=MagicMock(return_value=MagicMock())
        self.bot.whatsapp_outgoing_ids=MagicMock(return_value=['old'])
        self.bot.wait_for_whatsapp_confirmation=MagicMock(return_value=False)
        self.assertFalse(self.bot.send_whatsapp_message(result,'key'))
        self.assertEqual(outreach_stats(self.bot.db)[0]['whatsapp'],0)
        self.bot.find_whatsapp_send_button.reset_mock()
        self.assertFalse(self.bot.send_whatsapp_message(result,'key'))
        self.bot.find_whatsapp_send_button.assert_not_called()

    def test_confirmed_whatsapp_records_one_send(self):
        self.bot.find_whatsapp_send_button=MagicMock(return_value=MagicMock())
        self.bot.whatsapp_outgoing_ids=MagicMock(return_value=[])
        self.bot.wait_for_whatsapp_confirmation=MagicMock(return_value=True)
        self.assertTrue(self.bot.send_whatsapp_message(self.lead(),'key'))
        self.assertEqual(outreach_stats(self.bot.db)[1]['whatsapp'],1)

    def smtp(self, refused=None):
        smtp=patch('main.smtplib.SMTP').start()
        server=smtp.return_value.__enter__.return_value
        # The implementation uses `with server`, retaining the original object.
        smtp.return_value.send_message.return_value=refused or {}
        return smtp

    def test_email_counts_accepted_recipients_and_retries_only_refused(self):
        self.bot.config['email']['send_to_all_found']=True
        result=self.lead();result['emails']=['a@fixture.test','b@fixture.test']
        smtp=self.smtp({'b@fixture.test':(550,b'Rejected')})
        self.assertTrue(self.bot.send_email_message(result,'key'))
        self.assertEqual(outreach_stats(self.bot.db)[0]['emails'],1)
        smtp.return_value.send_message.return_value={}
        self.assertTrue(self.bot.send_email_message(result,'key'))
        self.assertEqual(smtp.return_value.send_message.call_args.args[0]['To'],'b@fixture.test')
        self.assertEqual(outreach_stats(self.bot.db)[0]['emails'],2)

    def test_unconfigured_email_does_not_send(self):
        with patch.dict(os.environ,{},clear=True):
            self.bot.config['email']['smtp_host']=''
            smtp=self.smtp()
            result=self.lead()
            self.assertFalse(self.bot.send_email_message(result,'key'))
            smtp.assert_not_called()
            self.assertEqual(result['channel_status']['email']['status'],'configuration_missing')

    def test_disabled_and_review_email_do_not_send(self):
        smtp=self.smtp()
        for setting, status in [('enabled','disabled'),('auto_send','review')]:
            self.bot.config['email'][setting]=False
            result=self.lead()
            self.assertFalse(self.bot.send_email_message(result,'key'))
            self.assertEqual(result['channel_status']['email']['status'],status)
            self.bot.config['email'][setting]=True
        smtp.assert_not_called()

    def test_legacy_stats_add_missing_events_per_business_and_do_not_count_prefill_as_contact(self):
        self.seed('legacy','whatsapp_sent'); _, key=self.seed('modern')
        record_event(self.bot.db,'whatsapp_sent',key)
        record_event(self.bot.db,'whatsapp_sent',key)
        self.seed('prefilled')
        self.bot.db.execute("UPDATE outreach SET form_prefilled=1 WHERE business_name='prefilled'")
        totals,_=outreach_stats(self.bot.db)
        self.assertEqual((totals['whatsapp'],totals['contacted'],totals['pending']),(3,2,1))

    def test_dashboard_totals_not_limited_to_recent_250(self):
        for i in range(260):
            self.seed(str(i))
        with patch('web_app.data_dir', return_value=self.bot.data_dir), patch('web_app.job_status',return_value={}), patch('web_app.authenticated',return_value=True):
            response=web_app.app.test_client().get('/api/dashboard')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['stats']['leads'],260)
        self.assertEqual(len(response.json['leads']),250)
        self.assertIn('no-store',response.headers['Cache-Control'])

    def test_pending_email_works_after_schema_migration(self):
        self.seed('pending')
        self.bot.db.execute("UPDATE outreach SET emails=?",(json.dumps(['hello@fixture.test']),))
        self.bot.db.commit()
        self.smtp()
        self.bot.process_pending_channel('email')
        self.assertEqual(outreach_stats(self.bot.db)[0]['emails'],1)

    def test_constructor_uses_app_directory_and_pending_mode_needs_no_browser(self):
        config={**self.bot.config,'data_dir':str(self.bot.data_dir)}
        with patch.object(Automation,'read_json',return_value=config) as read, \
             patch.object(Automation,'process_pending_channel'), patch.object(Automation,'_log'), \
             patch.object(Automation,'get_driver') as launch:
            Automation(mode='pending-email')
        self.assertTrue(Path(read.call_args.args[0]).is_absolute())
        launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
