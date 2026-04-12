# -*- encoding: utf-8 -*-
"""
UploadProcessorFactory — returns the correct BaseUploadService subclass for a given
upload type key.

Usage:
    from .upload_factory import UploadProcessorFactory

    service = UploadProcessorFactory.get('orders')
    response, status = service.execute(uploaded_file, context)
"""

from ..constants.upload_types import UploadType
from .base_upload_service import BaseUploadService


class UploadProcessorFactory:
    """Factory that maps UploadType values to their service implementations."""

    @staticmethod
    def get(upload_type) -> BaseUploadService:
        """
        Return a new instance of the upload service for *upload_type*.

        Args:
            upload_type: An UploadType enum member or its string value
                         (e.g. UploadType.ORDERS or 'orders').

        Raises:
            KeyError: If upload_type is not registered.
        """
        # Import here to avoid circular imports at module load time
        from .order_service import OrderUploadService
        from .invoice_service import InvoiceUploadService
        from .product_service import ProductUploadService

        registry = {
            UploadType.ORDERS:   OrderUploadService,
            UploadType.INVOICES: InvoiceUploadService,
            UploadType.PRODUCTS: ProductUploadService,
        }

        # Allow lookup by string value as well as by enum member
        if not isinstance(upload_type, UploadType):
            upload_type = UploadType(upload_type)

        return registry[upload_type]()
