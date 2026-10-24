import json
import tempfile
import unittest
from pathlib import Path

from automation_hub.google_blogger import GoogleBloggerConnector, GoogleBloggerError, load_google_desktop_client_file, validate_google_desktop_client_config


VALID = {
    'installed': {
        'client_id': '1234567890-abcdef.apps.googleusercontent.com',
        'project_id': 'example-project',
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
        'client_secret': 'not-a-real-secret',
        'redirect_uris': ['http://localhost'],
    }
}


class FakeVault:
    def __init__(self, text=None):
        self.text = text

    def exists(self):
        return self.text is not None

    def load_text(self):
        return self.text

    def save_text(self, text):
        self.text = text

    def delete(self):
        self.text = None


class GoogleOAuthConfigTests(unittest.TestCase):
    def test_valid_desktop_config(self):
        metadata = validate_google_desktop_client_config(VALID)
        self.assertEqual(metadata.project_id, 'example-project')

    def test_redirect_uris_may_be_absent_for_desktop_client(self):
        config = json.loads(json.dumps(VALID))
        del config['installed']['redirect_uris']
        metadata = validate_google_desktop_client_config(config)
        self.assertTrue(metadata.client_id.endswith('.apps.googleusercontent.com'))

    def test_known_legacy_google_token_endpoint_is_accepted(self):
        config = json.loads(json.dumps(VALID))
        config['installed']['token_uri'] = 'https://accounts.google.com/o/oauth2/token'
        metadata = validate_google_desktop_client_config(config)
        self.assertEqual(metadata.project_id, 'example-project')

    def test_rejects_web_application_json(self):
        with self.assertRaises(GoogleBloggerError):
            validate_google_desktop_client_config({'web': dict(VALID['installed'])})

    def test_rejects_remote_redirect(self):
        config = json.loads(json.dumps(VALID))
        config['installed']['redirect_uris'] = ['https://example.com/callback']
        with self.assertRaises(GoogleBloggerError):
            validate_google_desktop_client_config(config)

    def test_loader_rejects_oversized_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'client.json'
            path.write_text(' ' * (70 * 1024), encoding='utf-8')
            with self.assertRaises(GoogleBloggerError):
                load_google_desktop_client_file(path)

    def test_import_replaces_token_when_client_id_changes(self):
        old_token = json.dumps({'client_id': 'old.apps.googleusercontent.com'})
        token_vault = FakeVault(old_token)
        client_vault = FakeVault()
        connector = GoogleBloggerConnector(token_vault=token_vault, client_vault=client_vault)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'credentials.json'
            path.write_text(json.dumps(VALID), encoding='utf-8')
            result = connector.import_client_config(path)
        self.assertTrue(result.token_reset)
        self.assertIsNone(token_vault.text)
        self.assertIsNotNone(client_vault.text)

    def test_import_keeps_token_for_same_client_and_no_longer_needs_source_file(self):
        client_id = VALID['installed']['client_id']
        token_vault = FakeVault(json.dumps({'client_id': client_id}))
        client_vault = FakeVault()
        connector = GoogleBloggerConnector(token_vault=token_vault, client_vault=client_vault)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'credentials.json'
            path.write_text(json.dumps(VALID), encoding='utf-8')
            result = connector.import_client_config(path)
            path.unlink()
            metadata = connector.client_metadata()
        self.assertFalse(result.token_reset)
        self.assertIsNotNone(token_vault.text)
        self.assertEqual(metadata.client_id, client_id)


if __name__ == '__main__':
    unittest.main()
