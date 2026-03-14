from types import SimpleNamespace

import pytest

from scraper import ReadmooScraper


class DummyApp:
    def update_status(self, text, error=False):
        self.last_status = (text, error)


@pytest.fixture
def scraper():
    return ReadmooScraper(DummyApp())


def test_extract_included_items_supports_multiple_shapes(scraper):
    direct = {"included": [{"id": 1}, {"id": 2}, "skip"]}
    nested = {"data": {"included": [{"id": 3}, None]}}
    data_list = {"data": [{"id": 4}, "skip"]}
    raw_list = [{"id": 5}, "skip"]

    assert scraper._extract_included_items(direct) == [{"id": 1}, {"id": 2}]
    assert scraper._extract_included_items(nested) == [{"id": 3}]
    assert scraper._extract_included_items(data_list) == [{"id": 4}]
    assert scraper._extract_included_items(raw_list) == [{"id": 5}]


def test_extract_book_ids_filters_non_books_and_missing_ids(scraper):
    payload = {
        "included": [
            {"type": "book", "id": 100},
            {"type": "book:owned", "id": "200"},
            {"type": "author", "id": 300},
            {"type": "book", "title": "no-id"},
        ]
    }

    assert scraper._extract_book_ids(payload) == ["100", "200"]


def test_build_browser_paging_strategies(scraper):
    strategies = scraper._build_browser_paging_strategies(1000)
    names = [name for name, _ in strategies]

    assert names == [
        "page_per_page",
        "page_limit",
        "offset_per_page",
        "offset_limit",
        "start_limit",
    ]

    strategy_map = {name: builder for name, builder in strategies}
    assert strategy_map["page_per_page"](2) == {"page": 2, "per_page": 1000}
    assert strategy_map["offset_per_page"](3) == {"offset": 2000, "per_page": 1000}


def test_detect_browser_paging_strategy_chooses_first_with_new_ids(scraper, monkeypatch):
    payloads = {
        ("page_per_page", 1): {"included": [{"type": "book", "id": "a"}]},
        ("page_per_page", 2): {"included": [{"type": "book", "id": "a"}]},
        ("page_limit", 1): {"included": [{"type": "book", "id": "x"}]},
        ("page_limit", 2): {"included": [{"type": "book", "id": "y"}]},
    }

    def fake_fetch(params):
        if "per_page" in params and "page" in params:
            key = ("page_per_page", params["page"])
        elif "limit" in params and "page" in params:
            key = ("page_limit", params["page"])
        else:
            raise RuntimeError("unexpected strategy")
        return payloads[key]

    monkeypatch.setattr(scraper, "_browser_fetch_payload", fake_fetch)

    result = scraper._detect_browser_paging_strategy(10)

    assert result is not None
    strategy_name, _, first_payload = result
    assert strategy_name == "page_limit"
    assert first_payload == payloads[("page_limit", 1)]


def test_detect_browser_paging_strategy_returns_none_when_all_duplicate(scraper, monkeypatch):
    def fake_fetch(params):
        return {"included": [{"type": "book", "id": "same"}]}

    monkeypatch.setattr(scraper, "_browser_fetch_payload", fake_fetch)

    assert scraper._detect_browser_paging_strategy(10) is None


@pytest.mark.parametrize(
    "status_code,json_payload,expected",
    [
        (200, {"status": "ok"}, True),
        (200, {"status": "error_login"}, False),
        (403, {"status": "ok"}, False),
    ],
)
def test_is_logged_in_api(scraper, monkeypatch, status_code, json_payload, expected):
    def fake_get(*args, **kwargs):
        return SimpleNamespace(status_code=status_code, json=lambda: json_payload)

    monkeypatch.setattr(scraper.session, "get", fake_get)

    assert scraper._is_logged_in_api() is expected


