# Deploying apps on this AWS server

Runbook for an AI agent deploying a **new** app alongside the existing ones.
Written from a real migration; the warnings are things that actually went wrong,
not hypotheticals. Read the constraints before touching anything.

---

## 1. Infrastructure

| | |
|---|---|
| **EC2** | `13.203.20.67` · Ubuntu 24.04 LTS · **aarch64 (ARM64)** · `t4g.small` (2 vCPU / 1.8 GB) · 30 GB gp3 · ap-south-1c |
| **RDS** | `shared-mysql.cp8846wq074m.ap-south-1.rds.amazonaws.com:3306` · MySQL 8.0.42 · `db.t4g.micro` (1 GB) · Single-AZ · **private only** (`172.31.48.38`) |
| **SSH** | `ssh -i ~/Downloads/warehousemanagement.pem ubuntu@13.203.20.67` |
| **MySQL** | `mysql` on the box reads `~/.my.cnf` (master creds, mode 600). No password needed on the CLI. |
| **Region/AZ** | ap-south-1, both EC2 and RDS in **ap-south-1c** — keep new resources here to avoid cross-AZ transfer charges |

Node is installed via nvm and **must be sourced in every non-interactive SSH command**:

```bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"
```

Omit that and you get "node: command not found" over SSH while it works fine
interactively.

---

## 2. Hard constraints — do not violate

1. **Do not `apt install` anything.** The owner has explicitly forbidden new
   system packages. Everything you need is present: nginx, certbot, mysql
   client, `uv` (Python), `tesseract-ocr`, git, build-essential. npm
   dependencies inside an app are fine; system packages are not.
2. **Adapt code to this infrastructure, not the reverse.** MySQL 8.0, Node 22,
   ARM64. Other apps will be built against the same config.
3. **Never grant `ON *.*`.** Every app gets its own database and its own user
   scoped to it. See §4.
4. **Never expose an app port publicly.** Bind to `127.0.0.1` and let nginx
   proxy. The security group only opens 22/80/443; anything else is either
   unreachable or a mistake.
5. **Budget MySQL connections.** `db.t4g.micro` allows **~85 connections in
   total, shared across every app**. A default pool of 10 per app across a few
   apps plus a couple of processes exhausts it and takes down *all* apps, not
   just yours. Set an explicit small pool (8 or fewer).

---

## 3. What is already running

| Service | Port | pm2 name | Notes |
|---|---|---|---|
| warehouse-ops (Next.js) | `127.0.0.1:3000` | `warehouse-ops` | main app |
| cheque-gateway (FastAPI) | `127.0.0.1:8109` | `cheque-gateway` | Gemini vision |
| cheque-ocr (FastAPI) | `127.0.0.1:8110` | `cheque-ocr` | Tesseract fallback |
| nginx | `0.0.0.0:80`, `:443` | — | vhosts in `/etc/nginx/sites-enabled/` |

**Ports 3000, 8109, 8110 are taken.** Start new apps at **3001** and count up.
Check first:

```bash
ss -ltn | grep -E ':(300[0-9]|81[0-9][0-9])'
```

Databases in use: `warehouse_ops`. MySQL users: `admin` (master), `wo_app`.

Headroom is tight: ~1 GB RAM free and 22 GB disk. A Next.js build peaks near
1 GB, so **build one app at a time**. There is a 2 GB swapfile; without it
`next build` OOMs.

---

## 4. Create the app's database and user

Run on the box (uses `~/.my.cnf`). Replace `myapp` and generate a real password.

```bash
APPPW=$(openssl rand -base64 24 | tr -d '/+=' | head -c 28)
mysql <<SQL
CREATE DATABASE IF NOT EXISTS myapp
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS 'myapp_app'@'%' IDENTIFIED BY '${APPPW}';
GRANT SELECT, INSERT, UPDATE, DELETE ON myapp.* TO 'myapp_app'@'%';
FLUSH PRIVILEGES;
SQL
echo "DATABASE_URL=mysql://myapp_app:${APPPW}@shared-mysql.cp8846wq074m.ap-south-1.rds.amazonaws.com:3306/myapp"
```

