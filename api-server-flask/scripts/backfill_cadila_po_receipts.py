# -*- encoding: utf-8 -*-
"""One-off backfill: load Cadila_PO_Receipts_Data.xlsx as goods receipts.

Run from /app inside the backend container (it needs the app's DB config on the path):

    docker exec -it wms_backend python3 scripts/backfill_cadila_po_receipts.py --file /tmp/Cadila_PO_Receipts_Data.xlsx
    docker exec -it wms_backend python3 scripts/backfill_cadila_po_receipts.py --file /tmp/Cadila_PO_Receipts_Data.xlsx --commit

Without --commit it only prints what it would do — no database writes. Review that
output before adding --commit.

Why this exists
----------------
The file is a flat receipts export (Product Code, Invoice No, Invoice Date, Batch No,
Expiry, Quantity, Landed Rate, MRP, GST %, IRN, Order No, Delivery No, Transaction
Value) — not one of Cadila's PDF templates, so it cannot go through the normal
Inventory Ingestion upload. This script reshapes each row into the same `doc`/`line`
shape api.modules.inventory.ingestion.parser_cadila.parse_documents() produces, then
hands it to the SAME service._ingest_document() a real PDF upload uses — so the write
(product/batch resolution, stock, ledger, price details, duplicate handling) is
byte-for-byte what a PDF upload of these receipts would have done.

Rows are skipped, not guessed at, in two cases:
  * the batch (by the app's own identity: SKU + batch number + expiry) already exists
    — most of this file turned out to already be in the system from earlier PDF
    uploads, and re-receiving it would double stock.
  * the product code is not yet in the catalogue — this file carries no product name,
    pack or UOM, so a product cannot be safely created from it. These are reported so
    the master can be fixed and this file (or the row) re-run afterwards.

Each invoice (Invoice No) becomes one document, written in its own transaction — one
bad invoice cannot roll back the others, same as a multi-document PDF upload.
"""
import argparse
import os
import sys

import pandas as pd

# Run as a plain script (not `python -m`), so the project root — this file's parent
# directory — needs to be on sys.path for `api.*` to import.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.shared.db_manager import mysql_manager
from api.modules.inventory.ingestion import service
from api.modules.inventory.ingestion.parser_cadila import _doc_date, _month_end

COMPANY_ID = 3        # Cadila
WAREHOUSE_ID = 1       # Main Warehouse — the only one mapped to company 3
UPLOAD_USER = 'backfill_script'


def _norm(v):
    return str(v).strip().upper() if v is not None and str(v).strip().lower() != 'nan' else ''


def _existing_product_codes(company_id):
    rows = mysql_manager.execute_query(
        "SELECT product_id, product_string, name FROM product WHERE company_id = %s",
        (company_id,))
    return {r['product_string']: r for r in rows if r['product_string']}


def _existing_batch_hashes(company_id):
    rows = mysql_manager.execute_query(
        "SELECT batch_hash FROM sku_batch WHERE company_id = %s", (company_id,))
    return {r['batch_hash'] for r in rows}


def load_rows(path):
    df = pd.read_excel(path, sheet_name='Receipts')
    df['Product Code'] = df['Product Code'].map(_norm)
    df['Batch No'] = df['Batch No'].map(_norm)
    return df


def classify_rows(df, products, existing_hashes):
    """Split rows into (ready_rows, missing_product_rows, already_exists_rows)."""
    ready, missing_product, already_exists = [], [], []

    for _, row in df.iterrows():
        code = row['Product Code']
        product = products.get(code)
        if not product:
            missing_product.append(row)
            continue

        expiry = _month_end(str(row['Expiry']))
        h = service.batch_hash(product['product_id'], row['Batch No'], expiry)
        if h in existing_hashes:
            already_exists.append(row)
            continue

        ready.append((row, product, expiry))

    return ready, missing_product, already_exists


