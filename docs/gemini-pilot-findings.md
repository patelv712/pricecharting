# Gemini 3.6 Flash Pilot Findings

**Date:** July 29, 2026  \
**Model:** `gemini-3.6-flash`  \
**Tier:** Gemini Developer API paid tier  \
**Status:** validation ablation and locked final evaluation completed

## Executive finding

The model integration works, images are accepted, and structured results validate. The first
stratified run also exposed two evaluation defects that make its aggregate score unsuitable for a
model-selection decision:

1. The prompt originally supplied numeric condition IDs without the authoritative ID/name catalog.
   Gemini confidently invented mappings, such as treating ID 17 as PSA 9.
2. In 916 of 1,593 condition-button rows, `condition-id` equals the condition encoded by `status`.
   PriceCharting later clarified that reviewers may confirm an existing condition by selecting its
   condition button instead of selecting `ignore`.

Both issues are fixed. Same-condition actions are now semantically labeled `ignored`; only the 677
differing-condition actions are labeled `condition_change`. A corrected run was attempted, but the
free-tier API returned HTTP 429 for both conservatively throttled requests and stopped at the
configured failure budget. No corrected quality score is available yet.

## What was proven

- Real PriceCharting product enrichment and real eBay image retrieval work.
- Gemini accepts the combined image and structured evidence packet.
- Historical labels are removed from the provider prompt.
- Structured JSON validation works without a repair call on successful samples.
- Checkpoint/resume and partial-failure accounting work.
- A missing-image deletion example completed successfully.
- API keys are stored only in the permission-restricted, Git-ignored `.env`.

## Diagnostic run

The uncorrected 20-row sample completed 16 responses and encountered four final quota failures
after one retry recovered a fifth failure. Across successful requests:

- 38,939 input tokens and 4,771 output tokens.
- Median latency 7.77 seconds; observed p95 13.46 seconds.
- Every successful result used route `accept` with confidence between 0.95 and 0.98.
- Three available historical `needsMod` rows were all predicted `deleted` and auto-accepted.
- Five condition-change rows included three rows whose input condition already equaled the target.

The apparent 69.23% resolved-decision accuracy and 0.733 macro-F1 must not be used as model
performance estimates. The sample is tiny, three confirmation actions were incorrectly treated as
changes, and the prompt omitted the condition mapping. The consistently high confidence despite
errors is itself a useful result: raw model confidence is not calibrated and cannot drive
automation.

## Corrective changes

- Added the complete PriceCharting condition ID/name catalog to every model request.
- Added an instruction forbidding invented condition mappings.
- Relabeled same-condition button actions as semantic `ignored` confirmations.
- Added deterministic sampling from the product-grouped holdout.
- Added one missing-image row per target stratum when available.
- Added per-row checkpoints, retry of failed checkpoint rows, request throttling, and failure
  budgets.
- Added sanitized provider HTTP details for future quota diagnosis.
- Increased the automated suite to cover mapping visibility, ambiguous-state exclusion, retry, and
  quota-error handling.

## Corrected canary and ontology finding

After PriceCharting clarified same-condition confirmation behavior, a fresh product-grouped canary
completed 12/12 responses:

- 9/9 resolved semantic decisions matched the historical labels.
- 3/3 condition corrections included the exact replacement condition ID.
- 30,886 input tokens and 3,242 output tokens.
- Median latency 10.97 seconds; observed p95 25.34 seconds.

An incremental expansion produced two more successful responses before the free-tier request
ceiling blocked progress. The combined checkpoint currently has 14 successful responses, including
11/11 resolved decisions matching historical labels. This remains far too small for a quality
claim.

The three historical `needsMod` rows exposed a decision-ontology problem: Gemini auto-accepted two
as `deleted` and one as `ignored`, while none routed to a human. PriceCharting explained that most
`needsMod` cases are resolved by changing the product on the internal sale entity. Therefore, a
valid single-item sale assigned to the wrong product should be `needs_modification` and routed to a
human, not deleted solely for a product, variant, set, or language mismatch. The prompt now states
this explicitly. This corrected policy must be canary-tested before a larger evaluation.

Gemini reported a free-tier `generate_content` request limit of 20 and continued returning HTTP 429
after its advertised retry windows. The runner now parses retry instructions and performs bounded
quota retries, but completing a 100-row evaluation reliably requires paid billing or multiple
quota-reset periods.

## Paid validation canary

Paid billing was enabled and a fresh four-row canary was run on validation products excluded from
all earlier pilot manifests. The run completed 4/4 requests after retrying one temporary HTTP 503:

- 2/3 resolved historical decisions matched.
- The condition correction selected the exact replacement ID.
- The historical `needsMod` row routed to human review.
- The historically deleted row was instead treated as a valid product-reassignment candidate.
- 10,713 input tokens and 1,302 output tokens cost approximately $0.026 at list price.

This sample proves paid access and the revised routing behavior, not model quality. In particular,
the disagreement on the deleted row requires evidence review before changing either the prompt or
the interpretation of the historical label.

## Completed evaluation

The requested 100-row paired validation ablation and one-time 100-row final multimodal evaluation
are complete. Multimodal validation and final accuracy were both 76.7%; macro-F1 was 0.735 in both,
exact condition-ID accuracy was 93.3% in both, and deletion precision/recall were 100%/33.3% in
both. Images improved 20 underlying validation decisions and degraded one relative to text-only.

The apparent 0.98 confidence threshold did not generalize: accepted accuracy declined from 97.9%
on validation to 88.6% on final. The completed POC therefore remains recommendation-only. See
`docs/poc-executive-report.md` for the decision and limitations.

## PriceCharting clarification

PriceCharting confirmed that `status` is the reviewer’s selected action. Selecting the existing
condition and selecting `ignore` can have the same final result. The implementation now converts
those two reviewer actions into the same semantic `ignored` target.

For most `needsMod` rows, PriceCharting has a final outcome only on the internal sale entity after
changing the product. That outcome is not available in this table or through a public API.
Accordingly, `needsMod` is excluded from semantic decision accuracy and retained only for
escalation analysis.
