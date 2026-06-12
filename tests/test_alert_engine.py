import os
import tempfile
import unittest
from unittest.mock import patch

from src.storage.database import init_database, save_results, insert_alert, resolve_alert, get_open_alert_for_track
from src.monitor import evaluate_track, evaluate_alerts


class TestEvaluateTrack(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, 'test.db')
        init_database(self.db_path)
        self.config = {
            'warning_threshold': 3,
            'critical_threshold': 5,
            'flap_transitions': 3,
            'flap_window_minutes': 10,
            'stabilisation_threshold': 3,
        }

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self.tmp_dir)

    def _save_failure(self, host='8.8.8.8', check_type='ICMP', port=None, label='H'):
        save_results(self.db_path, [
            {'host_label': label, 'host_address': host, 'check_type': check_type, 'port': port, 'status': 'DOWN' if check_type == 'ICMP' else 'CLOSED', 'latency_ms': None}
        ])

    def _save_pass(self, host='8.8.8.8', check_type='ICMP', port=None, label='H'):
        save_results(self.db_path, [
            {'host_label': label, 'host_address': host, 'check_type': check_type, 'port': port, 'status': 'UP' if check_type == 'ICMP' else 'OPEN', 'latency_ms': 1.0}
        ])

    def test_no_alert_below_threshold(self):
        for _ in range(2):
            self._save_failure()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
        actions = evaluate_track(self.db_path, result, self.config)
        self.assertEqual(actions['fired'], [])
        self.assertEqual(actions['resolved'], 0)
        self.assertIsNone(get_open_alert_for_track(self.db_path, '8.8.8.8', 'ICMP', None))

    def test_warning_fires(self):
        for _ in range(3):
            self._save_failure()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
        actions = evaluate_track(self.db_path, result, self.config)
        self.assertEqual(actions['fired'], ['WARNING'])
        alert = get_open_alert_for_track(self.db_path, '8.8.8.8', 'ICMP', None)
        self.assertIsNotNone(alert)
        self.assertEqual(alert['severity'], 'WARNING')

    def test_critical_escalates_from_warning(self):
        for _ in range(3):
            self._save_failure()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
        evaluate_track(self.db_path, result, self.config)
        for _ in range(2):
            self._save_failure()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
        actions = evaluate_track(self.db_path, result, self.config)
        self.assertEqual(actions['escalated'], 1)
        self.assertEqual(actions['fired'], ['CRITICAL'])
        alert = get_open_alert_for_track(self.db_path, '8.8.8.8', 'ICMP', None)
        self.assertEqual(alert['severity'], 'CRITICAL')

    def test_critical_fires_directly(self):
        for _ in range(5):
            self._save_failure()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
        actions = evaluate_track(self.db_path, result, self.config)
        self.assertEqual(actions['fired'], ['CRITICAL'])
        self.assertEqual(actions['escalated'], 0)
        alert = get_open_alert_for_track(self.db_path, '8.8.8.8', 'ICMP', None)
        self.assertEqual(alert['severity'], 'CRITICAL')

    def test_auto_resolve(self):
        for _ in range(3):
            self._save_failure()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
        evaluate_track(self.db_path, result, self.config)
        self.assertIsNotNone(get_open_alert_for_track(self.db_path, '8.8.8.8', 'ICMP', None))
        # Pass resolves
        self._save_pass()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'UP'}
        actions = evaluate_track(self.db_path, result, self.config)
        self.assertEqual(actions['resolved'], 1)
        self.assertIsNone(get_open_alert_for_track(self.db_path, '8.8.8.8', 'ICMP', None))

    def test_no_double_warning(self):
        for _ in range(3):
            self._save_failure()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
        evaluate_track(self.db_path, result, self.config)
        # Same cycle again should not fire another warning
        actions = evaluate_track(self.db_path, result, self.config)
        self.assertEqual(actions['fired'], [])
        alerts = get_open_alert_for_track(self.db_path, '8.8.8.8', 'ICMP', None)
        self.assertIsNotNone(alerts)

    def test_flap_detection(self):
        # Create 3 warning + resolve cycles
        for i in range(3):
            for _ in range(3):
                self._save_failure()
            result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
            actions = evaluate_track(self.db_path, result, self.config)
            self.assertEqual(actions['fired'], ['WARNING'])
            self._save_pass()
            result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'UP'}
            actions = evaluate_track(self.db_path, result, self.config)
            if i == 2:
                # 3rd cycle's UP evaluation triggers flap detection (3 alert rows in window)
                self.assertEqual(actions['flapped'], 1)
        alert = get_open_alert_for_track(self.db_path, '8.8.8.8', 'ICMP', None)
        self.assertIsNotNone(alert)
        self.assertEqual(alert['severity'], 'FLAPPING')

    def test_stabilisation(self):
        # Enter flapping state
        for _ in range(3):
            for _ in range(3):
                self._save_failure()
            result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
            evaluate_track(self.db_path, result, self.config)
            self._save_pass()
            result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'UP'}
            evaluate_track(self.db_path, result, self.config)
        # 4th warning triggers flapping
        for _ in range(3):
            self._save_failure()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
        evaluate_track(self.db_path, result, self.config)
        # Now 3 consecutive passes
        for _ in range(3):
            self._save_pass()
            result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'UP'}
            actions = evaluate_track(self.db_path, result, self.config)
        self.assertEqual(actions['stabilised'], 1)
        self.assertIsNone(get_open_alert_for_track(self.db_path, '8.8.8.8', 'ICMP', None))

    def test_stabilisation_reset_by_failure(self):
        # Enter flapping
        for _ in range(3):
            for _ in range(3):
                self._save_failure()
            result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
            evaluate_track(self.db_path, result, self.config)
            self._save_pass()
            result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'UP'}
            evaluate_track(self.db_path, result, self.config)
        for _ in range(3):
            self._save_failure()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
        evaluate_track(self.db_path, result, self.config)
        # 2 passes
        for _ in range(2):
            self._save_pass()
            result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'UP'}
            evaluate_track(self.db_path, result, self.config)
        # 1 failure resets
        self._save_failure()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
        actions = evaluate_track(self.db_path, result, self.config)
        self.assertEqual(actions['stabilised'], 0)
        alert = get_open_alert_for_track(self.db_path, '8.8.8.8', 'ICMP', None)
        self.assertIsNotNone(alert)
        self.assertEqual(alert['severity'], 'FLAPPING')

    def test_flapping_no_new_alerts(self):
        # Enter flapping
        for _ in range(3):
            for _ in range(3):
                self._save_failure()
            result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
            evaluate_track(self.db_path, result, self.config)
            self._save_pass()
            result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'UP'}
            evaluate_track(self.db_path, result, self.config)
        for _ in range(3):
            self._save_failure()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
        evaluate_track(self.db_path, result, self.config)
        # Now in FLAPPING. More failures should not create new alerts.
        self._save_failure()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
        actions = evaluate_track(self.db_path, result, self.config)
        self.assertEqual(actions['fired'], [])
        self.assertEqual(actions['flapped'], 0)
        self.assertEqual(actions['stabilised'], 0)
        self.assertEqual(actions['escalated'], 0)
        self.assertEqual(actions['resolved'], 0)

    def test_tcp_port_warning(self):
        for _ in range(3):
            self._save_failure(check_type='TCP', port=443)
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'TCP', 'port': 443, 'status': 'CLOSED'}
        actions = evaluate_track(self.db_path, result, self.config)
        self.assertEqual(actions['fired'], ['WARNING'])
        alert = get_open_alert_for_track(self.db_path, '8.8.8.8', 'TCP', 443)
        self.assertEqual(alert['severity'], 'WARNING')

    def test_jumped_threshold(self):
        # 7 failures in a row with no prior alert
        for _ in range(7):
            self._save_failure()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'}
        actions = evaluate_track(self.db_path, result, self.config)
        # Should only fire CRITICAL, not WARNING
        self.assertEqual(actions['fired'], ['CRITICAL'])
        self.assertEqual(actions['escalated'], 0)
        alert = get_open_alert_for_track(self.db_path, '8.8.8.8', 'ICMP', None)
        self.assertEqual(alert['severity'], 'CRITICAL')

    def test_no_alert_on_passing(self):
        for _ in range(3):
            self._save_pass()
        result = {'host_label': 'H', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'UP'}
        actions = evaluate_track(self.db_path, result, self.config)
        self.assertEqual(actions['fired'], [])
        self.assertEqual(actions['resolved'], 0)


