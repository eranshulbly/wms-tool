# -*- encoding: utf-8 -*-
"""Dealer Payment Tracker — parsers for the two Tally exports it reads. Pure functions: bytes in,
plain dicts out, no database. See Cadila/dealer_payment_tracker_spec.md.

  parse_outstanding(data)     Tally Export 1: Outstanding (pending bills), group "Cadila Dist",
                              with or without bill-wise voucher detail
  parse_receipt_register(data)  Tally Export 2: Receipt Register

Party names are the dealer key (dealers are created from them) and are kept EXACTLY as
Tally writes them: no trimming, no case change ('Shri Ram Pharma  | Cadila | Chandausi' has two spaces).

Tally writes every amount as a positive number and puts Dr/Cr in the cell's NUMBER FORMAT
(""0.00" Dr" / ""0.00" Cr"), which pandas drops — so amounts are read with openpyxl and
signed from the format: Dr positive (the dealer owes), Cr negative.
"""

import io
import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

import openpyxl


class ParseError(ValueError):
    """The file is not the expected export, or fails one of its own totals."""


CENTS = Decimal('0.01')

# Bill reference kinds (Export 1, column "Ref. No.").
KIND_INVOICE = 'invoice'          # A000031 — Cadila sales invoice (Dr)
KIND_BOUNCE = 'bounce'            # Boo 338558 — bill made by a Payment voucher: a bounced /
                                  # reversed receipt, Dr: the dealer owes it again
KIND_CREDIT_NOTE = 'credit_note'  # CN00005, SC00001 — credit notes (Cr)
KIND_OTHER = 'other'

_RE_INVOICE = re.compile(r'^A\d{6}$')
_RE_BOUNCE = re.compile(r'^Boo\s+\d+$')
_RE_CREDIT_NOTE = re.compile(r'^(CN|SC)\d+$')
_RE_PERIOD = re.compile(r'(\d{1,2}-[A-Za-z]{3}-\d{2,4})\s+to\s+(\d{1,2}-[A-Za-z]{3}-\d{2,4})')


def bill_kind(ref_no):
    ref = (ref_no or '').strip()
    if _RE_INVOICE.match(ref):
        return KIND_INVOICE
    if _RE_BOUNCE.match(ref):
        return KIND_BOUNCE
    if _RE_CREDIT_NOTE.match(ref):
        return KIND_CREDIT_NOTE
    return KIND_OTHER


# ── cells ─────────────────────────────────────────────────────────────────────

def _blank(v):
    return v is None or (isinstance(v, str) and v.strip() == '')


def _text(v):
    """A cell's text exactly as written (None for an empty cell). Not stripped."""
    if _blank(v):
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _ref(v):
    """A reference or voucher number: outer whitespace is not part of it."""
    t = _text(v)
    return t.strip() if t is not None else None


def _date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()
        for fmt in ('%d-%b-%y', '%d-%b-%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                pass
    return None


def _decimal(v):
    if _blank(v):
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)).quantize(CENTS, ROUND_HALF_UP)
    s = str(v).replace(',', '').strip()
    try:
        return Decimal(s).quantize(CENTS, ROUND_HALF_UP)
    except Exception:
        return None


def dr_cr_sign(number_format):
    """+1 for a Dr format, -1 for Cr, None when the format names neither."""
    fmt = number_format or ''
    if re.search(r'\bCr\b', fmt):
        return -1
    if re.search(r'\bDr\b', fmt):
        return 1
    return None


def signed_amount(cell, warnings=None, where=''):
    """The cell's amount, Cr negative. A plain number (no Dr/Cr in the format) is taken
    as written."""
    amount = _decimal(cell.value)
    if amount is None:
        return None
    sign = dr_cr_sign(cell.number_format)
    if sign is None:
        return amount
    if amount < 0 and warnings is not None:
        warnings.append(f'{where}: negative amount {amount} in a Dr/Cr cell; sign taken from the format.')
    return abs(amount) * sign


def _period(rows, upto):
    """(from, to) dates from the first 'd-Mmm-yy to d-Mmm-yy' text in rows[:upto]."""
    for row in rows[:upto]:
        for c in row:
            if isinstance(c.value, str):
                m = _RE_PERIOD.search(c.value)
                if m:
                    return _date(m.group(1)), _date(m.group(2))
    return None, None


