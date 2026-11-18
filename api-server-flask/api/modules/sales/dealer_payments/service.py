# -*- encoding: utf-8 -*-
"""Dealer Payment Tracker — storage and processing (Cadila/dealer_payment_tracker_spec.md).

Every call acts on the Cadila company, which the server works out itself. The rules live
in rules.py and the file parsing in parser.py; this module reads and writes the dpt_*
tables and runs the processing after every change:

  run_processing   3.1 bounces -> 3.2 matching -> 3.3 manual-check flags

Flags never change a balance. Balances come only from Tally's own files and the payment
log.
"""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from api.shared.db_manager import mysql_manager
from api.core.logging import get_logger
from api.modules.sales.dealer_payments import cheques as C
from api.modules.sales.dealer_payments import parser as P
from api.modules.sales.dealer_payments import rules as R

logger = get_logger(__name__)

KIND_OUTSTANDING, KIND_RECEIPTS = 'outstanding', 'receipts'
FEEDS = (KIND_OUTSTANDING, KIND_RECEIPTS)
MAX_FILE_BYTES = 10 * 1024 * 1024


class DealerPaymentsError(ValueError):
    """A request the module refuses, with a message for the person who made it."""


def cadila_company_id():
    """The Cadila company: the one whose name starts with "Cadila"; on a database holding a
    single company, that one. Never chosen by the request."""
    rows = mysql_manager.execute_query(
        "SELECT company_id FROM company WHERE LOWER(TRIM(name)) LIKE %s ORDER BY company_id",
        ('cadila%',)) or []
    if len(rows) == 1:
        return rows[0]['company_id']
    if not rows:
        only = mysql_manager.execute_query('SELECT company_id FROM company') or []
        if len(only) == 1:
            return only[0]['company_id']
    raise DealerPaymentsError('Could not identify the Cadila company (expected exactly one company '
                              'named "Cadila…"). Ask an admin to check the company list.')


def today_ist():
    """Today in India — the server clock is UTC."""
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()


def fy_start(day):
    """1 April of the financial year `day` falls in."""
    return date(day.year if day.month >= 4 else day.year - 1, 4, 1)


# ── reads ─────────────────────────────────────────────────────────────────────

def dealers(company_id):
    rows = mysql_manager.execute_query(
        """SELECT dealer_id, tally_ledger_name, dealer_name, principal, town, cheque_system_name,
                  phone, salesman, exclude_from_chase, active, first_txn_date, source, is_new
           FROM dpt_dealer WHERE company_id = %s ORDER BY dealer_id""", (company_id,)) or []
    for r in rows:
        for k in ('exclude_from_chase', 'active', 'is_new'):
            r[k] = bool(r[k])
    return rows


def latest_as_of(company_id):
    row = mysql_manager.execute_query(
        'SELECT MAX(as_of_date) AS d FROM dpt_outstanding WHERE company_id = %s', (company_id,))
    return row[0]['d'] if row else None


def snapshot(company_id, as_of, today=None):
    """The Export 1 bills of `as_of`, in the shape rules.py takes. With `today`, each bill's
    overdue days are counted to today rather than to the export date."""
    if as_of is None:
        return []
    rows = mysql_manager.execute_query(
        """SELECT dealer_id, ref_no, kind, bill_date, opening_amt, pending_amt_signed AS pending_amt,
                  due_on, overdue_days FROM dpt_outstanding
           WHERE company_id = %s AND as_of_date = %s ORDER BY dealer_id, bill_date, ref_no""",
        (company_id, as_of)) or []
    return R.age_bills(rows, today) if today else rows


def receipts(company_id):
    return mysql_manager.execute_query(
        """SELECT vch_no, vch_date, dealer_id, vch_type, amount FROM dpt_receipt
           WHERE company_id = %s ORDER BY vch_date, vch_no""", (company_id,)) or []


def payments(company_id, status=None, limit=None):
    sql = """SELECT p.id, p.dealer_id, d.dealer_name, d.town, p.mode, p.amount, p.payment_date,
                    p.reference, p.note, p.status, p.matched_vch_no, p.matched_vch_date,
                    p.bounced_by_ref, (p.proof_path IS NOT NULL) AS has_proof, p.created_by,
                    p.created_on, p.updated_by, p.updated_on
             FROM dpt_payment p
             LEFT JOIN dpt_dealer d ON d.company_id = p.company_id AND d.dealer_id = p.dealer_id
             WHERE p.company_id = %s"""
    params = [company_id]
    if status:
        sql += ' AND p.status = %s'
        params.append(status)
    sql += ' ORDER BY p.payment_date DESC, p.id DESC'
    if limit:
        sql += ' LIMIT %s'
        params.append(int(limit))
    rows = mysql_manager.execute_query(sql, tuple(params)) or []
    for r in rows:
        r['has_proof'] = bool(r['has_proof'])
    return rows


