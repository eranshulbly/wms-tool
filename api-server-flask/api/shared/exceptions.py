# -*- encoding: utf-8 -*-
"""
Custom exception hierarchy for the WMS API.

All exceptions carry an http_status so route handlers can do a single
generic catch:

    except WMSException as e:
        return {'success': False, 'msg': e.message}, e.http_status

Hierarchy:

    WMSException
    ├── DatabaseException
    │   ├── ConnectionException
    │   └── QueryException
    ├── BusinessRuleException
    │   ├── InvalidStateTransitionException
    │   ├── OrderNotFoundException
    │   └── DuplicateOrderException
    ├── UploadException
    │   ├── UnsupportedFileFormatException
    │   ├── MissingColumnsException
    │   └── EmptyFileException
    ├── AuthException
    │   ├── TokenExpiredException
    │   ├── TokenRevokedException
    │   └── InsufficientPermissionException
    └── ValidationException
"""


class WMSException(Exception):
    """Base for all application exceptions."""

    def __init__(self, message: str, http_status: int = 500, payload: dict = None):
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.payload = payload or {}

    def to_dict(self) -> dict:
        return {
            'success': False,
            'error': self.__class__.__name__,
            'msg': self.message,
            **self.payload,
        }


# ── Database ──────────────────────────────────────────────────────────────────

class DatabaseException(WMSException):
    def __init__(self, message: str = 'Database operation failed', http_status: int = 500):
        super().__init__(message, http_status)


class ConnectionException(DatabaseException):
    def __init__(self, message: str = 'Could not connect to database'):
        super().__init__(message, 503)


class QueryException(DatabaseException):
    def __init__(self, message: str = 'Database query failed'):
        super().__init__(message, 500)


# ── Business rules ────────────────────────────────────────────────────────────

class BusinessRuleException(WMSException):
    def __init__(self, message: str, http_status: int = 400, payload: dict = None):
        super().__init__(message, http_status, payload)


class InvalidStateTransitionException(BusinessRuleException):
    def __init__(self, current_status: str, target_status: str):
        super().__init__(
            f"Cannot transition order from '{current_status}' to '{target_status}'.",
            http_status=400,
        )
        self.current_status = current_status
        self.target_status = target_status


class OrderNotFoundException(BusinessRuleException):
    def __init__(self, order_id):
        super().__init__(f"Order '{order_id}' not found.", http_status=404)


class DuplicateOrderException(BusinessRuleException):
    def __init__(self, order_id):
        super().__init__(
            f"Order '{order_id}' already exists.",
            http_status=409,
        )


# ── Upload ────────────────────────────────────────────────────────────────────

class UploadException(WMSException):
    def __init__(self, message: str, http_status: int = 400):
        super().__init__(message, http_status)


class UnsupportedFileFormatException(UploadException):
    def __init__(self, ext: str):
        super().__init__(
            f"Unsupported file format '{ext}'. Accepted: .csv, .xls, .xlsx"
        )


class MissingColumnsException(UploadException):
    def __init__(self, missing: list, available: list):
        super().__init__(
            f"Missing required columns: {', '.join(missing)}. "
            f"Available: {', '.join(available)}"
        )
        self.missing = missing
        self.available = available


class EmptyFileException(UploadException):
    def __init__(self):
        super().__init__("Uploaded file contains no data rows.")


# ── Auth ──────────────────────────────────────────────────────────────────────

class AuthException(WMSException):
    def __init__(self, message: str, http_status: int = 401):
        super().__init__(message, http_status)


class TokenExpiredException(AuthException):
    def __init__(self):
        super().__init__("Token has expired.", 401)


class TokenRevokedException(AuthException):
    def __init__(self):
        super().__init__("Token has been revoked.", 401)


class InsufficientPermissionException(AuthException):
    def __init__(self, action: str = 'perform this action'):
        super().__init__(f"You do not have permission to {action}.", 403)


# ── Validation ────────────────────────────────────────────────────────────────

class ValidationException(WMSException):
    def __init__(self, field: str, message: str):
        super().__init__(
            f"Validation failed for '{field}': {message}",
            http_status=400,
            payload={'field': field, 'detail': message},
        )
        self.field = field
