# -*- encoding: utf-8 -*-
"""
Dealer Business Logic for MySQL
"""

import re
from datetime import datetime
from api.models import mysql_manager
from api.core.logging import get_logger

logger = get_logger(__name__)

# What an order/invoice document can tell us about the buyer, beyond its name and code.
# Each is a dealer column. Files carrying them under the "Party ..." headings are read by
# dealer_details_from_row; the dealer master upload writes the same columns directly.
DEALER_DETAIL_FIELDS = ('gstin', 'phone', 'alt_phone', 'address', 'town', 'state', 'pincode',
                        'pan', 'drug_license_numbers', 'sale_type', 'credit_days')

_GSTIN_RE = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$')

# Row header -> dealer column. 'Party GSTIN' is preferred; the plain code columns are only
# taken as a GSTIN when they look like one, since in a non-PDF feed they hold a dealer code.
_ROW_HEADERS = {
    'phone': 'Party Phone', 'alt_phone': 'Party Alt Phone', 'address': 'Party Address',
    'town': 'Party Town', 'state': 'Party State', 'pincode': 'Party Pincode',
    'pan': 'Party PAN', 'drug_license_numbers': 'Party Drug Licenses',
    'sale_type': 'Sale Type', 'credit_days': 'Credit Days',
}


def _clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s.lower() in ('', 'nan', 'none', 'nat') else s


def dealer_details_from_row(row):
    """{dealer column: value} for whatever buyer details this upload row carries.

    Never raises and never invents: a missing or blank cell is simply absent from the
    result. The PAN is derived from a valid GSTIN when the file did not print one.
    """
    get = row.get if hasattr(row, 'get') else (lambda k, d=None: d)
    out = {}
    for field, header in _ROW_HEADERS.items():
        val = _clean(get(header))
        if val:
            out[field] = val

    gstin = None
    for header in ('Party GSTIN', 'Code', 'Purchaser SAP Code'):
        cand = (_clean(get(header)) or '').upper()
        if _GSTIN_RE.match(cand):
            gstin = cand
            break
    if gstin:
        out['gstin'] = gstin
        out.setdefault('pan', gstin[2:12])

    if 'credit_days' in out:
        try:
            out['credit_days'] = int(float(out['credit_days']))
        except ValueError:
            del out['credit_days']
    if 'sale_type' in out:
        out['sale_type'] = out['sale_type'].upper()[:10]
    return out


def _fill_blank_details(dealer_id, details):
    """Set each detail the dealer does not already have.

    COALESCE(NULLIF(col, ''), new): an invoice can complete a dealer created from a bare
    order, but it can never overwrite what someone entered by hand or loaded through the
    dealer master — the printed party block is the less trusted source (clipped state,
    truncated phone numbers, an address that wraps mid-word).
    """
    fields = [f for f in DEALER_DETAIL_FIELDS if details.get(f) not in (None, '')]
    if not fields:
        return
    sets = ', '.join(f"{f} = COALESCE(NULLIF({f}, ''), %s)" if f != 'credit_days'
                     else "credit_days = COALESCE(credit_days, %s)" for f in fields)
    try:
        mysql_manager.execute_query(
            f"UPDATE dealer SET {sets}, updated_at = %s WHERE dealer_id = %s",
            tuple(details[f] for f in fields) + (datetime.utcnow(), dealer_id), fetch=False)
    except Exception as e:
        # Enrichment is a bonus on top of resolving the dealer; it must not fail the upload.
        logger.warning("Could not complete dealer details",
                       extra={'dealer_id': dealer_id, 'error': str(e)})

# Cache to avoid repeated database lookups
_dealer_cache = {}


