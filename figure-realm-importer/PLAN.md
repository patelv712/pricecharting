# Figure Realm Importer Plan

## Goal

Build a resumable, auditable tool that discovers Figure Realm's public action-figure catalog,
stores the source metadata locally, proposes PriceCharting sets and product names, and exports CSV
files in PriceCharting's required format.

The collector uses browser-backed page loads because the catalog is server-rendered HTML and direct
HTTP requests receive a 403. For the site-owner-authorized pilot, an opt-in Patchright profile can
reduce automated-browser fingerprinting. It does not solve CAPTCHAs or bypass authentication.

## Current findings

- Figure Realm is organized as index -> universe -> series/checklist -> figure.
- Some index entries link directly to a checklist; others link to a universe containing multiple
  manufacturer/series combinations.
- Large checklists expose normal pagination links such as `ns=100`.
- The products are present in the main HTML document; there is no product JSON API.
- The observed `/pickle` background request only retrieves eBay affiliate listings and is not a
  Figure Realm catalog endpoint.
- Checklist pages can provide many products per request. Individual detail pages should be opened
  only for fields unavailable from the checklist.

## Implementation phases

### 1. Lock the import contracts

- Obtain the PriceCharting set-import CSV template.
- Treat each Figure Realm subseries as part of the PriceCharting set identity.
- Define the canonical PriceCharting set-name pattern.
- Decide whether images are excluded, exported as URLs, or downloaded under explicit permission.
- Decide which Figure Realm records are in scope: figures, multipacks, vehicles, accessories,
  playsets, statues, and other checklist entries.
- Confirm authorization and acceptable crawl rate for bulk reuse of Figure Realm metadata.

Exit condition: written set and product schemas with examples and no unresolved required fields.

### 2. Build a small access and parsing spike

- Create an independent Python package and command-line interface in this directory.
- Use Playwright with a normal browser session to load public pages.
- Block unnecessary images, advertisements, stylesheets, fonts, and the eBay `/pickle` request.
- Capture representative fixtures for a direct checklist, a multi-series universe, a paginated
  checklist, a product with an item number, and a product without one.
- Parse only stored fixtures in automated tests; tests must not depend on the live website.
- Measure request timing and verify graceful handling of 403, 429, 5xx, CAPTCHA, and changed HTML.

Exit condition: a command extracts validated structured records from the representative pages.

### 3. Implement catalog discovery

- Seed the frontier with `#` and `A` through `Z` universe-index pages.
- Classify discovered links as universe, series/checklist, subseries, or figure links.
- Deduplicate using Figure Realm's numeric universe, series, subseries, and figure IDs.
- Follow server-provided pagination links rather than constructing unverified page numbers.
- Persist the frontier and completion state in SQLite after every successfully parsed page.
- Make interrupted runs resume without repeating completed work.

Exit condition: a discovery-only run reports exact counts of universes, series, pages, and figures.

### 4. Collect and normalize source metadata

- Store raw source values separately from normalized PriceCharting values.
- Capture figure name, item/model number, universe, series, subseries, manufacturer, release year,
  source ID, source URL, and any permitted image URLs.
- Visit figure detail pages only when required fields are absent from the checklist page.
- Record provenance for every field so questionable transformations can be audited.
- Retain parse failures and incomplete records in a review queue instead of silently dropping them.

Exit condition: the local catalog reconciles to discovery counts and has explicit completeness
metrics for every required field.

### 5. Propose and create PriceCharting sets

- Apply the approved set-granularity and naming rules.
- Export a set proposal with Figure Realm IDs, manufacturer, year range, product count, and source
  URL for review.
- Produce the PriceCharting set-import CSV once its schema is supplied.
- Import PriceCharting's resulting set-name-to-`console-id` mapping.
- Fail closed on missing or duplicate set mappings.

Exit condition: every in-scope figure maps to exactly one approved `console-id`.

### 6. Generate PriceCharting product names

- Start with the source item name as the plain name whenever it represents the printed name.
- Preserve item/model numbers in `model-number`, not as an invented variant.
- Group possible collisions by approved set, normalized plain name, and model number.
- Add no variant when the group contains one product.
- For collisions, choose the smallest observable marketplace descriptor, prioritizing outfit/color,
  pose, accessory, package, retailer/exclusive, scale, and then year when meaningful. For Funko,
  prioritize Figure Realm's `Exclusive` value as the store/exclusive stamp, adding another visible
  descriptor only when multiple versions share that value.
- Put unresolved or unreliable distinctions in a human-review CSV instead of guessing.
- Keep every naming transformation deterministic and explainable.

Exit condition: no duplicate `(console-id, product-name, model-number)` keys and every bracketed
variant has recorded source evidence.

### 7. Export and validate products

- Emit exactly these columns in order:
  `product-name,model-number,genre,console-id,release-date,figure-realm-link`.
- Set `genre` to `Action Figures`.
- Preserve a source year as a four-digit `release-date`.
- Leave unavailable model numbers blank.
- Include the Figure Realm detail-page URL in `figure-realm-link`.
- Validate CSV quoting, UTF-8 encoding, required values, set mappings, duplicate keys, and dates.
- Produce a separate audit report containing source IDs, URLs, warnings, and transformation reasons;
  do not add audit-only columns to the PriceCharting import file.

Exit condition: the importer CSV passes automated schema and consistency checks.

### 8. Pilot before the full crawl

- Run one small direct checklist and one large, paginated, variant-heavy universe.
- Have PriceCharting review the proposed sets, names, variants, omissions, and CSV compatibility.
- Correct rules in code and rerun the same source fixtures to prove deterministic output.
- Only after pilot approval, run the complete resumable crawl at the approved rate.

Exit condition: PriceCharting accepts the pilot CSV and naming behavior.

## Planned project layout

```text
figure-realm-importer/
  README.md
  PLAN.md
  pyproject.toml
  src/figure_realm_importer/
    cli.py
    browser.py
    discovery.py
    parsers.py
    storage.py
    naming.py
    export.py
    models.py
  tests/
    fixtures/
  config/
    naming-policy.json
  output/                 # ignored generated files
  cache/                  # ignored browser/page cache and SQLite state
```

## Immediate next steps after the completed Scooby-Doo pilot

1. Review the 62 canonical subseries-level Scooby-Doo set proposals and 347 product names with
   PriceCharting.
2. Get the set-import CSV template and approve the set/image/scope decisions.
3. Create those sets and replace the proposed names in `console-id` with their assigned set codes.
4. Have PriceCharting test-import the regenerated pilot CSV.
5. Add persistent discovery/frontier state, then expand discovery to `#` and A-Z at the
   owner-approved request rate.

## Definition of done

- The project installs and runs independently of `pcqc`.
- A stopped crawl resumes safely and does not duplicate records.
- Live-site changes or blocks produce visible errors, not partial silent exports.
- Every output value is traceable to a source field or documented deterministic rule.
- No required product fields are invented.
- The final import contains no duplicate product keys or unresolved set IDs.
- A separate review report contains every ambiguous, excluded, or incomplete record.
