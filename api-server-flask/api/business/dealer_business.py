# -*- encoding: utf-8 -*-
"""
Dealer Business Logic for MySQL
"""

from datetime import datetime
from ..models import Dealer
from ..core.logging import get_logger

logger = get_logger(__name__)

# Cache to avoid repeated database lookups
_dealer_cache = {}


def get_or_create_dealer(dealer_name, dealer_code=None):
    """
    Get an existing dealer or create a new one.

    Lookup order:
      1. If dealer_code provided: find by dealer_code first
      2. Fall back to find by name
      3. Create new dealer if not found

    Args:
        dealer_name: Name of the dealer
        dealer_code: Optional eway bill dealer code

    Returns:
        int: Dealer ID
    """
    dealer_name = dealer_name.strip() if dealer_name else ''
    dealer_code = dealer_code.strip() if dealer_code else None

    if not dealer_name and not dealer_code:
        raise ValueError("Dealer name or code must be provided")

    logger.debug("get_or_create_dealer", extra={'dealer_name': dealer_name, 'dealer_code': dealer_code})

    # Check cache by code first, then by name
    cache_key = dealer_code if dealer_code else dealer_name.lower()
    if cache_key in _dealer_cache:
        logger.debug("Dealer cache hit", extra={'dealer_id': _dealer_cache[cache_key]})
        return _dealer_cache[cache_key]

    # 1. Try lookup by dealer_code
    if dealer_code:
        try:
            dealer = Dealer.find_by_code(dealer_code)
            if dealer:
                logger.debug("Found dealer by code", extra={'dealer_id': dealer.dealer_id})
                _dealer_cache[cache_key] = dealer.dealer_id
                if dealer_name and dealer_name.lower():
                    _dealer_cache[dealer_name.lower()] = dealer.dealer_id
                return dealer.dealer_id
        except Exception as e:
            logger.warning("Error querying dealer by code", extra={'dealer_code': dealer_code, 'error': str(e)})

    # 2. Try lookup by name
    if dealer_name:
        try:
            dealer = Dealer.find_by_name(dealer_name)
            if dealer:
                logger.debug("Found dealer by name", extra={'dealer_id': dealer.dealer_id})
                # Update dealer_code if we now have it and it wasn't set
                if dealer_code and not dealer.dealer_code:
                    dealer.dealer_code = dealer_code
                    dealer.save()
                    logger.debug("Updated dealer code", extra={'dealer_code': dealer_code})
                _dealer_cache[cache_key] = dealer.dealer_id
                return dealer.dealer_id
        except Exception as e:
            logger.warning("Error querying dealer by name", extra={'dealer_name': dealer_name, 'error': str(e)})

    # 3. Create new dealer
    try:
        dealer = Dealer(
            name=dealer_name or dealer_code,
            dealer_code=dealer_code,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        dealer.save()

        dealer_id = dealer.dealer_id
        logger.debug("Created new dealer", extra={'dealer_id': dealer_id, 'dealer_name': dealer_name})

        _dealer_cache[cache_key] = dealer_id
        if dealer_name and dealer_name.lower() != cache_key:
            _dealer_cache[dealer_name.lower()] = dealer_id
        return dealer_id

    except Exception as e:
        logger.exception("Error creating dealer", extra={'dealer_name': dealer_name})
        raise e


def clear_dealer_cache():
    """Clear the dealer cache — useful for testing."""
    global _dealer_cache
    _dealer_cache = {}
    logger.debug("Dealer cache cleared")
