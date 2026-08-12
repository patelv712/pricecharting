# PriceCharting Sale Quality Checker

Proof-of-concept pipeline for reviewing questionable eBay trading-card sales with catalog,
listing-title, price, and image evidence. It includes a transparent rules baseline and an
OpenAI-compatible multimodal reviewer behind the same strict output contract.

## What is implemented

- Validated ingestion of the reviewed-sale export and authoritative status-slug decoding.
- Leakage-resistant train/test assignment grouped by PriceCharting product ID.
- Price-guide CSV indexing plus cached, rate-limited PriceCharting API enrichment.
- Validated eBay and assigned-catalog image retrieval with content limits, hashing, and caching.
- Verified catalog-page identity before catalog artwork can be used as model evidence.
- Cached `/api/products` replacement search with deterministic, auditable ranking and verified
  artwork for the highest-ranked alternatives.
- Deterministic identity gates for event years and explicit finish, printing, language, packaging,
  and card-code markers, independent of model judgment.
- Dedicated finish resolver using catalog metadata, verified finish siblings, reproducible image
  crops, and a narrow Gemini Pro visual task. It never emits confidence or routing.
- Relationship-first evidence features; price is corroboration rather than proof.
- Deterministic baseline, multimodal provider adapter, schema validation, and one repair retry.
- Three-way decision evaluation, exact replacement-condition accuracy, and selective-risk metrics.
- Separate reporting of historical `needsMod` as an escalation proxy, not a semantic sale class.
- CLI workflows and a FastAPI `POST /check-sale` endpoint.

The full design and evaluation rationale are in
[`docs/questionable-sales-review-design.md`](docs/questionable-sales-review-design.md).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
```

Keep credentials in `.env`; it is ignored by Git. The supplied token is intentionally not
stored in this repository or in proof artifacts.

## Commands

```bash
# Validate and profile the complete labeled export.
.venv/bin/pcqc profile \
  --sales /path/to/PRICECHARTING.csv \
  --output reports/proof/data-profile.json

# Evaluate the rules baseline on a product-grouped holdout.
.venv/bin/pcqc baseline \
  --sales /path/to/PRICECHARTING.csv \
  --price-guide /path/to/pokemon-price-guide.csv \
  --output-dir reports/proof

# Prove live product enrichment, image retrieval, evidence, and review.
.venv/bin/pcqc live-smoke \
  --sales /path/to/PRICECHARTING.csv \
  --output reports/proof/live-smoke.json

# Review one export row with either rules or a configured multimodal model.
.venv/bin/pcqc review \
  --sales /path/to/PRICECHARTING.csv \
  --identifier 389374866266 \
  --provider llm \
  --output reports/single-review.json

# Inspect only the finish-resolution subsystem for one row.
.venv/bin/pcqc finish-review \
  --sales /path/to/PRICECHARTING.csv \
  --identifier 157864951321 \
  --output reports/finish-review.json

# Evaluate independently adjudicated finish cases.
.venv/bin/pcqc finish-evaluate \
  --benchmark evaluation/finish-regression-seed.json \
  --results-dir reports/finish-regression \
  --output reports/finish-regression/report.json

# Run a checkpointed validation pilot. Previously inspected products are forced
# into development and cannot enter validation or the locked final holdout.
.venv/bin/pcqc multimodal-eval \
  --sales /path/to/PRICECHARTING.csv \
  --output-dir reports/pilot-v3 \
  --per-target 5 \
  --exclude-manifest reports/pilot/gemini-pilot-manifest.json \
  --exclude-manifest reports/pilot-v1/gemini-pilot-manifest.json \
  --exclude-manifest reports/pilot-v2/gemini-pilot-manifest.json

# Start the API.
.venv/bin/pcqc serve
```

## Review Console

The FastAPI service includes a browser-based POC review console at
`http://127.0.0.1:8000/`. It accepts either the labeled historical export or an
unlabeled sale feed containing the inference fields. Start it with:

```bash
.venv/bin/pcqc serve
```

The console supports:

- CSV upload with a 100-row POC safety limit.
- Seeded random sampling or searchable selection of specific listing IDs before any model calls.
- Deterministic-rules and Gemini multimodal modes.
- Incremental batch progress and persistent JSON run records under
  `cache/console-runs/`.
- Versioned run metadata covering policy, prompt, model, and canonical input hash; older runs are
  visibly marked outdated and cannot be adjudicated as current output.
