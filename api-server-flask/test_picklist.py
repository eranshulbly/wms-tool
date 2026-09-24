# -*- encoding: utf-8 -*-
"""Pick-list QR payload, renderer and extractor.

Run with:  pytest test_picklist.py    (from api-server-flask/)

This test lives at the package root, not beside the module it tests, and stubs the
api.* tree by hand. Both are deliberate: `import api` runs create_app() at module scope
(api/__init__.py:208), which builds the Flask app and issues the schema DDL — so a
plain import would need a live database to test three modules that never touch one.
The tree is stubbed as namespace packages instead; extract, pdf and qrcode_payload
import nothing from `api` beyond the logger.

What this does NOT cover: parsing a PDF produced by the actual DMS. The round-trip
renders with pdf.py and reads back with extract.py, which pins the table geometry,
the header regexes and the QR payload against each other, but a real pick list may
lay its grid out differently. Parse one before trusting the importer in production.
"""

import io
import json
import logging
import os
import sys
import types

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_API_ROOT = _HERE

if _API_ROOT not in sys.path:
    sys.path.insert(0, _API_ROOT)

for _name, _path in [
    ('api', os.path.join(_API_ROOT, 'api')),
    ('api.core', os.path.join(_API_ROOT, 'api', 'core')),
    ('api.modules', os.path.join(_API_ROOT, 'api', 'modules')),
    ('api.modules.fulfillment', os.path.join(_API_ROOT, 'api', 'modules', 'fulfillment')),
    ('api.modules.fulfillment.picklist',
     os.path.join(_API_ROOT, 'api', 'modules', 'fulfillment', 'picklist')),
]:
    if _name not in sys.modules:
        _mod = types.ModuleType(_name)
        _mod.__path__ = [_path]
        sys.modules[_name] = _mod

if 'api.core.logging' not in sys.modules:
    _log = types.ModuleType('api.core.logging')
    _log.get_logger = logging.getLogger
    sys.modules['api.core.logging'] = _log

from api.modules.fulfillment.picklist import extract, pdf, qrcode_payload  # noqa: E402

pdfplumber = pytest.importorskip('pdfplumber')
pytest.importorskip('reportlab')


ORDER_NO = '30305-02-PSAO-0826-32338'
PICKLIST_CODE = '30305-02-DLR-0225-7'

# Lines 1, 3, 4, 5 and 8 of the sample pick list. Line 3 is the one whose part number
# the printer wraps across three lines; line 4 is the only one with two bin locations.
META = {
    'v': 1,
    'header': {
        'distributor_name': 'OM MARKETING',
        'address_lines': [
            'C/O UPSWC, go down no. 58,59 and 60,, Road No.3 ,Opp Bharat Petroleum,,',
            'PARSAKHERA, UP, India, 243122',
        ],
        'state_code': '9',
        'contact': '9837038183',
        'gstin': '09AADFO8472B1Z7',
        'authorized_distributor_of': 'Hero MotoCorp Ltd.',
        'doc_title': 'Pick List',
    },
    'order': {
        'code': PICKLIST_CODE,
        'order_no': ORDER_NO,
        'order_date': '08/07/2026 18:23:55',
        'order_date_iso': '2026-07-08T18:23:55',
        'dealer_name': 'BAWA AUTO SALES',
        'city': 'BALRAMPUR',
    },
    'lines': [
        {'sl': 1, 'bin': ['M4G3', '', ''], 'part': '070HH198012S',
         'desc': 'SOCKET 20-070HH198012S', 'hsn': '82060010', 'moq': 1, 'stock': 0,
         'mrp': '155.00', 'order_qty': 3, 'allocated_qty': 3, 'picked_qty': None},
        {'sl': 3, 'bin': ['BS6', '', ''], 'part': 'ADGAA7Y00100099GS',
         'desc': 'METER ASSEMBLY COMBINATION-ADGAA7Y00100099GS', 'hsn': '87141090',
         'moq': 1, 'stock': 5, 'mrp': '4395.00', 'order_qty': 1, 'allocated_qty': 1,
         'picked_qty': None},
        {'sl': 4, 'bin': ['L9E9', 'L9E10', ''], 'part': '25K170S',
         'desc': 'BALL RACES KIT (ACHR/GLMR)-25K170S', 'hsn': '84821051', 'moq': 50,
         'stock': 683, 'mrp': '475.00', 'order_qty': 12, 'allocated_qty': 12,
         'picked_qty': None},
        {'sl': 5, 'bin': ['K6C6', '', ''], 'part': '31916KPH90099S',
         'desc': 'SPARK PLUG-31916KPH90099S', 'hsn': '85111000', 'moq': 200,
         'stock': 602, 'mrp': '150.00', 'order_qty': 11, 'allocated_qty': 11,
         'picked_qty': None},
        {'sl': 8, 'bin': ['NKF-105', '', ''], 'part': 'AAELE1H000000GS',
         'desc': 'THROTTLE BODY ASSY-AAELE1H000000GS', 'hsn': '84099191', 'moq': 1,
         'stock': 6, 'mrp': '3740.00', 'order_qty': 2, 'allocated_qty': 2,
         'picked_qty': None},
    ],
    'footer_fields': [],
    'source_filename': 'sample.pdf',
    'extracted_at': '2026-09-24T00:00:00Z',
}


