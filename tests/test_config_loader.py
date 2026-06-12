import os
import tempfile
import unittest
from unittest.mock import patch

from src.config.loader import load_env, load_hosts, load_config, validate_alert_config


class TestLoadEnv(unittest.TestCase):

    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_defaults_when_no_env_vars(self):
        config = load_env()
        self.assertEqual(config['db_path'], 'data/monitor.db')
        self.assertEqual(config['interval'], 60)
        self.assertEqual(config['log_level'], 'INFO')
        self.assertEqual(config['max_workers'], 20)
        self.assertEqual(config['probe_timeout'], 3)
        self.assertEqual(config['warning_threshold'], 3)
        self.assertEqual(config['critical_threshold'], 5)
        self.assertEqual(config['flap_transitions'], 3)
        self.assertEqual(config['flap_window_minutes'], 10)
        self.assertEqual(config['stabilisation_threshold'], 3)

    def test_reads_custom_env_vars(self):
        os.environ['MONITOR_DB_PATH'] = 'custom.db'
        os.environ['MONITOR_INTERVAL_SECONDS'] = '120'
        os.environ['MONITOR_LOG_LEVEL'] = 'DEBUG'
        os.environ['MONITOR_MAX_WORKERS'] = '10'
        os.environ['MONITOR_PROBE_TIMEOUT'] = '5'
        os.environ['MONITOR_WARNING_THRESHOLD'] = '4'
        os.environ['MONITOR_CRITICAL_THRESHOLD'] = '7'
        os.environ['MONITOR_FLAP_TRANSITIONS'] = '4'
        os.environ['MONITOR_FLAP_WINDOW_MINUTES'] = '15'
        os.environ['MONITOR_STABILISATION_THRESHOLD'] = '4'
        config = load_env()
        self.assertEqual(config['db_path'], 'custom.db')
        self.assertEqual(config['interval'], 120)
        self.assertEqual(config['log_level'], 'DEBUG')
        self.assertEqual(config['max_workers'], 10)
        self.assertEqual(config['probe_timeout'], 5)
        self.assertEqual(config['warning_threshold'], 4)
        self.assertEqual(config['critical_threshold'], 7)
        self.assertEqual(config['flap_transitions'], 4)
        self.assertEqual(config['flap_window_minutes'], 15)
        self.assertEqual(config['stabilisation_threshold'], 4)

    def test_type_casts_integers(self):
        os.environ['MONITOR_INTERVAL_SECONDS'] = '90'
        os.environ['MONITOR_MAX_WORKERS'] = '5'
        os.environ['MONITOR_PROBE_TIMEOUT'] = '1'
        os.environ['MONITOR_WARNING_THRESHOLD'] = '2'
        os.environ['MONITOR_CRITICAL_THRESHOLD'] = '4'
        os.environ['MONITOR_FLAP_TRANSITIONS'] = '2'
        os.environ['MONITOR_FLAP_WINDOW_MINUTES'] = '5'
        os.environ['MONITOR_STABILISATION_THRESHOLD'] = '2'
        config = load_env()
        self.assertIsInstance(config['interval'], int)
        self.assertIsInstance(config['max_workers'], int)
        self.assertIsInstance(config['probe_timeout'], int)
        self.assertIsInstance(config['warning_threshold'], int)
        self.assertIsInstance(config['critical_threshold'], int)
        self.assertIsInstance(config['flap_transitions'], int)
        self.assertIsInstance(config['flap_window_minutes'], int)
        self.assertIsInstance(config['stabilisation_threshold'], int)

    def test_load_dotenv_file_present(self):
        # The .env file in the repo has these values
        os.environ['MONITOR_DB_PATH'] = 'data/monitor.db'
        os.environ['MONITOR_LOG_LEVEL'] = 'INFO'
        os.environ['MONITOR_INTERVAL_SECONDS'] = '60'
        os.environ['MONITOR_MAX_WORKERS'] = '20'
        os.environ['MONITOR_PROBE_TIMEOUT'] = '3'
        os.environ['MONITOR_WARNING_THRESHOLD'] = '3'
        os.environ['MONITOR_CRITICAL_THRESHOLD'] = '5'
        os.environ['MONITOR_FLAP_TRANSITIONS'] = '3'
        os.environ['MONITOR_FLAP_WINDOW_MINUTES'] = '10'
        os.environ['MONITOR_STABILISATION_THRESHOLD'] = '3'
        config = load_env()
        self.assertEqual(config['db_path'], 'data/monitor.db')


