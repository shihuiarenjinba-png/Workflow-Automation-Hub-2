import json
import tempfile
import unittest
from pathlib import Path

from automation_hub.settings import SettingsStore


class SettingsTests(unittest.TestCase):
    def test_corrupt_settings_are_quarantined(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'settings.json'
            path.write_text('{bad json', encoding='utf-8')
            store = SettingsStore(path)
            data = store.load()
            self.assertEqual(data['locale'], 'ja')
            self.assertFalse(path.exists())
            self.assertEqual(len(list(Path(td).glob('settings.json.corrupt-*'))), 1)

    def test_save_does_not_persist_unknown_secret_like_fields(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'settings.json'
            SettingsStore(path).save({'locale': 'en', 'api_key': 'SECRET', 'google_client_id_hint': 'hint'})
            raw = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(raw['locale'], 'en')
            self.assertNotIn('api_key', raw)


if __name__ == '__main__':
    unittest.main()
