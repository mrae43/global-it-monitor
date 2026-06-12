import unittest
from unittest.mock import patch, MagicMock

from src.monitor import run_checks_for_host, run_cycle, evaluate_alerts, evaluate_track


class TestRunChecksForHost(unittest.TestCase):

    @patch('src.monitor.check_port')
    @patch('src.monitor.ping')
    def test_icmp_up_tcp_open(self, mock_ping, mock_check_port):
        mock_ping.return_value = {'status': 'UP', 'latency_ms': 12.5}
        mock_check_port.return_value = {'status': 'OPEN', 'latency_ms': 20.0}

        host = {'label': 'Test', 'host': '10.0.0.1', 'ports': [80]}
        results = run_checks_for_host(host, probe_timeout=3)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['check_type'], 'ICMP')
        self.assertEqual(results[0]['status'], 'UP')
        self.assertEqual(results[0]['latency_ms'], 12.5)
        self.assertEqual(results[0]['host_address'], '10.0.0.1')
        self.assertEqual(results[1]['check_type'], 'TCP')
        self.assertEqual(results[1]['port'], 80)
        self.assertEqual(results[1]['status'], 'OPEN')
        self.assertEqual(results[1]['latency_ms'], 20.0)
        self.assertEqual(results[1]['host_address'], '10.0.0.1')

    @patch('src.monitor.check_port')
    @patch('src.monitor.ping')
    def test_icmp_down_tcp_closed(self, mock_ping, mock_check_port):
        mock_ping.return_value = {'status': 'DOWN', 'latency_ms': None}
        mock_check_port.return_value = {'status': 'CLOSED', 'latency_ms': None}

        host = {'label': 'Test', 'host': '10.0.0.1', 'ports': [443]}
        results = run_checks_for_host(host)

        self.assertEqual(results[0]['status'], 'DOWN')
        self.assertEqual(results[1]['status'], 'CLOSED')

    @patch('src.monitor.check_port')
    @patch('src.monitor.ping')
    def test_multiple_ports(self, mock_ping, mock_check_port):
        mock_ping.return_value = {'status': 'UP', 'latency_ms': 10.0}
        mock_check_port.side_effect = [
            {'status': 'OPEN', 'latency_ms': 5.0},
            {'status': 'CLOSED', 'latency_ms': None}
        ]

        host = {'label': 'Test', 'host': '10.0.0.1', 'ports': [80, 443]}
        results = run_checks_for_host(host)

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]['check_type'], 'ICMP')
        self.assertEqual(results[1]['check_type'], 'TCP')
        self.assertEqual(results[1]['port'], 80)
        self.assertEqual(results[2]['check_type'], 'TCP')
        self.assertEqual(results[2]['port'], 443)

    @patch('src.monitor.check_port')
    @patch('src.monitor.ping')
    def test_no_ports(self, mock_ping, mock_check_port):
        mock_ping.return_value = {'status': 'UP', 'latency_ms': 5.0}

        host = {'label': 'Test', 'host': '10.0.0.1', 'ports': []}
        results = run_checks_for_host(host)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['check_type'], 'ICMP')
        mock_check_port.assert_not_called()

    def test_passes_probe_timeout(self):
        with patch('src.monitor.ping') as mock_ping, \
             patch('src.monitor.check_port') as mock_check_port:
            mock_ping.return_value = {'status': 'UP', 'latency_ms': 1.0}
            mock_check_port.return_value = {'status': 'OPEN', 'latency_ms': 1.0}
            host = {'label': 'Test', 'host': '10.0.0.1', 'ports': [80]}
            run_checks_for_host(host, probe_timeout=5)
            mock_ping.assert_called_once_with('10.0.0.1', timeout=5)
            mock_check_port.assert_called_once_with('10.0.0.1', 80, timeout=5)