Grant only what the app needs. Add `CREATE, ALTER, DROP, INDEX, REFERENCES`
temporarily if it runs its own migrations, then revoke them.

Verify isolation — this **must** fail:

```bash
mysql -u myapp_app -p'<pw>' -h shared-mysql...rds.amazonaws.com -e "SELECT 1 FROM mysql.user"
```

---

## 5. Deploy the app

```bash
# from your machine — tar over ssh (rsync is NOT installed)
tar -cz --exclude=node_modules --exclude=.next --exclude=.git --exclude='.env*' . \
  | ssh -i ~/Downloads/warehousemanagement.pem ubuntu@13.203.20.67 \
      'mkdir -p /home/ubuntu/myapp && tar -xz -C /home/ubuntu/myapp'
```

If you are on Windows, **normalise line endings on any shell script you ship**
(`find . -name '*.sh' -exec sed -i 's/\r$//' {} \;`) — a CRLF shebang fails with
a confusing "no such file or directory".

Then on the box:

```bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"
cd /home/ubuntu/myapp
npm ci                       # rebuilds native modules for ARM64
npx tsc --noEmit             # gate: do not proceed if this fails
npm run build
```

**Never copy `node_modules` from another machine.** This box is ARM64; x86
binaries (SWC, Tailwind oxide, sharp, bcrypt) fail at runtime, sometimes only
under load. Always `npm ci` here.

Write the env file with mode 600:

```bash
cat > /home/ubuntu/myapp/.env.local <<EOF
DATABASE_URL=mysql://myapp_app:...@shared-mysql...:3306/myapp
DB_POOL_SIZE=8
EOF
chmod 600 /home/ubuntu/myapp/.env.local
```

Start under pm2, **bound to localhost**:

```bash
pm2 start npm --name myapp -- start -- -H 127.0.0.1 -p 3001
pm2 save          # required, or it will not come back after reboot
```

pm2 boot persistence is already installed (`pm2-ubuntu` systemd unit). `pm2 save`
after every process change.

---

## 6. nginx vhost + TLS

Create `/etc/nginx/sites-available/myapp`:

```nginx
server {
    server_name myapp.example.org;

    # REQUIRED. See §7 — this is what stopped a repeat compromise.
    if ($host != myapp.example.org) { return 444; }

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    listen 443 ssl;
}
```

```bash
sudo ln -sf /etc/nginx/sites-available/myapp /etc/nginx/sites-enabled/myapp
sudo nginx -t && sudo systemctl reload nginx
```

**Point DNS at `13.203.20.67` before running certbot** — Let's Encrypt validates
by connecting to the domain.

```bash
sudo certbot --nginx -d myapp.example.org --non-interactive --agree-tos -m you@example.com
```

⚠️ **Certbot's `--redirect` rewrites the whole port-80 block into a blanket
redirect.** If your app needs any plain-HTTP path (device callbacks, webhooks
from clients that can't do TLS), certbot will silently delete it. Re-add it
afterwards and put the redirect **inside `location /`**, not at server level:

```nginx
location / {
    if ($host = myapp.example.org) { return 301 https://$host$request_uri; }
    return 404;
}
```

Always re-check the config after certbot runs. Also re-add the `$host` guard —
certbot may reorder things around it.

---

## 7. Security rules — learned the hard way

This box's predecessor was **compromised twice in 36 hours** (cryptominer, cron
persistence, credential theft). The entry vector was an unauthenticated `POST`
to a non-existent path, reaching Next.js **because it was addressed to the bare
IP** and that vhost was nginx's default for 443.

1. **Always include the `$host` guard.** Without it, any vhost can become the
   catch-all for IP-addressed traffic. This single rule blocked the follow-up
   attacks.
