# Deployed instances

Two separate deployments of this repo run on two separate EC2 boxes in `ap-south-1`.
They share one RDS server but **not** one database, and they do **not** run the same code.

If you only remember one thing: **`warehub` is Hero/Cadila, `warehub-ebco` is Ebco.**

| | **HERO / CADILA** (original) | **EBCO** (second instance) |
|---|---|---|
| URL | https://warehub.duckdns.org | https://warehub-ebco.duckdns.org |
| Public IP | `13.203.20.67` | `65.1.42.160` |
| EC2 instance id | `i-0dd6fb2d0b43e5e2d` | `i-0ceb1b1201dc9ef1a` |
| Database | `warehouse_management` | `warehouse_management_ebco` |
| DB user | `wms_app` | `ebco_app` |
| pm2 process | `wms-backend` | `ebco-backend` |
| Security groups | `ec2-rds-1`, `launch-wizard-1` | `ec2-rds-1`, `wms-tool-2-web` |
| IAM instance role | `anshul-ec2` | **none attached** |
| Shares the box with | 4 unrelated apps | nothing |

Both are `t4g.small` (ARM64) in `ap-south-1c`, both SSH as `ubuntu` with
`warehousemanagement.pem`, and both serve on `127.0.0.1:3001` behind nginx with a
Let's Encrypt cert. Same private key, same layout, same port — which is exactly why
it is easy to run a command on the wrong one. Check the IP.

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
scp -i warehousemanagement.pem <files> ubuntu@65.1.42.160:/home/ubuntu/wms-tool/api-server-flask/<path>/
ssh -i warehousemanagement.pem ubuntu@65.1.42.160 \
  'find /home/ubuntu/wms-tool/api-server-flask -name __pycache__ -type d -exec rm -rf {} + ; pm2 restart ebco-backend'

# Hero/Cadila — same, but 13.203.20.67 and `pm2 restart wms-backend`
```

`pm2` lives under nvm, so a non-interactive `ssh host 'pm2 ...'` may not find it. Source
it first: `export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"`.

Verify with `curl -s -o /dev/null -w '%{http_code}' https://<domain>/health` — a 200 from
the public URL proves nginx, the cert, gunicorn and the DB connection are all up.

Frontend builds are served statically by nginx from
`/home/ubuntu/wms-tool/react-ui/build`; rebuilding needs
`NODE_OPTIONS=--openssl-legacy-provider` (CRA 4 on Node 22) and no restart.

## Also worth knowing

- **DNS is DuckDNS**, updated by hand. If a domain stops resolving, check the DuckDNS
  record before suspecting AWS. `Resolve-DnsName` works from Windows; `getent` fails
  silently against DuckDNS.
- **Neither box is in an Auto Scaling group, and there are no snapshots on a schedule.**
  The only durable state is in RDS. Order photos are on **local disk** on the box that
  received them — see the S3 note in the order-photo code; losing an instance loses them.
- **The Ebco box has no IAM role.** Anything needing AWS APIs (S3 for order photos,
  for one) will fail there until `anshul-ec2` or an equivalent is attached.
