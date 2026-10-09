"""HTTP smoke checks without database, inbox, AI, or real credentials."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app


class WebSmoke(unittest.TestCase):
    def setUp(self):
        # Without the context manager, TestClient skips the external-service
        # startup hooks. These checks exercise HTTP routing, auth and assets.
        self.credential_patch = patch.object(app, 'credentials', return_value=('test-hash', 'version'))
        self.credential_patch.start()
        self.addCleanup(self.credential_patch.stop)
        self.client = TestClient(app.app)
        self.addCleanup(self.client.close)

    def test_authenticated_page_and_static_assets(self):
        response = self.client.get('/', follow_redirects=False)
        self.assertEqual(response.status_code,303)
        self.assertTrue(response.headers['location'].startswith('/login'))
        self.assertNotIn('www-authenticate',response.headers)
        self.assertEqual(self.client.get('/login').status_code,200)
        with patch.object(app.web_auth, 'authenticated', return_value=True):
            response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Email Assist', response.text)
        self.assertIn('/static/app.js', response.text)
        self.assertIn('/static/style.css', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])
        for path in ('/static/app.js', '/static/style.css', '/static/login.js'):
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
