# -*- encoding: utf-8 -*-
"""sales.beat_outstanding service — loads the uploads and builds each executive's
outstanding for a day, on screen and as an Excel file to hand to them.

The Tally outstanding report is never stored: the page sends the file with every request
(read_outstanding), and the amounts exist only for that request. The DMS feeds — Outlet
Master and Beat Plan — are stored as uploads.

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
}

_FEED_TABLE = {
    P.FEED_OUTLETS: 'outlets',
    P.FEED_BEAT_PLAN: 'beat_plan',
}


# ── uploads ──────────────────────────────────────────────────────────────────

def ingest(feed, stream, filename, company_id, user):
    """Parse and load one upload in one transaction — a failure part-way leaves the
    previous upload in place, never half of this one. Each replaces all its rows. The
    Tally outstanding report is refused: it is never stored (see read_outstanding)."""
    if feed == P.FEED_OUTSTANDING:
        raise BeatOutstandingError('The Tally outstanding report is not stored — pick it on the '
                                   'Beat Outstanding page.')
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
        cur.execute(f'DELETE FROM {table} WHERE company_id = %s', (company_id,))
        all_cols = ['company_id', 'upload_id'] + cols
        cur.executemany(
            f'INSERT INTO {table} ({", ".join(all_cols)}) '
            f'VALUES ({", ".join(["%s"] * len(all_cols))})',
            [(company_id, upload_id, *[r[c] for c in cols]) for r in rows])
    out = {'feed': feed, 'label': P.FEED_LABELS[feed], 'filename': filename,
           'counts': {key: len(rows)}, 'warnings': warnings[:50],
           'warning_count': len(warnings)}
    return out


def feed_status(company_id):
    """Last upload of each stored feed (the outstanding report is never stored)."""
    out = []
    for feed in (P.FEED_OUTLETS, P.FEED_BEAT_PLAN):
        last = mysql_manager.execute_query(
            """SELECT filename, row_count, uploaded_by, uploaded_on FROM bo_upload_log
               WHERE company_id = %s AND feed = %s ORDER BY id DESC LIMIT 1""",
            (company_id, feed))
        out.append({'feed': feed, 'label': P.FEED_LABELS[feed],
                    'last_upload': _upload_out(last[0]) if last else None})
    return out


# ── executive beats (kept on the page) ───────────────────────────────────────

def exec_beats(company_id):
    return [_jsonable(r) for r in mysql_manager.execute_query(
        'SELECT se_name, beat_name FROM bo_exec_beat WHERE company_id = %s '
        'ORDER BY se_name, id', (company_id,)) or []]


def executive_names(company_id):
    rows = mysql_manager.execute_query(
        'SELECT DISTINCT se_name FROM bo_beat_plan WHERE company_id = %s '
        'UNION SELECT DISTINCT se_name FROM bo_exec_beat WHERE company_id = %s',
        (company_id, company_id)) or []
    return sorted({r['se_name'] for r in rows if r['se_name']}, key=str.casefold)


def exec_beats_page(company_id):
    """What the Executive Beats page shows and offers as it is typed."""
    outlets = mysql_manager.execute_query(
        "SELECT DISTINCT beat_name FROM bo_outlet WHERE company_id = %s AND beat_name <> ''",
        (company_id,)) or []
    return {'exec_beats': exec_beats(company_id), 'cd_days': R.CD_DAYS,
            'executive_names': executive_names(company_id),
            'beat_names': sorted({o['beat_name'] for o in outlets}, key=str.casefold)}


def set_day_beats(company_id, se_name, beat_names, today=None):
    """Set by hand the beats `se_name` covers today — for a day with no beat plan file, or
    to change it. Replaces that executive's beats for today only; a beat plan uploaded
    later replaces the whole plan, these included."""
    today = today or today_ist()
    mapping = exec_beats(company_id)
    mapped_name = next((m['se_name'] for m in mapping if R.name_match(m['se_name']) == R.name_match(se_name)), None)
    if not mapped_name:
        raise BeatOutstandingError(f'{se_name} is not in Executive Beats.')
    outlets = _load(company_id)
    by_name = {}
    for o in outlets:
        if o['beat_id']:
            by_name.setdefault(R.name_match(o['beat_name']), (o['beat_id'], o['beat_name']))
    beats, unknown = [], []
    for n in beat_names or []:
        hit = by_name.get(R.name_match(n))
        if not hit:
            unknown.append(n)
        elif hit not in beats:
            beats.append(hit)
    if unknown:
        raise BeatOutstandingError('Not a beat in the Outlet Master: ' + ', '.join(unknown))
    rows = mysql_manager.execute_query(
        'SELECT se_name, user_id FROM bo_beat_plan WHERE company_id = %s AND user_id <> %s '
        'ORDER BY plan_date DESC', (company_id, '')) or []
    user_id = next((r['user_id'] for r in rows if R.name_match(r['se_name']) == R.name_match(se_name)), '')
    on_day = mysql_manager.execute_query(
        'SELECT id, se_name FROM bo_beat_plan WHERE company_id = %s AND plan_date = %s',
        (company_id, today)) or []
    drop = [r['id'] for r in on_day if R.name_match(r['se_name']) == R.name_match(se_name)]
    # the name the day's plan already uses for them, else Executive Beats'
    name = next((r['se_name'] for r in on_day if r['id'] in drop), mapped_name)
    with mysql_manager.get_cursor() as cur:
        if drop:
            cur.execute(f'DELETE FROM bo_beat_plan WHERE id IN ({", ".join(["%s"] * len(drop))})', drop)
        # upload_id 0: set on the page, not from a file
        cur.executemany(
            'INSERT INTO bo_beat_plan (company_id, upload_id, user_id, se_name, plan_date, beat_id, '
            'beat_name, total_outlets) VALUES (%s, 0, %s, %s, %s, %s, %s, 0)',
            [(company_id, user_id, name, today, bid, bname) for bid, bname in beats])
    return {'se_name': name, 'beats': [b for _, b in beats]}


def save_exec_beats(company_id, rows, user):
    """Replace the whole executive → beat table with `rows` ([{se_name, beat_name}]),
    in one transaction. Blank rows are dropped and repeats kept once. Beats not in the
    Outlet Master are saved but warned about — no dealer can be found on them."""
    clean, seen = [], set()
    for i, r in enumerate(rows or [], 1):
        se = ' '.join(str(r.get('se_name') or '').split())[:255]
        beat = ' '.join(str(r.get('beat_name') or '').split())[:255]
        if not se and not beat:
            continue
        if not se or not beat:
            raise BeatOutstandingError(f'Row {i}: give both the user and the beat.')
        key = (R.name_match(se), R.name_match(beat))
        if key not in seen:
            seen.add(key)
            clean.append((se, beat))
    with mysql_manager.get_cursor() as cur:
        cur.execute('DELETE FROM bo_exec_beat WHERE company_id = %s', (company_id,))
        cur.executemany(
            'INSERT INTO bo_exec_beat (company_id, se_name, beat_name, updated_by) '
            'VALUES (%s, %s, %s, %s)',
            [(company_id, se, beat, (user or 'system')[:100]) for se, beat in clean])
    known = {R.name_match(r['beat_name']) for r in mysql_manager.execute_query(
        'SELECT DISTINCT beat_name FROM bo_outlet WHERE company_id = %s', (company_id,)) or []}
    unknown = sorted({beat for _, beat in clean if R.name_match(beat) not in known})
    return {'saved': len(clean), 'exec_beats': exec_beats(company_id),
            'warnings': [f'{b}: not a beat in the Outlet Master — no dealers will be found on it'
                         for b in unknown]}


# ── report ───────────────────────────────────────────────────────────────────

def _load(company_id):
    return mysql_manager.execute_query(
        'SELECT outlet_name, name_key, beat_id, beat_name, city FROM bo_outlet '
        'WHERE company_id = %s', (company_id,)) or []


def read_outstanding(stream, filename):
    """The Tally outstanding report sent with a request, parsed — held only for that
    request, never stored. {'bills', 'distributor', 'report_to', 'filename', 'total',
    'bill_count', 'warnings'}."""
    tables, warnings, meta = P.parse(P.FEED_OUTSTANDING, stream, filename)
    distributor = meta.get('distributor') or ''
    bills = [{**b, 'distributor': distributor} for b in tables['bills']]
    return {'bills': bills, 'distributor': distributor, 'report_to': meta.get('report_to'),
            'filename': filename or '', 'total': round(sum(b['amount'] for b in bills), 2),
            'bill_count': len(bills), 'warnings': warnings[:50]}


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


def report(company_id, wanted_date=None, today=None, outstanding=None):
    """Every executive in Executive Beats — with the beats the beat plan (uploaded, or
    set by hand with set_day_beats) gives them for the date, none if it gives none — and
    the outstanding of the dealers on those beats; the parties that could not be placed
    on a beat; and every dealer no executive covers (`other`)."""
    today = today or today_ist()
    dates = plan_dates(company_id)
    plan_date = _pick_date(dates, wanted_date, today)
    outlets = _load(company_id)
    # No report picked: no bills, so no amounts anywhere.
    bills = outstanding['bills'] if outstanding else []
    placed, unplaced = R.place_parties(bills, outlets)

    plan = mysql_manager.execute_query(
        'SELECT user_id, se_name, beat_id, beat_name FROM bo_beat_plan '
        'WHERE company_id = %s AND plan_date = %s ORDER BY id',
        (company_id, plan_date)) or []

    mapping = exec_beats(company_id)
    users = {R.name_match(m['se_name']) for m in mapping}
    # Only the users kept in Executive Beats are shown and get a file: those on the plan,
    # in its order, then the rest with no beats yet (their beats can be added by hand).
    on_plan = [e for e in R.executives_on(plan) if R.name_match(e['se_name']) in users]
    seen = {R.name_match(e['se_name']) for e in on_plan}
    for m in mapping:
        if R.name_match(m['se_name']) not in seen:
            seen.add(R.name_match(m['se_name']))
            on_plan.append({'user_id': '', 'se_name': m['se_name'], 'beats': []})
    executives = []
    for e in on_plan:
        dealers = R.dealers_on([b['beat_id'] for b in e['beats']], bills, placed, today)
        for b in e['beats']:
            mine = [d for d in dealers if d['beat_id'] == b['beat_id']]
            b.update(dealer_count=len(mine), amount=round(sum(d['amount'] for d in mine), 2))
        mapped = [m['beat_name'] for m in mapping if R.name_match(m['se_name']) == R.name_match(e['se_name'])]
        cd = R.cd_lapsed(R.dealers_on(R.beat_ids_named(mapped, outlets), bills, placed, today), today)
        executives.append({**e, **_totals(dealers), 'dealers': dealers, 'mapped_beats': mapped,
                           'cd_dealers': cd, 'cd_amount': round(sum(d['amount'] for d in cd), 2)})

    owned = R.beat_ids_named([m['beat_name'] for m in mapping], outlets)
    unassigned = R.unassigned_dealers(bills, placed, unplaced, owned, today)
    other_cd = R.cd_lapsed(unassigned, today)

    feeds = feed_status(company_id)
    return _jsonable({
        'as_of': today,
        'plan_date': plan_date,
        'today': today,
        # The day asked for (today, by default) has no beat plan uploaded.
        'plan_missing': plan_date not in dates,
        'plan_dates': dates,
        'feeds': feeds,
        # the Tally report this request carried (its bills are not sent back), or None
        'outstanding': ({k: v for k, v in outstanding.items() if k != 'bills'}
                        if outstanding else None),
        'total_outstanding': round(sum(float(b['amount']) for b in bills), 2),
        'executives': executives,
        'cd_days': R.CD_DAYS,
        'exec_beats': mapping,
        # what the mapping table offers as it is typed
        'beat_names': sorted({o['beat_name'] for o in outlets if o['beat_name']}, key=str.casefold),
        'executive_names': executive_names(company_id),
        'unplaced': unplaced,
        # 'Other': every dealer no executive covers, as one more row of the table
        'other': {'dealers': unassigned, 'dealer_count': len(unassigned),
                  'amount': round(sum(d['amount'] for d in unassigned), 2),
                  'cd_dealers': other_cd, 'cd_amount': round(sum(d['amount'] for d in other_cd), 2)},
    })


def _totals(dealers):
    owed = [d['max_days_overdue'] for d in dealers if d['max_days_overdue'] is not None]
    return {'dealer_count': len(dealers),
            'bill_count': sum(d['bill_count'] for d in dealers),
            'amount': round(sum(d['amount'] for d in dealers), 2),
            'max_days_overdue': max(owed) if owed else None}


# ── Excel ────────────────────────────────────────────────────────────────────

def export_one(company_id, wanted_date, user_id, se_name, outstanding):
    """(filename, xlsx bytes) for one executive's outstanding on the date, from the Tally
    report sent with the request."""
    _require_outstanding(outstanding)
    rep = report(company_id, wanted_date, outstanding=outstanding)
    e = next((x for x in rep['executives']
              if x['user_id'] == (user_id or '') and x['se_name'] == se_name), None)
    if not e:
        raise BeatOutstandingError(f'{se_name} is not in Executive Beats.')
    if not e['dealers'] and not e['cd_dealers']:
        raise BeatOutstandingError(f'No outstanding on {se_name}\'s beats that day.')
    return _filename(e, rep['plan_date'], 'xlsx'), _workbook_for(e, rep)


def export_all(company_id, wanted_date, outstanding):
    """(filename, zip bytes) with one workbook per executive who has outstanding that day,
    plus the Other row's workbook when there are any, from the Tally report sent."""
    _require_outstanding(outstanding)
    rep = report(company_id, wanted_date, outstanding=outstanding)
    execs = [e for e in rep['executives'] if e['dealers'] or e['cd_dealers']]
    if not execs and not rep['other']['dealers']:
        raise BeatOutstandingError('No executive has outstanding on their beats that day.')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        # Two executives with one first name would overwrite each other: they get their
        # full names instead.
        firsts = [_first_name(e['se_name']) for e in execs]
        for e in execs:
            full = firsts.count(_first_name(e['se_name'])) > 1
            z.writestr(_filename(e, rep['plan_date'], 'xlsx', full_name=full), _workbook_for(e, rep))
        if rep['other']['dealers']:
            z.writestr(_unassigned_filename(rep), _unassigned_workbook(rep))
    return f"{_file_date(rep['plan_date'])}_outstanding.zip", buf.getvalue()


