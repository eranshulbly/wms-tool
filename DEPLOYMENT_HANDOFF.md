# WMS Tool — deployment handoff

Everything needed to deploy this project, written for a fresh Claude Code session (or a
new engineer) with no prior context. Verified against the live box on **2026-09-16**.

Read this **instead of** `deployment.md` where the two disagree — the corrections are
marked below. The repo's `deploy.sh`, `rollback.sh` and every `docker-compose*.yml` do
**not** describe how this is actually deployed; see §11.

---

## 1. The one-paragraph version

One EC2 box runs **two tenants** of this app plus three unrelated apps. Each tenant is a
plain directory of files (no git, no Docker) with its own Python venv, its own pm2
process on its own loopback port, its own MySQL database on a shared RDS instance, and
its own nginx vhost terminating TLS. Deploying = copy changed files over SSH, restart
pm2 for the backend, rebuild the static React bundle for the frontend.

---

## 2. Infrastructure

| Thing | Value |
|---|---|
| EC2 | `13.203.20.67` · Ubuntu 24.04 · **aarch64/ARM64** · `t4g.small` (2 vCPU / 1.8 GB) · ap-south-1c |
| RDS | `shared-mysql.cp8846wq074m.ap-south-1.rds.amazonaws.com:3306` · MySQL 8.0.42 · `db.t4g.micro` · **private only**, no public route |
| SSH key | `C:\Users\anshu\Downloads\warehousemanagement.pem` (Windows) = `~/Downloads/warehousemanagement.pem` |
| SSH | `ssh -i C:\Users\anshu\Downloads\warehousemanagement.pem ubuntu@13.203.20.67` |
| Node | v22.23.2 via nvm — **must** `source ~/.nvm/nvm.sh` first over SSH |
| uv | `/home/ubuntu/.local/bin/uv` — **not** on the non-interactive SSH PATH |
| Docker | **not installed**, and not wanted |
| AWS CLI / creds | **none** anywhere — nothing here can provision infrastructure |

### Tenants of this app

| | Main (Hero) | Cadila |
|---|---|---|
| Domain | `warehub.duckdns.org` | `warehub-cadila.duckdns.org` |
| Directory | `/home/ubuntu/wms-tool` | `/home/ubuntu/wms-tool-cadila` |
| pm2 process | `wms-backend` | `wms-cadila-backend` |
| Backend port | `127.0.0.1:3001` | `127.0.0.1:3002` |
| Database | `warehouse_management` | `warehouse_management_cadila` |
| DB user | `wms_app` | `cadila_app` |
| nginx vhost | `/etc/nginx/sites-available/wms-tool` | `/etc/nginx/sites-available/wms-cadila` |
| Loopback test port | `127.0.0.1:8088` | `127.0.0.1:8091` |
| Source branch | `main` | `cadila_changes` |

Other apps on the same box, do not disturb: `warehouse-ops` (`wareops.duckdns.org`, holds
`default_server` on :80), `attendance-gateway`, `cheque-gateway`, `cheque-ocr`.
**Ports taken:** 3000, 3001, 3002, 8080 (reserved for the ZKTeco attendance gateway even
though nothing listens now), 8088, 8091, 8109, 8110. Next free app port: **3003**.

---

## 3. Getting in — three traps that look like something else

1. **Port 22 is IP-allowlisted; 80/443 are open to the world.** When the office IP
   changes, SSH times out while `https://warehub.duckdns.org` still returns 200. That
   reads like a local network fault but isn't. Diagnose with a per-port TCP test (22
   fails, 80/443 succeed) plus the current public IP, then have the user set the port-22
   rule's source to "My IP" in the AWS console. **There is no AWS CLI here, so this
   always needs the user.**
2. **Never pipe a secret into `ssh` from Windows PowerShell 5.1.** It prepends a UTF-8
   BOM, so the remote side stores `\ufeffsecret`. Every server-side check through the same
   pipe agrees with itself, so tests pass while the credential is broken. Pass secrets
   **base64-encoded as an argv argument** and decode remotely.
3. **The Bash tool on the Windows machine has no network access** (ssh/curl time out);
   PowerShell does. But Bash writes clean bytes. So: author payloads/scripts in Bash,
   transmit with PowerShell.

