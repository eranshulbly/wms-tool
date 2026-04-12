# -*- encoding: utf-8 -*-
"""
Product Upload Service — extends BaseUploadService for the Template Method pipeline.

Backward-compatible module-level function kept so existing route calls
(product_service.process_product_upload(...)) require no changes.
"""

from ..business.product_upload_business import process_product_upload_dataframe
from ..core.logging import get_logger
from .base_upload_service import BaseUploadService

logger = get_logger(__name__)


class ProductUploadService(BaseUploadService):
    """Upload service for product files."""

    upload_type = 'products'
    required_columns = ['Order #', 'Part #', 'Part Description', 'Reserved Qty']

    def process_dataframe(self, df, context: dict) -> dict:
        result = process_product_upload_dataframe(
            df,
            context.get('company_id'),
            context['user_id'],
            context['upload_batch_id'],
        )
        return {
            'processed_count': result['products_processed'],
            'error_rows': result['error_rows'],
            'orders_updated': result['orders_updated'],
        }


# ── Backward-compatible shim ──────────────────────────────────────────────────

_service = ProductUploadService()


def process_product_upload(uploaded_file, company_id, user_id):
    """Process an uploaded product file. Returns (result_dict, http_status_code)."""
    return _service.execute(
        uploaded_file,
        # warehouse_id is not applicable for product uploads; base service calls .get() safely
        {'company_id': company_id, 'user_id': user_id},
    )
