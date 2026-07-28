# -*- encoding: utf-8 -*-
"""
Upload type, user role, and user status constants.

All enums inherit from str so values compare equal to the corresponding
string literals already stored in the database, keeping DB queries unchanged.
"""

from enum import Enum


class UploadType(str, Enum):
    ORDERS   = 'orders'
    INVOICES = 'invoices'
    PRODUCTS = 'products'


class UserRole(str, Enum):
    ADMIN           = 'admin'
    MANAGER         = 'manager'
    WAREHOUSE_STAFF = 'warehouse_staff'
    DISPATCHER      = 'dispatcher'
    VIEWER          = 'viewer'


class UserStatus(str, Enum):
    PENDING = 'pending'
    ACTIVE  = 'active'
    BLOCKED = 'blocked'
