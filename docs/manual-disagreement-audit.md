# Validation Disagreement Audit

**Date:** July 29, 2026  
**Cohort:** 100 product-grouped validation rows  
**Focus:** deletion versus product reassignment and paired image effects

## Method

The audit compared deterministic, text-only Gemini, and multimodal Gemini outputs for the same
listing IDs. All 61 cross-mode disagreements were exported with the historical target, listing and
product titles, image URL, predicted actions, and rationales. The 24 disagreements on historically
deleted rows were reviewed in detail. Images were visually inspected for the nine multimodal
product-reassignment decisions and three multimodal `ignored` decisions.

This is a POC audit, not authoritative relabeling. The historical export records reviewer actions,
and PriceCharting does not expose the final product assignment for `needsMod`. Some apparent model
errors may therefore be label-policy disagreements.

## Findings

- Multimodal predicted `deleted` for 10 historically deleted rows. All 10 were clear invalid
  comparables such as lots, multiple boxes or packs, sealed products assigned to a single card, or
  an apparent counterfeit. Observed deletion precision was 10/10.
- Multimodal routed nine historically deleted rows as `needs_modification`. Their images and titles
  showed plausible single-item sales with a different variant, language, sealed-case unit, or
  product assignment. This is consistent with the frozen reassignment policy and JJ's explanation
  of how `needsMod` is resolved internally.
- Multimodal returned `ignored` for three historically deleted rows. The images visibly matched the
  assigned Buggy, Poncho-Wearing Eevee, and Tohoku's Pikachu products. No deletion reason was
  observable from the public evidence.
- Two historically deleted rows received an underlying condition correction. One image showed a
  PSA 9 slab assigned to PSA 10; the other showed a raw card assigned to Grade 1. These are
  defensible condition corrections even though the historical action was deletion.
- The paired image arm improved 20 underlying resolved decisions and degraded one relative to
  text-only, for a net improvement of 19/90. When human-routing actions are treated as distinct
  outcomes, images improved 22 and degraded two, net 20/90.
- The one underlying-decision regression was a booster case historically deleted but routed by
  multimodal for reassignment from the single-box product. Under the frozen ontology this is not an
  obvious semantic regression.

## Automation Decision

The multimodal arm achieved 97.9% validation accuracy among 48 accepted resolved rows at raw
confidence at least 0.98, but one error and the small sample produce insufficient evidence for
automatic mutation. Raw confidence was also overconfident overall.

The POC policy is therefore recommendation-only:

- Never mutate a sale automatically.
- Route product, variant, language, and packaging reassignments to a human.
- Show the image observation, rationale, proposed decision, and proposed condition ID.
- Treat `deleted` as a reviewer recommendation even when model confidence is high.
- Collect authoritative final product/outcome labels before calibrating a production threshold.

The complete machine-readable disagreement set is in
`reports/evaluation-validation/comparison/disagreements.jsonl`.
