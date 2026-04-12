# -*- encoding: utf-8 -*-
"""
Order state constants.

Uses str as the enum mixin so:
    OrderStatus.OPEN == 'Open'  →  True

This means all existing DB queries that pass an OrderStatus value where a
plain string is expected continue to work without any query changes.
"""

from enum import Enum


class OrderStatus(str, Enum):
    OPEN                = 'Open'
    PICKING             = 'Picking'
    PACKED              = 'Packed'
    INVOICED            = 'Invoiced'
    DISPATCH_READY      = 'Dispatch Ready'
    COMPLETED           = 'Completed'
    PARTIALLY_COMPLETED = 'Partially Completed'

    # ── Convenience helpers ────────────────────────────────────────────────

    @classmethod
    def from_frontend_slug(cls, slug: str) -> 'OrderStatus':
        """
        Convert a frontend URL-style slug to an OrderStatus.

        Examples:
            'open'                → OrderStatus.OPEN
            'dispatch-ready'      → OrderStatus.DISPATCH_READY
            'partially-completed' → OrderStatus.PARTIALLY_COMPLETED
        """
        _map: dict[str, 'OrderStatus'] = {
            'open':                cls.OPEN,
            'picking':             cls.PICKING,
            'packed':              cls.PACKED,
            'invoiced':            cls.INVOICED,
            'dispatch-ready':      cls.DISPATCH_READY,
            'completed':           cls.COMPLETED,
            'partially-completed': cls.PARTIALLY_COMPLETED,
        }
        result = _map.get(slug.lower())
        if result is None:
            raise ValueError(f"Unknown frontend status slug: {slug!r}")
        return result

    def to_frontend_slug(self) -> str:
        """'Dispatch Ready' → 'dispatch-ready'"""
        return self.value.lower().replace(' ', '-')
