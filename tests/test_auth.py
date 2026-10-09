"""Security integration tests using a disposable PostgreSQL schema, never mail."""
import hashlib
import unittest
import uuid
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
import app
import auth

class Sessions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoded = auth.hasher.hash('test-only-strong-password')
        cls.version = hashlib.sha256(cls.encoded.encode()).hexdigest()

    def setUp(self):
        self.schema = 'test_' + uuid.uuid4().hex
        self.real_db = app.db
        with self.real_db() as conn:
            conn.execute('CREATE SCHEMA ' + self.schema)
        def isolated_db():
            return psycopg.connect(password=app.secret('db-password'),
                                   options='-c search_path=' + self.schema, row_factory=dict_row)
        self.patches = [patch.object(app, 'db', isolated_db),
                        patch.object(app, 'credentials', return_value=(self.encoded, self.version)),
                        patch.object(app, 'WEB_USERNAME', 'tester'),
                        patch.object(app, 'ORIGIN', 'https://inbox.example.test')]
        for p in self.patches:
            p.start()
        app.init_db()
        self.client = TestClient(app.app, base_url='https://inbox.example.test')
        self.headers = {'Origin':'https://inbox.example.test', 'X-Email-Assist':'1'}

    def tearDown(self):
        self.client.close()
        for p in self.patches:
            p.stop()
        with self.real_db() as conn:
            conn.execute('DROP SCHEMA ' + self.schema + ' CASCADE')

    def login(self, **changes):
        value = {'username':'tester','password':'test-only-strong-password','next':'/'} | changes
        return self.client.post('/api/login', json=value, headers=self.headers)

    def test_session_cookie_logout_and_replay(self):
        denied = self.client.get('/api/emails')
        self.assertEqual(denied.status_code,401)
        self.assertNotIn('www-authenticate',denied.headers)
        response = self.login()
        self.assertEqual(response.status_code,200)
        cookie = response.headers['set-cookie']
        for flag in ['Secure','HttpOnly','SameSite=strict','Path=/','Max-Age=86400']:
            self.assertIn(flag,cookie)
        self.assertNotIn('Domain=',cookie)
        token = self.client.cookies.get(auth.COOKIE)
        with app.db() as conn:
            stored = conn.execute('SELECT token_hash FROM web_sessions').fetchone()['token_hash']
        self.assertNotEqual(stored,token)
        self.assertEqual(stored,auth.token_hash(token))
        self.assertEqual(self.client.get('/api/emails').status_code,200)
        self.assertEqual(self.client.post('/api/logout',headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/emails',headers={'Cookie':auth.COOKIE+'='+token}).status_code,401)

    def test_login_errors_and_rate_limit_persist_in_database(self):
        first = self.login(username='wrong-user')
        second = self.login(password='wrong-password')
        self.assertEqual(first.json(),second.json())
        self.assertNotIn('www-authenticate',first.headers)
        for _ in range(auth.LOGIN_LIMIT-2):
            self.assertEqual(self.login(password='wrong').status_code,401)
        limited = self.login()
        self.assertEqual(limited.status_code,429)
        self.assertIn('retry-after',limited.headers)
        with app.db() as conn:
            conn.execute("UPDATE web_login_limit SET window_start=now()-interval '6 minutes'")
        self.assertEqual(self.login().status_code,200)

    def test_expiration_and_password_change(self):
        for condition in ["expires_at=now()-interval '1 second'", "last_seen=now()-interval '61 minutes'", "credential_version='old-version'"]:
            with self.subTest(condition=condition):
                self.assertEqual(self.login().status_code,200)
                with app.db() as conn:
                    conn.execute('UPDATE web_sessions SET '+condition)
                self.assertEqual(self.client.get('/api/emails').status_code,401)

    def test_csrf_and_session_fixation(self):
        for headers in [{}, {'Origin':'https://evil.example.test','X-Email-Assist':'1'}, {'Origin':'https://inbox.example.test'}]:
            self.assertEqual(self.client.post('/api/login',json={'username':'tester','password':'test-only-strong-password'},headers=headers).status_code,403)
        self.login()
        old = self.client.cookies.get(auth.COOKIE)
        self.login()
        current = self.client.cookies.get(auth.COOKIE)
        self.assertNotEqual(old,current)
        self.assertEqual(self.client.get('/api/emails',headers={'Cookie':auth.COOKIE+'='+old}).status_code,401)
        self.assertEqual(self.client.post('/api/logout',headers={'Origin':'https://evil.example.test','X-Email-Assist':'1'}).status_code,403)
        self.assertEqual(self.client.get('/api/emails').status_code,200)

    def test_page_redirect_returns_to_message_without_open_redirect(self):
        response = self.client.get('/email/example',follow_redirects=False)
        self.assertEqual(response.status_code,303)
        self.assertIn('next=%2Femail%2Fexample',response.headers['location'])
        for target in ['https://evil.example.test','//evil.example.test','/\\evil.example.test','/api/logout']:
            self.assertEqual(self.login(next=target).json()['next'],'/')
        self.assertEqual(self.login(next='/email/example').json()['next'],'/email/example')

if __name__ == '__main__':
    unittest.main()