def export_unassigned(company_id, outstanding):
    """(filename, xlsx bytes): the 'Other' row — every dealer with outstanding that no
    executive covers, from the Tally report sent."""
    _require_outstanding(outstanding)
    rep = report(company_id, outstanding=outstanding)
    if not rep['other']['dealers']:
        raise BeatOutstandingError('Every dealer with outstanding is on an executive\'s beats.')
    return _unassigned_filename(rep), _unassigned_workbook(rep)


def _unassigned_filename(rep):
    return f"Other_{_file_date(rep['as_of'])}_outstanding.xlsx"


def _require_outstanding(outstanding):
    if not outstanding:
        raise BeatOutstandingError('Pick the Tally outstanding report first.')


def _first_name(se_name):
    return (se_name or '').split()[0] if (se_name or '').split() else ''


def _file_date(d):
    """'2026-11-14' -> '14-11-2026', the date in a download's name."""
    return datetime.strptime(d, '%Y-%m-%d').strftime('%d-%m-%Y')


def _filename(e, plan_date, ext, full_name=False):
    """'<first name>_<dd-mm-yyyy>_outstanding.xlsx', e.g. Nitesh_14-11-2026_outstanding.xlsx."""
    name = e['se_name'] if full_name else _first_name(e['se_name'])
    who = re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_') or 'executive'
    return f'{who}_{_file_date(plan_date)}_outstanding.{ext}'


