# -*- encoding: utf-8 -*-
"""Parsers for the three Beat Outstanding uploads. Pure functions — no database.

  outlets      DMS Outlet Master (.csv/.xlsx)         -> outlet rows (outlet -> beat, city)
  beat_plan    DMS User Beat Details (.csv/.xlsx)     -> plan rows (executive x date x beat)
  outstanding  Tally Bills Receivable export (.xlsx)  -> bill rows, plus whose report it is

Every feed replaces what is stored, so a file is checked for its own columns BEFORE
anything is replaced: a beat plan dropped into the Outlet Master slot is refused rather
than wiping every outlet.
"""

import csv
import io
import re
from datetime import date, datetime


class ParseError(Exception):
    pass


FEED_OUTLETS = 'outlets'
FEED_BEAT_PLAN = 'beat_plan'
FEED_OUTSTANDING = 'outstanding'

FEED_LABELS = {
    FEED_OUTLETS: 'Outlet Master',
    FEED_BEAT_PLAN: 'Beat Plan',
    FEED_OUTSTANDING: 'Outstanding Report',
}

# Only the columns read here are required, so an export that gains a column still loads.
OUTLET_COLS = ['Outlet_Name', 'Beat_ID', 'Beat_Name']
BEAT_PLAN_COLS = ['SEName', 'Date', 'BeatId', 'BeatName']


# ── low-level helpers ────────────────────────────────────────────────────────

def _s(v):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _int(v):
    try:
        return int(float(_s(v).replace(',', '') or 0))
    except ValueError:
        return 0


def _date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _s(v)
    if not s or s.startswith('0000'):
        return None
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%d-%m-%Y', '%d/%m/%Y', '%d-%b-%y',
                '%d-%b-%Y', '%d.%m.%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def name_key(name):
    """A party/outlet name reduced to what identifies it, so Tally's ledger name and the
    DMS outlet name meet: 'M/S UPKAR  HARDWARE  STORE' and 'M/s Upkar Hardware Store'
    -> 'UPKAR HARDWARE STORE'. Case, the 'M/S' prefix, '&' vs 'AND', punctuation and
    repeated spaces are all ignored; nothing else is — no fuzzy matching, because a
    near-miss would hand one dealer's dues to another beat's executive."""
    s = _s(name).upper().replace('&', ' AND ')
    s = re.sub(r'^\s*M\s*/\s*S\b\.?', '', s)
    s = re.sub(r'[^A-Z0-9]+', ' ', s)
    return ' '.join(s.split())


def _table(data, filename):
    """Header and rows of a single-table export (.csv, or the first sheet of an .xlsx)."""
    name = (filename or '').lower()
    if name.endswith(('.xlsx', '.xlsm')):
        ws = _workbook(data).worksheets[0]
        it = ws.iter_rows(values_only=True)
        header = [_s(h) for h in next(it, [])]
        return header, [dict(zip(header, r)) for r in it if any(c not in (None, '') for c in r)]
    if name.endswith('.csv') or not name:
        text = data.decode('utf-8-sig', errors='replace')
        reader = csv.reader(io.StringIO(text))
        header = [h.strip() for h in next(reader, [])]
        return header, [dict(zip(header, r)) for r in reader if any(c.strip() for c in r)]
    raise ParseError('Upload the report as .csv or .xlsx.')


def _workbook(data, read_only=True):
    from openpyxl import load_workbook
    try:
        return load_workbook(io.BytesIO(data), read_only=read_only, data_only=True)
    except Exception as e:
        raise ParseError(f'Could not read this file as an Excel workbook — {e}')


def _require(header, cols, label):
    missing = [c for c in cols if c not in header]
    if missing:
        raise ParseError(f'Not a {label} — missing column(s): {", ".join(missing)}. '
                         'Nothing was changed.')


# ── DMS feeds ────────────────────────────────────────────────────────────────

def parse_outlets(data, filename):
    header, rows = _table(data, filename)
    _require(header, OUTLET_COLS, FEED_LABELS[FEED_OUTLETS])
    out, warnings = [], []
    for i, r in enumerate(rows, start=2):
        name = _s(r.get('Outlet_Name'))
        if not name:
            warnings.append(f'Row {i}: no Outlet_Name — skipped')
            continue
        beat_id = _s(r.get('Beat_ID'))
        if not beat_id or beat_id == '0':
            warnings.append(f'Row {i}: {name} is on no beat')
            beat_id = ''
        out.append({
            'outlet_id': _s(r.get('Outlet_Id')),
            'outlet_name': name,
            'name_key': name_key(name),
            'beat_id': beat_id,
            'beat_name': _s(r.get('Beat_Name')),
            'city': _s(r.get('city') or r.get('City')),
            'distributor': _s(r.get('Distributor')),
        })
    return {'outlets': out}, warnings, {}


def parse_beat_plan(data, filename):
    header, rows = _table(data, filename)
    _require(header, BEAT_PLAN_COLS, FEED_LABELS[FEED_BEAT_PLAN])
    out, warnings = [], []
    for i, r in enumerate(rows, start=2):
        se, beat_id, plan_date = _s(r.get('SEName')), _s(r.get('BeatId')), _date(r.get('Date'))
        if not se or not beat_id or not plan_date:
            warnings.append(f'Row {i}: no SEName, BeatId or Date — skipped')
            continue
        out.append({
            'user_id': _s(r.get('UserID')),
            'se_name': se,
            'plan_date': plan_date,
            'beat_id': beat_id,
            'beat_name': _s(r.get('BeatName')),
            'total_outlets': _int(r.get('Total_Outlets')),
        })
    return {'beat_plan': out}, warnings, {}


