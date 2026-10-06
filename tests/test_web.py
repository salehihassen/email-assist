"""HTTP smoke checks without database, inbox, AI, or real credentials."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app


class WebSmoke(unittest.TestCase):
    def setUp(self):
        # Without the context manager, TestClient skips the external-service
        # startup hooks. These checks exercise HTTP routing, auth and assets.
        self.client = TestClient(app.app)
        self.addCleanup(self.client.close)

    def test_authenticated_page_and_static_assets(self):
        self.assertEqual(self.client.get('/').status_code, 401)
        with patch.object(app, 'secret', return_value='test-password'):
            response = self.client.get('/', auth=(app.WEB_USERNAME, 'test-password'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Email Assist', response.text)
        self.assertIn('/static/app.js', response.text)
        self.assertIn('/static/style.css', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])
        for path in ('/static/app.js', '/static/style.css'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.content)

    def test_inbox_api_requires_authentication(self):
        for path in ('/api/status', '/api/emails', '/api/email/example'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
        for path in ('/api/refresh', '/api/setup'):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, json={}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