class TestValidateAlertConfig(unittest.TestCase):

    def test_valid_config(self):
        config = {
            'warning_threshold': 3,
            'critical_threshold': 5,
            'flap_transitions': 3,
            'flap_window_minutes': 10,
            'stabilisation_threshold': 3,
        }
        validate_alert_config(config)

    def test_critical_less_than_warning(self):
        config = {
            'warning_threshold': 5,
            'critical_threshold': 3,
            'flap_transitions': 3,
            'flap_window_minutes': 10,
            'stabilisation_threshold': 3,
        }
        with self.assertRaises(ValueError) as cm:
            validate_alert_config(config)
        self.assertIn('CRITICAL_THRESHOLD', str(cm.exception))

    def test_critical_equal_warning(self):
        config = {
            'warning_threshold': 3,
            'critical_threshold': 3,
            'flap_transitions': 3,
            'flap_window_minutes': 10,
            'stabilisation_threshold': 3,
        }
        with self.assertRaises(ValueError) as cm:
            validate_alert_config(config)
        self.assertIn('CRITICAL_THRESHOLD', str(cm.exception))

    def test_flap_transitions_less_than_2(self):
        config = {
            'warning_threshold': 3,
            'critical_threshold': 5,
            'flap_transitions': 1,
            'flap_window_minutes': 10,
            'stabilisation_threshold': 3,
        }
        with self.assertRaises(ValueError) as cm:
            validate_alert_config(config)
        self.assertIn('FLAP_TRANSITIONS', str(cm.exception))

    def test_flap_window_minutes_zero(self):
        config = {
            'warning_threshold': 3,
            'critical_threshold': 5,
            'flap_transitions': 3,
            'flap_window_minutes': 0,
            'stabilisation_threshold': 3,
        }
        with self.assertRaises(ValueError) as cm:
            validate_alert_config(config)
        self.assertIn('FLAP_WINDOW_MINUTES', str(cm.exception))

    def test_stabilisation_threshold_zero(self):
        config = {
            'warning_threshold': 3,
            'critical_threshold': 5,
            'flap_transitions': 3,
            'flap_window_minutes': 10,
            'stabilisation_threshold': 0,
        }
        with self.assertRaises(ValueError) as cm:
            validate_alert_config(config)
        self.assertIn('STABILISATION_THRESHOLD', str(cm.exception))


class TestLoadHosts(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmp_dir, 'hosts.yaml')

    def tearDown(self):
        if os.path.exists(self.config_path):
            os.unlink(self.config_path)
        os.rmdir(self.tmp_dir)

    def _write_hosts(self, content):
        with open(self.config_path, 'w') as f:
            f.write(content)

    def test_valid_hosts(self):
        self._write_hosts("""
hosts:
  - label: "Test Host"
    host: "10.0.0.1"
    ports: [80, 443]
""")
        hosts = load_hosts(self.config_path)
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0]['label'], 'Test Host')
        self.assertEqual(hosts[0]['host'], '10.0.0.1')
        self.assertEqual(hosts[0]['ports'], [80, 443])

    def test_file_not_found(self):
        hosts = load_hosts('/nonexistent/path/hosts.yaml')
        self.assertEqual(hosts, [])

    def test_malformed_yaml(self):
        self._write_hosts("{not yaml: [[")
        hosts = load_hosts(self.config_path)
        self.assertEqual(hosts, [])

    def test_empty_yaml(self):
        self._write_hosts("")
        hosts = load_hosts(self.config_path)
        self.assertEqual(hosts, [])

    def test_no_hosts_key(self):
        self._write_hosts("other: []")
        hosts = load_hosts(self.config_path)
        self.assertEqual(hosts, [])

    def test_empty_hosts_list(self):
        self._write_hosts("hosts: []")
        hosts = load_hosts(self.config_path)
        self.assertEqual(hosts, [])

    def test_missing_label(self):
        self._write_hosts("""
hosts:
  - host: "10.0.0.1"
    ports: [80]
""")
        hosts = load_hosts(self.config_path)
        self.assertEqual(hosts, [])

    def test_missing_host(self):
        self._write_hosts("""
hosts:
  - label: "Test"
    ports: [80]
""")
        hosts = load_hosts(self.config_path)
        self.assertEqual(hosts, [])

    def test_invalid_ports_not_list(self):
        self._write_hosts("""
hosts:
  - label: "Test"
    host: "10.0.0.1"
    ports: "80"
""")
        hosts = load_hosts(self.config_path)
        self.assertEqual(hosts, [])

    def test_invalid_ports_not_all_ints(self):
        self._write_hosts("""
hosts:
  - label: "Test"
    host: "10.0.0.1"
    ports: [80, "443"]
""")
        hosts = load_hosts(self.config_path)
        self.assertEqual(hosts, [])

    def test_mixed_valid_and_invalid(self):
        self._write_hosts("""
hosts:
  - label: "Valid"
    host: "10.0.0.1"
    ports: [80]
  - label: "Invalid"
    host: "10.0.0.2"
    ports: "not a list"
  - label: "Also Valid"
    host: "10.0.0.3"
    ports: [443]
""")
        hosts = load_hosts(self.config_path)
        self.assertEqual(len(hosts), 2)
        self.assertEqual(hosts[0]['label'], 'Valid')
        self.assertEqual(hosts[1]['label'], 'Also Valid')

    def test_ports_empty_list(self):
        self._write_hosts("""
hosts:
  - label: "Test"
    host: "10.0.0.1"
    ports: []
""")
        hosts = load_hosts(self.config_path)
        self.assertEqual(hosts, [])


class TestLoadConfig(unittest.TestCase):

    def test_load_config_composes(self):
        with patch('src.config.loader.load_env') as mock_load_env, \
             patch('src.config.loader.load_hosts') as mock_load_hosts:
            mock_load_env.return_value = {'db_path': 'test.db'}
            mock_load_hosts.return_value = [{'label': 'H', 'host': '1.1.1.1', 'ports': [80]}]
            config = load_config()
            self.assertEqual(config['db_path'], 'test.db')
            self.assertEqual(config['hosts'], [{'label': 'H', 'host': '1.1.1.1', 'ports': [80]}])


if __name__ == '__main__':
    unittest.main()