def last_uploads(company_id):
    """The latest upload of each kind."""
    rows = mysql_manager.execute_query(
        """SELECT u.kind, u.filename, u.as_of, u.period_from, u.period_to, u.row_count, u.warnings,
                  u.uploaded_by, u.uploaded_on
           FROM dpt_upload u
           JOIN (SELECT kind, MAX(id) AS id FROM dpt_upload WHERE company_id = %s GROUP BY kind) m
             ON m.id = u.id""", (company_id,)) or []
    out = {}
    for r in rows:
        r['warnings'] = json.loads(r['warnings']) if r['warnings'] else []
        out[r['kind']] = r
    return out


def _ensure_dealers(cur, company_id, party_names):
    """{ledger name: dealer_id}, creating a dealer for every party name not seen before.
    Dealers come only from the Tally uploads; names are matched exactly."""
    cur.execute('SELECT dealer_id, tally_ledger_name FROM dpt_dealer WHERE company_id = %s FOR UPDATE',
                (company_id,))
    known = list(cur.fetchall())
    new = R.new_dealers(known, party_names)
    if new:
        cur.executemany(
            """INSERT INTO dpt_dealer (company_id, dealer_id, tally_ledger_name, dealer_name, principal,
                   town, is_new, source) VALUES (%s,%s,%s,%s,%s,%s,0,'Tally upload')""",
            [(company_id, d['dealer_id'], d['tally_ledger_name'], d['dealer_name'], d['principal'],
              d['town']) for d in new])
    ids = {d['tally_ledger_name']: d['dealer_id'] for d in known}
    ids.update({d['tally_ledger_name']: d['dealer_id'] for d in new})
    return ids, new


# ── Tally uploads ─────────────────────────────────────────────────────────────

def load_outstanding(company_id, data, filename, user):
    """Store an Export 1 snapshot. Re-uploading the same as-of date replaces it."""
    parsed = P.parse_outstanding(_check_size(data))
    with mysql_manager.get_cursor() as cur:
        ids, new = _ensure_dealers(cur, company_id, [b['party'] for b in parsed['bills']])
        upload_id = _upload_row(cur, company_id, KIND_OUTSTANDING, filename, user,
                                as_of=parsed['as_of'], period_from=parsed['period_from'],
                                period_to=parsed['as_of'], row_count=len(parsed['bills']),
                                warnings=parsed['warnings'])
        cur.execute('DELETE FROM dpt_outstanding WHERE company_id = %s AND as_of_date = %s',
                    (company_id, parsed['as_of']))
        replaced = cur.rowcount
        cur.execute('DELETE FROM dpt_bill_adjustment WHERE company_id = %s AND as_of_date = %s',
                    (company_id, parsed['as_of']))
        cur.executemany(
            """INSERT INTO dpt_outstanding (company_id, as_of_date, dealer_id, ref_no, kind, bill_date,
                   opening_amt, pending_amt_signed, due_on, overdue_days, upload_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [(company_id, parsed['as_of'], ids[b['party']], b['ref_no'], b['kind'], b['bill_date'],
              b['opening_amt'], b['pending_amt'], b['due_on'], b['overdue_days'], upload_id)
             for b in parsed['bills']])
        if parsed['adjustments']:
            cur.executemany(
                """INSERT INTO dpt_bill_adjustment (company_id, as_of_date, dealer_id, ref_no, vch_type,
                       vch_no, vch_date, amount, upload_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(company_id, parsed['as_of'], ids[a['party']], a['ref_no'], a['vch_type'], a['vch_no'],
                  a['vch_date'], a['amount'], upload_id) for a in parsed['adjustments']])
    out = run_processing(company_id)
    return {'upload_id': upload_id, 'as_of': parsed['as_of'], 'bills': len(parsed['bills']),
            'voucher_lines': len(parsed['adjustments']), 'grand_total': parsed['grand_total'],
            'replaced_rows': replaced, 'new_dealers': [d['dealer_id'] for d in new],
            'warnings': parsed['warnings'], 'processing': out}