---

## 4. How each tenant is wired

**Backend** — gunicorn under pm2, Python **3.9** venv at `api-server-flask/.venv`
(uv-managed standalone; system Python is 3.12 and the pins are too old for it).
pm2 is configured by `<dir>/ecosystem.config.js`:

```js
name: 'wms-backend',
script:     '/home/ubuntu/wms-tool/api-server-flask/.venv/bin/gunicorn',
interpreter:'/home/ubuntu/wms-tool/api-server-flask/.venv/bin/python',  // MANDATORY
args:       '--config /home/ubuntu/wms-tool/api-server-flask/gunicorn-prod.py run:app',
cwd:        '/home/ubuntu/wms-tool/api-server-flask',
max_memory_restart: '300M',
```

`interpreter` is mandatory: `.venv/bin/gunicorn` has no file extension, so pm2 runs it as
Node and dies with `SyntaxError: Invalid or unexpected token` on the Python shebang.

**gunicorn config is `gunicorn-prod.py`, which exists only on the box** — it is not in
git. It binds `127.0.0.1:3001`, `workers = 1`, `worker_class = 'gthread'`, `threads = 4`,
`preload_app = False`. The repo's `api-server-flask/gunicorn-cfg.py` is **inert here** —
it binds `0.0.0.0:5000` and sets `preload_app = True`. Ignore diffs in it.

**Frontend** — CRA build output served straight by nginx from `react-ui/build`.
`REACT_APP_BACKEND_SERVER` is deliberately **unset**: `react-ui/src/config.js` falls back
to a relative `/api/`, so the bundle is origin-agnostic and survives a domain change with
no rebuild.

**nginx** — each vhost proxies `/api/` and `^/(health|admin)` to its backend port, serves
the SPA with `try_files ... /index.html`, sets `client_max_body_size 50M`, and carries a
mandatory `$host` guard (`return 444`) so it can never become the catch-all for
IP-addressed traffic. Certs in `/etc/letsencrypt/live/<domain>/`, `certbot.timer` enabled.

> **certbot warning (Cadila vhost especially):** it was run with `--no-redirect` on
> purpose. certbot's `--redirect` collapses the `:80` block into a blanket redirect and
> silently drops custom config; left alone it also merges `443` into the same block as
> `:80`, which quietly leaves `/api/` answering over plain HTTP. The three-block split
> (`:80` redirect, `:443` app, loopback) is hand-made. **Re-check both vhosts after any
> certbot run.**

---

## 5. Hard constraints — do not "fix" these

1. **Single process only.** `MySQLManager` opens `DB_POOL_SIZE` connections *per process*
   at import and never enforces `max_overflow`, and `initialize_database()` re-runs DDL
   plus a check-then-insert role seed on every boot. More workers = multiplied RDS
   connections + a seed race. **Scale with threads, never workers.**
2. **RDS `max_connections` is 60** — shared across every app on the box. (`deployment.md`
   claims ~85; it is wrong.) Baseline ~11; each tenant's pool adds ~4.
3. **`mysqlclient` must stay out of the installed requirements.** Nothing imports
   `MySQLdb` (the app calls `pymysql.install_as_MySQLdb()`), and building it needs
   `libmysqlclient-dev` + `pkg-config`, which the box owner forbids installing. Filter it
   out of `requirements.txt` at install time.
4. **No apt installs, no Docker, no new EC2/RDS.** There are no AWS credentials.
5. **Memory is tight** (1.8 GB, ~900 MB free, swap in use). A React build can push
   `warehouse-ops` into a restart loop — **build one app at a time**.

---

## 6. Finding what is actually stale

`/home/ubuntu/wms-tool` is **not a git repo** (it was tar-shipped), so there is no
`git log` on the box. Compare `md5sum` lists instead:

```bash
# remote (run from PowerShell, capture to a file)
ssh ... "cd /home/ubuntu/wms-tool && find . -type f \
  -not -path './react-ui/node_modules/*' -not -path './react-ui/build*' \
  -not -path '*/.venv/*' -not -path '*/__pycache__/*' -not -name '*.pyc' \
  -print0 | xargs -0 md5sum" > remote_md5.txt

# local (Bash)
git ls-files -z | xargs -0 md5sum > local_md5.txt
```

