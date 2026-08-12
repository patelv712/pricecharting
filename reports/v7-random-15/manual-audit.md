# Fifteen-Row Development Audit

**Run date:** 2026-08-10  
**Cohort:** validation partition, target-stratified random sample  
**Batch run:** `gemini-3.6-flash` plus targeted `gemini-3.1-pro-preview` finish review  
**Batch policy:** `2026-08-10-candidate-ambiguity-v6:multimodal+2026-08-10-targeted-finish-v2+2026-08-10-finish-resolution-v5`  
**Post-audit policy:** `2026-08-10-candidate-ambiguity-v7:multimodal+2026-08-10-targeted-finish-v2+2026-08-10-finish-resolution-v5`

## Bottom Line

This run is useful development evidence, but it is not a final accuracy estimate.
The cohort was sampled randomly within historical target classes, not uniformly from the
feed, and its failures were used to change the finish resolver before the final regression
pass. These 15 rows are therefore tuning data now.

- 15 of 15 rows completed with no API failures.
- All 4 historical condition corrections were predicted with the exact reviewed condition ID.
- Historical top-level action agreement was 9 of 12, or 75%. The 3 disagreements were all
  `deleted` rows where the system correctly found a product mismatch but recommended retaining
  the sale for reassignment.
- The only clear intrinsic deletion in the sample, an artwork case marked "Card Not Included,"
  was deleted by the system.
- The 3 historical `needsMod` rows cannot be scored as ordinary labels. PriceCharting confirmed
  that the final modification is stored on the sale entity and is not included in this export.
- Automatic routing coverage is 0%. Every result is still routed to human review, so this is not
  yet evidence for unattended production use.

## Metric Interpretation

| Measure | Result | Interpretation |
|---|---:|---|
| Completed | 15/15 | Pipeline reliability for this small run only |
| Historical action accuracy | 9/12 (75.0%) | Excludes `needsMod`; penalizes delete-versus-reassign policy differences |
| Historical macro-F1 | 0.7091 | Same label limitation as action accuracy |
| Deletion precision | 1/1 (100%) | Only one model deletion, so this estimate is extremely unstable |
| Deletion recall | 1/4 (25%) | Other three feed deletions were diagnosed as product mismatches requiring reassignment |
| Condition-ID accuracy | 4/4 (100%) | Promising but far too few examples for a final claim |
| Human-review routing | 15/15 (100%) | Safe, but no workload reduction yet |
| Main-model latency | 8.187 s p50, 16.254 s p95 | Excludes the additional specialist call on eight rows |
| Specialist latency | 123.996 s total over 8 calls | 15.500 s mean additional latency on invoked rows |
| Estimated model cost | $0.479187 total | Code-estimated successful-response cost, not a Google billing invoice |

The cost estimate is `$0.241015` for the main-model calls plus `$0.238172` for eight specialist
calls. It excludes any pricing drift, taxes, retries not represented in successful-response
metadata, and prior development runs. The append-only checkpoint contains three complete passes
used to find and verify the fixes. Applying the same estimator gives `$1.511138` across those
passes, plus about `$0.019149` for the post-audit booster regression, or `$1.530287` for this
entire 15-row development exercise.

## Row-By-Row Audit

