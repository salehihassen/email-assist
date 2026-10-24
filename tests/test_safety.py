import unittest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from starlette.requests import Request
import app
import mail

class Safety(unittest.TestCase):
    def test_session_auth_never_sends_basic_challenge(self):
        request = Request({'type':'http','headers':[]})
        with patch.object(app, 'credentials', return_value=('hash','version')):
            with self.assertRaises(HTTPException) as error:
                app.auth(request)
        self.assertEqual(error.exception.status_code,401)
        self.assertFalse(error.exception.headers)

    def test_post_guard_rejects_foreign_origin_and_missing_header(self):
        with patch.object(app, 'ORIGIN', 'https://inbox.example.test'):
            for origin, marker, allowed in [('https://inbox.example.test', '1', True),
                                           ('https://foreign.example.test', '1', False),
                                           ('https://inbox.example.test', '', False)]:
                request = Request({'type': 'http', 'headers': [
                    (b'origin', origin.encode()), (b'x-email-assist', marker.encode())]})
                if allowed:
                    app.post_guard(request)
                else:
                    with self.assertRaises(HTTPException) as error:
                        app.post_guard(request)
                    self.assertEqual(error.exception.status_code, 403)

    def test_password_from_secret_file_then_environment_then_ui(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secrets_dir = root / 'secrets'
            state_dir = root / 'state'
            secrets_dir.mkdir()
            state_dir.mkdir()
            env = {'work': {'password': 'env-password'}}
            with patch.object(app, 'SECRET', secrets_dir), patch.object(app, 'STATE', state_dir), \
                 patch.object(app, 'ENV_PROVIDERS', env):
                self.assertEqual(app.password('home'), ('', None))
                app.save_password('home', 'saved-password')
                self.assertEqual((state_dir / 'home-imap-password').stat().st_mode & 0o777, 0o600)
                self.assertEqual(app.password('home'), ('saved-password', 'saved'))
                (state_dir / 'work-imap-password').write_text('saved-password')
                self.assertEqual(app.password('work'), ('env-password', 'env'))
                (secrets_dir / 'work-imap-password').write_text('mounted-password')
                self.assertEqual(app.password('work'), ('mounted-password', 'file'))

    def test_environment_providers(self):
        values = {'MAIL_PROVIDERS': 'home, Work-Mail', 'MAIL_HOME_TYPE': 'bridge',
                  'MAIL_WORK_MAIL_HOST': 'imap.example.test', 'MAIL_WORK_MAIL_PORT': '1993',
                  'MAIL_WORK_MAIL_LABEL': 'Business', 'MAIL_WORK_MAIL_PASSWORD': 'secret'}
        with patch.dict(app.os.environ, values):
            providers = app.env_providers()
        self.assertEqual(list(providers), ['home', 'work-mail'])
        self.assertEqual(providers['home']['config']['label'], 'Home')
        self.assertEqual(providers['work-mail']['config']['port'], 1993)
        self.assertEqual(providers['work-mail']['locked'], ['host', 'label', 'port'])
        self.assertEqual(providers['work-mail']['password'], 'secret')
        for bad in ({'MAIL_PROVIDERS': '../home'}, {'MAIL_PROVIDERS': 'work'}):
            with self.subTest(bad=bad), patch.dict(app.os.environ, bad), self.assertRaises(Exception):
                app.env_providers()

    def test_provider_settings_validated(self):
        app.ProviderConfig(label='Home', type='bridge')
        for bad in [dict(label='Work'), dict(label='Work', host='imap.example.test/x'),
                    dict(label='Work', host='imap.example.test', webmail='javascript:alert(1)'),
                    dict(label='Work', host='imap.example.test', port=0), dict(label='', type='bridge')]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                app.ProviderConfig(**bad)

    def test_connection_errors_are_actionable_and_private(self):
        self.assertIn('username and password', app.connection_error(mail.imaplib.IMAP4.error('secret detail')))
        self.assertIn('secure connection', app.connection_error(app.ssl.SSLError('secret detail')))
        self.assertIn('Cannot reach', app.connection_error(ConnectionRefusedError('secret detail')))
        self.assertIn('Bridge', app.connection_error(FileNotFoundError('secret detail'), bridge=True))
        self.assertNotIn('secret', app.connection_error(RuntimeError('secret detail')))

    def test_seven_day_boundary(self):
        now = datetime.now(timezone.utc)
        self.assertTrue(app.fresh(now-timedelta(days=7)+timedelta(seconds=1), now))
        self.assertFalse(app.fresh(now-timedelta(days=7), now))
        self.assertFalse(app.fresh(None, now))

    def test_model_output_must_match_inputs(self):
        import json
        row = {'id':'one','score':80,'response_needed':True,'reason':'Deadline tomorrow','suggested_action':'Confirm attendance'}
        self.assertEqual(app.parse_scores(json.dumps({'emails':[row]}),{'one'})['one']['score'],80)
        for bad in [row|{'score':101},row|{'score':True},row|{'response_needed':'yes'},row|{'id':'injected'}]:
            with self.assertRaises(ValueError):
                app.parse_scores(json.dumps({'emails':[bad]}),{'one'})
        with self.assertRaises(ValueError):
            app.parse_scores(json.dumps({'emails':[row,row]}),{'one'})

    def test_imap_write_commands_blocked(self):
        for cls in (mail.UnixIMAP, mail.TLSIMAP):
            with self.subTest(cls=cls.__name__):
                self.assert_read_only(cls.__new__(cls))

    def assert_read_only(self, client):
        for command,args in [('SELECT',('INBOX',)),('STORE',('1','+FLAGS','\\Seen')),
            ('EXPUNGE',()),('APPEND',('INBOX',)),('UID',('STORE','1','+FLAGS','\\Seen')),
            ('UID',('FETCH','1','(BODY[])')),('UID',('FETCH','1','(RFC822)'))]:
            with self.assertRaises(ValueError):
                client._command(command,*args)
        with patch.object(mail.imaplib.IMAP4,'_command',return_value='ok') as forward:
            self.assertEqual(client._command('UID','FETCH','1','(BODY.PEEK[])'),'ok')
            self.assertEqual(client._command('EXAMINE','INBOX'),'ok')
            self.assertEqual(forward.call_count,2)

    def test_body_read_uses_peek_and_sanitizes_html(self):
        from unittest.mock import Mock
        client=Mock()
        client.uid.return_value=('OK',[(b'1 (UID 3 FLAGS ())',b'From: sender@example.com\r\nSubject: hello\r\nContent-Type: text/html\r\n\r\n<p>Hi</p><script>evil()</script>')])
        result=mail.fetch(client,3)
        self.assertEqual(result['body'],'Hi')
        client.uid.assert_called_once_with('FETCH','3','(UID FLAGS BODY.PEEK[]<0.262144>)')

if __name__ == '__main__':
    unittest.main()
