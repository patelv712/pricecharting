# Finish Identity Resolution Design

**Version:** `2026-08-10-targeted-finish-v7`  
**Scope:** trading-card finish identity only  
**Deployment:** recommendation-only, always human review

**Specialist prompt:** `2026-08-10-targeted-finish-v2`

**Resolver policy:** `2026-08-10-finish-resolution-v5`

## Problem Framing

“Foil classification” is an incomplete framing. The operational question is relational:

1. What finish does the assigned PriceCharting product represent?
2. What finish is observable in the eBay listing?
3. Do those identities match?
4. If not, is exactly one verified PriceCharting sibling the correct replacement?

A model saying “reverse holo” is not enough. A reverse-holo listing assigned to a regular product
is a product mismatch; the same listing assigned to the reverse-holo sibling is a product match.

Historical `deleted` is not a finish label. Deletion can reflect cancellation, fraud, duplication,
unsupported policy, or a product mismatch. It must not be used as ground truth for finish.

## Evidence Contract

The resolver uses evidence in this order:

1. Assigned PriceCharting product name, description, and notes.
2. Explicit listing-title finish markers.
3. Verified same-family PriceCharting finish siblings.
4. The original eBay image plus reproducible full-card and card-body crops.
5. A narrow multimodal visual observation when text does not settle the listing finish.

Price, rarity, the historical review action, the upstream score, and model-generated confidence are
excluded from finish inference.

## Finish Ontology

The first POC ontology is:

- `regular`
- `holo`
- `reverse_holo`
- `cosmos_holo`
- `foil`
- `special_foil`
- `unknown`

Specific terms take precedence over generic terms. For example, `reverse holo foil` maps only to
`reverse_holo`, and `non-holo` maps to `regular` rather than accidentally matching `holo`.

This ontology is intentionally conservative. It does not claim that all named treatments inside
`special_foil` are interchangeable. Exact reassignment is allowed only when the observed class has
one verified eligible sibling. Multiple special-finish siblings produce no replacement.

Finish identity is catalog-relative. A visible cosmos pattern can be part of a product that
PriceCharting identifies simply as `Holo`. It is treated as a distinct `cosmos_holo` identity only
when the verified product family exposes a separate cosmos sibling.

Likewise, generic visual `foil` and catalog `Holo` are treated as the same identity unless the
verified family exposes a separate Foil sibling. Reverse holo and named special treatments remain
distinct.

Finish classification applies only to single-card products. Booster packs, boxes, decks, sealed
collections, and listings that explicitly say the card is not included bypass the finish resolver.

## Catalog Resolution

An explicit assigned-product marker wins. This matters because some unsuffixed PriceCharting names
are inherently holo, such as catalog entries whose description says `Holo`.

An unsuffixed product can be inferred as `regular` only when:

- its catalog page was verified;
- schema-v2 metadata was extracted; and
- separately named finish siblings exist in the same normalized product family.

Absence of the word `holo` alone is never evidence of `regular`.

## Visual Resolution

Gemini 3.1 Pro Preview receives a narrow task rather than the general sale-review prompt. It sees:

- listing title and assigned finish metadata;
- a full listing crop and card-body detail;
- verified assigned catalog artwork;
- only verified finish-sibling candidate images.

It must identify a concrete evidence region such as `illustration`, `card_body`, `border`, or
`slab_label`. Weak glare is not proof of regular finish. If lighting or resolution is inadequate,
the required answer is `unknown`.

The numerical image features are measurements, not confidence. They record dimensions, aspect
ratio, saturation distribution, luminance variation, and highlight fraction for reproducibility.
They do not independently prove foil treatment.

## Decision Rules

- Assigned and observed finish equal: `match`.
- Both are known and differ: `mismatch`.
- Either is unknown: `unknown`.
- Unknown never becomes match.
- Unknown forces modification only when catalog metadata, listing text, or verified siblings raised
  a concrete finish-verification question. Absence of any finish signal is not evidence of a defect.
- Mismatch forces `needs_modification` and human review.
- A replacement ID requires one unique candidate with a verified PriceCharting page and usable
  catalog image whose finish equals the observed finish.
- A specialist error becomes unknown and human review; it never aborts into an implicit match.
- Retryable timeouts, HTTP 429s, and server errors receive one bounded retry after 60 seconds.
- The targeted result overrides a contradictory general-review finish field.
- No result automatically mutates a sale.

## Evaluation Design

The three manually inspected development cases are regression tests, not a benchmark. A credible
evaluation requires at least 100 independently adjudicated cases and preferably 200 or more.
Products must be grouped across development, validation, and holdout to prevent sibling or repeated
listing leakage.

The adjudication form must record:

- assigned product ID and assigned finish;
- observed listing finish or genuinely indeterminate;
- finish match status;
- exact replacement product ID, when one exists;
- evidence notes and adjudicator status.

Required metrics are:

- assigned-finish accuracy;
- observed-finish accuracy and per-finish support;
- mismatch precision and recall;
- exact replacement accuracy;
- unknown rate;
- unsafe false matches, where a true mismatch was called match;
- specialist and total latency, token usage, and cost.

An overall accuracy number alone is unacceptable because a regular-heavy sample can hide poor
reverse-holo recall. The highest-risk metric is unsafe false matches. Even zero failures in 100
examples does not prove zero risk; it only supplies a limited empirical bound.

## Acceptance Gate

Before a locked holdout run:

- no known regression may produce an unsafe match;
- every finish stratum must have non-trivial independently labeled support;
- exact replacement must fail closed when candidates are missing or ambiguous;
- provider errors and unusable images must return unknown;
- prompt, ontology, model IDs, catalog schema, routing policy, and source hashes must be frozen.

The final holdout is run once. Any subsequent prompt or policy change invalidates that result and
requires a new untouched holdout.

## Current Evidence

The development seed contains Tyrantrum reverse holo, Typhlosion holo, and Pikachu cosmos holo.
All three currently resolve correctly, including exact replacement for the two mismatches. Because
the sample size is three and was used during development, this result is not a performance claim.

The integrated Tyrantrum proof is stored at
`reports/finish-regression/157864951321-integrated.json`.
