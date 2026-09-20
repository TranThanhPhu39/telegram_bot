"""Vietstock public-document discovery and bounded report downloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
import logging
import os
from pathlib import Path
import re
import zipfile
from urllib.parse import unquote, urlparse

import requests


LOGGER = logging.getLogger(__name__)
BASE_URL = "https://finance.vietstock.vn"
DOCUMENT_ENDPOINT = f"{BASE_URL}/data/getdocument"
ALLOWED_DOWNLOAD_HOSTS = {"static2.vietstock.vn"}
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
TOKEN_PATTERN = re.compile(
    r'name=(?:["\'])?__RequestVerificationToken(?:["\'])?[^>]*?'
    r'value=(?:["\']([^"\']+)["\']|([^\s>]+))',
    re.I,
)
DATE_PATTERN = re.compile(r"^/Date\((\d+)\)/$")


class VietstockDocumentError(RuntimeError):
    """Raised when the public document contract cannot be used safely."""


@dataclass(frozen=True, slots=True)
class VietstockDocument:
    file_info_id: int
    title: str
    url: str
    file_extension: str
    published_at: datetime
    total_rows: int

    @property
    def consolidated(self) -> bool:
        normalized = self.title.casefold()
        return "hợp nhất" in normalized or "hopnhat" in self.url.casefold()


class VietstockDocumentClient:
    def __init__(self, session: requests.Session | None = None, *, timeout: float = 20.0) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.7,en;q=0.6",
        })

    def list_documents(self, symbol: str, *, page: int = 1, document_type: int = 1) -> tuple[VietstockDocument, ...]:
        symbol = _symbol(symbol)
        if page <= 0 or document_type <= 0:
            raise ValueError("page and document_type must be positive")
        page_url = f"{BASE_URL}/{symbol}/tai-tai-lieu.htm?doctype={document_type}"
        try:
            landing = self.session.get(page_url, timeout=self.timeout)
            landing.raise_for_status()
            token = _csrf_token(landing.text)
            response = self.session.post(
                DOCUMENT_ENDPOINT,
                data={"code": symbol, "page": str(page), "type": str(document_type),
                      "__RequestVerificationToken": token},
                headers={"Referer": page_url, "X-Requested-With": "XMLHttpRequest"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise VietstockDocumentError(f"Vietstock document request failed: {exc}") from exc
        if not isinstance(payload, list):
            raise VietstockDocumentError("Vietstock document response must be a JSON list")
        documents = tuple(_document(item) for item in payload)
        LOGGER.info("Vietstock returned %d document records for %s page %d", len(documents), symbol, page)
        return documents

    def list_all_documents(self, symbol: str, *, document_type: int = 1, page_size: int = 20) -> tuple[VietstockDocument, ...]:
        first = self.list_documents(symbol, page=1, document_type=document_type)
        if not first:
            return ()
        total = first[0].total_rows
        pages = max(1, (total + page_size - 1) // page_size)
        result = list(first)
        seen = {item.file_info_id for item in first}
        for page in range(2, pages + 1):
            for item in self.list_documents(symbol, page=page, document_type=document_type):
                if item.file_info_id not in seen:
                    seen.add(item.file_info_id)
                    result.append(item)
        return tuple(result)

    def download(self, document: VietstockDocument, directory: str | Path) -> Path:
        parsed = urlparse(document.url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
            raise VietstockDocumentError("document URL host is not allow-listed")
        filename = f"{document.file_info_id}_{Path(unquote(parsed.path)).name}"
        destination = Path(directory) / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.stat().st_size > 0:
            return destination
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            response = self.session.get(document.url, timeout=self.timeout, stream=True)
            response.raise_for_status()
            declared_size = int(response.headers.get("Content-Length", 0))
            if declared_size > MAX_DOWNLOAD_BYTES:
                raise VietstockDocumentError("Vietstock document exceeds the download limit")
            written = 0
            with temporary.open("wb") as output:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        raise VietstockDocumentError("Vietstock document exceeds the download limit")
                    output.write(chunk)
            _validate_download(temporary, document.file_extension)
            os.replace(temporary, destination)
        except requests.RequestException as exc:
            raise VietstockDocumentError(f"Vietstock download failed: {exc}") from exc
        finally:
            if temporary.exists():
                temporary.unlink()
        return destination


def _validate_download(path: Path, expected_extension: str) -> None:
    """Reject error pages and malformed archives before they enter the data pipeline."""
    extension = expected_extension.strip().lower()
    with path.open("rb") as source:
        signature = source.read(8)
    if extension == ".pdf" and not signature.startswith(b"%PDF-"):
        raise VietstockDocumentError("downloaded content is not a PDF")
    if extension == ".zip":
        if not zipfile.is_zipfile(path):
            raise VietstockDocumentError("downloaded content is not a ZIP archive")
        with zipfile.ZipFile(path) as archive:
            unsafe = [name for name in archive.namelist()
                      if Path(name).is_absolute() or ".." in Path(name).parts]
            if unsafe:
                raise VietstockDocumentError("ZIP archive contains an unsafe path")


def _csrf_token(html: str) -> str:
    match = TOKEN_PATTERN.search(html)
    if match is None:
        raise VietstockDocumentError("CSRF token was not found on Vietstock document page")
    return unescape(match.group(1) or match.group(2))


def _document(value: object) -> VietstockDocument:
    if not isinstance(value, dict):
        raise VietstockDocumentError("document record must be an object")
    match = DATE_PATTERN.match(str(value.get("LastUpdate", "")))
    if match is None:
        raise VietstockDocumentError("document LastUpdate has an unknown format")
    try:
        return VietstockDocument(
            file_info_id=int(value["FileInfoID"]),
            title=str(value.get("FullName") or value["Title"]).strip(),
            url=str(value["Url"]).strip().replace(" ", "%20"),
            file_extension=str(value["FileExt"]).strip().lower(),
            published_at=datetime.fromtimestamp(int(match.group(1)) / 1000, timezone.utc),
            total_rows=int(value["TotalRow"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise VietstockDocumentError(f"invalid document record: {exc}") from exc


def _symbol(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized or not normalized.isalnum():
        raise ValueError("symbol must be alphanumeric")
    return normalized
