import unittest
from unittest.mock import patch, MagicMock

from src.scheduler import start_scheduler


class TestStartScheduler(unittest.TestCase):

    @patch('src.scheduler.run_cycle')
    @patch('src.scheduler.BlockingScheduler')
    def test_creates_scheduler(self, mock_scheduler_cls, mock_run_cycle):
        mock_scheduler = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler

        start_scheduler(60, [], 'test.db', 10, 3)

        mock_scheduler_cls.assert_called_once()

    @patch('src.scheduler.run_cycle')
    @patch('src.scheduler.BlockingScheduler')
    def test_adds_interval_job(self, mock_scheduler_cls, mock_run_cycle):
        mock_scheduler = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler

        start_scheduler(60, [], 'test.db', 10, 3)

        mock_scheduler.add_job.assert_called_once()
        args, kwargs = mock_scheduler.add_job.call_args
        self.assertEqual(args[0], mock_run_cycle)
        self.assertEqual(args[1], 'interval')
        self.assertEqual(kwargs['seconds'], 60)
        self.assertEqual(kwargs['args'], ([], 'test.db', 10, 3))
        self.assertEqual(kwargs['max_instances'], 1)
        self.assertEqual(kwargs['misfire_grace_time'], 30)

    @patch('src.scheduler.run_cycle')
    @patch('src.scheduler.BlockingScheduler')
    def test_fires_initial_cycle(self, mock_scheduler_cls, mock_run_cycle):
        mock_scheduler = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler

        start_scheduler(60, [], 'test.db', 10, 3)

        mock_run_cycle.assert_called_once_with([], 'test.db', 10, 3)

    @patch('src.scheduler.run_cycle')
    @patch('src.scheduler.BlockingScheduler')
    def test_calls_scheduler_start(self, mock_scheduler_cls, mock_run_cycle):
        mock_scheduler = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler

        start_scheduler(60, [], 'test.db', 10, 3)

        mock_scheduler.start.assert_called_once()

    @patch('src.scheduler.logger')
    @patch('src.scheduler.run_cycle')
    @patch('src.scheduler.BlockingScheduler')
    def test_handles_keyboard_interrupt(self, mock_scheduler_cls, mock_run_cycle, mock_logger):
        mock_scheduler = MagicMock()
        mock_scheduler.start.side_effect = KeyboardInterrupt
        mock_scheduler_cls.return_value = mock_scheduler

        start_scheduler(60, [], 'test.db', 10, 3)

        mock_scheduler.shutdown.assert_called_once()
        mock_logger.info.assert_called()

    @patch('src.scheduler.run_cycle')
    @patch('src.scheduler.BlockingScheduler')
    def test_passes_custom_interval(self, mock_scheduler_cls, mock_run_cycle):
        mock_scheduler = MagicMock()
        mock_scheduler_cls.return_value = mock_scheduler

        start_scheduler(120, [], 'test.db', 10, 3)

        args, kwargs = mock_scheduler.add_job.call_args
        self.assertEqual(kwargs['seconds'], 120)


if __name__ == '__main__':
    unittest.main()