Four rules, each learned the hard way:

1. **Normalize line endings before believing a mismatch.** The Windows checkout is CRLF,
   the box is LF. A raw diff on 2026-09-15 flagged 20 "changed" files; every app file
   among them was byte-identical after `tr -d '\r'`. Compare with
   `tr -d '\r' < f | md5sum`, or pull the file and `diff -u --strip-trailing-cr`.
2. **Sanity-check the remote list before trusting it.** If ssh fails, the redirect
   captures `ssh: connect to host ... timed out` as a one-line "file list" and every join
   comes back empty — a broken connection looks *exactly* like "already in sync".
   `grep -qi "ssh:"` the file and compare line counts first.
3. **A tar/scp overlay never deletes.** Real deploys remove files (a module got split
   once), so build a three-part manifest — changed / new / **gone** — with
   `join -j2`, `-v1`, `-v2`. Ship the first two, `rm` the third, purge `__pycache__`.
4. **Expect legitimate remote-only files**: `.env`, `gunicorn-prod.py`,
   `ecosystem.config.js`, `media/**` (uploaded photos — never delete), `*.bak*` files
   from past hand-edits, `build*/`, `node_modules/`, `.venv/`.

**`api-server-flask/.env` is tracked in git but differs on the box — never ship it.**

---

## 7. Deploying the backend

```bash
# 1. ship changed files (from the repo root, Git Bash; MSYS_NO_PATHCONV=1 if paths mangle)
tar czf - <changed files> | ssh -i <key> ubuntu@13.203.20.67 \
  "tar xzf - -C /home/ubuntu/wms-tool"

# 2. remove files that are gone, then purge stale bytecode
ssh ... "cd /home/ubuntu/wms-tool && rm -f <deleted files> && \
  find . -name __pycache__ -type d -prune -exec rm -rf {} +"

# 3. dependencies ONLY if requirements.txt changed (note the mysqlclient filter)
ssh ... "export PATH=\$HOME/.local/bin:\$PATH && cd /home/ubuntu/wms-tool/api-server-flask && \
  grep -v mysqlclient requirements.txt > /tmp/req.txt && .venv/bin/pip install -r /tmp/req.txt"

# 4. restart + verify
ssh ... "source ~/.nvm/nvm.sh && pm2 restart wms-backend && sleep 3 && pm2 ls"
```

**Schema convergence is automatic.** `_migrate_v2_api_columns()` and friends in
`api/shared/db_manager.py` run at boot and idempotently add columns, so **a backend
restart is the migration**. Two exceptions in §9.

---

## 8. Deploying the frontend

```bash
ssh ... "source ~/.nvm/nvm.sh && cd /home/ubuntu/wms-tool/react-ui && \
  NODE_OPTIONS=--openssl-legacy-provider BUILD_PATH=./build_new npm run build && \
  mv build build_old && mv build_new build"
```

- `NODE_OPTIONS=--openssl-legacy-provider` is required — CRA 4.0.3 on Node 22.
- **Build to a staging dir and swap.** A plain `npm run build` wipes `build/` in place and
  404s the live site for the whole build.
- **Afterwards, copy any `build_old/static` chunk missing from the new build into
  `build/`** — users mid-session otherwise hit `ChunkLoadError` on lazily-loaded routes.
- Build **one app at a time** (memory, §5.5).
- No rebuild is needed for a domain change (origin-agnostic bundle, §4).

---

## 9. Database

**Read access** (RDS is private-only, so everything goes through the box):

```bash
ssh -i <key> ubuntu@13.203.20.67
cd ~/wms-tool/api-server-flask && ./.venv/bin/python /tmp/script.py
```

Let the app load its own credentials — do **not** read `.env` (correctly blocked). Ship
the script as base64 over argv (§3.2).

- **Trap:** `api/__init__.py` ends with a module-level `app = create_app()`, and
  `create_app()` calls `initialize_database()` — so *any* `import api.*` runs DDL on
  production. There is no import path that avoids it. Before accepting that risk, check
  that the newest on-disk source is **older** than the running process (`pm2 describe`) —
  then the live app has already applied that exact idempotent DDL.