def _load(data):
    try:
        return openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    except Exception as e:
        raise ParseError(f'Not a readable .xlsx file ({e.__class__.__name__}). Export it from Tally as Excel.')


# ── Export 1: Outstanding ─────────────────────────────────────────────────────

def _header_row(rows, first, second):
    for i, row in enumerate(rows[:30]):
        a = _text(row[0].value) if len(row) > 0 else None
        b = _text(row[1].value) if len(row) > 1 else None
        if a and b and a.strip() == first and b.strip() == second:
            return i
    return None


def _columns(rows, head):
    """{label: column index} from the two-line header starting at rows[head]."""
    cols = {}
    width = max(len(rows[head]), len(rows[head + 1]) if head + 1 < len(rows) else 0)
    for j in range(width):
        top = _text(rows[head][j].value) if j < len(rows[head]) else None
        low = _text(rows[head + 1][j].value) if head + 1 < len(rows) and j < len(rows[head + 1]) else None
        label = ' '.join(p.strip() for p in (top, low) if p and p.strip())
        if label:
            cols[label] = j
    return cols


def _find(cols, *prefixes):
    for label, j in cols.items():
        if any(label.lower().startswith(p.lower()) for p in prefixes):
            return j
    return None


def parse_outstanding(data):
    """Tally Export 1 (Outstanding, pending bills) -> dict:

      as_of         the export date (end of the 'd-Mmm-yy to d-Mmm-yy' range on row 1)
      period_from   the start of that range
      detail        True when the file has bill-wise voucher lines (GrpBills layout)
      bills         [{party, ref_no, kind, bill_date, opening_amt, pending_amt, post_dated_amt,
                      final_amt, due_on, overdue_days, row}]   amounts signed, Cr negative
      adjustments   [{party, ref_no, vch_type, vch_no, vch_date, amount, row}]  (detail only)
      grand_total   Tally's grand pending total, signed
      warnings      [str]

    Checks, raising ParseError: each party's bills add up to Tally's subtotal for them, and
    all bills add up to the grand total.
    """
    wb = _load(data)
    ws = wb['Cadila Dist'] if 'Cadila Dist' in wb.sheetnames else wb.worksheets[0]
    rows = list(ws.iter_rows())
    head = _header_row(rows, 'Date', 'Ref. No.')
    if head is None:
        raise ParseError('Not the Tally Outstanding export: no "Date | Ref. No." header found.')
    period_from, as_of = _period(rows, head)
    if as_of is None:
        raise ParseError('Could not read the "1-Apr-.. to ..-..-.." range on the first row.')

    cols = _columns(rows, head)
    c_open = _find(cols, 'Opening')
    c_pend = _find(cols, 'Pending')
    c_pdc = _find(cols, 'Post-Dated', 'Post Dated')
    c_final = _find(cols, 'Final')
    c_due = _find(cols, 'Due on')
    c_over = _find(cols, 'Overdue')
    if c_open is None or c_pend is None:
        raise ParseError('Not the Tally Outstanding export: no Opening / Pending Amount columns.')
    # With voucher detail, the voucher columns (Vch Type, Vch No., Amount) sit in C, D, E
    # and the bill amounts move right; without it, Opening is the fourth column.
    detail = c_open > 4
    C_DATE, C_REF, C_PARTY, C_VNO, C_VAMT = 0, 1, 2, 3, 4

    def cell(row, j):
        return row[j] if j is not None and j < len(row) else None

    def val(row, j):
        c = cell(row, j)
        return c.value if c is not None else None

    warnings, bills, adjustments, checks = [], [], [], []
    party = None          # the party whose bills are being read
    last_party = None     # the last party header seen (for a stray bill)
    block = []            # bills since the last party header / subtotal, for the subtotal check
    grand_total = None
    current_bill = None

    for i in range(head + 2, len(rows)):
        row = rows[i]
        rn = i + 1
        a, b, c = val(row, C_DATE), val(row, C_REF), val(row, C_PARTY)
        amounts_filled = any(not _blank(val(row, j)) for j in (c_open, c_pend) if j is not None)
        if all(_blank(x.value) for x in row):
            continue

        if not _blank(b) and _date(a) is not None:
            # A bill row.
            if party is None:
                if last_party is None:
                    raise ParseError(f'Row {rn}: bill {_ref(b)} comes before any party.')
                party = last_party
                warnings.append(f'Row {rn}: bill {_ref(b)} has no party header above it; '
                                f'attached to the last party, "{last_party}".')
            bill = {
                'party': party,
                'ref_no': _ref(b),
                'kind': bill_kind(_ref(b)),
                'bill_date': _date(a),
                'opening_amt': signed_amount(row[c_open], warnings, f'Row {rn}'),
                'pending_amt': signed_amount(row[c_pend], warnings, f'Row {rn}') or Decimal('0.00'),
                'post_dated_amt': signed_amount(row[c_pdc], warnings, f'Row {rn}') if cell(row, c_pdc) is not None else None,
                'final_amt': signed_amount(row[c_final], warnings, f'Row {rn}') if cell(row, c_final) is not None else None,
                'due_on': _date(val(row, c_due)),
                'overdue_days': _int(val(row, c_over)),
                'row': rn,
            }
            block.append(bill)
            current_bill = bill
            continue

        if detail and _blank(b) and _date(a) is not None and not _blank(c):
            # A voucher line under the bill above: Date | (blank) | Vch Type | Vch No. | Amount.
            if current_bill is None:
                warnings.append(f'Row {rn}: voucher line with no bill above it; skipped.')
                continue
            adjustments.append({
                'party': current_bill['party'],
                'ref_no': current_bill['ref_no'],
                'vch_type': _text(c).strip(),
                'vch_no': _ref(val(row, C_VNO)),
                'vch_date': _date(a),
                'amount': signed_amount(row[C_VAMT], warnings, f'Row {rn}'),
                'row': rn,
            })
            continue

        if _blank(a) and _blank(b) and not _blank(c) and not amounts_filled:
            # A party header: only Party's Name is filled. Kept exactly as written.
            if block:
                raise ParseError(f'Row {rn}: party "{c}" starts before the subtotal of "{party}".')
            party = last_party = _text(c)
            current_bill = None
            continue

        if _blank(a) and _blank(b) and _blank(c) and amounts_filled:
            total = signed_amount(row[c_pend], warnings, f'Row {rn}') or Decimal('0.00')
            if block:
                # The subtotal of the bills just read.
                got = sum((x['pending_amt'] for x in block), Decimal('0.00'))
                checks.append({'party': block[0]['party'], 'row': rn, 'subtotal': total, 'sum': got})
                if got != total:
                    raise ParseError(f'Row {rn}: bills of "{block[0]["party"]}" add up to {got}, '
                                     f'but Tally\'s subtotal is {total}.')
                bills.extend(block)
                block = []
                party = None
                current_bill = None
            elif grand_total is None:
                grand_total = total
            else:
                warnings.append(f'Row {rn}: another total row ({total}) after the grand total; ignored.')
            continue

        warnings.append(f'Row {rn}: not a party, bill, voucher or total row; skipped.')

    if block:
        raise ParseError(f'The bills of "{block[0]["party"]}" have no subtotal row.')
    if grand_total is None:
        raise ParseError('No grand total row found at the end of the export.')

    # A stray bill attached to a party that already has the same bill, amounts and all,
    # is the same bill printed twice — keep one.
    seen, unique = {}, []
    for x in bills:
        key = (x['party'], x['ref_no'])
        if key in seen:
            first = seen[key]
            if (first['opening_amt'], first['pending_amt']) == (x['opening_amt'], x['pending_amt']):
                warnings.append(f'Row {x["row"]}: bill {x["ref_no"]} of "{x["party"]}" repeats row '
                                f'{first["row"]}; counted once.')
                continue
            raise ParseError(f'Row {x["row"]}: bill {x["ref_no"]} of "{x["party"]}" appears twice '
                             f'with different amounts (rows {first["row"]} and {x["row"]}).')
        seen[key] = x
        unique.append(x)
    bills = unique
    kept_rows = {x['row'] for x in bills}
    adjustments = [v for v in adjustments if (v['party'], v['ref_no']) in seen
                   and seen[(v['party'], v['ref_no'])]['row'] in kept_rows]

    total = sum((x['pending_amt'] for x in bills), Decimal('0.00'))
    if total != grand_total:
        raise ParseError(f'Bills add up to {total}, but Tally\'s grand total is {grand_total}.')

    return {'as_of': as_of, 'period_from': period_from, 'detail': detail, 'bills': bills,
            'adjustments': adjustments, 'grand_total': grand_total, 'subtotal_checks': checks,
            'warnings': warnings}


