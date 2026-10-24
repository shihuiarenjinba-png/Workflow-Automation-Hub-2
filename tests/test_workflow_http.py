from __future__ import annotations

import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from workflow_hub import Runner, WorkflowError, _RejectRedirectHandler


class _RedirectingOpener:
    def open(self, request, timeout=30):
        raise urllib.error.HTTPError(request.full_url, 302, "Found", {"Location": "https://evil.example/"}, None)


class WorkflowHttpTests(unittest.TestCase):
    def test_redirect_handler_never_follows(self) -> None:
        handler = _RejectRedirectHandler()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example/"))

    def test_http_action_rejects_redirect_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = Runner({"base_dir": tmp, "allow_hosts": ["allowed.example"], "workflow": [{"action": "write_text", "path": "x.txt"}]})
            with patch("workflow_hub.urllib.request.build_opener", return_value=_RedirectingOpener()):
                with self.assertRaisesRegex(WorkflowError, "Redirect responses are not allowed"):
                    runner._http_request({"url": "https://allowed.example/start", "method": "GET"})

    def test_dry_run_still_performs_no_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = Runner({"base_dir": tmp, "allow_hosts": ["allowed.example"], "workflow": [{"action": "write_text", "path": "x.txt"}]}, dry_run=True)
            with patch("workflow_hub.urllib.request.build_opener") as build_opener:
                runner._http_request({"url": "https://allowed.example/start", "method": "GET"})
                build_opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
