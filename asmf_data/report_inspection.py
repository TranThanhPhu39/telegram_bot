"""Inspect downloaded financial-report containers before value extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import zipfile

from pypdf import PdfReader


class UnsupportedReportError(ValueError):
    """Raised when a report cannot enter a verified extraction branch."""


@dataclass(frozen=True, slots=True)
class ReportInspection:
    kind: str
    page_count: int = 0
    text_character_count: int = 0
    image_count: int = 0
    members: tuple[str, ...] = ()

    @property
    def requires_ocr(self) -> bool:
        return self.kind == "pdf" and self.page_count > 0 and self.text_character_count == 0 and self.image_count > 0


def inspect_report(path: str | Path) -> ReportInspection:
    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix == ".pdf":
        reader = PdfReader(source)
        text_count = 0
        image_count = 0
        for page in reader.pages:
            text_count += len((page.extract_text() or "").strip())
            image_count += len(page.images)
        return ReportInspection("pdf", len(reader.pages), text_count, image_count)
    if suffix == ".zip":
        with zipfile.ZipFile(source) as archive:
            members = tuple(info.filename for info in archive.infolist() if not info.is_dir())
        return ReportInspection("zip", members=members)
    raise UnsupportedReportError(f"unsupported report extension: {source.suffix or '<none>'}")


def extraction_branch(inspection: ReportInspection) -> str:
    """Return the verified next extraction branch without guessing report fields."""
    if inspection.requires_ocr:
        return "ocr_required"
    if inspection.kind == "pdf" and inspection.text_character_count > 0:
        return "pdf_text"
    if inspection.kind == "zip":
        extensions = {Path(name).suffix.casefold() for name in inspection.members}
        if extensions & {".xlsx", ".xls", ".csv", ".xml", ".xbrl"}:
            return "structured_archive"
        if ".pdf" in extensions:
            return "pdf_archive"
        return "unsupported_archive"
    return "unsupported"
