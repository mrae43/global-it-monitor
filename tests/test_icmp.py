import unittest
from unittest.mock import patch, MagicMock
import subprocess

from src.probes.icmp import ping


class TestPing(unittest.TestCase):

    @patch('src.probes.icmp.subprocess.run')
    @patch('src.probes.icmp.platform.system')
    def test_ping_up_linux(self, mock_system, mock_run):
        mock_system.return_value = 'Linux'
        mock_run.return_value = MagicMock(returncode=0, stdout='64 bytes from 8.8.8.8: icmp_seq=0 ttl=115 time=24.3 ms')
        result = ping('8.8.8.8')
        self.assertEqual(result['status'], 'UP')
        self.assertEqual(result['latency_ms'], 24.3)

    @patch('src.probes.icmp.subprocess.run')
    @patch('src.probes.icmp.platform.system')
    def test_ping_up_windows(self, mock_system, mock_run):
        mock_system.return_value = 'Windows'
        mock_run.return_value = MagicMock(returncode=0, stdout='Reply from 8.8.8.8: bytes=32 time=24ms TTL=115')
        result = ping('8.8.8.8')
        self.assertEqual(result['status'], 'UP')
        self.assertEqual(result['latency_ms'], 24.0)

    @patch('src.probes.icmp.subprocess.run')
    @patch('src.probes.icmp.platform.system')
    def test_ping_down(self, mock_system, mock_run):
        mock_system.return_value = 'Linux'
        mock_run.return_value = MagicMock(returncode=1, stdout='')
        result = ping('10.0.0.0')
        self.assertEqual(result['status'], 'DOWN')
        self.assertIsNone(result['latency_ms'])

    @patch('src.probes.icmp.subprocess.run')
    @patch('src.probes.icmp.platform.system')
    def test_ping_timeout(self, mock_system, mock_run):
        mock_system.return_value = 'Linux'
        mock_run.side_effect = subprocess.TimeoutExpired(['ping'], 5)
        result = ping('10.0.0.0')
        self.assertEqual(result['status'], 'DOWN')
        self.assertIsNone(result['latency_ms'])

    @patch('src.probes.icmp.subprocess.run')
    @patch('src.probes.icmp.platform.system')
    def test_ping_up_latency_unparseable(self, mock_system, mock_run):
        mock_system.return_value = 'Linux'
        mock_run.return_value = MagicMock(returncode=0, stdout='some weird output without time')
        result = ping('8.8.8.8')
        self.assertEqual(result['status'], 'UP')
        self.assertIsNone(result['latency_ms'])

    @patch('src.probes.icmp.subprocess.run')
    @patch('src.probes.icmp.platform.system')
    def test_ping_generic_exception(self, mock_system, mock_run):
        mock_system.return_value = 'Linux'
        mock_run.side_effect = OSError('ping not found')
        result = ping('8.8.8.8')
        self.assertEqual(result['status'], 'DOWN')
        self.assertIsNone(result['latency_ms'])

    @patch('src.probes.icmp.subprocess.run')
    @patch('src.probes.icmp.platform.system')
    def test_ping_builds_linux_command(self, mock_system, mock_run):
        mock_system.return_value = 'Linux'
        mock_run.return_value = MagicMock(returncode=0, stdout='time=1.0 ms')
        ping('8.8.8.8', timeout=3)
        mock_run.assert_called_once_with(
            ['ping', '-c', '1', '-W', '3', '8.8.8.8'],
            capture_output=True,
            text=True,
            timeout=5,
        )

    @patch('src.probes.icmp.subprocess.run')
    @patch('src.probes.icmp.platform.system')
    def test_ping_builds_windows_command(self, mock_system, mock_run):
        mock_system.return_value = 'Windows'
        mock_run.return_value = MagicMock(returncode=0, stdout='time=1ms')
        ping('8.8.8.8', timeout=3)
        mock_run.assert_called_once_with(
            ['ping', '-n', '1', '-w', '3000', '8.8.8.8'],
            capture_output=True,
            text=True,
            timeout=5,
        )


if __name__ == '__main__':
    unittest.main()