def get_or_create_dealer(dealer_name, dealer_code=None, company_id=None, details=None):
    """
    Get an existing dealer or create a new one.

    Lookup order:
      1. If dealer_code provided: find by dealer_code first
      2. Fall back to find by name (case-insensitive)
      3. Create new dealer if not found

    With `company_id`, both lookups are confined to that company and a dealer created
    here belongs to it. A dealer is one company's customer: matching by name across
    tenants attaches an order to another company's dealer, and creating a dealer with no
    company leaves one that no company-scoped screen can ever show. Callers that have no
    company (the e-way bill flow) keep the previous unscoped behaviour.

    `details` (see DEALER_DETAIL_FIELDS) is what the document also said about the buyer. A
    new dealer is created with it; an existing one only has its BLANK fields completed.

    Returns:
        int: Dealer ID
    """
    dealer_name = dealer_name.strip() if dealer_name else ''
    dealer_code = dealer_code.strip() if dealer_code else None

    if not dealer_name and not dealer_code:
        raise ValueError("Dealer name or code must be provided")

    scope_sql, scope_params = ('AND company_id = %s', (company_id,)) if company_id else ('', ())

    # Keyed by company as well: otherwise the first company to name a dealer answers that
    # lookup for every other company for the rest of the upload.
    prefix = f"{company_id or ''}:"
    code_key = f"{prefix}code:{dealer_code}" if dealer_code else None
    name_key = f"{prefix}name:{dealer_name.lower()}" if dealer_name else None
    cache_key = code_key or name_key
    details = {f: v for f, v in (details or {}).items()
               if f in DEALER_DETAIL_FIELDS and v not in (None, '')}
    if cache_key in _dealer_cache:
        logger.debug("Dealer cache hit", extra={'dealer_id': _dealer_cache[cache_key]})
        if details:
            _fill_blank_details(_dealer_cache[cache_key], details)
        return _dealer_cache[cache_key]

    def _remember(dealer_id):
        for key in (code_key, name_key):
            if key:
                _dealer_cache[key] = dealer_id
        if details:
            _fill_blank_details(dealer_id, details)
        return dealer_id

    # 1. Try lookup by dealer_code
    if dealer_code:
        try:
            rows = mysql_manager.execute_query(
                f"SELECT dealer_id FROM dealer WHERE dealer_code = %s {scope_sql} LIMIT 1",
                (dealer_code, *scope_params))
            if rows:
                logger.debug("Found dealer by code", extra={'dealer_id': rows[0]['dealer_id']})
                return _remember(rows[0]['dealer_id'])
        except Exception as e:
            logger.warning("Error querying dealer by code",
                           extra={'dealer_code': dealer_code, 'error': str(e)})

    # 2. Try lookup by name
    if dealer_name:
        try:
            rows = mysql_manager.execute_query(
                f"SELECT dealer_id, dealer_code FROM dealer "
                f"WHERE LOWER(name) = LOWER(%s) {scope_sql} LIMIT 1",
                (dealer_name, *scope_params))
            if rows:
                dealer_id = rows[0]['dealer_id']
                logger.debug("Found dealer by name", extra={'dealer_id': dealer_id})
                # Update dealer_code if we now have it and it wasn't set
                if dealer_code and not rows[0]['dealer_code']:
                    mysql_manager.execute_query(
                        "UPDATE dealer SET dealer_code = %s, updated_at = %s WHERE dealer_id = %s",
                        (dealer_code, datetime.utcnow(), dealer_id), fetch=False)
                    logger.debug("Updated dealer code", extra={'dealer_code': dealer_code})
                return _remember(dealer_id)
        except Exception as e:
            logger.warning("Error querying dealer by name",
                           extra={'dealer_name': dealer_name, 'error': str(e)})

    # 3. Create new dealer
    try:
        now = datetime.utcnow()
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                "INSERT INTO dealer (name, dealer_code, company_id, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (dealer_name or dealer_code, dealer_code, company_id, now, now))
            dealer_id = cursor.lastrowid
        logger.info("Created new dealer",
                    extra={'dealer_id': dealer_id, 'dealer_name': dealer_name,
                           'company_id': company_id})
        return _remember(dealer_id)

    except Exception as e:
        logger.exception("Error creating dealer", extra={'dealer_name': dealer_name})
        raise e


def clear_dealer_cache():
    """Clear the dealer cache — useful for testing."""
    global _dealer_cache
    _dealer_cache = {}
    logger.debug("Dealer cache cleared")
