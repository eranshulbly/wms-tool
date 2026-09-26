# -*- encoding: utf-8 -*-
"""
The scanned code is a structured record, not a SKU.

Two confirmed samples, both 11 `/`-delimited fields:

    single pc  D/GFSG0000604934/FCGS2T438AVJ/14610086000RS     /000001/0000100.00/ABH/1/G/000/00
    full box   D/KH6G0000000344/DCGKM4WNNA4Z/14610086000RS/000200/0095.00/ABF/1/G/000/00HSVG...

Five fields are confirmed against the printed Hero labels: UPI code, part number,
net quantity, MRP and batch. Field 5 is already in BASE UNITS ("NET QUANTITY: 200
NUMBER (200 PACKS X 1 NUMBER)"), so nothing multiplies it.

> **Split on the delimiter and trim. Never slice by byte offset.** The format is
> NOT fixed-width: field 4 is space-padded to 18 in the piece code and unpadded at
> 13 in the box code; field 6 is 10 characters in one and 7 in the other. A parser
> built on the piece sample's offsets silently mis-reads every box code — and
> mis-reading the *quantity* field seals a box against the wrong expected weight,
> which is precisely the failure this module exists to prevent.
> (PACKING_DESIGN.md §6.7, §6.7.6.)

The app parses locally too, because the live weight display cannot wait for a
round trip. This parser is the one that counts: quantity is attacker-supplied the
moment it arrives as a client field, so the server re-derives it from `raw`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from api.modules.fulfillment.packing import constants as C


@dataclass(frozen=True)
class BarcodeFormat:
    """How one company's codes decode. Field numbers are 1-based FIELD INDEXES.

    Frozen because a format is snapshot-like: the parse of a given raw string must
    not change halfway through a batch because something mutated the layout.
    """

    delimiter: str = C.BARCODE_DELIMITER
    field_count: int = C.BARCODE_FIELD_COUNT
    trim_fields: bool = C.BARCODE_TRIM_FIELDS
    product_field: int = C.BARCODE_PRODUCT_FIELD
    quantity_field: int = C.BARCODE_QUANTITY_FIELD
    upi_field: int = C.BARCODE_UPI_FIELD
    serial_field: int = C.BARCODE_SERIAL_FIELD
    batch_field: int = C.BARCODE_BATCH_FIELD
    mrp_field: int = C.BARCODE_MRP_FIELD

    @classmethod
    def from_config(cls) -> "BarcodeFormat":
        """The layout in force for this deployment, read from app config."""
        return cls()

    def as_dict(self) -> dict:
        """The `barcode_format` block of `GET /packing/config`.

        Served rather than compiled into the APK so a new company — or a changed
        layout — is a config push, and so the app and the server decode identically.
        """
        return {
            "delimiter": self.delimiter,
            "field_count": self.field_count,
            "trim_fields": self.trim_fields,
            "product_field": self.product_field,
            "quantity_field": self.quantity_field,
            "upi_field": self.upi_field,
            "serial_field": self.serial_field,
            "batch_field": self.batch_field,
            "mrp_field": self.mrp_field,
        }


@dataclass(frozen=True)
class ParsedCode:
    """One decoded scan. `ok` is False for anything the format does not explain."""

    raw: str
    ok: bool
    product_code: Optional[str] = None
    quantity: int = 0
    serial: Optional[str] = None
    upi: Optional[str] = None
    batch: Optional[str] = None
    mrp: Optional[Decimal] = None
    error: Optional[str] = None

    @property
    def is_intact_carton(self) -> bool:
        """A code declaring several base units is a supplier pack, not a piece.

        There is no pack-level field in the code (§6.7 checked the printed labels),
        so the declared quantity is the only signal — and it is what decides which
        endpoint may accept the scan.
        """
        return self.ok and self.quantity >= C.INTACT_CARTON_MIN_QUANTITY


def _field(parts, index_1based: int, trim: bool) -> Optional[str]:
    """Element `index_1based` of the split, or None when the code is shorter."""
    if index_1based < 1 or index_1based > len(parts):
        return None
    value = parts[index_1based - 1]
    return value.strip() if trim else value


def _as_int(value: Optional[str]) -> Optional[int]:
    """'000200' -> 200. Zero-padded quantities are the norm on these labels."""
    if value is None:
        return None
    try:
        return int(value.lstrip('0') or '0')
    except ValueError:
        return None


def _as_decimal(value: Optional[str]) -> Optional[Decimal]:
    if not value:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def parse(raw: str, fmt: Optional[BarcodeFormat] = None) -> ParsedCode:
    """Decode one scanned string against a company's format.

    Never raises: an undecodable code is a `result: 'unparseable'` on that one scan,
    not a failed batch. A packer whose whole flush was rejected because one trigger
    pull caught a shipping label would lose nineteen good scans with it.
    """
    fmt = fmt or BarcodeFormat.from_config()
    text = (raw or '').strip()
    if not text:
        return ParsedCode(raw=raw or '', ok=False, error="empty code")

    parts = text.split(fmt.delimiter)

    # `>=` rather than `==`: the wholesale sample carries 38 trailing characters
    # after field 11 whose meaning is still unconfirmed (design §9 Q10). Rejecting
    # a code because it carried MORE than the known fields would refuse every real
    # box code, and the fields we read are all positioned before the trailer.
    if len(parts) < fmt.field_count:
        return ParsedCode(
            raw=text, ok=False,
            error=f"expected at least {fmt.field_count} fields, found {len(parts)}",
        )

    product_code = _field(parts, fmt.product_field, fmt.trim_fields)
    if not product_code:
        return ParsedCode(raw=text, ok=False, error="no product code in the expected field")

    quantity = _as_int(_field(parts, fmt.quantity_field, fmt.trim_fields))
    if quantity is None or quantity < 0:
        return ParsedCode(raw=text, ok=False, error="quantity field is not a number")

    return ParsedCode(
        raw=text,
        ok=True,
        product_code=product_code,
        quantity=quantity,
        serial=_field(parts, fmt.serial_field, fmt.trim_fields) or None,
        upi=_field(parts, fmt.upi_field, fmt.trim_fields) or None,
        batch=_field(parts, fmt.batch_field, fmt.trim_fields) or None,
        mrp=_as_decimal(_field(parts, fmt.mrp_field, fmt.trim_fields)),
    )
