# -*- encoding: utf-8 -*-
"""
Order Business Logic
"""

from datetime import datetime
from ..models import db, PotentialOrder, PotentialOrderProduct, OrderState, OrderStateHistory
from . import dealer_business, product_business


def process_order_dataframe(df, warehouse_id, company_id, user_id):
    """
    Process a dataframe of order data

    Args:
        df: Pandas DataFrame with order data
        warehouse_id: Warehouse ID
        company_id: Company ID
        user_id: ID of the user processing the orders

    Returns:
        dict: Processing results
    """
    orders_processed = 0
    products_processed = 0
    errors = []
    orders_map = {}  # Used to track unique orders

    # Process each row in the dataframe
    for index, row in df.iterrows():
        try:
            # Extract data from row
            order_id = str(row.get('Order #'))
            order_date_str = row.get('Date')
            product_id = str(row.get('Part #'))
            product_description = row.get('Part Description')
            dealer_name = row.get('Account Name') or row.get('Cash Customer Name')
            dealer_code = row.get('Code')
            dealer_last_name = row.get('Contact Last Name')
            order_quantity = int(row.get('Order Quantity', 0))
            reserved_quantity = int(row.get('Reserved Qty', 0))

            # Handle date parsing
            order_date = parse_order_date(order_date_str, index, errors)

            # Get or create dealer
            dealer_id = None
            if dealer_name:
                dealer_id = dealer_business.get_or_create_dealer(dealer_name, dealer_code, dealer_last_name)
            else:
                errors.append(f"Row {index}: No dealer name found. Proceeding without dealer association.")

            # Get or create product
            product_id = product_business.get_or_create_product(product_id, product_description)

            # Create or update order
            if order_id in orders_map:
                potential_order_id = orders_map[order_id]
            else:
                potential_order_id = create_potential_order(
                    order_id, warehouse_id, company_id, dealer_id, order_date, user_id
                )
                orders_map[order_id] = potential_order_id
                orders_processed += 1

            # Add product to order
            if order_quantity > 0:
                add_product_to_order(potential_order_id, product_id, order_quantity)
                products_processed += 1

        except Exception as e:
            errors.append(f"Row {index}: Error processing row: {str(e)}")
            continue

    return {
        'orders_processed': orders_processed,
        'products_processed': products_processed,
        'errors': errors
    }


def parse_order_date(order_date_str, row_index, errors):
    """Parse order date from various formats"""
    try:
        if isinstance(order_date_str, str):
            # Try multiple date formats
            date_formats = ['%Y-%m-%d', '%d/%m/%Y %H:%M:%S %p', '%d/%m/%Y']
            for fmt in date_formats:
                try:
                    return datetime.strptime(order_date_str, fmt)
                except ValueError:
                    continue

            # If none of the formats match, try a more flexible approach
            try:
                from dateutil import parser
                return parser.parse(order_date_str)
            except:
                raise ValueError(f"Unrecognized date format: {order_date_str}")
        else:
            # If it's already a datetime object from pandas
            return order_date_str
    except Exception as e:
        errors.append(f"Row {row_index}: Could not parse date '{order_date_str}'. Using current date. Error: {str(e)}")
        return datetime.now()


def create_potential_order(order_id, warehouse_id, company_id, dealer_id, order_date, user_id):
    """Create a new order request"""
    # Get current UTC time
    current_time = datetime.utcnow()

    # Create new order request
    potential_order = PotentialOrder(
        original_order_id=order_id,
        warehouse_id=warehouse_id,
        company_id=company_id,
        dealer_id=dealer_id,
        order_date=order_date,
        requested_by=user_id,
        status='Open',
        created_at=current_time,
        updated_at=current_time
    )

    # Save without commit - the transaction is managed at the service level
    db.session.add(potential_order)
    db.session.flush()  # This assigns the ID without committing

    # Create initial order state history
    initial_state = db.session.query(OrderState).filter(OrderState.state_name == 'Open').first()
    if initial_state:
        state_history = OrderStateHistory(
            potential_order_id=potential_order.potential_order_id,
            state_id=initial_state.state_id,
            changed_by=user_id,
            changed_at=current_time
        )
        db.session.add(state_history)
        db.session.flush()

    return potential_order.potential_order_id


def add_product_to_order(potential_order_id, product_id, quantity):
    """Add a product to an order request"""
    current_time = datetime.utcnow()

    potential_order_product = PotentialOrderProduct(
        potential_order_id=potential_order_id,
        product_id=product_id,
        quantity=quantity,
        created_at=current_time,
        updated_at=current_time
        # Add price information if available
    )

    # Save without commit - the transaction is managed at the service level
    db.session.add(potential_order_product)
    db.session.flush()