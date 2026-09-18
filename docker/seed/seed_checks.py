"""Deterministic acceptance seed for the Healthchecks prospect.

Creates the smallest coherent product state for useful browser assertions
(cron-monitoring theme: small SaaS ops setup). Idempotent: existing seed
checks (matched by name within the admin's default project) are deleted
first, then recreated with fixed attributes; ping history is generated
through the real Check.ping() code path so Ping rows, n_pings, last_ping,
status, and alert_after are all consistent.

Run inside the web container:
    ./manage.py shell < docker/seed/seed_checks.py
"""

from datetime import timedelta
import json

from django.contrib.auth.models import User
from hc.accounts.models import Project
from hc.api.models import Channel, Check

ADMIN_EMAIL = "admin@example.org"

# Deterministic Ntfy integration: name is the idempotency key.
NTFY_NAME = "Ops Ntfy Feed"
NTFY_TOPIC = "tester-env-ops-alerts"
NTFY_URL = "https://ntfy.sh"
NTFY_PRIORITY = 4  # High priority for "down" events
NTFY_PRIORITY_UP = 1  # Min priority for "up" events

# (name, kind, timeout_days, grace_hours, schedule, tz, tags, desc,
#  n_success_pings, final_status)
SEED_CHECKS = [
    (
        "Nightly Database Backup",
        "simple",
        1,
        1,
        "* * * * *",
        "UTC",
        "prod database",
        "pg_dump of the production database, run by cron on db-01.",
        5,
        "up",
    ),
    (
        "Weekly Sales Report",
        "cron",
        1,
        4,
        "0 7 * * 1",
        "UTC",
        "reports",
        "Monday 07:00 UTC sales rollup emailed to the team.",
        3,
        "up",
    ),
    (
        "Staging Deploy Hook",
        "simple",
        3,
        2,
        "* * * * *",
        "UTC",
        "staging",
        "Pinged by CI after each staging deploy. Not wired up yet.",
        0,
        "new",
    ),
    (
        "Legacy Billing Import",
        "simple",
        1,
        1,
        "* * * * *",
        "UTC",
        "billing legacy",
        "Old billing CSV import, paused during the migration.",
        0,
        "paused",
    ),
]

user = User.objects.filter(email=ADMIN_EMAIL).first()
assert user is not None, f"no user {ADMIN_EMAIL}"
# Default project is owned directly by the user (no Member row at this stage).
project = Project.objects.filter(owner=user).order_by("id").first()
assert project is not None, f"no project owned by {ADMIN_EMAIL}"

names = [spec[0] for spec in SEED_CHECKS]
# Clear the whole project (including ad-hoc browser-smoke checks) so the
# dashboard shows exactly the deterministic baseline after every reset+seed.
Check.objects.filter(project=project).delete()
# Channels are separate rows (not cascaded by check deletion); clear all ntfy
# channels so exactly one deterministic seed integration exists (the email
# channel is a product default and is left alone).
Channel.objects.filter(project=project, kind="ntfy").delete()

for name, kind, timeout_days, grace_hours, schedule, tz, tags, desc, n_pings, status in SEED_CHECKS:
    check = Check.objects.create(
        project=project,
        name=name,
        kind=kind,
        timeout=timedelta(days=timeout_days),
        grace=timedelta(hours=grace_hours),
        schedule=schedule,
        tz=tz,
        tags=tags,
        desc=desc,
    )
    if name == "Staging Deploy Hook":
        # Clone-scenario seed: content filtering with HTTP request body
        # selected and unmatched pings classified as failure. Set before
        # pings so the flags persist; Check.ping() takes an explicit action
        # and does not reclassify, so status/n_pings are unaffected.
        check.filter_http_body = True
        check.filter_default_fail = True
        check.save()
    for _ in range(n_pings):
        check.ping(
            remote_addr="127.0.0.1",
            scheme="http",
            method="GET",
            ua="tester-env-seed/1.0",
            body=b"",
            action="success",
            rid=None,
        )
    if status == "paused":
        check.status = "paused"
        check.alert_after = None
        check.save()

ntfy = Channel.objects.create(
    project=project,
    kind="ntfy",
    name=NTFY_NAME,
    value=json.dumps(
        {
            "topic": NTFY_TOPIC,
            "url": NTFY_URL,
            "priority": NTFY_PRIORITY,
            "priority_up": NTFY_PRIORITY_UP,
            "token": "",
        },
        sort_keys=True,
    ),
)
# Wire the integration to all seed checks, like the add form does.
ntfy.assign_all_checks()

# ---- assertions (fail loudly if the visible baseline is wrong) ----
rows = list(Check.objects.filter(project=project, name__in=names))
assert len(rows) == 4, f"expected 4 seed checks, got {len(rows)}"
by_name = {c.name: c for c in rows}
for name, _kind, _td, _gh, _sched, _tz, _tags, _desc, n_pings, status in SEED_CHECKS:
    c = by_name[name]
    assert c.get_status() == status, f"{name}: get_status()={c.get_status()!r}, want {status!r}"
    c.refresh_from_db()
    assert c.n_pings == n_pings, f"{name}: n_pings={c.n_pings}, want {n_pings}"
    assert c.status == status, f"{name}: status={c.status!r}, want {status!r}"
total_pings = sum(c.n_pings for c in rows)
staging = by_name["Staging Deploy Hook"]
assert staging.filter_http_body is True, "Staging Deploy Hook: filter_http_body must be True"
assert staging.filter_default_fail is True, "Staging Deploy Hook: filter_default_fail must be True"
for other in ("Nightly Database Backup", "Weekly Sales Report", "Legacy Billing Import"):
    o = by_name[other]
    assert o.filter_http_body is False, f"{other}: filter_http_body={o.filter_http_body!r}, want False"
    assert o.filter_default_fail is False, f"{other}: filter_default_fail={o.filter_default_fail!r}, want False"
ntfy.refresh_from_db()
assert ntfy.is_editable(), "seed ntfy channel must be editable"
assert ntfy.ntfy.topic == NTFY_TOPIC, f"ntfy topic={ntfy.ntfy.topic!r}, want {NTFY_TOPIC!r}"
assert ntfy.ntfy.url == NTFY_URL, f"ntfy url={ntfy.ntfy.url!r}, want {NTFY_URL!r}"
assert ntfy.ntfy.priority == NTFY_PRIORITY, f"ntfy priority={ntfy.ntfy.priority}, want {NTFY_PRIORITY}"
assert ntfy.ntfy.priority_up == NTFY_PRIORITY_UP, f"ntfy priority_up={ntfy.ntfy.priority_up}, want {NTFY_PRIORITY_UP}"
print(f"SEED PASS: 4 checks ({total_pings} pings): " + ", ".join(
    f"{n} [{by_name[n].get_status()}, n_pings={by_name[n].n_pings}]" for n in names
))
print(f"SEED PASS: ntfy {NTFY_NAME!r} (topic={NTFY_TOPIC}, url={NTFY_URL}, "
      f"priority={NTFY_PRIORITY}, priority_up={NTFY_PRIORITY_UP})")
print("SEED PASS: filtering Staging Deploy Hook "
      "(filter_http_body=True, filter_default_fail=True)")
