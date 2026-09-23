# -*- encoding: utf-8 -*-
"""One-off backfill: complete dealer details from old invoice PDFs already on file.

Re-uploading an old invoice through the Invoice Upload screen does NOT do this.
process_invoice_dataframe() (api/modules/fulfillment/invoice/business.py) rejects any row
whose order is already in a terminal state (Invoiced / Dispatch Ready / Completed /
Partially Completed) as a duplicate BEFORE dealer resolution ever runs — and an "old"
invoice's order has, by definition, already reached one of those. This script reaches
dealer resolution directly, bypassing the order-status gate entirely: it never touches an
order or an invoice row, only the dealer's own blank detail columns (gstin, phone,
alt_phone, address, town, state, pincode, pan, drug_license_numbers, sale_type,
credit_days).

Nothing is ever overwritten. get_or_create_dealer's _fill_blank_details() only sets a
dealer column that is currently blank — COALESCE(NULLIF(col, ''), new), same rule a live
invoice upload follows — so running this before or after Invoice Upload has processed the
same invoice, or running it twice, is equally safe.

Two steps, on purpose — so the PDFs themselves never have to leave wherever they already
are (a laptop, a local dev box) to reach the server:

  extract — reads a folder of PDFs, pulls out each one's buyer name/GSTIN and detail
            fields, writes them to one small JSON file. Touches no database (beyond the
            app's usual eager connection at import time — see below); safe to run
            anywhere the PDFs are.

  apply   — reads that JSON file and, for each record, calls the exact same
            dealer-resolution function a live invoice upload uses per row
            (_resolve_dealer -> get_or_create_dealer). Needs no PDFs at all: only the
            small JSON, and a working DB connection for whichever environment it is run
            in. This is the step to run on the server.

Run (see backfill_cadila_po_receipts.py for more detail on why the project-root/.env
handling below exists, and why --company-id has no default — same reasoning applies
here: a dealer is looked up/created scoped to one company, and that id differs between
databases):

    # 1. On your laptop / local dev box, against the PDFs:
    docker exec -it wms_backend python3 scripts/backfill_dealer_details_from_invoices.py \
        extract --dir /tmp/old_invoices --out /tmp/dealer_backfill.json

    # 2. Copy ONLY dealer_backfill.json to the server (no PDFs), then there:
    /path/to/.venv/bin/python3 scripts/backfill_dealer_details_from_invoices.py \
        apply --in /tmp/dealer_backfill.json --company-id 1          # dry run
    /path/to/.venv/bin/python3 scripts/backfill_dealer_details_from_invoices.py \
        apply --in /tmp/dealer_backfill.json --company-id 1 --commit  # actually write

`apply` is a dry run by default — prints what it would complete, writes nothing — until
--commit is added. `extract` never writes to a database regardless.
"""
import argparse
import glob
import json
import os
import sys

from dotenv import load_dotenv

# See backfill_cadila_po_receipts.py for why both of these are needed when run as a
# plain script rather than `python -m`.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

# Importing these (transitively) makes the app connect to whatever database this
# environment's .env points at, even in `extract` mode, which never queries it — that
# connection is the app's own eager startup behaviour (api.shared.db_manager), not
# something this script asks for. Harmless: `extract` only ever reads PDFs and writes
# the output file, but the printed "DB ready" lines below are why.
from api.modules.inventory.ingestion import parser
from api.modules.platform.catalog import dealer_business
# Private, but it is exactly the function a live invoice upload calls per row — reusing
# it keeps the GSTIN validation, credit_days parsing and dealer_code/name lookup order
# identical to the real thing, rather than a second copy that could quietly drift from it.
from api.modules.fulfillment.invoice.business import _resolve_dealer  # pylint: disable=protected-access


def _row_from_doc(doc):
    """The subset of pdf_upload_adapter's row shape that _resolve_dealer and
    dealer_details_from_row actually read, built straight from one parsed document —
    there is no need to expand it into the full per-line DataFrame row shape a real
    invoice upload uses, since this never creates an invoice or touches an order."""
    return {
        'Code': doc.get('party_gstin') or '',
        'Account Name': doc.get('party_name') or '',
        'Party GSTIN': doc.get('party_gstin') or '',
        'Party Address': doc.get('party_address') or '',
        'Party Town': doc.get('party_town') or '',
        'Party State': doc.get('party_state') or '',
        'Party Pincode': doc.get('party_pincode') or '',
        'Party Phone': doc.get('party_phone') or '',
        'Party Alt Phone': doc.get('party_alt_phone') or '',
        'Party PAN': doc.get('party_pan') or '',
        'Party Drug Licenses': doc.get('party_drug_license_numbers') or '',
        'Sale Type': doc.get('sale_type') or '',
        'Credit Days': doc.get('credit_days') if doc.get('credit_days') is not None else '',
    }


def scan(paths):
    """Parse every PDF, splitting into (usable, skipped, failed)."""
    usable, skipped, failed = [], [], []
    for path in paths:
        try:
            doc = parser.parse_pdf(path, os.path.basename(path))
        except parser.ParseError as e:
            failed.append((path, str(e)))
            continue
        if doc['doc_type'] not in parser.OUTBOUND_TYPES:
            skipped.append((path, f"a {doc.get('doc_title') or doc['doc_type']}, not a sales invoice"))
            continue
        if not (doc.get('party_name') or doc.get('party_gstin')):
            skipped.append((path, 'no buyer name or GSTIN printed on it'))
            continue
        usable.append((path, doc))
    return usable, skipped, failed


