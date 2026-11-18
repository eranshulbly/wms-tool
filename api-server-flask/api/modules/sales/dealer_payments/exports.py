# -*- encoding: utf-8 -*-
"""The Outstanding download: a Tally-style bills-outstanding sheet (pure: data in, bytes out).

Tally's layout — party header, one line per pending bill, the party total — with two more
columns beside Pending Amount, filled on each party's total row: payments received but not
yet in Tally, and PDCs held. Neither is tied to a particular bill, so bill lines leave them
blank. The grand total of Pending Amount equals Tally's.

Amounts are signed (Dr positive, Cr negative) and shown as Tally shows them: 1,234.00 Dr.
"""

import io
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from api.modules.sales.dealer_payments import rules as R
from api.modules.sales.dealer_payments.parser import KIND_BOUNCE, KIND_CREDIT_NOTE, KIND_RECEIPT

DRCR = '#,##0.00 "Dr";#,##0.00 "Cr";0.00'
MONEY = '#,##0.00;-#,##0.00;0.00'
DATE = 'dd-mmm-yy'
BOLD = Font(bold=True)
HEAD = Font(bold=True, color='FFFFFF')
HEAD_FILL = PatternFill('solid', fgColor='1F4E78')
PARTY_FILL = PatternFill('solid', fgColor='DDEBF7')
TOTAL_TOP = Border(top=Side(style='thin'))
KIND_LABEL = {KIND_BOUNCE: 'Bounced receipt', KIND_CREDIT_NOTE: 'Credit note', 'invoice': 'Invoice',
              KIND_RECEIPT: 'Receipt (on account)', 'other': 'Other'}


def _f(v):
    """Decimal -> float for openpyxl; None stays empty."""
    return None if v is None else float(v)


def _header(ws, row, titles, widths):
    for i, (t, w) in enumerate(zip(titles, widths), start=1):
        c = ws.cell(row=row, column=i, value=t)
        c.font, c.fill = HEAD, HEAD_FILL
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _title(ws, lines):
    for i, line in enumerate(lines, start=1):
        ws.cell(row=i, column=1, value=line).font = Font(bold=(i == 1), size=13 if i == 1 else 10)
    return len(lines) + 2


def build_outstanding_xlsx(*, as_of, dealers, bills, payments, cheques, bounced_cheques, cheques_note, today,
                           company='', cleared=()):
    """`bills` the snapshot of `as_of`; `cheques` mapped cheques (with dealer_id), any status;
    `bounced_cheques` {(cheque_no, bank): boo_ref}; `cheques_note` says where/when they were read;
    `cleared` the cleared cheques Tally has no receipt for yet (rules.cleared_not_in_tally)."""
    by_id = {d['dealer_id']: d for d in dealers}
    bills_by = defaultdict(list)
    for b in bills:
        bills_by[b['dealer_id']].append(b)
    for v in bills_by.values():
        v.sort(key=lambda b: (b['bill_date'] or as_of, b['ref_no']))
    open_ids = {p['dealer_id'] for p in payments if p['status'] == R.OPEN}

    # Dealers with anything to show, in ledger-name order as Tally lists them.
    ids = (set(bills_by) | {c['dealer_id'] for c in cheques if c['status'] in R.HELD} | open_ids
           | {c['dealer_id'] for c in cleared})
    shown = sorted((by_id[i] for i in ids if i in by_id), key=lambda d: d['tally_ledger_name'].lower())
    summaries = {d['dealer_id']: R.dealer_summary(d, bills_by.get(d['dealer_id'], []), payments, cheques,
                                                  bounced_cheques.keys(), cleared) for d in shown}
    as_of_txt = as_of.strftime('%d-%b-%y') if as_of else 'no Outstanding upload yet'
    subtitle = f'Tally as of {as_of_txt} · PDCs: {cheques_note} · downloaded {today.strftime("%d-%b-%y")}'

    wb = Workbook()
    ws = wb.active
    ws.title = 'Outstanding'
    row = _title(ws, [f'{company} — Bills outstanding (dealer-wise)'.lstrip(' —'), subtitle])
    titles = ['Date', 'Ref. No.', "Party's Name", 'Type', 'Opening Amount', 'Pending Amount',
              'Received, not in Tally', 'PDCs held', 'Due on', 'Overdue by days', 'Note']
    ncol = len(titles)
    _header(ws, row, titles, [11, 14, 46, 15, 16, 16, 16, 16, 11, 10, 40])
    row += 1
    grand = {'pending': R.ZERO, 'received': R.ZERO, 'pdc': R.ZERO}
    for d in shown:
        s = summaries[d['dealer_id']]
        dbills = bills_by.get(d['dealer_id'], [])
        ws.cell(row=row, column=3, value=d['tally_ledger_name']).font = BOLD
        for col in range(1, ncol + 1):
            ws.cell(row=row, column=col).fill = PARTY_FILL
        row += 1
        for b in dbills:
            vals = {1: b['bill_date'], 2: b['ref_no'], 4: KIND_LABEL.get(b['kind'], b['kind'] or ''),
                    5: _f(b['opening_amt']), 6: _f(b['pending_amt']), 9: b['due_on'], 10: b['overdue_days'],
                    11: R.BOUNCE_LABEL if b['kind'] == KIND_BOUNCE else None}
            for col, v in vals.items():
                ws.cell(row=row, column=col, value=v)
            for col in (1, 9):
                ws.cell(row=row, column=col).number_format = DATE
            for col in (5, 6):
                ws.cell(row=row, column=col).number_format = DRCR
            row += 1

        # The party total: Tally O/S, and beside it what Tally does not know yet.
        ws.cell(row=row, column=3, value=f'Total ({len(dbills)} bill{"s" if len(dbills) != 1 else ""})').font = BOLD
        for col, v, fmt in ((6, s['tally_os'], DRCR), (7, s['received_not_in_tally'] or None, MONEY),
                            (8, s['pdc_amount'] or None, MONEY)):
            c = ws.cell(row=row, column=col, value=_f(v))
            c.number_format, c.font = fmt, BOLD
        notes = []
        if s['open_payments']:
            notes.append(f"{s['open_payments']} payment{'s' if s['open_payments'] != 1 else ''} not in Tally")
        if s['cleared_cheques']:
            notes.append(f"{s['cleared_cheques']} cleared cheque{'s' if s['cleared_cheques'] != 1 else ''} not in Tally")
        if s['pdc_count']:
            notes.append(f"{s['pdc_count']} PDC{'s' if s['pdc_count'] != 1 else ''}, next "
                         f"{s['next_pdc_date'].strftime('%d-%b-%y')}")
        if d.get('exclude_from_chase'):
            notes.append('Excluded from chase')
        if notes:
            ws.cell(row=row, column=11, value='; '.join(notes)).font = Font(italic=True)
        for col in range(1, ncol + 1):
            ws.cell(row=row, column=col).border = TOTAL_TOP
        grand['pending'] += s['tally_os']
        grand['received'] += s['received_not_in_tally']
        grand['pdc'] += s['pdc_amount']
        row += 2

    ws.cell(row=row, column=3, value='Grand Total').font = BOLD
    for col, v, fmt in ((6, grand['pending'], DRCR), (7, grand['received'], MONEY), (8, grand['pdc'], MONEY)):
        c = ws.cell(row=row, column=col, value=_f(v))
        c.number_format, c.font = fmt, BOLD
    for col in range(1, ncol + 1):
        ws.cell(row=row, column=col).border = Border(top=Side(style='thin'), bottom=Side(style='double'))

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
