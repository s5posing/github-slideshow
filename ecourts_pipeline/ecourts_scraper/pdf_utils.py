"""PDF acquisition and text extraction helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pdfminer.high_level
from pdfminer.layout import LAParams
from pdf2image import convert_from_path
from pypdf import PdfReader
from pytesseract import image_to_string


logger = logging.getLogger(__name__)


def extract_text_with_pypdf(path: Path, max_pages: Optional[int] = None) -> str:
    reader = PdfReader(str(path))
    text_chunks = []
    for index, page in enumerate(reader.pages):
        if max_pages is not None and index >= max_pages:
            break
        text_chunks.append(page.extract_text() or "")
    return "\n".join(text_chunks)


def extract_text_with_pdfminer(path: Path, max_pages: Optional[int] = None) -> str:
    with path.open("rb") as handle:
        if max_pages is not None:
            laparams = LAParams()
            return pdfminer.high_level.extract_text(
                handle,
                maxpages=max_pages,
                laparams=laparams,
            )
        return pdfminer.high_level.extract_text(handle)


def ocr_pdf(path: Path, dpi: int = 300, lang: str = "eng") -> str:
    images = convert_from_path(str(path), dpi=dpi)
    text = []
    for image in images:
        text.append(image_to_string(image, lang=lang))
    return "\n".join(text)


def extract_text(path: Path, max_pages: Optional[int] = None, force_ocr: bool = False) -> str:
    path = Path(path)
    errors = []
    if not force_ocr:
        try:
            text = extract_text_with_pypdf(path, max_pages=max_pages)
            if text.strip():
                return text
        except Exception as exc:  # noqa: BLE001
            logger.warning("pypdf text extraction failed: %s", exc)
            errors.append(exc)
        try:
            text = extract_text_with_pdfminer(path, max_pages=max_pages)
            if text.strip():
                return text
        except Exception as exc:  # noqa: BLE001
            logger.warning("pdfminer text extraction failed: %s", exc)
            errors.append(exc)

    try:
        return ocr_pdf(path)
    except Exception as exc:  # noqa: BLE001
        logger.error("OCR extraction failed for %s: %s", path, exc)
        raise RuntimeError(f"Unable to extract text from {path}") from exc

