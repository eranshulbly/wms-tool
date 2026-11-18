# -*- encoding: utf-8 -*-
"""The Outstanding download: a Tally-style bills-outstanding workbook (pure: data in, bytes out).

  Outstanding            Tally's layout — party header, one line per pending bill, the party
                         total — then, under each party, what the app knows on top of Tally:
                         payments received but not yet in Tally, Effective O/S, PDCs held.
                         The grand total of Pending Amount equals Tally's.
  Dealer summary         one line per dealer, as on the dealer screen
  PDC cheques            every cheque from the cheque system tied to a Cadila dealer
  Received, not in Tally payments logged in the app and still OPEN

Amounts are signed (Dr positive, Cr negative) and shown as Tally shows them: 1,234.00 Dr.
"""

import io
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from api.modules.sales.dealer_payments import rules as R
from api.modules.sales.dealer_payments.parser import KIND_BOUNCE, KIND_CREDIT_NOTE

DRCR = '#,##0.00 "Dr";#,##0.00 "Cr";0.00'
MONEY = '#,##0.00;-#,##0.00;0.00'
DATE = 'dd-mmm-yy'
BOLD = Font(bold=True)
HEAD = Font(bold=True, color='FFFFFF')
HEAD_FILL = PatternFill('solid', fgColor='1F4E78')
PARTY_FILL = PatternFill('solid', fgColor='DDEBF7')
TOTAL_TOP = Border(top=Side(style='thin'))
KIND_LABEL = {KIND_BOUNCE: 'Bounced receipt', KIND_CREDIT_NOTE: 'Credit note', 'invoice': 'Invoice'}
CHEQUE_LABEL = {R.HOLDING: 'Held (not deposited)', R.DEPOSITED: 'Deposited', R.CLEARED: 'Cleared',
                R.CHQ_BOUNCED: 'Bounced'}


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


