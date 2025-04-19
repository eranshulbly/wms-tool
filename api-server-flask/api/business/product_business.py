# -*- encoding: utf-8 -*-
"""
Product Business Logic
"""

from datetime import datetime
from ..models import db, Product

# Cache to avoid repeated database lookups
_product_cache = {}


def get_or_create_product(product_id, product_description):
    """
    Get an existing product or create a new one

    Args:
        product_id: ID of the product
        product_description: Description of the product

    Returns:
        int: Product ID
    """
    # Check cache first
    if product_id in _product_cache:
        return _product_cache[product_id]

    # Try to find by ID
    product = db.session.query(Product).filter(Product.product_string == product_id).first()

    if not product:
        # Create new product with current timestamp
        current_time = datetime.utcnow()
        product = Product(
            product_string=product_id,
            name=product_description,
            description=product_description,
            created_at=current_time,
            updated_at=current_time
        )
        # Add to session but don't commit - the transaction is managed at the service level
        db.session.add(product)
        db.session.flush()  # This assigns the ID without committing

    # Update cache
    _product_cache[product_id] = product.product_id

    return product.product_id