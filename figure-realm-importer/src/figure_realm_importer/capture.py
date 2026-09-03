from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from .browser import FetchError


ALLOWED_HOSTS = {"figurerealm.com", "www.figurerealm.com"}


def import_capture_bundle(bundle_path: Path, cache_dir: Path) -> int:
    try:
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FetchError(f"could not read browser capture {bundle_path}: {exc}") from exc

    if payload.get("schemaVersion") != 1 or not isinstance(payload.get("pages"), list):
        raise FetchError("browser capture must have schemaVersion 1 and a pages array")

    cache_dir.mkdir(parents=True, exist_ok=True)
    imported = 0
    seen: set[str] = set()
    for page in payload["pages"]:
        if not isinstance(page, dict):
            raise FetchError("browser capture contains a non-object page")
        url = page.get("url")
        html = page.get("html")
        if not isinstance(url, str) or not isinstance(html, str):
            raise FetchError("every captured page must contain string url and html fields")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise FetchError(f"capture contains an unexpected URL: {url}")
        lowered = html.casefold()
        if "captcha" in lowered or "access denied" in lowered or "cf-chl-" in lowered:
            raise FetchError(f"capture contains an access challenge: {url}")
        if url in seen:
            continue
        seen.add(url)

        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        destination = cache_dir / f"{digest}.html"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(html, encoding="utf-8")
        temporary.replace(destination)
        imported += 1
    return imported
