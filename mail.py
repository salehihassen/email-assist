"""Read-only IMAP reader. Never SELECT writable or issue message mutation commands."""
import email
import hashlib
import imaplib
import re
import socket
import ssl
from datetime import datetime, timezone
from email import policy
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup

class UnixIMAP(imaplib.IMAP4):
    def _command(self, name, *args):
        # Keep writes impossible through this client, including future code changes.
        if name not in {'CAPABILITY', 'STARTTLS', 'LOGIN', 'EXAMINE', 'UID', 'LOGOUT'}:
            raise ValueError('IMAP command is outside the read-only allowlist')
        if name == 'UID':
            if not args or args[0] not in {'SEARCH', 'FETCH'}:
                raise ValueError('Only UID SEARCH and FETCH are allowed')
            if args[0] == 'FETCH':
                parts = str(args[-1]).upper()
                if 'BODY[' in parts or 'RFC822' in parts:
                    raise ValueError('Message bodies must be fetched using BODY.PEEK')
        return super()._command(name, *args)

    def _create_socket(self, timeout):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect('/mail/imap.sock')
        return sock

def connect(username, password, cert='/run/secrets/bridge-cert.pem'):
    if any(c in username + password for c in ('\r', '\n', '\x00')):
        raise ValueError('Invalid credential characters')
    client = UnixIMAP(host='127.0.0.1', timeout=60)
    try:
        # Trust only the certificate copied from local Bridge listener.
        ctx = ssl.create_default_context(cafile=cert)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        client.starttls(ssl_context=ctx)
        client.login(username, password)
        typ, _ = client.select('INBOX', readonly=True)  # Sends EXAMINE.
        if typ != 'OK':
            raise RuntimeError('Cannot examine inbox')
        return client
    except Exception:
        try:
            client.logout()
        except Exception:
            pass
        raise

def inbox_uids(client):
    typ, rows = client.uid('SEARCH', None, 'ALL')
    if typ != 'OK':
        raise RuntimeError('Inbox search failed')
    return [int(x) for x in rows[0].split()]

def fetch(client, uid):
    typ, rows = client.uid('FETCH', str(uid), '(UID FLAGS BODY.PEEK[]<0.262144>)')
    if typ != 'OK':
        raise RuntimeError('Message read failed')
    literals = [r for r in rows if isinstance(r, tuple)]
    if not literals:
        return None  # Message removed between SEARCH and FETCH.
    meta, raw = literals[0]
    msg = email.message_from_bytes(raw, policy=policy.default)
    body = msg.get_body(preferencelist=('plain', 'html'))
    text = ''
    if body is not None:
        try:
            text = body.get_content()
        except (LookupError, UnicodeError):
            text = body.get_payload(decode=True).decode('utf-8', errors='replace')
        if body.get_content_type() == 'text/html':
            soup = BeautifulSoup(text, 'html.parser')
            for node in soup(['script', 'style', 'head']):
                node.decompose()
            text = soup.get_text(' ', strip=True)
    text = text[:16000]
    try:
        sent = parsedate_to_datetime(str(msg.get('Date', '')))
        if sent.tzinfo is None:
            sent = sent.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        sent = None
    message_id = str(msg.get('Message-ID', '')).strip()
    # Exact content identity deduplicates analyses after UIDVALIDITY changes.
    content_hash = hashlib.sha256(raw).hexdigest()
    key = hashlib.sha256((message_id + ':' + content_hash).encode()).hexdigest()
    flags = [x.decode(errors='replace') for x in imaplib.ParseFlags(meta)]
    return dict(id=key, uid=uid, message_id=message_id, subject=str(msg.get('Subject', '(No subject)')),
                sender=str(msg.get('From', '')), sent_at=sent, body=text, flags=flags,
                truncated=len(raw) >= 262144)