class TestEvaluateAlerts(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, 'test.db')
        init_database(self.db_path)
        self.config = {
            'warning_threshold': 3,
            'critical_threshold': 5,
            'flap_transitions': 3,
            'flap_window_minutes': 10,
            'stabilisation_threshold': 3,
        }

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self.tmp_dir)

    def test_evaluate_alerts_multiple_tracks(self):
        # Track 1: 3 failures
        for _ in range(3):
            save_results(self.db_path, [
                {'host_label': 'H1', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN', 'latency_ms': None}
            ])
        # Track 2: 5 failures
        for _ in range(5):
            save_results(self.db_path, [
                {'host_label': 'H2', 'host_address': '1.1.1.1', 'check_type': 'TCP', 'port': 443, 'status': 'CLOSED', 'latency_ms': None}
            ])
        results = [
            {'host_label': 'H1', 'host_address': '8.8.8.8', 'check_type': 'ICMP', 'port': None, 'status': 'DOWN'},
            {'host_label': 'H2', 'host_address': '1.1.1.1', 'check_type': 'TCP', 'port': 443, 'status': 'CLOSED'},
        ]
        actions = evaluate_alerts(self.db_path, results, self.config)
        self.assertEqual(actions['fired'], ['WARNING', 'CRITICAL'])

    def test_evaluate_alerts_empty_results(self):
        actions = evaluate_alerts(self.db_path, [], self.config)
        self.assertEqual(actions['fired'], [])
        self.assertEqual(actions['resolved'], 0)


if __name__ == '__main__':
    unittest.main()
