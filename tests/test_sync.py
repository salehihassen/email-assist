"""Uses a disposable schema in the dedicated email_assist database."""
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import psycopg
from fastapi import HTTPException
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
        with app.db() as c:
            c.execute("INSERT INTO providers(id,label,type,username) VALUES('proton','Personal','bridge','me@proton.test')")
            c.execute("INSERT INTO providers(id,label,type,host,port,username,focus) VALUES('zoho','Business','imap','imap.example.test',993,'me@work.test','Clients first.')")
        self.client=Mock()
        self.client.__enter__=Mock(return_value=self.client)
        self.client.__exit__=Mock(return_value=False)
        self.client.response.return_value=('UIDVALIDITY',[b'11'])
        self.client.uid.return_value=('OK',[b'1 (UID 1 FLAGS ())'])
        self.item=dict(id='message-one',uid=1,message_id='<one@example.test>',subject='Reply requested',sender='test@example.test',sent_at=datetime.now(timezone.utc),body='Can you reply today?',flags=[],truncated=False)
        self.patches=[patch.object(app.mail,'connect',return_value=self.client),patch.object(app.mail,'inbox_uids',return_value=[1]),
                      patch.object(app.mail,'fetch',return_value=self.item),patch.object(app,'password',return_value=('test','file')),
                      patch.dict(app.jobs,clear=True)]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in self.patches:p.stop()
        self.db_patch.stop()
        with self.real_db() as c:c.execute('DROP SCHEMA '+self.schema+' CASCADE')

    def scores(self,pid='proton',item='message-one'):
        key=app.email_key(pid,item)
        return {key:dict(id=key,score=88,response_needed=True,reason='Needs reply today',suggested_action='Answer question')}

    def run_sync(self,pid='proton'):
        self.assertTrue(app.job(pid)['lock'].acquire(blocking=False))
        app.sync(pid)
        self.assertIsNone(app.job(pid)['status']['error'])

    def test_cache_reuse_expiry_and_uidvalidity(self):
        with patch.object(app,'analyze',return_value=self.scores()) as ai:
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
        with patch.object(app,'analyze',return_value=self.scores()):self.run_sync()
        self.client.uid.return_value=('OK',[b'1 (UID 1 FLAGS (\\Answered))'])
        self.run_sync()
        self.assertEqual(app.emails(top=True)['total'],0)
        self.assertEqual(app.emails()['total'],1)
        with patch.object(app.mail,'inbox_uids',return_value=[]):self.run_sync()
        self.assertEqual(app.emails()['total'],0)

    def test_model_failure_preserves_old_score_and_date(self):
        with patch.object(app,'analyze',return_value=self.scores()):self.run_sync()
        with app.db() as c:
            c.execute("UPDATE emails SET analyze_date=now()-interval '8 days'")
            old=c.execute('SELECT score,analyze_date FROM emails').fetchone()
        with patch.object(app,'analyze',side_effect=RuntimeError('invalid output')):
            self.assertTrue(app.job('proton')['lock'].acquire(blocking=False));app.sync('proton')
        with app.db() as c:new=c.execute('SELECT score,analyze_date FROM emails').fetchone()
        self.assertEqual(old,new)
        self.assertIn('could not be scored',app.job('proton')['status']['error'])

    def test_providers_are_isolated_and_ranked_together(self):
        with patch.object(app,'analyze',return_value=self.scores()) as ai:self.run_sync()
        app.mail.connect.assert_called_with('me@proton.test','test',None,993)
        self.assertEqual(ai.call_args.args[1],'')
        work=self.scores('zoho','message-two')
        next(iter(work.values()))['score']=95
        with patch.object(app.mail,'fetch',return_value=self.item|{'id':'message-two'}),patch.object(app,'analyze',return_value=work) as ai:
            self.run_sync('zoho')
        self.assertEqual(ai.call_args.args[1],'Clients first.')
        app.mail.connect.assert_called_with('me@work.test','test','imap.example.test',993)
        self.assertEqual([e['provider'] for e in app.emails(top=True)['emails']],['zoho','proton'])
        self.assertEqual([e['provider'] for e in app.emails(provider='proton')['emails']],['proton'])
        with patch.object(app.mail,'inbox_uids',return_value=[]):self.run_sync('zoho')
        self.assertEqual(app.emails(provider='zoho')['total'],0)
        self.assertEqual(app.emails()['total'],1)
        self.assertEqual({p['id']:p['inbox'] for p in app.get_status()['providers']},{'proton':1,'zoho':0})

    def test_create_update_and_delete_provider(self):
        with patch.object(app,'trigger') as trigger,patch.object(app,'save_password') as save:
            pid=app.create_provider(app.ProviderIn(label='Business',host='imap.other.test',username='a@b.test',password='pw'))['id']
            self.assertEqual(pid,'business');save.assert_called_once_with('business','pw');trigger.assert_called_with('business')
            self.assertEqual(app.create_provider(app.ProviderIn(label='Business',host='imap.other.test'))['id'],'business-2')
            app.update_provider('business',app.ProviderIn(label='Work',host='imap.new.test',port=1993,username='a@b.test'))
        saved=app.get_provider('business')
        self.assertEqual((saved['label'],saved['host'],saved['port']),('Work','imap.new.test',1993))
        with patch.object(app,'analyze',return_value=self.scores('business')):self.run_sync('business')
        app.delete_provider('business')
        with app.db() as c:
            self.assertEqual(c.execute("SELECT count(*) AS n FROM emails WHERE provider='business'").fetchone()['n'],0)
        with self.assertRaises(HTTPException):app.get_provider('business')

    def test_environment_fields_are_locked(self):
        env={'work':dict(config=app.ProviderConfig(label='Work',host='imap.env.test').model_dump(),locked=['host','label'],password='')}
        with patch.object(app,'ENV_PROVIDERS',env):
            app.init_db()
            with patch.object(app,'trigger'):
                app.update_provider('work',app.ProviderIn(label='Renamed',host='imap.evil.test',username='me@work.test'))
            saved=app.get_provider('work')
            self.assertEqual((saved['label'],saved['host'],saved['username']),('Work','imap.env.test','me@work.test'))
            env['work']['config']['host']='imap.moved.test'
            app.init_db()
            self.assertEqual((app.get_provider('work')['host'],app.get_provider('work')['username']),('imap.moved.test','me@work.test'))
            with self.assertRaises(HTTPException) as error:app.delete_provider('work')
            self.assertEqual(error.exception.status_code,409)

    def test_single_mailbox_install_migrates_to_proton_provider(self):
        with app.db() as c:
            c.execute('DROP TABLE emails');c.execute('DROP TABLE providers')
            c.execute('''CREATE TABLE emails(id text PRIMARY KEY,uid bigint NOT NULL,uidvalidity text NOT NULL,message_id text NOT NULL,
                subject text NOT NULL,sender text NOT NULL,sent_at timestamptz,body text NOT NULL,flags jsonb NOT NULL,
                truncated boolean NOT NULL DEFAULT false,in_inbox boolean NOT NULL DEFAULT true,score integer,analyze_date timestamptz,
                response_needed boolean,reason text,suggested_action text,model text,last_seen timestamptz NOT NULL DEFAULT now())''')
            c.execute("INSERT INTO emails(id,uid,uidvalidity,message_id,subject,sender,body,flags,score,analyze_date) VALUES('old',1,'11','<x>','Hi','a@b','body','[]',70,now())")
            c.execute('CREATE TABLE sync_state(id integer PRIMARY KEY,last_scan timestamptz,last_success timestamptz,last_error text,last_analyzed integer NOT NULL DEFAULT 0,last_cached integer NOT NULL DEFAULT 0)')
            c.execute("INSERT INTO sync_state VALUES(1,now(),now(),NULL,4,2)")
        with patch.dict(app.os.environ,IMAP_USERNAME='me@proton.test'):app.init_db()
        provider=app.get_provider('proton')
        self.assertEqual((provider['type'],provider['username'],provider['last_analyzed']),('bridge','me@proton.test',4))
        with app.db() as c:
            row=c.execute('SELECT id,provider,score FROM emails').fetchone()
            self.assertIsNone(c.execute("SELECT to_regclass('sync_state') AS t").fetchone()['t'])
        self.assertEqual(row,{'id':app.email_key('proton','old'),'provider':'proton','score':70})

if __name__ == '__main__':unittest.main()
