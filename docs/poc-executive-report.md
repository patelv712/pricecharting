# PriceCharting eBay Sale Reviewer POC: Current Status

**Date:** August 10, 2026  
**Active version:** `2026-08-10-catalog-evidence-v8`  
**Status:** finish-aware workflow implemented; independent validation and a new holdout required

## Current Decision

The active reviewer no longer accepts or reports AI-generated confidence. Gemini returns only
structured observations, a proposed decision, and an evidence-grounded reason. The application
attaches deterministic evidence facts and routes every recommendation to human review.

The prior v2 evaluation is superseded because it:

- Asked Gemini to invent numeric confidence.
- Allowed Gemini to choose its own routing.
- Did not provide explicit assigned-product finish or sibling foil variants.
- Failed a reverse-holo versus non-holo example with a self-reported score of 0.98.

Consequently, the earlier final metrics describe only the legacy v2 implementation. They are not
performance claims for the active implementation.

## Active Contract

Gemini may return:

- Proposed decision
- Proposed replacement condition ID
- `needs_modification`
- Reason and rationale codes
- Structured visual and consistency observations

Gemini may not return:

- Confidence or probability
- Auto-accept recommendation
- Routing decision

Our code records these deterministic facts without converting them into a probability:

- Whether an image exists and is usable
- Regex-derived deletion indicators
- Regex-derived explicit grade/condition
- Title-to-product token overlap
- Number of catalog price anchors
- Structured image observations for human inspection

## Routing

Every active v8 result is `human_review`. Unknown or conflicting finish, product variant, language,
set, package quantity, grading company, or image evidence must remain `needs_modification`.

V8 retrieves and verifies assigned PriceCharting catalog artwork, sends listing and catalog images
as separately labeled evidence, and requires structured comparisons for artwork, release/event,
set/card number, language, finish, printing/parallel, quantity/packaging, and object type. Explicit
text conflicts are application-derived and cannot be overridden by Gemini. Finish is fail-closed:
an `ignored` or `condition_change` proposal becomes `needs_modification` unless finish is positively
reported as matched.

V8 also searches PriceCharting's `/api/products` endpoint, ranks returned candidates using explicit
text identity features, and retrieves verified catalog artwork for the highest-ranked alternatives.
Gemini may select only a supplied candidate, and the application retains that ID only when the
candidate page ID and image are verified and the model reports a direct listing-to-candidate match.
The ranking score is not confidence and is never used for automatic mutation.

No sale is automatically ignored, deleted, reassigned, or condition-corrected.

V8 includes a dedicated finish resolver before the general reviewer. It uses assigned catalog
description/notes, named sibling products, deterministic image observations, and a narrow Gemini
3.1 Pro visual prompt. The resolver separately records assigned finish, observed listing finish,
match status, visible evidence regions, and an optional unique verified replacement. It contains no
AI-generated confidence. Its result overrides a contradictory general-model finish judgment.

Repeated live calls showed that temperature zero does not make image interpretation deterministic:
one call incorrectly described the known reverse-holo Tyrantrum as regular. V7 therefore prohibits
an image-only `regular` observation from becoming a positive match when verified reflective
siblings exist. Absence of visible reflection becomes `unknown`. Positive finish matches also
require visual corroboration; title/catalog agreement alone cannot pass after a specialist outage.
Retryable provider failures receive one retry after 60 seconds, then fail closed.

The known Tyrantrum regression resolves assigned `regular`, observed `reverse_holo`, mismatch, and
verified replacement product `12385647` in the integrated review path, including after a timed-out
first attempt and bounded retry. The three-case seed is
3/3, but this is regression proof only and is not statistically valid evidence of general accuracy.

## Required Evaluation

The current policy still requires:

1. A fresh product-grouped validation cohort containing dedicated finish, artwork/parallel,
   language, set/reprint, packaging/quantity, object-type, and condition slices.
2. Independent adjudication of product match, sale validity, replacement ID, and condition ID;
   historical deletion actions alone are not semantic ground truth.
3. At least 100 independently adjudicated finish examples, with meaningful support for regular,
   holo, reverse holo, cosmos holo, special foil, and genuinely indeterminate images.
4. A new untouched holdout because the previous final rows have already been inspected.
5. Metrics based on issue detection, workflow action, exact replacement IDs, unknown rate, unsafe
   false matches, cost, and latency. Confidence and
   auto-accept coverage metrics are prohibited.

## Legacy Evidence

The historical v2 report remains available only for audit:
`docs/legacy/poc-executive-report-v2.md`.
