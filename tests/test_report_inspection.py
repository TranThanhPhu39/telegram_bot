"""Tests for financial-report container classification."""

from pathlib import Path
import zipfile

from pypdf import PdfWriter
import pytest

from asmf_data.report_inspection import UnsupportedReportError, extraction_branch, inspect_report


def test_textless_blank_pdf_is_not_mislabeled_as_scanned(tmp_path: Path) -> None:
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with path.open("wb") as output:
        writer.write(output)
    result = inspect_report(path)
    assert result.page_count == 1
    assert result.text_character_count == 0
    assert result.image_count == 0
    assert extraction_branch(result) == "unsupported"


def test_zip_with_spreadsheet_selects_structured_branch(tmp_path: Path) -> None:
    path = tmp_path / "report.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ACB/report.xlsx", b"placeholder")
    result = inspect_report(path)
    assert result.members == ("ACB/report.xlsx",)
    assert extraction_branch(result) == "structured_archive"


def test_unknown_report_extension_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "report.txt"
    path.write_text("not a report", encoding="utf-8")
    with pytest.raises(UnsupportedReportError):
        inspect_report(path)
