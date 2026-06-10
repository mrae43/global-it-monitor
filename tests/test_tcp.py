import unittest
from unittest.mock import patch, MagicMock
import socket

from src.probes.tcp import check_port


class TestCheckPort(unittest.TestCase):

    @patch("src.probes.tcp.socket.socket")
    def test_port_open(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect_ex.return_value = 0

        result = check_port("203.0.113.10", 80)
        self.assertEqual(result["status"], "OPEN")
        self.assertIsNotNone(result["latency_ms"])
        self.assertIsInstance(result["latency_ms"], float)

    @patch("src.probes.tcp.socket.socket")
    def test_port_closed(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect_ex.return_value = 111  # ECONNREFUSED

        result = check_port("203.0.113.10", 443)
        self.assertEqual(result["status"], "CLOSED")
        self.assertIsNone(result["latency_ms"])

    @patch("src.probes.tcp.socket.socket")
    def test_port_timeout(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect_ex.side_effect = socket.timeout

        result = check_port("10.0.0.0", 22)
        self.assertEqual(result["status"], "CLOSED")
        self.assertIsNone(result["latency_ms"])

    @patch("src.probes.tcp.socket.socket")
    def test_port_network_unreachable(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect_ex.side_effect = OSError("Network is unreachable")

        result = check_port("10.0.0.0", 22)
        self.assertEqual(result["status"], "CLOSED")
        self.assertIsNone(result["latency_ms"])

    @patch("src.probes.tcp.socket.socket")
    def test_socket_always_closed(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        check_port("203.0.113.10", 80)
        mock_sock.close.assert_called_once()

    @patch("src.probes.tcp.socket.socket")
    def test_default_timeout(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect_ex.return_value = 0

        check_port("203.0.113.10", 80)
        mock_sock.settimeout.assert_called_once_with(3)

    @patch("src.probes.tcp.socket.socket")
    def test_custom_timeout(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect_ex.return_value = 0

        check_port("203.0.113.10", 80, timeout=5)
        mock_sock.settimeout.assert_called_once_with(5)

    @patch("src.probes.tcp.socket.socket")
    def test_latency_rounded(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect_ex.return_value = 0

        result = check_port("203.0.113.10", 80)
        self.assertIsNotNone(result["latency_ms"])
        self.assertIsInstance(result["latency_ms"], float)
        # latency should be a reasonable small value in the mock context
        self.assertGreaterEqual(result["latency_ms"], 0)

    @patch("src.probes.tcp.socket.socket")
    def test_generic_exception(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect_ex.side_effect = RuntimeError("unexpected")

        result = check_port("203.0.113.10", 80)
        self.assertEqual(result["status"], "CLOSED")
        self.assertIsNone(result["latency_ms"])
        mock_sock.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
