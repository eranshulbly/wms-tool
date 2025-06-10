# -*- encoding: utf-8 -*-
"""
FIXED: Order Business Logic for MySQL
"""

from datetime import datetime
from ..models import (
    Dealer, Product, PotentialOrder, PotentialOrderProduct,
    OrderState, OrderStateHistory, Invoice, mysql_manager
)
from . import dealer_business, product_business


def process_order_dataframe(df, warehouse_id, company_id, user_id):
    """
    Process a dataframe of order data - MySQL implementation

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

    print(f"Processing DataFrame with {len(df)} rows")
    print(f"DataFrame columns: {df.columns.tolist()}")

    # Process each row in the dataframe
    for index, row in df.iterrows():
        try:
            print(f"Processing row {index}: {dict(row)}")

            # Extract data from row with better error handling
            order_id = str(row.get('Order #', ''))
            order_date_str = row.get('Date')
            product_id = str(row.get('Part #', ''))
            product_description = row.get('Part Description', '')
            dealer_name = row.get('Account Name') or row.get('Cash Customer Name')
            dealer_code = row.get('Code', '')
            dealer_last_name = row.get('Contact Last Name', '')

            # Handle quantity conversion with error checking
            try:
                order_quantity = int(float(row.get('Order Quantity', 0)))
            except (ValueError, TypeError):
                order_quantity = 0

            try:
                reserved_quantity = int(float(row.get('Reserved Qty', 0)))
            except (ValueError, TypeError):
                reserved_quantity = 0

            print(f"Row {index} data: order_id={order_id}, product_id={product_id}, dealer_name={dealer_name}, quantity={order_quantity}")

            # Skip rows with missing critical data
            if not order_id or not product_id:
                errors.append(f"Row {index}: Missing Order # or Part #. Skipping row.")
                continue

            if order_quantity <= 0:
                errors.append(f"Row {index}: Order quantity is 0 or invalid. Skipping row.")
                continue

            # Handle date parsing
            order_date = parse_order_date(order_date_str, index, errors)

            # Get or create dealer
            dealer_id = None
            if dealer_name and dealer_name.strip():
                try:
                    dealer_id = dealer_business.get_or_create_dealer(dealer_name.strip(), dealer_code, dealer_last_name)
                    print(f"Row {index}: Got dealer_id={dealer_id}")
                except Exception as e:
                    errors.append(f"Row {index}: Error creating dealer: {str(e)}")
                    dealer_id = None
            else:
                errors.append(f"Row {index}: No dealer name found. Proceeding without dealer association.")

            # Get or create product
            try:
                product_db_id = product_business.get_or_create_product(product_id.strip(), product_description)
                print(f"Row {index}: Got product_db_id={product_db_id}")
            except Exception as e:
                errors.append(f"Row {index}: Error creating product: {str(e)}")
                continue

            # Create or update order
            if order_id in orders_map:
                potential_order_id = orders_map[order_id]
                print(f"Row {index}: Using existing order {potential_order_id}")
            else:
                try:
                    potential_order_id = create_potential_order(
                        order_id, warehouse_id, company_id, dealer_id, order_date, user_id
                    )
                    orders_map[order_id] = potential_order_id
                    orders_processed += 1
                    print(f"Row {index}: Created new order {potential_order_id}")
                except Exception as e:
                    errors.append(f"Row {index}: Error creating order: {str(e)}")
                    continue

            # Add product to order
            if order_quantity > 0:
                try:
                    add_product_to_order(potential_order_id, product_db_id, order_quantity)
                    products_processed += 1
                    print(f"Row {index}: Added product to order")
                except Exception as e:
                    errors.append(f"Row {index}: Error adding product to order: {str(e)}")
                    continue

        except Exception as e:
            errors.append(f"Row {index}: Unexpected error processing row: {str(e)}")
            print(f"Row {index}: Unexpected error: {str(e)}")
            continue

    print(f"Processing complete: {orders_processed} orders, {products_processed} products, {len(errors)} errors")

    return {
        'orders_processed': orders_processed,
        'products_processed': products_processed,
        'errors': errors
    }

def parse_order_date(order_date_str, row_index, errors):
    """Parse order date from various formats"""
    try:
        if isinstance(order_date_str, str) and order_date_str.strip():
            # Try multiple date formats
            date_formats = ['%Y-%m-%d', '%d/%m/%Y %H:%M:%S %p', '%d/%m/%Y', '%m/%d/%Y']
            for fmt in date_formats:
                try:
                    return datetime.strptime(order_date_str.strip(), fmt)
                except ValueError:
                    continue

            # If none of the formats match, try a more flexible approach
            try:
                from dateutil import parser
                return parser.parse(order_date_str)
            except:
                raise ValueError(f"Unrecognized date format: {order_date_str}")
        else:
            # If it's already a datetime object from pandas or empty
            if hasattr(order_date_str, 'year'):
                return order_date_str
            else:
                return datetime.now()
    except Exception as e:
        errors.append(f"Row {row_index}: Could not parse date '{order_date_str}'. Using current date. Error: {str(e)}")
        return datetime.now()

def create_potential_order(order_id, warehouse_id, company_id, dealer_id, order_date, user_id):
    """Create a new order request - MySQL implementation"""
    # Get current UTC time
    current_time = datetime.utcnow()

    print(f"Creating potential order: order_id={order_id}, warehouse_id={warehouse_id}, company_id={company_id}, dealer_id={dealer_id}")

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

    potential_order.save()
    potential_order_id = potential_order.potential_order_id
    print(f"Created potential order with ID: {potential_order_id}")

    # Create initial order state history
    try:
        # Get or create Open state
        initial_state = OrderState.find_by_name('Open')
        if not initial_state:
            initial_state = OrderState(
                state_name='Open',
                description='Order is open and ready for processing'
            )
            initial_state.save()

        state_history = OrderStateHistory(
            potential_order_id=potential_order_id,
            state_id=initial_state.state_id,
            changed_by=user_id,
            changed_at=current_time
        )
        state_history.save()
        print(f"Created state history for order {potential_order_id}")

    except Exception as e:
        print(f"Error creating state history: {str(e)}")
        # Don't fail the order creation if state history fails

    return potential_order_id

def add_product_to_order(potential_order_id, product_id, quantity):
    """Add a product to an order request - MySQL implementation"""
    current_time = datetime.utcnow()

    print(f"Adding product to order: order_id={potential_order_id}, product_id={product_id}, quantity={quantity}")

    # Check if this product already exists in this order
    existing_product = PotentialOrderProduct.find_by_order_and_product(potential_order_id, product_id)

    if existing_product:
        # Update quantity instead of creating duplicate
        existing_product.quantity += quantity
        existing_product.updated_at = current_time
        existing_product.save()
        print(f"Updated existing product quantity to {existing_product.quantity}")
    else:
        # Create new product order entry
        potential_order_product = PotentialOrderProduct(
            potential_order_id=potential_order_id,
            product_id=product_id,
            quantity=quantity,
            quantity_packed=0,
            quantity_remaining=quantity,
            created_at=current_time,
            updated_at=current_time
        )
        potential_order_product.save()
        print(f"Created new product order entry")