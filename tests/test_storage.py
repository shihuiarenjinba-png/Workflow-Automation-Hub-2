import os
import tempfile
import unittest
from pathlib import Path

from automation_hub.storage import DPAPITokenVault


@unittest.skipUnless(os.name == "nt", "Windows DPAPI test")
class DPAPITokenVaultTests(unittest.TestCase):
    def test_round_trip_is_encrypted_and_deletable(self):
        secret = "refresh-token-test-秘密"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "token.dpapi"
            vault = DPAPITokenVault(path)
            vault.save_text(secret)
            self.assertTrue(path.exists())
            self.assertNotIn(secret.encode("utf-8"), path.read_bytes())
            self.assertEqual(vault.load_text(), secret)
            vault.delete()
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
