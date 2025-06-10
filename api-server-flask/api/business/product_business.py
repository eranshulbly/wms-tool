# -*- encoding: utf-8 -*-
"""
FIXED: Product Business Logic for MySQL
"""

from datetime import datetime
from ..models import (
    Dealer, Product, PotentialOrder, PotentialOrderProduct,
    OrderState, OrderStateHistory, Invoice, mysql_manager
)

# Cache to avoid repeated database lookups
_product_cache = {}


def get_or_create_product(product_id, product_description):
    """
    Get an existing product or create a new one - MySQL implementation

    Args:
        product_id: ID of the product (product string)
        product_description: Description of the product

    Returns:
        int: Product database ID (primary key)
    """
    # Normalize product data
    product_id = str(product_id).strip() if product_id else ''
    product_description = str(product_description).strip() if product_description else ''

    if not product_id:
        raise ValueError("Product ID cannot be empty")

    print(f"Getting or creating product: {product_id}")

    # Check cache first
    cache_key = product_id.lower()
    if cache_key in _product_cache:
        print(f"Found product in cache: {_product_cache[cache_key]}")
        return _product_cache[cache_key]

    # Try to find by product_string in database
    try:
        product = Product.find_by_product_string(product_id)
        if product:
            print(f"Found existing product: {product.product_id}")
            # Update cache
            _product_cache[cache_key] = product.product_id
            return product.product_id

    except Exception as e:
        print(f"Error querying for product: {str(e)}")

    # Create new product if not found
    try:
        # Use product_description as name if available, otherwise use product_id
        product_name = product_description if product_description else product_id

        product = Product(
            product_string=product_id,
            name=product_name,
            description=product_description,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        product.save()

        product_db_id = product.product_id
        print(f"Created new product with ID: {product_db_id}")

        # Update cache
        _product_cache[cache_key] = product_db_id
        return product_db_id

    except Exception as e:
        print(f"Error creating product: {str(e)}")
        raise e

def clear_product_cache():
    """Clear the product cache - useful for testing"""
    global _product_cache
    _product_cache = {}
    print("Product cache cleared")