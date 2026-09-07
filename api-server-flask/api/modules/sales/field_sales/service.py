# -*- encoding: utf-8 -*-
"""
Sales-analytics computation — the single source of truth shared by the web
dashboards (/api/analytics/*, legacy auth) and the mobile app (/api/v1/analytics/*,
JWT auth). Both routers are thin wrappers over the functions here.

This deployment is invoice-based: figures come from uploaded invoices
(`invoice`), attributed invoice -> dealer (invoice.dealer_id) -> executive
(dealer.sales_executive_id). There are no sales targets, so every payload
reports `has_targets` False and the app drops the target/category surfaces.

The month is taken from invoice_date (when the sale happened), not created_at
(when the file was uploaded), so a late upload lands in the month it belongs to.
Cancelled invoices carry a cancellation_date and are excluded — a cancelled
invoice is not a sale, and leaving it in inflates the rep's own number.
"""

from api.shared.db_manager import mysql_manager

# Attribution goes through the company's dealers, scoped to one company at a time.
DEFAULT_COMPANY = 1

_deployment_company_id = None


def deployment_company_id():
    """The one company this deployment serves (one schema = one company).

    With a schema per company there is exactly one `company` row, and it is the
    answer for every caller regardless of their grants. Cached after first read.
    """
    global _deployment_company_id
    if _deployment_company_id is None:
        rows = mysql_manager.execute_query(
            "SELECT company_id FROM company ORDER BY company_id LIMIT 1")
        _deployment_company_id = int(rows[0]['company_id']) if rows else DEFAULT_COMPANY
    return _deployment_company_id


def month_label(period='this_month'):
    """The month the figures actually cover, for the UI's period caption.

    Must follow `period`, not the wall clock: captioning last_month's numbers
    "August" while they are July's is how the dashboard ends up lying about
    which month it is showing. Rolling windows (last_7d, last_6m, …) are
    anchored to the current month, matching the target they are measured against.
    """
    # %% because execute_query runs `query % params`, so a literal % must be doubled.
    anchor = ("DATE_SUB(CURDATE(), INTERVAL 1 MONTH)" if period == 'last_month'
              else "CURDATE()")
    rows = mysql_manager.execute_query(f"SELECT DATE_FORMAT({anchor}, '%%M %%Y') AS m")
    return rows[0]['m'] if rows else ''


def _num(v):
    """MySQL SUM returns Decimal; hand the client plain floats/ints."""
    if v is None:
        return 0
    f = float(v)
    return int(f) if f.is_integer() else round(f, 2)


def _pct(sales, target):
    """% of target achieved, or None when there is no target to measure against."""
    if not target:
        return None
    return round(float(sales) / float(target) * 100, 1)


# ---------------------------------------------------------------------------
# Invoice-mode analytics
#
# This deployment has no Busy feed and no dealer_target rows: everything a
# company can answer is "how much was invoiced this month", so that is all
# these functions return — the app reads has_targets False and drops the
# target/category surfaces rather than rendering empty ones.
#
# The month is taken from invoice_date (when the sale happened), not created_at
# (when the file was uploaded), so a late upload lands in the month it belongs to.
# Cancelled invoices carry a cancellation_date and are excluded — a cancelled
# invoice is not a sale, and leaving it in inflates the rep's own number.
# ---------------------------------------------------------------------------

_INVOICE_MONTH = ("YEAR(i.invoice_date) = YEAR(CURDATE()) "
                  "AND MONTH(i.invoice_date) = MONTH(CURDATE())")
_INVOICE_LIVE = "i.cancellation_date IS NULL"


def invoice_data_through(company_id):
    """The latest invoice_date on file for the company, as 'YYYY-MM-DD'.

    Invoices arrive by upload, so the figures trail today by however long it's
    been since the last one.
    """
    rows = mysql_manager.execute_query(
        f"""SELECT MAX(i.invoice_date) AS d FROM invoice i
            WHERE i.company_id = %s AND {_INVOICE_LIVE}""", (int(company_id),))
    d = rows[0]['d'] if rows else None
    return d.date().isoformat() if hasattr(d, 'date') else (d.isoformat() if d else None)


def exec_invoice_summary(executive_id, company_id):
    """This month's invoiced total for one executive — the check-in home's card.

    Attribution runs invoice -> dealer -> dealer.sales_executive_id. An invoice
    with no dealer_id belongs to nobody and is therefore counted for nobody.
    """
    rows = mysql_manager.execute_query(
        f"""SELECT COALESCE(SUM(i.total_invoice_amount), 0) AS s
            FROM invoice i
            JOIN dealer d ON d.dealer_id = i.dealer_id AND d.company_id = %s
            WHERE i.company_id = %s AND d.sales_executive_id = %s
              AND {_INVOICE_LIVE} AND {_INVOICE_MONTH}""",
        (int(company_id), int(company_id), executive_id))
    return {
        'month': month_label(),
        'executive_id': executive_id,
        'sales': _num(rows[0]['s']) if rows else 0,
        'target': 0,
        'pct': None,
        'data_through': invoice_data_through(company_id),
        'has_targets': False,
    }


def dealer_invoice_summary(dealer_id, company_id):
    """This month's invoiced total for one dealer — the dealer session's overview.

    The category blocks are empty: an invoice-mode company has no category targets
    to split the total across. None when the dealer isn't in this company.
    """
    head = mysql_manager.execute_query(
        "SELECT dealer_id, name FROM dealer WHERE dealer_id = %s AND company_id = %s",
        (dealer_id, int(company_id)))
    if not head:
        return None

    rows = mysql_manager.execute_query(
        f"""SELECT COALESCE(SUM(i.total_invoice_amount), 0) AS s
            FROM invoice i
            WHERE i.company_id = %s AND i.dealer_id = %s
              AND {_INVOICE_LIVE} AND {_INVOICE_MONTH}""",
        (int(company_id), dealer_id))
    return {
        'month': month_label(),
        'dealer_id': head[0]['dealer_id'],
        'dealer_name': head[0]['name'],
        'sales': _num(rows[0]['s']) if rows else 0,
        'target': 0,
        'pct': None,
        'categories': [],
        'category_sales': [],
        'data_through': invoice_data_through(company_id),
        'has_targets': False,
    }
