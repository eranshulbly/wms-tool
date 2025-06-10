# -*- encoding: utf-8 -*-
"""
FIXED: Dealer Business Logic for MySQL
"""

from datetime import datetime
from ..models import (
    Dealer
)

# Cache to avoid repeated database lookups
_dealer_cache = {}


def get_or_create_dealer(dealer_name, dealer_code=None, dealer_last_name=None):
    """
    Get an existing dealer or create a new one - MySQL implementation

    Args:
        dealer_name: Name of the dealer
        dealer_code: Optional dealer code
        dealer_last_name: Optional last name

    Returns:
        int: Dealer ID
    """
    # Normalize dealer name
    dealer_name = dealer_name.strip() if dealer_name else ''

    if not dealer_name:
        raise ValueError("Dealer name cannot be empty")

    print(f"Getting or creating dealer: {dealer_name}")

    # Check cache first
    cache_key = dealer_name.lower()
    if cache_key in _dealer_cache:
        print(f"Found dealer in cache: {_dealer_cache[cache_key]}")
        return _dealer_cache[cache_key]

    # Try to find by name in database
    try:
        dealer = Dealer.find_by_name(dealer_name)
        if dealer:
            print(f"Found existing dealer: {dealer.dealer_id}")
            # Update cache
            _dealer_cache[cache_key] = dealer.dealer_id
            return dealer.dealer_id

    except Exception as e:
        print(f"Error querying for dealer: {str(e)}")

    # Create new dealer if not found
    try:
        dealer = Dealer(
            name=dealer_name,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        dealer.save()

        dealer_id = dealer.dealer_id
        print(f"Created new dealer with ID: {dealer_id}")

        # Update cache
        _dealer_cache[cache_key] = dealer_id
        return dealer_id

    except Exception as e:
        print(f"Error creating dealer: {str(e)}")
        raise e

def clear_dealer_cache():
    """Clear the dealer cache - useful for testing"""
    global _dealer_cache
    _dealer_cache = {}
    print("Dealer cache cleared")