def _picklist(token='7QXMK2R9NTVB4HJC'):
    return {'qr_token': token, 'original_order_id': ORDER_NO,
            'picklist_code': PICKLIST_CODE, 'meta': META}


# ── QR payload ───────────────────────────────────────────────────────────────

def test_payload_round_trips():
    token = qrcode_payload.new_token()
    parsed = qrcode_payload.parse(qrcode_payload.build(ORDER_NO, PICKLIST_CODE, token))
    assert parsed == {'order_no': ORDER_NO, 'picklist_code': PICKLIST_CODE,
                      'token': token}


def test_token_is_80_bits_of_crockford_base32():
    tokens = {qrcode_payload.new_token() for _ in range(200)}
    assert len(tokens) == 200, 'tokens must not collide'
    for token in tokens:
        assert len(token) == qrcode_payload.TOKEN_LENGTH
        assert not set(token) & set('ILOU'), 'Crockford base32 excludes I, L, O and U'


def test_payload_stays_in_qr_alphanumeric_mode():
    """Byte mode would grow the symbol; the separator is why it is * and not |."""
    payload = qrcode_payload.build(ORDER_NO, PICKLIST_CODE, qrcode_payload.new_token())
    assert qrcode_payload.is_qr_safe(payload.replace(qrcode_payload.SEP, ''))
    assert len(payload) < 90, 'longer payloads push the symbol past QR version 4'


@pytest.mark.parametrize('bad', [
    '', 'nonsense', 'PL1*a*b', 'PL9*a*b*c', 'PL1**b*7QXMK2R9NTVB4HJC',
    'PL1*a*b*tooshort', 'PL1*a*b*7QXMK2R9NTVB4HJC*extra',
])
def test_bad_payloads_are_rejected(bad):
    with pytest.raises(qrcode_payload.PayloadError):
        qrcode_payload.parse(bad)


def test_separator_in_a_field_is_refused_at_build_time():
    """Better to fail the upload than mint a QR nobody can parse."""
    with pytest.raises(qrcode_payload.PayloadError):
        qrcode_payload.build('ORDER*1', PICKLIST_CODE, qrcode_payload.new_token())


# ── Renderer ─────────────────────────────────────────────────────────────────

def test_columns_fit_the_printable_width():
    """A wider total does not shrink the table, it overflows and cells collide."""
    assert sum(pdf._COL_WIDTHS_MM) <= pdf._PRINTABLE_WIDTH_MM


def test_renders_a_pdf():
    out = pdf.build_pdf([_picklist()])
    assert out[:5] == b'%PDF-'


