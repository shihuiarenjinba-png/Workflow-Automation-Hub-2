import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation_hub.diagnostics import collect_diagnostics, format_diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_report_excludes_sensitive_environment_and_paths(self):
        with tempfile.TemporaryDirectory() as td:
            secret_user = "DO_NOT_LEAK_USERNAME_123"
            secret_path = str(Path(td) / secret_user)
            Path(secret_path).mkdir(parents=True)
            with patch.dict(os.environ, {"LOCALAPPDATA": secret_path, "USERNAME": secret_user}, clear=False):
                report = collect_diagnostics(include_self_test=False)
            rendered = format_diagnostics(report)
            self.assertNotIn(secret_user, rendered)
            self.assertNotIn(secret_path, rendered)
            self.assertFalse(report["privacy"]["contains_oauth_token"])
            self.assertFalse(report["privacy"]["contains_client_secret"])
            self.assertTrue(report["local_state"]["app_data_write"])

    def test_report_is_valid_json_and_has_support_fields(self):
        report = collect_diagnostics(include_self_test=False)
        payload = json.loads(format_diagnostics(report))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["product"], "Workflow Automation Hub")
        self.assertIn("executable_sha256", payload["runtime"])
        self.assertIn("architecture", payload["windows"])
        self.assertIsNone(payload["self_test"]["ok"])


if __name__ == "__main__":
    unittest.main()