- Set `DB_POOL_SIZE=1` / `DB_MAX_OVERFLOW=1` in `os.environ` **before** importing, or the
  eager pool opens ten connections against the shared 60.
- **`mysqldump` needs `--set-gtid-purged=OFF`** (the master user lacks `RELOAD`). It
  still writes an 839-byte header and exits 2 on failure, so a redirected dump *looks*
  like it worked — check `wc -c` / `grep -c "CREATE TABLE"`, never just `$?`:
  `mysqldump --single-transaction --set-gtid-purged=OFF --no-tablespaces --routines --events --triggers <db>`

**Hand-run migrations — the two exceptions to "restart is the migration":**

1. **Never run `migration_v2_api.sql` by hand.** Besides schema it contains
   `DELETE FROM potential_order WHERE status='submitted'` and a `DROP TABLE` — one-way
   data moves, not DDL.
2. **`MIGRATIONS_OFFLINE_ORDERS.md` must be applied BEFORE deploying its API**, in this
   order: `migration_refresh_token_hardening.sql`, `migration_idempotency.sql`,
   `migration_location_provenance.sql`. They add columns the new code writes on every
   order; deploying first makes every order fail with an unknown-column error. All three
   are idempotent. *(These are already applied on the main tenant as of 2026-09-15.)*

---

## 10. Verifying, and rolling back

```bash
# from outside — the only test that proves the public path works
curl -s -o /dev/null -w '%{http_code}\n' https://warehub.duckdns.org/
ssh ... "source ~/.nvm/nvm.sh && pm2 ls && tail -50 ~/.pm2/logs/wms-backend-out.log"
ssh ... "curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8088/"   # loopback vhost
```

- **Verify auth changes from a genuinely different client and network path** than the one
  that made the change (§3.2) — a test reusing the writing path proves only
  self-consistency.
- **Do not verify loaded code with `python -c "from run import app"`** — that spawns a new
  interpreter reading from disk and reports the code you *wish* were live. Hit an HTTP
  route the new code adds.
- **Rollback:** frontend — `mv build build_bad && mv build_old build`. Backend — ship the
  previous files and `pm2 restart`. The offline-orders migrations only add columns and a
  table, so the previous build runs against the migrated schema unchanged.

---

## 11. Repo files that will mislead you

| File | Reality |
|---|---|
| `deploy.sh`, `rollback.sh` | Docker/compose based. **Never used here.** Docker isn't installed. |
| `docker-compose*.yml` | Would stand up its own MySQL instead of the shared RDS. Local dev only. |
| `api-server-flask/gunicorn-cfg.py` | Superseded by the box-only `gunicorn-prod.py`. Diffs in it are noise. |
| `deployment.md` | Right about addresses; **wrong** that RDS allows ~85 connections (it's 60). |
| `nginx/prod*.conf` | Samples. The live config is `/etc/nginx/sites-available/*`, edited by hand. |
| `react-ui/package.json` → `homepage` | Hardcodes `warehub.duckdns.org` on both tenants. Harmless (only its path is used) but confusing. |
| `docker-compose.dev.yml` "hot reload" | A lie for Python: gunicorn preloads with no `--reload`. **Restart the backend after any edit or branch switch** — a stale process serves deleted code from memory. |

---

## 12. Adding a third tenant

Copy the Cadila shape, do not provision hardware: new directory, **next free port (3003)**,
own database + scoped user, own `.env` + `ecosystem.config.js`, own hand-split nginx vhost,
certbot with `--no-redirect`. Then seed the first admin into **both** `users.role` and
`user_roles` with status exactly `'active'`, or permissions silently fall back to legacy
defaults. Grants in `user_warehouse_company` are always **(warehouse, company) pairs** —
`company_id` is NOT NULL, so a warehouse alone cannot be stored.

---

## 13. Current state (2026-09-16)

`main` @ `a1c5b1b` is **fully deployed** on the main tenant: backend files match, the
frontend build (Aug 10) is newer than every frontend source file, and the offline-orders
migrations are applied. The only unapplied part of that commit is its **nginx gzip and
keepalive changes**, which live in the repo's sample configs and were never copied into
`/etc/nginx`.
