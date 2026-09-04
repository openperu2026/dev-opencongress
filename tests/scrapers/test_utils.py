from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx
from lxml.html import fromstring

from backend.scrapers import utils as u


# ---------- simple pure functions ----------


@pytest.mark.parametrize(
    "input_txt, expected",
    [
        (None, ""),
        ("", ""),
        ("   Hola   Mundo   ", "hola mundo"),
        ("\nHola\nMundo\t", "hola mundo"),
        ("MAYÚSCULAS y   espacios", "mayúsculas y espacios"),
    ],
)
def test_normalize_text(input_txt, expected):
    assert u.normalize_text(input_txt) == expected


@pytest.mark.parametrize(
    "input_txt, expected",
    [
        ("  hola   mundo  ", "hola mundo"),
        ("\nlinea 1\n   linea 2  ", "linea 1 linea 2"),
        ("solo_una_palabra", "solo_una_palabra"),
    ],
)
def test_clean_string(input_txt, expected):
    assert u.clean_string(input_txt) == expected


def test_url_to_cache_file_basic(tmp_path: Path):
    url = "https://example.com/path?query=1"
    cache_path = u.url_to_cache_file(url, tmp_path)

    # should be inside the tmp_path and end with .txt
    assert cache_path.parent == tmp_path
    assert cache_path.suffix == ".txt"
    # scheme removed, special chars converted to underscores
    assert "https" not in cache_path.name
    assert "?" not in cache_path.name
    assert "__" not in cache_path.name or isinstance(cache_path, Path)


def test_save_ocr_txt_to_cache_creates_dir_and_file(tmp_path: Path):
    cache_path = tmp_path / "nested" / "file.txt"
    txt = "hola mundo"

    u.save_ocr_txt_to_cache(txt, cache_path)

    assert cache_path.exists()
    assert cache_path.read_text(encoding="utf-8") == txt


def test_xpath2_returns_text():
    html = "<html><body><div class='title'>Hola</div></body></html>"
    tree = fromstring(html)

    result = u.xpath2("//div[@class='title']", tree)
    assert result == "Hola"


def test_xpath2_returns_none_when_not_found():
    html = "<html><body><div>Hola</div></body></html>"
    tree = fromstring(html)

    result = u.xpath2("//span[@class='missing']", tree)
    assert result is None


# ---------- get_url / get_url_text ----------


class DummyResponse:
    def __init__(self, status_code=200, text="OK", content=b"PDF", is_success=True):
        self.status_code = status_code
        self.text = text
        self.content = content
        self.is_success = is_success

    def raise_for_status(self):
        if not self.is_success:
            raise httpx.HTTPStatusError(
                "error", request=None, response=httpx.Response(self.status_code)
            )


def test_get_url_success(monkeypatch):
    def fake_client(*args, **kwargs):
        class Ctx:
            def __enter__(self_inner):
                class Client:
                    def get(self, url):
                        return DummyResponse(
                            status_code=200, text="OK", is_success=True
                        )

                    def post(self, url, data=None):
                        return DummyResponse(
                            status_code=200, text="OK", is_success=True
                        )

                return Client()

            def __exit__(self_inner, exc_type, exc, tb):
                return False

        return Ctx()

    monkeypatch.setattr(u.httpx, "Client", fake_client)

    resp = u.get_url("https://example.com")
    assert isinstance(resp, DummyResponse)
    assert resp.text == "OK"


def test_get_url_non_success_returns_none(monkeypatch):
    def fake_client(*args, **kwargs):
        class Ctx:
            def __enter__(self_inner):
                class Client:
                    def get(self, url):
                        # is_success False simulates HTTP error handled in get_url
                        return DummyResponse(
                            status_code=500, text="ERR", is_success=False
                        )

                return Client()

            def __exit__(self_inner, exc_type, exc, tb):
                return False

        return Ctx()

    monkeypatch.setattr(u.httpx, "Client", fake_client)

    resp = u.get_url("https://example.com")
    assert resp is None


def test_get_url_request_error_returns_none(monkeypatch):
    def fake_client(*args, **kwargs):
        class Ctx:
            def __enter__(self_inner):
                class Client:
                    def get(self, url):
                        raise httpx.RequestError("boom")

                return Client()

            def __exit__(self_inner, exc_type, exc, tb):
                return False

        return Ctx()

    monkeypatch.setattr(u.httpx, "Client", fake_client)

    resp = u.get_url("https://example.com")
    assert resp is None


def test_get_url_text_with_response(monkeypatch):
    def fake_client(*args, **kwargs):
        class Ctx:
            def __enter__(self_inner):
                class Client:
                    def get(self, url):
                        return DummyResponse(
                            status_code=200, text="OK", is_success=True
                        )

                    def post(self, url, data=None):
                        return DummyResponse(
                            status_code=200, text="OK", is_success=True
                        )

                return Client()

            def __exit__(self_inner, exc_type, exc, tb):
                return False

        return Ctx()

    monkeypatch.setattr(u.httpx, "Client", fake_client)

    resp = u.get_url("https://example.com")
    assert isinstance(resp, DummyResponse)
    assert resp.text == "OK"


def test_get_url_text_with_none_returns_none():
    resp = None
    assert u.get_url_text(resp) is None


# ---------- async helpers ----------


class DummyAsyncResponse:
    def __init__(self, status_code=200, text="OK"):
        self.status_code = status_code
        self.text = text


