# Email Assist

Private, read-only daily inbox triage across any number of mail providers:
standard IMAP over TLS (Zoho Mail, Fastmail, Gmail, and others) and Proton Mail
Bridge. A small FastAPI app presents the ten highest-priority emails needing a
reply across all inboxes or for one provider, with scores, reasons, suggested
next steps, and text previews.

## Configuration

Copy the commented [`.env.example`](.env.example) to `.env`. It includes local
browser defaults and placeholders for your AI endpoint, database, networks,
and storage. Replace the AI placeholders and configure your own services before
starting the app. Set `PUBLIC_ORIGIN` to the exact origin you
use in your browser (scheme and hostname, optional port, no trailing slash).
Set `WEB_USERNAME` for the app login. Add mail providers on the app's
**Providers** page or, if you prefer, in `.env`; `.env.example` includes a
commented example of setting providers with environment variables (see
[Mail providers](#mail-providers)).
Personal hostnames and account names belong in your ignored `.env` file.
Compose injects these variables into the app; running Python directly requires
setting them in the process environment.

You need PostgreSQL and an OpenAI-compatible AI endpoint. Bridge providers also
need Proton Mail Bridge listening on its standard host loopback IMAP port
`127.0.0.1:1143`; IMAP providers connect directly from the app container. Set the
database connection and AI settings for your own services. The Compose file
joins two existing Docker networks; set `DATABASE_NETWORK` and `AI_NETWORK`
to networks where those services are reachable. Create or provision those
networks and services before starting the app. Provision a dedicated database
and a role without superuser, create-db, create-role, or replication rights;
the app creates its own tables.

| Variable | Purpose / default |
| --- | --- |
| `AI_BASE_URL`, `AI_MODEL` | Your endpoint's API base URL and model name; required |
| `PGHOST`, `PGDATABASE`, `PGUSER` | Database host, database, and login role |
| `DATABASE_NETWORK`, `AI_NETWORK` | External Docker network names |
| `SECRETS_DIR`, `STATE_DIR`, `SOCKET_DIR` | Host storage; defaults to `./secrets`, `./state`, `./run` |
| `HOST_PORT` | Loopback HTTP port; defaults to `8000` |
| `TZ` | Daily check timezone; defaults to `UTC` |
| `MAIL_PROVIDERS`, `MAIL_<NAME>_*` | Optional mail providers defined by environment; see below |

Create your configured storage directories, restrict their permissions, and
make them accessible to container UID 1000. Put these files in `SECRETS_DIR`:

| File | Contents |
| --- | --- |
| `web-password` | A strong, unique app login password (compatibility / operator recovery) |
| `web-password-hash` (recommended) | Argon2id hash of the app password; takes precedence over `web-password` |
| `db-password` | Password for the dedicated PostgreSQL role |
| `ai-key` | API key for your configured AI endpoint |
| `bridge-cert.pem` | Certificate copied from the trusted local Bridge listener (Bridge providers only) |
| `<name>-imap-password` (optional) | Mailbox password for provider `<name>` |

Use mode 600 for credentials. The Bridge password is separate from your Proton
account password. UI-provided passwords live in `state/<name>-imap-password`,
also mode 600. A secrets file takes precedence over `MAIL_<NAME>_PASSWORD`,
which takes precedence over a password entered in the UI.
Secrets, environment files, runtime state, keys, and certificates are ignored
by Git and excluded from the Docker build context.

```sh
cp .env.example .env
# Edit .env and provision the database, secrets and directories above.
docker compose up -d --build
docker compose ps
docker logs email-assist --tail 30
```

The app binds only to host loopback on your configured `HOST_PORT`. Use an HTTPS reverse proxy
with private network access controls, and set `PUBLIC_ORIGIN` to its external
origin. Session cookies require HTTPS, including browser testing. Set `PUBLIC_ORIGIN` to the exact HTTPS origin (without a trailing slash).
If you run Compose from another directory, pass `--env-file /path/to/.env`.

## Mail providers

Email Assist reads any number of mailboxes. Each provider has a name,
connection type, host and port (IMAP only), username, password, optional
webmail link, and optional scoring guidance that is added to the AI prompt,
such as "prioritize clients and invoices; rank SaaS notifications low".
For Zoho, Gmail, and similar services, enable IMAP access in their settings
and use an app-specific password; the username is usually the full email
address. Only implicit TLS (usually port 993) is supported; plain IMAP and
STARTTLS servers other than Bridge are not.

### In the app

The **Providers** page (`/providers`, linked in the header) adds, edits, and
removes providers. **Test connection** logs in read-only with the form's
values, before or after saving, and reports the inbox size or what failed.

### With environment variables (optional)

[`.env.example`](.env.example) shows how to set providers in `.env` instead;
copy its commented `MAIL_*` lines and edit them. List provider names in
`MAIL_PROVIDERS`, then set `MAIL_<NAME>_*` for each. Names use lowercase
letters, digits, and hyphens; in variable names they become uppercase with
underscores, so `side-project` uses `MAIL_SIDE_PROJECT_HOST`.

```sh
MAIL_PROVIDERS=proton,work
MAIL_PROTON_LABEL=Personal
MAIL_PROTON_TYPE=bridge
MAIL_WORK_LABEL=Business
MAIL_WORK_HOST=imappro.zoho.com
MAIL_WORK_USERNAME=you@yourcompany.com
```

| Suffix | Meaning | Default |
| --- | --- | --- |
| `_LABEL` | Display name | The name, capitalized |
| `_TYPE` | `imap` or `bridge` | `imap` |
| `_HOST`, `_PORT` | IMAP server; ignored for `bridge` | Host required for `imap`; port `993` |
| `_USERNAME`, `_PASSWORD` | Mailbox login | None |
| `_WEBMAIL` | `https://` link for **Open webmail** | None |
| `_FOCUS` | Extra scoring guidance | General guidance |

Settings are validated at startup; invalid values stop the app with an error.
Non-empty fields set this way are locked in the UI and reapplied on every
start; unset fields stay editable there, so you can, for example, enter the
username in the app. Passwords come from `secrets/<name>-imap-password`, then
`MAIL_<NAME>_PASSWORD`, then the UI; prefer the secrets file, because container
environment variables are visible through `docker inspect`. Environment
providers can't be removed in the UI. Removing one from `MAIL_PROVIDERS` keeps
it, with its emails and scores, as an ordinary provider you can edit or remove.
The Compose file passes the whole `.env` to the app, so new `MAIL_*`
variables need no Compose changes. Providers from both sources rank together.

### Upgrading from a single mailbox

The first start of this version migrates the single Proton mailbox to a
Bridge provider named `proton`, keeping scores, their dates, and sync history.
Cached emails get new provider-scoped IDs, so older `/email/...` links open
**Email not found**. The Bridge username comes from `state/imap-username` or,
failing that, `IMAP_USERNAME`. A UI-saved password moves to
`state/proton-imap-password`; rename a `secrets/imap-password` file to
`secrets/proton-imap-password` yourself. To manage it from the environment
afterwards, add `proton` to `MAIL_PROVIDERS`.

## Use

The **Sign in** page uses your configured `WEB_USERNAME` and existing app password.
Use **Sign out** to revoke the current browser session. Sessions expire after
one hour without requests or 24 hours from sign-in; signing in issues a new token.
The browser receives an opaque `Secure`, `HttpOnly`, `SameSite=Strict`, host-only
cookie, never the password. Only a SHA-256 hash of that random token is stored
in PostgreSQL. Password-hash changes revoke existing sessions.

Login is limited to ten attempts per five minutes for the single account,
including across container restarts. Incorrect usernames and passwords share
the same error. Login and other POST requests require the exact configured
Origin and a custom header. Browser clients redirect to the login page when
the session expires; unauthenticated APIs return 401 without a Basic challenge.

Enter your configured app credentials to sign in, add a provider on the
**Providers** page if none exists, then press **Refresh inbox**. With two or more providers, tabs filter
to **All inboxes** or a single provider; stats, refresh, and lists follow the
selection, and cards in **All inboxes** name their provider. Each provider has
its own credentials, inbox, scores, and refresh; one failing does not affect
the others.
**Top 10** shows the highest-scored emails needing a reply, then fills up with
the next highest-scored emails. **All inbox** shows
all titles with search and pagination. Each title links to its preview,
sender/date, score, reason, and recommended next step. **Copy subject** and
**Open webmail** (when the provider has a webmail link) help locate the
original; IMAP does not provide web message IDs for direct links.

An inbox check runs for every provider on startup, when its credentials are
added, and daily at/after 07:00 in your configured `TZ`.
Refresh scans new mail, updates flags/removals, and scores new emails or emails
whose analysis is at least seven days old. It does not bypass the seven-day
cache. Failed analyses preserve existing scores and dates and are retried.
Higher scores mean more urgency and importance. Answered messages are
excluded from Top 10.

## Architecture and privacy

- FastAPI serves the UI/API and one background worker per provider; PostgreSQL stores
  previews and scores. Protect database access and backups as sensitive mail.
- Email subjects, senders, dates, flags, and bounded text previews go to the
  configured AI endpoint. A proxy/model alias may route to a cloud provider;
  check its routing and data policy before connecting your inbox.
- Email content is untrusted data. The AI has no tools, credentials, or ability
  to act. Strict result validation requires exactly the supplied message IDs,
  integer scores in range, and bounded explanations.
- The IMAP client uses `EXAMINE`, `UID SEARCH`, and `BODY.PEEK`. A command
  allowlist blocks message mutations and non-PEEK body fetches. There is no
  SMTP connection or send endpoint. Mailbox credentials remain capable of
  writes in other clients.
- IMAP providers connect directly over implicit TLS, verified against the
  system certificate store with TLS 1.2 or newer. Connection tests can reach
  any host and port, so only trusted users should have the app login.
- A separate relay exposes a mode-600 UNIX socket connected only to loopback
  IMAP. It stores no credentials and publishes no TCP listener. The app uses
  ordinary Docker networks, without the Docker socket or Bridge state mounts.
- STARTTLS trusts the certificate copied from the local Bridge endpoint and
  checks its `127.0.0.1` identity. Changed certificates fail closed.
- Server-side cookie sessions over HTTPS protect inbox data. Passwords are
  verified using Argon2id; POST endpoints check the exact configured origin
  and require a custom header. Email/model text is
  rendered as text; remote images and email links are not loaded. CSP and
  no-store headers apply. Access logging is disabled.
- At most the first 256 KiB of each MIME message is fetched; a 16,000-character
  text preview is stored/analyzed. Attachments are not analyzed. Mail removed
  from INBOX disappears from lists, but cached previews remain in the database
  for stable app permalinks.

Host/Docker administrators can access mounted secrets and cached mail. Keep
runtime data and database backups outside the public repository.

## Maintenance and verification

The daily worker retries failed runs at most hourly after 07:00. A manual
refresh can retry sooner; simultaneous refresh requests for a provider share
its worker.
Partial runs retain completed scores.

If Bridge rotates its certificate, copy the new certificate only after
verifying the trusted local endpoint, then restart the app:

```sh
openssl s_client -starttls imap -connect 127.0.0.1:1143 -servername 127.0.0.1 \
  </dev/null 2>/dev/null | openssl x509 -outform PEM \
  > ./secrets/bridge-cert.pem
docker compose restart app
```

Use your configured `SECRETS_DIR` if it differs from the default `./secrets`.

Safety tests cover IMAP command blocking, non-PEEK rejection, MIME sanitization,
AI response validation, provider settings and password precedence, and
configuration/authentication boundaries. Run them
in an environment with `requirements.txt` installed:

```sh
python -m unittest discover -s tests -p test_safety.py -v
python -m unittest discover -s tests -p test_web.py -v
```

GitHub Actions builds the Docker image and runs these safety and HTTP smoke
tests with networking disabled. The smoke tests check authenticated page
rendering (inbox and **Providers**), static assets, security headers, and API authentication, skipping
the database/inbox startup hooks. A separate Gitleaks job scans full Git
history. CI needs no inbox, database, AI credentials, or custom GitHub secrets.

After both checks pass on the default branch (`main`), the workflow publishes
`ghcr.io/<owner>/<repo>:latest` and `ghcr.io/<owner>/<repo>:sha-<full-commit-sha>`
using GitHub's automatic token. Pull requests run checks without publishing.
Manual runs publish only when targeting the default branch. The image targets
`linux/amd64` and includes build provenance and an SBOM. Actions are pinned to
commit SHAs, and Dependabot checks those pins monthly. After the first push,
set the GHCR package visibility to public if you want anonymous image pulls.

Integration tests in `tests/test_sync.py` require PostgreSQL and the mounted
`db-password` file. They create and drop a disposable schema and cover cache
reuse/expiry, UIDVALIDITY resets, answered/removed mail, preserving scores on
AI failure, provider isolation and ranking across providers, provider
create/edit/remove, environment locking, and the single-mailbox upgrade. Run
them against a test database with the corresponding `PG*` environment variables; they mock IMAP and AI and never read the real inbox.

### Provision or rotate the password hash

The password hash can be created from the existing mode-600 `web-password`
without placing a password in shell arguments or logs:

```sh
docker compose run --rm --no-deps -v "${SECRETS_DIR:-./secrets}:/hash-output" app python -c \
  "from pathlib import Path; from argon2 import PasswordHasher; import os; os.umask(0o077); p=Path('/hash-output'); (p/'web-password-hash').write_text(PasswordHasher().hash((p/'web-password').read_text().strip()))"
```

Provision `web-password-hash` on the host and mount it with the other secrets.
The app uses that hash when present; a plaintext credential file is optional
in this mode and can be kept separately for operator recovery. To change the
password, replace the hash with one for the new password. Existing sessions
are rejected immediately on subsequent requests.

Session tables are additive. Apart from the one-time single-mailbox upgrade
above, deployments do not rewrite cached email rows. Both are covered by the existing database backups. Login attempt records and
session tokens are never logged or returned by inbox APIs.
