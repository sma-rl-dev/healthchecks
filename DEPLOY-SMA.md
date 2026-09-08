# Healthchecks - Deployment, Seed, and Browser Notes

Fork of `healthchecks/healthchecks` at release tag **v4.4**
(`49924faadf0f24a846abc3acf3014b396fdc1f29`, 2026-08-31) plus tester-env
tooling on branch `tester-env-baseline`.

## Quick Start

```bash
./tester-env deploy    # Build web from editable source, start db+web, create superuser
./tester-env seed      # Populate deterministic 4-check baseline (idempotent)
./tester-env verify    # Assert login page 200 (localhost + host.docker.internal)
./tester-env reset     # compose down -v (removes containers AND db-data volume)
```

| Command  | Description |
|----------|-------------|
| `deploy` | `docker/.env` from `.env.example` (deterministic placeholders), `compose build web`, `up -d`, wait for 200, create superuser |
| `seed`   | `manage.py shell < docker/seed/seed_checks.py` (4 checks, 8 pings via real `Check.ping()`) |
| `verify` | `GET /accounts/login/` -> 200 on `localhost` and `Host: host.docker.internal` |
| `reset`  | `compose down -v` (image kept; cleanup via `scripts/rl-env gc --prune-images`) |
| `stop`   | `compose stop` (preserves data) |
| `logs`   | Tail web logs |
| `status` | RUNNING + URL, or NOT RUNNING |

Options: `--run-id <id>` isolates the compose project (containers/volumes);
`--port <port>` overrides the host port (default `8234`).

Image policy: the `docker-compose.tester-env.yml` overlay pins the web image
to `${IMAGE_TAG:-tester-env-healthchecks:dev}` (honoured from `scripts/rl-env`
content-addressed tags). `RUN_ID` never scopes the image name.

## Build

- `docker/Dockerfile` (python:3.14-slim, wheels stage) + `docker/docker-compose.yml`
  (postgres:16 + uwsgi `:8000`, migrations auto-run via uwsgi `hook-pre-app`).
- Overlay adds `8234:8000` (upstream `8000:8000` binding coexists).
- `docker/.env` is git-ignored; `ensure_env` derives it deterministically from
  `docker/.env.example`: `DB_PASSWORD`/`SECRET_KEY` fixed placeholders,
  `SITE_ROOT=http://localhost:8234`,
  `ALLOWED_HOSTS=localhost,127.0.0.1,host.docker.internal` (the
  `host.docker.internal` entry is required: browser MCP containers reach the
  app under that Host header and Django would 400 otherwise).

## Local URL

- App: `http://localhost:8234` (login: `http://localhost:8234/accounts/login/`)

## Credentials

- Email: `admin@example.org`
- Password: deterministic test placeholder in the `tester-env` script
  (`ADMIN_PASSWORD`); DB password / Django secret key are deterministic
  placeholders generated into the git-ignored `docker/.env`. No real secrets
  are committed. Email login-links / WebAuthn / REMOTE_USER are off;
  `REGISTRATION_OPEN=True` (upstream default); SMTP unconfigured (benign mail
  warnings in logs).

## Seed Data

`./tester-env seed` creates 4 checks in the admin's default project via the
real `Check.ping()` path (byte-identical across clean-volume
reset -> deploy -> seed -> verify cycles; re-seed idempotent):

- Nightly Database Backup (simple, Up, 5 pings, tags `prod database`)
- Weekly Sales Report (cron `0 7 * * 1`, Up, 3 pings, tag `reports`)
- Staging Deploy Hook (simple, New, 0 pings, tag `staging`)
- Legacy Billing Import (simple, Paused, 0 pings, tags `billing legacy`)

## Reset

```bash
./tester-env reset && ./tester-env deploy && ./tester-env seed && ./tester-env verify
```

Full reset -> deploy -> verify cycle passes from a clean volume; the superuser
is recreated deterministically (`manage.py createsuperuser --email/--password`;
upstream takes no `--noinput`/`--username` flags).

## Browser Verification

- Login page 200; form login as `admin@example.org` lands on the project
  checks page (`Log Out` + `Add Check` visible).
- Smoke: `Add Check` "Browser Smoke Check" (period 1 day, grace 1 hour,
  Last Ping Never) appeared in the list alongside "My First Check" —
  state-changing workflow visibly persisted.
- Seed: dashboard lists all 4 checks with expected Up/New/Paused badges and
  tags; details page shows 5 seeded events incl. the new -> up transition.
- Host root `/` -> 302 (normal redirect); `Host: host.docker.internal:8234`
  login page -> 200 ("Log In - Mychecks").