def test_batch_is_one_document():
    single = pdf.build_pdf([_picklist()])
    batch = pdf.build_pdf([_picklist(), _picklist(), _picklist()])
    assert len(batch) > len(single)
    with pdfplumber.open(io.BytesIO(batch)) as doc:
        assert len(doc.pages) == 3


def test_unknown_meta_version_is_refused():
    """meta.v exists so an extractor change cannot silently mis-draw old pick lists."""
    with pytest.raises(pdf.PicklistRenderError):
        pdf.build_pdf([{'qr_token': '7QXMK2R9NTVB4HJC', 'original_order_id': ORDER_NO,
                        'picklist_code': PICKLIST_CODE, 'meta': {'v': 99}}])


def test_empty_selection_is_refused():
    with pytest.raises(pdf.PicklistRenderError):
        pdf.build_pdf([])


# ── Extractor ────────────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def extracted():
    return extract.extract(io.BytesIO(pdf.build_pdf([_picklist()])), 'roundtrip.pdf')


def test_header_survives_the_round_trip(extracted):
    for key in ('distributor_name', 'gstin', 'state_code', 'contact',
                'authorized_distributor_of'):
        assert extracted['header'][key] == META['header'][key], key


def test_order_block_survives_the_round_trip(extracted):
    for key in ('order_no', 'code', 'dealer_name', 'city', 'order_date_iso'):
        assert extracted['order'][key] == META['order'][key], key


def test_every_line_survives_the_round_trip(extracted):
    assert len(extracted['lines']) == len(META['lines'])
    for got, want in zip(extracted['lines'], META['lines']):
        for key in ('part', 'hsn', 'moq', 'stock', 'mrp', 'order_qty',
                    'allocated_qty', 'bin', 'desc'):
            assert got[key] == want[key], '%s of %s' % (key, want['part'])


def test_wrapped_part_number_is_rejoined():
    """A part number split across lines is one token, never two words."""
    assert extract._join_part('ADGAA7Y0010\n0099GS') == 'ADGAA7Y00100099GS'
    assert extract._join_part('31916KPH90099\nS') == '31916KPH90099S'


def test_description_tail_is_repaired_against_the_part_column():
    assert extract._repair_desc(
        'METER ASSEMBLY COMBINATION- ADGAA7Y00100099 GS', 'ADGAA7Y00100099GS'
    ) == 'METER ASSEMBLY COMBINATION-ADGAA7Y00100099GS'


def test_description_is_left_alone_when_the_tail_is_not_the_part():
    """Only a provable match is rewritten; anything else is reported as printed."""
    assert extract._repair_desc('SOME-OTHER TEXT', 'AAELE1H000000GS') == 'SOME-OTHER TEXT'


def test_mrp_stays_a_string():
    """It is money that gets reprinted verbatim, never summed."""
    assert extract._to_decimal_str('4,395.00') == '4395.00'
    assert extract._to_decimal_str('') is None


@pytest.mark.parametrize('raw,expected', [
    ('08/07/2026 18:23:55', '2026-07-08T18:23:55'),
    ('03/04/2026 08:59:37 AM', '2026-04-03T08:59:37'),
    ('08/07/2026', '2026-07-08T00:00:00'),
    ('not a date', None),
])
def test_dates(raw, expected):
    assert extract._parse_date(raw) == expected


@pytest.mark.parametrize('payload', [b'hello world', b'', b'%PDF-1.4 truncated'])
def test_unreadable_files_are_refused_loudly(payload):
    """The upload is discarded after ingest, so a partial parse must never pass."""
    with pytest.raises(extract.PicklistExtractError):
        extract.extract(io.BytesIO(payload))


def test_a_pdf_that_is_not_a_picklist_is_refused():
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, 'This is an invoice, not a pick list.')
    c.save()
    with pytest.raises(extract.PicklistExtractError):
        extract.extract(io.BytesIO(buf.getvalue()))


def test_meta_survives_the_json_column(extracted):
    assert json.loads(json.dumps(extracted, ensure_ascii=False)) == extracted
