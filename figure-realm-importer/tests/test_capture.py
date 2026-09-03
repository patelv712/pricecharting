import hashlib
import json
from pathlib import Path

import pytest

from figure_realm_importer.browser import FetchError
from figure_realm_importer.capture import import_capture_bundle


def test_import_capture_bundle(tmp_path: Path) -> None:
    url = "https://www.figurerealm.com/universe?index=S"
    bundle = tmp_path / "capture.json"
    bundle.write_text(
        json.dumps({"schemaVersion": 1, "pages": [{"url": url, "html": "<html>Scooby</html>"}]}),
        encoding="utf-8",
    )
    cache = tmp_path / "cache"

    assert import_capture_bundle(bundle, cache) == 1
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    assert (cache / f"{digest}.html").read_text(encoding="utf-8") == "<html>Scooby</html>"


def test_import_capture_rejects_other_hosts(tmp_path: Path) -> None:
    bundle = tmp_path / "capture.json"
    bundle.write_text(
        json.dumps({"schemaVersion": 1, "pages": [{"url": "https://example.test/", "html": "ok"}]}),
        encoding="utf-8",
    )

    with pytest.raises(FetchError, match="unexpected URL"):
        import_capture_bundle(bundle, tmp_path / "cache")
