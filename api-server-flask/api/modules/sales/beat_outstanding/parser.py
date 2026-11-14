# -*- encoding: utf-8 -*-
"""Parsers for the files Beat Outstanding reads. Pure functions — no database.

  outstanding   Tally Bills Receivable export (.xlsx)  -> bill rows, plus whose report it is
  exec beats    User / Beat sheet (.csv/.xlsx)         -> rows for the Executive Beats table
"""

import csv
import io
import re
from datetime import date, datetime


class ParseError(Exception):
    pass


FEED_OUTSTANDING = 'outstanding'

FEED_LABELS = {
    FEED_OUTSTANDING: 'Outstanding Report',
}


# ── low-level helpers ────────────────────────────────────────────────────────

def _s(v):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


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
# party header reads 'Name | Division | Town': the whole text is kept as the party's name,
# exactly as Tally prints it, and only the part before the first '|' is matched to the
# Outlet Master. That layout starts 'Group : <group> ... 1-Apr-26 to 6-Nov-26' on one
# row, so the group is taken as whose report it is, and the period is looked for in
# every cell above the header.

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
        'opening': col(lambda t: t.startswith('opening')),
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


def _opening(row, cols):
    if cols.get('opening') is None:
        return None
    v = _signed(_cell(row, cols['opening']))
    return None if v is None else round(v, 2)


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
            texts = [_s(v) for v in values if _s(v)]
            if not distributor and texts:
                distributor = texts[0]
                if distributor.rstrip(':').strip().lower() == 'group':
                    distributor = texts[1] if len(texts) > 1 else ''
            for t in texts:
                m = _PERIOD.match(t)
                if m and report_to is None:
                    report_to = _date(m.group(2))
            cols = _find_columns(values)
            continue

        bill_date = _date(_cell(values, cols['date']))
        ref = _s(_cell(values, cols['ref']))
        name = _s(_cell(values, cols['party']))
        if bill_date is None and not ref:
            amount = _signed(_cell(row, cols['amount']))
            if name and amount is None:
                party = name
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
            'name_key': name_key(party.split('|')[0]),
            'bill_date': bill_date,
            'ref_no': ref,
            'amount': round(amount, 2),
            'opening': _opening(row, cols),
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


# ── Executive beats (bulk fill of the table on the Executive Beats page) ─────

# Header names accepted, compared without case or spaces (SEName / BeatName too, as a
# DMS beat export names them).
EXEC_BEAT_USER = ('user', 'sename', 'executive', 'username')
EXEC_BEAT_BEAT = ('beat', 'beatname')


def parse_exec_beats(data, filename):
    """([{se_name, beat_name}], warnings) from a file with a User and a Beat column.
    Nothing is stored here: the rows go back to the page to be checked and saved."""
    header, rows = _table(data, filename)
    norm = {re.sub(r'[\s_]+', '', h).lower(): h for h in header if h}
    user = next((norm[k] for k in EXEC_BEAT_USER if k in norm), None)
    beat = next((norm[k] for k in EXEC_BEAT_BEAT if k in norm), None)
    if not user or not beat:
        raise ParseError('The file needs two columns: User and Beat.')
    out, seen, warnings = [], set(), []
    for i, r in enumerate(rows, start=2):
        se, b = _s(r.get(user)), _s(r.get(beat))
        if not se or not b:
            warnings.append(f'Row {i}: {"no User" if not se else "no Beat"} — skipped')
            continue
        key = (se.casefold(), b.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append({'se_name': se, 'beat_name': b})
    if not out:
        raise ParseError('No User / Beat rows in this file.')
    return out, warnings


PARSERS = {
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