2. **Keep frameworks patched.** The RCE was in Next.js 15.1.6. Cleaning the box
   without upgrading got it re-owned within hours. Check versions before
   deploying, not after.
3. **Bind services to `127.0.0.1`.** The old box had ports 3000 and 8080 open to
   the world for no reason.
4. **`chmod 600` every `.env`.** They were world-readable (644) on the old box.
5. **Never put a database's admin/master credential in an app's env.** Scoped
   user, scoped database.
6. **Do not open new security-group ports** unless there is no alternative.
   Proxy through nginx instead.

---

## 8. MySQL gotchas (from a real Postgres → MySQL port)

- **`DATETIME(6)`, not `TIMESTAMP`.** `TIMESTAMP` silently converts to the
  session timezone and cannot represent dates past 2038. Store UTC in
  `DATETIME(6)` and convert at the edges.
- **Money: `DECIMAL`, and read it as a string.** Configure the driver with
  `decimalNumbers: false`. JS doubles silently round currency.
- **Rounding:** MySQL/Postgres `round(x, 2)` is half-up away from zero.
  `Math.round(x*100)/100` is not equivalent for values like `x.xx5` — use an
  EPSILON nudge, or a decimal library.
- **No RLS in MySQL.** If you are porting from Postgres, row-level security has
  no equivalent and must be reimplemented in application code. Enforce it in one
  central choke point, not at each call site.
- **No sequences.** Use `AUTO_INCREMENT`, or a counter table driven by
  `LAST_INSERT_ID()` for formatted codes.
- **`TEXT` cannot be indexed or used as a key** without a prefix length. Use
  `VARCHAR(255)` for any column that is a key, unique, or indexed.
- **No function defaults** beyond `CURRENT_TIMESTAMP` and simple expressions.
  `DEFAULT (UUID())` works; `DEFAULT my_function()` does not — use a
  `BEFORE INSERT` trigger.
- **Importing generated INSERTs:** set `SET SESSION sql_mode =
  'NO_BACKSLASH_ESCAPES'` so backslashes in data survive.
- **Allocated storage can never shrink.** Start at 20 GB with autoscaling on.

---

## 9. Verify before declaring done

```bash
# typecheck + build already passed above
pm2 list                                    # process online
ss -ltn | grep 3001                         # bound to 127.0.0.1, NOT 0.0.0.0
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3001/
curl -s -o /dev/null -w '%{http_code}\n' https://myapp.example.org/
curl -sk -o /dev/null -w '%{http_code}\n' https://13.203.20.67/   # must fail/444
tail -20 ~/.pm2/logs/myapp-error.log
```

Do not report success on an HTTP 200 alone. A Next.js login page returns 200
while the database behind it is unreachable — the page is static. **Exercise a
path that actually reads data.**

---

## 10. Cost

| | Monthly |
|---|---|
| EC2 t4g.small | ~$8.18 |
| EBS 30 GB gp3 | ~$2.50 |
| Public IPv4 | ~$3.65 |
| RDS db.t4g.micro + 20 GB | ~$18 |
| **Total** | **~$32** |

Shared across all apps. Adding an app costs nothing extra unless it forces a
bigger instance. Watch `DatabaseConnections` in CloudWatch — hitting the ~85
ceiling is the most likely reason to upgrade RDS.

---

## 11. Rollback

- **App:** `pm2 restart <name>` after restoring the previous build; keep a copy
  of `.next` and `node_modules` before a risky upgrade.
- **nginx:** back up the vhost before editing; `nginx -t` before every reload.
- **DNS:** repointing DNS is the fastest rollback for a bad cutover — keep the
  old host alive for about a week after migrating.
- **Database:** RDS has 7-day automated backups, but **point-in-time recovery is
  instance-level, not per-database**. Restoring one app's database means
  restoring the whole instance to a new one and dumping that schema out. Take a
  `mysqldump` of your database before destructive migrations.
