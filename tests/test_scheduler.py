import unittest
from unittest.mock import patch

from automation_hub.models import BloggerLinkJob, ModelValidationError, ScheduleSpec
from automation_hub.scheduler import SchedulerError, build_create_args, task_name, validate_time


class SchedulerTests(unittest.TestCase):
    def test_daily_args_are_fixed_interactive_limited_runner(self):
        job = BloggerLinkJob(id='job-1', name='x', blog_id='b', target_text='x', link_url='https://example.com', anchor_text='x', schedule=ScheduleSpec(kind='daily', time='08:30'))
        with patch('automation_hub.scheduler.sys.executable', r'C:\Python Files\python.exe'):
            args = build_create_args(job)
        self.assertEqual(args[0], 'schtasks')
        self.assertIn('/RL', args)
        self.assertIn('LIMITED', args)
        self.assertIn('/IT', args)
        command = args[args.index('/TR') + 1]
        self.assertIn('--run-job', command)
        self.assertIn('job-1', command)
        self.assertNotIn('powershell', command.lower())
        self.assertNotIn('cmd.exe', command.lower())

    def test_weekly_requires_day_at_model_boundary(self):
        with self.assertRaises(ModelValidationError):
            ScheduleSpec(kind='weekly', time='08:00', weekdays=[])

    def test_time_validation(self):
        self.assertEqual(validate_time('23:59'), '23:59')
        with self.assertRaises(ModelValidationError):
            validate_time('24:00')

    def test_task_name_rejects_unsafe_id_instead_of_sanitizing(self):
        with self.assertRaises(ModelValidationError):
            task_name('a b/c')

    def test_disabled_job_cannot_be_registered(self):
        job = BloggerLinkJob(id='j1', name='x', blog_id='b', target_text='x', link_url='https://example.com', anchor_text='x', enabled=False)
        with self.assertRaises(SchedulerError):
            build_create_args(job)


if __name__ == '__main__':
    unittest.main()
