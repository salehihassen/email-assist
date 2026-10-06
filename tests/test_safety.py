import unittest
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials
from starlette.requests import Request
import app
import mail

class Safety(unittest.TestCase):
    def test_auth_uses_configured_username_and_secret_password(self):
        with patch.object(app, 'WEB_USERNAME', 'custom-user'), patch.object(app, 'secret', return_value='test-password'):
            app.auth(HTTPBasicCredentials(username='custom-user', password='test-password'))
            for username, password in [('admin', 'test-password'), ('custom-user', 'wrong-password')]:
                with self.assertRaises(HTTPException) as error:
                    app.auth(HTTPBasicCredentials(username=username, password=password))
                self.assertEqual(error.exception.status_code, 401)

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

    def test_mailbox_username_from_env_or_saved_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secrets_dir = root / 'secrets'
            state_dir = root / 'state'
            secrets_dir.mkdir()
            state_dir.mkdir()
            with patch.object(app, 'SECRET', secrets_dir), patch.object(app, 'STATE', state_dir), \
                 patch.dict(os.environ, {'IMAP_USERNAME': 'configured@example.test'}):
                self.assertEqual(app.mailbox_credentials(), ('configured@example.test', ''))
                (state_dir / 'imap-username').write_text('saved@example.test')
                (state_dir / 'imap-password').write_text('saved-password')
                self.assertEqual(app.mailbox_credentials(), ('saved@example.test', 'saved-password'))
                (secrets_dir / 'imap-password').write_text('mounted-password')
                self.assertEqual(app.mailbox_credentials(), ('saved@example.test', 'mounted-password'))

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
        client = mail.UnixIMAP.__new__(mail.UnixIMAP)
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
