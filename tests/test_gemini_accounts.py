"""Saved Gemini accounts, legacy profile migration, and worker launch isolation."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from desktop.runtime import (apply_form_settings, copy_default_settings, get_active_account,
                             load_settings, make_default_settings, normalize_chatgpt_accounts)
from resource_guard import configured_profiles, canonical_path
import test_web_api as api_helpers


class GeminiAccountsTests(unittest.TestCase):
    setUp = api_helpers.WebApiTests.setUp
    tearDown = api_helpers.WebApiTests.tearDown

    def gemini(self):
        response = self.api.save_settings({"service": "gemini"})
        self.assertTrue(response["ok"], response)
        return self.api.settings["gemini_accounts"][0]

    def test_migration_keeps_existing_google_login_profile(self):
        profile = self.data_dir / "existing-google-profile"
        profile.mkdir()
        marker = profile / "login-marker"
        marker.write_bytes(b"existing login data")
        self.settings_path.write_text(json.dumps({"service": "gemini", "profile_dir": str(profile)}))
        restored = load_settings(self.settings_path, make_default_settings(self.data_dir))
        normalize_chatgpt_accounts(restored, self.data_dir)
        self.assertEqual(get_active_account(restored, self.data_dir)["profile_dir"], str(profile))
        self.assertEqual(restored["gemini_accounts"][0]["name"], "Gemini 1")
        self.assertNotEqual(restored["chatgpt_accounts"][0]["profile_dir"], str(profile))
        self.assertEqual(marker.read_bytes(), b"existing login data")

    def test_default_lists_are_copied_independently(self):
        defaults = make_default_settings(self.data_dir)
        copied = copy_default_settings(defaults)
        copied["gemini_accounts"][0]["name"] = "Changed"
        self.assertEqual(defaults["gemini_accounts"][0]["name"], "Gemini 1")

    def test_gemini_crud_persists_without_changing_chatgpt_or_deleting_profile(self):
        chatgpt = deepcopy(self.api.settings["chatgpt_accounts"])
        original = self.gemini().copy()
        added = self.api.add_account("Google cá nhân")
        self.assertTrue(added["ok"], added)
        account_id = added["data"]["active_id"]
        account = get_active_account(self.api.settings, self.data_dir)
        self.assertIn("gemini_auto_profile_", account["profile_dir"])
        self.assertNotEqual(account["profile_dir"], original["profile_dir"])
        profile = Path(account["profile_dir"])
        profile.mkdir()
        marker = profile / "login-marker"
        marker.write_bytes(b"keep login")
        self.assertTrue(self.api.rename_account(account_id, "Google công việc")["ok"])
        restored = load_settings(self.settings_path, make_default_settings(self.data_dir))
        self.assertEqual(get_active_account(restored, self.data_dir)["name"], "Google công việc")
        self.assertEqual(restored["active_gemini_account_id"], account_id)
        self.assertTrue(self.api.remove_account(account_id)["ok"])
        self.assertEqual(self.api.settings["gemini_profile_dir"], original["profile_dir"])
        self.assertEqual(self.api.settings["chatgpt_accounts"], chatgpt)
        self.assertEqual(marker.read_bytes(), b"keep login")
        self.assertFalse(self.api.remove_account(original["id"])["ok"])

    def test_services_can_use_same_names_and_default_ids(self):
        self.assertTrue(self.api.add_account("Personal")["ok"])
        chatgpt_id = self.api.settings["active_chatgpt_account_id"]
        self.gemini()
        self.assertTrue(self.api.add_account("Personal")["ok"])
        self.assertFalse(self.api.add_account("personal")["ok"])
        self.assertTrue(self.api.select_account("default")["ok"])
        self.assertEqual(self.api.settings["active_gemini_account_id"], "default")
        self.assertEqual(self.api.settings["active_chatgpt_account_id"], chatgpt_id)
        self.assertFalse(self.api.select_account(chatgpt_id)["ok"])

    def test_switch_service_does_not_copy_chatgpt_profile_into_gemini(self):
        chatgpt_profile = self.api.settings["profile_dir"]
        gemini = self.gemini()
        self.assertEqual(self.api.settings["profile_dir"], gemini["profile_dir"])
        self.assertNotEqual(self.api.settings["profile_dir"], chatgpt_profile)
        self.assertTrue(self.api.save_settings({"service": "chatgpt"})["ok"])
        self.assertEqual(self.api.settings["profile_dir"], chatgpt_profile)

    def test_profile_edit_changes_only_active_gemini_account(self):
        original = self.gemini().copy()
        self.api.add_account("Second")
        before = deepcopy(self.api.settings)
        profile = str(self.data_dir / "custom-google-profile")
        updated = apply_form_settings(self.api.settings, {"profile_dir": profile}, self.data_dir)
        self.assertEqual(self.api.settings, before)
        self.assertEqual(get_active_account(updated, self.data_dir)["profile_dir"], profile)
        self.assertEqual(updated["gemini_profile_dir"], profile)
        self.assertEqual(updated["gemini_accounts"][0], original)

    def test_signin_and_batch_launch_use_selected_gemini_profile(self):
        self.gemini()
        response = self.api.add_account("Work Google")
        account_id = response["data"]["active_id"]
        profile = get_active_account(self.api.settings, self.data_dir)["profile_dir"]
        login = self.api.login_account(account_id)
        self.assertTrue(login["ok"], login)
        env = self.factory.calls[-1][1]["env"]
        self.assertEqual(env["SERVICE"], "gemini")
        self.assertEqual(env["RUN_MODE"], "login")
        self.assertEqual(env["PROFILE_DIR"], profile)
        snapshot = json.loads(Path(env["BATCH_TRANSLATOR_SETTINGS_FILE"]).read_text())
        self.assertEqual(snapshot["active_gemini_account_id"], account_id)
        self.assertFalse(self.api.add_account("While running")["ok"])
        self.assertFalse(self.api.select_account("default")["ok"])
        self.api.stop_process()
        self.factory.processes[-1].return_code = 0
        self.api._dispatch_once()
        result = self.api.start_batch("main")
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.factory.calls[-1][1]["env"]["PROFILE_DIR"], profile)

    def test_inactive_gemini_profiles_are_in_resource_conflict_checks(self):
        original = self.gemini().copy()
        self.api.add_account("Second")
        profiles = configured_profiles(self.api.settings)
        self.assertIn(canonical_path(original["profile_dir"]), profiles)
        self.assertIn(canonical_path(self.api.settings["profile_dir"]), profiles)


if __name__ == "__main__":
    unittest.main()
