# Email Assist

Private, read-only daily inbox triage for Proton Mail Bridge. A small FastAPI
app presents the ten highest-priority emails needing a reply, with scores,
reasons, suggested next steps, and text previews.

## Configuration

Copy the commented [`.env.example`](.env.example) to `.env`. It includes local
browser defaults and placeholders for your AI endpoint, database, networks,
and storage. Replace the AI placeholders and configure your own services before
starting the app. Set `PUBLIC_ORIGIN` to the exact origin you
use in your browser (scheme and hostname, optional port, no trailing slash).
Set `WEB_USERNAME` for the app login. Set `IMAP_USERNAME` if you supply your
Bridge password as a file; otherwise enter both Bridge credentials in the UI.
Personal hostnames and account names belong in your ignored `.env` file.
Compose injects these variables into the app; running Python directly requires
setting them in the process environment.

You need PostgreSQL, an OpenAI-compatible AI endpoint, and Proton Mail Bridge
listening on its standard host loopback IMAP port `127.0.0.1:1143`. Set the
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

Create your configured storage directories, restrict their permissions, and
make them accessible to container UID 1000. Put these files in `SECRETS_DIR`:

| File | Contents |
| --- | --- |
| `web-password` | A strong, unique app login password |
| `db-password` | Password for the dedicated PostgreSQL role |
| `ai-key` | API key for your configured AI endpoint |
| `bridge-cert.pem` | Certificate copied from the trusted local Bridge listener |
| `imap-password` (optional) | Bridge-generated IMAP password |

Use mode 600 for credentials. The Bridge password is separate from your Proton
account password. UI-provided IMAP credentials live in `state/`, also mode 600;
a file-provided password takes precedence over the UI-provided password.
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
origin. Local testing with the default port can use `PUBLIC_ORIGIN=http://localhost:8000`.
If you run Compose from another directory, pass `--env-file /path/to/.env`.

## Use

Log in with your configured `WEB_USERNAME` and `web-password`. Enter the Bridge
IMAP username and password if needed, then press **Refresh inbox**.
**Top 10** shows the highest-scored emails needing a reply. **All inbox** shows
all titles with search and pagination. Each title links to its preview,
sender/date, score, reason, and recommended next step. **Copy subject** and
**Open Proton Mail** help locate the original; Bridge does not provide Proton
web message IDs for direct links.

An inbox check runs on startup and daily at/after 07:00 in your configured `TZ`.
Refresh scans new mail, updates flags/removals, and scores new emails or emails
whose analysis is at least seven days old. It does not bypass the seven-day
cache. Failed analyses preserve existing scores and dates and are retried.
Higher scores mean more urgency and importance. Answered messages and
recommendations requiring no response are excluded from Top 10.

## Architecture and privacy

- FastAPI serves the UI/API and one background inbox worker; PostgreSQL stores
  previews and scores. Protect database access and backups as sensitive mail.
- Email subjects, senders, dates, flags, and bounded text previews go to the
  configured AI endpoint. A proxy/model alias may route to a cloud provider;
  check its routing and data policy before connecting your inbox.
- Email content is untrusted data. The AI has no tools, credentials, or ability
  to act. Strict result validation requires exactly the supplied message IDs,
  integer scores in range, and bounded explanations.
- The IMAP client uses `EXAMINE`, `UID SEARCH`, and `BODY.PEEK`. A command
  allowlist blocks message mutations and non-PEEK body fetches. There is no
  SMTP connection or send endpoint. The Bridge credential remains capable of
  writes in other clients.
- A separate relay exposes a mode-600 UNIX socket connected only to loopback
  IMAP. It stores no credentials and publishes no TCP listener. The app uses
  ordinary Docker networks, without the Docker socket or Bridge state mounts.
- STARTTLS trusts the certificate copied from the local Bridge endpoint and
  checks its `127.0.0.1` identity. Changed certificates fail closed.
- Basic authentication over HTTPS protects inbox data. POST endpoints check
  the configured origin and require a custom header. Email/model text is
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
refresh can retry sooner; simultaneous refresh requests share one worker.
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
AI response validation, and configuration/authentication boundaries. Run them
in an environment with `requirements.txt` installed:

```sh
python -m unittest discover -s tests -p test_safety.py -v
python -m unittest discover -s tests -p test_web.py -v
```

GitHub Actions builds the Docker image and runs these safety and HTTP smoke
tests with networking disabled. The smoke tests check authenticated page
rendering, static assets, security headers, and API authentication, skipping
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
reuse/expiry, UIDVALIDITY resets, answered/removed mail, and preserving scores
on AI failure. Run them against a test database with the corresponding `PG*`
environment variables; they mock IMAP and AI and never read the real inbox.
