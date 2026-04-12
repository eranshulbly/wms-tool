# -*- encoding: utf-8 -*-
"""
FIXED: Product Business Logic for MySQL
"""

from datetime import datetime
from ..models import Product
from ..core.logging import get_logger

logger = get_logger(__name__)

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

    logger.debug("get_or_create_product", extra={'product_id': product_id})

    # Check cache first
    cache_key = product_id.lower()
    if cache_key in _product_cache:
        logger.debug("Product cache hit", extra={'product_db_id': _product_cache[cache_key]})
        return _product_cache[cache_key]

    # Try to find by product_string in database
    try:
        product = Product.find_by_product_string(product_id)
        if product:
            logger.debug("Found existing product", extra={'product_db_id': product.product_id})
            # Update cache
            _product_cache[cache_key] = product.product_id
            return product.product_id

    except Exception as e:
        logger.warning("Error querying for product", extra={'product_id': product_id, 'error': str(e)})

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
        logger.debug("Created new product", extra={'product_db_id': product_db_id, 'product_string': product_id})

        # Update cache
        _product_cache[cache_key] = product_db_id
        return product_db_id

    except Exception as e:
        logger.exception("Error creating product", extra={'product_id': product_id})
        raise e


def clear_product_cache():
    """Clear the product cache - useful for testing"""
    global _product_cache
    _product_cache = {}
    logger.debug("Product cache cleared")