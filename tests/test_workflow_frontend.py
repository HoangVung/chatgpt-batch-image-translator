import json
import os
import tempfile
import unittest
from pathlib import Path

import test_web_frontend as frontend_helpers
from desktop.workflow_sessions import SessionManager

PROJECT_ROOT = frontend_helpers.PROJECT_ROOT


class WorkflowFrontendTests(unittest.TestCase):
    setUpClass = classmethod(frontend_helpers.WebFrontendTests.setUpClass.__func__)
    tearDownClass = classmethod(frontend_helpers.WebFrontendTests.tearDownClass.__func__)

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1180, "height": 820})
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        with tempfile.TemporaryDirectory() as directory:
            manager = SessionManager(app_dir=PROJECT_ROOT, data_dir=Path(directory))
            initial = manager._invoke("get_initial_state")["data"]
            manager._shutdown()
        initial["sessions"]["book-1"]["settings"]["image_folder"] = "D:/book-A/source"
        initial["sessions"]["book-1"]["settings"]["download_folder"] = "D:/book-A/output"
        bootstrap = r"""
          const initial = JSON.parse(%s);
          window.calls = [];
          const ok = (data={}) => Promise.resolve({ok:true,data:structuredClone(data)});
          const records = initial.sessions;
          function emit(id, type, payload={}) {
            const c = records[id].controller;
            c.sequence += 1;
            if(type === 'log_appended') c.log_history = (c.log_history || '') + payload.text;
            if(type === 'log_cleared') c.log_history = '';
            if(type === 'progress_changed') { c.progress_done = payload.done; c.progress_total = payload.total; }
            if(type === 'process_started') c.running = true;
            if(type === 'process_completed') c.running = false;
            if(type === 'manual_action_required') c.manual_action_required = true;
            window.batchTranslatorReceive({session_id:id,run_id:id+'-run',sequence:c.sequence,type,payload});
          }
          window.emitWorkflow = emit;
          window.pywebview = {api: {
            get_initial_state: (id) => ok(id ? records[id] : initial),
            save_settings: (payload,id) => {
              calls.push(['save_settings',id,structuredClone(payload)]);
              const finish = () => { Object.assign(records[id].settings,payload); return ok({settings:records[id].settings}); };
              if(window.deferSave === id) { window.deferSave = null; return new Promise(resolve => { window.finishSave = () => resolve(finish()); }); }
              return finish();
            },
            start_batch: (mode,id) => { calls.push(['start_batch',id,mode]); emit(id,'process_started'); return ok({state:records[id].controller}); },
            choose_folder: (kind,id) => {
              calls.push(['choose_folder',id,kind]);
              return new Promise(resolve => { window.finishFolder = path => resolve({ok:true,data:{kind,path,cancelled:false}}); });
            },
            stop_process: (id) => { calls.push(['stop_process',id]); emit(id,'process_completed'); return ok({state:records[id].controller}); },
            continue_manual_intervention: (id) => { calls.push(['continue',id]); return ok(); },
            clear_log: (id) => { calls.push(['clear_log',id]); emit(id,'log_cleared'); return ok(); },
            copy_log: (id) => { calls.push(['copy_log',id]); return ok(); },
            export_log: (id) => { calls.push(['export_log',id]); return ok(); },
            open_output_folder: (id) => { calls.push(['open_output',id]); return ok(); },
            cancel_auto_next: (id) => { calls.push(['cancel_auto',id]); return ok(); },
            run_auto_next_now: (id) => { calls.push(['run_now',id]); return ok(); },
            set_theme: (theme) => { for (const id in records) { records[id].settings.theme = theme; emit(id,'preferences_changed',{theme}); } return ok(); },
            set_language: (language) => { for (const id in records) { records[id].settings.language = language; emit(id,'preferences_changed',{language}); } return ok(); },
            login_account: (account,id) => { calls.push(['login',id,account]); emit(id,'process_started'); return ok({state:records[id].controller}); },
            confirm_existing_output: (id) => { calls.push(['confirm_output',id]); return ok(); }
          }};
        """ % json.dumps(json.dumps(initial, ensure_ascii=False))
        self.page.add_init_script(bootstrap)
        self.page.goto((PROJECT_ROOT / "ui/index.html").as_uri())
        self.page.wait_for_selector("#tab-book-2")

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def test_streaming_logs_preserve_selection_scroll_and_other_ui(self):
        page = self.page
        page.evaluate(r"""() => {
          emitWorkflow('book-1', 'process_started');
          emitWorkflow('book-1', 'log_appended', {text:'selected log line\n'.repeat(200)});
          const log = document.querySelector('#log');
          log.scrollTop = 100;
          window.originalLogScroll = log.scrollTop;
          window.originalLogNode = log.firstChild;
          const range = document.createRange();
          range.setStart(log.firstChild, 0);
          range.setEnd(log.firstChild, 8);
          getSelection().removeAllRanges();
          getSelection().addRange(range);
          window.uiChanges = [];
          window.uiObserver = new MutationObserver(changes => {
            uiChanges.push(...changes.filter(change => !log.contains(change.target)));
          });
          uiObserver.observe(document.body, {subtree:true,childList:true,characterData:true,attributes:true});
        }""")
        page.evaluate(r"""async () => {
          for (let index = 0; index < 12; index++) {
            emitWorkflow('book-1', 'log_appended', {text:`new line ${index}\n`});
            emitWorkflow('book-2', 'log_appended', {text:`background ${index}\n`});
            await new Promise(requestAnimationFrame);
          }
        }""")
        self.assertEqual(page.evaluate("getSelection().toString()"), "selected")
        self.assertTrue(page.evaluate("document.querySelector('#log').firstChild === originalLogNode"))
        self.assertEqual(page.evaluate("document.querySelector('#log').scrollTop"), page.evaluate("originalLogScroll"))
        self.assertEqual(page.evaluate("uiChanges.length"), 0)
        self.assertIn("new line 11", page.locator("#log").text_content())
        self.assertNotIn("background", page.locator("#log").text_content())
        page.evaluate("uiObserver.disconnect(); getSelection().removeAllRanges();")
        page.evaluate(r"""() => {
          const log = document.querySelector('#log');
          log.scrollTop = log.scrollHeight;
          emitWorkflow('book-1', 'log_appended', {text:'follow the tail\n'.repeat(20)});
        }""")
        self.assertTrue(page.evaluate("(() => { const log = document.querySelector('#log'); return log.scrollHeight - log.clientHeight - log.scrollTop < 2; })()"))
        page.locator('#tab-book-2').click()
        self.assertIn('background 11', page.locator('#log').text_content())
        self.assertNotIn('new line', page.locator('#log').text_content())
        page.evaluate("emitWorkflow('book-2', 'log_cleared'); emitWorkflow('book-2', 'log_appended', {text:'after clear'});")
        self.assertEqual(page.locator('#log').text_content(), 'after clear')

    def test_progress_updates_keep_unchanged_labels_and_focus(self):
        page = self.page
        page.evaluate("emitWorkflow('book-1', 'process_started');")
        page.locator('#tab-book-1').focus()
        page.evaluate("""() => {
          window.stableLabels = ['#active-book', '#run-indicator span:last-child',
            '#tab-book-1 strong', '#tab-book-2 small', '.context-service', '.context-caption']
            .map(selector => { const node = document.querySelector(selector); return [node, node.firstChild]; });
          for (let done = 1; done <= 10; done++) {
            emitWorkflow('book-1', 'progress_changed', {done,total:10});
          }
        }""")
        self.assertTrue(page.evaluate("stableLabels.every(([node, child]) => node.firstChild === child)"))
        self.assertEqual(page.evaluate('document.activeElement.id'), 'tab-book-1')
        self.assertIn('10 / 10 (100%)', page.locator('#progress-text').text_content())
        self.assertIn('10/10', page.locator('#tab-book-1').text_content())

    def test_snapshot_ahead_of_log_events_does_not_drop_or_duplicate_output(self):
        page = self.page
        page.evaluate("""() => {
          emitWorkflow('book-1', 'log_cleared');
          emitWorkflow('book-1', 'log_appended', {text:'before snapshot;'});
          window.originalLogNode = document.querySelector('#log').firstChild;
          acceptSnapshot(state, {...state.controller, sequence:state.sequence + 1,
            log_history:state.controller.log_history + 'snapshot output;'});
          emitWorkflow('book-1', 'log_appended', {text:'snapshot output;'});
          emitWorkflow('book-1', 'log_appended', {text:'next output;'});
        }""")
        self.assertEqual(page.locator('#log').text_content(), 'before snapshot;snapshot output;next output;')
        self.assertTrue(page.evaluate("document.querySelector('#log').firstChild === originalLogNode"))
        page.evaluate("acceptSnapshot(state, {...state.controller, sequence:state.sequence + 1, log_history:''});")
        self.assertEqual(page.locator('#log').text_content(), '')

    def test_sidebar_shows_both_books_and_background_account_switch(self):
        page = self.page
        page.evaluate("""() => {
          for (const [id, target] of sessions) {
            target.settings.chatgpt_accounts = [
              {id:'personal',name:'Vung-Personal',profile_dir:'D:/'+id+'/personal'},
              {id:'business',name:'Vung-Business',profile_dir:'D:/'+id+'/business'}];
            target.settings.service = 'chatgpt';
            target.settings.active_chatgpt_account_id = id === 'book-1' ? 'personal' : 'business';
          }
          renderSession();
        }""")
        first = page.locator('#service-book-1')
        second = page.locator('#service-book-2')
        self.assertIn('Sách 1', first.text_content())
        self.assertIn('Vung-Personal', first.text_content())
        self.assertIn('Sách 2', second.text_content())
        self.assertIn('Vung-Business', second.text_content())
        page.evaluate("emitWorkflow('book-2','account_event',{event:{event:'account_switched',account_id:'personal'}})")
        self.assertIn('Vung-Personal', second.text_content())
        self.assertEqual(page.locator('#tab-book-1').get_attribute('aria-selected'), 'true')
        page.locator('#tab-book-2').click()
        page.locator('#service').select_option('gemini')
        self.assertIn('Google Gemini', second.text_content())
        self.assertIn('ChatGPT', first.text_content())
        page.locator('#tab-book-1').click()
        self.assertIn('Google Gemini', second.text_content())
        page.locator('#language').select_option('en')
        self.assertIn('Book 1', first.text_content())
        self.assertIn('Book 2', second.text_content())

    def test_background_events_drafts_controls_and_keyboard_stay_with_book(self):
        page = self.page
        page.locator("#source-folder").fill("D:/draft-book-A")
        page.evaluate("emitWorkflow('book-2','progress_changed',{done:2,total:8}); emitWorkflow('book-2','log_appended',{text:'LOG B ONLY'}); emitWorkflow('book-2','process_started');")
        self.assertNotIn("LOG B", page.locator("#log").text_content())
        self.assertIn("2/8", page.locator("#tab-book-2").text_content())
        page.locator("#tab-book-2").click()
        self.assertEqual(page.locator("#source-folder").input_value(), "")
        self.assertIn("LOG B ONLY", page.locator("#log").text_content())
        self.assertIn("2 / 8", page.locator("#progress-text").text_content())
        self.assertTrue(page.locator("#source-folder").is_disabled())
        page.locator("#stop").click()
        page.wait_for_function("window.calls.some(c=>c[0]==='stop_process' && c[1]==='book-2')")
        page.locator("#tab-book-2").focus()
        page.keyboard.press("ArrowLeft")
        self.assertEqual(page.locator("#tab-book-1").get_attribute("aria-selected"), "true")
        self.assertEqual(page.locator("#source-folder").input_value(), "D:/draft-book-A")
        page.evaluate("emitWorkflow('book-2','manual_action_required');")
        self.assertEqual(page.locator("#tab-book-2").get_attribute("data-attention"), "true")
        self.assertFalse(page.locator("#manual-banner").is_visible())

    def test_late_save_start_and_folder_response_cannot_target_current_tab(self):
        page = self.page
        page.evaluate("window.deferSave='book-1'")
        page.locator('[data-mode="main"]').click()
        page.wait_for_function("typeof window.finishSave === 'function'")
        page.locator("#tab-book-2").click()
        page.locator("#source-folder").fill("D:/source-B")
        page.locator("#output-folder").fill("D:/output-B")
        page.locator('[data-mode="main"]').click()
        page.wait_for_function("calls.some(c=>c[0]==='start_batch' && c[1]==='book-2')")
        page.evaluate("window.finishSave()")
        page.wait_for_function("calls.some(c=>c[0]==='start_batch' && c[1]==='book-1')")
        starts = page.evaluate("calls.filter(c=>c[0]==='start_batch').map(c=>c[1])")
        self.assertEqual(starts, ["book-2", "book-1"])
        self.assertEqual(page.locator("#source-folder").input_value(), "D:/source-B")
        page.locator("#stop").click()
        page.locator('[data-folder="output"]').click()
        page.wait_for_function("typeof window.finishFolder === 'function'")
        page.locator("#tab-book-1").click()
        page.evaluate("window.finishFolder('D:/picked-B-output')")
        self.assertEqual(page.locator("#output-folder").input_value(), "D:/book-A/output")
        page.locator("#tab-book-2").click()
        page.wait_for_function("document.querySelector('#output-folder').value==='D:/picked-B-output'")

    def test_folder_totals_stay_with_each_book_across_batches_and_language(self):
        page = self.page
        page.evaluate("emitWorkflow('book-1','folder_progress_changed',{done:13,total:100}); emitWorkflow('book-2','folder_progress_changed',{done:42,total:200}); emitWorkflow('book-1','process_started'); emitWorkflow('book-1','progress_changed',{done:3,total:10});")
        self.assertIn("3/10", page.locator("#tab-book-1").text_content())
        self.assertIn("Cả thư mục: 13/100 ảnh", page.locator("#tab-book-1").text_content())
        page.locator("#tab-book-2").click()
        page.evaluate("emitWorkflow('book-1','progress_changed',{done:0,total:10}); emitWorkflow('book-2','process_completed');")
        self.assertIn("13/100", page.locator("#tab-book-1").text_content())
        self.assertIn("42/200", page.locator("#tab-book-2").text_content())
        page.locator("#language").select_option("en")
        self.assertIn("Whole folder: 42/200 images", page.locator("#tab-book-2").text_content())

    def test_preferences_and_layout_at_minimum_window_size(self):
        page = self.page
        page.locator("#theme").select_option("dark")
        page.locator("#tab-book-2").click()
        self.assertEqual(page.locator("html").get_attribute("data-theme"), "dark")
        page.locator("#language").select_option("en")
        page.wait_for_function("document.querySelector('#tab-book-1 strong').textContent==='Book 1'")
        page.locator("#tab-book-1").click()
        self.assertEqual(page.locator("#language").input_value(), "en")
        for width, height in ((900, 620), (1180, 820), (1440, 1000)):
            page.set_viewport_size({"width": width, "height": height})
            self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"))
            self.assertTrue(page.evaluate("document.querySelector('#tab-book-1').getBoundingClientRect().right < document.querySelector('#tab-book-2').getBoundingClientRect().left"))
        folder = os.environ.get("PARALLEL_SCREENSHOT_DIR")
        if folder:
            target = Path(folder)
            target.mkdir(parents=True, exist_ok=True)
            page.locator("#language").select_option("vi")
            page.evaluate("emitWorkflow('book-1','process_started'); emitWorkflow('book-1','progress_changed',{done:3,total:10}); emitWorkflow('book-2','process_started'); emitWorkflow('book-2','progress_changed',{done:6,total:10});")
            page.set_viewport_size({"width": 1180, "height": 820})
            page.screenshot(path=target / "two-tabs-dark.png", full_page=True, animations="disabled")
            page.locator("#theme").select_option("light")
            page.set_viewport_size({"width": 900, "height": 620})
            page.screenshot(path=target / "two-tabs-light-small.png", full_page=True, animations="disabled")


if __name__ == "__main__":
    unittest.main()
