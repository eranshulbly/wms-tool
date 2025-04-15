# -*- encoding: utf-8 -*-
"""
Dealer Business Logic
"""

from ..models import db, Dealer

# Cache to avoid repeated database lookups
_dealer_cache = {}


def get_or_create_dealer(dealer_name, dealer_code=None, dealer_last_name=None):
    """
    Get an existing dealer or create a new one

    Args:
        dealer_name: Name of the dealer
        dealer_code: Optional dealer code
        dealer_last_name: Optional last name

    Returns:
        int: Dealer ID
    """
    # Check cache first
    if dealer_name in _dealer_cache:
        return _dealer_cache[dealer_name]

    # Try to find by name
    dealer = db.session.query(Dealer).filter(Dealer.name == dealer_name).first()

    if not dealer:
        # Create new dealer
        dealer = Dealer(name=dealer_name)
        dealer.save()

    # Update cache
    _dealer_cache[dealer_name] = dealer.dealer_id

    return dealer.dealer_id