def _int(v):
    if _blank(v):
        return None
    try:
        return int(float(str(v).strip()))
    except ValueError:
        return None


# ── Export 2: Receipt Register ────────────────────────────────────────────────

def parse_receipt_register(data):
    """Tally Export 2 (Receipt Register) -> dict:

      period_from, period_to   the register's date range (the row above the header) — the
                               window that an upload replaces
      receipts   [{vch_no, vch_date, party, vch_type, amount, row}]   amount = Credit − Debit
      total      Tally's 'Total:' credit, checked against the rows
      warnings   [str]

    (vch_no, vch_date) is the key; a repeat inside the file is an error.
    """
    wb = _load(data)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows())
    head = _header_row(rows, 'Date', 'Particulars')
    if head is None:
        raise ParseError('Not the Tally Receipt Register: no "Date | Particulars" header found.')
    period_from, period_to = _period(rows, head)
    if period_from is None:
        raise ParseError('Could not read the register\'s "d-Mmm-yy to d-Mmm-yy" period above the header.')
    labels = {(_text(c.value) or '').strip().lower(): j for j, c in enumerate(rows[head])}
    try:
        c_date, c_party = labels['date'], labels['particulars']
        c_type, c_no = labels['vch type'], labels['vch no.']
        c_dr, c_cr = labels['debit'], labels['credit']
    except KeyError as e:
        raise ParseError(f'Not the Tally Receipt Register: no {e} column.')

    warnings, receipts, keys = [], [], {}
    total = None
    for i in range(head + 1, len(rows)):
        row = rows[i]
        rn = i + 1
        first = _text(row[c_date].value)
        if first and first.strip().lower().startswith('total'):
            total = _decimal(row[c_cr].value) or Decimal('0.00')
            total_dr = _decimal(row[c_dr].value) or Decimal('0.00')
            total = total - total_dr
            break
        d = _date(row[c_date].value)
        if d is None:
            if any(not _blank(c.value) for c in row) and i > head + 1:
                warnings.append(f'Row {rn}: no date; skipped.')
            continue
        party = _text(row[c_party].value)
        vch_no = _ref(row[c_no].value)
        if party is None or vch_no is None:
            raise ParseError(f'Row {rn}: a receipt needs Particulars and Vch No.')
        credit = _decimal(row[c_cr].value) or Decimal('0.00')
        debit = _decimal(row[c_dr].value) or Decimal('0.00')
        key = (vch_no, d)
        if key in keys:
            raise ParseError(f'Row {rn}: voucher {vch_no} of {d:%d-%b-%y} repeats row {keys[key]}.')
        keys[key] = rn
        if not (period_from <= d <= period_to):
            raise ParseError(f'Row {rn}: voucher {vch_no} is dated {d:%d-%b-%y}, outside the register\'s '
                             f'period {period_from:%d-%b-%y} to {period_to:%d-%b-%y}.')
        receipts.append({'vch_no': vch_no, 'vch_date': d, 'party': party,
                         'vch_type': (_text(row[c_type].value) or '').strip(),
                         'amount': credit - debit, 'row': rn})
    if total is None:
        raise ParseError('No "Total:" row found at the end of the register.')
    got = sum((r['amount'] for r in receipts), Decimal('0.00'))
    if got != total:
        raise ParseError(f'Receipts add up to {got}, but the register\'s total is {total}.')
    return {'period_from': period_from, 'period_to': period_to, 'receipts': receipts,
            'total': total, 'warnings': warnings}
