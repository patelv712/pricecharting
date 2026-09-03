# Figure Realm Importer

Standalone project for collecting public action-figure catalog metadata from Figure Realm,
normalizing it to PriceCharting naming conventions, and producing PriceCharting-compatible set
and product CSV files.

This directory is intentionally separate from the `pcqc` eBay sale-quality proof of concept.
It will have its own package, dependencies, commands, tests, cache, and documentation.

## Confirmed product CSV rules

The target columns are:

```text
product-name,model-number,genre,console-id,release-date,figure-realm-link
```

- `genre` is `Action Figures`.
- `release-date` remains a four-digit year when Figure Realm supplies only a year.
- `model-number` is blank when the source provides no item/model number.
- `figure-realm-link` is the source detail-page URL for that figure.
- The POC places the proposed set name in `console-id`, as allowed for the initial handoff. Replace
  it with PriceCharting's assigned set code after the sets are created.
- `product-name` uses the plain item name plus the smallest necessary bracketed variant.
- For Funko collisions, Figure Realm's `Exclusive` value is treated as the store/exclusive stamp
  and is the first-choice bracketed variant. A color or other visible descriptor is added only when
  the store alone is not unique.

See [PLAN.md](PLAN.md) for the implementation sequence and open decisions.

## Scooby-Doo POC

The first pilot targets Figure Realm universe `2400` (Scooby-Doo). The completed owner-authorized
capture contains:

- 16 Figure Realm series/manufacturer combinations
- 19 universe and checklist pages
- 347 unique checklist records, exactly matching the source series counts
- 347 figure detail pages
- 62 canonical subseries-level proposed sets
- 347 import-ready product proposals with no duplicate import keys
- 115 manufacturer/model numbers and 272 release years
- 0 unresolved records in `review.csv`

The POC proposes one PriceCharting set per Figure Realm series, subseries, and manufacturer. This
keeps materially different product lines such as Funko Pop! Vinyl, Dorbz, Soda, and Zag Toys Domez
in separate `console-id` values. Known source aliases are normalized before set creation; Figure
Realm's `Pop! Towns` and `Pop! Town` both map to canonical subseries `Pop! Town`.

## `#` universe-index run

The completed owner-authorized run of `universe?index=1` contains:

- 27 universe/index entries and 39 series
- 236 unique checklist records, exactly matching all 39 source series counts
- 236 figure detail pages
- 74 subseries-level proposed sets
- 234 import-ready products with no duplicate import keys
- 96 manufacturer/model numbers and 202 release years
- 2 unresolved duplicate-name records in `review.csv`

The two review records are McDonald's `Lucky` figures in the same set with blank model numbers and
no marketplace-visible distinguishing variant in the captured metadata.

## Setup

```bash
cd figure-realm-importer
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

## Browser capture

Standalone Playwright sessions currently receive a Cloudflare 403 from Figure Realm. The included
[`extension`](extension/) directory contains a small local Chrome capture helper that uses an
already-open Figure Realm tab, waits one second between requests, and stops on any HTTP failure or
access challenge. See [`extension/README.md`](extension/README.md) for installation steps.

Because the site owner explicitly authorized anti-bot testing, the CLI also has an opt-in
`--stealth` mode that applies basic Playwright fingerprint masking. It remains rate-limited and
still stops on HTTP blocks and CAPTCHAs:

```bash
.venv/bin/figure-realm-poc \
  --stealth \
  --headed \
  --limit-figures 5 \
  --output-dir output/stealth-smoke
```

This mode is intentionally not the default and should only be used against systems where the
operator has authorization.

The basic stealth mode was tested against Figure Realm in both headless and visible Chrome and was
still rejected with HTTP 403. The stronger owner-test option uses Patchright with a dedicated
persistent Chrome profile. It completed all 347 Scooby-Doo detail pages successfully:

```bash
.venv/bin/figure-realm-poc \
  --patchright \
  --headed \
  --delay 1.0 \
  --cache-dir .cache/pages \
  --profile-dir .cache/patchright-profile \
  --output-dir output/scooby-doo-complete
```

Do not point `--profile-dir` at a normal personal Chrome profile. The default is an isolated
project-local test profile.

Collect an entire Figure Realm universe-index page—including entries that link directly to a
checklist—with `--index-url`. Successful pages use the same resumable cache:

```bash
.venv/bin/figure-realm-poc \
  --index-url 'https://www.figurerealm.com/universe?index=1' \
  --patchright \
  --headed \
  --delay 1.0 \
  --cache-dir .cache/pages \
  --profile-dir .cache/patchright-profile \
  --output-dir output/universe-index-number-complete
```

The extension downloads a JSON capture. Convert it to the POC outputs with:

```bash
.venv/bin/figure-realm-poc \
  --capture-json /path/to/figure-realm-scooby-doo-capture.json \
  --detail-mode available \
  --output-dir output/scooby-doo
```

The command writes:

- `products.csv`: import-ready rows using proposed set names in `console-id` and a source link for
  every figure.
- `output/master-workbooks/figure-realm-<category>.xlsx` for index runs: the same product schema,
  with one Excel worksheet tab per universe. Each Figure Realm category (`#`, `A` through `Z`)
  gets a separate workbook in this central directory; the `#` filename uses
  `figure-realm-number.xlsx`. Single-universe runs retain the `products-by-universe.xlsx` filename
  inside their requested output directory. Override the central location with
  `--master-workbook-dir` when needed.
- `set-proposals.csv`: the proposed set hierarchy and source-count reconciliation.
- `audit.csv`: source provenance, subseries, images, detail coverage, and naming reasons.
- `review.csv`: records withheld from `products.csv` because their unique variant is unresolved.

`--detail-mode available` enriches any captured detail pages and explicitly marks all other rows as
not detail-fetched. Use `required` only after every figure detail page has been captured.

Excel worksheet names are sanitized to Excel's 31-character limit and made unique when two
universe names would otherwise produce the same tab name. Model numbers remain text so leading
zeroes are preserved; year-only release dates are stored as numbers. Use `--no-workbook` only when
an Excel artifact is not needed.

## Safari capture pacing

Manual Safari capture uses the conservative limits in `safari-rate-limit.json`:

- Start no more than one Figure Realm page every 60 seconds.
- After 40 page starts, stop for 15 minutes before continuing.
- On the first HTTP 403, stop immediately and wait at least 20 minutes; never retry the denied
  page in a loop.
- Stop on a CAPTCHA or browser challenge instead of attempting to solve or bypass it.

The live pacing checkpoint is written to
`output/universe-index-w-complete/safari-pacing-state.json`. It records the last request time,
pages since the scheduled cooldown, and any active 403 backoff so a restarted session cannot send
an accidental burst. The 60-second value is a minimum start-to-start interval; normal page loading
may make the effective interval longer.

## Current boundary

This is a proof of concept, not yet the full-database crawler. Before expanding beyond the pilot,
PriceCharting still needs to approve the set naming/granularity and image scope. Figure Realm's
owner authorized the browser-fingerprint test used for this pilot. The collector remains
rate-limited, caches successful pages, and stops rather than attempting to solve a CAPTCHA.
