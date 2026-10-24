"""Single-user login with revocable, opaque server-side sessions."""
import hashlib
import re
import secrets
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException, Request

COOKIE = '__Host-email-assist-session'
MAX_AGE = 24 * 60 * 60
IDLE_SECONDS = 60 * 60
LOGIN_WINDOW = 5 * 60
LOGIN_LIMIT = 10
hasher = PasswordHasher()


def initialize(db):
    with db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS web_sessions (
            token_hash text PRIMARY KEY, credential_version text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            last_seen timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS web_login_limit (
            id integer PRIMARY KEY CHECK(id=1), attempts integer NOT NULL DEFAULT 0,
            window_start timestamptz NOT NULL DEFAULT now())''')
        conn.execute('INSERT INTO web_login_limit(id) VALUES(1) ON CONFLICT DO NOTHING')


def credential_record(secret_dir):
    path = Path(secret_dir) / 'web-password-hash'
    if path.exists():
        encoded = path.read_text().strip()
        return encoded, hashlib.sha256(encoded.encode()).hexdigest()
    # Compatibility for existing installs: verify with Argon2 even when the
    # operator has not yet provisioned the optional persistent password hash.
    password = (Path(secret_dir) / 'web-password').read_text().strip()
    return hasher.hash(password), hashlib.sha256(password.encode()).hexdigest()


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def safe_next(value):
    if value in ('/', '/providers') or re.fullmatch(r'/email/[a-zA-Z0-9_-]{1,128}', value):
        return value
    return '/'


def same_origin(request, origin):
    if (request.headers.get('origin') != origin
            or request.headers.get('x-email-assist') != '1'):
        raise HTTPException(403, 'Refresh this page and try again')


def reserve_login_attempt(db):
    # Account-wide and persisted: cannot be bypassed by spoofing client IPs,
    # restarting the app, or switching usernames. Reserve before hashing.
    with db() as conn:
        row = conn.execute('''SELECT attempts,
            extract(epoch FROM now()-window_start) AS elapsed
            FROM web_login_limit WHERE id=1 FOR UPDATE''').fetchone()
        if row['elapsed'] >= LOGIN_WINDOW:
            conn.execute('UPDATE web_login_limit SET attempts=1,window_start=now() WHERE id=1')
        elif row['attempts'] >= LOGIN_LIMIT:
            retry = max(1, int(LOGIN_WINDOW - row['elapsed']) + 1)
            raise HTTPException(429, 'Too many attempts. Please try again shortly.',
                                headers={'Retry-After': str(retry)})
        else:
            conn.execute('UPDATE web_login_limit SET attempts=attempts+1 WHERE id=1')


def login(db, request, username, password, expected_username, encoded, version):
    reserve_login_attempt(db)
    valid_user = secrets.compare_digest(username.encode(), expected_username.encode())
    try:
        valid_password = hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        valid_password = False
    if not (valid_user and valid_password):
        # No WWW-Authenticate header: browsers must never display Basic auth.
        raise HTTPException(401, 'Username or password is incorrect.')
    token = secrets.token_urlsafe(32)
    with db() as conn:
        conn.execute('''DELETE FROM web_sessions WHERE expires_at <= now()
            OR last_seen <= now() - %s * interval '1 second'
            OR credential_version <> %s''', (IDLE_SECONDS, version))
        revoke(conn, request.cookies.get(COOKIE))
        conn.execute('''INSERT INTO web_sessions(token_hash,credential_version,expires_at)
            VALUES(%s,%s,now()+%s * interval '1 second')''', (token_hash(token), version, MAX_AGE))
        conn.execute('UPDATE web_login_limit SET attempts=0,window_start=now() WHERE id=1')
    return token


def authenticated(db, request, version):
    token = request.cookies.get(COOKIE, '')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{43}', token):
        return False
    with db() as conn:
        row = conn.execute('''UPDATE web_sessions SET last_seen=now()
            WHERE token_hash=%s AND credential_version=%s AND expires_at > now()
            AND last_seen > now() - %s * interval '1 second' RETURNING token_hash''',
            (token_hash(token), version, IDLE_SECONDS)).fetchone()
    return bool(row)


def revoke(conn, token):
    if token:
        conn.execute('DELETE FROM web_sessions WHERE token_hash=%s', (token_hash(token),))


def set_cookie(response, token):
    response.set_cookie(COOKIE, token, max_age=MAX_AGE, secure=True, httponly=True,
                        samesite='strict', path='/')


def clear_cookie(response):
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='strict', path='/')
