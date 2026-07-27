"""PDF text extraction via the pypdf fallback path.

pdfplumber is the primary extractor; pypdf only runs when pdfplumber raises.
These tests pin that fallback so a future library swap cannot silently turn it
into a no-op that always returns None.
"""
import io

import fitz  # PyMuPDF, already a dependency — used here only to build fixtures.
import pytest

from src.collector.paper.text_extractor import TextExtractor


@pytest.fixture
def extractor():
    ex = TextExtractor()
    yield ex
    ex.close()


def _pdf_bytes(text: str) -> io.BytesIO:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    buf = io.BytesIO(doc.tobytes())
    doc.close()
    return buf


def test_extract_with_pypdf_reads_page_text(extractor):
    assert "Attention Is All You Need" in extractor._extract_with_pypdf(
        _pdf_bytes("Attention Is All You Need")
    )


def test_extract_with_pypdf_returns_none_for_non_pdf(extractor):
    assert extractor._extract_with_pypdf(io.BytesIO(b"not a pdf at all")) is None


def test_extract_with_pypdf_returns_none_for_textless_pdf(extractor):
    doc = fitz.open()
    doc.new_page()
    buf = io.BytesIO(doc.tobytes())
    doc.close()

    assert extractor._extract_with_pypdf(buf) is None
