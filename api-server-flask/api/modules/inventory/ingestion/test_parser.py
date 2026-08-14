# -*- encoding: utf-8 -*-
"""Regression tests for the supplier PDF parser.

Run against a directory of real supplier PDFs:

    INGESTION_PDF_DIR=~/Downloads python3 -m pytest api/modules/inventory/ingestion/test_parser.py -v

The corpus is NOT committed — the documents are commercial paperwork. Without the
directory the corpus tests skip and only the pure-function tests run.

What the corpus test actually guards is the arithmetic. The parser derives every rate
from the printed amount, so `rate * quantity` must reproduce that amount on every line;
if a future template change shifts a column, this is what catches it, because a shifted
column breaks the reconciliation long before it looks wrong to a human.
"""

import glob
import os
from datetime import date

import pytest

from api.modules.inventory.ingestion.parser import parse_pdf, parse_expiry, ParseError

CORPUS = os.path.expanduser(os.environ.get('INGESTION_PDF_DIR', ''))
PDFS = sorted(glob.glob(os.path.join(CORPUS, '*.pdf'))) if CORPUS else []
needs_corpus = pytest.mark.skipif(not PDFS, reason='set INGESTION_PDF_DIR to a folder of supplier PDFs')


# ── Pure functions ───────────────────────────────────────────────────────────
@pytest.mark.parametrize('raw,expected', [
    ('3/28', date(2028, 3, 31)),      # month-end, not month-start
    ('5/29', date(2029, 5, 31)),
    ('2/28', date(2028, 2, 29)),      # leap year
    ('12/26', date(2026, 12, 31)),
    ('', None),
    ('13/28', None),                  # not a month
    ('garbage', None),
])
def test_parse_expiry(raw, expected):
    assert parse_expiry(raw) == expected


# ── Corpus ───────────────────────────────────────────────────────────────────
@needs_corpus
@pytest.mark.parametrize('path', PDFS, ids=os.path.basename)
def test_document_parses_and_reconciles(path):
    doc = parse_pdf(path, os.path.basename(path))

    assert doc['doc_type'] in ('GRN', 'CN', 'DN')
    assert doc['doc_number']
    assert doc['lines'], 'no line items extracted'

    for line in doc['lines']:
        # The derived rate must reproduce the printed amount. This is the check that
        # fails first if a column shifts.
        if line['quantity']:
            assert abs(line['rate'] * line['quantity'] - line['amount']) <= 0.02, (
                f"line {line['line_no']}: {line['rate']} x {line['quantity']} "
                f"!= {line['amount']}")
        # A batch with an unreadable expiry would silently break FEFO.
        if line['raw_expiry']:
            assert line['expiry_date'] is not None, (
                f"line {line['line_no']}: expiry {line['raw_expiry']!r} not parsed")

    assert abs(sum(l['amount'] for l in doc['lines']) - doc['subtotal']) < 0.05


@needs_corpus
def test_watermark_does_not_leak_into_values():
    """The template's diagonal watermark must not survive into extracted text.

    Its characters land inside table cells, so if the filter regresses they reappear as
    single-character segments and shift every later value onto the wrong product.
    """
    for path in PDFS:
        doc = parse_pdf(path, os.path.basename(path))
        for line in doc['lines']:
            assert len(line['raw_product_name']) > 1, f'{path}: watermark leak'
            assert '\n' not in line['raw_batch']


@needs_corpus
def test_credit_notes_carry_no_mrp():
    """Documented assumption behind excluding MRP from batch identity.

    Notes print MRP 0.00 while naming the batch they adjust. If a note ever arrives with
    a real MRP this assumption needs revisiting — hence the assertion rather than a
    comment.
    """
    seen = False
    for path in PDFS:
        doc = parse_pdf(path, os.path.basename(path))
        if doc['doc_type'] in ('CN', 'DN'):
            seen = True
            assert all(l['mrp'] == 0 for l in doc['lines']), (
                f"{path}: a note carries a non-zero MRP — batch identity assumption "
                f"in service.batch_hash needs review")
    if not seen:
        pytest.skip('no credit/debit notes in corpus')


def test_rejects_non_pdf(tmp_path):
    junk = tmp_path / 'not.pdf'
    junk.write_bytes(b'this is not a pdf')
    with pytest.raises(Exception):
        parse_pdf(str(junk), 'not.pdf')