def build_docs(ready_rows):
    """Group ready rows by Invoice No into parser_cadila-shaped doc dicts."""
    docs_by_invoice = {}
    for row, product, expiry in ready_rows:
        invoice_no = str(int(row['Invoice No']))
        doc = docs_by_invoice.setdefault(invoice_no, {
            'doc_type': 'GRN',
            'doc_number': invoice_no,
            'doc_date': _doc_date(str(row['Invoice Date'])),
            'irn': _norm(row.get('IRN')) or None,
            'order_number': str(int(row['Order No'])) if pd.notna(row.get('Order No')) else None,
            'delivery_number': (str(int(row['Delivery No']))
                                 if pd.notna(row.get('Delivery No')) else None),
            'buyer_gstin': '',
            'warnings': [],
            'lines': [],
        })
        doc['lines'].append({
            'product_code': row['Product Code'],
            'raw_product_name': product['name'] or row['Product Code'],
            'raw_pack': '',
            'raw_batch': row['Batch No'],
            'expiry_date': expiry,
            'quantity': float(row['Quantity']),
            'mrp': float(row['MRP']) if pd.notna(row['MRP']) else None,
            'rate': float(row['Landed Rate']),
            'gst_rate': float(row['GST %']) if pd.notna(row['GST %']) else None,
            'stp_basis': True,   # Quantity is already the sellable-unit (strip) count
            'uom': '',
            'hsn': '',
            'manufacturer': '',
        })
    return docs_by_invoice


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--file', required=True, help='Path to Cadila_PO_Receipts_Data.xlsx')
    ap.add_argument('--commit', action='store_true',
                     help='Actually write. Without this flag, only prints a preview.')
    args = ap.parse_args()

    df = load_rows(args.file)
    products = _existing_product_codes(COMPANY_ID)
    existing_hashes = _existing_batch_hashes(COMPANY_ID)

    ready, missing_product, already_exists = classify_rows(df, products, existing_hashes)

    print(f"Rows in file:             {len(df)}")
    print(f"Already in the system:    {len(already_exists)} (skipped — batch already exists)")
    print(f"Missing from catalogue:   {len(missing_product)} (skipped — product not in master)")
    print(f"Ready to receive:         {len(ready)}")

    if missing_product:
        codes = sorted({r['Product Code'] for r in missing_product})
        print(f"\nProduct codes not in the catalogue ({len(codes)}): {', '.join(codes)}")
        print("Add these to the product master, then re-run this script — already-loaded")
        print("rows are skipped automatically, so re-running is safe.")

    docs_by_invoice = build_docs(ready)
    print(f"\n{len(docs_by_invoice)} invoice(s) will be received:")
    for invoice_no, doc in sorted(docs_by_invoice.items()):
        print(f"  Invoice {invoice_no} ({doc['doc_date']}): {len(doc['lines'])} line(s)")
        for line in doc['lines']:
            print(f"    {line['product_code']:10s} batch {line['raw_batch']:14s} "
                  f"qty {line['quantity']:>8g}  rate {line['rate']:>10.4f}  "
                  f"mrp {line['mrp']}")

    if not args.commit:
        print("\nDry run only — nothing written. Re-run with --commit to write these.")
        return

    if not docs_by_invoice:
        print("\nNothing to write.")
        return

    print("\nWriting...")
    total_received, total_created = 0, 0
    failures = []
    for invoice_no, doc in sorted(docs_by_invoice.items()):
        try:
            result = service._ingest_document(  # pylint: disable=protected-access
                doc, COMPANY_ID, WAREHOUSE_ID, user=UPLOAD_USER)
        except service.IngestionError as e:
            failures.append((invoice_no, str(e)))
            print(f"  Invoice {invoice_no}: FAILED — {e}")
            continue
        total_received += result['received']
        total_created += len(result['created_products'])
        flag = ' (DUPLICATE — stock not added, only price refreshed)' if result['duplicate'] else ''
        print(f"  Invoice {invoice_no}: {result['received']} line(s) received{flag}")
        if result['created_products']:
            # Should not happen — every line here was matched to an existing product —
            # surfaced loudly because it would mean the pre-filter missed something.
            print(f"    UNEXPECTED: created product(s) {result['created_products']}")

    print(f"\nDone. {total_received} line(s) received across "
          f"{len(docs_by_invoice) - len(failures)} invoice(s).")
    if total_created:
        print(f"WARNING: {total_created} product(s) were created — investigate, this "
              "backfill was expected to only touch existing catalogue products.")
    if failures:
        print(f"\n{len(failures)} invoice(s) failed:")
        for invoice_no, msg in failures:
            print(f"  Invoice {invoice_no}: {msg}")


if __name__ == '__main__':
    sys.exit(main())
