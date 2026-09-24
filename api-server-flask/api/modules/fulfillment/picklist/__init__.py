# -*- encoding: utf-8 -*-
"""picklist module — ingest warehouse pick-list PDFs and reprint them with a QR code.

A pick list is a document the DMS prints for an order that is already in
potential_order. Uploading one does NOT create or move an order: it attaches the
document to the order it names, fills in that order's line items, and mints a QR
token. Scanning the QR later is what moves the order.

The uploaded PDF is not kept. Everything needed to redraw the page is captured in
order_picklist.meta, and pdf.py rebuilds it on demand with the QR added — so a
download always reflects one code path rather than a mix of original and stamped
files.
"""
