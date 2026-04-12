# -*- encoding: utf-8 -*-
"""
Order-related validators.
"""


def validate_warehouse_exists(warehouse_id):
    """
    Verify the warehouse exists in the database.

    Returns:
        (True, None)                                 — warehouse found
        (False, (response_dict, http_status_code))   — not found
    """
    from ..models import Warehouse
    warehouse = Warehouse.get_by_id(warehouse_id)
    if not warehouse:
        return False, (
            {
                'success': False,
                'msg': f'Warehouse with ID {warehouse_id} not found',
                'processed_count': 0,
                'error_count': 0,
            },
            400,
        )
    return True, None


def validate_company_exists(company_id):
    """
    Verify the company exists in the database.

    Returns:
        (True, None)                                 — company found
        (False, (response_dict, http_status_code))   — not found
    """
    from ..models import Company
    company = Company.get_by_id(company_id)
    if not company:
        return False, (
            {
                'success': False,
                'msg': f'Company with ID {company_id} not found',
                'processed_count': 0,
                'error_count': 0,
            },
            400,
        )
    return True, None