- A review queue with listing and catalog images, identity dimensions,
  evidence facts, and replacement candidates.
- Human acceptance or override notes without a model-generated confidence score. Blocked results
  name the missing evidence instead of using a generic manual-review label.
- CSV export of recommendations and adjudications.

Integration endpoints:

```text
POST /api/runs
POST /api/runs/preview
GET  /api/runs
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/reviews
GET  /api/runs/{run_id}/reviews/{identifier}
PUT  /api/runs/{run_id}/reviews/{identifier}/adjudication
GET  /api/runs/{run_id}/export
```

OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

The API defaults to the deterministic reviewer. Set `use_multimodal_model: true` in a request
only after `LLM_API_KEY` and `LLM_MODEL` are configured.

## Verify

```bash
.venv/bin/pytest --cov=pcqc --cov-report=term-missing
./scripts/verify_handoff.sh
SALES_CSV=/path/to/PRICECHARTING.csv ./scripts/demo_poc.sh
```

`demo_poc.sh` verifies the completed artifacts and rebuilds the paired comparison offline. It does
not call Gemini, spend API credits, or rerun the locked final holdout. It requires an authorized
copy of the original sales export because that dataset is intentionally not committed.

See [`HANDOFF.md`](HANDOFF.md) for the supported delivery boundary, recipient setup, credential
ownership, demonstration workflow, and known limitations.

Current proof artifacts:

- `reports/proof/data-profile.json`: complete 10,000-row data profile.
- `reports/proof/baseline-report.json`: diagnostic grouped-split baseline metrics; not the locked
  final evaluation because examples from that earlier split informed prompt development.
- `reports/proof/live-smoke.json`: sanitized live API/image result; no credentials or cached image.

The rules result is a floor, not a production candidate. Its low holdout recall is expected and
is evidence for testing a multimodal model rather than a claim that the problem is solved.

The first Gemini pilot exposed an ambiguous export field and an unsafe self-reported confidence
design. Paid access is active, but the legacy final metrics are superseded. The dedicated finish
seed currently contains only three manually inspected development cases, so its perfect regression
score is not a performance estimate.
The completed POC decision is in
[`docs/poc-executive-report.md`](docs/poc-executive-report.md).
See [`docs/gemini-pilot-findings.md`](docs/gemini-pilot-findings.md) before interpreting any
multimodal metrics or expanding the run.

## Cache and leakage guarantees

- Historical `status`, semantic target, target condition, reviewer action, review timestamps, and
  the undocumented upstream questionable-sale score are removed before constructing the Gemini
  request.
- Product API caches contain catalog metadata and prices only; they contain no review labels or
  model answers.
- Image caches contain bytes fetched from the row and assigned-catalog image URLs. Listing images
  are keyed by listing ID plus URL hash; catalog images are keyed by verified product ID.
- Cached image bytes are rehashed and length-checked before reuse. Malformed cache metadata or a
  changed canonical catalog URL forces a refetch instead of silently trusting stale evidence.
- A multimodal `ignored` or `condition_change` result cannot pass as a product match unless the
  model explicitly compares the eBay image with verified assigned-catalog artwork. Missing,
  mismatched, or uncertain catalog artwork forces `needs_modification`.
- Finish is fail-closed: `regular`, `holo`, `reverse holo`, `cosmos holo`, and named special foils
  are separate product identities. The finish resolver first establishes the assigned catalog
  finish, then observes the listing finish, and only then compares them. Unknown is never treated
  as a match. Image-only absence of reflection cannot prove `regular` when reflective siblings
  exist. A specialist outage produces unknown plus human review, not acceptance; retryable failures
  receive one bounded retry after 60 seconds.
- A replacement product ID is retained only when it came from PriceCharting search, its catalog
  page ID and image were verified, and the model explicitly matched the listing to that candidate.
- Prediction checkpoints are not trusted by listing ID alone. Each result is bound to a SHA-256
  fingerprint of the label-blind evidence, image hash, model ID, and prompt version.
- Changing a title, product, condition, price, image, model, prompt, or catalog evidence forces a
  new inference. Changing a historical label updates scoring without exposing that label to the
  model.
- Each pilot manifest records the SHA-256 of the complete source CSV and the prompt version.

Another labeled PriceCharting export works when it has the required columns and known status
values. The single-sale HTTP API accepts unlabeled operational input. A generic unlabeled batch
feed would need a small batch-ingestion command because the evaluation command intentionally
requires historical labels for stratification and metrics.
