"""Decode effective-dated VNAllshare sector memberships from HOSE PDFs."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import unicodedata

from pypdf import PdfReader

from asmf_data.models import SectorMembership


SECTORS = {
    "nang luong": ("VNENE", "VNAllshare Năng lượng"),
    "nguyen vat lieu": ("VNMAT", "VNAllshare Nguyên vật liệu"),
    "cong nghiep": ("VNIND", "VNAllshare Công nghiệp"),
    "hang tieu dung thiet yeu": ("VNCONS", "VNAllshare Hàng tiêu dùng thiết yếu"),
    "hang tieu dung": ("VNCOND", "VNAllshare Hàng tiêu dùng"),
    "cham soc suc khoe": ("VNHEAL", "VNAllshare Chăm sóc sức khỏe"),
    "tai chinh": ("VNFIN", "VNAllshare Tài chính"),
    "bat dong san": ("VNREAL", "VNAllshare Bất động sản"),
    "dich vu tien ich": ("VNUTI", "VNAllshare Dịch vụ tiện ích"),
    "cong nghe thong tin": ("VNIT", "VNAllshare Công nghệ thông tin"),
}

_ROW = re.compile(r"^\s*\d+\s+([A-Z][A-Z0-9]{2})\s+\S")
_SECTOR_MARKER = "cac chi so nganh vnallshare sector indices"
_NO_INDEX_MARKER = "nganh moi chua co chi so"


def extract_pdf_pages(path: str | Path) -> tuple[str, ...]:
    """Extract page text without assigning any undocumented PDF fields."""
    reader = PdfReader(str(path))
    return tuple(page.extract_text() or "" for page in reader.pages)


def parse_hose_sector_pages(
    pages: tuple[str, ...],
    *,
    effective_from: date,
    effective_to: date | None,
    source: str,
    include_codes: frozenset[str] | None = None,
) -> tuple[SectorMembership, ...]:
    """Parse the sector-list portion of an official HOSE-Index publication.

    Sector headings are printed at the bottom of each table page. A table can
    continue on the next page, so the most recent heading remains active until
    another recognized heading is encountered.
    """
    if effective_to is not None and effective_to < effective_from:
        raise ValueError("effective_to must not precede effective_from")
    if not source.strip():
        raise ValueError("source must be non-empty")
    selected = None if include_codes is None else frozenset(code.strip().upper() for code in include_codes)
    known_codes = {code for code, _ in SECTORS.values()}
    if selected is not None and (not selected or selected - known_codes):
        raise ValueError("include_codes contains an unknown or empty sector code")

    started = False
    current: tuple[str, str] | None = None
    rows: list[SectorMembership] = []
    symbol_sectors: dict[str, str] = {}

    for page in pages:
        normalized_page = _ascii(page)
        if _SECTOR_MARKER in normalized_page:
            started = True
        if not started:
            continue
        if _NO_INDEX_MARKER in normalized_page:
            current = None
            continue
        heading = _sector_heading(normalized_page)
        if heading is not None:
            current = heading
        if current is None:
            continue
        code, name = current
        if selected is not None and code not in selected:
            continue
        for line in page.splitlines():
            match = _ROW.match(line)
            if match is None:
                continue
            symbol = match.group(1)
            previous = symbol_sectors.setdefault(symbol, code)
            if previous != code:
                raise ValueError(f"{symbol} appears in multiple HOSE sectors")
            rows.append(SectorMembership(
                symbol, code, name, effective_from, effective_to, source.strip()
            ))

    unique = {(row.symbol, row.sector_code): row for row in rows}
    result = tuple(sorted(unique.values(), key=lambda row: (row.sector_code, row.symbol)))
    found_codes = {row.sector_code for row in result}
    required = selected if selected is not None else known_codes
    missing = required - found_codes
    if missing:
        raise ValueError(f"HOSE sector PDF is missing requested sectors: {', '.join(sorted(missing))}")
    return result


def extract_vnallshare_symbols(pages: tuple[str, ...]) -> frozenset[str]:
    """Return the eligible symbols printed in the VNAllshare table."""
    started = False
    symbols: set[str] = set()
    for page in pages:
        normalized_page = _ascii(page)
        if _SECTOR_MARKER in normalized_page:
            break
        if "chi so vnallshare" in normalized_page:
            started = True
        if not started:
            continue
        for line in page.splitlines():
            match = _ROW.match(line)
            if match is not None:
                symbols.add(match.group(1))
    if not symbols:
        raise ValueError("PDF has no VNAllshare component table")
    return frozenset(symbols)


def parse_hose_sector_pdf(
    path: str | Path,
    *,
    effective_from: date,
    effective_to: date | None,
    source: str,
    include_codes: frozenset[str] | None = None,
) -> tuple[SectorMembership, ...]:
    return parse_hose_sector_pages(
        extract_pdf_pages(path),
        effective_from=effective_from,
        effective_to=effective_to,
        source=source,
        include_codes=include_codes,
    )


def sector_counts(rows: tuple[SectorMembership, ...]) -> dict[str, int]:
    return {
        code: sum(row.sector_code == code for row in rows)
        for code in sorted({row.sector_code for row in rows})
    }


def _sector_heading(normalized_page: str) -> tuple[str, str] | None:
    # Match longer labels first because "hang tieu dung" is a prefix of
    # "hang tieu dung thiet yeu".
    matches = [
        (normalized_page.rfind(f"vnallshare {label}"), value)
        for label, value in sorted(SECTORS.items(), key=lambda item: len(item[0]), reverse=True)
    ]
    position, value = max(matches, key=lambda item: item[0])
    return value if position >= 0 else None


def _ascii(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).replace("đ", "d").replace("Đ", "D")
    return " ".join(
        "".join(character for character in decomposed if not unicodedata.combining(character))
        .lower()
        .split()
    )
