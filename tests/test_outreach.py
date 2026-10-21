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

from campaign import load_location_catalog, seed_target_areas
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
                           'use_browser_ai': True,
                           'email': {'enabled': True, 'auto_send': True, 'smtp_host': 'smtp.test',
                                     'from_email': 'sender@example.test', 'smtp_username': '',
                                     'smtp_password': '', 'include_contact_details': False},
                           'whatsapp': {'enabled': True, 'auto_send': True, 'include_contact_details': False,
                                        'invalid_number_pause_seconds': 0},
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
        self.bot.whatsapp_window = None
        def available_whatsapp(result, _business_key):
            _numbers, _usable, candidates = self.bot.whatsapp_candidates(result)
            if not candidates:
                return ''
            result['_verified_whatsapp_phone'] = candidates[0]
            return candidates[0]
        self.bot.preflight_whatsapp = MagicMock(side_effect=available_whatsapp)
        self.bot.audit_current_website = MagicMock(return_value=[])
        self.bot.current_area = {}
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

    def test_opaque_google_website_redirect_is_deferred(self):
        self.bot.resolve_google_website=MagicMock()
        self.assertEqual(self.bot.unwrap_google_url('/goto?cid=123'), '')
        self.bot.resolve_google_website.assert_not_called()

    def test_google_redirect_self_closed_tab_restores_results_window(self):
        class SelfClosingDriver:
            def __init__(self):
                self.handles=['google'];self.active='google';self.switch_to=self.Switch(self)
            class Switch:
                def __init__(self,driver): self.driver=driver
                def new_window(self,_kind):
                    self.driver.handles.append('temporary');self.driver.active='temporary'
                def window(self,handle):
                    if handle not in self.driver.handles: raise RuntimeError('missing window')
                    self.driver.active=handle
            @property
            def current_window_handle(self):
                if self.active not in self.handles: raise RuntimeError('target window already closed')
                return self.active
            @property
            def window_handles(self): return self.handles[:]
            @property
            def current_url(self):
                if self.active not in self.handles: raise RuntimeError('target window already closed')
                return 'https://www.google.com/search?q=salon'
            def get(self,_url):
                self.handles.remove(self.active)
            def close(self):
                self.handles.remove(self.active)

        self.bot.driver=SelfClosingDriver()
        self.assertIsNone(self.bot.resolve_google_website('https://www.google.com/goto?cid=123'))
        self.assertEqual(self.bot.driver.current_window_handle,'google')

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

    def test_google_profile_phone_waits_for_website_audit_before_whatsapp(self):
        self.bot.generate_website_proposal=MagicMock(return_value='Hello')
        self.bot.send_whatsapp_message=MagicMock(return_value=True)
        self.bot.open_website=MagicMock(return_value=None)
        self.bot.process_website({'name':'Profile phone','url':'https://fixture.test','phones':['0501112222']})
        self.bot.send_whatsapp_message.assert_called_once()
        self.bot.open_website.assert_called_once()

    def test_no_website_profile_phone_gets_website_development_message(self):
        self.bot.ask_ai=MagicMock(return_value='Hello')
        self.bot.send_whatsapp_message=MagicMock(return_value=True)
        self.bot.process_website({'name':'Phone only','phones':['0501112222']})
        prompt=self.bot.ask_ai.call_args.args[0]
        self.assertIn('no website listed',prompt.lower())
        self.assertIn('creating a new professional, modern website',prompt.lower())

    def test_existing_website_prompt_uses_url_and_confirmed_audit_findings(self):
        self.bot.ask_ai=MagicMock(return_value='Hello')
        self.bot.generate_website_proposal({
            'name':'Has site',
            'url':'https://fixture.test',
            'audit_findings':['The homepage has no main H1 heading.'],
        })
        prompt=self.bot.ask_ai.call_args.args[0]
        self.assertIn('website checked: https://fixture.test',prompt.lower())
        self.assertIn('the homepage has no main h1 heading',prompt.lower())
        self.assertIn('briefly names two or three of the confirmed issues',prompt.lower())
        self.assertIn('do not replace the specific issues',prompt.lower())
        self.assertIn('do not provide a technical solution',prompt.lower())
        self.assertIn('start the first sentence with "we"',prompt.lower())
        self.assertIn('our team at [company name]',prompt.lower())

    def test_ai_draft_that_exposes_audit_details_is_replaced_with_general_summary(self):
        self.bot.ask_ai=MagicMock(return_value=(
            'Your homepage has no H1 tag and 44 images are missing alt text.'
        ))
        message=self.bot.generate_website_proposal({
            'name':'Has site',
            'url':'https://fixture.test',
            'audit_findings':[
                'The homepage has no main H1 heading.',
                '44 of 50 homepage images are missing descriptive alt text.',
            ],
        })
        self.assertIn('missing a clear main heading',message.lower())
        self.assertIn('images are missing accessibility descriptions',message.lower())
        self.assertNotIn('h1',message.lower())
        self.assertNotIn('alt text',message.lower())
        self.assertNotIn('44',message)

    def test_ai_draft_with_general_audit_language_is_kept(self):
        safe_message='We found opportunities to improve SEO and accessibility.'
        self.bot.ask_ai=MagicMock(return_value=safe_message)
        message=self.bot.generate_website_proposal({
            'name':'Has site',
            'url':'https://fixture.test',
            'audit_findings':['The homepage has no main H1 heading.'],
        })
        self.assertEqual(message,safe_message)

    def test_existing_travel_business_prompt_proposes_tailored_software_and_both_options(self):
        self.bot.ask_ai=MagicMock(return_value='Hello')
        self.bot.generate_website_proposal({
            'name':'Desert Sky Travel',
            'profile_text':'Travel agency and tour operator',
            'url':'https://fixture.test',
            'audit_findings':['The homepage has no meta description for search-result summaries.'],
        })
        prompt=self.bot.ask_ai.call_args.args[0].lower()
        self.assertIn('dedicated software concept',prompt)
        self.assertIn('streamline its operations',prompt)
        self.assertIn('website improvements, new or updated dedicated software, or both',prompt)
        self.assertIn('briefly names two or three of the confirmed issues',prompt)

    def test_local_travel_message_combines_specific_website_issue_and_software(self):
        self.bot.config['use_browser_ai']=False
        message=self.bot.generate_website_proposal({
            'name':'Desert Sky Travel',
            'profile_text':'Travel agency and tour operator',
            'url':'https://fixture.test',
            'audit_findings':['The homepage has no main H1 heading.'],
        })
        lower=message.lower()
        self.assertIn('missing a clear main heading',lower)
        self.assertIn('travel-operations platform',lower)
        self.assertIn('bookings',lower)
        self.assertIn('itineraries',lower)
        self.assertIn('website improvements, new or updated dedicated software, or both',lower)
        self.assertNotIn('h1',lower)

    def test_software_company_gets_partnership_prompt_not_website_pitch(self):
        self.bot.ask_ai = MagicMock(return_value='Partnership message')
        message = self.bot.generate_website_proposal({
            'name':'Acme Software Development',
            'profile_text':'Software company in Dubai',
        })
        prompt = self.bot.ask_ai.call_args.args[0].lower()
        self.assertEqual(message, 'Partnership message')
        self.assertIn('partnership outreach requirement', prompt)
        self.assertIn('reciprocal referrals', prompt)
        self.assertIn('do not pitch website creation', prompt)
        self.assertNotIn('clearly and politely propose creating a new professional business website', prompt)

    def test_marketing_agency_local_message_proposes_collaboration(self):
        self.bot.config['use_browser_ai'] = False
        self.bot.ask_ai = MagicMock()
        message = self.bot.generate_website_proposal({
            'name':'Bright Digital Marketing Agency',
            'profile_text':'Marketing agency and advertising service',
        })
        self.bot.ask_ai.assert_not_called()
        self.assertIn('business opportunity', message.lower())
        self.assertIn('reciprocal referrals', message.lower())
        self.assertIn('white-label', message.lower())
        self.assertNotIn('does not currently show a website', message.lower())

    def test_ordinary_business_is_not_classified_as_similar_provider(self):
        self.assertFalse(self.bot.is_similar_service_business({
            'name':'Garden Restaurant',
            'profile_text':'Restaurant with social media pages and online booking',
        }))

    def test_ai_failure_uses_local_message_and_continues_to_whatsapp(self):
        self.bot.ask_ai=MagicMock(side_effect=RuntimeError('AI unavailable'))
        self.bot.send_whatsapp_message=MagicMock(return_value=True)
        self.bot.open_website=MagicMock(return_value=None)
        result=self.bot.process_website({'name':'Fallback Salon','url':'https://fixture.test','phones':['0501112222']})
        self.bot.send_whatsapp_message.assert_called_once()
        self.assertIn('deeper review',result['proposal'].lower())
        self.assertNotIn('create a professional, mobile-friendly website',result['proposal'].lower())

    def test_ai_failure_without_website_uses_development_fallback(self):
        self.bot.ask_ai=MagicMock(side_effect=RuntimeError('AI unavailable'))
        self.bot.send_whatsapp_message=MagicMock(return_value=True)
        result=self.bot.process_website({'name':'Fallback Salon','phones':['0501112222']})
        self.assertIn('does not currently show a website',result['proposal'].lower())
        self.assertIn('create a professional, mobile-friendly website',result['proposal'].lower())

    def test_invalid_whatsapp_without_email_does_not_generate_message(self):
        def unavailable(result, _business_key):
            result.setdefault('channel_status', {})['whatsapp'] = {
                'status': 'not_on_whatsapp', 'reason': 'not registered'
            }
            return ''
        self.bot.preflight_whatsapp = MagicMock(side_effect=unavailable)
        self.bot.generate_website_proposal = MagicMock(return_value='Should not be generated')
        result = self.bot.process_website({'name':'Phone only','phones':['0501112222']})
        self.bot.preflight_whatsapp.assert_called_once()
        self.bot.generate_website_proposal.assert_not_called()
        self.assertFalse(result['proposal'])
        self.assertEqual(result['channel_status']['email']['status'], 'no_email')

    def test_invalid_whatsapp_uses_email_found_on_website(self):
        self.bot.preflight_whatsapp = MagicMock(return_value='')
        self.bot.open_website = MagicMock(return_value={'window_handle':'site','original_window':'google'})
        self.bot.find_emails = MagicMock(return_value=['hello@fixture.test'])
        self.bot.find_phone_numbers = MagicMock(return_value=[])
        self.bot.find_whatsapp_numbers = MagicMock(return_value=[])
        self.bot.find_contact_page = MagicMock(return_value=None)
        self.bot.generate_website_proposal = MagicMock(return_value='Hello by email')
        self.bot.send_whatsapp_message = MagicMock()
        self.bot.send_email_message = MagicMock(return_value=True)
        self.bot.fill_contact_form = MagicMock(return_value=False)

        result = self.bot.process_website({
            'name':'Email fallback', 'url':'https://fixture.test', 'phones':['0501112222']
        })

        self.bot.generate_website_proposal.assert_called_once()
        self.bot.send_whatsapp_message.assert_not_called()
        self.bot.send_email_message.assert_called_once()
        self.assertTrue(result['email_sent'])

    def test_website_without_working_whatsapp_or_email_prepares_contact_form_message(self):
        self.bot.preflight_whatsapp = MagicMock(return_value='')
        self.bot.open_website = MagicMock(return_value={'window_handle':'site','original_window':'google'})
        self.bot.find_emails = MagicMock(return_value=[])
        self.bot.find_phone_numbers = MagicMock(return_value=[])
        self.bot.find_whatsapp_numbers = MagicMock(return_value=[])
        self.bot.find_contact_page = MagicMock(return_value=None)
        self.bot.generate_website_proposal = MagicMock(return_value='Contact form message')
        self.bot.fill_contact_form = MagicMock(return_value=True)
        result = self.bot.process_website({'name':'No channel','url':'https://fixture.test'})
        self.bot.generate_website_proposal.assert_called_once()
        self.bot.fill_contact_form.assert_called_once()
        self.assertEqual(result['proposal'], 'Contact form message')
        self.assertTrue(result['form_prefilled'])

    def test_successful_whatsapp_also_sends_email_when_found(self):
        self.bot.preflight_whatsapp = MagicMock(return_value='971501112222')
        self.bot.send_whatsapp_message = MagicMock(return_value=True)
        self.bot.send_email_message = MagicMock(return_value=True)
        self.bot.generate_website_proposal = MagicMock(return_value='Hello')
        result = {
            'emails':['hello@fixture.test'],
            'phones':['0501112222'],
            'proposal':'',
            'channel_status':{},
        }
        sent = self.bot.attempt_preferred_outreach(
            result,
            {'name':'Both channels','url':'https://fixture.test'},
            'key',
        )
        self.assertTrue(sent)
        self.bot.send_whatsapp_message.assert_called_once()
        self.bot.send_email_message.assert_called_once()
        self.assertTrue(result['whatsapp_sent'])
        self.assertTrue(result['email_sent'])

    def test_whatsapp_preflight_reuses_tab_and_opens_no_message_text(self):
        element = MagicMock()
        element.is_displayed.return_value = True
        self.bot.whatsapp_window = 'wa'
        self.bot.driver.current_window_handle = 'google'
        self.bot.driver.window_handles = ['google', 'wa']
        self.bot.driver.find_elements.return_value = [element]
        self.bot.whatsapp_unavailable_reason = MagicMock(return_value='')

        state, _reason = self.bot.check_whatsapp_phone('971501112222')

        self.assertEqual(state, 'available')
        self.bot.driver.switch_to.new_window.assert_not_called()
        self.bot.driver.get.assert_called_once_with(
            'https://web.whatsapp.com/send?phone=971501112222'
        )
        self.assertNotIn('text=', self.bot.driver.get.call_args.args[0])

    def test_current_whatsapp_invalid_number_text_is_detected(self):
        self.bot.driver.execute_script.return_value = (
            "The number +971 2 678 9808 isn't on WhatsApp. OK"
        )
        self.assertTrue(self.bot.whatsapp_unavailable_reason())

    def test_invalid_number_preflight_dismisses_immediately_when_pause_is_zero(self):
        self.bot.whatsapp_window = 'wa'
        self.bot.driver.current_window_handle = 'google'
        self.bot.driver.window_handles = ['google', 'wa']
        self.bot.whatsapp_unavailable_reason = MagicMock(
            return_value='Number is invalid or not registered on WhatsApp; skipped'
        )
        self.bot.dismiss_whatsapp_unavailable_dialog = MagicMock(return_value=True)

        state, _reason = self.bot.check_whatsapp_phone('97126789808')

        self.assertEqual(state, 'not_on_whatsapp')
        self.bot.dismiss_whatsapp_unavailable_dialog.assert_called_once_with(self.bot.driver)

    def test_invalid_number_pause_keeps_notice_visible_for_configured_time(self):
        self.bot.config['whatsapp']['invalid_number_pause_seconds'] = 7
        with patch('main.sleep') as pause:
            self.bot.pause_before_invalid_whatsapp_continue()
        pause.assert_called_once_with(7)
        self.bot._log.assert_called_once()

    def test_local_message_mode_does_not_open_browser_ai(self):
        self.bot.config['use_browser_ai']=False
        self.bot.ask_ai=MagicMock()
        message=self.bot.generate_website_proposal({
            'name':'General Trading',
            'url':'https://fixture.test',
            'audit_findings':['The homepage has no meta description for search-result summaries.'],
        })
        self.bot.ask_ai.assert_not_called()
        self.assertIn('https://fixture.test',message.lower())
        self.assertIn('missing a search-result description',message.lower())
        self.assertNotIn('meta description',message.lower())
        self.assertNotIn('h1',message.lower())
        self.assertIn('fix these website issues',message.lower())

    def test_local_message_names_multiple_customer_friendly_issues_without_counts(self):
        self.bot.config['use_browser_ai']=False
        message=self.bot.generate_website_proposal({
            'name':'General Trading',
            'url':'https://fixture.test',
            'audit_findings':[
                'The homepage has no main H1 heading.',
                '44 of 50 homepage images are missing descriptive alt text.',
            ],
        })
        self.assertIn('identified several issues',message.lower())
        self.assertIn('missing a clear main heading',message.lower())
        self.assertIn('images are missing accessibility descriptions',message.lower())
        self.assertNotIn('h1',message.lower())
        self.assertNotIn('alt text',message.lower())
        self.assertNotIn('44',message)

    def test_homepage_audit_reports_only_observable_signals(self):
        self.bot.driver.execute_script.return_value = {
            'url':'http://fixture.test',
            'title':'Short',
            'description':'',
            'canonical':'',
            'viewport':'',
            'lang':'',
            'h1Count':0,
            'imageCount':4,
            'imagesMissingAlt':2,
            'insecureForms':1,
            'mixedResources':0,
        }
        findings = Automation.audit_current_website(self.bot)
        joined = ' '.join(findings).lower()
        self.assertIn('http rather than https', joined)
        self.assertIn('meta description', joined)
        self.assertIn('mobile viewport', joined)
        self.assertNotIn('hacked', joined)
        self.assertLessEqual(len(findings), 6)

    def test_website_audit_is_attached_before_message_generation(self):
        self.prepare_website()
        finding = 'The homepage has no main H1 heading.'
        self.bot.audit_current_website.return_value = [finding]
        self.bot.fill_contact_form = MagicMock(return_value=False)
        website = {'name':'Audited business','url':'https://fixture.test'}
        self.bot.process_website(website)
        generated_website = self.bot.generate_website_proposal.call_args.args[0]
        self.assertEqual(generated_website['audit_findings'], [finding])

    def prepare_website(self):
        self.bot.open_website=MagicMock(return_value={'window_handle':'site','original_window':'google'})
        self.bot.find_emails=MagicMock(return_value=['hello@fixture.test'])
        self.bot.find_phone_numbers=MagicMock(return_value=['0503334444'])
        self.bot.find_whatsapp_numbers=MagicMock(return_value=['0505556666'])
        self.bot.find_contact_page=MagicMock(return_value=None)
        self.bot.generate_website_proposal=MagicMock(return_value='Hello')
        self.bot.send_whatsapp_message=MagicMock(return_value=True)
        self.bot.send_email_message=MagicMock(return_value=True)

    def test_form_exception_does_not_block_outreach_and_site_phones_are_retained(self):
        self.prepare_website()
        self.bot.fill_contact_form=MagicMock(side_effect=RuntimeError('Form broke'))
        result=self.bot.process_website({'name':'Salon','url':'https://fixture.test'})
        self.bot.send_whatsapp_message.assert_called_once()
        self.bot.send_email_message.assert_called_once()
        self.assertEqual(set(result['phones']),{'0503334444','0505556666'})

    def test_filled_form_still_runs_outreach(self):
        self.prepare_website();self.bot.fill_contact_form=MagicMock(return_value=True)
        result=self.bot.process_website({'name':'Salon','url':'https://fixture.test'})
        self.assertTrue(result['form_prefilled'])
        self.bot.send_whatsapp_message.assert_called_once()
        self.bot.send_email_message.assert_called_once()
        self.assertEqual(outreach_stats(self.bot.db)[0]['forms'],1)

    def test_google_phone_is_used_before_failed_website(self):
        self.bot.open_website=MagicMock(return_value=None)
        self.bot.generate_website_proposal=MagicMock(return_value='Hello')
        self.bot.send_whatsapp_message=MagicMock(return_value=False)
        result=self.bot.process_website({'name':'Unavailable','url':'https://fixture.test','phones':['0501112222']})
        self.bot.send_whatsapp_message.assert_called_once()
        self.bot.open_website.assert_called_once()
        self.assertEqual(result['status'],'website_error')

    def test_form_requires_message_field(self):
        self.bot.find_contact_form=MagicMock(return_value=MagicMock())
        self.bot.find_form_field=MagicMock(side_effect=[MagicMock(),MagicMock(),None,None,None])
        self.bot.fill_field_value=MagicMock(return_value=True)
        self.assertFalse(self.bot.fill_contact_form('Sender','sender@example.test','','Hello'))

    def test_filled_form_is_submitted_when_review_mode_is_disabled(self):
        form = MagicMock()
        message_field = MagicMock()
        self.bot.config['review_mode'] = False
        self.bot.find_contact_form = MagicMock(return_value=form)
        self.bot.find_form_field = MagicMock(
            side_effect=[None, None, None, None, message_field]
        )
        self.bot.fill_field_value = MagicMock(return_value=True)
        self.bot.submit_contact_form = MagicMock(return_value='submitted')

        self.assertTrue(self.bot.fill_contact_form('', '', '', 'Hello'))

        self.bot.submit_contact_form.assert_called_once_with(form)
        self.assertEqual(self.bot.last_form_submission_status, 'submitted')

    def test_review_mode_keeps_filled_form_without_submitting(self):
        form = MagicMock()
        message_field = MagicMock()
        self.bot.config['review_mode'] = True
        self.bot.find_contact_form = MagicMock(return_value=form)
        self.bot.find_form_field = MagicMock(
            side_effect=[None, None, None, None, message_field]
        )
        self.bot.fill_field_value = MagicMock(return_value=True)
        self.bot.submit_contact_form = MagicMock()

        self.assertTrue(self.bot.fill_contact_form('', '', '', 'Hello'))

        self.bot.submit_contact_form.assert_not_called()
        self.assertEqual(self.bot.last_form_submission_status, 'review')

    def test_submit_contact_form_clicks_explicit_submit_only_once(self):
        form = MagicMock()
        button = MagicMock()
        button.is_displayed.return_value = True
        button.is_enabled.return_value = True
        form.find_elements.side_effect = lambda _by, selector: (
            [button] if selector == "button[type='submit']" else []
        )
        self.bot.driver.current_url = 'https://fixture.test/contact'

        def click():
            self.bot.driver.current_url = 'https://fixture.test/thank-you'

        button.click.side_effect = click

        outcome = self.bot.submit_contact_form(form)

        self.assertEqual(outcome, 'submitted')
        button.click.assert_called_once_with()

    def test_whatsapp_tries_second_number_without_losing_contacts(self):
        result=self.lead();result['phones']=['0501112222','0503334444']
        self.bot._send_whatsapp_to_phone=MagicMock(side_effect=[False,True])
        self.assertTrue(self.bot.send_whatsapp_message(result,'key'))
        self.assertEqual(self.bot._send_whatsapp_to_phone.call_count,2)
        self.assertEqual(result['phones'],['0501112222','0503334444'])

    def test_not_on_whatsapp_is_a_skip_status(self):
        result=self.lead()
        self.bot.find_whatsapp_send_button=MagicMock(return_value=None)
        self.bot.whatsapp_unavailable_reason=MagicMock(return_value='Number is not registered')
        self.assertFalse(self.bot.send_whatsapp_message(result,'key'))
        self.assertEqual(result['channel_status']['whatsapp']['status'],'not_on_whatsapp')
        self.bot.update_result_status(result)
        self.assertEqual(result['status'],'not_on_whatsapp')

    def test_same_whatsapp_recipient_is_never_contacted_twice(self):
        record_event(self.bot.db,'whatsapp_sent','first',recipient='971501112222')
        self.bot._send_whatsapp_to_phone=MagicMock()
        result=self.lead(name='Different listing')
        self.assertFalse(self.bot.send_whatsapp_message(result,'second'))
        self.bot._send_whatsapp_to_phone.assert_not_called()
        self.assertEqual(result['channel_status']['whatsapp']['status'],'duplicate_recipient')

    def test_uncertain_whatsapp_recipient_is_not_retried_under_another_listing(self):
        record_event(self.bot.db,'whatsapp_uncertain','first',recipient='971501112222')
        self.bot._send_whatsapp_to_phone=MagicMock()
        result=self.lead(name='Alternate listing name')
        self.assertFalse(self.bot.send_whatsapp_message(result,'second'))
        self.bot._send_whatsapp_to_phone.assert_not_called()
        self.assertEqual(result['channel_status']['whatsapp']['status'],'duplicate_recipient')

    def test_whatsapp_reuses_existing_tab(self):
        self.bot.whatsapp_window='wa'
        self.bot.driver.current_window_handle='google'
        self.bot.driver.window_handles=['google','wa']
        self.bot.find_whatsapp_send_button=MagicMock(return_value=MagicMock())
        self.bot.whatsapp_outgoing_ids=MagicMock(return_value=[])
        self.bot.wait_for_whatsapp_confirmation=MagicMock(return_value=True)
        self.assertTrue(self.bot._send_whatsapp_to_phone(self.lead(),'key'))
        self.bot.driver.switch_to.new_window.assert_not_called()
        self.bot.driver.get.assert_called_once()

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

    def test_confirmed_send_is_linked_to_campaign_area(self):
        self.bot.find_whatsapp_send_button=MagicMock(return_value=MagicMock())
        self.bot.whatsapp_outgoing_ids=MagicMock(return_value=[])
        self.bot.wait_for_whatsapp_confirmation=MagicMock(return_value=True)
        result=self.lead();result['area_key']='area-1'
        self.assertTrue(self.bot.send_whatsapp_message(result,'key'))
        self.assertEqual(
            self.bot.db.execute("SELECT area_key FROM outreach_events WHERE event_type='whatsapp_sent'").fetchone()[0],
            'area-1'
        )

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

    def test_missing_email_settings_fail_closed_without_smtp(self):
        self.bot.config.pop('email')
        smtp = self.smtp()
        result = self.lead()
        self.assertFalse(self.bot.send_email_message(result, 'key'))
        self.assertEqual(result['channel_status']['email']['status'], 'disabled')
        smtp.assert_not_called()

    def test_live_email_kill_switch_overrides_running_process_config(self):
        self.bot.config['email']['enabled'] = True
        self.bot.config_path = self.bot.data_dir / 'live-config.json'
        self.bot.config_path.write_text(
            json.dumps({'email': {'enabled': False}}), encoding='utf-8'
        )
        smtp = self.smtp()
        result = self.lead()
        self.assertFalse(self.bot.send_email_message(result, 'key'))
        self.assertFalse(self.bot._send_email_message(result, 'key'))
        self.assertEqual(result['channel_status']['email']['status'], 'disabled')
        smtp.assert_not_called()

    def test_disabled_email_is_skipped_before_preferred_outreach_sender(self):
        self.bot.config['email']['enabled'] = False
        self.bot.preflight_whatsapp = MagicMock(return_value='')
        self.bot.send_email_message = MagicMock()
        result = {
            'emails': ['hello@fixture.test'],
            'phones': [],
            'proposal': 'Saved message',
            'channel_status': {},
        }
        self.assertFalse(self.bot.attempt_preferred_outreach(
            result, {'name': 'Email disabled', 'url': 'https://fixture.test'}, 'key'
        ))
        self.bot.send_email_message.assert_not_called()
        self.assertEqual(result['channel_status']['email']['status'], 'disabled')

    def test_disabled_email_pending_and_retry_jobs_do_not_call_sender(self):
        _site, key = self.seed('disabled-email-jobs')
        self.bot.db.execute(
            "UPDATE outreach SET emails=?, proposal=? WHERE business_key=?",
            (json.dumps(['hello@fixture.test']), 'Saved message', key),
        )
        self.bot.db.commit()
        self.bot.config['email']['enabled'] = False
        self.bot.send_email_message = MagicMock()
        self.assertEqual(self.bot.process_pending_channel('email'), 0)
        self.assertFalse(self.bot.process_retry_channel('email', key))
        self.bot.send_email_message.assert_not_called()

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
        self.assertGreaterEqual(response.json['campaign']['total'],150)
        self.assertEqual(len(response.json['areas']),response.json['campaign']['total'])
        self.assertIn('no-store',response.headers['Cache-Control'])

    def test_dashboard_returns_saved_message_and_retry_starts_one_lead_job(self):
        _site, key = self.seed('retry-ready')
        self.bot.db.execute(
            "UPDATE outreach SET emails=?, proposal=?, channel_status=? WHERE business_key=?",
            (json.dumps(['hello@fixture.test']), 'Keep this exact message',
             json.dumps({'email': {'status': 'failed', 'reason': 'Temporary SMTP error'}}), key),
        )
        self.bot.db.commit()
        state = {'pid': 321, 'mode': 'retry-email', 'status': 'running'}
        with patch('web_app.data_dir', return_value=self.bot.data_dir), \
             patch('web_app.job_status', return_value={}), \
             patch('web_app.email_sending_enabled', return_value=True), \
             patch('web_app.start_process', return_value=state) as start, \
             patch('web_app.authenticated', return_value=True):
            client = web_app.app.test_client()
            dashboard = client.get('/api/dashboard')
            retry = client.post(f'/api/leads/{key}/retry', json={'channel': 'email'})
        lead = next(item for item in dashboard.json['leads'] if item['key'] == key)
        self.assertEqual(lead['proposal'], 'Keep this exact message')
        self.assertEqual(lead['channel_status']['email']['status'], 'failed')
        self.assertEqual(retry.status_code, 202)
        start.assert_called_once_with('retry-email', ['--retry-email', key])

    def test_retry_endpoint_rejects_confirmed_send(self):
        _site, key = self.seed('already-sent')
        self.bot.db.execute(
            "UPDATE outreach SET emails=?, proposal=? WHERE business_key=?",
            (json.dumps(['hello@fixture.test']), 'Saved message', key),
        )
        record_event(self.bot.db, 'email_sent', key, recipient='hello@fixture.test')
        with patch('web_app.data_dir', return_value=self.bot.data_dir), \
             patch('web_app.job_status', return_value={}), \
             patch('web_app.email_sending_enabled', return_value=True), \
             patch('web_app.start_process') as start, \
             patch('web_app.authenticated', return_value=True):
            response = web_app.app.test_client().post(
                f'/api/leads/{key}/retry', json={'channel': 'email'}
            )
        self.assertEqual(response.status_code, 409)
        start.assert_not_called()

    def test_web_dashboard_rejects_email_jobs_when_disabled(self):
        _site, key = self.seed('disabled-web-email')
        self.bot.db.execute(
            "UPDATE outreach SET emails=?, proposal=? WHERE business_key=?",
            (json.dumps(['hello@fixture.test']), 'Saved message', key),
        )
        self.bot.db.commit()
        with patch('web_app.data_dir', return_value=self.bot.data_dir), \
             patch('web_app.job_status', return_value={}), \
             patch('web_app.email_sending_enabled', return_value=False), \
             patch('web_app.start_process') as start, \
             patch('web_app.authenticated', return_value=True):
            client = web_app.app.test_client()
            pending = client.post('/api/jobs/start', json={'mode': 'pending-email'})
            retry = client.post(f'/api/leads/{key}/retry', json={'channel': 'email'})
        self.assertEqual(pending.status_code, 409)
        self.assertEqual(retry.status_code, 409)
        start.assert_not_called()

    def test_single_lead_retry_reuses_saved_proposal_and_preserves_other_channel(self):
        _site, key = self.seed('saved-retry')
        self.bot.db.execute(
            "UPDATE outreach SET emails=?, proposal=?, channel_status=? WHERE business_key=?",
            (json.dumps(['hello@fixture.test']), 'Exact saved proposal',
             json.dumps({'whatsapp': {'status': 'failed', 'reason': 'No confirmation'}}), key),
        )
        self.bot.db.commit()
        captured = {}

        def send(result, _key):
            captured['proposal'] = result['proposal']
            result['email_sent'] = True
            return self.bot.channel_outcome(result, 'email', 'sent') or True

        self.bot.send_email_message = MagicMock(side_effect=send)
        self.bot.process_retry_channel('email', key)
        saved = self.bot.db.execute(
            'SELECT proposal,channel_status FROM outreach WHERE business_key=?', (key,)
        ).fetchone()
        statuses = json.loads(saved['channel_status'])
        self.assertEqual(captured['proposal'], 'Exact saved proposal')
        self.assertEqual(saved['proposal'], 'Exact saved proposal')
        self.assertEqual(statuses['email']['status'], 'sent')
        self.assertEqual(statuses['whatsapp']['status'], 'failed')

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

    def test_uae_catalog_has_seven_emirates_and_unique_ordered_areas(self):
        catalog=Path(__file__).resolve().parents[1]/'locations'/'uae.json'
        locations=load_location_catalog(catalog)
        self.assertGreaterEqual(len(locations),150)
        self.assertEqual(len({item['area_key'] for item in locations}),len(locations))
        self.assertEqual({item['region'] for item in locations},{
            'Abu Dhabi','Dubai','Sharjah','Ajman','Ras Al Khaimah','Fujairah','Umm Al Quwain'
        })
        self.assertEqual([item['position'] for item in locations],list(range(1,len(locations)+1)))

    def test_area_queue_is_idempotent_and_marks_exhausted_area_complete(self):
        catalog=self.bot.data_dir/'locations.json'
        catalog.write_text(json.dumps({
            'country':'Testland','regions':[{'name':'North','cities':[{'name':'City','areas':['Area A']}]}]
        }),encoding='utf-8')
        locations=load_location_catalog(catalog)
        self.assertEqual(seed_target_areas(self.bot.db,locations),1)
        self.assertEqual(seed_target_areas(self.bot.db,locations),0)
        self.bot.search_business=MagicMock(return_value=self.bot.driver)
        def process(*_args,**_kwargs):
            self.bot.last_search_outcome={'status':'completed','reason':'No next Google page or additional business results'}
            return []
        self.bot.process_all_websites=MagicMock(side_effect=process)
        self.bot.run_location_campaign({
            'country':'Testland','locations_file':str(catalog),
            'query_template':'businesses in {area}, {city}, {country}',
            'businesses_per_area':10,'max_areas_per_run':1,
        })
        row=self.bot.db.execute('SELECT status,last_query,attempt_count FROM target_areas').fetchone()
        self.assertEqual(row['status'],'completed')
        self.assertEqual(row['last_query'],'businesses in Area A, City, Testland')
        self.assertEqual(row['attempt_count'],1)

    def test_area_stays_in_progress_when_business_attempt_limit_is_reached(self):
        catalog=self.bot.data_dir/'locations.json'
        catalog.write_text(json.dumps({
            'country':'Testland','regions':[{'name':'North','cities':[{'name':'City','areas':['Area A','Area B']}]}]
        }),encoding='utf-8')
        self.bot.search_business=MagicMock(return_value=self.bot.driver)
        def process(*_args,**_kwargs):
            self.bot.last_search_outcome={'status':'completed','reason':'Configured business limit reached'}
            return []
        self.bot.process_all_websites=MagicMock(side_effect=process)
        self.bot.run_location_campaign({
            'country':'Testland','locations_file':str(catalog),
            'businesses_per_area':10,'max_areas_per_run':2,
        })
        statuses=dict(self.bot.db.execute('SELECT area,status FROM target_areas'))
        self.assertEqual(statuses,{'Area A':'in_progress','Area B':'pending'})
        self.bot.process_all_websites.assert_called_once()


if __name__ == '__main__':
    unittest.main()
