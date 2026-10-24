import unittest

from automation_hub.models import BloggerLinkJob, ModelValidationError, ScheduleSpec, validate_job_id


class ModelTests(unittest.TestCase):
    def test_safe_job_id_required(self):
        self.assertEqual(validate_job_id('abc-_.123'), 'abc-_.123')
        for bad in ['', 'a b', '../x', 'x/y']:
            with self.assertRaises(ModelValidationError):
                validate_job_id(bad)

    def test_weekly_requires_weekday(self):
        with self.assertRaises(ModelValidationError):
            ScheduleSpec(kind='weekly', time='08:00', weekdays=[])

    def test_max_posts_is_not_silently_clamped(self):
        with self.assertRaises(ModelValidationError):
            BloggerLinkJob(id='j1', name='x', blog_id='b', target_text='x', link_url='https://example.com', anchor_text='x', max_posts=999)

    def test_link_url_rejects_embedded_credentials(self):
        with self.assertRaises(ModelValidationError):
            BloggerLinkJob(id='j1', name='x', blog_id='b', target_text='x', link_url='https://u:p@example.com', anchor_text='x')


if __name__ == '__main__':
    unittest.main()
