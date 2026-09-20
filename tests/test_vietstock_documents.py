"""Offline tests for the observed Vietstock document contract."""

from io import BytesIO
from pathlib import Path
import zipfile

import requests

from asmf_data.vietstock import VietstockDocumentClient, _csrf_token


class Response:
    def __init__(self, *, text="", payload=None, content=b"%PDF-1.7\n"):
        self.text = text
        self.payload = payload
        self.content = content
        self.headers = {"Content-Length": str(len(content))}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        yield self.content


class Session(requests.Session):
    def __init__(self, payload):
        super().__init__()
        self.payload = payload
        self.posts = []

    def get(self, url, **kwargs):
        if "tai-tai-lieu" in url:
            return Response(text='<input name="__RequestVerificationToken" value="SECRET">')
        return Response()

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return Response(payload=self.payload)


def payload():
    return [{"FileExt": ".pdf ", "TotalRow": 210, "FileInfoID": 558363,
             "Url": "https://static2.vietstock.vn/data/HOSE/2026/BCTC/VN/QUY 2/a.pdf",
             "Title": "BCTC Hợp nhất", "FullName": "Báo cáo tài chính Hợp nhất",
             "LastUpdate": "/Date(1786755989523)/"}]


def test_observed_contract_parses_and_sends_runtime_csrf_token() -> None:
    session = Session(payload())
    document = VietstockDocumentClient(session).list_documents("acb")[0]
    assert document.file_info_id == 558363
    assert document.consolidated
    assert document.url.endswith("QUY%202/a.pdf")
    assert document.total_rows == 210
    assert session.posts[0][1]["data"] == {
        "code": "ACB", "page": "1", "type": "1",
        "__RequestVerificationToken": "SECRET",
    }


def test_csrf_html_entities_are_decoded() -> None:
    assert _csrf_token('<input name="__RequestVerificationToken" value="A&amp;B">') == "A&B"
    assert _csrf_token('<input name=__RequestVerificationToken type=hidden value=ABC123>') == "ABC123"


def test_download_streams_and_validates_pdf(tmp_path: Path) -> None:
    document = VietstockDocumentClient(Session(payload())).list_documents("ACB")[0]
    result = VietstockDocumentClient(Session(payload())).download(document, tmp_path)
    assert result.read_bytes().startswith(b"%PDF-")
    assert not result.with_suffix(result.suffix + ".part").exists()


def test_download_rejects_html_disguised_as_pdf(tmp_path: Path) -> None:
    session = Session(payload())
    session.get = lambda url, **kwargs: Response(content=b"<html>login</html>")
    document = VietstockDocumentClient(Session(payload())).list_documents("ACB")[0]
    try:
        VietstockDocumentClient(session).download(document, tmp_path)
    except Exception as exc:
        assert "not a PDF" in str(exc)
    else:
        raise AssertionError("invalid PDF content was accepted")
