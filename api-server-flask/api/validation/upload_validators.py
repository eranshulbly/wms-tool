# -*- encoding: utf-8 -*-
"""
Upload-related validators.
"""

import os


def validate_warehouse_company_access(current_user, warehouse_id, company_id):
    """
    Check that the current user can access the given warehouse+company combination.

    Returns:
        (True, None)                                 — access granted
        (False, (response_dict, http_status_code))   — access denied
    """
    from ..permissions import has_all_warehouse_access
    if not has_all_warehouse_access(current_user.role):
        from ..models import UserWarehouseCompany
        if not UserWarehouseCompany.user_can_access(current_user.id, warehouse_id, company_id):
            return False, (
                {
                    'success': False,
                    'msg': 'You do not have access to this warehouse/company combination.',
                    'processed_count': 0,
                    'error_count': 0,
                },
                403,
            )
    return True, None


def validate_file_extension(filename, supported=('.csv', '.xls', '.xlsx')):
    """
    Check that the uploaded file has a supported extension.

    Returns:
        (True, None)                                 — extension OK
        (False, (response_dict, http_status_code))   — unsupported format
    """
    ext = os.path.splitext(filename or '')[1].lower()
    if ext not in supported:
        return False, (
            {
                'success': False,
                'msg': f'Unsupported file format "{ext}". Accepted: {", ".join(supported)}',
                'processed_count': 0,
                'error_count': 0,
            },
            400,
        )
    return True, None
