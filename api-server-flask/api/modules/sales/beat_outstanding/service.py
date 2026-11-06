# -*- encoding: utf-8 -*-
"""sales.beat_outstanding service — loads the uploads and builds each executive's
outstanding for a day, on screen and as an Excel file to hand to them.

Parsing lives in parser.py and the rules in rules.py; this file is the database half of
both, plus the Excel writer.
"""

import io
import re
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal

from api.shared.db_manager import mysql_manager
from api.modules.sales.beat_outstanding import parser as P
from api.modules.sales.beat_outstanding import rules as R


class BeatOutstandingError(Exception):
    pass


def ebco_company_id():
    """Beat Outstanding is Ebco only — same company lookup PO Builder and TAT Check use."""
    from api.modules.procurement.po_builder import service as pob
    try:
        return pob.ebco_company_id()
    except pob.PoBuilderError as e:
        raise BeatOutstandingError(str(e))


def today_ist():
    """Today in India — the server clock is UTC, and an executive's day is IST."""
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()


# table key (from the parser) -> (table, columns)
_TABLES = {
    'outlets': ('bo_outlet', ['outlet_id', 'outlet_name', 'name_key', 'beat_id', 'beat_name',
                              'city', 'distributor']),
    'beat_plan': ('bo_beat_plan', ['user_id', 'se_name', 'plan_date', 'beat_id', 'beat_name',
                                   'total_outlets']),
    'bills': ('bo_bill', ['distributor', 'party_name', 'name_key', 'bill_date', 'ref_no',
                          'amount', 'due_on']),
}

_FEED_TABLE = {
    P.FEED_OUTLETS: 'outlets',
    P.FEED_BEAT_PLAN: 'beat_plan',
    P.FEED_OUTSTANDING: 'bills',
}


# ── uploads ──────────────────────────────────────────────────────────────────

