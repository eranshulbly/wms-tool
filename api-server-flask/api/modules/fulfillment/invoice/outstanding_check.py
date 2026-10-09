# -*- encoding: utf-8 -*-
"""Outstanding check — a Tally "Bills Receivable / Pending Bills" export, summarised by
dealer: how much each one owes, and for how long.

Read-only by design: nothing about an uploaded file is stored. It is parsed in memory
and every figure is computed on the way out, so the same file — or a fresher one,
re-exported tomorrow — can be checked any number of times without side effects, and
nothing here ever touches this app's own `dealer` table.

Tally's own export is a structural report, not a flat table: a dealer's own header row
("Name | Division | Town", no date or amounts) is followed by one row per pending bill,
then a subtotal row Tally prints for that dealer, and the sheet ends with one grand
total row — all three of which look alike (no date, no reference number) and are not
bills themselves. The one reliable signal that a row IS a bill is that it carries BOTH a
date and a reference number; everything else carries neither, so rows are classified on
exactly that, and dealer/grand totals are summed from the bill rows rather than trusted
from Tally's own — which turns out to matter (see _signed_amount below).

Each bill's own "Overdue by days" column is not used either — it was correct as of
whenever the report was run in Tally, which goes stale the moment the clock moves on.
days_overdue is recomputed here from Due On against today, so a week-old file still
reports today's true age rather than the day it was exported.
"""

from datetime import date, datetime

# Columns, by position, in Tally's fixed "Pending Bills" layout — there is no single
# header row to resolve by name the way a flat CSV upload would (see module docstring:
# two header rows, then nested dealer groups), so position is the only stable handle.
# The full row is Date, Ref.No., Party's Name, Opening, Pending, Post-Dated, Final
# Balance, Due on, Overdue by days — only the four actually read here are named; the
# rest (Opening/Pending/Post-Dated/Overdue) are superseded by Final Balance and a
# freshly-computed days_overdue, see _signed_amount and check_outstanding.
_COL_DATE, _COL_REF, _COL_NAME, _COL_FINAL, _COL_DUE = 0, 1, 2, 6, 7


class OutstandingCheckError(ValueError):
    """The file cannot be read as a Tally outstanding/pending-bills export."""


