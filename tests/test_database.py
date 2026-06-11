import os
import sqlite3
import tempfile
import unittest

from src.storage.database import init_database, save_results, query_latest, CREATE_TABLE_SQL


class TestDatabase(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, 'test.db')

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self.tmp_dir)

    def test_init_database_creates_db(self):
        init_database(self.db_path)
        self.assertTrue(os.path.exists(self.db_path))
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        self.assertIn('check_results', tables)

    def test_init_database_creates_parent_dir(self):
        nested = os.path.join(self.tmp_dir, 'nested', 'deep', 'test.db')
        init_database(nested)
        self.assertTrue(os.path.exists(nested))
        os.unlink(nested)
        os.rmdir(os.path.dirname(nested))
        os.rmdir(os.path.dirname(os.path.dirname(nested)))

    def test_init_database_is_idempotent(self):
        init_database(self.db_path)
        init_database(self.db_path)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        self.assertIn('check_results', tables)

    def test_save_results_inserts_rows(self):
        init_database(self.db_path)
        results = [
            {
                'host_label': 'Test Host',
                'host_ip': '8.8.8.8',
                'check_type': 'ICMP',
                'status': 'UP',
                'latency_ms': 12.3
            }
        ]
        save_results(self.db_path, results)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM check_results")
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_save_results_creates_table_if_missing(self):
        # Skip init_database, let save_results create the table
        results = [
            {
                'host_label': 'Test Host',
                'host_ip': '8.8.8.8',
                'check_type': 'ICMP',
                'status': 'UP',
                'latency_ms': 12.3
            }
        ]
        save_results(self.db_path, results)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM check_results")
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_save_results_inserts_multiple_rows(self):
        init_database(self.db_path)
        results = [
            {
                'host_label': 'Host A',
                'host_ip': '8.8.8.8',
                'check_type': 'ICMP',
                'status': 'UP',
                'latency_ms': 10.0
            },
            {
                'host_label': 'Host B',
                'host_ip': '1.1.1.1',
                'check_type': 'TCP',
                'port': 443,
                'status': 'OPEN',
                'latency_ms': 5.0
            }
        ]
        save_results(self.db_path, results)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM check_results")
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)

    def test_save_results_null_port(self):
        init_database(self.db_path)
        results = [
            {
                'host_label': 'Test Host',
                'host_ip': '8.8.8.8',
                'check_type': 'ICMP',
                'status': 'UP',
                'latency_ms': 12.3
            }
        ]
        save_results(self.db_path, results)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT port FROM check_results")
        port = cursor.fetchone()[0]
        conn.close()
        self.assertIsNone(port)

    def test_save_results_null_latency(self):
        init_database(self.db_path)
        results = [
            {
                'host_label': 'Test Host',
                'host_ip': '8.8.8.8',
                'check_type': 'ICMP',
                'status': 'DOWN',
                'latency_ms': None
            }
        ]
        save_results(self.db_path, results)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT latency_ms FROM check_results")
        latency = cursor.fetchone()[0]
        conn.close()
        self.assertIsNone(latency)

    def test_query_latest_returns_data(self):
        init_database(self.db_path)
        results = [
            {
                'host_label': 'Test Host',
                'host_ip': '8.8.8.8',
                'check_type': 'ICMP',
                'status': 'UP',
                'latency_ms': 12.3
            }
        ]
        save_results(self.db_path, results)
        rows = query_latest(self.db_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 'Test Host')
        self.assertEqual(rows[0][1], 'UP')
        self.assertEqual(rows[0][2], 12.3)
        self.assertIsNotNone(rows[0][3])  # checked_at

    def test_query_latest_returns_empty(self):
        init_database(self.db_path)
        rows = query_latest(self.db_path)
        self.assertEqual(rows, [])

    def test_query_latest_latest_per_host(self):
        init_database(self.db_path)
        # Insert two results for same host
        results1 = [
            {
                'host_label': 'Host A',
                'host_ip': '8.8.8.8',
                'check_type': 'ICMP',
                'status': 'UP',
                'latency_ms': 10.0
            }
        ]
        results2 = [
            {
                'host_label': 'Host A',
                'host_ip': '8.8.8.8',
                'check_type': 'ICMP',
                'status': 'DOWN',
                'latency_ms': None
            }
        ]
        save_results(self.db_path, results1)
        save_results(self.db_path, results2)
        rows = query_latest(self.db_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'DOWN')
        self.assertIsNone(rows[0][2])

    def test_query_latest_grouped_by_host_ip_check_type_port(self):
        init_database(self.db_path)
        results = [
            {
                'host_label': 'Host A',
                'host_ip': '8.8.8.8',
                'check_type': 'ICMP',
                'status': 'UP',
                'latency_ms': 10.0
            },
            {
                'host_label': 'Host A',
                'host_ip': '8.8.8.8',
                'check_type': 'TCP',
                'port': 443,
                'status': 'OPEN',
                'latency_ms': 5.0
            },
            {
                'host_label': 'Host B',
                'host_ip': '1.1.1.1',
                'check_type': 'ICMP',
                'status': 'DOWN',
                'latency_ms': None
            }
        ]
        save_results(self.db_path, results)
        rows = query_latest(self.db_path)
        self.assertEqual(len(rows), 3)
        host_labels = [row[0] for row in rows]
        self.assertEqual(host_labels, sorted(host_labels))

    def test_query_latest_closes_connection(self):
        init_database(self.db_path)
        # If connection leaks, this won't cause an error in the test,
        # but we can at least verify the function works without crashing
        rows = query_latest(self.db_path)
        self.assertEqual(rows, [])


class TestCreateTableSql(unittest.TestCase):

    def test_create_table_sql_exists(self):
        self.assertIsInstance(CREATE_TABLE_SQL, str)
        self.assertIn('CREATE TABLE IF NOT EXISTS check_results', CREATE_TABLE_SQL)

    def test_create_table_sql_has_all_columns(self):
        required = ['id', 'checked_at', 'host_label', 'host_ip', 'check_type', 'port', 'status', 'latency_ms']
        for col in required:
            self.assertIn(col, CREATE_TABLE_SQL)


if __name__ == '__main__':
    unittest.main()
