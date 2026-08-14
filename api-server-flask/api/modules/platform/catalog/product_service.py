# -*- encoding: utf-8 -*-
"""
Product Upload Service — extends BaseUploadService for the Template Method pipeline.

Backward-compatible module-level function kept so existing route calls
(product_service.process_product_upload(...)) require no changes.
"""

from api.modules.platform.catalog.product_upload_business import (
    process_product_upload_dataframe, rows_missing_part_number, generate_part_numbers,
)
from api.core.logging import get_logger
from api.shared.upload_base import BaseUploadService

logger = get_logger(__name__)


class ProductUploadService(BaseUploadService):
    """Upload service for product files."""

    upload_type = 'products'
    # `Part #` is deliberately NOT required. A catalogue without one is not a broken file,
    # it is a file whose codes can be generated — but only once the operator agrees, since
    # the codes become permanent catalogue identifiers. before_processing runs that ask.
    required_columns = ['Order #', 'Part Description', 'Reserved Qty']

    def before_processing(self, df, context: dict):
        """Stop and ask when part numbers are missing, unless already approved."""
        missing = rows_missing_part_number(df)
        if not missing:
            return None

        if not context.get('auto_generate_part_numbers'):
            # Nothing has been written yet, so declining is a true no-op. The preview
            # shows what WOULD be created, on a copy, so this call generates nothing.
            preview_rows = generate_part_numbers(
                df.copy(), context.get('company_id'), missing[:10])
            logger.info("Product upload awaiting part-number approval",
                        extra={'missing': len(missing), 'total': len(df)})
            return {
                'success': False,
                'needs_approval': 'auto_generate_part_numbers',
                'msg': (f"{len(missing)} of {len(df)} rows have no Part #. "
                        f"Approve to upload with auto-generated product numbers, "
                        f"or reject to cancel — nothing has been saved."),
                'missing_count': len(missing),
                'total_rows': len(df),
                'sample': [{'row': int(i) + 2, 'description': d, 'generated': code}
                           for i, d, code in preview_rows],
                'processed_count': 0,
                'error_count': 0,
            }, 200

        generated = generate_part_numbers(df, context.get('company_id'), missing)
        context['generated_part_numbers'] = len(generated)
        return None

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
            'generated_part_numbers': context.get('generated_part_numbers', 0),
        }


# ── Backward-compatible shim ──────────────────────────────────────────────────

_service = ProductUploadService()


def process_product_upload(uploaded_file, company_id, user_id,
                           auto_generate_part_numbers=False):
    """Process an uploaded product file. Returns (result_dict, http_status_code).

    `auto_generate_part_numbers` is the operator's answer to the approval prompt raised on
    a first attempt; without it a file lacking Part # is refused rather than guessed at.
    """
    return _service.execute(
        uploaded_file,
        # warehouse_id is not applicable for product uploads; base service calls .get() safely
        {'company_id': company_id, 'user_id': user_id,
         'auto_generate_part_numbers': auto_generate_part_numbers},
    )
