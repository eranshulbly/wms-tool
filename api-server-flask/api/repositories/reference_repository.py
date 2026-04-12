# -*- encoding: utf-8 -*-
"""
ReferenceRepository — SQL for read-mostly reference tables:
  Warehouse, Company, Dealer.

Additive in Phase 4; route handlers still call model classmethods directly
and will migrate to this repository in Phase 5-6.
"""

from ..core.logging import get_logger
from .base_repository import BaseRepository

logger = get_logger(__name__)


class ReferenceRepository(BaseRepository):
    """Data access layer for warehouse / company / dealer reference data."""

    # ── Warehouse ─────────────────────────────────────────────────────────────

    def get_all_warehouses(self) -> list:
        """Return all Warehouse instances."""
        from ..models import Warehouse
        return Warehouse.get_all()

    def get_warehouse_by_id(self, warehouse_id: int):
        """Return a Warehouse by primary key, or None."""
        from ..models import Warehouse
        return Warehouse.get_by_id(warehouse_id)

    # ── Company ───────────────────────────────────────────────────────────────

    def get_all_companies(self) -> list:
        """Return all Company instances."""
        from ..models import Company
        return Company.get_all()

    def get_company_by_id(self, company_id: int):
        """Return a Company by primary key, or None."""
        from ..models import Company
        return Company.get_by_id(company_id)

    # ── Dealer ────────────────────────────────────────────────────────────────

    def find_dealer_by_id(self, dealer_id: int):
        """Return a Dealer by primary key, or None."""
        from ..models import Dealer
        return Dealer.get_by_id(dealer_id)

    def find_dealer_by_name(self, name: str):
        """Return a Dealer by name (case-insensitive), or None."""
        from ..models import Dealer
        return Dealer.find_by_name(name)

    def find_dealer_by_code(self, dealer_code: str):
        """Return a Dealer by eway bill code, or None."""
        from ..models import Dealer
        return Dealer.find_by_code(dealer_code)

    def save_dealer(self, dealer) -> None:
        """Persist a Dealer instance (INSERT or UPDATE)."""
        dealer.save()
