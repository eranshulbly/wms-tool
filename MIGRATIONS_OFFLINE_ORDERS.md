# Offline-orders release — migration runbook

Four migrations, in this order. Every one is idempotent (each checks
`information_schema` first), so re-running is safe and a partial application can
simply be re-run from the top.

**Apply these before deploying the API.** Three of them add columns the new code
writes on every order; deploying first means every order raised in the gap fails
with an unknown-column error.

```bash
mysql -h "$DB_HOST" -u "$DB_USERNAME" -p "$DB_NAME" < migration_refresh_token_hardening.sql
mysql -h "$DB_HOST" -u "$DB_USERNAME" -p "$DB_NAME" < migration_idempotency.sql
mysql -h "$DB_HOST" -u "$DB_USERNAME" -p "$DB_NAME" < migration_location_provenance.sql
```

| File | Adds | Needed by |
|---|---|---|
| `migration_refresh_token_hardening.sql` | `refresh_tokens.revoked_reason`, `.replaced_by`, two indexes | Refresh-token rotation, reuse detection, the grace window |
| `migration_idempotency.sql` | `idempotency_keys` table | Safe retry of every queued write |
| `migration_location_provenance.sql` | `submitted_orders.location_source`, `.location_age_s`, `.location_is_mocked`, an index | Telling a live GPS fix from a cached one |

`migration_partitions.sql` and the rest of the existing set are unrelated and
should not be re-run.

## Order of operations

1. Apply the three migrations above.
2. Deploy the API (`pm2 restart`). The new `gunicorn-cfg.py` switches to a
   threaded worker — watch DB connection count for a few minutes; four threads
   draw at most four of the pool's ten.
3. Apply the nginx changes (§6 of `deployment.md`) and **verify gzip actually
   fires** with the curl in that section. A `gzip on` that never applies is the
   common failure and it is invisible until measured from outside.
4. Ship the app build.

## Two behaviour changes worth briefing the team on

**Every rep is signed out once.** Sessions from older builds stored no refresh
token, so they cannot be renewed. This is deliberate — such a token dies within
the hour anyway, and failing at launch beats failing mid-visit at a dealer.

**Orders are queued, not sent immediately.** The confirmation screen now says
either "Request received" (it reached us) or "Order saved" (it is on the phone and
will send itself). Both mean the rep is finished. The back office will see a short
delay on orders raised in poor coverage, and `location_captured_at` — not
`created_at` — is now the order's business date.

## Rollback

The migrations only add columns and a table, so the previous API build runs
against the migrated schema unchanged. Roll back the app and API without touching
the database.

One caveat: orders queued by the new app but not yet delivered live only on the
rep's phone. Rolling the app back to a build without an outbox strands them. If a
rollback is needed, do it with the fleet on WiFi and have reps open the app first
so their queues drain.
