"""Verified OCR boundary for Vietnamese consolidated bank reports."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unicodedata

from PIL import Image, ImageFilter, ImageOps
from pypdf import PdfReader

from asmf_data.models import BankFinancialReport


class BankReportOcrError(ValueError):
    """Raised when OCR evidence is missing or fails accounting checks."""


NUMBER = re.compile(r"\(?\d{1,3}(?:[.,]\d{3})+\)?")


def ocr_pdf_pages(
    path: str | Path,
    pages: tuple[int, ...],
    *,
    rotation: int = 180,
    executable: str | Path | None = None,
) -> dict[int, str]:
    """OCR selected one-based pages; the source PDF is never modified."""
    if not pages or any(page <= 0 for page in pages):
        raise ValueError("pages must contain positive one-based page numbers")
    command = _tesseract(executable)
    reader = PdfReader(path)
    if max(pages) > len(reader.pages):
        raise ValueError("requested OCR page exceeds PDF page count")
    result: dict[int, str] = {}
    with TemporaryDirectory(prefix="bank-report-ocr-") as temporary:
        directory = Path(temporary)
        for page_number in pages:
            images = reader.pages[page_number - 1].images
            if len(images) != 1:
                raise BankReportOcrError(
                    f"page {page_number} must contain exactly one scanned image"
                )
            image = images[0].image
            if rotation:
                image = image.rotate(rotation, expand=True)
            # Vietstock scans are low-resolution JPEGs. Upscaling before OCR is
            # essential for distinguishing adjacent digits in financial values.
            image = ImageOps.autocontrast(image.convert("L"))
            image = image.resize(
                (image.width * 2, image.height * 2), Image.Resampling.LANCZOS
            ).filter(ImageFilter.SHARPEN)
            image_path = directory / f"page-{page_number}.png"
            image.save(image_path)
            completed = subprocess.run(
                [command, str(image_path), "stdout", "-l", "vie+eng", "--psm", "6"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                check=False,
            )
            if completed.returncode != 0:
                raise BankReportOcrError(
                    f"Tesseract failed on page {page_number}: {completed.stderr.strip()}"
                )
            result[page_number] = completed.stdout
    return result


def parse_bank_interim_ocr(
    *,
    symbol: str,
    report_period: str,
    public_date: date,
    asset_text: str,
    liability_text: str,
    income_text: str,
    quality_text: str | None = None,
    source: str,
) -> BankFinancialReport:
    """Parse only verified Vietnamese B02a/B03a labels with integrity checks."""
    reported_gross_loans = _current_value(asset_text, "cho vay khach hang", occurrence=2)
    reserve = abs(_current_value(asset_text, "du phong rui ro cho vay khach hang"))
    net_loans = _current_value(asset_text, "cho vay khach hang", occurrence=1)
    gross_loans = _reconcile(
        net_loans + reserve, reported_gross_loans, "gross loans"
    )

    equity = _current_value(liability_text, "tong von chu so huu")
    interest_income = _current_value(income_text, "thu nhap lai va cac khoan thu nhap tuong tu")
    interest_expense = abs(_current_value(income_text, "chi phi lai va cac chi phi tuong tu"))
    net_interest_income = _current_value(income_text, "thu nhap lai thuan")
    if interest_income - interest_expense != net_interest_income:
        raise BankReportOcrError("interest values fail income minus expense equals NII check")
    net_profit = _current_value(income_text, "loi nhuan sau thue")
    nonperforming_loans = None
    if quality_text is not None:
        nonperforming_loans = sum(
            _current_value(quality_text, f"nhom {group} - no")
            for group in (3, 4, 5)
        )
        if nonperforming_loans <= 0 or nonperforming_loans > gross_loans:
            raise BankReportOcrError("nonperforming-loan groups are invalid")

    return BankFinancialReport(
        symbol.strip().upper(), report_period.strip().upper(), public_date,
        int(report_period[-1]) * 3, float(net_interest_income), float(net_profit),
        float(equity), float(gross_loans),
        float(nonperforming_loans) if nonperforming_loans is not None else None,
        float(reserve), None, source.strip(),
    )


def _current_value(text: str, label: str, *, occurrence: int = 1) -> int:
    normalized_label = _plain(label)
    matches = [line for line in text.splitlines() if normalized_label in _plain(line)]
    if len(matches) < occurrence:
        raise BankReportOcrError(f"OCR label not found: {label} occurrence {occurrence}")
    values = NUMBER.findall(matches[occurrence - 1])
    if len(values) < 2:
        raise BankReportOcrError(f"two reporting columns not found for: {label}")
    return _integer(values[-2])


def _integer(value: str) -> int:
    negative = value.startswith("(") and value.endswith(")")
    digits = re.sub(r"\D", "", value)
    if not digits:
        raise BankReportOcrError("OCR numeric token is empty")
    parsed = int(digits)
    return -parsed if negative else parsed


def _reconcile(expected: int, observed: int, label: str) -> int:
    """Correct a small OCR digit error only when an exact accounting identity exists."""
    if expected == observed:
        return expected
    relative_error = abs(expected - observed) / max(abs(expected), 1)
    if relative_error <= 0.002:
        return expected
    raise BankReportOcrError(f"{label} fails accounting reconciliation")


def _plain(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).split())


def _tesseract(value: str | Path | None) -> str:
    candidates = [str(value)] if value else []
    found = shutil.which("tesseract")
    if found:
        candidates.append(found)
    candidates.append(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    raise BankReportOcrError("Tesseract executable was not found")