class TestRunCycle(unittest.TestCase):

    @patch('src.monitor.evaluate_alerts')
    @patch('src.monitor.save_results')
    @patch('src.monitor.ping')
    @patch('src.monitor.check_port')
    def test_all_hosts_checked(self, mock_check_port, mock_ping, mock_save_results, mock_evaluate_alerts):
        mock_ping.return_value = {'status': 'UP', 'latency_ms': 10.0}
        mock_check_port.return_value = {'status': 'OPEN', 'latency_ms': 5.0}
        mock_evaluate_alerts.return_value = {'fired': [], 'escalated': 0, 'resolved': 0, 'flapped': 0, 'stabilised': 0}

        hosts = [
            {'label': 'H1', 'host': '10.0.0.1', 'ports': [80]},
            {'label': 'H2', 'host': '10.0.0.2', 'ports': [443]},
        ]
        config = {'interval': 60, 'max_workers': 5, 'probe_timeout': 2, 'warning_threshold': 3, 'critical_threshold': 5, 'flap_transitions': 3, 'flap_window_minutes': 10, 'stabilisation_threshold': 3}
        run_cycle(hosts, 'test.db', config)

        mock_save_results.assert_called_once()
        all_results = mock_save_results.call_args[0][1]
        self.assertEqual(len(all_results), 4)
        self.assertEqual(mock_save_results.call_args[0][0], 'test.db')

    @patch('src.monitor.evaluate_alerts')
    @patch('src.monitor.save_results')
    def test_empty_hosts(self, mock_save_results, mock_evaluate_alerts):
        mock_evaluate_alerts.return_value = {'fired': [], 'escalated': 0, 'resolved': 0, 'flapped': 0, 'stabilised': 0}
        config = {'interval': 60, 'max_workers': 20, 'probe_timeout': 3, 'warning_threshold': 3, 'critical_threshold': 5, 'flap_transitions': 3, 'flap_window_minutes': 10, 'stabilisation_threshold': 3}
        run_cycle([], 'test.db', config)
        mock_save_results.assert_called_once_with('test.db', [])

    @patch('src.monitor.evaluate_alerts')
    @patch('src.monitor.save_results')
    @patch('src.monitor.run_checks_for_host')
    def test_future_exception_logged(self, mock_run_checks, mock_save_results, mock_evaluate_alerts):
        mock_run_checks.side_effect = Exception('host failed')
        mock_evaluate_alerts.return_value = {'fired': [], 'escalated': 0, 'resolved': 0, 'flapped': 0, 'stabilised': 0}

        with patch('src.monitor.logger') as mock_logger:
            hosts = [{'label': 'H1', 'host': '10.0.0.1', 'ports': [80]}]
            config = {'interval': 60, 'max_workers': 20, 'probe_timeout': 3, 'warning_threshold': 3, 'critical_threshold': 5, 'flap_transitions': 3, 'flap_window_minutes': 10, 'stabilisation_threshold': 3}
            run_cycle(hosts, 'test.db', config)

        mock_save_results.assert_called_once_with('test.db', [])
        mock_logger.warning.assert_called()

    @patch('src.monitor.evaluate_alerts')
    @patch('src.monitor.save_results')
    @patch('src.monitor.ping')
    @patch('src.monitor.check_port')
    def test_summary_logged(self, mock_check_port, mock_ping, mock_save_results, mock_evaluate_alerts):
        mock_ping.return_value = {'status': 'UP', 'latency_ms': 10.0}
        mock_check_port.return_value = {'status': 'CLOSED', 'latency_ms': None}
        mock_evaluate_alerts.return_value = {'fired': [], 'escalated': 0, 'resolved': 0, 'flapped': 0, 'stabilised': 0}

        with patch('src.monitor.logger') as mock_logger:
            hosts = [{'label': 'H1', 'host': '10.0.0.1', 'ports': [80]}]
            config = {'interval': 60, 'max_workers': 20, 'probe_timeout': 3, 'warning_threshold': 3, 'critical_threshold': 5, 'flap_transitions': 3, 'flap_window_minutes': 10, 'stabilisation_threshold': 3}
            run_cycle(hosts, 'test.db', config)

        log_calls = [call.args[0] for call in mock_logger.info.call_args_list]
        self.assertTrue(
            any('2 checks' in str(c) and '1 UP' in str(c) and '1 DOWN' in str(c) for c in log_calls),
            f"Expected summary in log calls: {log_calls}"
        )

    @patch('src.monitor.evaluate_alerts')
    @patch('src.monitor.save_results')
    @patch('src.monitor.ping')
    @patch('src.monitor.check_port')
    def test_uses_max_workers(self, mock_check_port, mock_ping, mock_save_results, mock_evaluate_alerts):
        from concurrent.futures import Future
        mock_ping.return_value = {'status': 'UP', 'latency_ms': 1.0}
        mock_check_port.return_value = {'status': 'OPEN', 'latency_ms': 1.0}
        mock_evaluate_alerts.return_value = {'fired': [], 'escalated': 0, 'resolved': 0, 'flapped': 0, 'stabilised': 0}

        hosts = [{'label': 'H1', 'host': '10.0.0.1', 'ports': [80]}]
        config = {'interval': 60, 'max_workers': 5, 'probe_timeout': 3, 'warning_threshold': 3, 'critical_threshold': 5, 'flap_transitions': 3, 'flap_window_minutes': 10, 'stabilisation_threshold': 3}
        with patch('src.monitor.ThreadPoolExecutor') as mock_executor_cls:
            mock_executor = MagicMock()
            mock_executor_cls.return_value.__enter__ = MagicMock(return_value=mock_executor)
            mock_executor_cls.return_value.__exit__ = MagicMock(return_value=None)

            # as_completed needs real Future objects, so make submit return a Future
            def mock_submit(fn, *args, **kwargs):
                f = Future()
                f.set_result(fn(*args, **kwargs))
                return f

            mock_executor.submit = mock_submit
            run_cycle(hosts, 'test.db', config)
            mock_executor_cls.assert_called_once_with(max_workers=5)

    @patch('src.monitor.evaluate_alerts')
    @patch('src.monitor.save_results')
    @patch('src.monitor.ping')
    @patch('src.monitor.check_port')
    def test_save_results_failure_logged(self, mock_check_port, mock_ping, mock_save_results, mock_evaluate_alerts):
        mock_ping.return_value = {'status': 'UP', 'latency_ms': 10.0}
        mock_check_port.return_value = {'status': 'OPEN', 'latency_ms': 5.0}
        mock_save_results.side_effect = Exception('db locked')
        mock_evaluate_alerts.return_value = {'fired': [], 'escalated': 0, 'resolved': 0, 'flapped': 0, 'stabilised': 0}

        with patch('src.monitor.logger') as mock_logger:
            hosts = [{'label': 'H1', 'host': '10.0.0.1', 'ports': [80]}]
            config = {'interval': 60, 'max_workers': 20, 'probe_timeout': 3, 'warning_threshold': 3, 'critical_threshold': 5, 'flap_transitions': 3, 'flap_window_minutes': 10, 'stabilisation_threshold': 3}
            run_cycle(hosts, 'test.db', config)

        mock_logger.error.assert_called()
        error_calls = [call.args[0] for call in mock_logger.error.call_args_list]
        self.assertTrue(
            any('Failed to save check results' in str(c) for c in error_calls),
            f"Expected save_results error in log calls: {error_calls}"
        )

    @patch('src.monitor.evaluate_alerts')
    @patch('src.monitor.save_results')
    @patch('src.monitor.ping')
    @patch('src.monitor.check_port')
    def test_evaluate_alerts_failure_logged(self, mock_check_port, mock_ping, mock_save_results, mock_evaluate_alerts):
        mock_ping.return_value = {'status': 'UP', 'latency_ms': 10.0}
        mock_check_port.return_value = {'status': 'OPEN', 'latency_ms': 5.0}
        mock_evaluate_alerts.side_effect = Exception('db locked')

        with patch('src.monitor.logger') as mock_logger:
            hosts = [{'label': 'H1', 'host': '10.0.0.1', 'ports': [80]}]
            config = {'interval': 60, 'max_workers': 20, 'probe_timeout': 3, 'warning_threshold': 3, 'critical_threshold': 5, 'flap_transitions': 3, 'flap_window_minutes': 10, 'stabilisation_threshold': 3}
            run_cycle(hosts, 'test.db', config)

        mock_logger.error.assert_called()
        error_calls = [call.args[0] for call in mock_logger.error.call_args_list]
        self.assertTrue(
            any('Alert evaluation failed' in str(c) for c in error_calls),
            f"Expected evaluate_alerts error in log calls: {error_calls}"
        )

    @patch('src.monitor.evaluate_alerts')
    @patch('src.monitor.save_results')
    @patch('src.monitor.run_checks_for_host')
    def test_run_cycle_top_level_failure_logged(self, mock_run_checks, mock_save_results, mock_evaluate_alerts):
        mock_evaluate_alerts.return_value = {'fired': [], 'escalated': 0, 'resolved': 0, 'flapped': 0, 'stabilised': 0}

        with patch('src.monitor.ThreadPoolExecutor') as mock_executor_cls, \
             patch('src.monitor.logger') as mock_logger:
            mock_executor_cls.side_effect = RuntimeError('executor crashed')

            hosts = [{'label': 'H1', 'host': '10.0.0.1', 'ports': [80]}]
            config = {'interval': 60, 'max_workers': 20, 'probe_timeout': 3, 'warning_threshold': 3, 'critical_threshold': 5, 'flap_transitions': 3, 'flap_window_minutes': 10, 'stabilisation_threshold': 3}
            run_cycle(hosts, 'test.db', config)

        mock_logger.error.assert_called()
        error_calls = [call.args[0] for call in mock_logger.error.call_args_list]
        self.assertTrue(
            any('Monitoring cycle failed' in str(c) for c in error_calls),
            f"Expected cycle failure in log calls: {error_calls}"
        )


if __name__ == '__main__':
    unittest.main()
