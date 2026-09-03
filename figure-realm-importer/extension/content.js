(() => {
  const SCOOBY_URL = "https://www.figurerealm.com/universe?action=serieslist&universeid=2400&universe=scoobydoo";
  const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

  function report(message, options = {}) {
    chrome.runtime.sendMessage({type: "capture-status", message, ...options}).catch(() => {});
  }

  async function fetchHtml(url) {
    const response = await fetch(url, {credentials: "include", cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
    const html = await response.text();
    if (/captcha|access denied|cf-chl-|just a moment/i.test(html)) {
      throw new Error(`Access challenge at ${url}`);
    }
    await delay(1000);
    return html;
  }

  function documentFor(html) {
    return new DOMParser().parseFromString(html, "text/html");
  }

  function absoluteUrl(value, base) {
    return new URL(value, base).href;
  }

  async function captureScooby(sampleDetails) {
    const pages = [];
    const universeHtml = await fetchHtml(SCOOBY_URL);
    pages.push({url: SCOOBY_URL, html: universeHtml});
    const universeDocument = documentFor(universeHtml);
    const seriesUrls = [...universeDocument.querySelectorAll('a[href*="action=seriesitemlist"]')]
      .map((anchor) => absoluteUrl(anchor.getAttribute("href"), SCOOBY_URL))
      .filter((value, index, values) => values.indexOf(value) === index);
    if (!seriesUrls.length) throw new Error("No Scooby-Doo series links were found.");

    const detailSamples = [];
    for (let index = 0; index < seriesUrls.length; index += 1) {
      report(`Checklist ${index + 1}/${seriesUrls.length}`);
      const pageUrl = new URL(seriesUrls[index]);
      pageUrl.searchParams.set("ssid", "-1");
      pageUrl.searchParams.set("mode", "1");
      const seen = new Set();
      let nextUrl = pageUrl.href;
      let firstDetail = null;
      while (nextUrl && !seen.has(nextUrl)) {
        seen.add(nextUrl);
        const html = await fetchHtml(nextUrl);
        pages.push({url: nextUrl, html});
        const parsed = documentFor(html);
        firstDetail ||= parsed.querySelector('.checkminihdr a[href*="action=actionfigure"]');
        const next = [...parsed.querySelectorAll("a")].find((anchor) => /^\s*Next(?:\s+Page)?\s*$/i.test(anchor.textContent || ""));
        nextUrl = next ? absoluteUrl(next.getAttribute("href"), nextUrl) : null;
      }
      if (firstDetail) detailSamples.push(absoluteUrl(firstDetail.getAttribute("href"), seriesUrls[index]));
    }

    if (sampleDetails) {
      for (let index = 0; index < detailSamples.length; index += 1) {
        report(`Detail sample ${index + 1}/${detailSamples.length}`);
        const url = detailSamples[index];
        pages.push({url, html: await fetchHtml(url)});
      }
    }

    const payload = JSON.stringify({
      schemaVersion: 1,
      capturedAt: new Date().toISOString(),
      universeUrl: SCOOBY_URL,
      pages,
    });
    const blobUrl = URL.createObjectURL(new Blob([payload], {type: "application/json"}));
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = "figure-realm-scooby-doo-capture.json";
    link.style.display = "none";
    document.documentElement.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 30_000);
    report(`Captured ${pages.length} pages. JSON download started.`, {done: true});
  }

  let running = false;
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "capture-scooby") return false;
    if (running) {
      sendResponse({message: "A capture is already running."});
      return false;
    }
    running = true;
    captureScooby(Boolean(message.sampleDetails))
      .catch((error) => report(`Stopped: ${error.message}`, {error: true}))
      .finally(() => { running = false; });
    sendResponse({message: "Capture started. Keep this tab open."});
    return false;
  });
})();
