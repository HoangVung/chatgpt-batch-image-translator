import base64
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import books34_composer as composer
import run_chatgpt_batch_books34 as worker
from desktop import runtime, webview_app, books34_setup
from desktop.workflow_sessions import SessionManager
from desktop.web_api import WebApi
from resource_guard import ResourceConflict
from test_web_api import FakeScheduler, Factory, FakeThread
from desktop_controller import DesktopController
from playwright.sync_api import sync_playwright
from test_image_results import image_url, image_bytes


class RoutingTests(unittest.TestCase):
    def test_all_modes_route_only_chatgpt_books34(self):
        for service in ('chatgpt', 'gemini'):
            for book in ('book-1', 'book-2', 'book-3', 'book-4'):
                for mode in ('main', 'retry', 'force', 'login'):
                    for frozen in (False, True):
                        with self.subTest(service=service, book=book, mode=mode, frozen=frozen):
                            settings = runtime.make_default_settings(ROOT)
                            settings['service'] = service
                            launch = runtime.build_process_launch(settings, mode, app_dir=ROOT,
                                session_id=book, frozen=frozen, environ={'BATCH_TRANSLATOR_WORKER_VARIANT':'injected'})
                            special = book in ('book-3','book-4') and service == 'chatgpt'
                            self.assertEqual(launch.env.get('BATCH_TRANSLATOR_WORKER_VARIANT'), 'books34' if special else None)
                            if not frozen:
                                self.assertEqual(Path(launch.command[-1]).name, 'run_chatgpt_batch_books34.py' if special else 'run_chatgpt_batch.py')

    def test_stable_frozen_launch_survives_broken_isolated_import(self):
        stable=Mock(return_value=0)
        with patch.dict(sys.modules, {'run_chatgpt_batch':SimpleNamespace(run_guarded=stable),
                                      'run_chatgpt_batch_books34':None}), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(webview_app.run_packaged_worker(),0)
            stable.assert_called_once()

    def test_frozen_dispatch_does_not_import_other_worker(self):
        stable, isolated = Mock(return_value=17), Mock(return_value=23)
        with patch.dict(sys.modules, {'run_chatgpt_batch':SimpleNamespace(run_guarded=stable),
                                      'run_chatgpt_batch_books34':SimpleNamespace(run_guarded=isolated)}):
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(webview_app.run_packaged_worker(),17)
                isolated.assert_not_called()
            with patch.dict(os.environ, {'BATCH_TRANSLATOR_WORKER_VARIANT':'books34'}):
                self.assertEqual(webview_app.run_packaged_worker(),23)
            with patch.dict(os.environ, {'BATCH_TRANSLATOR_WORKER_VARIANT':'bad'}), patch.object(sys,'stderr',io.StringIO()):
                self.assertEqual(webview_app.run_packaged_worker(),1)
            self.assertEqual(stable.call_count,1)
            self.assertEqual(isolated.call_count,1)

    def test_stable_launch_matches_reviewed_baseline(self):
        # Evidence is external to source; absence is not silently treated as a pass.
        baseline = ROOT.parent/'books34-evidence'/'baseline'/'desktop'/'runtime.py'
        if not baseline.exists():
            self.skipTest('Baseline evidence required for local characterization')
        spec=importlib.util.spec_from_file_location('baseline_runtime',baseline)
        old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
        for book in ('book-1','book-2'):
            for mode in ('main','retry','force','login'):
                for frozen in (False,True):
                    before=runtime.make_default_settings(ROOT/book);after=deepcopy(before)
                    kw=dict(app_dir=ROOT,data_dir=ROOT/book,settings_file=ROOT/'snapshot.json',
                            environ={'PATH':'original'},frozen=frozen)
                    a=old.build_process_launch(before,mode,**kw)
                    b=runtime.build_process_launch(after,mode,session_id=book,**kw)
                    self.assertEqual(a,b)
                    self.assertEqual(before,after)


class ResetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.registry=patch('resource_guard.registry_dir',return_value=self.root/'locks');self.registry.start();self.addCleanup(self.registry.stop)
        self.browser_scan=patch('resource_guard.browser_profiles_in_use',return_value=set());self.browser_scan.start();self.addCleanup(self.browser_scan.stop)

    def api(self,book):
        directory=self.root if book=='book-1' else self.root/'workflows'/book
        return WebApi(app_dir=ROOT,data_dir=directory,session_id=book,scheduler=FakeScheduler())

    def test_pair_mapping_reset_and_restart_preserve_files(self):
        originals={}
        for i,book in enumerate(('book-1','book-2','book-3','book-4'),1):
            api=self.api(book);api.settings.update(batch_size=str(i),start_from='44_044.jpg')
            runtime.save_settings(api.settings_path,api.settings)
            originals[book]=api.settings_path.read_bytes()
            profile=Path(api.settings['profile_dir']);profile.mkdir(parents=True)
            (profile/'do-not-delete').write_bytes(b'original')
        manager=SessionManager(app_dir=ROOT,data_dir=self.root)
        try:
            for book,template in (('book-3','book-1'),('book-4','book-2')):
                api=manager.sessions[book]
                self.assertFalse(hasattr(api,'_books34_setup_error'))
                self.assertEqual(api.settings['batch_size'], '1' if template=='book-1' else '2')
                self.assertEqual(api.settings['image_folder'],'')
                self.assertEqual(api.settings['download_folder'],'')
                self.assertEqual(api.settings['start_from'],'')
                self.assertIn('isolated-profiles',api.settings['profile_dir'])
                self.assertEqual((api.data_dir/'books34-setup-v1'/'app_settings.original.json').read_bytes(),originals[book])
                self.assertEqual((api.data_dir/'chatgpt_auto_profile'/'do-not-delete').read_bytes(),b'original')
                api.settings['batch_size']='19';runtime.save_settings(api.settings_path,api.settings)
            for book in ('book-1','book-2'):
                self.assertEqual(manager.sessions[book].settings_path.read_bytes(),originals[book])
        finally:manager._shutdown()
        again=SessionManager(app_dir=ROOT,data_dir=self.root)
        try:
            for book in ('book-3','book-4'):self.assertEqual(again.sessions[book].settings['batch_size'],'19')
        finally:again._shutdown()

    def test_interrupted_marker_write_recovers_original_backup_and_target(self):
        api,template=self.api('book-3'),self.api('book-1')
        runtime.save_settings(api.settings_path,api.settings);original=api.settings_path.read_bytes()
        actual=books34_setup.save_settings
        def fail_marker(path,data):
            if path.name=='complete.json':raise OSError('interrupted')
            actual(path,data)
        with patch.object(books34_setup,'save_settings',side_effect=fail_marker):
            with self.assertRaises(OSError):books34_setup.reset_book(api,template)
        first=api.settings_path.read_bytes()
        template.settings['batch_size']='99'
        books34_setup.reset_book(api,template)
        self.assertEqual(api.settings_path.read_bytes(),first)
        self.assertEqual((api.data_dir/'books34-setup-v1'/'app_settings.original.json').read_bytes(),original)

    def test_busy_reset_is_local_and_never_modifies_stable_settings(self):
        original=books34_setup.reset_book
        def busy(api,template):
            if api.session_id=='book-3':raise ResourceConflict('busy')
            return original(api,template)
        with patch.object(books34_setup,'reset_book',side_effect=busy):
            manager=SessionManager(app_dir=ROOT,data_dir=self.root)
        try:
            self.assertEqual(manager.sessions['book-3']._books34_setup_error,'busy')
            self.assertFalse(hasattr(manager.sessions['book-1'],'_books34_setup_error'))
            self.assertFalse(hasattr(manager.sessions['book-4'],'_books34_setup_error'))
            self.assertFalse(manager.sessions['book-1'].settings_path.exists())
        finally:manager._shutdown()

    def test_real_resource_lease_blocks_reset_without_writing_settings(self):
        from resource_guard import ResourceLease, canonical_path
        api,template=self.api('book-3'),self.api('book-1')
        runtime.save_settings(api.settings_path,api.settings)
        original=api.settings_path.read_bytes()
        with ResourceLease([{'kind':'profile','path':canonical_path(api.settings['profile_dir'])}], inspect_browsers=False):
            with self.assertRaises(ResourceConflict):books34_setup.reset_book(api,template)
        self.assertEqual(api.settings_path.read_bytes(),original)
        self.assertFalse((api.data_dir/'books34-setup-v1'/'pending.json').exists())

    def test_reset_rejects_running_and_stable_workflows(self):
        api,template=self.api('book-3'),self.api('book-1')
        for field in ('running','auto_next_active'):
            setattr(api.controller.state,field,True)
            with self.assertRaises(ResourceConflict):books34_setup.reset_book(api,template)
            setattr(api.controller.state,field,False)
        with self.assertRaises(ValueError):books34_setup.reset_book(template,api)
        self.assertFalse(api.settings_path.exists())


class ComposerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch(headless=True,executable_path=os.environ.get('BATCH_TEST_BROWSER'))
    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.page=self.browser.new_page();self.addCleanup(self.page.close)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.clock=0
        self.patchers=[patch.object(worker,'DOWNLOAD_FOLDER',self.temp.name),
                       patch.object(worker,'wait_if_cloudflare'),
                       patch.object(worker.time,'monotonic',side_effect=lambda:self.clock),
                       patch.object(worker,'sleep',side_effect=self.advance)]
        for patcher in self.patchers:patcher.start();self.addCleanup(patcher.stop)
    def advance(self,seconds):self.clock+=seconds
    def show(self,html):
        self.page.set_content(html)
        self.page.wait_for_function('Array.from(document.images).every(i=>i.complete)')
    def fixture(self,extra='',editor='<div class="ProseMirror" role="textbox" contenteditable="true" style="min-height:30px"></div>'):
        self.show('<main><form><div>'+extra+'</div>'+editor+'</form></main>')

    def test_hidden_editor_attachment_then_prompt_ready_and_fill(self):
        self.show('<textarea id="prompt-textarea" style="display:none">hidden</textarea><main><form>'
                  '<div><img src="'+image_url()+'"><button aria-label="Cancel upload">Cancel</button></div>'
                  '<div><div class="ProseMirror" contenteditable="true" style="height:30px"></div></div></form></main>')
        self.assertTrue(worker.wait_upload_attached(self.page,3))
        self.assertTrue(worker.wait_prompt_ready(self.page,3))
        worker.safe_click_prompt(self.page,3);worker.clear_prompt_box(self.page);worker.fill_prompt_box(self.page,'test only')
        self.assertEqual(worker.get_prompt_text(self.page),'test only')
        self.assertEqual(self.page.locator('#prompt-textarea').input_value(),'hidden')
        worker.clear_prompt_box(self.page);self.assertEqual(worker.get_prompt_text(self.page),'')
        self.assertFalse(worker.is_generating(self.page))

    def test_unrelated_cancel_does_not_block_real_generation_does(self):
        self.fixture('<button aria-label="Cancel">Cancel</button><img src="'+image_url()+'">')
        self.assertTrue(worker.wait_prompt_ready(self.page,2))
        self.page.locator('form').evaluate("el=>el.insertAdjacentHTML('beforeend','<button data-testid=\"stop-button\">Stop</button>')")
        self.assertTrue(worker.is_generating(self.page))
        self.assertFalse(worker.wait_prompt_ready(self.page,2))
        self.assertEqual(self.clock,2)

    def test_disabled_editor_replaced_after_hydration(self):
        self.fixture(editor='<div id="prompt-textarea" aria-disabled="true" contenteditable="true" style="height:30px"></div>')
        def advance(seconds):
            self.clock+=seconds
            if self.clock>=1:self.page.locator('#prompt-textarea').evaluate("el=>el.removeAttribute('aria-disabled')")
        with patch.object(worker,'sleep',side_effect=advance):self.assertTrue(worker.wait_prompt_ready(self.page,3))
        self.assertEqual(self.clock,1)

    def test_history_and_broken_images_never_count_as_upload(self):
        for preview in ('<img src="bad://broken">','<img src="'+image_url()+'" style="display:none">',''):
            self.show('<main><article data-message-author-role="user"><img src="'+image_url()+'"></article>'
                '<form>'+preview+'<div contenteditable="true" style="height:30px"></div></form></main>')
            with self.assertRaisesRegex(RuntimeError,'Không xác nhận'):worker.wait_upload_attached(self.page,2)
        records=list((Path(self.temp.name)/'composer-diagnostics').glob('*.json'))
        self.assertEqual(len(records),3)
        for record in records:
            text=record.read_text(encoding='utf-8');self.assertNotIn('data:image',text);self.assertNotIn('bad://',text)

    def test_upload_waits_until_busy_clears_then_reads_fresh_composer(self):
        self.fixture('<div data-testid="attachment" aria-busy="true"><img src="'+image_url()+'"></div>')
        def advance(seconds):
            self.clock+=seconds
            if self.clock==1:self.page.locator('[data-testid="attachment"]').evaluate("el=>el.removeAttribute('aria-busy')")
        with patch.object(worker,'sleep',side_effect=advance):self.assertTrue(worker.wait_upload_attached(self.page,3))
        self.assertEqual(self.clock,1)
        self.page.locator('.ProseMirror').evaluate("el=>el.outerHTML='<div id=\"prompt-textarea\" contenteditable=\"true\" style=\"height:30px\"></div>'")
        worker.fill_prompt_box(self.page,'fresh');self.assertEqual(worker.get_prompt_text(self.page),'fresh')

    def test_upload_error_and_readonly_editor_are_not_ready(self):
        self.fixture('<div data-testid="attachment"><span role="alert">private failure</span></div>')
        self.assertFalse(worker.wait_prompt_ready(self.page,2))
        self.fixture(editor='<textarea id="prompt-textarea" readonly>private prompt</textarea>')
        self.assertFalse(worker.wait_prompt_ready(self.page,2))
        self.assertEqual(composer.inspect(self.page)['reason'],'editor_disabled')
        for record in (Path(self.temp.name)/'composer-diagnostics').glob('*.json'):
            self.assertNotIn('private',record.read_text(encoding='utf-8'))

    def test_upload_uses_current_composer_input_and_never_sends(self):
        self.show('<aside><input type="file" id="wrong"></aside><form><input type="file" id="upload-files" style="display:none">'
                  '<div contenteditable="true" style="height:30px"></div><button data-testid="send-button">Send</button></form>')
        self.page.evaluate("() => {window.sent=0;document.querySelector('button').onclick=e=>{e.preventDefault();window.sent++};}")
        image=Path(self.temp.name)/'sample.png';image.write_bytes(image_bytes())
        worker.upload_image(self.page,image)
        self.assertEqual(self.page.locator('#wrong').evaluate('el=>el.files.length'),0)
        self.assertEqual(self.page.locator('#upload-files').evaluate('el=>el.files.length'),1)
        worker.fill_prompt_box(self.page,'test');worker.clear_prompt_box(self.page)
        self.assertEqual(self.page.evaluate('window.sent'),0)

    def test_history_editor_is_ignored_and_missing_editor_is_not_sent(self):
        self.show('<article data-message-author-role="user"><div contenteditable="true" style="height:30px">history</div></article>')
        self.assertEqual(worker.get_prompt_locator(self.page).count(),0)
        with self.assertRaises(RuntimeError):worker.get_prompt_text(self.page)
