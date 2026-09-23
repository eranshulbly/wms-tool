# -*- encoding: utf-8 -*-
"""One-off backfill: complete dealer details from old invoice PDFs already on file.

Re-uploading an old invoice through the Invoice Upload screen does NOT do this.
process_invoice_dataframe() (api/modules/fulfillment/invoice/business.py) rejects any row
whose order is already in a terminal state (Invoiced / Dispatch Ready / Completed /
Partially Completed) as a duplicate BEFORE dealer resolution ever runs — and an "old"
invoice's order has, by definition, already reached one of those. This script reads each
PDF directly and calls the exact same dealer-resolution function the invoice upload uses
(_resolve_dealer -> get_or_create_dealer), bypassing the order-status gate entirely: it
never touches an order or an invoice row, only the dealer's own blank detail columns
(gstin, phone, alt_phone, address, town, state, pincode, pan, drug_license_numbers,
sale_type, credit_days).

Nothing is ever overwritten. get_or_create_dealer's _fill_blank_details() only sets a
dealer column that is currently blank — COALESCE(NULLIF(col, ''), new), same rule a live
invoice upload follows — so running this before or after Invoice Upload has processed the
same invoice, or running it twice, is equally safe.

Run wherever the app's own DB config is on the path (see backfill_cadila_po_receipts.py
for the same note in more detail — this script follows its conventions):

    docker exec -it wms_backend python3 scripts/backfill_dealer_details_from_invoices.py \
        --dir /tmp/old_invoices --company-id 3

    /path/to/.venv/bin/python3 scripts/backfill_dealer_details_from_invoices.py \
        --dir /path/to/old_invoices --company-id 1 --commit

Without --commit it only prints what each PDF would resolve to and complete — no
database writes. Review that output before adding --commit.

--company-id has no default on purpose: a dealer is looked up (and, failing that,
created) scoped to one company, and every environment can assign the Cadila tenant a
different company_id — see backfill_cadila_po_receipts.py for why guessing one is unsafe.

Scans --dir recursively for *.pdf. A file that isn't a sales invoice (a goods receipt or
credit/debit note, which this same parser also reads) is skipped, not guessed at — those
carry no buyer to enrich a dealer from in the first place.
"""
import argparse
import glob
import os
import sys

from dotenv import load_dotenv

# See backfill_cadila_po_receipts.py for why both of these are needed when run as a
# plain script rather than `python -m`.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

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


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', required=True,
                     help='Folder of invoice PDFs (scanned recursively for *.pdf)')
    ap.add_argument('--company-id', required=True, type=int,
                     help="This environment's company_id for the Cadila tenant — check, "
                          "don't assume, it differs between databases.")
    ap.add_argument('--commit', action='store_true',
                     help='Actually write. Without this flag, only prints a preview.')
    args = ap.parse_args()

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

    if not usable:
        print("\nNothing to do.")
        return

    print(f"\n{'[DRY RUN] ' if not args.commit else ''}What each invoice would complete on its dealer:")
    for path, doc in usable:
        row = _row_from_doc(doc)
        details = dealer_business.dealer_details_from_row(row)
        party = doc.get('party_name') or doc.get('party_gstin') or '(unnamed)'
        fields = ', '.join(sorted(details)) if details else '(nothing on this document to add)'
        print(f"  {os.path.basename(path)}: {party} — {fields}")

    if not args.commit:
        print("\nDry run only — nothing written. Re-run with --commit to write these.")
        print("Note: a field only gets WRITTEN if the dealer's own column is currently")
        print("blank — this preview lists what the PDF carries, not what will change.")
        return

    print("\nWriting...")
    resolved, no_dealer = 0, []
    for path, doc in usable:
        row = _row_from_doc(doc)
        dealer_id = _resolve_dealer(row, index=os.path.basename(path), company_id=args.company_id)
        if dealer_id:
            resolved += 1
        else:
            no_dealer.append(path)

    print(f"\nDone. {resolved} invoice(s) resolved to a dealer — each had its blank detail "
          f"fields completed; fields it already had on file were left untouched.")
    if no_dealer:
        print(f"\n{len(no_dealer)} PDF(s) had no usable Code (GSTIN) or Account Name, so no "
              f"dealer could be resolved:")
        for path in no_dealer:
            print(f"  {os.path.basename(path)}")


if __name__ == '__main__':
    sys.exit(main())
