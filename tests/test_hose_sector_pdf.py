from datetime import date

import pytest

from asmf_data.hose_sector_pdf import (
    extract_vnallshare_symbols,
    parse_hose_sector_pages,
    sector_counts,
)


def test_parser_ignores_index_pages_and_keeps_continuation_sector() -> None:
    pages = (
        "1 FPT CTCP FPT\nCÔNG BỐ DANH MỤC CHỈ SỐ VN30",
        "1 FPT CTCP FPT\n2 CMG CTCP CMC\n"
        "CÁC CHỈ SỐ NGÀNH VNALLSHARE SECTOR INDICES\nVNAllshare Công nghệ thông tin",
        "3 ELC CTCP ELCOM\n4 ICT CTCP Tin học",
        "1 ACB Ngân hàng Á Châu\n2 TCB Ngân hàng Kỹ thương\nVNAllshare Tài chính",
    )
    rows = parse_hose_sector_pages(
        pages,
        effective_from=date(2026, 2, 2),
        effective_to=date(2026, 8, 2),
        source="HOSE/HOSE-Index/2026-01",
        include_codes=frozenset(("VNIT", "VNFIN")),
    )

    assert [(row.symbol, row.sector_code) for row in rows] == [
        ("ACB", "VNFIN"), ("TCB", "VNFIN"),
        ("CMG", "VNIT"), ("ELC", "VNIT"), ("FPT", "VNIT"), ("ICT", "VNIT"),
    ]
    assert all(row.effective_to == date(2026, 8, 2) for row in rows)
    assert sector_counts(rows) == {"VNFIN": 2, "VNIT": 4}


def test_parser_rejects_requested_sector_missing_from_pdf() -> None:
    pages = (
        "1 FPT CTCP FPT\nCÁC CHỈ SỐ NGÀNH VNALLSHARE SECTOR INDICES\n"
        "VNAllshare Công nghệ thông tin",
    )
    with pytest.raises(ValueError, match="VNUTI"):
        parse_hose_sector_pages(
            pages,
            effective_from=date(2026, 2, 2),
            effective_to=None,
            source="TEST",
            include_codes=frozenset(("VNIT", "VNUTI")),
        )


def test_parser_rejects_symbol_in_multiple_sectors() -> None:
    pages = (
        "1 FPT CTCP FPT\nCÁC CHỈ SỐ NGÀNH VNALLSHARE SECTOR INDICES\n"
        "VNAllshare Công nghệ thông tin",
        "1 FPT CTCP FPT\nVNAllshare Tài chính",
    )
    with pytest.raises(ValueError, match="multiple HOSE sectors"):
        parse_hose_sector_pages(
            pages,
            effective_from=date(2026, 2, 2),
            effective_to=None,
            source="TEST",
            include_codes=frozenset(("VNIT", "VNFIN")),
        )


def test_parser_does_not_assign_unindexed_new_industry_to_prior_sector() -> None:
    pages = (
        "1 VIC Tập đoàn\nCÁC CHỈ SỐ NGÀNH VNALLSHARE SECTOR INDICES\n"
        "VNAllshare Bất động sản",
        "1 YEG CTCP Yeah1\nNgành mới chưa có chỉ số",
    )
    rows = parse_hose_sector_pages(
        pages,
        effective_from=date(2026, 8, 3),
        effective_to=None,
        source="TEST",
        include_codes=frozenset(("VNREAL",)),
    )
    assert [row.symbol for row in rows] == ["VIC"]


def test_extract_vnallshare_symbols_stops_before_sector_tables() -> None:
    pages = (
        "1 FPT CTCP FPT\nCÔNG BỐ THÔNG TIN CỦA CHỈ SỐ VNALLSHARE",
        "2 ACB Ngân hàng Á Châu",
        "1 CMG CTCP CMC\nCÁC CHỈ SỐ NGÀNH VNALLSHARE SECTOR INDICES",
    )
    assert extract_vnallshare_symbols(pages) == frozenset(("FPT", "ACB"))