def _as_date(v):
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ('%d-%b-%y', '%d-%b-%Y', '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_dealer_header(text):
    """'Agarwal Medical Store | Cadila | Badaun' -> (name, division, town).

    Division and town are whatever a company's own Tally ledger grouping prints after
    the name — only the name is required for a header to be recognised at all.
    """
    parts = [p.strip() for p in (text or '').split('|')]
    name = parts[0].strip() if parts and parts[0].strip() else None
    division = parts[1] if len(parts) > 1 and parts[1] else None
    town = parts[2] if len(parts) > 2 and parts[2] else None
    return name, division, town


def _signed_amount(cell):
    """A bill's amount, positive when the dealer owes it and negative when it doesn't.

    Tally prints every amount as a plain positive number — the sign lives in the CELL'S
    OWN NUMBER FORMAT instead, as a literal "Dr" or "Cr" suffix baked into the format
    string (e.g. '"0.00" Dr' vs '"0.00" Cr'), not in the reference number or any other
    visible column. A credit note can carry an ordinary-looking reference (confirmed on
    this company's own export: one credit sat under reference '4171', no 'CN' prefix at
    all) — number format is the only reliable signal. Confirmed against this file's own
    printed grand total: summing every bill this way reproduces it exactly; summing the
    raw Pending/Final Balance values with no sign adjustment overshoots it by precisely
    the sum of the Cr-formatted rows.
    """
    v = cell.value
    if v is None or v == '':
        return None
    try:
        amount = float(v)
    except (TypeError, ValueError):
        return None
    fmt = cell.number_format or ''
    return -amount if 'Cr' in fmt else amount


def check_outstanding(stream, filename, today=None):
    """Every pending bill in a Tally outstanding export, grouped by dealer.

    Raises OutstandingCheckError if the file cannot be opened as an Excel workbook, or
    if not a single bill-shaped row (see module docstring) is found anywhere in it.
    """
    try:
        import openpyxl
    except ImportError as e:  # pragma: no cover - openpyxl is a hard dependency already
        raise OutstandingCheckError(f'Excel support unavailable — {e}')

    # openpyxl's read_only mode needs a genuinely seekable stream, which the upload's own
    # stream is not guaranteed to be (a Werkzeug FileStorage can back it with a
    # SpooledTemporaryFile, whose seekable() only exists from Python 3.11) — read it into
    # a plain BytesIO first so this works the same regardless of upload size or runtime.
    import io
    try:
        buf = io.BytesIO(stream.read())
    except Exception as e:
        raise OutstandingCheckError(f'could not read the uploaded file — {e}')

    try:
        wb = openpyxl.load_workbook(buf, data_only=True, read_only=True)
    except Exception as e:
        raise OutstandingCheckError(f'could not read this file as an Excel workbook — {e}')

    today = today or date.today()
    ws = wb.worksheets[0]

    bills = []
    current_dealer = None  # (name, division, town) from the most recent header row
    for row in ws.iter_rows():
        if not row:
            continue
        date_cell = row[_COL_DATE] if len(row) > _COL_DATE else None
        ref_cell = row[_COL_REF] if len(row) > _COL_REF else None
        name_cell = row[_COL_NAME] if len(row) > _COL_NAME else None

        bill_date = _as_date(date_cell.value if date_cell is not None else None)
        ref_no = (str(ref_cell.value).strip()
                  if ref_cell is not None and ref_cell.value not in (None, '') else '')

        if bill_date is None and not ref_no:
            # Not a bill row — a dealer header (Party's Name holds "Name | Div | Town"),
            # a subtotal, the grand total, or a remark that wrapped onto its own line.
            # Only a header updates the dealer in progress; the rest carry nothing
            # needed, since totals below are re-summed from the bill rows themselves.
            name_val = name_cell.value if name_cell is not None else None
            if name_val and '|' in str(name_val):
                current_dealer = _parse_dealer_header(str(name_val))
            continue

        if bill_date is None or not ref_no or current_dealer is None:
            # Half a bill row (a date with no reference, or the reverse — not seen in
            # practice), or a bill-shaped row before any dealer header was ever seen.
            # Either way, skipped rather than guessed at.
            continue

        final_cell = row[_COL_FINAL] if len(row) > _COL_FINAL else None
        amount = _signed_amount(final_cell) if final_cell is not None else None
        if amount is None:
            continue

        due_cell = row[_COL_DUE] if len(row) > _COL_DUE else None
        due_on = _as_date(due_cell.value if due_cell is not None else None) or bill_date
        days_overdue = (today - due_on).days

        remark_val = name_cell.value if name_cell is not None else None
        name, division, town = current_dealer
        bills.append({
            'dealer_name': name,
            'division': division,
            'town': town,
            'bill_date': bill_date.isoformat(),
            'ref_no': ref_no,
            'remark': str(remark_val).strip() if remark_val else None,
            'amount': round(amount, 2),
            'due_on': due_on.isoformat(),
            'days_overdue': days_overdue,
        })

    if not bills:
        raise OutstandingCheckError(
            "no pending bills found — this doesn't look like a Tally outstanding / "
            "pending bills export")

    dealers = _group_by_dealer(bills)
    return {
        'filename': filename,
        'as_of': today.isoformat(),
        'bills': bills,
        'dealers': dealers,
        'summary': _summary(dealers),
    }


# A dealer's balance only counts as "overdue" once it is actually owed — a dealer whose
# bills net to a credit (more returned/adjusted than billed) is not at risk of anything,
# so OVER_30_DAYS only ever looks at positive amounts.
OVER_30_DAYS = 30


def _group_by_dealer(bills):
    """One row per (name, town) — town disambiguates two dealers who happen to share a
    name, the same key StockMovement/Sales Report use for a dealer elsewhere in the app.
    """
    groups = {}
    for b in bills:
        key = (b['dealer_name'], b['town'])
        g = groups.setdefault(key, {
            'dealer_name': b['dealer_name'], 'division': b['division'], 'town': b['town'],
            'bill_count': 0, 'amount': 0.0, 'max_days_overdue': None,
        })
        g['bill_count'] += 1
        g['amount'] += b['amount']
        # Only a bill actually owed (positive) sets how overdue the dealer looks — a
        # credit note's own age is not something to chase a dealer over.
        if b['amount'] > 0:
            g['max_days_overdue'] = max(g['max_days_overdue'] or 0, b['days_overdue'])

    out = []
    for g in groups.values():
        g['amount'] = round(g['amount'], 2)
        out.append(g)
    # Worst first: oldest overdue money, then the largest amount — the pair a planner
    # chasing payments wants at the top. Nulls (nothing actually owed) sort last.
    out.sort(key=lambda g: (-(g['max_days_overdue'] if g['max_days_overdue'] is not None else -1),
                            -g['amount']))
    return out


def _summary(dealers):
    over_30 = [d for d in dealers
               if (d['max_days_overdue'] or 0) > OVER_30_DAYS and d['amount'] > 0]
    return {
        'dealer_count': len(dealers),
        'bill_count': sum(d['bill_count'] for d in dealers),
        'total_outstanding': round(sum(d['amount'] for d in dealers), 2),
        'over_30_dealer_count': len(over_30),
        'over_30_amount': round(sum(d['amount'] for d in over_30), 2),
    }
