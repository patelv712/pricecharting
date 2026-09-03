from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path


class FetchError(RuntimeError):
    """Raised when a public Figure Realm page cannot be safely retrieved."""


class CacheOnlyFetcher:
    """Read browser-captured HTML without launching an automated browser."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    async def __aenter__(self) -> CacheOnlyFetcher:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.html"

    async def get(self, url: str) -> str:
        cache_path = self._cache_path(url)
        if not cache_path.exists():
            raise FetchError(f"browser capture is missing: {url}")
        return cache_path.read_text(encoding="utf-8")


class BrowserFetcher:
    def __init__(
        self,
        cache_dir: Path,
        *,
        delay_seconds: float = 1.0,
        headless: bool = True,
        browser_channel: str = "chrome",
        timeout_ms: int = 30_000,
        stealth: bool = False,
        patchright: bool = False,
        block_assets: bool = False,
        request_interval_seconds: float = 0.0,
        profile_dir: Path | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.delay_seconds = delay_seconds
        self.headless = headless
        self.browser_channel = browser_channel
        self.timeout_ms = timeout_ms
        self.stealth = stealth
        self.patchright = patchright
        self.block_assets = block_assets
        self.request_interval_seconds = request_interval_seconds
        self.profile_dir = profile_dir or cache_dir.parent / "patchright-profile"
        self._request_lock = asyncio.Lock()
        self._next_request_at = 0.0
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def __aenter__(self) -> BrowserFetcher:
        try:
            if self.patchright:
                from patchright.async_api import async_playwright
            else:
                from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - exercised only without live dependency
            raise FetchError("Playwright is not installed; run: pip install -e '.[dev]'") from exc

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        try:
            if self.patchright:
                self.profile_dir.mkdir(parents=True, exist_ok=True)
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    channel=self.browser_channel,
                    headless=self.headless,
                    no_viewport=True,
                )
            else:
                launch_args = ["--disable-blink-features=AutomationControlled"] if self.stealth else []
                self._browser = await self._playwright.chromium.launch(
                    channel=self.browser_channel,
                    headless=self.headless,
                    args=launch_args,
                )
        except Exception as exc:
            await self._playwright.stop()
            raise FetchError(
                f"could not launch the {self.browser_channel!r} browser channel: {exc}"
            ) from exc

        if not self.patchright:
            self._context = await self._browser.new_context()
        if self.stealth and not self.patchright:
            try:
                from playwright_stealth import Stealth
            except ImportError as exc:  # pragma: no cover - dependency contract
                raise FetchError(
                    "stealth mode requires playwright-stealth; reinstall with pip install -e '.[dev]'"
                ) from exc
            await Stealth(
                navigator_languages_override=("en-US", "en"),
            ).apply_stealth_async(self._context)
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        # Patchright normally keeps the browser's network stack intact. Owners can explicitly
        # trade that camouflage for faster collection by blocking non-HTML assets.
        if not self.patchright or self.block_assets:
            await self._page.route("**/*", self._route_request)
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def _route_request(self, route) -> None:
        request = route.request
        url = request.url.casefold()
        # Every field collected by this importer is present in Figure Realm's
        # server-rendered HTML. Permit the ordinary Cloudflare browser-check
        # resources if the site presents them, but skip unrelated page assets.
        cloudflare_check = "challenges.cloudflare.com" in url or "/cdn-cgi/" in url
        if request.resource_type != "document" and not cloudflare_check:
            await route.abort()
        else:
            await route.continue_()

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.html"

    @staticmethod
    def _looks_like_access_challenge(html: str) -> bool:
        lowered = html.casefold()
        return any(
            marker in lowered
            for marker in (
                "captcha",
                "access denied",
                "cf-chl-",
                "<title>just a moment...</title>",
                "enable javascript and cookies to continue",
            )
        )

    def _read_cached_html(self, cache_path: Path) -> str | None:
        if not cache_path.exists():
            return None
        html = cache_path.read_text(encoding="utf-8")
        if self._looks_like_access_challenge(html):
            # A challenge response is not product data and must be fetched again.
            cache_path.unlink()
            return None
        return html

    async def _read_page_content(self, page=None) -> str:
        page = page or self._page
        if page is None:
            raise FetchError("browser fetcher is not open")
        for attempt in range(3):
            try:
                return await page.content()
            except Exception as exc:
                navigating = "page is navigating and changing the content" in str(exc).casefold()
                if not navigating or attempt == 2:
                    raise FetchError(f"could not read the browser page: {exc}") from exc
                await page.wait_for_timeout(500)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
                except Exception:
                    # A redirect may replace the frame again. The bounded content retry is the
                    # authoritative check and will surface a FetchError after three attempts.
                    pass
        raise FetchError("could not read the browser page after navigation")

    async def _goto_page(self, url: str, page=None):
        page = page or self._page
        if page is None:
            raise FetchError("browser fetcher is not open")
        for attempt in range(3):
            try:
                return await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            except Exception as exc:
                timed_out = "timeout" in type(exc).__name__.casefold() or "timeout" in str(
                    exc
                ).casefold()
                if not timed_out or attempt == 2:
                    raise FetchError(f"could not navigate to {url}: {exc}") from exc
                await page.wait_for_timeout(1_000)
        raise FetchError(f"could not navigate to {url} after retries")

    async def _wait_for_request_slot(self) -> None:
        """Space navigation starts across every page in this browser context."""
        if not self.request_interval_seconds:
            return
        async with self._request_lock:
            loop = asyncio.get_running_loop()
            wait_seconds = self._next_request_at - loop.time()
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._next_request_at = loop.time() + self.request_interval_seconds

    async def _get_with_page(self, url: str, page) -> str:
        cache_path = self._cache_path(url)
        cached_html = self._read_cached_html(cache_path)
        if cached_html is not None:
            return cached_html

        response = None
        status = 0
        for attempt in range(3):
            await self._wait_for_request_slot()
            response = await self._goto_page(url, page)
            status = response.status if response else 0
            if status not in {500, 502, 503, 504, 520} or attempt == 2:
                break
            await page.wait_for_timeout(2_000 * (attempt + 1))
        if status == 403 and self.patchright:
            # Give Cloudflare's non-interactive browser check time to complete naturally. Manual
            # Turnstile/CAPTCHA pages are still detected below and never solved automatically.
            await page.wait_for_timeout(8_000)
            html = await self._read_page_content(page)
            if "seriesitemlist" not in html and "action=actionfigure" not in html:
                raise FetchError("Figure Realm returned HTTP 403 after the owner test wait")
            status = 200
        if status in {401, 403, 429}:
            raise FetchError(f"Figure Realm returned HTTP {status}; stopping without bypassing it")
        if status >= 400 or status == 0:
            raise FetchError(f"Figure Realm returned HTTP {status} for {url}")

        html = await self._read_page_content(page)
        if self._looks_like_access_challenge(html) and self.patchright and not self.block_assets:
            # Allow Cloudflare's ordinary, non-interactive browser check to finish. This never
            # clicks or solves a CAPTCHA; an unresolved challenge still stops collection.
            await page.wait_for_timeout(8_000)
            html = await self._read_page_content(page)
        if self._looks_like_access_challenge(html):
            raise FetchError("Figure Realm presented an access challenge; stopping")

        temporary = cache_path.with_suffix(".tmp")
        temporary.write_text(html, encoding="utf-8")
        temporary.replace(cache_path)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        return html

    async def get(self, url: str) -> str:
        if self._page is None:
            raise FetchError("browser fetcher is not open")
        return await self._get_with_page(url, self._page)

    async def get_many(self, urls: list[str], *, concurrency: int) -> list[str]:
        """Fetch independent pages with a small reusable browser-page pool."""
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if self._page is None or self._context is None:
            raise FetchError("browser fetcher is not open")
        if concurrency == 1 or len(urls) < 2:
            return [await self.get(url) for url in urls]

        # Resolve cached URLs before creating worker pages. During a resumed
        # category scrape, thousands of complete batches may be read from disk;
        # opening and closing a Chrome page for every one of those batches can
        # eventually close or destabilize the browser context before collection
        # reaches the first missing URL.
        results = [""] * len(urls)
        pending: list[tuple[int, str]] = []
        for result_index, url in enumerate(urls):
            cache_path = self._cache_path(url)
            cached_html = self._read_cached_html(cache_path)
            if cached_html is None:
                pending.append((result_index, url))
            else:
                results[result_index] = cached_html
        if not pending:
            return results

        worker_count = min(concurrency, len(pending))
        pages = [self._page]
        for _ in range(worker_count - 1):
            page = await self._context.new_page()
            if not self.patchright or self.block_assets:
                await page.route("**/*", self._route_request)
            pages.append(page)

        assignments = [pending[index::worker_count] for index in range(worker_count)]

        async def worker(page, items: list[tuple[int, str]]) -> None:
            for result_index, url in items:
                results[result_index] = await self._get_with_page(url, page)

        tasks = [
            asyncio.create_task(worker(page, items))
            for page, items in zip(pages, assignments, strict=True)
        ]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            for page in pages[1:]:
                await page.close()
        return results
