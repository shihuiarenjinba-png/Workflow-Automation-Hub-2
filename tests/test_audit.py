import json
import tempfile
import unittest
from pathlib import Path

from automation_hub.audit import AuditLogger, REDACTED


class AuditTests(unittest.TestCase):
    def test_sensitive_fields_and_text_are_redacted(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'audit.jsonl'
            logger = AuditLogger(path)
            logger.write(
                'error',
                refresh_token='REFRESH-SECRET',
                nested={'password': 'PASS-SECRET'},
                detail='Authorization: Bearer abc.def.ghi refresh_token=TOKEN-SECRET',
            )
            row = json.loads(path.read_text(encoding='utf-8').strip())
            self.assertEqual(row['refresh_token'], REDACTED)
            self.assertEqual(row['nested']['password'], REDACTED)
            self.assertNotIn('REFRESH-SECRET', path.read_text(encoding='utf-8'))
            self.assertNotIn('PASS-SECRET', path.read_text(encoding='utf-8'))
            self.assertNotIn('abc.def.ghi', row['detail'])
            self.assertNotIn('TOKEN-SECRET', row['detail'])


if __name__ == '__main__':
    unittest.main()
