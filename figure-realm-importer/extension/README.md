# Browser capture helper

Figure Realm currently returns a Cloudflare 403 to standalone Playwright, including a visible
Playwright-launched Chrome window. It loads normally in an established user Chrome session. This
small unpacked extension performs ordinary same-origin requests from an open Figure Realm tab and
stops on any HTTP error or access challenge. It does not solve or bypass CAPTCHAs.

## Install for local testing

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Choose **Load unpacked** and select this `extension` directory.
4. Open the Scooby-Doo universe page on Figure Realm.
5. Open the extension and choose **Capture Scooby-Doo**.
6. Keep the tab open until `figure-realm-scooby-doo-capture.json` downloads.

Import the capture and produce CSV files:

```bash
.venv/bin/figure-realm-poc \
  --capture-json /path/to/figure-realm-scooby-doo-capture.json \
  --detail-mode available \
  --output-dir output/scooby-doo
```
