import asyncio
import hashlib
from pathlib import Path

import pytest

from figure_realm_importer.browser import BrowserFetcher, CacheOnlyFetcher, FetchError


def test_cache_only_fetcher_reads_url_hash(tmp_path: Path) -> None:
    url = "https://www.figurerealm.com/universe?index=S"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    (tmp_path / f"{digest}.html").write_text("<html>Scooby-Doo</html>", encoding="utf-8")

    async def read() -> str:
        async with CacheOnlyFetcher(tmp_path) as fetcher:
            return await fetcher.get(url)

    assert asyncio.run(read()) == "<html>Scooby-Doo</html>"


def test_cache_only_fetcher_reports_missing_url(tmp_path: Path) -> None:
    async def read() -> None:
        async with CacheOnlyFetcher(tmp_path) as fetcher:
            await fetcher.get("https://example.test/missing")

    with pytest.raises(FetchError, match="browser capture is missing"):
        asyncio.run(read())


def test_browser_fetcher_retries_content_during_redirect(tmp_path: Path) -> None:
    class RedirectingPage:
        def __init__(self) -> None:
            self.calls = 0

        async def content(self) -> str:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError(
                    "Unable to retrieve content because the page is navigating and changing the content"
                )
            return "<html>ready</html>"

        async def wait_for_timeout(self, milliseconds: int) -> None:
            assert milliseconds == 500

        async def wait_for_load_state(self, state: str, timeout: int) -> None:
            assert state == "domcontentloaded"
            assert timeout == 30_000

    fetcher = BrowserFetcher(tmp_path)
    page = RedirectingPage()
    fetcher._page = page

    assert asyncio.run(fetcher._read_page_content()) == "<html>ready</html>"
    assert page.calls == 2


def test_browser_fetcher_retries_navigation_timeout(tmp_path: Path) -> None:
    class Response:
        status = 200

    class TimingOutPage:
        def __init__(self) -> None:
            self.calls = 0

        async def goto(self, url: str, wait_until: str, timeout: int):
            self.calls += 1
            assert url == "https://example.test/item"
            assert wait_until == "domcontentloaded"
            assert timeout == 30_000
            if self.calls == 1:
                raise TimeoutError("navigation timeout")
            return Response()

        async def wait_for_timeout(self, milliseconds: int) -> None:
            assert milliseconds == 1_000

    fetcher = BrowserFetcher(tmp_path)
    page = TimingOutPage()
    fetcher._page = page

    response = asyncio.run(fetcher._goto_page("https://example.test/item"))
    assert response.status == 200
    assert page.calls == 2


def test_browser_fetcher_get_many_reads_complete_cached_batch_without_new_pages(
    tmp_path: Path,
) -> None:
    urls = [f"https://example.test/item/{index}" for index in range(5)]
    for index, url in enumerate(urls):
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        (tmp_path / f"{digest}.html").write_text(f"page-{index}", encoding="utf-8")

    class Page:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class Context:
        def __init__(self) -> None:
            self.created: list[Page] = []

        async def new_page(self) -> Page:
            page = Page()
            self.created.append(page)
            return page

    fetcher = BrowserFetcher(tmp_path, patchright=True)
    fetcher._page = Page()
    fetcher._context = Context()

    result = asyncio.run(fetcher.get_many(urls, concurrency=3))

    assert result == [f"page-{index}" for index in range(5)]
    assert fetcher._context.created == []


def test_browser_fetcher_discards_cached_access_challenge(tmp_path: Path) -> None:
    url = "https://www.figurerealm.com/actionfigure?action=actionfigure&id=1"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cache_path = tmp_path / f"{digest}.html"
    cache_path.write_text(
        "<html><title>Just a moment...</title>Enable JavaScript and cookies to continue</html>",
        encoding="utf-8",
    )

    fetcher = BrowserFetcher(tmp_path)

    assert fetcher._read_cached_html(cache_path) is None
    assert not cache_path.exists()


def test_browser_fetcher_blocks_assets_but_keeps_html_requests(tmp_path: Path) -> None:
    class Request:
        def __init__(self, resource_type: str, url: str) -> None:
            self.resource_type = resource_type
            self.url = url

    class Route:
        def __init__(self, resource_type: str, url: str) -> None:
            self.request = Request(resource_type, url)
            self.action = ""

        async def abort(self) -> None:
            self.action = "abort"

        async def continue_(self) -> None:
            self.action = "continue"

    fetcher = BrowserFetcher(tmp_path, patchright=True, block_assets=True)
    image = Route("image", "https://www.figurerealm.com/photo.jpg")
    html = Route("document", "https://www.figurerealm.com/actionfigure?id=1")
    ad = Route("script", "https://pagead2.googlesyndication.com/ad.js")
    api = Route("fetch", "https://www.figurerealm.com/background-data")
    cloudflare = Route("script", "https://challenges.cloudflare.com/turnstile/v0/api.js")

    asyncio.run(fetcher._route_request(image))
    asyncio.run(fetcher._route_request(html))
    asyncio.run(fetcher._route_request(ad))
    asyncio.run(fetcher._route_request(api))
    asyncio.run(fetcher._route_request(cloudflare))

    assert image.action == "abort"
    assert html.action == "continue"
    assert ad.action == "abort"
    assert api.action == "abort"
    assert cloudflare.action == "continue"


def test_browser_fetcher_shares_request_interval_across_callers(tmp_path: Path) -> None:
    async def exercise() -> float:
        fetcher = BrowserFetcher(tmp_path, request_interval_seconds=0.01)
        loop = asyncio.get_running_loop()
        started = loop.time()
        await asyncio.gather(
            fetcher._wait_for_request_slot(),
            fetcher._wait_for_request_slot(),
            fetcher._wait_for_request_slot(),
        )
        return loop.time() - started

    assert asyncio.run(exercise()) >= 0.018


def test_browser_fetcher_retries_transient_http_status(tmp_path: Path) -> None:
    class Response:
        def __init__(self, status: int) -> None:
            self.status = status

    class Page:
        def __init__(self) -> None:
            self.goto_calls = 0
            self.waits: list[int] = []

        async def goto(self, url: str, wait_until: str, timeout: int) -> Response:
            self.goto_calls += 1
            return Response(520 if self.goto_calls == 1 else 200)

        async def wait_for_timeout(self, milliseconds: int) -> None:
            self.waits.append(milliseconds)

        async def content(self) -> str:
            return "<html><a href='?action=actionfigure&id=1'>item</a></html>"

    fetcher = BrowserFetcher(tmp_path, delay_seconds=0)
    page = Page()

    html = asyncio.run(fetcher._get_with_page("https://example.test/item", page))

    assert "actionfigure" in html
    assert page.goto_calls == 2
    assert page.waits == [2_000]
