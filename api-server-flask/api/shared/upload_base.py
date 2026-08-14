# -*- encoding: utf-8 -*-
"""
BaseUploadService — Template Method pattern for all upload pipelines.

Every upload type (orders, invoices, products) follows the same 8-step skeleton:
  1. Save uploaded file to a temp path
  2. Validate file extension
  3. Parse file into a Pandas DataFrame
  4. Normalise column names and resolve required columns
  5. Create an upload_batches tracking record
  6. Run the domain-specific processing inside a DB transaction
  7. Commit or rollback; update / delete the batch record accordingly
  8. Clean up the temp file and return a standardised response

Subclasses override only:
  • upload_type       — string key (e.g. 'orders')
  • required_columns  — list of column names that must exist after fuzzy resolution
  • process_dataframe — domain logic (receives df + context dict, returns result dict)

The backward-compatible module-level function wrappers in each subclass file
mean that existing route calls (order_service.process_order_upload(...)) require
no changes.
"""

import abc
import os

from api.db_manager import mysql_manager
from api.shared.upload_utils import (
    cleanup_temp_file, create_upload_batch, make_upload_response,
    read_upload_file, resolve_required_columns, save_temp_file,
)
from api.core.logging import get_logger

logger = get_logger(__name__)

_SUPPORTED_EXTENSIONS = ('.csv', '.xls', '.xlsx', '.pdf')

# PDFs arrive on a fixed supplier template rather than as operator-authored sheets, so
# they are rendered into the same column shape the spreadsheet feeds use (see
# shared/pdf_upload_adapter). Every rule downstream of parsing is therefore unchanged.
_PDF_EXTENSION = '.pdf'


class BaseUploadService(abc.ABC):
    """Abstract base for all upload services."""

    # ── Subclass contract ─────────────────────────────────────────────────────

    @property
    @abc.abstractmethod
    def upload_type(self) -> str:
        """Upload type key stored in upload_batches.upload_type (e.g. 'orders')."""

    @property
    @abc.abstractmethod
    def required_columns(self) -> list:
        """Column names that must be present after fuzzy resolution."""

    def before_processing(self, df, context: dict):
        """Optional gate, run after parsing and before ANY write.

        Return None to continue, or a (response_dict, status_code) tuple to stop. Use it
        to ask the operator something the file cannot answer — nothing has been written at
        this point, so declining costs nothing and leaves no partial upload behind.

        `df` may be modified in place; the modified frame is what gets processed.
        """
        return None

    @abc.abstractmethod
    def process_dataframe(self, df, context: dict) -> dict:
        """
        Domain-specific processing.

        Args:
            df:      Normalised Pandas DataFrame.
            context: Dict with keys: warehouse_id, company_id (optional),
                     user_id, upload_batch_id.

        Returns:
            Dict that MUST contain:
                processed_count (int)   — rows successfully committed
                error_rows      (list)  — list of {'order_id', 'name', 'reason'}
            May also contain any extra keys forwarded to make_upload_response().
        """

    # ── Template method ───────────────────────────────────────────────────────

    def execute(self, uploaded_file, context: dict) -> tuple:
        """
        Run the full 8-step pipeline.

        Args:
            uploaded_file: Werkzeug FileStorage object from the request.
            context:       Dict with at minimum {'user_id'} and optionally
                           {'warehouse_id', 'company_id'}.

        Returns:
            (response_dict, http_status_code)
        """
        temp_path = None
        upload_batch_id = None

        try:
            # Step 1 — save to temp
            temp_path, ext = save_temp_file(uploaded_file, self._tmp_dir())

            # Step 2 — validate extension
            if ext not in _SUPPORTED_EXTENSIONS:
                return {
                    'success': False,
                    'msg': 'Unsupported file format. Please upload a CSV, Excel or PDF file.',
                    'processed_count': 0, 'error_count': 0,
                }, 400

            # Step 3 — parse
            if ext == _PDF_EXTENSION:
                from api.shared.pdf_upload_adapter import pdf_to_dataframe
                from api.modules.inventory.ingestion.parser import ParseError
                try:
                    df = pdf_to_dataframe(temp_path, context.get('company_id'),
                                          upload_type=self.upload_type)
                except ParseError as e:
                    # The template did not match. Refusing beats reading a money column
                    # from the wrong place, so the operator is told rather than the file
                    # being half-imported.
                    return {'success': False, 'msg': f'Could not read this PDF: {e}',
                            'processed_count': 0, 'error_count': 0}, 400
            else:
                df = read_upload_file(temp_path, ext)
            df = df.dropna(how='all')

            # Step 4 — normalise columns + resolve required
            df.columns = df.columns.str.replace('\n', ' ').str.replace('\r', ' ').str.strip()
            df, error = resolve_required_columns(df, self.required_columns)
            if error:
                return {'success': False, 'msg': error, 'processed_count': 0, 'error_count': 0}, 400

            # Step 4b — let the subclass inspect the file before anything is written.
            # Returning a response here aborts the upload having touched nothing: no
            # upload_batches row, no rows, nothing to undo. That is what makes it safe to
            # ask the operator a question and have them decline.
            interrupt = self.before_processing(df, context)
            if interrupt is not None:
                cleanup_temp_file(temp_path)
                return interrupt

            # Step 5 — create batch record
            upload_batch_id = create_upload_batch(
                mysql_manager,
                self.upload_type,
                uploaded_file.filename,
                context.get('warehouse_id'),
                context.get('company_id'),
                context['user_id'],
            )
            context = {**context, 'upload_batch_id': upload_batch_id}

            # Step 6+7 — run in transaction
            result = self._run_in_transaction(df, context, upload_batch_id)

            # Step 8 — cleanup + respond
            cleanup_temp_file(temp_path)
            extra = {k: v for k, v in result.items()
                     if k not in ('processed_count', 'error_rows')}
            extra.setdefault('upload_batch_id', upload_batch_id)
            return make_upload_response(result['processed_count'], result['error_rows'], **extra)

        except Exception as e:
            logger.exception("Upload pipeline error", extra={'upload_type': self.upload_type})
            cleanup_temp_file(temp_path)
            self._delete_batch(upload_batch_id)
            return {
                'success': False,
                'msg': f'Error processing file: {str(e)}',
                'processed_count': 0, 'error_count': 0,
            }, 400

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _run_in_transaction(self, df, context: dict, upload_batch_id) -> dict:
        """Wraps process_dataframe in a DB transaction; commits or rolls back."""
        try:
            with mysql_manager.get_cursor(commit=False) as cursor:
                result = self.process_dataframe(df, context)
                processed = result.get('processed_count', 0)

                if processed > 0:
                    cursor.connection.commit()
                    if upload_batch_id:
                        mysql_manager.execute_query(
                            "UPDATE upload_batches SET record_count=%s WHERE id=%s",
                            (processed, upload_batch_id), fetch=False
                        )
                else:
                    cursor.connection.rollback()
                    self._delete_batch(upload_batch_id)

                return result

        except Exception as db_error:
            self._delete_batch(upload_batch_id)
            raise db_error

    def _delete_batch(self, upload_batch_id) -> None:
        """Best-effort deletion of an incomplete upload_batches record."""
        if not upload_batch_id:
            return
        try:
            mysql_manager.execute_query(
                "DELETE FROM upload_batches WHERE id=%s", (upload_batch_id,), fetch=False
            )
        except Exception:
            pass

    def _tmp_dir(self) -> str:
        return os.path.join(os.path.dirname(os.path.realpath(__file__)), 'tmp')