def build_outstanding_xlsx(*, as_of, dealers, bills, payments, cheques, bounced_cheques, cheques_note, today):
    """`bills` the snapshot of `as_of`; `cheques` mapped cheques (with dealer_id), any status;
    `bounced_cheques` {(cheque_no, bank): boo_ref}; `cheques_note` says where/when they were read."""
    by_id = {d['dealer_id']: d for d in dealers}
    bills_by = defaultdict(list)
    for b in bills:
        bills_by[b['dealer_id']].append(b)
    for v in bills_by.values():
        v.sort(key=lambda b: (b['bill_date'] or as_of, b['ref_no']))
    cheques_by = defaultdict(list)
    for c in cheques:
        cheques_by[c['dealer_id']].append(c)
    open_pays = [p for p in payments if p['status'] == R.OPEN]
    pays_by = defaultdict(list)
    for p in open_pays:
        pays_by[p['dealer_id']].append(p)

    # Dealers with anything to show, in ledger-name order as Tally lists them.
    ids = set(bills_by) | {c['dealer_id'] for c in cheques if c['status'] in R.HELD} | set(pays_by)
    shown = sorted((by_id[i] for i in ids if i in by_id), key=lambda d: d['tally_ledger_name'].lower())
    summaries = {d['dealer_id']: R.dealer_summary(d, bills_by.get(d['dealer_id'], []), payments, cheques,
                                                  bounced_cheques.keys()) for d in shown}
    as_of_txt = as_of.strftime('%d-%b-%y') if as_of else 'no Outstanding upload yet'
    subtitle = f'Tally as of {as_of_txt} · PDCs: {cheques_note} · downloaded {today.strftime("%d-%b-%y")}'

    wb = Workbook()

    # ── Outstanding ──
    ws = wb.active
    ws.title = 'Outstanding'
    row = _title(ws, ['Cadila Dist — Bills outstanding (dealer-wise)', subtitle])
    _header(ws, row, ['Date', 'Ref. No.', "Party's Name", 'Type', 'Opening Amount', 'Pending Amount',
                      'Due on', 'Overdue by days', 'Note'], [11, 14, 46, 15, 16, 16, 11, 10, 44])
    row += 1
    grand = R.ZERO
    for d in shown:
        s = summaries[d['dealer_id']]
        dbills = bills_by.get(d['dealer_id'], [])
        c = ws.cell(row=row, column=3, value=d['tally_ledger_name'])
        c.font = BOLD
        for col in range(1, 10):
            ws.cell(row=row, column=col).fill = PARTY_FILL
        row += 1
        for b in dbills:
            vals = [b['bill_date'], b['ref_no'], None, KIND_LABEL.get(b['kind'], b['kind'] or ''),
                    _f(b['opening_amt']), _f(b['pending_amt']), b['due_on'], b['overdue_days'],
                    R.BOUNCE_LABEL if b['kind'] == KIND_BOUNCE else None]
            for col, v in enumerate(vals, start=1):
                ws.cell(row=row, column=col, value=v)
            ws.cell(row=row, column=1).number_format = DATE
            ws.cell(row=row, column=7).number_format = DATE
            ws.cell(row=row, column=5).number_format = DRCR
            ws.cell(row=row, column=6).number_format = DRCR
            row += 1
        grand += s['tally_os']

        def line(label, value, fmt=DRCR, bold=False, border=False, note=None):
            nonlocal row
            ws.cell(row=row, column=3, value=label).font = Font(bold=bold, italic=not bold)
            c = ws.cell(row=row, column=6, value=_f(value))
            c.number_format, c.font = fmt, Font(bold=bold)
            if note:
                ws.cell(row=row, column=9, value=note).font = Font(italic=True)
            if border:
                for col in range(1, 10):
                    ws.cell(row=row, column=col).border = TOTAL_TOP
            row += 1

        line(f'Total ({len(dbills)} bill{"s" if len(dbills) != 1 else ""}) — Tally O/S', s['tally_os'],
             bold=True, border=True)
        if s['received_not_in_tally']:
            line(f'Less: received, not in Tally ({s["open_payments"]} payment{"s" if s["open_payments"] != 1 else ""})',
                 -s['received_not_in_tally'])
            line('Effective O/S', s['effective_os'], bold=True)
        if s['pdc_count']:
            line(f'PDCs held ({s["pdc_count"]})', s['pdc_amount'], fmt=MONEY,
                 note=f'next cheque dated {s["next_pdc_date"].strftime("%d-%b-%y")}')
        if d.get('exclude_from_chase'):
            ws.cell(row=row - 1, column=9, value='Excluded from chase').font = Font(italic=True)
        row += 1
    c = ws.cell(row=row, column=3, value='Grand Total (Tally O/S)')
    c.font = BOLD
    c = ws.cell(row=row, column=6, value=_f(grand))
    c.number_format, c.font = DRCR, BOLD
    for col in range(1, 10):
        ws.cell(row=row, column=col).border = Border(top=Side(style='thin'), bottom=Side(style='double'))

    # ── Dealer summary ──
    ws = wb.create_sheet('Dealer summary')
    row = _title(ws, ['Dealer summary', subtitle])
    _header(ws, row, ['Dealer', 'Tally Ledger Name', 'Tally O/S', 'Received, not in Tally', 'Effective O/S',
                      'PDCs held (no.)', 'PDCs held (amount)', 'Next PDC', 'Oldest overdue (days)', 'Action'],
            [34, 46, 16, 16, 16, 10, 16, 11, 11, 18])
    row += 1
    order = sorted(shown, key=lambda d: (d.get('exclude_from_chase', False),
                                         R._ACTION_ORDER[summaries[d['dealer_id']]['action']],
                                         -summaries[d['dealer_id']]['effective_os']))
    for d in order:
        s = summaries[d['dealer_id']]
        action = 'Excluded from chase' if d.get('exclude_from_chase') else (
            f"WAIT till {s['wait_till'].strftime('%d-%b-%y')}" if s['action'] == 'WAIT' else s['action'])
        vals = [s['dealer'], d['tally_ledger_name'], _f(s['tally_os']), _f(s['received_not_in_tally']),
                _f(s['effective_os']), s['pdc_count'], _f(s['pdc_amount']), s['next_pdc_date'],
                s['oldest_overdue_days'], action]
        for col, v in enumerate(vals, start=1):
            ws.cell(row=row, column=col, value=v)
        for col in (3, 4, 5):
            ws.cell(row=row, column=col).number_format = DRCR
        ws.cell(row=row, column=7).number_format = MONEY
        ws.cell(row=row, column=8).number_format = DATE
        row += 1

    # ── PDC cheques ──
    ws = wb.create_sheet('PDC cheques')
    row = _title(ws, ['PDC cheques (from the cheque system)', subtitle])
    _header(ws, row, ['Dealer', 'Cheque date', 'Cheque no.', 'Bank', 'Amount', 'Status', 'Counted in PDCs held',
                      'Note'], [34, 11, 12, 26, 14, 20, 12, 40])
    row += 1
    for c in sorted(cheques, key=lambda c: (summaries.get(c['dealer_id'], {}).get('dealer') or c['dealer_id'],
                                           c['cheque_date'])):
        boo = bounced_cheques.get((c['cheque_no'], c['bank']))
        counted = c['status'] in R.HELD and not boo
        d = by_id.get(c['dealer_id'])
        vals = [f"{d['dealer_name']} ({d['town']})" if d and d.get('town') else (d['dealer_name'] if d else c['dealer_id']),
                c['cheque_date'], c['cheque_no'], c['bank'], _f(c['amount']), CHEQUE_LABEL.get(c['status'], c['status']),
                'Yes' if counted else 'No',
                f'Reversed in Tally by {boo}' if boo else (f"Name in cheque system: {c['party_name']}")]
        for col, v in enumerate(vals, start=1):
            ws.cell(row=row, column=col, value=v)
        ws.cell(row=row, column=2).number_format = DATE
        ws.cell(row=row, column=5).number_format = MONEY
        row += 1
    if not cheques:
        ws.cell(row=row, column=1, value=f'No cheques. ({cheques_note})').font = Font(italic=True)

    # ── Received, not in Tally ──
    ws = wb.create_sheet('Received, not in Tally')
    row = _title(ws, ['Payments logged in the app, not yet posted in Tally', subtitle])
    _header(ws, row, ['Date', 'Dealer', 'Mode', 'Amount', 'Reference', 'Note', 'Logged by'],
            [11, 34, 8, 14, 18, 30, 24])
    row += 1
    for p in sorted(open_pays, key=lambda p: (p['payment_date'], p['id'])):
        d = by_id.get(p['dealer_id'])
        vals = [p['payment_date'], f"{d['dealer_name']} ({d['town']})" if d and d.get('town') else p['dealer_id'],
                p['mode'], _f(p['amount']), p.get('reference') or '', p.get('note') or '', p.get('created_by') or '']
        for col, v in enumerate(vals, start=1):
            ws.cell(row=row, column=col, value=v)
        ws.cell(row=row, column=1).number_format = DATE
        ws.cell(row=row, column=4).number_format = MONEY
        row += 1
    if not open_pays:
        ws.cell(row=row, column=1, value='None.').font = Font(italic=True)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
