# Legacy V2 PriceCharting eBay Sale Reviewer Evaluation

> Superseded July 29, 2026. This historical report used AI-generated confidence and model-selected
> routing. Those fields have been removed from the active v3 contract. These results do not
> validate the current finish-aware, human-review-only implementation.

**Date:** July 29, 2026  
**Model:** Google Gemini `gemini-3.6-flash`  
**Decision:** POC successful for reviewer assistance; not approved for automatic sale mutation

## Executive Summary

The POC demonstrates that image-aware AI can materially improve review of questionable
PriceCharting trading-card sales. On a locked final set of previously unseen products, multimodal
Gemini reproduced validation performance:

| Metric | Validation | Final |
|---|---:|---:|
| Resolved-decision accuracy | 76.7% | 76.7% |
| Macro-F1 | 0.735 | 0.735 |
| Deleted precision | 100.0% | 100.0% |
| Deleted recall | 33.3% | 33.3% |
| Condition-change recall | 96.7% | 100.0% |
| Exact replacement-condition accuracy | 93.3% | 93.3% |
| Model-selected coverage | 84.4% | 85.6% |
| Accuracy within coverage | 85.5% | 85.7% |
| Cost per 100 listings | $0.64 | $0.63 |
| Median latency | 11.6 s | 11.6 s |
| p95 latency | 27.3 s | 26.4 s |

The final accuracy estimate is 76.7% with a 95% Wilson interval of 67.0%-84.2%. Deletion precision
was 10/10, but its interval is still wide at 72.3%-100%, and recall was only 10/30. These results
support a recommendation workflow, not autonomous deletion.

## Evaluation Design

- Products, not rows, were assigned to development, validation, and final partitions.
- Products seen during prompt development were forced into development.
- Validation and final each used 100 rows: 30 ignored, 30 deleted, 30 actual condition changes,
  and 10 historical `needsMod` routing proxies.
- The validation ablation used identical listing IDs for deterministic rules, Gemini text/catalog
  evidence, and Gemini text/catalog/image evidence.
- Historical labels, status, target condition, review timestamps, and upstream score were removed
  from model input.
- The final source, partition, model, prompt, and policy were hash-locked before the one-time run.
- Historical `needsMod` was excluded from resolved-decision accuracy because PriceCharting does not
  publicly expose its final product reassignment.

## Image Value

| Arm | Accuracy | Macro-F1 | Exact condition ID | Cost/100 |
|---|---:|---:|---:|---:|
| Deterministic rules | 40.0% | 0.292 | 16.7% | $0.00 |
| Gemini text/catalog | 55.6% | 0.528 | 36.7% | $0.43 |
| Gemini multimodal | 76.7% | 0.735 | 93.3% | $0.64 |

Against text-only Gemini, images improved 20 underlying decisions and degraded one across 90
resolved validation rows, a net gain of 19. The largest improvement was exact recognition of slabs
and grades that were not reliably present in listing titles.

## Disagreement Audit

The deletion-versus-reassignment audit found that the historical action is not always a perfect
semantic target:

- All 10 multimodal deletion recommendations on historically deleted rows were clear invalid
  comparables in the available evidence.
- Nine historically deleted rows routed for modification appeared to be valid single-item sales
  assigned to another variant, language, package quantity, or product.
- Three historically deleted rows predicted ignored visibly matched their assigned products.
- Two historically deleted rows contained observable condition conflicts instead.

This is consistent with PriceCharting's explanation that product modifications are recorded on
the internal sale entity and are not exposed as final outcomes in the export/API.

## Confidence Finding

Raw Gemini confidence is not calibrated. The highest validation confidence threshold looked
promising but failed to generalize:

| `raw_confidence` threshold | Validation accuracy | Final accuracy | Final coverage |
|---|---:|---:|---:|
| 0.95 | 85.3% | 85.7% | 85.6% |
| 0.98 | 97.9% | 88.6% | 48.9% |

Therefore, confidence must remain an audit/ranking signal. It must not authorize automatic changes.

## Decision

### Passed

- End-to-end ingestion, enrichment, image retrieval, structured review, retries, checkpointing,
  and API integration work.
- Multimodal evidence provides substantial value over rules and text-only evidence.
- Condition correction and exact condition-ID selection are strong enough for reviewer assistance.
- Validation and final aggregate performance are unusually consistent.
- Inference cost is low enough for a larger supervised pilot.

### Not Passed

- Automatic deletion: recall is low and the precision sample is too small.
- Automatic condition mutation: 28/30 exact is useful but below a defensible autonomous gate.
- Confidence-based auto-accept: the validation threshold did not generalize.
- `needsMod` quality: authoritative final outcomes are unavailable.

## Recommendation

Demonstrate and deploy this POC only as a reviewer-assistance tool:

1. Show the proposed action, condition ID, rationale, and extracted image observations.
2. Require a human to confirm every mutation.
3. Prioritize high-confidence condition corrections and clear lots/bundles in the review queue.
4. Route product/variant/language/package mismatches as product-reassignment candidates.
5. Capture the human's final action and final product ID for future calibration.
6. Run a larger temporal evaluation before considering any automation.

The POC is complete and defensible for demonstrating feasibility. It is not a production
autonomous classifier.

## Limitations

- The balanced evaluation cohort does not represent production class prevalence.
- Historical reviewer actions contain ontology and label noise.
- `needsMod` has no authoritative public final outcome.
- The 100-row final set gives wide confidence intervals for deletion precision.
- This is a product-group holdout from one export window, not a temporal holdout.
- API catalog caches have no freshness TTL.
- Model behavior can drift if Google changes the served model behind the same name.

## Evidence

- Validation comparison: `reports/evaluation-validation/comparison/comparison.md`
- Full disagreement export: `reports/evaluation-validation/comparison/disagreements.jsonl`
- Manual audit: `docs/manual-disagreement-audit.md`
- Frozen policy: `config/frozen-poc-policy.json`
- Final report: `reports/evaluation-final/multimodal/gemini-pilot-report.json`
- Final lock: `reports/evaluation-final/multimodal/final-evaluation-lock.json`