def test_is_logged_in_api_handles_exceptions(scraper, monkeypatch):
    def fake_get(*args, **kwargs):
        raise RuntimeError("network")

    monkeypatch.setattr(scraper.session, "get", fake_get)

    assert scraper._is_logged_in_api() is False


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://readmoo.com/library", True),
        ("https://readmoo.com/home", True),
        ("https://next.readmoo.com/zh-TW/auth/signin", False),
        ("https://member.readmoo.com/#/auth/signin", False),
        ("https://readmoo.com/#/library", True),
    ],
)
def test_check_login_url_rules(scraper, url, expected):
    scraper.driver = SimpleNamespace(current_url=url)
    assert scraper.check_login() is expected


def test_check_login_handles_driver_error(scraper):
    class BrokenDriver:
        @property
        def current_url(self):
            raise RuntimeError("boom")

    scraper.driver = BrokenDriver()
    assert scraper.check_login() is False


def test_sync_cookies_to_session(scraper):
    class FakeDriver:
        def get_cookies(self):
            return [
                {"name": "a", "value": "1", "domain": ".readmoo.com", "path": "/"},
                {"name": "b", "value": "2", "domain": ".readmoo.com", "path": "/"},
            ]

    scraper.driver = FakeDriver()
    scraper._sync_cookies_to_session()

    assert scraper.session.cookies.get("a") == "1"
    assert scraper.session.cookies.get("b") == "2"


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_get_books_uses_browser_path_and_stops_by_total_hint(scraper, monkeypatch):
    scraper.id_token = "token"
    scraper.driver = object()

    def make_books(prefix):
        return [
            {"type": "book", "id": f"{prefix}-{i}", "title": f"{prefix} {i}", "author": "A"}
            for i in range(1000)
        ]

    first_payload = {
        "total": 2000,
        "included": make_books("Book1"),
    }

    def fake_detect(_per_page):
        return "offset_per_page", (lambda page: {"offset": (page - 1) * 1000, "per_page": 1000}), first_payload

    def fake_browser_fetch(_params):
        return {
            "total": 2000,
            "included": make_books("Book2"),
        }

    monkeypatch.setattr(scraper, "_detect_browser_paging_strategy", fake_detect)
    monkeypatch.setattr(scraper, "_browser_fetch_payload", fake_browser_fetch)

    def should_not_call_requests(*_args, **_kwargs):
        raise AssertionError("requests fallback should not be called")

    monkeypatch.setattr(scraper.session, "get", should_not_call_requests)

    books = scraper.get_books()

    assert len(books) == 2000
    assert books[0]["title"] == "Book1 0"
    assert books[-1]["title"] == "Book2 999"
    assert scraper.app.last_status[0].endswith("2000/2000 本）...")


def test_get_books_falls_back_to_requests_when_browser_strategy_missing(scraper, monkeypatch):
    scraper.driver = object()
    monkeypatch.setattr(scraper, "_detect_browser_paging_strategy", lambda _per_page: None)

    payload = {
        "status": "ok",
        "total": 1,
        "included": [{"type": "book", "id": "id-1", "title": "Only", "author": "One"}],
    }

    monkeypatch.setattr(scraper.session, "get", lambda *_args, **_kwargs: FakeResponse(200, payload))

    books = scraper.get_books()

    assert books == [{"title": "Only", "author": "One"}]


def test_get_books_requests_path_stops_after_three_duplicate_pages(scraper, monkeypatch):
    scraper.driver = None

    def make_page(book_id):
        included = [{"type": "book", "id": book_id, "title": "T", "author": "A"}]
        included.extend({"type": "author", "id": f"a{i}"} for i in range(999))
        return {"status": "ok", "included": included}

    responses = iter([
        FakeResponse(200, make_page("b1")),
        FakeResponse(200, make_page("b1")),
        FakeResponse(200, make_page("b1")),
        FakeResponse(200, make_page("b1")),
    ])

    monkeypatch.setattr(scraper.session, "get", lambda *_args, **_kwargs: next(responses))

    books = scraper.get_books()

    assert books == [{"title": "T", "author": "A"}]
