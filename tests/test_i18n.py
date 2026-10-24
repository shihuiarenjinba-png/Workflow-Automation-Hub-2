import unittest

from automation_hub.i18n import tr


class I18nTests(unittest.TestCase):
    def test_both_languages(self):
        self.assertNotEqual(tr('ja', 'tab_jobs'), tr('en', 'tab_jobs'))
        self.assertIn('Workflow', tr('en', 'app_title'))

    def test_language_selector_label_is_always_bilingual(self):
        self.assertEqual(tr('ja', 'language'), '言語 / Language')
        self.assertEqual(tr('en', 'language'), '言語 / Language')


if __name__ == '__main__':
    unittest.main()
