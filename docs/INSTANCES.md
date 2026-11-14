# Deployed instances

Two separate deployments of this repo run on two separate EC2 boxes in `ap-south-1`.
They share one RDS server but **not** one database, and they do **not** run the same code.

If you only remember one thing: **`warehub` is Hero, `warehub-cadila` is Cadila (same box
as Hero), `warehub-ebco` is Ebco.**

## Getting onto a box — SSH through SSM, never the IP

Port 22 is closed to the internet: `ssh ubuntu@<ip>` and `scp ... ubuntu@<ip>:` **time
out**. Both boxes are reached by SSH tunnelled through AWS Session Manager, set up as
host aliases in `~/.ssh/config` (ProxyCommand `aws ssm start-session ...
AWS-StartSSHSession --profile wms --region ap-south-1`):

```bash
ssh ebco 'cmd'          # Ebco box
ssh hero 'cmd'          # Hero + Cadila box
scp <file> ebco:/home/ubuntu/wms-tool/<path>
```

The `wms` profile may start sessions (`ssm:StartSession`) but **not**
`ssm:SendCommand`, and cannot read its own IAM policies — do not try `aws ssm
send-command` or policy lookups; use the aliases.

| | **HERO** (original) | **CADILA** (same box as Hero) | **EBCO** (second instance) |
|---|---|---|---|
| URL | https://warehub.duckdns.org | https://warehub-cadila.duckdns.org | https://warehub-ebco.duckdns.org |
| SSH alias | `hero` | `hero` | `ebco` |
| Code folder | `~/wms-tool` | `~/wms-tool-cadila` | `~/wms-tool` |
| Public IP (not for SSH) | `13.203.20.67` | `13.203.20.67` | `65.1.42.160` |
| EC2 instance id | `i-0dd6fb2d0b43e5e2d` | `i-0dd6fb2d0b43e5e2d` | `i-0ceb1b1201dc9ef1a` |
| Database | `warehouse_management` | `warehouse_management_cadila` | `warehouse_management_ebco` |
| DB user | `wms_app` | — | `ebco_app` |
| pm2 process | `wms-backend` (port 3001) | `wms-cadila-backend` (port 3002) | `ebco-backend` |
| Security groups | `ec2-rds-1`, `launch-wizard-1` | (Hero's) | `ec2-rds-1`, `wms-tool-2-web` |
| Shares the box with | Cadila + 4 unrelated apps | Hero + 4 unrelated apps | nothing |

Both boxes are `t4g.small` (ARM64) in `ap-south-1c`, log in as `ubuntu` (the aliases
use `warehousemanagement.pem`), and serve behind nginx with a Let's Encrypt cert. Hero
and Cadila share a box but nothing else: own folder, own pm2 process, own database —
deploying one does not touch the other. **None of the three is a git checkout**, and each
carries changes made on the server that are not in git: diff the server's copy against
git before overwriting a file, and patch only your change onto it.

## Shared RDS

Both connect to `shared-mysql.cp8846wq074m.ap-south-1.rds.amazonaws.com` (MySQL 8.4.9),
reached because both boxes are in the `ec2-rds-1` security group, which the RDS group
allows as a source. There is no password-only path in from outside.

`max_connections` on that server is **60**, for every database and every app on it.
That budget is the reason each backend runs `workers=1` with `DB_POOL_SIZE=4` — see
[deployment.md](../deployment.md). Adding a third instance means re-checking the budget
first, not after.

The databases are isolated. `ebco_app` cannot read `warehouse_management`, and dropping
one database does not touch the other. But a runaway connection leak on either box
starves both, so a "the other portal is down too" symptom usually means RDS, not the app.

## What runs where — code drift

The two boxes are **not** on the same revision. Neither is a git checkout; both were
deployed by copying files, so `git log` on the box tells you nothing.

| Feature | Hero/Cadila | Ebco |
|---|---|---|
| `api/modules/inventory/ingestion/` (PDF GRN ingestion) | absent | present |
| `api/modules/fulfillment/order/challan_parser.py` | absent | present |
| `api/modules/fulfillment/order/product_sync.py` | absent | present |
| `product.gst_percent` column | absent | present |
| `uom` / `product_uom` / `fc_sku_price_details` | absent | present |
| `potential_order_product` money columns (`unit_price`, `line_item_discount_percent`, `additional_discount_percent`, `net_selling_price`) | absent | present |
| `product_location` (bin locations) + picklist download | absent | present |

The Ebco box is the newer one and was built from a fresh database, which is what shipped
the schema differences: the migrations that add `gst_percent` and the UoM tables run at
boot on Ebco but have never been run against `warehouse_management`.

**Consequence:** code written against Ebco can fail on the Hero box on a missing column.
`product_sync.py` handles this by discovering which product columns exist at runtime
rather than assuming `gst_percent` is there. Anything new that touches those columns
needs the same treatment, or the migration in
[migration_product_uom_pricing.sql](../api-server-flask/migration_product_uom_pricing.sql)
has to be applied to `warehouse_management` first.

## Ports on the Hero/Cadila box

That box is shared. `wms-backend` is only one of five pm2 apps on it:

| Port | Process | Belongs to |
|---|---|---|
| 3000 | `warehouse-ops` (Next.js) | wareops.duckdns.org |
| **3001** | **`wms-backend` (gunicorn)** | **warehub.duckdns.org — this repo** |
| 8080 | `cheque-gateway` | unrelated |
| 8088, 8109, 8110 | `cheque-ocr`, `attendance-gateway` | unrelated |

It also serves a **second domain**, `wareops.duckdns.org`, from a different app in
`/home/ubuntu/app`. Restarting all of pm2 on that box takes down three unrelated
services. Restart `wms-backend` by name, never `pm2 restart all`.

The Ebco box listens on 3001 only, and `pm2 restart all` there is harmless.

## Deploying

Nothing is automated. Copy the changed files, then restart — gunicorn loads the app once
at start and **does not** pick up edited files on its own, so a deploy without a restart
silently keeps running the old code.

```bash
# Ebco
scp <files> ebco:/home/ubuntu/wms-tool/api-server-flask/<path>/
ssh ebco 'export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh";
  find ~/wms-tool/api-server-flask -name __pycache__ -type d -exec rm -rf {} + ; pm2 restart ebco-backend'

# Hero   — ssh hero, ~/wms-tool,        pm2 restart wms-backend
# Cadila — ssh hero, ~/wms-tool-cadila, pm2 restart wms-cadila-backend
# On the shared box restart only the one process — never `pm2 restart all`.
```

`pm2` lives under nvm, so a non-interactive `ssh host 'pm2 ...'` may not find it. Source
it first: `export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"`.

Verify with `curl -s -o /dev/null -w '%{http_code}' https://<domain>/health` — a 200 from
the public URL proves nginx, the cert, gunicorn and the DB connection are all up.

Frontend builds are served statically by nginx from each app's `react-ui/build`; no
restart needed.

- **Ebco** builds on the box: `ssh ebco 'bash ~/build-ebco.sh > ~/build-ebco.log'`
  (builds into `build_new`, then swaps it in).
- **Cadila** has no frontend source on the box: build elsewhere and swap the `build`
  folder in, keeping the old one as `build_old_<ts>` and copying its `static/` files into
  the new build (open tabs still ask for old chunk files). If you build in the local dev
  container, **unset `REACT_APP_BACKEND_SERVER`** (it is `http://localhost:5001/api/`
  there) — otherwise the live site sends every request to the visitor's own machine.
  Before uploading, check the main chunk contains `"/api/"` and no `localhost:5001`.

## Also worth knowing

- **DNS is DuckDNS**, updated by hand. If a domain stops resolving, check the DuckDNS
  record before suspecting AWS. `Resolve-DnsName` works from Windows; `getent` fails
  silently against DuckDNS.
- **Neither box is in an Auto Scaling group, and there are no snapshots on a schedule.**
  The only durable state is in RDS. Order photos are on **local disk** on the box that
  received them — see the S3 note in the order-photo code; losing an instance loses them.
- **The Ebco box's IAM role:** it was once listed as having none; SSM works on it now, so
  it has one — check the console for which, and whether it covers S3 (order photos).