def _fmt(d):
    return datetime.strptime(d, '%Y-%m-%d').strftime('%d %b %Y') if d else ''


def _tally_date(d):
    dt = datetime.strptime(d, '%Y-%m-%d') if isinstance(d, str) else d
    return f'{dt.day}-{dt:%b-%y}'


def _period(rep):
    """Tally's period line, '1-Apr-26 to 6-Nov-26': from the start of the financial year
    to the report's date (today when the report carries none)."""
    o = rep['outstanding'] or {}
    end = datetime.strptime(o.get('report_to') or rep['as_of'], '%Y-%m-%d').date()
    start = date(end.year if end.month >= 4 else end.year - 1, 4, 1)
    return f'{_tally_date(start)} to {_tally_date(end)}'


def _sheet_name(name, taken):
    name = re.sub(r'[\[\]:*?/\\]', ' ', name).strip()[:31] or 'Bills Receivable'
    return name if name not in taken else f'{name[:28]} 1'


def _workbook_for(e, rep):
    """Two sheets, both laid out like Tally's group Bills Receivable report (Group : … /
    Details of: Pending Bills, Opening and Pending amounts): the day's outstanding on the
    executive's beats that day, and the bills past the cash-discount period on all the
    beats mapped to them. Party names are exactly as Tally prints them."""
    from openpyxl import Workbook

    wb = Workbook()
    plan = datetime.strptime(rep['plan_date'], '%Y-%m-%d')
    group = (rep['outstanding'] or {}).get('distributor') or 'Bills Receivable'
    first = wb.active
    first.title = _sheet_name(group, set())
    _tally_sheet(
        first, group, _period(rep), e['dealers'],
        f"{e['se_name']} · {plan:%A, %d %b %Y} · " + ', '.join(b['beat_name'] for b in e['beats'])
        + f" · overdue days as on {_tally_date(rep['as_of'])}",
        ('Overdue', 'by days'), 'days_overdue', red_over=30,
        empty="No outstanding on this day's beats.")

    cd_days = rep['cd_days']
    if e['mapped_beats']:
        who = (f"{e['se_name']} · bills {cd_days} days or more old (cash discount lapsed) · all beats: "
               + ', '.join(e['mapped_beats']))
        empty = f'No unpaid bills {cd_days} days or more old on these beats.'
    else:
        who = f"{e['se_name']} · no beats mapped"
        empty = 'No beats are mapped to this executive — add them under Beat Outstanding → Executive Beats.'
    _tally_sheet(
        wb.create_sheet(_sheet_name(f'CD {cd_days}+ days', {first.title})), group, _period(rep),
        e['cd_dealers'], who, ('Days since', 'bill'), 'days_since_bill', empty=empty)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _unassigned_workbook(rep):
    """The 'Other' row's file: the dealers no executive covers, as an executive's file —
    all their outstanding, then their bills past the cash-discount period — in the same
    Tally layout. Beside each party, why no executive has it (its beat is in nobody's
    Executive Beats, or it is not on a beat at all)."""
    from openpyxl import Workbook

    wb = Workbook()
    group = (rep['outstanding'] or {}).get('distributor') or 'Bills Receivable'
    other, cd_days = rep['other'], rep['cd_days']
    ws = wb.active
    ws.title = _sheet_name(group, set())
    _tally_sheet(
        ws, group, _period(rep), other['dealers'],
        f"Other — dealers not on any executive's beats · overdue days as on {_tally_date(rep['as_of'])}",
        ('Overdue', 'by days'), 'days_overdue', red_over=30)
    _tally_sheet(
        wb.create_sheet(_sheet_name(f'CD {cd_days}+ days', {ws.title})), group, _period(rep),
        other['cd_dealers'],
        f"Other · bills {cd_days} days or more old (cash discount lapsed)",
        ('Days since', 'bill'), 'days_since_bill',
        empty=f'No unpaid bills {cd_days} days or more old.')
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _tally_sheet(ws, group, period, dealers, who_line, days_head, days_key, red_over=None, empty=''):
    """One sheet in Tally's group Bills Receivable layout: the Group / Details of heading,
    a line saying whose list this is (the row Tally leaves blank), the two-row column
    header, each party (A to Z) with its bills and a party total, then the grand total.
    Amounts are shown as Tally does — the figure with Dr, or Cr for a credit. The last
    column is `days_key` of each bill, headed `days_head`, blank when not yet due."""
    from openpyxl.styles import Alignment, Border, Font, Side

    bold, plain = Font(bold=True), Font()
    right, left = Alignment(horizontal='right'), Alignment(horizontal='left')
    thin = Side(style='thin')

    ws.append(['Group :', group, None, period])
    ws.merge_cells('B1:C1')
    ws.merge_cells('D1:G1')
    ws['B1'].font = ws['D1'].font = bold
    ws['D1'].alignment = right
    ws.append(['Details of:', 'Pending Bills'])
    ws.merge_cells('B2:C2')
    ws['B2'].font = bold
    ws.append([who_line])
    ws.merge_cells('A3:G3')

    ws.append(['Date', 'Ref. No.', "Party's Name", 'Opening', 'Pending', 'Due on', days_head[0]])
    ws.append(['', '', '', 'Amount', 'Amount', '', days_head[1]])
    head = ws.max_row - 1
    for r in (head, head + 1):
        for col in range(1, 8):
            c = ws.cell(r, col)
            c.font = bold if col in (1, 5) else plain
            c.alignment = left if col in (2, 3) else right
            c.border = Border(top=thin) if r == head else Border(bottom=thin)

    def amount(c, v, is_bold=False):
        c.value = abs(v)
        c.number_format = '0.00" Cr"' if v < 0 else '0.00" Dr"'
        c.alignment = right
        c.font = bold if is_bold else plain

    red = Font(color='B91C1C')
    note = Font(italic=True, color='7A869A')
    for d in sorted(dealers, key=lambda x: x['party_name'].lower()):
        ws.append(['', '', d['party_name']])
        ws.cell(ws.max_row, 3).font = bold
        if d.get('reason'):
            # unassigned dealers only: why no executive has this party
            c = ws.cell(ws.max_row, 4, d['reason'] + (f" ({d['beat_name']})" if d.get('beat_name') else ''))
            c.font = note
        for b in d['bills']:
            days = b[days_key]
            ws.append([datetime.strptime(b['bill_date'], '%Y-%m-%d').date(), b['ref_no'], '', None, None,
                       datetime.strptime(b['due_on'], '%Y-%m-%d').date(), days if days and days > 0 else ''])
            r = ws.max_row
            ws.cell(r, 1).font = bold
            ws.cell(r, 1).number_format = ws.cell(r, 6).number_format = 'dd-mmm-yy'
            for col in (1, 6, 7):
                ws.cell(r, col).alignment = right
            ws.cell(r, 2).alignment = left
            amount(ws.cell(r, 4), b['opening'])
            amount(ws.cell(r, 5), b['amount'], is_bold=bool(days and days > 0))
            if red_over is not None and b['amount'] > 0 and days and days > red_over:
                ws.cell(r, 7).font = red
        r = ws.max_row + 1  # the party total; ws.append([]) would not create the row
        amount(ws.cell(r, 4), round(sum(b['opening'] for b in d['bills']), 2))
        amount(ws.cell(r, 5), round(sum(b['amount'] for b in d['bills']), 2), is_bold=True)
        ws.cell(r, 4).border = ws.cell(r, 5).border = Border(top=thin, bottom=thin)

    if dealers:
        r = ws.max_row + 1
        amount(ws.cell(r, 4), round(sum(b['opening'] for d in dealers for b in d['bills']), 2))
        amount(ws.cell(r, 5), round(sum(d['amount'] for d in dealers), 2), is_bold=True)
        for col in range(2, 8):
            ws.cell(r, col).border = Border(top=thin, bottom=thin)
    else:
        ws.append(['', '', empty])

    for col, width in zip('ABCDEFG', (9.8, 20.3, 52.4, 13.2, 13.3, 9.7, 8.7)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = ws.cell(head + 2, 1)
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0


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