# ── extract ─────────────────────────────────────────────────────────────────────────

def cmd_extract(args):
    paths = sorted(glob.glob(os.path.join(args.dir, '**', '*.pdf'), recursive=True))
    if not paths:
        print(f"No .pdf files found under {args.dir}")
        return

    print(f"Found {len(paths)} PDF(s) under {args.dir}\n")
    usable, skipped, failed = scan(paths)

    print(f"Usable (sales invoice with a buyer on it): {len(usable)}")
    print(f"Skipped:                                   {len(skipped)}")
    print(f"Could not parse:                           {len(failed)}")

    if skipped:
        print("\nSkipped:")
        for path, reason in skipped:
            print(f"  {os.path.basename(path)}: {reason}")
    if failed:
        print("\nCould not parse:")
        for path, reason in failed:
            print(f"  {os.path.basename(path)}: {reason}")

    records = []
    for path, doc in usable:
        row = _row_from_doc(doc)
        details = dealer_business.dealer_details_from_row(row)
        dealer_name = (doc.get('party_name') or '').strip()
        dealer_code = (doc.get('party_gstin') or '').strip() or None
        if not dealer_name and not dealer_code:
            continue  # scan() already excludes this, but stay consistent if that changes
        records.append({
            'source_file': os.path.basename(path),
            'dealer_name': dealer_name,
            'dealer_code': dealer_code,
            'details': details,
        })

    # One PDF per record on purpose, duplicates included: the same dealer can appear on
    # several invoices, each printing a slightly different subset of its details (one
    # invoice's header cuts off the pincode, another's carries it) — `apply` resolves
    # every record to the same dealer_id and fills whatever is still blank at that point,
    # so a later record can complete what an earlier one on the same dealer left out.
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(records)} record(s) to {args.out}")
    print("Nothing was written to any database. Copy this file to where `apply` will "
          "run and run that with --commit when ready.")


# ── apply ───────────────────────────────────────────────────────────────────────────

def cmd_apply(args):
    with open(args.infile, encoding='utf-8') as fh:
        records = json.load(fh)

    if not records:
        print(f"{args.infile} has no records — nothing to do.")
        return

    print(f"Loaded {len(records)} record(s) from {args.infile}\n")
    print(f"{'[DRY RUN] ' if not args.commit else ''}What each record would complete on its dealer:")
    for r in records:
        details = r.get('details') or {}
        fields = ', '.join(sorted(details)) if details else '(nothing on this record to add)'
        who = r.get('dealer_name') or r.get('dealer_code') or '(unnamed)'
        print(f"  {r.get('source_file', '?')}: {who} — {fields}")

    if not args.commit:
        print("\nDry run only — nothing written. Re-run with --commit to write these.")
        print("Note: a field only gets WRITTEN if the dealer's own column is currently")
        print("blank — this preview lists what each record carries, not what will change.")
        return

    print("\nWriting...")
    resolved, no_dealer = 0, []
    for r in records:
        row = {
            'Code': r.get('dealer_code') or '',
            'Account Name': r.get('dealer_name') or '',
        }
        details = r.get('details') or {}
        # dealer_details_from_row() expects the "Party ..." header names, not the plain
        # field keys extract() already resolved them to — reconstruct just enough of that
        # shape for it to hand straight back what's already in `details`, so `apply`
        # keeps using the exact same _resolve_dealer() call a live upload uses.
        header_by_field = dealer_business._ROW_HEADERS  # pylint: disable=protected-access
        for field, value in details.items():
            header = header_by_field.get(field)
            if header:
                row[header] = value
        if 'gstin' in details:
            row['Party GSTIN'] = details['gstin']

        dealer_id = _resolve_dealer(row, index=r.get('source_file', '?'), company_id=args.company_id)
        if dealer_id:
            resolved += 1
        else:
            no_dealer.append(r.get('source_file', '?'))

    print(f"\nDone. {resolved} record(s) resolved to a dealer — each had its blank detail "
          f"fields completed; fields it already had on file were left untouched.")
    if no_dealer:
        print(f"\n{len(no_dealer)} record(s) had no usable Code (GSTIN) or Account Name, "
              f"so no dealer could be resolved:")
        for src in no_dealer:
            print(f"  {src}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p_extract = sub.add_parser('extract', help='Parse PDFs into a JSON file (no DB writes).')
    p_extract.add_argument('--dir', required=True,
                            help='Folder of invoice PDFs (scanned recursively for *.pdf)')
    p_extract.add_argument('--out', required=True, help='Path to write the JSON file to')
    p_extract.set_defaults(func=cmd_extract)

    p_apply = sub.add_parser('apply', help='Apply a JSON file from `extract` to the database.')
    p_apply.add_argument('--in', dest='infile', required=True,
                          help='JSON file produced by `extract`')
    p_apply.add_argument('--company-id', required=True, type=int,
                          help="This environment's company_id for the Cadila tenant — "
                               "check, don't assume, it differs between databases.")
    p_apply.add_argument('--commit', action='store_true',
                          help='Actually write. Without this flag, only prints a preview.')
    p_apply.set_defaults(func=cmd_apply)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    sys.exit(main())