class DummyAsyncClient:
    def __init__(self, responses):
        # responses: dict[url] -> (status_code, text)
        self._responses = responses

    async def get(self, url):
        status, text = self._responses[url]
        return DummyAsyncResponse(status_code=status, text=text)

    async def post(self, url, data=None):
        status, text = self._responses[url]
        return DummyAsyncResponse(status_code=status, text=text)


@pytest.mark.asyncio
async def test_get_url_text_async_get_ok():
    client = DummyAsyncClient({"https://example.com": (200, "hola")})
    text = await u.get_url_text_async(client, "https://example.com")
    assert text == "hola"


@pytest.mark.asyncio
async def test_get_url_text_async_non_200_returns_none():
    client = DummyAsyncClient({"https://example.com": (500, "error")})
    text = await u.get_url_text_async(client, "https://example.com")
    assert text is None


@pytest.mark.asyncio
async def test_fetch_multiple_urls_async(monkeypatch):
    # We will patch httpx.AsyncClient used inside fetch_multiple_urls_async
    responses = {
        "https://a.com": (200, "<html><body><p>A</p></body></html>"),
        "https://b.com": (200, "<html><body><p>B</p></body></html>"),
    }

    class PatchedAsyncClient:
        def __init__(self, *args, **kwargs):
            self._client = DummyAsyncClient(responses)

        async def __aenter__(self):
            return self._client

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(u.httpx, "AsyncClient", PatchedAsyncClient)

    urls = ["https://a.com", "https://b.com"]
    result = await u.fetch_multiple_urls_async(urls)

    # should return a list of HtmlElement objects
    assert len(result) == 2
    texts = [el.xpath("//p/text()")[0] for el in result]
    assert sorted(texts) == ["A", "B"]


# ---------- render_pdf (high-level wiring with mocks) ----------


def test_render_pdf_uses_extract_text_from_page(monkeypatch):
    # Fake HTTP response for get_url
    class FakeResp:
        def __init__(self):
            self.content = b"%PDF-1.4 fake"
            self.is_success = True

        def raise_for_status(self):
            pass

    def fake_get_url(url, data=None, timeout=None, verify=True):
        return FakeResp()

    monkeypatch.setattr(u, "get_url", fake_get_url)

    # Fake fitz.open so that it yields two "pages"
    class FakePage:
        pass

    class FakeDoc:
        def __iter__(self):
            # two pages
            yield FakePage()
            yield FakePage()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_fitz_open(stream=None, filetype=None):
        return FakeDoc()

    monkeypatch.setattr(u, "fitz", SimpleNamespace(open=fake_fitz_open))

    # Make extract_text_from_page return deterministic text
    calls = []

    def fake_extract(page):
        calls.append(page)
        return "PAGE_TEXT"

    monkeypatch.setattr(u, "extract_text_from_page", fake_extract)

    text_dict = u.render_pdf("https://example.com/fake.pdf")

    # Should have been called twice (2 pages)
    assert len(calls) == 2
    # And the final text should contain both page texts
    assert text_dict[0].strip() == "PAGE_TEXT"
    assert text_dict[1].strip() == "PAGE_TEXT"


# ---------- get_last_id (bicameral scraping) ----------


class _FakePostResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _make_fake_post_client(monkeypatch, captured, entity):
    """Patches httpx.Client so client.post(url, json=payload) records
    payload into `captured` and returns a minimal valid response for
    `entity` ("Bills" or "Motions")."""
    data_var = {"Bills": "proyectos", "Motions": "mociones"}[entity]
    id_var = {"Bills": "pleyNum", "Motions": "mocionNum"}[entity]

    def fake_client(*args, **kwargs):
        class Ctx:
            def __enter__(self_inner):
                class Client:
                    def post(self, url, json=None):
                        captured.append(json)
                        return _FakePostResponse({"data": {data_var: [{id_var: 42}]}})

                return Client()

            def __exit__(self_inner, exc_type, exc, tb):
                return False

        return Ctx()

    monkeypatch.setattr(u.httpx, "Client", fake_client)


def test_get_last_id_bills_legacy_default_payload_unchanged(monkeypatch):
    """Regression: no new args -> exact same payload as before this change
    (perParId=2021, no codTipoParl key)."""
    captured = []
    _make_fake_post_client(monkeypatch, captured, "Bills")

    result = u.get_last_id("Bills")

    assert result == 42
    assert captured == [{"perParId": 2021, "pageSize": 10, "rowStart": 0}]


def test_get_last_id_motions_legacy_default_payload_unchanged(monkeypatch):
    """Regression: no new args -> exact same payload as before this change
    (codTipoParl="C", no perParId key)."""
    captured = []
    _make_fake_post_client(monkeypatch, captured, "Motions")

    result = u.get_last_id("Motions")

    assert result == 42
    assert captured == [{"pageSize": 10, "rowStart": 0, "codTipoParl": "C"}]


def test_get_last_id_bills_new_args_payload(monkeypatch):
    captured = []
    _make_fake_post_client(monkeypatch, captured, "Bills")

    u.get_last_id("Bills", per_par_id=2026, cod_tipo_parl="S")

    assert captured == [
        {"pageSize": 10, "rowStart": 0, "perParId": 2026, "codTipoParl": "S"}
    ]


def test_get_last_id_motions_new_args_payload(monkeypatch):
    captured = []
    _make_fake_post_client(monkeypatch, captured, "Motions")

    u.get_last_id("Motions", per_par_id=2026, cod_tipo_parl="D")

    assert captured == [
        {"pageSize": 10, "rowStart": 0, "codTipoParl": "D", "perParId": 2026}
    ]
