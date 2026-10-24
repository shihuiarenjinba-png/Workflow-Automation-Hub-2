import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path

from automation_hub.blogger_automation import insert_link_once, run_link_job
from automation_hub.models import BloggerLinkJob


class FakeConnector:
    def __init__(self, posts):
        self.posts = posts
        self.patched = []

    def list_posts(self, blog_id, status='LIVE', max_posts=50):
        return self.posts[:max_posts]

    def patch_post_content(self, blog_id, post_id, content):
        self.patched.append((blog_id, post_id, content))
        return {'id': post_id}


class NullAudit:
    def write(self, event, **fields):
        pass


class BloggerAutomationTests(unittest.TestCase):
    def setUp(self):
        self.job = BloggerLinkJob(id='j1', name='test', blog_id='b1', target_text='target', link_url='https://example.com', anchor_text='target')

    def test_inserts_first_visible_match_without_reformatting_other_html(self):
        source = '<DIV class="X"><p data-z="1">Hello target world</p><BR/></DIV>'
        result = insert_link_once(source, 'target', 'https://example.com/a?x=1&y=2', 'Read & Go')
        self.assertTrue(result.changed)
        self.assertEqual(
            result.html,
            '<DIV class="X"><p data-z="1">Hello <a href="https://example.com/a?x=1&amp;y=2">Read &amp; Go</a> world</p><BR/></DIV>',
        )

    def test_skips_if_url_already_present_and_returns_original_bytes(self):
        html = '<P><a href="https://example.com/a">Existing</a> target</P>'
        result = insert_link_once(html, 'target', 'https://example.com/a', 'Read')
        self.assertFalse(result.changed)
        self.assertEqual(result.reason, 'link_already_present')
        self.assertEqual(result.html, html)

    def test_does_not_replace_inside_nested_existing_link(self):
        html = '<p><a href="https://other.example/"><span>target</span></a></p>'
        result = insert_link_once(html, 'target', 'https://example.com/a', 'Read')
        self.assertFalse(result.changed)
        self.assertEqual(result.reason, 'target_not_found')
        self.assertEqual(result.html, html)

    def test_does_not_guess_across_html_entity(self):
        html = '<p>A &amp; B</p>'
        result = insert_link_once(html, 'A & B', 'https://example.com/a', 'Read')
        self.assertFalse(result.changed)
        self.assertEqual(result.html, html)

    def test_dry_run_never_patches_or_writes_backup(self):
        connector = FakeConnector([{'id': '1', 'content': '<p>target</p>'}])
        with tempfile.TemporaryDirectory() as td:
            backup_root = Path(td) / 'backups'
            result = run_link_job(connector, self.job, dry_run=True, audit=NullAudit(), backup_root=backup_root, execution_lock=nullcontext())
            self.assertEqual(result.changed, 1)
            self.assertEqual(connector.patched, [])
            self.assertFalse(backup_root.exists())

    def test_live_run_backs_up_original_before_patch(self):
        original = '<p>target original</p>'
        connector = FakeConnector([{'id': '1', 'title': 'Title', 'url': 'https://blog.example/p', 'content': original}])
        with tempfile.TemporaryDirectory() as td:
            backup_root = Path(td) / 'backups'
            result = run_link_job(connector, self.job, dry_run=False, audit=NullAudit(), backup_root=backup_root, execution_lock=nullcontext())
            self.assertEqual(result.changed, 1)
            self.assertEqual(len(connector.patched), 1)
            files = list(backup_root.glob('*.json'))
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text(encoding='utf-8'))
            self.assertEqual(payload['original_content'], original)

    def test_backup_failure_prevents_remote_patch(self):
        connector = FakeConnector([{'id': '1', 'content': '<p>target</p>'}])
        with tempfile.TemporaryDirectory() as td:
            not_a_directory = Path(td) / 'file'
            not_a_directory.write_text('x', encoding='utf-8')
            with self.assertRaises(OSError):
                run_link_job(connector, self.job, dry_run=False, audit=NullAudit(), backup_root=not_a_directory, execution_lock=nullcontext())
            self.assertEqual(connector.patched, [])


if __name__ == '__main__':
    unittest.main()