| # | Listing | Feed | Model | Manual finding |
|---:|---|---|---|---|
| 1 | [306878701824](https://www.ebay.com/itm/306878701824) | ignored | ignored + review | The title and image support Manga OP13-118 and PSA 9. Core decision is correct. The review flag comes from unresolved catalog sibling ambiguity, so this is conservative over-routing rather than a wrong product diagnosis. [PriceCharting](https://www.pricecharting.com/game/one-piece-carrying-on-his-will/monkey-d-luffy-manga-op13-118) |
| 2 | [327184867383](https://www.ebay.com/itm/327184867383) | ignored | ignored + review | Mew EX #100 and PSA 8 match. Title and image support a holo/cosmos appearance, but the assigned catalog record does not state a finish and no verified separate finish sibling resolves the identity. Retaining while reviewing is defensible. [PriceCharting](https://www.pricecharting.com/game/pokemon-holon-phantoms/mew-ex-100) |
| 3 | [287301555783](https://www.ebay.com/itm/287301555783) | ignored | ignored | Exact Dragonite #180 Japanese Holo PSA 10 match. Correct. [PriceCharting](https://www.pricecharting.com/game/pokemon-japanese-cry-from-the-mysterious/dragonite-180) |
| 4 | [117165604200](https://www.ebay.com/itm/117165604200) | PSA 10 | ignored + review | Erika's Vileplume ex #3 and PSA 10 visually match. The model retained the sale, but the catalog page could not be verified, causing safe over-routing. [PriceCharting](https://www.pricecharting.com/game/pokemon-ascended-heroes/erikas-vileplume-ex-3) |
| 5 | `PmU12BnGLMYs` | deleted | ignored + modification | The listing title explicitly says Offline Regional 2024 Vol. 3, while the assigned product is the ordinary OP07-091 printing. Product-mismatch diagnosis is correct. Delete versus reassign is a business-policy decision, and the non-eBay identifier plus missing image reduce verifiability. [PriceCharting](https://www.pricecharting.com/game/one-piece-500-years-in-the-future/monkey-d-luffy-op07-091) |
| 6 | [306977503059](https://www.ebay.com/itm/306977503059) | deleted | ignored + modification | Listing is a sealed Flagship Battle promo; assigned product is the 3rd Anniversary ST21-014 printing. Product-mismatch diagnosis is correct. Feed deletion may reflect low-value/high-volume policy or lack of a verified replacement. [PriceCharting](https://www.pricecharting.com/game/one-piece-promo/monkey-d-luffy-3rd-anniversary-st21-014) |
| 7 | [227347782226](https://www.ebay.com/itm/227347782226) | deleted | deleted | Listing is an extended-art display case and the image says "Card Not Included." This is not a card sale. Correct deletion. [PriceCharting](https://www.pricecharting.com/game/pokemon-chaos-rising/ampharos-90) |
| 8 | [177838994353](https://www.ebay.com/itm/177838994353) | deleted | ignored + modification | Assigned product is English Ascended Heroes Pikachu ex #277; listing is Indonesian MA3 234/193 SAR. Language, set/card number, and release differ. Product-mismatch diagnosis is correct. Delete versus reassign remains policy-dependent because no verified Indonesian replacement was found. [PriceCharting](https://www.pricecharting.com/game/pokemon-ascended-heroes/pikachu-ex-277) |
| 9 | [227296357503](https://www.ebay.com/itm/227296357503) | CGC 10 | CGC 10 | Product and Holo finish match; listing is a CGC 10 slab rather than ungraded. Exact condition correction. [PriceCharting](https://www.pricecharting.com/game/pokemon-brilliant-stars/houndoom-tg10) |
| 10 | [287314443807](https://www.ebay.com/itm/287314443807) | PSA 10 | PSA 10 + review | The v6 batch produced the exact PSA 10 condition but an unsupported `artwork_mismatch` warning. This exposed a real system defect: the generic catalog name `Booster Pack` does not encode pack art. v7 fixed the rule, and a live one-row regression returned PSA 10 with `needs_modification=false`, `artwork=uncertain`, and no finish-specialist call. [PriceCharting](https://www.pricecharting.com/game/pokemon-base-set-2/booster-pack) |
| 11 | [406944934728](https://www.ebay.com/itm/406944934728) | PSA 10 | PSA 10 | Japanese Zapdos EX #204 SAR and PSA 10 match. Exact condition correction. v5 correctly avoids inventing a finish problem where neither catalog nor title requires finish verification. [PriceCharting](https://www.pricecharting.com/game/pokemon-japanese-scarlet-%26-violet-151/zapdos-ex-204) |
| 12 | [198327133121](https://www.ebay.com/itm/198327133121) | PSA 8 | PSA 8 + review | Exact condition correction. The title says Holo while the catalog finish is unspecified and the image does not positively resolve the finish, so retaining the finish conflict for review is appropriate. [PriceCharting](https://www.pricecharting.com/game/pokemon-silver-tempest/pikachu-49) |
| 13 | [297969078690](https://www.ebay.com/itm/297969078690) | needsMod | ignored + modification | Assigned product is Base Set Chansey 3/102; listing is Base Set 2 Chansey 3/130. Clear set/card-number mismatch. Correct diagnosis, but the hidden final upstream action cannot be checked from this export. [PriceCharting](https://www.pricecharting.com/game/pokemon-base-set/chansey-1999-2000-3) |
| 14 | [406570068105](https://www.ebay.com/itm/406570068105) | needsMod | ignored | Current public evidence supports Japanese World Champions Pack Charizard #8 PSA 10. This does not prove that the feed is wrong: PriceCharting says `needsMod` outcomes may have already changed the sale entity, and the original issue is not exported. Exclude this row from accuracy scoring. [PriceCharting](https://www.pricecharting.com/game/pokemon-japanese-world-champions-pack/charizard-8) |
| 15 | [257468750876](https://www.ebay.com/itm/257468750876) | needsMod | ignored + modification | Listing is the Orange `/25` parallel; assigned product is the unsuffixed base Storybook Land Canal Boats card. Clear printing/parallel mismatch. Correct diagnosis, with final upstream action unavailable. [PriceCharting](https://www.pricecharting.com/game/2025-topps-disneyland-70th-anniversary-poster/storybook-land-canal-boats-p-7) |

## Defects Found And Fixed

1. An assigned product with only unknown-finish candidates could be incorrectly inferred as
   Regular. The resolver now ignores unknown candidates when establishing a finish family.
2. Finish rules were being applied to booster packs and other non-single-card objects. v5 marks
   finish as not applicable for supported sealed/accessory patterns.
3. Rows with no finish signal were being forced into modification merely because finish was not
   proven. v5 requires a known assigned finish, an explicit listing finish, or a verified finish
   sibling before finish verification is mandatory.
4. Gemini's generic visual `foil` label was conflicting with PriceCharting's `Holo` taxonomy.
   Generic foil now normalizes to Holo only when the assigned/title identity is Holo and no
   separate verified Foil sibling exists.
5. Generic booster-pack wrapper art was treated like identity-defining card artwork. v7 now
   suppresses artwork-only modification when the verified PriceCharting product is generically
   named `Booster Pack` or `Blister Pack`; named sealed variants remain identity-sensitive.

## Remaining Risks

- The generic sealed-product exception currently covers booster and blister packs. Other sealed
  product families need independently adjudicated examples before expanding this policy.
- Delete versus reassign cannot be learned reliably from the current export because the label
  mixes product validity with PriceCharting operational policy.
- `needsMod` is not an evaluable final-outcome label with the public fields currently available.
- Product replacement remains conservative. Correctly detecting a mismatch does not guarantee a
  verified replacement product ID.
- The sample is too small for stable class metrics, especially deletion precision.
- Because these rows informed changes, the next meaningful score must come from a new untouched
  validation cohort. The locked final holdout should remain unopened until prompt and policy are
  frozen.

## Artifacts

- `gemini-pilot-manifest.json`: exact cohort and partition fingerprints.
- `gemini-pilot-predictions.jsonl`: append-only checkpoints from three development iterations;
  the final 15 records are the active v5 regression pass.
- `gemini-pilot-report.json`: active v5 historical-label metrics.
- `listing-contact-sheet.jpg`: visual audit sheet for the 14 rows with listing images.
- `booster-pack-v7-review.json`: live post-audit proof for the generic pack-art fix.
