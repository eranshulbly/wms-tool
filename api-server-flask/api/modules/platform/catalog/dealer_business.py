# -*- encoding: utf-8 -*-
"""
Dealer Business Logic for MySQL
"""

from datetime import datetime
from api.models import mysql_manager
from api.core.logging import get_logger

logger = get_logger(__name__)

# Cache to avoid repeated database lookups
_dealer_cache = {}


def get_or_create_dealer(dealer_name, dealer_code=None, company_id=None):
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
    if cache_key in _dealer_cache:
        logger.debug("Dealer cache hit", extra={'dealer_id': _dealer_cache[cache_key]})
        return _dealer_cache[cache_key]

    def _remember(dealer_id):
        for key in (code_key, name_key):
            if key:
                _dealer_cache[key] = dealer_id
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