def load_receipts(company_id, data, filename, user):
    """Window reload (spec 2.3): delete every stored receipt dated inside the file's period,
    then insert the file's receipts — one transaction, so a failure leaves the old ones."""
    parsed = P.parse_receipt_register(_check_size(data))
    lo, hi = parsed['period_from'], parsed['period_to']
    with mysql_manager.get_cursor() as cur:
        ids, new = _ensure_dealers(cur, company_id, [r['party'] for r in parsed['receipts']])
        upload_id = _upload_row(cur, company_id, KIND_RECEIPTS, filename, user, period_from=lo,
                                period_to=hi, row_count=len(parsed['receipts']),
                                warnings=parsed['warnings'])
        cur.execute('DELETE FROM dpt_receipt WHERE company_id = %s AND vch_date BETWEEN %s AND %s',
                    (company_id, lo, hi))
        deleted = cur.rowcount
        if parsed['receipts']:
            cur.executemany(
                """INSERT INTO dpt_receipt (company_id, vch_no, vch_date, dealer_id, vch_type, amount, upload_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                [(company_id, r['vch_no'], r['vch_date'], ids[r['party']], r['vch_type'] or R.RECEIPT,
                  r['amount'], upload_id) for r in parsed['receipts']])
    out = run_processing(company_id)
    return {'upload_id': upload_id, 'period_from': lo, 'period_to': hi, 'deleted': deleted,
            'inserted': len(parsed['receipts']), 'total': parsed['total'],
            'new_dealers': [d['dealer_id'] for d in new], 'warnings': parsed['warnings'],
            'processing': out}


def _check_size(data):
    if not data:
        raise DealerPaymentsError('The file is empty.')
    if len(data) > MAX_FILE_BYTES:
        raise DealerPaymentsError('The file is larger than 10 MB; is it the right export?')
    return data


def _upload_row(cur, company_id, kind, filename, user, as_of=None, period_from=None, period_to=None,
                row_count=0, warnings=None):
    cur.execute(
        """INSERT INTO dpt_upload (company_id, kind, filename, as_of, period_from, period_to, row_count,
               warnings, uploaded_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (company_id, kind, (filename or '')[:255], as_of, period_from, period_to, row_count,
         json.dumps(warnings or [])[:60000], (user or 'system')[:100]))
    return cur.lastrowid


# ── payment log (2.4) ─────────────────────────────────────────────────────────

def create_payment(company_id, form, user, proof=None):
    """Log a payment the moment it is heard of. Returns the payment after processing, so
    one Tally already shows comes back POSTED."""
    dealer_id = (form.get('dealer_id') or '').strip()
    known = {d['dealer_id']: d for d in dealers(company_id)}
    if dealer_id not in known:
        raise DealerPaymentsError('Choose the dealer from the list.')
    mode = (form.get('mode') or '').strip().upper()
    if mode not in R.MODES:
        raise DealerPaymentsError('Mode must be BT (NEFT / RTGS / UPI) or CASH.')
    try:
        amount = Decimal(str(form.get('amount') or '').replace(',', '').strip()).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        raise DealerPaymentsError('Enter the amount as a number.')
    if amount <= 0:
        raise DealerPaymentsError('The amount must be more than zero.')
    try:
        payment_date = datetime.strptime((form.get('payment_date') or '').strip(), '%Y-%m-%d').date()
    except ValueError:
        raise DealerPaymentsError('Payment date must be YYYY-MM-DD.')
    if payment_date > today_ist() + timedelta(days=1):
        raise DealerPaymentsError('The payment date is in the future.')
    reference = (form.get('reference') or '').strip()[:64]
    note = (form.get('note') or '').strip()[:500]

    with mysql_manager.get_cursor() as cur:
        cur.execute(
            """INSERT INTO dpt_payment (company_id, dealer_id, mode, amount, payment_date, reference, note,
                   status, created_by, updated_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (company_id, dealer_id, mode, amount, payment_date, reference, note, R.OPEN,
             (user or '')[:100], (user or '')[:100]))
        payment_id = cur.lastrowid
    if proof is not None and getattr(proof, 'filename', ''):
        from api.shared import media
        try:
            path, mime, _size = media.save_payment_proof(proof, payment_id)
        except media.MediaError as e:
            mysql_manager.execute_query('DELETE FROM dpt_payment WHERE id = %s AND company_id = %s',
                                        (payment_id, company_id), fetch=False)
            raise DealerPaymentsError(f'Proof image: {e}')
        mysql_manager.execute_query('UPDATE dpt_payment SET proof_path = %s, proof_mime = %s WHERE id = %s',
                                    (path, mime, payment_id), fetch=False)
    run_processing(company_id)
    return payment(company_id, payment_id)


def payment(company_id, payment_id):
    rows = [p for p in payments(company_id) if p['id'] == int(payment_id)]
    if not rows:
        raise DealerPaymentsError('No such payment.')
    return rows[0]


def cancel_payment(company_id, payment_id, user):
    """OPEN -> CANCELLED, by hand (2.4). A POSTED or BOUNCED payment is Tally's record now."""
    p = payment(company_id, payment_id)
    if p['status'] != R.OPEN:
        raise DealerPaymentsError(f'Only an OPEN payment can be cancelled; this one is {p["status"]}.')
    mysql_manager.execute_query(
        "UPDATE dpt_payment SET status = %s, updated_by = %s WHERE id = %s AND company_id = %s AND status = %s",
        (R.CANCELLED, (user or '')[:100], p['id'], company_id, R.OPEN), fetch=False)
    run_processing(company_id)
    return payment(company_id, payment_id)


def proof(company_id, payment_id):
    rows = mysql_manager.execute_query(
        'SELECT proof_path, proof_mime FROM dpt_payment WHERE id = %s AND company_id = %s',
        (int(payment_id), company_id)) or []
    if not rows or not rows[0]['proof_path']:
        raise DealerPaymentsError('This payment has no proof image.')
    return rows[0]['proof_path'], rows[0]['proof_mime']


# ── cheques (2.5) ─────────────────────────────────────────────────────────────

# The cheques last read from the cheque system, per company: {cheques, error, read_at}.
# wareops is read only when someone opens the dealer screen (screen(read_cheques=True));
# every other reload — after an upload, a review, Refresh — and processing reuse this copy.
_CHEQUE_CACHE = {}


def _read_cheques(company_id, today):
    adapter = C.get_adapter()
    try:
        raw, error = C.normalize(adapter.fetch_cheques(fy_start(today))), None
    except C.ChequeAdapterError as e:
        logger.warning('cheque adapter: %s', e)
        raw, error = [], f'Could not read the cheque system: {e}'
    except Exception as e:      # the adapter is someone else's system
        logger.exception('cheque adapter failed')
        raw, error = [], f'Could not read the cheque system: {e}'
    _CHEQUE_CACHE[company_id] = {'cheques': raw, 'error': error, 'read_at': datetime.utcnow() + timedelta(hours=5, minutes=30)}
    return _CHEQUE_CACHE[company_id]


def fetch_cheques(company_id, dealer_list, today, read=False):
    """(mapped, unmapped, other, error, read_at) — see rules.map_cheques. Reads the cheque
    system only when `read`; otherwise uses the cheques from the last read. An adapter failure
    is reported, not raised: the rest of the screen still works."""
    got = _read_cheques(company_id, today) if read else _CHEQUE_CACHE.get(company_id)
    if got is None:
        return [], [], [], 'Cheques are read when you open the Dealer Payments tile; open it again to read them.', None
    mapped, unmapped, other = R.map_cheques(got['cheques'], dealer_list)
    return mapped, unmapped, other, got['error'], got['read_at']


# ── processing (3) ────────────────────────────────────────────────────────────

def run_processing(company_id, today=None):
    """3.1 bounces -> 3.2 matching -> 3.3 flags, after every upload and payment change.
    Only payment statuses and the manual-check list are written."""
    today = today or today_ist()
    dealer_list = dealers(company_id)
    bills = snapshot(company_id, latest_as_of(company_id))
    rs = receipts(company_id)
    keys = {R.receipt_key(r) for r in rs}
    pays = payments(company_id)
    summary = {'reopened': 0, 'bounced': 0, 'posted': 0, 'ambiguous': 0}

    with mysql_manager.get_cursor() as cur:
        # A POSTED payment whose receipt Tally has since deleted (gone after a window
        # reload) is open again, and can match afresh below.
        for p in pays:
            if p['status'] == R.POSTED and p['matched_vch_no'] and \
                    (p['matched_vch_no'], p['matched_vch_date']) not in keys:
                cur.execute("""UPDATE dpt_payment SET status = %s, matched_vch_no = NULL,
                               matched_vch_date = NULL, updated_by = 'auto' WHERE id = %s""", (R.OPEN, p['id']))
                p.update(status=R.OPEN, matched_vch_no=None, matched_vch_date=None)
                summary['reopened'] += 1

        # 3.1 A payment a Boo bill reverses has bounced.
        boos = R.bounce_bills(bills)
        for pid, ref in R.bounced_payments(pays, boos).items():
            cur.execute("UPDATE dpt_payment SET status = %s, bounced_by_ref = %s, updated_by = 'auto' WHERE id = %s",
                        (R.BOUNCED, ref, pid))
            next(p for p in pays if p['id'] == pid)['status'] = R.BOUNCED
            summary['bounced'] += 1

        # 3.2 Match OPEN payments to Tally receipts.
        matched = {(p['matched_vch_no'], p['matched_vch_date']) for p in pays if p['matched_vch_no']}
        posted, ambiguous = R.match_payments(pays, rs, matched)
        for pid, (vch_no, vch_date) in posted.items():
            cur.execute("""UPDATE dpt_payment SET status = %s, matched_vch_no = %s, matched_vch_date = %s,
                           updated_by = 'auto' WHERE id = %s AND status = %s""",
                        (R.POSTED, vch_no, vch_date, pid, R.OPEN))
        summary['posted'], summary['ambiguous'] = len(posted), len(ambiguous)

    # 3.3 Flags for the Manual check list. Unmapped-cheque flags are raised by screen() when it
    # reads the cheque system, so processing never touches it.
    flags = R.manual_check_flags(
        duplicates=R.possible_duplicates(rs, boos),
        credits=R.credit_balances(bills),
        ambiguous=ambiguous,
        payments_by_id={p['id']: p for p in pays},
        receipts_by_key={R.receipt_key(r): r for r in rs})
    # FLAG_NEW_DEALER is no longer raised; listing it here clears any left from before.
    types = {R.FLAG_DUPLICATE, R.FLAG_CREDIT, R.FLAG_AMBIGUOUS, R.FLAG_NEW_DEALER}
    summary['flags'] = _sync_flags(company_id, flags, types)
    return summary


def _sync_flags(company_id, flags, types):
    """Store the flags by fingerprint. A flag seen before keeps its Reviewed state; one no
    longer raised is set inactive (kept, hidden)."""
    with mysql_manager.get_cursor() as cur:
        for f in flags:
            details = {k: v for k, v in f.items() if k not in ('fingerprint', 'flag_type', 'dealer_id', 'reason')}
            cur.execute(
                """INSERT INTO dpt_manual_check (company_id, fingerprint, flag_type, dealer_id, details, reason)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE active = 1, last_seen = CURRENT_TIMESTAMP,
                       details = VALUES(details), reason = VALUES(reason), dealer_id = VALUES(dealer_id)""",
                (company_id, f['fingerprint'][:400], f['flag_type'], f['dealer_id'],
                 json.dumps(details, default=_json_default), f['reason'][:500]))
        live = [f['fingerprint'][:400] for f in flags]
        sql = 'UPDATE dpt_manual_check SET active = 0 WHERE company_id = %s AND flag_type IN ({})'.format(
            ','.join(['%s'] * len(types)))
        params = [company_id, *sorted(types)]
        if live:
            sql += ' AND fingerprint NOT IN ({})'.format(','.join(['%s'] * len(live)))
            params += live
        cur.execute(sql, tuple(params))
    return len(flags)


def _json_default(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


def manual_checks(company_id, include_reviewed=False):
    sql = """SELECT m.id, m.flag_type, m.dealer_id, d.dealer_name, d.town, m.details, m.reason,
                    m.reviewed, m.review_note, m.reviewed_by, m.reviewed_on, m.first_seen
             FROM dpt_manual_check m
             LEFT JOIN dpt_dealer d ON d.company_id = m.company_id AND d.dealer_id = m.dealer_id
             WHERE m.company_id = %s AND m.active = 1"""
    if not include_reviewed:
        sql += ' AND m.reviewed = 0'
    sql += ' ORDER BY m.flag_type, m.first_seen, m.id'
    rows = mysql_manager.execute_query(sql, (company_id,)) or []
    for r in rows:
        r['details'] = json.loads(r['details']) if r['details'] else {}
        r['reviewed'] = bool(r['reviewed'])
        r['type_label'] = R.FLAG_LABELS.get(r['flag_type'], r['flag_type'])
    return rows


def set_review(company_id, check_id, reviewed, note, user):
    rows = mysql_manager.execute_query(
        'SELECT id FROM dpt_manual_check WHERE id = %s AND company_id = %s', (int(check_id), company_id))
    if not rows:
        raise DealerPaymentsError('No such manual-check item.')
    mysql_manager.execute_query(
        """UPDATE dpt_manual_check SET reviewed = %s, review_note = %s, reviewed_by = %s,
               reviewed_on = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END
           WHERE id = %s AND company_id = %s""",
        (int(bool(reviewed)), (note or '').strip()[:500], (user or '')[:100] if reviewed else '',
         int(bool(reviewed)), int(check_id), company_id), fetch=False)
    return {'id': int(check_id), 'reviewed': bool(reviewed)}


# ── the daily dealer screen (4) ───────────────────────────────────────────────

def screen(company_id, today=None, include_reviewed=False, read_cheques=False):
    """The daily dealer screen. `read_cheques` (set when the tile is opened) reads the cheque
    system afresh and syncs the unmapped-cheque flags; otherwise the last read is reused."""
    today = today or today_ist()
    dealer_list = dealers(company_id)
    as_of = latest_as_of(company_id)
    bills = snapshot(company_id, as_of, today)
    pays = payments(company_id)
    mapped, unmapped, other, cheque_error, cheques_read_at = fetch_cheques(company_id, dealer_list, today,
                                                                           read=read_cheques)
    if read_cheques and cheque_error is None:   # keep the old flags while the system is unreachable
        _sync_flags(company_id, R.manual_check_flags(unmapped=unmapped), {R.FLAG_UNMAPPED_CHEQUE})
    bounced_cheques = R.bounced_cheques(mapped, R.bounce_bills(bills))
    cleared = _cleared_not_in_tally(company_id, mapped, bounced_cheques.keys(), pays)
    names = {d['dealer_id']: d for d in dealer_list}
    vouchers_to = mysql_manager.execute_query(
        'SELECT MAX(vch_date) AS d FROM dpt_receipt WHERE company_id = %s', (company_id,))
    adapter = C.get_adapter()

    def dealer_label(dealer_id):
        d = names.get(dealer_id)
        return f"{d['dealer_name']} ({d['town']})" if d and d['town'] else (d['dealer_name'] if d else dealer_id)

    return {
        'today': today,
        'tally_as_of': as_of,
        'vouchers_loaded_to': vouchers_to[0]['d'] if vouchers_to else None,
        'uploads': last_uploads(company_id),
        'dealer_count': len(dealer_list),
        'cheque_system': {'name': adapter.name, 'connected': bool(adapter.connected and not cheque_error),
                          'error': cheque_error, 'read_at': cheques_read_at, 'cheques': len(mapped),
                          'other_parties': len({c['party_name'] for c in other})},
        'rows': R.dealer_rows(dealer_list, bills, pays, mapped, today, bounced_cheques.keys(), cleared),
        'pdcs_due': [{**c, 'dealer': dealer_label(c['dealer_id'])}
                     for c in R.pdcs_to_deposit(mapped, today, bounced_cheques.keys())],
        'bounced_cheques': [{'cheque_no': k[0], 'bank': k[1], 'boo_ref': v} for k, v in bounced_cheques.items()],
        'cheques': _cheque_lines(mapped, bounced_cheques, dealer_label, cleared),
        'stale_payments': [{**p, 'dealer': dealer_label(p['dealer_id']),
                            'days_open': (today - p['payment_date']).days}
                           for p in R.stale_payments(pays, today)],
        'manual_checks': manual_checks(company_id, include_reviewed),
    }


def _cleared_not_in_tally(company_id, mapped, bounced_keys, pays):
    """The cleared cheques Tally has no receipt for yet (rules.cleared_not_in_tally)."""
    got = mysql_manager.execute_query(
        'SELECT MIN(period_from) AS d FROM dpt_upload WHERE company_id = %s AND kind = %s',
        (company_id, KIND_RECEIPTS))
    covered_from = got[0]['d'] if got else None
    matched = {(str(p['matched_vch_no']), p['matched_vch_date']) for p in pays if p['matched_vch_no']}
    return R.cleared_not_in_tally(mapped, receipts(company_id), matched, covered_from, bounced_keys)


def _cheque_lines(mapped, bounced_cheques, dealer_label, cleared=()):
    """Every mapped cheque, newest first, with whether it counts in PDCs held (`counted`) or,
    cleared but not in Tally yet, in Received, not in Tally (`in_received`)."""
    cleared_keys = {(c['cheque_no'], c['bank']) for c in cleared}
    out = []
    for c in sorted(mapped, key=lambda c: (c['cheque_date'], c['cheque_no']), reverse=True):
        boo = bounced_cheques.get((c['cheque_no'], c['bank']))
        out.append({**c, 'dealer': dealer_label(c['dealer_id']), 'boo_ref': boo,
                    'counted': c['status'] in R.HELD and not boo,
                    'in_received': (c['cheque_no'], c['bank']) in cleared_keys})
    return out


def _cheques_note(read_at, error):
    if error:
        return error
    return f"read from the cheque system at {read_at.strftime('%d-%b-%y %H:%M')} when the tile was opened"


# ── one dealer, in detail ─────────────────────────────────────────────────────

def dealer_detail(company_id, dealer_id, today=None):
    """Everything about one dealer: the line on the dealer screen, its pending bills (with the
    Tally voucher lines under each), payments logged and PDC cheques of any status. Cheques
    come from the last read (the tile open); wareops is not read."""
    today = today or today_ist()
    dealer_list = dealers(company_id)
    d = next((x for x in dealer_list if x['dealer_id'] == dealer_id), None)
    if d is None:
        raise DealerPaymentsError(f'No dealer {dealer_id}.')
    as_of = latest_as_of(company_id)
    all_bills = snapshot(company_id, as_of, today)
    bills = [b for b in all_bills if b['dealer_id'] == dealer_id]
    pays = payments(company_id)
    mapped, _u, _o, cheque_error, read_at = fetch_cheques(company_id, dealer_list, today)
    bounced = R.bounced_cheques(mapped, R.bounce_bills(all_bills))
    cleared = _cleared_not_in_tally(company_id, mapped, bounced.keys(), pays)
    label = (f"{d['dealer_name']} ({d['town']})" if d['town'] else d['dealer_name'])
    adj = mysql_manager.execute_query(
        """SELECT ref_no, vch_type, vch_no, vch_date, amount FROM dpt_bill_adjustment
           WHERE company_id = %s AND as_of_date = %s AND dealer_id = %s ORDER BY vch_date, id""",
        (company_id, as_of, dealer_id)) or [] if as_of else []
    adj_by = {}
    for a in adj:
        adj_by.setdefault(a['ref_no'], []).append(a)
    return {
        'dealer': {**d, 'label': label},
        'tally_as_of': as_of,
        'summary': R.dealer_summary(d, bills, pays, mapped, bounced.keys(), cleared),
        'bills': [{**b, 'adjustments': adj_by.get(b['ref_no'], []),
                   'label': R.BOUNCE_LABEL if b['kind'] == P.KIND_BOUNCE else None} for b in bills],
        'payments': [p for p in pays if p['dealer_id'] == dealer_id],
        'cheques': _cheque_lines([c for c in mapped if c['dealer_id'] == dealer_id], bounced, lambda _i: label,
                                 cleared),
        'cheques_note': _cheques_note(read_at, cheque_error),
    }


# ── the Outstanding download ──────────────────────────────────────────────────

def outstanding_export(company_id, today=None):
    """(filename, xlsx bytes). Cheques from the last read; wareops is not read."""
    from api.modules.sales.dealer_payments.exports import build_outstanding_xlsx
    today = today or today_ist()
    dealer_list = dealers(company_id)
    as_of = latest_as_of(company_id)
    bills = snapshot(company_id, as_of, today)
    mapped, _u, _o, cheque_error, read_at = fetch_cheques(company_id, dealer_list, today)
    pays = payments(company_id)
    bounced = R.bounced_cheques(mapped, R.bounce_bills(bills))
    data = build_outstanding_xlsx(as_of=as_of, dealers=dealer_list, bills=bills, payments=pays,
                                  cheques=mapped, bounced_cheques=bounced,
                                  cheques_note=_cheques_note(read_at, cheque_error), today=today,
                                  cleared=_cleared_not_in_tally(company_id, mapped, bounced.keys(), pays))
    stamp = (as_of or today).strftime('%d-%b-%y')
    return f'Cadila Dealer Outstanding {stamp}.xlsx', data