# ── Tally Bills Receivable ───────────────────────────────────────────────────
#
# Tally's export is a printed report, not a flat table:
#
#   Ebco Anmol Associates                  <- the distributor whose books these are
#   ...
#   1-Apr-26 to 17-Oct-26                  <- the period; its end is the report date
#   Date | Ref. No. | Party's Name | Pending Amount | Due on | Overdue by days
#        |          | CLASSIC HARDWARE  |          |        |          <- a party
#   12-Sep-26 | 26-27-EB-INV-10 |  | 104929 | 12-Sep-26 | 35          <- its bills
#        |          |                   | 104929   |        |          <- party subtotal
#   ...                                   | 2428314  |                <- grand total
#
# A row is a bill when it carries BOTH a date and a reference number; a party header
# carries a name and neither; subtotals carry neither and no name. Columns are found by
# their header text, so the layout with Opening / Pending / Final Balance columns (some
# companies' Tally prints those) reads too — Final Balance is then the amount. There a
# party header reads 'Name | Division | Town', of which the name is kept.

def _find_columns(header):
    """{role: index} from Tally's header row, or None if this row is not it."""
    texts = [_s(h).lower() for h in header]

    def col(pred):
        return next((i for i, t in enumerate(texts) if pred(t)), None)

    cols = {
        'date': col(lambda t: t == 'date'),
        'ref': col(lambda t: t.startswith('ref')),
        'party': col(lambda t: t.startswith('party')),
        'amount': col(lambda t: t.startswith('final balance')),
        'due': col(lambda t: t.startswith('due on')),
    }
    if cols['amount'] is None:
        cols['amount'] = col(lambda t: t.startswith('pending'))
    if cols['date'] is None or cols['party'] is None or cols['amount'] is None:
        return None
    return cols


def _cell(row, i):
    return row[i] if i is not None and i < len(row) else None


def _signed(cell):
    """A bill's amount — negative for a credit. Tally prints every amount as a positive
    number and keeps the sign in the cell's number format (a literal 'Cr' suffix)."""
    if cell is None or cell.value in (None, ''):
        return None
    try:
        amount = float(cell.value)
    except (TypeError, ValueError):
        return None
    return -amount if 'Cr' in (cell.number_format or '') else amount


_PERIOD = re.compile(r'^\s*(\S+)\s+to\s+(\S+)\s*$', re.I)


def parse_outstanding(data, filename):
    if not (filename or '').lower().endswith(('.xlsx', '.xlsm')):
        raise ParseError('Upload the Tally outstanding report as .xlsx. Nothing was changed.')
    ws = _workbook(data).worksheets[0]

    distributor, report_to, cols = '', None, None
    party, bills, warnings, last_total = None, [], [], None
    for n, row in enumerate(ws.iter_rows(), start=1):
        values = [c.value for c in row]
        if cols is None:
            first = next((_s(v) for v in values if _s(v)), '')
            if not distributor and first:
                distributor = first
            m = _PERIOD.match(first)
            if m:
                report_to = _date(m.group(2))
            cols = _find_columns(values)
            continue

        bill_date = _date(_cell(values, cols['date']))
        ref = _s(_cell(values, cols['ref']))
        name = _s(_cell(values, cols['party']))
        if bill_date is None and not ref:
            amount = _signed(_cell(row, cols['amount']))
            if name and amount is None:
                party = name.split('|')[0].strip()
            elif not name and amount is not None:
                last_total = amount
            continue
        if bill_date is None or not ref or not party:
            warnings.append(f'Row {n}: half a bill (date or reference missing) — skipped')
            continue
        amount = _signed(_cell(row, cols['amount']))
        if amount is None:
            warnings.append(f'Row {n}: bill {ref} has no amount — skipped')
            continue
        bills.append({
            'party_name': party,
            'name_key': name_key(party),
            'bill_date': bill_date,
            'ref_no': ref,
            'amount': round(amount, 2),
            'due_on': _date(_cell(values, cols['due'])) or bill_date,
        })

    if cols is None:
        raise ParseError("Not a Tally outstanding report — no header row with Date, Party's "
                         'Name and Pending / Final Balance. Nothing was changed.')
    if not bills:
        raise ParseError('No pending bills found in this report. Nothing was changed.')
    total = round(sum(b['amount'] for b in bills), 2)
    if last_total is not None and abs(round(last_total, 2) - total) > 0.01:
        warnings.append(f'Bills add up to {total:,.2f} but the report total is '
                        f'{last_total:,.2f} — check the export')
    return {'bills': bills}, warnings, {'distributor': distributor, 'report_to': report_to,
                                        'total': total}


PARSERS = {
    FEED_OUTLETS: parse_outlets,
    FEED_BEAT_PLAN: parse_beat_plan,
    FEED_OUTSTANDING: parse_outstanding,
}


def parse(feed, stream, filename):
    """({table_key: rows}, warnings, meta). Raises ParseError on the wrong file or no rows."""
    if feed not in PARSERS:
        raise ParseError(f'Unknown upload type: {feed}')
    tables, warnings, meta = PARSERS[feed](stream.read(), filename)
    if not any(tables.values()):
        raise ParseError(f'No usable rows in this {FEED_LABELS[feed]}. Nothing was changed.')
    return tables, warnings, meta
