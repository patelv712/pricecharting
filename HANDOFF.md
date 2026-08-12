# PriceCharting Sale Reviewer POC Handoff

## Delivery Boundary

This repository is a recommendation-only proof of concept for inspecting questionable eBay sales
against PriceCharting catalog, title, condition, and public image evidence. Every recommendation
requires human review. The POC does not automatically modify PriceCharting data and is not approved
for unattended production use.

The active review policy is `2026-08-10-catalog-evidence-v8`. Earlier evaluation artifacts are
retained for audit only and are not performance claims for the active policy. In particular, legacy
prediction files that asked a model for confidence are superseded.

## Recipient Setup

Requirements:

- Python 3.12
- A PriceCharting API token owned or approved by the recipient
- A Gemini API key owned or approved by the recipient for multimodal mode

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
.venv/bin/pytest
.venv/bin/pcqc serve
```

Open `http://127.0.0.1:8000/`. OpenAPI documentation is at
`http://127.0.0.1:8000/docs`.

Credentials are deliberately absent from Git. Never reuse a developer's personal API key for a
recipient deployment. Populate `.env` locally:

```dotenv
PRICECHARTING_API_TOKEN=
LLM_API_KEY=
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
LLM_MODEL=
FINISH_LLM_MODEL=
```

## Verification

Run the offline handoff check:

```bash
./scripts/verify_handoff.sh
```

It runs the test suite, validates the synthetic sample, and confirms policy metadata. It makes no
PriceCharting, eBay, or Gemini calls and spends no API credits.

The deeper artifact demonstration requires an authorized copy of the original sales export:

```bash
SALES_CSV=/path/to/PRICECHARTING.csv ./scripts/demo_poc.sh
```

The source export is not included in this repository.

## Console Demonstration

1. Start the service with `.venv/bin/pcqc serve`.
2. Select **New run** and upload a compatible CSV.
3. Choose either a seeded random sample or specific rows searchable by listing ID and title.
4. Use deterministic mode for an offline workflow demonstration or Gemini plus image evidence for
   the multimodal workflow.
5. Compare the POC conclusion with the historical PriceCharting outcome when that metadata exists.
6. Inspect catalog identity, finish/foil, language, printing, packaging, and replacement evidence.
7. Record human sale-validity, product-assignment, and condition-assignment judgments.
8. Export the review results as CSV.

Only selected rows are enriched or sent to the configured model provider.

## Input Contract

Operational CSV uploads require:

- `identifier`
- `unified-id`
- `product-title`
- `sale-title`
- `sale-amount-pennies`
- `broad-category`
- `condition-id`

`picture-url` and historical review fields are optional for operational uploads. Labeled evaluation
commands require the historical fields documented in `docs/questionable-sales-review-design.md`.

## Stored Data

The local console stores run records under `cache/console-runs/`. The cache may also contain fetched
listing images, catalog images, product metadata, and search results. `cache/` is excluded from Git.
Delete or retain it according to PriceCharting's approved data-retention policy.

Human adjudication is stored in the local run JSON and included in CSV exports. The JSON store is
appropriate for a local POC, not a multi-user production service.

## Known Limitations

- The active v8 policy has not received a fresh independent validation and untouched holdout.
- Historical `deleted` records do not expose the internal deletion reason and are not authoritative
  product-match ground truth.
- Historical `needsMod` final outcomes cannot be reconstructed from the public export.
- Delete-versus-reassign thresholds remain a PriceCharting business-policy decision.
- One listing image may not prove finish, authenticity, quantity, or all included items.
- Catalog URL construction is heuristic when a canonical product URL is unavailable from the API.
- All outcomes require a person; model output is not an automated mutation instruction.
- The local web service has no authentication, durable database, or per-user spend controls. Do not
  expose it directly to the public internet.

## Production Work Not Included

A production deployment requires authentication, authorization, durable queueing and storage,
secrets management, provider-spend limits, observability, backups, retention enforcement, and a
shadow deployment with independently adjudicated outcomes.

## Primary Documents

- `docs/questionable-sales-review-design.md`: architecture and evaluation methodology
- `docs/poc-executive-report.md`: current decision and evidence boundary
- `docs/full-discrepancy-audit.md`: manual discrepancy analysis
- `docs/finish-classification-design.md`: finish and foil subsystem
- `README.md`: commands and developer setup
