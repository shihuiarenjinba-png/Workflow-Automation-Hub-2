import tempfile
import unittest
from pathlib import Path

from automation_hub.jobs import JobStore
from automation_hub.models import BloggerLinkJob


class JobStoreTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            store = JobStore(Path(td) / 'jobs.json')
            job = BloggerLinkJob(id='abc', name='A', blog_id='1', target_text='x', link_url='https://example.com', anchor_text='x')
            store.upsert(job)
            self.assertEqual(store.get('abc').name, 'A')
            store.delete('abc')
            self.assertEqual(store.load_all(), [])


if __name__ == '__main__':
    unittest.main()