def ingest(feed, stream, filename, company_id, user):
    """Parse and load one upload in one transaction — a failure part-way leaves the
    previous upload in place, never half of this one. The DMS feeds replace all their
    rows; an outstanding report replaces only its own distributor's bills."""
    tables, warnings, meta = P.parse(feed, stream, filename)
    key = _FEED_TABLE[feed]
    table, cols = _TABLES[key]
    rows = tables[key]
    distributor = (meta.get('distributor') or '')[:255]
    with mysql_manager.get_cursor() as cur:
        cur.execute(
            """INSERT INTO bo_upload_log (company_id, feed, distributor, report_to, filename,
                                          row_count, uploaded_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (company_id, feed, distributor, meta.get('report_to'), (filename or '')[:255],
             len(rows), (user or 'system')[:100]))
        upload_id = cur.lastrowid
        if feed == P.FEED_OUTSTANDING:
            cur.execute('DELETE FROM bo_bill WHERE company_id = %s AND distributor = %s',
                        (company_id, distributor))
            rows = [{**r, 'distributor': distributor} for r in rows]
        else:
            cur.execute(f'DELETE FROM {table} WHERE company_id = %s', (company_id,))
        all_cols = ['company_id', 'upload_id'] + cols
        cur.executemany(
            f'INSERT INTO {table} ({", ".join(all_cols)}) '
            f'VALUES ({", ".join(["%s"] * len(all_cols))})',
            [(company_id, upload_id, *[r[c] for c in cols]) for r in rows])
    out = {'feed': feed, 'label': P.FEED_LABELS[feed], 'filename': filename,
           'counts': {key: len(rows)}, 'warnings': warnings[:50],
           'warning_count': len(warnings)}
    if feed == P.FEED_OUTSTANDING:
        out.update(distributor=distributor, report_to=_iso(meta.get('report_to')),
                   total=meta.get('total'))
    return out


def feed_status(company_id):
    """Last upload per feed — and per distributor for outstanding reports."""
    out = []
    for feed in (P.FEED_OUTLETS, P.FEED_BEAT_PLAN):
        last = mysql_manager.execute_query(
            """SELECT filename, row_count, uploaded_by, uploaded_on FROM bo_upload_log
               WHERE company_id = %s AND feed = %s ORDER BY id DESC LIMIT 1""",
            (company_id, feed))
        out.append({'feed': feed, 'label': P.FEED_LABELS[feed],
                    'last_upload': _upload_out(last[0]) if last else None})
    reports = mysql_manager.execute_query(
        """SELECT l.distributor, l.report_to, l.filename, l.row_count, l.uploaded_by,
                  l.uploaded_on
           FROM bo_upload_log l
           JOIN (SELECT distributor, MAX(id) AS id FROM bo_upload_log
                 WHERE company_id = %s AND feed = %s GROUP BY distributor) m ON m.id = l.id
           ORDER BY l.distributor""",
        (company_id, P.FEED_OUTSTANDING)) or []
    if not reports:
        out.append({'feed': P.FEED_OUTSTANDING, 'label': P.FEED_LABELS[P.FEED_OUTSTANDING],
                    'last_upload': None})
    for r in reports:
        out.append({'feed': P.FEED_OUTSTANDING,
                    'label': f"{P.FEED_LABELS[P.FEED_OUTSTANDING]} — {r['distributor']}",
                    'distributor': r['distributor'], 'report_to': _iso(r['report_to']),
                    'last_upload': _upload_out(r)})
    return out


# ── report ───────────────────────────────────────────────────────────────────

def _load(company_id):
    outlets = mysql_manager.execute_query(
        'SELECT outlet_name, name_key, beat_id, beat_name, city FROM bo_outlet '
        'WHERE company_id = %s', (company_id,)) or []
    bills = mysql_manager.execute_query(
        'SELECT distributor, party_name, name_key, bill_date, ref_no, amount, due_on '
        'FROM bo_bill WHERE company_id = %s ORDER BY id', (company_id,)) or []
    return outlets, bills


def plan_dates(company_id):
    rows = mysql_manager.execute_query(
        'SELECT DISTINCT plan_date FROM bo_beat_plan WHERE company_id = %s '
        'ORDER BY plan_date DESC', (company_id,)) or []
    return [r['plan_date'] for r in rows]


def _pick_date(dates, wanted, today):
    """The plan date asked for, else today — even when today's plan is not uploaded yet,
    so a stale day is never shown as if it were today (report() flags it instead)."""
    if wanted and wanted != today and wanted not in dates:
        raise BeatOutstandingError(f'The beat plan has no beats for {wanted:%d %b %Y}.')
    return wanted or today


def report(company_id, wanted_date=None, today=None):
    """Every executive on the beat plan for the date, with the outstanding of the dealers
    on their beats; the parties that could not be placed on a beat; and the placed
    dealers whose beat nobody covers that day."""
    today = today or today_ist()
    dates = plan_dates(company_id)
    plan_date = _pick_date(dates, wanted_date, today)
    outlets, bills = _load(company_id)
    placed, unplaced = R.place_parties(bills, outlets)

    plan = mysql_manager.execute_query(
        'SELECT user_id, se_name, beat_id, beat_name FROM bo_beat_plan '
        'WHERE company_id = %s AND plan_date = %s ORDER BY id',
        (company_id, plan_date)) or []

    executives, covered = [], set()
    for e in R.executives_on(plan):
        dealers = R.dealers_on([b['beat_id'] for b in e['beats']], bills, placed, today)
        covered.update(b['beat_id'] for b in e['beats'])
        for b in e['beats']:
            mine = [d for d in dealers if d['beat_id'] == b['beat_id']]
            b.update(dealer_count=len(mine), amount=round(sum(d['amount'] for d in mine), 2))
        executives.append({**e, **_totals(dealers), 'dealers': dealers})

    off_plan = {}
    for d in R.dealers_on({p['beat_id'] for p in placed.values()} - covered, bills, placed, today):
        b = off_plan.setdefault(d['beat_id'], {'beat_id': d['beat_id'], 'beat_name': d['beat_name'],
                                               'dealer_count': 0, 'amount': 0.0})
        b['dealer_count'] += 1
        b['amount'] = round(b['amount'] + d['amount'], 2)

    feeds = feed_status(company_id)
    return _jsonable({
        'as_of': today,
        'plan_date': plan_date,
        'today': today,
        # The day asked for (today, by default) has no beat plan uploaded.
        'plan_missing': plan_date not in dates,
        'plan_dates': dates,
        'feeds': feeds,
        'reports': [f for f in feeds if f['feed'] == P.FEED_OUTSTANDING and f['last_upload']],
        'total_outstanding': round(sum(float(b['amount']) for b in bills), 2),
        'executives': executives,
        'unplaced': unplaced,
        'off_plan': sorted(off_plan.values(), key=lambda b: -b['amount']),
    })


def _totals(dealers):
    owed = [d['max_days_overdue'] for d in dealers if d['max_days_overdue'] is not None]
    return {'dealer_count': len(dealers),
            'bill_count': sum(d['bill_count'] for d in dealers),
            'amount': round(sum(d['amount'] for d in dealers), 2),
            'max_days_overdue': max(owed) if owed else None}


# ── Excel ────────────────────────────────────────────────────────────────────

def export_one(company_id, wanted_date, user_id, se_name):
    """(filename, xlsx bytes) for one executive's outstanding on the date."""
    rep = report(company_id, wanted_date)
    _require_plan(rep)
    e = next((x for x in rep['executives']
              if x['user_id'] == (user_id or '') and x['se_name'] == se_name), None)
    if not e:
        raise BeatOutstandingError(f'{se_name} is not on the beat plan for that day.')
    if not e['dealers']:
        raise BeatOutstandingError(f'No outstanding on {se_name}\'s beats that day.')
    return _filename(e, rep['plan_date'], 'xlsx'), _workbook_for(e, rep)


def export_all(company_id, wanted_date):
    """(filename, zip bytes) with one workbook per executive who has outstanding that day."""
    rep = report(company_id, wanted_date)
    _require_plan(rep)
    execs = [e for e in rep['executives'] if e['dealers']]
    if not execs:
        raise BeatOutstandingError('No executive has outstanding on their beats that day.')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for e in execs:
            z.writestr(_filename(e, rep['plan_date'], 'xlsx'), _workbook_for(e, rep))
    return f"Beat_Outstanding_{rep['plan_date']}.zip", buf.getvalue()


def _require_plan(rep):
    if rep['plan_missing']:
        raise BeatOutstandingError(f"No beat plan uploaded for {_fmt(rep['plan_date'])}.")


def _filename(e, plan_date, ext):
    who = re.sub(r'[^A-Za-z0-9]+', '_', e['se_name']).strip('_') or 'executive'
    return f'Outstanding_{who}_{plan_date}.{ext}'


def _fmt(d):
    return datetime.strptime(d, '%Y-%m-%d').strftime('%d %b %Y') if d else ''


def _workbook_for(e, rep):
    """One sheet: a header saying whose beats and as of when, then each dealer — worst
    first — with its bills and a dealer total, then the executive's grand total."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = 'Outstanding'
    bold = Font(bold=True)
    plan = datetime.strptime(rep['plan_date'], '%Y-%m-%d')

    ws.append([f"Outstanding — {e['se_name']}"])
    ws['A1'].font = Font(bold=True, size=14)
    ws.append([f"Beats on {plan:%A, %d %b %Y}: " + ', '.join(b['beat_name'] for b in e['beats'])])
    reports = '; '.join(f"{r['distributor']} up to {_fmt(r['report_to'])}"
                        for r in rep['reports'] if r.get('report_to')) or '—'
    ws.append([f"Tally report: {reports}. Days overdue as of {_fmt(rep['as_of'])}."])
    ws.append([])

    header = ['Dealer', 'Beat', 'City', 'Bill date', 'Bill no.', 'Due on', 'Days overdue', 'Amount (₹)']
    ws.append(header)
    head_row = ws.max_row
    for c in ws[head_row]:
        c.font = bold
        c.fill = PatternFill('solid', fgColor='E5E7EB')

    red = Font(color='B91C1C')
    for d in e['dealers']:
        for b in d['bills']:
            ws.append([d['party_name'], d['beat_name'], d['city'],
                       datetime.strptime(b['bill_date'], '%Y-%m-%d').date(), b['ref_no'],
                       datetime.strptime(b['due_on'], '%Y-%m-%d').date(),
                       b['days_overdue'], b['amount']])
            r = ws.max_row
            ws.cell(r, 4).number_format = ws.cell(r, 6).number_format = 'DD-MMM-YY'
            ws.cell(r, 8).number_format = '#,##0.00'
            if b['amount'] > 0 and b['days_overdue'] > 30:
                ws.cell(r, 7).font = red
        ws.append([f"{d['party_name']} — total", '', '', '', '', '', d['max_days_overdue'], d['amount']])
        r = ws.max_row
        for c in ws[r]:
            c.font = bold
        ws.cell(r, 8).number_format = '#,##0.00'

    ws.append([])
    ws.append([f"Total — {e['dealer_count']} dealers, {e['bill_count']} bills",
               '', '', '', '', '', '', e['amount']])
    r = ws.max_row
    for c in ws[r]:
        c.font = Font(bold=True, size=12)
    ws.cell(r, 8).number_format = '#,##0.00'

    for col, width in zip('ABCDEFGH', (38, 26, 16, 11, 18, 11, 13, 15)):
        ws.column_dimensions[col].width = width
    ws.cell(head_row, 7).alignment = ws.cell(head_row, 8).alignment = Alignment(horizontal='right')
    ws.freeze_panes = ws.cell(head_row + 1, 1)
    ws.print_options.gridLines = True
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── helpers ──────────────────────────────────────────────────────────────────

def _upload_out(row):
    """An upload record for the browser. `uploaded_on` is MySQL's CURRENT_TIMESTAMP,
    which is UTC, so it is sent marked as UTC ('Z') and the browser shows local time."""
    out = _jsonable(row)
    if isinstance(row.get('uploaded_on'), datetime):
        out['uploaded_on'] = row['uploaded_on'].isoformat() + 'Z'
    return out


def _iso(v):
    return v.isoformat() if isinstance(v, (datetime, date)) else v


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (Decimal, float)):
        f = float(v)
        return int(f) if f.is_integer() else f
    return v
