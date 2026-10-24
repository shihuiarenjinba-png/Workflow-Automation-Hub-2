"""Headless UI contract checks for guide copy and fail-closed controls."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "automation_hub" / "gui.py"
TRANSLATIONS = ROOT / "resources" / "i18n"
REQUIRED = {
    "tab_home", "home_title", "home_what", "home_example",
    "home_connect_title", "home_connect_help", "home_connect_action",
    "home_job_title", "home_job_help", "home_job_action",
    "home_preview_title", "home_preview_help", "home_preview_action",
    "home_state_api_verified", "oauth_saved_unverified",
    "home_state_config_missing", "home_state_auth_missing", "home_state_auth_present",
    "home_state_jobs_missing", "home_state_jobs_ready", "home_state_jobs_error",
    "home_state_preview_needed", "home_state_preview_done",
    "save_changes_first", "preview_required_before_live", "confirm_discard_edits",
    "preview_required_before_schedule", "confirm_schedule_changes",
    "job_effect_title", "job_effect_missing", "job_effect_template",
    "google_first_setup", "google_management", "google_first_setup_tip",
}


class GuidedGuiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ast.parse(GUI.read_text(encoding="utf-8"), filename=str(GUI))
        cls.gui_class = next(
            node for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "AutomationHubGUI"
        )
        cls.methods = {
            node.name: node
            for node in cls.gui_class.body if isinstance(node, ast.FunctionDef)
        }

    def _calls(self, method: str) -> set[str]:
        names = set()
        for node in ast.walk(self.methods[method]):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    names.add(fn.id)
                elif isinstance(fn, ast.Attribute):
                    names.add(fn.attr)
        return names

    def test_python_gui_source_parses(self) -> None:
        self.assertIn("build_ui", self.methods)

    def test_beginner_home_is_constructed(self) -> None:
        self.assertIn("_build_home_tab", self._calls("build_ui"))
        self.assertIn("home_tab", ast.unparse(self.methods["build_ui"]))

    def test_preview_and_unsaved_validation_precede_live_run(self) -> None:
        calls = self._calls("run_job")
        self.assertTrue({"needs_save", "live_run_ready", "run_async"}.issubset(calls))

    def test_schedule_has_own_selection_and_approval(self) -> None:
        method = ast.unparse(self.methods["on_schedule_job_select"])
        self.assertIn("selected_schedule_job_id", method)
        self.assertNotIn("self.selected_job_id =", method)
        self.assertIn("job_revision", self._calls("register_schedule"))
        self.assertIn("askyesno", self._calls("register_schedule"))

    def test_unsaved_edits_are_preserved_on_language_change(self) -> None:
        method = ast.unparse(self.methods["on_language_change"])
        self.assertIn("fields", method)
        self.assertIn("notebook.select", method)

    def test_dirty_switch_prompts_instead_of_discarding(self) -> None:
        self.assertIn("_confirm_discard_input", self._calls("on_job_select"))
        self.assertIn("_restore_list_selection", self._calls("on_job_select"))

    def test_oauth_presence_is_not_called_verified(self) -> None:
        method = ast.unparse(self.methods["_google_status_text"])
        self.assertIn("google_verified", method)
        self.assertIn("oauth_saved_unverified", method)

    def test_both_languages_have_all_guidance(self) -> None:
        for name in ("ja", "en"):
            with self.subTest(name=name):
                values = json.loads((TRANSLATIONS / (name + ".json")).read_text(encoding="utf-8"))
                missing = REQUIRED - set(values)
                self.assertFalse(missing, f"Missing keys: {missing}")
                self.assertTrue(all(isinstance(values[k], str) and values[k].strip() for k in REQUIRED))

    def test_languages_have_identical_keys(self) -> None:
        ja = json.loads((TRANSLATIONS / "ja.json").read_text(encoding="utf-8"))
        en = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
        self.assertEqual(set(ja), set(en))


if __name__ == "__main__":
    unittest.main()
