from __future__ import annotations

from io import BytesIO

from xhtml2pdf import pisa


def html_to_pdf(html: str) -> bytes:
    buffer = BytesIO()
    result = pisa.CreatePDF(html, dest=buffer, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"PDF generation failed with {result.err} errors")
    return buffer.getvalue()
