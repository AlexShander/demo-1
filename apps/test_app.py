"""
Unit tests for the Flask application.

Tests cover:
- Liveness endpoint
- Readiness endpoint (with and without DB_ENDPOINT)
- Version file reading
- TCP connection checking
- Error handling
"""

import unittest
from unittest.mock import patch, mock_open, MagicMock
import os
import tempfile
from app import app, read_version, check_tcp_connect


class TestFlaskApp(unittest.TestCase):
    """Test cases for Flask application endpoints."""

    def setUp(self):
        """Set up test client and test environment."""
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        """Clean up after tests."""
        # Remove any environment variables set during tests
        if 'DB_ENDPOINT' in os.environ:
            del os.environ['DB_ENDPOINT']

    # ========== Liveness Endpoint Tests ==========

    def test_liveness_endpoint_returns_200(self):
        """Test that /liveness endpoint returns HTTP 200."""
        response = self.client.get('/liveness')
        self.assertEqual(response.status_code, 200)

    def test_liveness_endpoint_contains_html(self):
        """Test that /liveness endpoint returns HTML content."""
        response = self.client.get('/liveness')
        self.assertIn(b'<!doctype html>', response.data)
        self.assertIn(b'Current time in Beograd', response.data)

    def test_liveness_endpoint_contains_timezone(self):
        """Test that /liveness endpoint shows Belgrade timezone."""
        response = self.client.get('/liveness')
        # Check for CEST (summer) or CET (winter) timezone
        self.assertTrue(
            b'CEST' in response.data or b'CET' in response.data,
            "Response should contain Belgrade timezone (CEST or CET)"
        )

    @patch('app.read_version')
    def test_liveness_shows_version(self, mock_read_version):
        """Test that /liveness endpoint displays app version."""
        mock_read_version.return_value = "test-version-1.2.3"
        response = self.client.get('/liveness')
        self.assertIn(b'test-version-1.2.3', response.data)

    # ========== Readiness Endpoint Tests ==========

    def test_readiness_without_db_endpoint_returns_503(self):
        """Test that /readiness returns 503 when DB_ENDPOINT is not set."""
        # Ensure DB_ENDPOINT is not set
        if 'DB_ENDPOINT' in os.environ:
            del os.environ['DB_ENDPOINT']

        response = self.client.get('/readiness')
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'DB_ENDPOINT not set', response.data)

    @patch('app.check_tcp_connect')
    def test_readiness_with_unreachable_db_returns_503(self, mock_tcp_connect):
        """Test that /readiness returns 503 when DB is unreachable."""
        mock_tcp_connect.return_value = False
        os.environ['DB_ENDPOINT'] = 'localhost:3306'

        response = self.client.get('/readiness')
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'DB not reachable', response.data)

    @patch('app.check_tcp_connect')
    def test_readiness_with_reachable_db_returns_200(self, mock_tcp_connect):
        """Test that /readiness returns 200 when DB is reachable."""
        mock_tcp_connect.return_value = True
        os.environ['DB_ENDPOINT'] = 'localhost:3306'

        response = self.client.get('/readiness')
        self.assertEqual(response.status_code, 200)

        # Parse JSON response
        json_data = response.get_json()
        self.assertEqual(json_data['status'], 'ready')
        self.assertEqual(json_data['db_endpoint'], 'localhost:3306')

    @patch('app.check_tcp_connect')
    def test_readiness_parses_endpoint_with_port(self, mock_tcp_connect):
        """Test that /readiness correctly parses DB_ENDPOINT with port."""
        mock_tcp_connect.return_value = True
        os.environ['DB_ENDPOINT'] = 'db.example.com:5432'

        response = self.client.get('/readiness')
        self.assertEqual(response.status_code, 200)

        # Verify that check_tcp_connect was called with correct host and port
        mock_tcp_connect.assert_called_once_with('db.example.com', 5432)

    @patch('app.check_tcp_connect')
    def test_readiness_defaults_to_port_3306(self, mock_tcp_connect):
        """Test that /readiness uses default port 3306 when not specified."""
        mock_tcp_connect.return_value = True
        os.environ['DB_ENDPOINT'] = 'db.example.com'

        response = self.client.get('/readiness')
        self.assertEqual(response.status_code, 200)

        # Verify that check_tcp_connect was called with default port
        mock_tcp_connect.assert_called_once_with('db.example.com', 3306)

    @patch('app.check_tcp_connect')
    def test_readiness_handles_invalid_port(self, mock_tcp_connect):
        """Test that /readiness handles invalid port numbers gracefully."""
        mock_tcp_connect.return_value = True
        os.environ['DB_ENDPOINT'] = 'db.example.com:invalid'

        response = self.client.get('/readiness')
        self.assertEqual(response.status_code, 200)

        # Should default to port 3306 when port is invalid
        mock_tcp_connect.assert_called_once_with('db.example.com', 3306)

    # ========== Helper Function Tests ==========

    def test_read_version_with_existing_file(self):
        """Test read_version() with an existing version file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write('1.2.3-test\n')
            temp_file = f.name

        try:
            with patch('app.VERSION_FILE', temp_file):
                version = read_version()
                self.assertEqual(version, '1.2.3-test')
        finally:
            os.unlink(temp_file)

    def test_read_version_with_missing_file(self):
        """Test read_version() returns 'unknown' when file is missing."""
        with patch('app.VERSION_FILE', '/nonexistent/file.txt'):
            version = read_version()
            self.assertEqual(version, 'unknown')

    def test_read_version_strips_whitespace(self):
        """Test read_version() strips leading/trailing whitespace."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write('  1.2.3  \n\n')
            temp_file = f.name

        try:
            with patch('app.VERSION_FILE', temp_file):
                version = read_version()
                self.assertEqual(version, '1.2.3')
        finally:
            os.unlink(temp_file)

    @patch('socket.create_connection')
    def test_check_tcp_connect_success(self, mock_socket):
        """Test check_tcp_connect() returns True on successful connection."""
        mock_socket.return_value.__enter__ = MagicMock()
        mock_socket.return_value.__exit__ = MagicMock()

        result = check_tcp_connect('localhost', 3306)
        self.assertTrue(result)
        mock_socket.assert_called_once_with(('localhost', 3306), timeout=2.0)

    @patch('socket.create_connection')
    def test_check_tcp_connect_failure(self, mock_socket):
        """Test check_tcp_connect() returns False on connection failure."""
        mock_socket.side_effect = ConnectionRefusedError()

        result = check_tcp_connect('localhost', 3306)
        self.assertFalse(result)

    @patch('socket.create_connection')
    def test_check_tcp_connect_timeout(self, mock_socket):
        """Test check_tcp_connect() returns False on timeout."""
        mock_socket.side_effect = TimeoutError()

        result = check_tcp_connect('localhost', 3306, timeout=1.0)
        self.assertFalse(result)

    # ========== Integration Tests ==========

    def test_app_has_correct_routes(self):
        """Test that application has the expected routes."""
        rules = [rule.rule for rule in self.app.url_map.iter_rules()]
        self.assertIn('/liveness', rules)
        self.assertIn('/readiness', rules)

    def test_liveness_endpoint_is_get_only(self):
        """Test that /liveness only accepts GET requests."""
        # GET should work
        response = self.client.get('/liveness')
        self.assertEqual(response.status_code, 200)

        # POST should return 405 Method Not Allowed
        response = self.client.post('/liveness')
        self.assertEqual(response.status_code, 405)

    def test_readiness_endpoint_is_get_only(self):
        """Test that /readiness only accepts GET requests."""
        os.environ['DB_ENDPOINT'] = 'localhost:3306'

        # POST should return 405 Method Not Allowed
        response = self.client.post('/readiness')
        self.assertEqual(response.status_code, 405)


if __name__ == '__main__':
    unittest.main()
