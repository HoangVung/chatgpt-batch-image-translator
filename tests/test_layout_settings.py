"""Layout UI settings and launch isolation; all worker launches are simulated."""
import json
import sys
import tempfile
import threading
import types
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.runtime import (apply_form_settings, build_process_launch, load_settings,
                             make_default_settings, write_launch_snapshot,
                             write_layout_launch_snapshot)
from desktop.web_api import WebApi
from desktop.webview_app import WebBridge
from desktop.workflow_sessions import SessionManager
from desktop_controller import ControllerEvent, DesktopController
from layout_profile import load_profile
from test_web_api import FakeScheduler, Factory, FakeThread


class LayoutSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.scheduler, self.factory = FakeScheduler(), Factory()
        self.controller = DesktopController(self.scheduler, popen_factory=self.factory,
            thread_factory=FakeThread, process_tree_terminator=lambda pid: None)
        self.api = WebApi(controller=self.controller, scheduler=self.scheduler,
                          app_dir=ROOT, data_dir=self.root)
        # Avoid background scans: these tests concern settings and launches only.
        self.api._request_folder_progress = Mock(return_value={"done": 0, "total": 0})

    def tearDown(self):
        for process in self.factory.processes:
            process.return_code = 0
        self.api._shutdown()
        self.temp.cleanup()

    def enable(self, **values):
        response = self.api.save_settings(dict(layout_consistency_enabled=True, **values))
        self.assertTrue(response['ok'], response)

    def launch(self):
        response = self.api.start_batch('main')
        self.assertTrue(response['ok'], response)
        return self.factory.calls[-1][1]['env']

    def test_legacy_settings_default_to_off_without_rewriting_disk(self):
        source = self.root / 'legacy.json'
        source.write_text('{"batch_size": "8"}', encoding='utf-8')
        before = source.read_bytes()
        saved = load_settings(source, make_default_settings(self.root))
        self.assertIs(saved['layout_consistency_enabled'], False)
        self.assertEqual(saved['layout_profile_path'], '')
        self.assertEqual(source.read_bytes(), before)

    def test_form_rejects_truthy_values_and_nonstring_profile(self):
        for value in ('true', 'false', 1, 0, None, []):
            with self.subTest(value=value):
                result = self.api.save_settings({'layout_consistency_enabled': value})
                self.assertFalse(result['ok'])
                self.assertIs(self.api.settings['layout_consistency_enabled'], False)
        for value in (False, 4, None, 'bad\0path'):
            self.assertFalse(self.api.save_settings({'layout_profile_path': value})['ok'])
        self.assertFalse(self.api.settings_path.exists())

    def test_settings_save_and_reload_both_fields(self):
        self.enable(layout_profile_path='custom.json')
        reloaded = load_settings(self.api.settings_path, make_default_settings(self.root))
        self.assertIs(reloaded['layout_consistency_enabled'], True)
        self.assertEqual(reloaded['layout_profile_path'], 'custom.json')
        self.assertEqual(self.api.get_initial_state()['data']['settings']['layout_profile_path'], 'custom.json')

    def test_layout_change_is_run_configuration_change(self):
        with patch.object(self.controller, 'mark_run_configuration_changed') as changed:
            self.enable()
            changed.assert_called_once()
        with patch.object(self.controller, 'mark_run_configuration_changed') as changed:
            self.enable()
            changed.assert_not_called()
        with patch.object(self.controller, 'mark_run_configuration_changed') as changed:
            self.enable(layout_profile_path='another.json')
            changed.assert_called_once()

    def test_off_ignores_bad_profile_and_strips_inherited_environment(self):
        self.api.settings['layout_profile_path'] = str(self.root / 'missing.json')
        with patch.dict('os.environ', {'BATCH_LAYOUT_PROFILE': 'some-other-book.json'}), \
                patch('layout_profile.load_profile', side_effect=AssertionError('OFF must not read a profile')):
            env = self.launch()
        self.assertNotIn('BATCH_LAYOUT_PROFILE', env)
        self.assertEqual(list((self.root / 'run_configs').glob('*.layout.json')), [])

    def test_on_creates_default_companion_inside_book_output(self):
        self.enable()
        env = self.launch()
        settings_file = Path(env['BATCH_TRANSLATOR_SETTINGS_FILE'])
        profile_file = Path(env['BATCH_LAYOUT_PROFILE'])
        self.assertEqual(profile_file, settings_file.with_suffix('.layout.json'))
        profile = load_profile(profile_file)
        self.assertIs(profile.enabled, True)
        self.assertEqual(profile.target_size, (1600, 2400))
        self.assertEqual(profile.output_dir, Path(self.api.settings['download_folder']) / 'layout_results')
        self.assertTrue(profile.qc_enabled)
        self.assertTrue(profile.normalize_enabled)

    def test_custom_profile_resolves_paths_and_never_changes_source(self):
        directory = self.root / 'custom'
        directory.mkdir()
        sample = directory / 'approved.png'
        sample.write_bytes(b'placeholder')
        source = directory / 'profile.json'
        source.write_text(json.dumps({'enabled': False, 'target_size': [1800, 2600],
            'output_dir': 'outputs', 'approved_sample': 'approved.png', 'annotate': True}), encoding='utf-8')
        before = source.read_bytes()
        self.enable(layout_profile_path=str(source))
        env = self.launch()
        companion = Path(env['BATCH_LAYOUT_PROFILE'])
        profile = load_profile(companion)
        self.assertTrue(profile.enabled)
        self.assertTrue(profile.annotate)
        self.assertEqual(profile.target_size, (1800, 2600))
        self.assertEqual(profile.approved_sample, sample)
        self.assertEqual(profile.output_dir, directory / 'outputs')
        self.assertEqual(source.read_bytes(), before)
        frozen = companion.read_bytes()
        source.write_text('{"target_size": [2000, 3000]}', encoding='utf-8')
        self.assertEqual(companion.read_bytes(), frozen)

    def test_snapshot_cannot_be_replaced_during_same_launch(self):
        settings = dict(self.api.settings, layout_consistency_enabled=True)
        base = write_launch_snapshot(settings, self.root / 'snapshots')
        companion = write_layout_launch_snapshot(settings, base)
        before = companion.read_bytes()
        with self.assertRaises(FileExistsError):
            write_layout_launch_snapshot(settings, base)
        self.assertEqual(companion.read_bytes(), before)

    def test_invalid_profile_fails_before_worker_and_cleans_snapshots(self):
        source = self.root / 'bad.json'
        for content in ('bad JSON', '{"target_size": [0, 10]}', '{"unknown": true}',
                        '{"approved_sample": "missing.png"}'):
            with self.subTest(content=content):
                source.write_text(content, encoding='utf-8')
                self.enable(layout_profile_path=str(source))
                result = self.api.start_batch('main')
                self.assertFalse(result['ok'], result)
                self.assertEqual(self.factory.calls, [])
                self.assertIsNone(self.api._snapshot_path)
                self.assertEqual(list((self.root / 'run_configs').glob('*.json')), [])
                self.assertEqual(source.read_text(encoding='utf-8'), content)

    def test_missing_profile_fails_without_worker(self):
        self.enable(layout_profile_path=str(self.root / 'missing.json'))
        self.assertFalse(self.api.start_batch('main')['ok'])
        self.assertEqual(self.factory.calls, [])

    def test_default_profile_requires_output_folder(self):
        settings = dict(self.api.settings, layout_consistency_enabled=True, download_folder='')
        with self.assertRaises(ValueError):
            write_layout_launch_snapshot(settings, self.root / 'run.json')
        self.assertFalse((self.root / 'run.layout.json').exists())

    def test_failed_launch_cleans_companion(self):
        self.enable()
        with patch.object(self.controller, 'start', side_effect=OSError('simulated launch failure')):
            response = self.api.start_batch('main')
        self.assertFalse(response['ok'])
        self.assertEqual(list((self.root / 'run_configs').glob('*.json')), [])
        self.assertIsNone(self.api._snapshot_path)

    def test_completed_run_cleans_both_snapshots(self):
        self.enable()
        env = self.launch()
        settings_file = Path(env['BATCH_TRANSLATOR_SETTINGS_FILE'])
        profile_file = Path(env['BATCH_LAYOUT_PROFILE'])
        self.api._adapt_controller_event(ControllerEvent('process_completed', {}))
        self.assertFalse(settings_file.exists())
        self.assertFalse(profile_file.exists())
        self.assertIsNone(self.api._snapshot_path)

    def test_login_ignores_layout_even_with_invalid_profile(self):
        self.enable(layout_profile_path=str(self.root / 'missing.json'))
        with patch.dict('os.environ', {'BATCH_LAYOUT_PROFILE': 'inherited.json'}):
            response = self.api.login_account(self.api.settings['active_chatgpt_account_id'])
        self.assertTrue(response['ok'], response)
        env = self.factory.calls[-1][1]['env']
        self.assertEqual(env['RUN_MODE'], 'login')
        self.assertNotIn('BATCH_LAYOUT_PROFILE', env)
        self.assertEqual(list((self.root / 'run_configs').glob('*.layout.json')), [])

    def test_gemini_ignores_layout_even_with_invalid_profile(self):
        self.enable(layout_profile_path=str(self.root / 'missing.json'), service='gemini')
        with patch.dict('os.environ', {'BATCH_LAYOUT_PROFILE': 'inherited.json'}):
            env = self.launch()
        self.assertEqual(env['SERVICE'], 'gemini')
        self.assertNotIn('BATCH_LAYOUT_PROFILE', env)
        self.assertEqual(list((self.root / 'run_configs').glob('*.layout.json')), [])

    def test_launch_builder_requires_prepared_companion_when_enabled(self):
        settings = dict(self.api.settings, layout_consistency_enabled=True)
        with self.assertRaises(ValueError):
            build_process_launch(settings, 'main', app_dir=ROOT, environ={})
        with self.assertRaises(ValueError):
            build_process_launch(settings, 'main', app_dir=ROOT, environ={}, settings_file=self.root / 'run.json')

    def test_picker_cancel_and_json_filter_do_not_save_settings(self):
        picker = Mock(return_value=None)
        self.api._attach_window(types.SimpleNamespace(create_file_dialog=picker))
        fake_webview = types.SimpleNamespace(FileDialog=types.SimpleNamespace(OPEN='open'))
        with patch.dict(sys.modules, {'webview': fake_webview}):
            response = WebBridge(self.api).choose_layout_profile()
            self.assertEqual(response, {'ok': True, 'data': {'path': None, 'cancelled': True}})
            picker.assert_called_with('open', allow_multiple=False, file_types=('Layout profile (*.json)',))
            picker.return_value = [str(self.root / 'approved.JSON')]
            self.assertEqual(self.api.choose_layout_profile()['data']['path'], picker.return_value[0])
            picker.return_value = [str(self.root / 'program.exe')]
            self.assertFalse(self.api.choose_layout_profile()['ok'])
        self.assertEqual(self.api.settings['layout_profile_path'], '')
        self.assertFalse(self.api.settings_path.exists())


class LayoutSessionIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.factories = {}
        self.registry = patch('resource_guard.registry_dir', return_value=self.root / 'locks')
        self.registry.start()
        def factory(**kwargs):
            scheduler, process_factory = FakeScheduler(), Factory()
            self.factories[kwargs['session_id']] = process_factory
            controller = DesktopController(scheduler, popen_factory=process_factory,
                thread_factory=FakeThread, process_tree_terminator=lambda pid: None)
            api = WebApi(controller=controller, scheduler=scheduler, **kwargs)
            api._request_folder_progress = Mock(return_value={'done': 0, 'total': 0})
            return api
        self.manager = SessionManager(app_dir=ROOT, data_dir=self.root, api_factory=factory)
        self.bridge = WebBridge(self.manager)
        for book, api in self.manager.sessions.items():
            source = self.root / (book + '-source')
            source.mkdir()
            api.settings.update(image_folder=str(source), download_folder=str(self.root / (book + '-output')))

    def tearDown(self):
        for factory in self.factories.values():
            for process in factory.processes:
                process.return_code = 0
        self.manager._shutdown()
        self.registry.stop()
        self.temp.cleanup()

    def test_one_book_toggle_does_not_change_other_books(self):
        before = {book: deepcopy(api.settings) for book, api in self.manager.sessions.items()}
        disk_before = {book: api.settings_path.read_bytes() if api.settings_path.exists() else None
                       for book, api in self.manager.sessions.items()}
        response = self.bridge.save_settings({'layout_consistency_enabled': True}, 'book-3')
        self.assertTrue(response['ok'], response)
        for book in ('book-1', 'book-2', 'book-4'):
            api = self.manager.sessions[book]
            self.assertEqual(api.settings, before[book])
            disk_after = api.settings_path.read_bytes() if api.settings_path.exists() else None
            self.assertEqual(disk_after, disk_before[book])
        for book in ('book-1', 'book-3'):
            result = self.bridge.start_batch('main', book)
            self.assertTrue(result['ok'], result)
        first = self.factories['book-1'].calls[-1][1]['env']
        third = self.factories['book-3'].calls[-1][1]['env']
        self.assertNotIn('BATCH_LAYOUT_PROFILE', first)
        self.assertEqual(third['BATCH_TRANSLATOR_WORKER_VARIANT'], 'books34')
        profile = load_profile(third['BATCH_LAYOUT_PROFILE'])
        self.assertEqual(profile.output_dir, self.root / 'book-3-output' / 'layout_results')

    def test_enabled_books_get_distinct_profiles_and_output_folders(self):
        paths, output_dirs = [], []
        for book in self.manager.sessions:
            self.assertTrue(self.bridge.save_settings({'layout_consistency_enabled': True}, book)['ok'])
            result = self.bridge.start_batch('main', book)
            self.assertTrue(result['ok'], result)
            env = self.factories[book].calls[-1][1]['env']
            paths.append(env['BATCH_LAYOUT_PROFILE'])
            output_dirs.append(load_profile(paths[-1]).output_dir)
        self.assertEqual(len(set(paths)), 4)
        self.assertEqual(len(set(output_dirs)), 4)

    def test_running_book_rejects_toggle_change(self):
        self.assertTrue(self.bridge.start_batch('main', 'book-2')['ok'])
        result = self.bridge.save_settings({'layout_consistency_enabled': True}, 'book-2')
        self.assertFalse(result['ok'])
        self.assertFalse(self.manager.sessions['book-2'].settings['layout_consistency_enabled'])

    def test_picker_routes_to_book_without_holding_dispatch_lock(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def dialog():
            entered.set()
            release.wait(3)
            return {'ok': True, 'data': {'path': 'book3.json', 'cancelled': False}}
        api = self.manager.sessions['book-3']
        with patch.object(api, 'choose_layout_profile', side_effect=dialog) as picker:
            results = []
            thread = threading.Thread(target=lambda: results.append(self.bridge.choose_layout_profile('book-3')))
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                def take_lock():
                    with self.manager._lock:
                        finished.set()
                dispatch = threading.Thread(target=take_lock)
                dispatch.start()
                self.assertTrue(finished.wait(1), 'native picker must not block other book events')
                dispatch.join(2)
            finally:
                release.set()
                thread.join(3)
            picker.assert_called_once_with()
            self.assertEqual(results[0]['data']['path'], 'book3.json')
        self.assertFalse(self.bridge.choose_layout_profile('unknown-book')['ok'])


if __name__ == '__main__':
    unittest.main()
