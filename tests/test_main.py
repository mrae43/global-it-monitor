import unittest
from unittest.mock import patch, MagicMock

from src.main import main


class TestMain(unittest.TestCase):

    @patch('src.main.start_scheduler')
    @patch('src.main.init_database')
    @patch('src.main.load_config')
    @patch('src.main.validate_alert_config')
    @patch('src.main.logger')
    @patch('src.main.os.makedirs')
    def test_successful_run(self, mock_makedirs, mock_logger, mock_validate_alert_config, mock_load_config, mock_init_db, mock_start_scheduler):
        mock_load_config.return_value = {
            'db_path': 'data/monitor.db',
            'log_level': 'INFO',
            'interval': 60,
            'hosts': [{'label': 'H', 'host': '1.1.1.1', 'ports': [80]}],
            'max_workers': 20,
            'probe_timeout': 3,
            'warning_threshold': 3,
            'critical_threshold': 5,
            'flap_transitions': 3,
            'flap_window_minutes': 10,
            'stabilisation_threshold': 3,
        }

        main()

        mock_load_config.assert_called_once()
        mock_validate_alert_config.assert_called_once()
        mock_init_db.assert_called_once_with('data/monitor.db')
        mock_makedirs.assert_called_once_with('logs', exist_ok=True)
        mock_logger.add.assert_called_once()
        mock_start_scheduler.assert_called_once_with(mock_load_config.return_value)

    @patch('src.main.logger')
    @patch('src.main.load_config')
    def test_config_load_failure(self, mock_load_config, mock_logger):
        mock_load_config.side_effect = Exception('config broken')
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 1)
        mock_logger.error.assert_called_once()

    @patch('src.main.logger')
    @patch('src.main.validate_alert_config')
    @patch('src.main.init_database')
    @patch('src.main.load_config')
    def test_db_init_failure(self, mock_load_config, mock_init_db, mock_validate_alert_config, mock_logger):
        mock_load_config.return_value = {
            'db_path': 'data/monitor.db',
            'log_level': 'INFO',
            'interval': 60,
            'hosts': [],
            'max_workers': 20,
            'probe_timeout': 3,
            'warning_threshold': 3,
            'critical_threshold': 5,
            'flap_transitions': 3,
            'flap_window_minutes': 10,
            'stabilisation_threshold': 3,
        }
        mock_init_db.side_effect = Exception('db locked')
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 1)
        mock_logger.error.assert_called_once()

    @patch('src.main.logger')
    @patch('src.main.validate_alert_config')
    @patch('src.main.load_config')
    def test_alert_config_invalid(self, mock_load_config, mock_validate_alert_config, mock_logger):
        mock_load_config.return_value = {
            'db_path': 'data/monitor.db',
            'log_level': 'INFO',
            'interval': 60,
            'hosts': [],
            'max_workers': 20,
            'probe_timeout': 3,
            'warning_threshold': 5,
            'critical_threshold': 3,
            'flap_transitions': 3,
            'flap_window_minutes': 10,
            'stabilisation_threshold': 3,
        }
        mock_validate_alert_config.side_effect = ValueError('CRITICAL_THRESHOLD (3) must be greater than WARNING_THRESHOLD (5)')
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertEqual(cm.exception.code, 1)
        mock_logger.error.assert_called_once()


if __name__ == '__main__':
    unittest.main()
