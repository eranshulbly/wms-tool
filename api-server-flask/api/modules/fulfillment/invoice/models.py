# -*- encoding: utf-8 -*-
"""invoice module — data models. This module owns these tables.

Active-record classes over raw SQL (MySQLModel). Boundary rule: other
modules read these through this module's service.py, never by importing
these classes directly.
"""
from datetime import datetime
from api.shared.db_manager import mysql_manager, MySQLModel, partition_filter


class Invoice(MySQLModel):
    """Invoice model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Set all invoice fields from kwargs
        for field in ['invoice_id', 'potential_order_id', 'warehouse_id', 'company_id',
                      'dealer_id', 'invoice_number', 'original_order_id', 'order_date',
                      'account_tin', 'cash_customer_name', 'contact_first_name',
                      'contact_last_name', 'customer_category', 'invoice_date', 'invoice_status',
                      'invoice_type', 'invoice_format', 'part_no', 'part_name', 'uom',
                      'hsn_number', 'product_type', 'product_category', 'quantity',
                      'unit_price', 'line_item_discount_percent', 'line_item_discount',
                      'net_selling_price', 'assessable_value', 'vat_amount', 'cgst_percent',
                      'cgst_amount', 'sgst_percent', 'sgst_amount', 'utgst_percent',
                      'utgst_amount', 'igst_percent', 'igst_amount', 'cess_percent',
                      'cess_amount', 'additional_tax_amt', 'additional_tax_amt2',
                      'additional_tax_amt3', 'additional_tax_amt4', 'additional_tax_amt5',
                      'freight_amount', 'packaging_charges', 'frt_pkg_cgst_percent',
                      'frt_pkg_cgst_amount', 'frt_pkg_sgst_percent', 'frt_pkg_sgst_amount',
                      'frt_pkg_igst_percent', 'frt_pkg_igst_amount', 'frt_pkg_cess_percent',
                      'frt_pkg_cess_amount', 'total_invoice_amount', 'additional_discount_percent',
                      'cash_discount_percent', 'credit_days', 'state', 'state_code', 'gstin',
                      'record_updated_dt', 'login', 'voucher', 'type_field', 'parent',
                      'sale_return_date', 'narration', 'cancellation_date', 'executive_name',
                      'round_off_amount', 'invoice_round_off_amount', 'short_amount',
                      'realized_amount', 'hmcgl_card_no', 'campaign',
                      'b2b_purchase_order_number', 'b2b_order_type', 'invoice_header_type',
                      'packaging_forwarding_charges', 'tax_on_pf', 'type_of_tax_pf',
                      'irn_number', 'irn_status', 'ack_number', 'ack_date',
                      'credit_note_number', 'irn_cancel', 'irn_status_cancel',
                      'ack_number_cancel', 'ack_date_cancel',
                      'uploaded_by', 'upload_batch_id', 'created_at', 'updated_at']:
            setattr(self, field, kwargs.get(field))

    def save(self):
        """Save invoice"""
        # This is a complex insert - using a dictionary approach
        fields = [k for k in self.__dict__.keys() if not k.startswith('_') and getattr(self, k) is not None]
        values = [getattr(self, field) for field in fields]
        placeholders = ', '.join(['%s'] * len(fields))
        field_names = ', '.join(fields)

        with mysql_manager.get_cursor() as cursor:
            sql = f"INSERT INTO invoice ({field_names}) VALUES ({placeholders})"
            cursor.execute(sql, values)
            self.invoice_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, invoice_id):
        """Get invoice by ID"""
        pf_sql, pf_params = partition_filter('invoice')
        result = mysql_manager.execute_query(
            f"SELECT * FROM invoice WHERE {pf_sql} AND invoice_id = %s",
            pf_params + (invoice_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def get_statistics(cls, warehouse_id=None, company_ids=None, batch_id=None):
        """Get invoice statistics (active window only).

        `company_ids` is the caller's resolved tenant scope, not a request parameter.
        Currently unused by any route — kept tenant-safe so wiring it up later cannot
        reintroduce an unfiltered read.
        """
        from api.permissions import company_filter_sql
        pf_sql, pf_params = partition_filter('invoice')
        cf_sql, cf_params = company_filter_sql(company_ids)
        base_query = (f"SELECT COUNT(*) as total_invoices FROM invoice "
                      f"WHERE {pf_sql} AND {cf_sql}")
        params = list(pf_params) + list(cf_params)

        if warehouse_id:
            base_query += " AND warehouse_id = %s"
            params.append(warehouse_id)

        if batch_id:
            base_query += " AND upload_batch_id = %s"
            params.append(batch_id)

        total_result = mysql_manager.execute_query(base_query, params)
        total_invoices = total_result[0]['total_invoices'] if total_result else 0

        # Get unique orders
        unique_query = base_query.replace("COUNT(*)", "COUNT(DISTINCT potential_order_id)")
        unique_result = mysql_manager.execute_query(unique_query, params)
        unique_orders = unique_result[0]['COUNT(DISTINCT potential_order_id)'] if unique_result else 0

        # Get total amount
        amount_query = base_query.replace("COUNT(*)", "SUM(total_invoice_amount)")
        amount_result = mysql_manager.execute_query(amount_query, params)
        total_amount = amount_result[0]['SUM(total_invoice_amount)'] if amount_result else 0

        return {
            'total_invoices': total_invoices,
            'unique_orders': unique_orders,
            'total_amount': float(total_amount or 0)
        }


class InvoiceProcessingConfig(MySQLModel):
    """
    Generic key-value configuration for invoice processing rules.

    Current keys:
      bypass_order_type — order_type values whose orders skip the Packed
                          prerequisite and go directly to Invoiced on invoice
                          upload (e.g. 'ZGOI').
    """

    # Simple in-process cache: {config_key -> [value, ...]}
    _cache: dict = {}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = kwargs.get('id')
        self.config_key = kwargs.get('config_key')
        self.config_value = kwargs.get('config_value')
        self.description = kwargs.get('description')
        self.is_active = bool(kwargs.get('is_active', True))

    @classmethod
    def get_values(cls, config_key: str) -> list:
        """Return all active config_values for a given config_key.

        Results are cached in-process for the lifetime of the worker.
        Call invalidate_cache() if values are mutated at runtime.
        """
        if config_key not in cls._cache:
            rows = mysql_manager.execute_query(
                "SELECT config_value FROM invoice_processing_config "
                "WHERE config_key = %s AND is_active = 1",
                (config_key,)
            )
            cls._cache[config_key] = [r['config_value'] for r in rows] if rows else []
        return cls._cache[config_key]

    @classmethod
    def get_bypass_order_types(cls) -> set:
        """Return the set of order_type values that bypass the Packed prerequisite."""
        return set(cls.get_values('bypass_order_type'))

    @classmethod
    def get_complete_on_invoice_types(cls) -> set:
        """order_type values the invoice upload closes outright.

        For these the invoice IS the sale: there is no pick/pack step, so the upload takes
        the stock out of the invoiced batches and moves the order straight to Completed.
        """
        return set(cls.get_values('complete_on_invoice_type'))

    @classmethod
    def invalidate_cache(cls, config_key: str = None):
        """Clear cached values (call after mutating config rows)."""
        if config_key:
            cls._cache.pop(config_key, None)
        else:
            cls._cache.clear()

