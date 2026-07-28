# -*- encoding: utf-8 -*-
"""
DMS file generation for app-submitted orders.

A submitted order's parts become the company's DMS upload file (the operator
downloads it and uploads it into the company's DMS). The parts come from
submitted_order_products either way:

  - itemised orders already have their lines (sku_code / quantity / product_name / mrp),
    so nothing extra is needed;
  - photo orders have no lines until a part_convertor user reads the photo and fills a
    "part convertor" sheet, which parse_part_convertor() turns into those same lines.

The DMS layout is company-specific. Only Hero's is known so far (HERO_DMS below);
other companies fall back to it until their own sample is provided.
"""

import csv
import io

import openpyxl


class PartConvertorError(Exception):
    """The uploaded part-convertor sheet could not be understood."""


# --------------------------------------------------------------------------- #
# Part convertor sheet (photo orders)                                         #
# --------------------------------------------------------------------------- #
# The part_convertor user fills a sheet like "Part Convertor Sample.xlsx":
#     S.NO. | PART# | QTY | DESC. | MRP
# Header matching is lenient (case / spacing / punctuation are ignored) so small
# formatting differences between operators don't break the import.

def _norm(header):
    return ''.join(ch for ch in str(header or '').lower() if ch.isalnum())


def parse_part_convertor(file_storage):
    """Parse an uploaded part-convertor workbook into order lines.

    Returns a list of {sku_code, quantity, product_name, mrp}. Rows without a part
    number or with a non-positive quantity are skipped. Raises PartConvertorError on
    an unreadable file or missing required columns.
    """
    try:
        wb = openpyxl.load_workbook(file_storage, data_only=True)
    except Exception as e:  # openpyxl raises a grab-bag of errors on bad input
        raise PartConvertorError(f"could not read the file as an Excel workbook ({e})")

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise PartConvertorError("the sheet is empty")

    header = [_norm(c) for c in rows[0]]

    def find(*aliases):
        for a in aliases:
            if a in header:
                return header.index(a)
        return None

    i_part = find('part', 'partno', 'partnumber', 'partno.')
    i_qty = find('qty', 'quantity', 'orderquantity')
    i_desc = find('desc', 'description', 'partdescription')
    i_mrp = find('mrp', 'price', 'rate')
    if i_part is None or i_qty is None:
        raise PartConvertorError("the sheet needs at least a PART# column and a QTY column")

    def cell(row, idx):
        return row[idx] if (idx is not None and idx < len(row)) else None

    items = []
    for row in rows[1:]:
        if row is None:
            continue
        part = cell(row, i_part)
        if part is None or str(part).strip() == '':
            continue
        raw_qty = cell(row, i_qty)
        try:
            qty = int(float(raw_qty)) if raw_qty not in (None, '') else 0
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue

        desc = cell(row, i_desc)
        raw_mrp = cell(row, i_mrp)
        try:
            mrp = float(raw_mrp) if raw_mrp not in (None, '') else None
        except (TypeError, ValueError):
            mrp = None

        items.append({
            'sku_code': str(part).strip(),
            'quantity': qty,
            'product_name': (str(desc).strip() if desc not in (None, '') else None),
            'mrp': mrp,
        })

    if not items:
        raise PartConvertorError("no usable rows found (each needs a PART# and QTY greater than 0)")
    return items


# --------------------------------------------------------------------------- #
# DMS output file (company-specific)                                          #
# --------------------------------------------------------------------------- #
# Each builder takes the order's line items and yields rows (header first).
# `item` is a dict with sku_code / quantity / product_name / mrp.

def _hero_dms_rows(items):
    # Hero DMS: Part Number, Part Description, Quantity, MOQ. Description comes from the
    # line (product_name — the DESC. from the part-convertor sheet, or the product name
    # for itemised orders) when present, else blank. MOQ is left empty for now: the
    # system has no minimum-order-quantity source (to be defined later).
    yield ['Part Number', 'Part Description', 'Quantity', 'MOQ']
    for it in items:
        yield [it['sku_code'], it.get('product_name') or '', it['quantity'], '']


# Keyed by lower-cased company name. Only companies whose DMS sample we've actually
# seen get a builder — there is deliberately NO default: the layout is company-specific,
# so falling back to Hero's format for another company would produce a wrong file. Add a
# company here when its own sample arrives.
COMPANY_DMS_BUILDERS = {
    'hero': _hero_dms_rows,
}


class DMSNotConfiguredError(Exception):
    """No DMS layout is known for this company yet."""


def has_dms_format(company_name):
    """True only when a company's DMS layout is known (so far, just Hero)."""
    return (company_name or '').strip().lower() in COMPANY_DMS_BUILDERS


def build_dms_csv(company_name, items):
    """Render the DMS file for `company_name` as CSV text (matches that company's
    sample). Raises DMSNotConfiguredError if the company's layout isn't known yet."""
    builder = COMPANY_DMS_BUILDERS.get((company_name or '').strip().lower())
    if builder is None:
        raise DMSNotConfiguredError(company_name)
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in builder(items):
        writer.writerow(row)
    return buf.getvalue()
