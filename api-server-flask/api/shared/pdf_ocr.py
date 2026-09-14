# -*- encoding: utf-8 -*-
"""Reading PDFs whose words were saved as pictures.

Some documents arrive with no text in them at all. A PDF printed through a virtual
printer, or saved with its fonts flattened, carries only the SHAPES of its letters —
thousands of Bezier curves that render perfectly and extract to nothing. One real example:
a one-page challan whose content stream held 49,511 path operators and zero text
operators.

Nothing can read those directly, so the page is rendered to an image and put through OCR,
which produces a copy carrying an invisible text layer. That copy is what the parsers read.

WHY 600 DPI
-----------
Measured, not guessed, on a challan whose correct values were known:

    400 DPI   a line's Quantity of 2 was dropped entirely — a silent, wrong order
    600 DPI   every field correct
    1200 DPI  worse again: '50' read as 'SO', '0' as 'v', one row lost completely

Higher is not better. Above about 600 the glyph edges antialias into shapes tesseract
likes less, and the failures are the dangerous kind — a digit becomes a letter rather than
the read obviously collapsing.

OCR IS NEVER TRUSTED ON ITS OWN
-------------------------------
Everything read here is checked against totals the document itself prints — see
`challan_ocr.validate_against_totals`. A challan whose line quantities do not add up to
its own printed total is refused rather than imported. Guessing at somebody's order
quantities is worse than telling them the file cannot be read.
"""

import os
import shutil
import subprocess
import tempfile

import pdfplumber

from api.core.logging import get_logger

logger = get_logger(__name__)

# See the module docstring — this figure is measured, not a default.
OCR_DPI = 600

# How long one page may take. OCR is CPU-bound and this box has two cores; a challan takes
# about 8 seconds, so this is a wide margin that still stops a pathological file from
# holding a request open indefinitely.
OCR_TIMEOUT_SECONDS = 180


class OcrUnavailable(Exception):
    """The OCR toolchain is not installed on this machine."""


def ocr_available():
    """True when ocrmypdf and tesseract are both present."""
    return bool(shutil.which('ocrmypdf')) and bool(shutil.which('tesseract'))


def has_text_layer(path, pages_to_check=3):
    """True when this PDF carries text that can actually be read out of it.

    Errs towards True: if the file cannot be opened at all, the real parser should raise
    the real error rather than have this guess at one.
    """
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:pages_to_check]:
                if (page.extract_text() or '').strip():
                    return True
            return False
    except Exception:
        return True


def make_searchable(path, dpi=OCR_DPI):
    """Return the path to a copy of this PDF carrying an OCR text layer.

    The caller owns the returned file and must delete it. Raises OcrUnavailable when the
    tools are missing, and RuntimeError when OCR fails, so the upload reports the real
    reason rather than a downstream symptom.
    """
    if not ocr_available():
        raise OcrUnavailable(
            'this PDF has no readable text and OCR is not installed on the server')

    handle, out_path = tempfile.mkstemp(suffix='.pdf', prefix='ocr_')
    os.close(handle)
    cmd = [
        'ocrmypdf',
        '--force-ocr',          # the page has no text of its own; OCR all of it
        '--oversample', str(dpi),
        '--optimize', '0',      # keep the glyphs crisp; file size is irrelevant here
        '--output-type', 'pdf',
        '-l', 'eng',
        '--quiet',
        path, out_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=OCR_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _quiet_remove(out_path)
        raise RuntimeError('reading this PDF took too long — it may be unusually large')
    if result.returncode != 0:
        _quiet_remove(out_path)
        detail = (result.stderr or b'').decode('utf-8', 'replace').strip().splitlines()
        raise RuntimeError('could not read this PDF as an image (%s)'
                           % (detail[-1] if detail else 'OCR failed'))

    logger.info('PDF OCR complete', extra={'dpi': dpi,
                                           'source': os.path.basename(path)})
    return out_path


def _quiet_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def words_with_positions(path, page_number=0):
    """Every OCR'd word on a page, with its coordinates.

    Position is the whole point: the text alone runs the columns of a table together, but
    the x of each word says which column it was in, which is what lets a quantity be told
    apart from the stock figure printed beside it.
    """
    with pdfplumber.open(path) as pdf:
        if page_number >= len(pdf.pages):
            return [], 0, 0
        page = pdf.pages[page_number]
        return page.extract_words(), page.width, page.height
