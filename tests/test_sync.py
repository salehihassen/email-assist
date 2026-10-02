"""Uses a disposable schema in the dedicated email_assist database."""
import json
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import psycopg
from psycopg.rows import dict_row
import app

class Sync(unittest.TestCase):
    def setUp(self):
        self.schema='test_'+uuid.uuid4().hex
        with app.db() as c:
            c.execute('CREATE SCHEMA '+self.schema)
        self.real_db=app.db
        def isolated_db():
            return psycopg.connect(password=app.secret('db-password'),options='-c search_path='+self.schema,row_factory=dict_row)
        self.db_patch=patch.object(app,'db',isolated_db);self.db_patch.start()
        app.init_db()
        self.client=Mock()
        self.client.__enter__=Mock(return_value=self.client)
        self.client.__exit__=Mock(return_value=False)
        self.client.response.return_value=('UIDVALIDITY',[b'11'])
        self.client.uid.return_value=('OK',[b'1 (UID 1 FLAGS ())'])
        self.item=dict(id='message-one',uid=1,message_id='<one@example.test>',subject='Reply requested',sender='test@example.test',sent_at=datetime.now(timezone.utc),body='Can you reply today?',flags=[],truncated=False)
        self.scores={'message-one':dict(id='message-one',score=88,response_needed=True,reason='Needs reply today',suggested_action='Answer question')}
        self.patches=[patch.object(app.mail,'connect',return_value=self.client),patch.object(app.mail,'inbox_uids',return_value=[1]),patch.object(app.mail,'fetch',return_value=self.item),patch.object(app,'mailbox_credentials',return_value=('test','test'))]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in self.patches:p.stop()
        self.db_patch.stop()
        with self.real_db() as c:c.execute('DROP SCHEMA '+self.schema+' CASCADE')

    def run_sync(self):
        self.assertTrue(app.lock.acquire(blocking=False))
        app.sync()
        self.assertIsNone(app.status['error'])

    def test_cache_reuse_expiry_and_uidvalidity(self):
        with patch.object(app,'analyze',return_value=self.scores) as ai:
            self.run_sync();self.assertEqual(ai.call_count,1)
            with app.db() as c:first=c.execute('SELECT * FROM emails').fetchone()
            self.run_sync();self.assertEqual(ai.call_count,1)
            with app.db() as c:second=c.execute('SELECT * FROM emails').fetchone()
            self.assertEqual(first['analyze_date'],second['analyze_date'])
            self.client.response.return_value=('UIDVALIDITY',[b'12'])
            self.run_sync();self.assertEqual(ai.call_count,1)
            with app.db() as c:
                c.execute("UPDATE emails SET analyze_date=now()-interval '7 days'")
            self.run_sync();self.assertEqual(ai.call_count,2)

    def test_disappeared_and_answered_messages_excluded(self):
        with patch.object(app,'analyze',return_value=self.scores):self.run_sync()
        self.client.uid.return_value=('OK',[b'1 (UID 1 FLAGS (\\Answered))'])
        self.run_sync()
        self.assertEqual(app.emails(top=True)['total'],0)
        self.assertEqual(app.emails()['total'],1)
        with patch.object(app.mail,'inbox_uids',return_value=[]):self.run_sync()
        self.assertEqual(app.emails()['total'],0)

    def test_model_failure_preserves_old_score_and_date(self):
        with patch.object(app,'analyze',return_value=self.scores):self.run_sync()
        with app.db() as c:
            c.execute("UPDATE emails SET analyze_date=now()-interval '8 days'")
            old=c.execute('SELECT score,analyze_date FROM emails').fetchone()
        with patch.object(app,'analyze',side_effect=RuntimeError('invalid output')):
            self.assertTrue(app.lock.acquire(blocking=False));app.sync()
        with app.db() as c:new=c.execute('SELECT score,analyze_date FROM emails').fetchone()
        self.assertEqual(old,new)
        self.assertIn('could not be scored',app.status['error'])

if __name__ == '__main__':unittest.main()
