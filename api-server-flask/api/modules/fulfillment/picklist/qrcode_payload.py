# -*- encoding: utf-8 -*-
"""The string that goes in the QR code, and the token inside it.

Payload shape (v1):

    PL1*30305-02-PSAO-0826-32338*30305-02-DLR-0225-7*7QXMK2R9NTVB4HJC
     |            |                       |                 |
     |            |                       |                 qr_token
     |            |                       picklist_code
     |            original_order_id
     format version

The order number and pick-list code are in the payload so a scan is self-describing
and a mis-scan can be diagnosed from the raw string alone. They are NOT what the
server looks the pick list up by — see parse()'s docstring. The token is.

`*` is the separator rather than the more obvious `|` because QR's alphanumeric
mode covers only 0-9 A-Z space and $%*+-./: — a pipe would force the denser payload
into byte mode and grow the symbol for nothing.
"""

import re
import secrets

PREFIX = 'PL1'
SEP = '*'

# Crockford base32: no I, L, O or U, so nothing in a hand-typed fallback can be
# confused with 1 or 0. 16 chars x 5 bits = 80 bits.
_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
TOKEN_LENGTH = 16

# The QR alphanumeric character set, minus the separator. A field containing anything
# outside this still encodes fine (reportlab falls back to byte mode), but a field
# containing SEP would break parsing, so that one is rejected outright.
_QR_ALNUM = re.compile(r'^[0-9A-Z $%+\-./:]*$')


class PayloadError(ValueError):
    """The scanned string is not a pick-list QR payload this version understands."""


def new_token() -> str:
    """A fresh 80-bit token. secrets, never random — see schema.py."""
    return ''.join(secrets.choice(_ALPHABET) for _ in range(TOKEN_LENGTH))


def build(original_order_id: str, picklist_code: str, qr_token: str) -> str:
    """Render the payload that gets drawn into the QR symbol.

    Raises PayloadError if a field contains the separator, which would make the
    payload ambiguous to parse.
    """
    order_no = (original_order_id or '').strip().upper()
    code = (picklist_code or '').strip().upper()

    for label, value in (('order number', order_no), ('pick-list code', code)):
        if SEP in value:
            raise PayloadError(f"{label} contains {SEP!r}, which is the payload separator")

    return SEP.join((PREFIX, order_no, code, qr_token))


def is_qr_safe(value: str) -> bool:
    """True when `value` stays inside QR alphanumeric mode (keeps the symbol small)."""
    return bool(_QR_ALNUM.match((value or '').strip().upper()))


def parse(payload: str) -> dict:
    """Split a scanned payload into its fields.

    Returns {'order_no', 'picklist_code', 'token'}.

    What the caller does with these matters more than the parse: the pick list must
    be fetched by `token` and `order_no` compared against the row that comes back.
    Looking the row up by `order_no` instead would make the token decorative, and
    anyone able to read an order number off a printed sheet could move that order.
    """
    if not payload:
        raise PayloadError("empty payload")

    text = payload.strip().upper()
    parts = text.split(SEP)

    if len(parts) != 4:
        raise PayloadError(f"expected 4 {SEP!r}-separated fields, got {len(parts)}")
    if parts[0] != PREFIX:
        raise PayloadError(f"unknown payload format {parts[0]!r} (expected {PREFIX!r})")

    _, order_no, picklist_code, token = parts

    if not order_no:
        raise PayloadError("payload carries no order number")
    if len(token) != TOKEN_LENGTH or any(c not in _ALPHABET for c in token):
        raise PayloadError("payload carries no valid token")

    return {'order_no': order_no, 'picklist_code': picklist_code, 'token': token}
