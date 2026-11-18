# -*- encoding: utf-8 -*-
"""Post-dated cheques from the cheque reconciliation system (spec 2.5).

The tracker only ever calls `fetch_cheques(since_date)` on the adapter `get_adapter()`
returns. Each cheque is
    {cheque_no, bank, party_name, amount, cheque_date, status}
with status one of HOLDING | DEPOSITED | CLEARED | BOUNCED.

The real system is wareops (warehouse-ops, wareops.duckdns.org). Its cheques live in the
`cheques` table of the `warehouse_ops` database on the same RDS server as this app's own, so
WareopsChequeAdapter reads them with one SELECT over the existing connection pool: no new
connection, no write. It needs this read-only grant, run once by the RDS admin:

    GRANT SELECT (id, status, cheque_number, cheque_date, amount, dealer_name, bank_name,
                  payee_name) ON warehouse_ops.cheques TO '<this app's DB user>'@'%';

(cadila_app on Cadila, ebco_app on Ebco.)

Until then it reports "no read access" and the rest of the screen works as before.
StubChequeAdapter (no cheques) is kept for the tests.
"""

import os
from datetime import date, datetime
from decimal import Decimal

from api.modules.sales.dealer_payments.rules import HOLDING, DEPOSITED, CLEARED, CHQ_BOUNCED

STATUSES = (HOLDING, DEPOSITED, CLEARED, CHQ_BOUNCED)


class ChequeAdapterError(RuntimeError):
    pass


class ChequeAdapter:
    """The interface. `name` is shown on the screen next to PDCs held."""
    name = 'cheque system'
    connected = True

    def fetch_cheques(self, since_date):
        raise NotImplementedError


class StubChequeAdapter(ChequeAdapter):
    """Stands in until the real cheque system is wired: returns `cheques` (none by default)."""
    name = 'cheque system (not connected yet)'
    connected = False

    def __init__(self, cheques=None):
        self._cheques = list(cheques or [])

    def fetch_cheques(self, since_date):
        return [c for c in self._cheques if since_date is None or _as_date(c['cheque_date']) >= since_date]


# wareops status -> tracker status. draft / pending / rejected are not cheques in hand yet.
WAREOPS_STATUS = {'submitted': HOLDING, 'presented': DEPOSITED, 'passed': CLEARED, 'bounced': CHQ_BOUNCED}

# MySQL: 1044 no access to the database, 1142 to the table, 1143 to a column.
_NO_ACCESS = (1044, 1142, 1143)


def _payee_key(s):
    return ''.join(ch for ch in str(s or '').upper() if ch.isalnum())


class WareopsChequeAdapter(ChequeAdapter):
    """Cheques payable to the company's payee (DPT_CHEQUE_PAYEE, default Anmol Associates), read from
    wareops' database (DPT_CHEQUE_SCHEMA, default warehouse_ops). Read only."""
    name = 'wareops cheques'
    connected = True

    def __init__(self, schema=None, payee=None):
        self.schema = schema or os.getenv('DPT_CHEQUE_SCHEMA') or 'warehouse_ops'
        self.payee = payee or os.getenv('DPT_CHEQUE_PAYEE') or 'Anmol Associates'
        if not self.schema.replace('_', '').isalnum():
            raise ChequeAdapterError(f'Bad DPT_CHEQUE_SCHEMA {self.schema!r}.')

    def fetch_cheques(self, since_date):
        from api.shared.db_manager import mysql_manager
        sql = (f"SELECT cheque_number, cheque_date, amount, dealer_name, bank_name, payee_name, status "
               f"FROM `{self.schema}`.cheques WHERE status IN %s AND cheque_date IS NOT NULL")
        params = [tuple(WAREOPS_STATUS)]
        if since_date is not None:
            sql += ' AND cheque_date >= %s'
            params.append(since_date)
        try:
            rows = mysql_manager.execute_query(sql, tuple(params)) or []
        except Exception as e:
            code = e.args[0] if getattr(e, 'args', None) else None
            if code in _NO_ACCESS:
                raise ChequeAdapterError(
                    'This app has no read access to the wareops cheques yet (an RDS admin must run the '
                    'GRANT in dealer_payments/cheques.py).') from e
            if code == 1146 or code == 1049:
                raise ChequeAdapterError(f'The wareops cheques table ({self.schema}.cheques) is not on '
                                         f'this database server.') from e
            raise
        return to_tracker(rows, self.payee)


def to_tracker(rows, payee):
    """wareops cheque rows -> the adapter's records: only `payee`'s cheques, with a usable
    number, amount and dealer."""
    want = _payee_key(payee)
    out = []
    for r in rows:
        status = WAREOPS_STATUS.get(str(r.get('status') or '').lower())
        if (not status or _payee_key(r.get('payee_name')) != want or not r.get('cheque_number')
                or r.get('amount') is None or not (r.get('dealer_name') or '').strip()):
            continue
        out.append({'cheque_no': str(r['cheque_number']).strip(), 'bank': (r.get('bank_name') or '').strip(),
                    'party_name': r['dealer_name'].strip(), 'amount': r['amount'],
                    'cheque_date': r['cheque_date'], 'status': status})
    return out


def get_adapter():
    if (os.getenv('DPT_CHEQUE_SOURCE') or 'wareops').lower() == 'stub':
        return StubChequeAdapter()
    return WareopsChequeAdapter()


def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v)[:10], '%Y-%m-%d').date()


def normalize(cheques):
    """Validate and type the adapter's output; raises ChequeAdapterError on a bad record."""
    out = []
    for i, c in enumerate(cheques or []):
        try:
            status = str(c['status']).upper()
            if status not in STATUSES:
                raise ValueError(f'status {c["status"]!r}')
            out.append({'cheque_no': str(c['cheque_no']), 'bank': str(c.get('bank') or ''),
                        'party_name': str(c['party_name']), 'amount': Decimal(str(c['amount'])).quantize(Decimal('0.01')),
                        'cheque_date': _as_date(c['cheque_date']), 'status': status})
        except (KeyError, ValueError, TypeError, ArithmeticError) as e:
            raise ChequeAdapterError(f'Cheque system record {i + 1} is not usable: {e}')
    return out
