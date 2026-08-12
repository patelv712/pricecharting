# Full Multimodal Discrepancy Audit

**Audit date:** July 29, 2026  
**Scope:** Every multimodal disagreement in the 100-row validation and 100-row final cohorts  
**Rows reviewed:** 58 (28 validation, 30 final)  
**Images manually inspected:** 56 original cached listing images  
**Rows without an image:** 2 synthetic/non-eBay identifiers

## Executive Finding

The 58 evaluation disagreements are not 58 equivalent model errors.

| Adjudication | Count | Meaning |
|---|---:|---|
| Full model error | 5 | The model missed the material product, finish, or set issue |
| Partial model error | 2 | The model correctly resolved one material dimension but missed another |
| Correct diagnosis, action-label mismatch | 9 | The system found a real wrong product/variant, but proposed reassignment while the historical action was `deleted` |
| Appropriate conservative route | 6 | The proposed correction was right or plausible, but contradictory evidence, unsupported grading, or an undocumented bucket justified human review |
| Confirmed reference/feed error | 4 | The historical action or target conflicts with a distinct current PriceCharting product or published condition policy |
| PriceCharting API/data error | 1 | A valid public catalog product was unavailable through the product API, forcing degraded fallback evidence |
| Reference label questionable | 4 | Title and image support the system result more strongly than the historical action |
| Not publicly verifiable | 20 | Public evidence cannot establish the internal deletion reason, transaction validity, authenticity, or accessory policy |
| Historical `needsMod` is not evaluable against current product | 7 | The sale entity may already contain the post-modification product |

These are primary adjudication categories, but the underlying diagnostic labels are not mutually
exclusive. In the twelve deeply re-verified rows, nine have wrong or migrated datafeed product
assignments; six `deleted` actions are nevertheless directionally protective because they keep a
bad comparable off the assigned product. There are five full model errors, three partial model errors
(including the API-degraded Garchomp row), three model-correct rows, and one policy-dependent row.

Rows `177979887250`, `116638228859`, and `405107918595` are model successes against incorrect feed
product or condition targets. Row `127826616928` has both a PriceCharting API/data failure and a
partial model error: the model identified the card and condition correctly but added an unnecessary
language/product warning after enrichment failed.
This does **not**
produce a replacement accuracy figure: the 142 rows where the model and feed agreed were not
independently relabeled, and an agreement is not proof that both are correct.

## Method

For each disagreement, I compared:

1. The historical review action and condition target.
2. The sale title, sale amount, and original condition ID.
3. The assigned PriceCharting product name, set/category, and price anchors.
4. The original cached eBay image, including card number, set, language, finish, packaging, grading
   company, and visible grade.
5. The model decision and its stated reason.

The adjudication deliberately does not infer an internal deletion reason when the public evidence
cannot show it. Deleted sales may reflect facts absent from this export, including a cancelled or
duplicate transaction, seller behavior, authenticity review, or an internal product assignment.

The compact `Feed -> system` column is not always the raw record. Raw status slugs such as
`manualonly` are normalized, and a displayed system result of `needs modification` can represent
raw `decision=ignored` plus `needs_modification=true`. The multi-label canvas preserves these fields
separately.

## Validation Cohort

| Listing ID | Feed -> system | Adjudication | Manual evidence and discrepancy cause |
|---|---|---|---|
| `177979887250` | ignored -> ignored + needs modification | **Model correct; datafeed product mismatch; feed action wrong** | Image shows the sealed Cosmos-holo movie-promo Pikachu 42/146. The row is assigned to standard [Pikachu #42](https://www.pricecharting.com/game/pokemon-xy/pikachu-42), product ID `806540`, but the correct [Pikachu Cosmos Holo #42](https://www.pricecharting.com/game/pokemon-xy/pikachu-cosmos-holo-42) is ID `7051675`. The model detected the variant; it did not output the target ID. Expected operational result: reassign to `7051675`, condition 1. |
| `127826616928` | manualonly (normalized ignored) -> ignored + needs modification | **PriceCharting API/data error; partial model error; feed action correct** | Raw `manualonly` reconfirms existing condition 7 / PSA 10, so normalization correctly produces `ignored`. Assigned ID `5921897` semantically identifies the Japanese Garchomp Half Deck card but now returns `No such product` from the API; the current public entry is [Garchomp #7](https://www.pricecharting.com/game/pokemon-japanese-garchomp-half-deck/garchomp-7), ID `9627427`. The model correctly identified the card and condition but unnecessarily added a language warning after enrichment failed. Expected: `ignored` after canonical-ID resolution, or human review explicitly because the API failed. |
| `dAWcEvVkUN9Y` | deleted -> ignored | **Not publicly verifiable** | Synthetic identifier, no cached image. Title exactly names Umbreon VMAX #215, but there is insufficient public evidence to validate or overturn deletion. |
| `376471407335` | deleted -> ignored | **Full model error; datafeed product mismatch; feed deletion protective** | Image and PSA label show the seated-Luffy Championship '23 World Final DON!! card in PSA 10. Assigned product `10538863` is [Championship 2024](https://www.pricecharting.com/game/one-piece-promo/don-card-championship-2024); correct product is [Championship 2023](https://www.pricecharting.com/game/one-piece-promo/don-card-championship-2023), ID `7063757`. Deletion keeps the sale off the wrong product, but reassignment is preferable. The model missed the year/artwork mismatch. |
| `188181836952` | deleted -> needs modification | **Correct diagnosis, action-label mismatch** | Image is an alternate/parallel Buggy OP09-042 rather than the low-value base printing represented by the assigned product. Reassignment is operationally sensible; the benchmark only records deletion. |
| `187335545174` | deleted -> ignored | **Full model error; datafeed product mismatch; feed deletion protective** | Image shows Japanese alternate-art/parallel Buggy OP09-042, while assigned product `8506907` is the base printing. The correct [Japanese alternate-art product](https://www.pricecharting.com/game/one-piece-japanese-emperors-in-the-new-world/buggy-alternate-art-op09-042) is ID `8506909`. Deletion rejects the bad assignment; reassignment is preferable. The model matched only the card number. |
| `144210478354` | deleted -> ignored | **Not publicly verifiable** | Image is the Japanese Koga's Ninja Trick card and title/product match. The low sale price may suggest authenticity or transaction concerns, but the image does not prove them. |
| `366364450161` | deleted -> needs modification | **Not publicly verifiable** | Image and title identify Japanese Latias & Latios GX 105/095. The $61.99 sale is extreme against the roughly $1,010 raw anchor, which is a real anomaly, but public evidence cannot distinguish counterfeit, damage, or bad transaction from a valid bargain. |
| `117129733842` | deleted -> needs modification | **Correct diagnosis, action-label mismatch** | PSA label explicitly says Enel “Special Alternate Art,” while the assigned product is the ordinary alternate art. The system correctly identified a sibling-product mismatch. |
| `358652056222` | deleted -> needs modification | **Correct diagnosis, action-label mismatch** | Title says booster-box **case**, while assigned product is one booster box. The system correctly found the unit/packaging mismatch and proposed reassignment. |
| `267686069139` | deleted -> ignored | **Reference label questionable** | Image and number 246/182 match Golisopod ex #246; it is a single raw card. No public deletion reason is visible. |
| `357457930630` | deleted -> condition 5 | **Partial model error; datafeed product mismatch; feed deletion protective** | The image is the Championship '23 World Final card, not assigned [Championship 2024](https://www.pricecharting.com/game/one-piece-promo/don-card-championship-2024); correct product is [Championship 2023](https://www.pricecharting.com/game/one-piece-promo/don-card-championship-2023), ID `7063757`. The model correctly read PSA 9 / condition 5 but missed product identity. Expected: reassignment plus condition 5. |
| `388666503217` | deleted -> ignored | **Reference label questionable** | Image shows the exact Japanese Tohoku's Pikachu 088/SM-P, raw. No public evidence explains deletion. |
| `800017111084` | deleted -> ignored | **Not publicly verifiable** | Image and card number show Poncho-Wearing Eevee 141/SM-P, but the $68.70 price is far below the catalog anchor. Authenticity cannot be resolved reliably from this single image. |
| `147254139070` | deleted -> needs modification | **Not publicly verifiable** | Image is the correct Nami Treasure Rare in an FCG 10 holder, while original condition is ungraded. The export does not define how unsupported grading companies should be recorded, so the choice between deletion, ungraded, and human review is policy-dependent. |
| `406928040878` | deleted -> ignored | **Policy-dependent / not publicly verifiable; product and condition match** | Image confirms the exact assigned Rayquaza VMAX #218 in PSA 10, mounted in a protective extended-art acrylic display. Comparable displays sell separately for roughly $15–$27, versus the $2,600 feed sale, so the card drives nearly all value. The model's `ignored` recommendation is reasonable if protective displays are tolerated. Feed `deleted` is only supportable under an explicit accessory-bundle policy or an unavailable internal reason. The deterministic regex did not match `extended display`. |
| `358618146707` | deleted -> ignored | **Not publicly verifiable** | Image and number match Japanese McDonald's Squirtle 007/018 Holo. The price is far below the catalog anchor, but the image alone cannot prove counterfeit or invalid transaction. |
| `297854557406` | deleted -> needs modification | **Correct diagnosis, action-label mismatch** | Assigned product is Japanese Manga Zoro, but the visible card text is English. The system correctly found the language/product mismatch. |
| `326848667135` | deleted -> condition 1 | **Not publicly verifiable** | “PSA 1 CNTNDR” means PSA 1 contender, not a PSA slab, so condition 9 was wrong. However, the image shows an extremely creased, torn-looking raw card. Changing it to ungraded is schema-correct, but deletion is also defensible if PriceCharting excludes severely damaged comparables; that policy/reason is not exposed in the feed. |
| `387415426244` | deleted -> needs modification | **Correct diagnosis, action-label mismatch** | Title explicitly says Alt Art PRB-01, while assigned product is the base OP06 printing. The system correctly requested sibling-product reassignment. |
| `405312844637` | deleted -> needs modification | **Not publicly verifiable** | PSA label identifies a Chinese 1st Anniversary Nami #016 serialized card. The current product title also says Nami 1st Anniversary, so deletion may concern serialization or an internal product distinction not exposed by the API. |
| `127920802663` | deleted -> needs modification | **Correct diagnosis, action-label mismatch** | Image shows the sealed One Piece Day '25 premium collection, not a loose P-110 card. PriceCharting has a matching [Premium Card Collection sealed-product entry](https://www.pricecharting.com/game/one-piece-japanese-promo/premium-card-collection-one-piece-day-%2725), product ID `10656758`. The system correctly detected that the sale should be reassigned from single-card product `10338790`; the evaluation penalized it only because the historical action was `deleted`. |
| `168189988481` | condition 17 -> needs modification with 17 | **Appropriate conservative route** | Image is CGC Gem Mint 10, supporting condition 17, but title says PSA 10 and Japanese while the slab identifies Traditional Chinese. The proposed condition was correct and human review was warranted for the product-language conflict. |
| `336578936990` | condition 7 -> needs modification with 7 | **Appropriate conservative route** | Image is PSA 10 while title says PSA 9. The system selected condition 7 but refused to ignore the title/image contradiction. That is safer than treating this as an ordinary incorrect prediction. |
| `358613994372` | condition 9 -> needs modification | **Appropriate conservative route** | PSA label visibly says 1.5. The historical target buckets it into Grade 1, but condition documentation has no explicit 1.5 mapping. Human review exposed a missing deterministic normalization rule. |
| `366323133476` | needsMod -> ignored | **Historical needsMod not evaluable** | Current product and image both identify Boa Hancock Special Alternate Art EB03-026 in PSA 10. PriceCharting says the final needsMod result is written to the sale entity, so this may be the already-corrected product. |
| `366417706424` | needsMod -> ignored | **Historical needsMod not evaluable** | Current product, title, image, and PSA 10 condition all match Rayquaza VMAX #218. The pre-modification product is unavailable. |
| `168389695475` | needsMod -> condition 14 | **Partial model error; datafeed product mismatch; feed action correct** | Image is an ACE 4 slab containing [Mew BW98](https://www.pricecharting.com/game/pokemon-promo/mew-bw98), ID `1563493`, not assigned [4-Pack Blister Pack](https://www.pricecharting.com/game/pokemon-promo/4-pack-blister-pack), ID `12001084`. The model read ACE 4 but missed reassignment. A matching listing title appears in PriceCharting's ungraded bucket, while the feed amount is $94.03; expected condition is therefore 1 or human review pending an explicit ACE policy—not established condition 14. |

## Final Cohort

| Listing ID | Feed -> system | Adjudication | Manual evidence and discrepancy cause |
|---|---|---|---|
| `136774539819` | ignored -> condition 17 | **Confirmed reference/feed error** | Image is unmistakably a CGC Gem Mint 10 slab, while original condition is ungraded. The exact $34 sale also appears in PriceCharting's ungraded sold-listings section. The system's CGC 10 correction is supported; historical `ignored` incorrectly confirmed condition 1. |
| `116638228859` | ignored -> ignored + needs modification | **Model correct; datafeed product mismatch; feed action wrong** | PSA label identifies Diamond Preview PSA 10. The row is assigned to standard [Spider-Man #29](https://www.pricecharting.com/game/marvel-1990-universe/spider-man-29), ID `5077062`; correct [Diamond Preview](https://www.pricecharting.com/game/marvel-1990-universe/spider-man-diamond-preview-29) is ID `9714060`. The model detected the variant but did not output the target ID. |
| `pVwMKIc9c1rs` | deleted -> ignored | **Not publicly verifiable** | Synthetic identifier, no cached image. Title matches Rayquaza EX #85, but deletion cannot be adjudicated from title alone. |
| `287220021730` | deleted -> needs modification | **Not publicly verifiable** | Image and PSA label match Winner P-061 PSA 10. This row and `287251796749` use the exact same image bytes and certificate, so duplicate/relisted-sale handling is plausible, but the export lacks transaction history. |
| `366439643400` | deleted -> needs modification | **Appropriate conservative route; product assignment correct; feed deletion policy-dependent** | The assigned [Sprigatito Horizons Full Art #109](https://www.pricecharting.com/game/pokemon-chinese-gem-pack/sprigatito-horizons-full-art-109), ID `8710136`, is the exact Chinese CBB1C-01 09/09 product shown in the slab. The earlier audit incorrectly called this a product mismatch. The actual issue is a “7 Grading” Gem Mint 10 slab assigned to ungraded condition 1, with no matching condition ID. Human review was appropriate; deletion depends on unsupported-grader policy. |
| `287251796749` | deleted -> needs modification | **Not publicly verifiable** | Exact image duplicate of `287220021730`, with the same PSA certificate. Product and condition visually match, but duplicate transaction validity is not exposed. |
| `287361315070` | deleted -> ignored | **Full model error; datafeed product mismatch; feed deletion protective** | Image and title identify a Chaos Rising booster box, but assigned product `10616084` is [Mega Evolution](https://www.pricecharting.com/game/pokemon-mega-evolution/booster-box). Correct [Chaos Rising Booster Box](https://www.pricecharting.com/game/pokemon-chaos-rising/booster-box) is ID `12579973`. Deletion rejects the bad assignment; reassignment is preferable. |
| `389789113668` | deleted -> ignored | **Not publicly verifiable** | Image and PSA label support Chinese Fuecoco #09 PSA 10 and the assigned Horizons product appears consistent. The low price may indicate an authenticity/transaction issue that cannot be confirmed publicly. |
| `157864951321` | deleted -> ignored | **Full model error; datafeed product mismatch; feed deletion protective** | Image has reverse-holo foil; assigned [Tyrantrum #45](https://www.pricecharting.com/game/pokemon-perfect-order/tyrantrum-45), ID `12584352`, is non-holo deck-exclusive. Correct [Reverse Holo](https://www.pricecharting.com/game/pokemon-perfect-order/tyrantrum-reverse-holo-45) is ID `12385647`. The model emitted `non-foil`. Deletion is protective; exact transaction validity is unavailable. |
| `318045361830` | deleted -> needs modification | **Not publicly verifiable** | PSA label and card match Winner P-061 PSA 10. Public evidence does not expose why this transaction was deleted; the model's price concern is not enough to establish the reason. |
| `117226612085` | deleted -> ignored | **Reference label questionable** | Image and number 254/198 exactly match Koraidon ex #254, raw. No public deletion reason is visible. |
| `406943476110` | deleted -> needs modification | **Correct diagnosis, action-label mismatch** | PSA label says Indonesian SV8a Umbreon 217/187, while assigned product is Japanese Terastal Festival. The system correctly identified the language/product mismatch. |
| `336040429686` | deleted -> ignored | **Full model error; datafeed product mismatch; feed deletion protective** | Title identifies the ST23 reprint of Shanks OP09-001, but assigned product `8507023` is original OP09. Correct [Japanese Starter Deck 23 product](https://www.pricecharting.com/game/one-piece-japanese-starter-deck-23-red-shanks/shanks-op09-001) is ID `13346044`. Deletion rejects the bad assignment; reassignment is preferable. |
| `287233336983` | deleted -> needs modification | **Not publicly verifiable** | Image and PSA label match Winner P-061 PSA 10. Unlike the exact duplicate pair, this has a different certificate; no public deletion reason is available. |
| `327119413823` | deleted -> needs modification | **Not publicly verifiable** | Image is the older One Piece CCG “Vow of the Tattoo” CH024 card and matches the current catalog product. The title says holo and price is extreme, but the export does not reveal whether finish, authenticity, or transaction validity caused deletion. |
| `800158121808` | deleted -> needs modification | **Correct diagnosis, action-label mismatch** | Shipping carton label explicitly says six Fusion Strike displays. Assigned product is one booster box. The system correctly found case-versus-box quantity. |
| `318265494656` | deleted -> ignored | **Not publicly verifiable** | Raw Winner P-061 card, title and image match, and price is near the raw anchor. Internal deletion reason is unavailable. |
| `267637169529` | deleted -> needs modification | **Correct diagnosis, action-label mismatch** | Title says PRB-01 Full Art and image/stock image shows the Foil Special printing; assigned product is the OP03 base card. The system correctly found the printing mismatch. |
| `127658912817` | deleted -> ignored | **Not publicly verifiable** | PSA label and image match Typhlosion #16 PSA 10, but the $2,999.99 sale is more than six times the PSA 10 anchor. This may be a transaction anomaly; image review cannot prove it. |
| `366387028588` | deleted -> ignored | **Not publicly verifiable** | Image and number 110/098 match Japanese Lugia V #110. Sale price is far below the raw anchor, raising authenticity/transaction concerns that a single image cannot settle. |
| `277278272084` | deleted -> ignored | **Reference label questionable** | PSA label exactly matches Japanese Rotom V #104 PSA 10. Price is elevated but not enough to prove invalidity; no deletion reason is visible. |
| `306918676367` | deleted -> needs modification | **Not publicly verifiable** | Correct Wigglytuff #91 is in an RPA 10 holder while original condition is ungraded. Treatment of unsupported grading companies is not defined, so deletion versus ungraded/human review is policy-dependent. |
| `287378126818` | condition 3 -> needs modification | **Appropriate conservative route** | Image is CGC 7.5. Historical review buckets it into Grade 7, but the supplied condition catalog has no explicit half-grade rule. The model correctly refused to invent one. |
| `188166657897` | condition 7 -> needs modification with 7 | **Appropriate conservative route** | Title says PSA 9 while the image label says PSA 10. The model selected the historical target, condition 7, and routed the contradiction to a human. |
| `405107918595` | gradednew (target condition 5) -> condition 2 | **Model correct; datafeed condition target wrong; product assignment correct** | Original condition was 1 / ungraded; raw `gradednew` created historical target 5 / Grade 9. The slab is CGC 8.5, making condition 2 / Grade 8 the best-supported numeric bucket. PriceCharting methodology explicitly names PSA/BGS 8.5, not CGC 8.5, so the CGC policy should be documented rather than overstated. |
| `287265005361` | needsMod -> ignored | **Historical needsMod not evaluable** | Current product, title, image, first-edition marker, and PSA 9 condition all match Suicune #14. The pre-modification assignment is unavailable. |
| `406912009863` | needsMod -> ignored | **Historical needsMod not evaluable** | Current product, title, image, and PSA 10 condition all match Pikachu V SWSH285. The row cannot reveal what product was corrected. |
| `406945485080` | needsMod -> ignored | **Historical needsMod not evaluable** | Current product, title, image, and PSA 10 condition all match Charizard V SWSH260. The pre-modification assignment is unavailable. |
| `117128811891` | needsMod -> ignored | **Historical needsMod not evaluable** | Current product and PSA label match Japanese 1st Edition Azumarill #026 PSA 10. The original erroneous product is not exposed. |
| `405073528566` | needsMod -> ignored | **Historical needsMod not evaluable** | Current title, image, collector number 0330, borderless treatment, foil finish, and product all match Chthonian Nightmare. The current sale appears to contain the completed modification. |

## Root Causes

### Full and partial model failures

The five full and two primary partial failures group into concrete, fixable causes. The
API-degraded Garchomp row also contains a partial model over-route.

| Root cause | Listings | Required change |
|---|---|---|
| Product/object mismatch partly missed | `168389695475` | Product type and visible object must be checked before condition. A slabbed single card cannot match a sealed blister-pack product. |
| Finish mismatch missed | `157864951321` | Finish must be an explicit identity gate: non-foil, holo, reverse holo, and special foil are not interchangeable. |
| Artwork/year/parallel mismatch missed | `187335545174`, `376471407335`, `357457930630` | Generic product names and card numbers are insufficient. Compare visible artwork and event year against retrieved sibling products. |
| Set/reprint mismatch missed | `336040429686`, `287361315070` | Match set/product printing in addition to character and card number. ST23 vs OP09 and Mega Evolution vs Chaos Rising are distinct products. |

### Confirmed feed/reference failures

| Listing | Feed problem | Supported result |
|---|---|---|
| `177979887250` | Standard Pikachu product was confirmed despite a distinct Cosmos-holo promo sibling | Model correctly requested reassignment to product `7051675` |
| `116638228859` | Standard Spider-Man product was confirmed despite the Diamond Preview slab and distinct sibling | Model correctly requested reassignment to product `9714060` |
| `136774539819` | Ungraded condition was confirmed for a visible CGC Gem Mint 10 slab | Model correctly selected condition 17 |
| `405107918595` | Feed targeted Grade 9 for CGC 8.5; Grade 8 is the best-supported numeric bucket, but CGC half-grade policy is not explicit | Model selected condition 2 / Grade 8; document the CGC rule |

### Benchmark and ontology failures

1. **`deleted` is not a clean “wrong product” label.** It includes rows that visually match perfectly,
   probable transaction/authenticity failures, and rows where reassignment would be reasonable.
2. **Reassignment and deletion are scored as mutually exclusive even when the model correctly finds
   the invalid assignment.** Nine disagreements are detection successes but action-label mismatches.
3. **`needsMod` is temporally misjoined.** The review action describes a prior state while the sale
   entity can expose the corrected current product. Seven rows therefore cannot train or evaluate
   modification discovery.
4. **Public evidence is incomplete for deletion.** At least 18 disagreements need internal reason
   codes, transaction state, duplicate linkage, seller signals, or authoritative authenticity review.
5. **Contradictory title and image should not be scored as an ordinary miss.** Five rows were
   conservatively routed despite identifying the intended condition or exposing a missing mapping.

## Recommended Evaluation Redesign

Replace the single historical-action target with independently adjudicated fields:

- `product_match`: yes / no / unclear
- `condition_match`: yes / no / unclear
- `finish_match`: yes / no / unclear
- `language_set_printing_match`: yes / no / unclear
- `quantity_packaging_match`: yes / no / unclear
- `sale_validity`: valid / invalid / unknown
- `invalid_reason`: duplicate, cancelled, counterfeit, bundle, wrong product, wrong finish, other
- `correct_product_id`: required for product mismatch when available
- `correct_condition_id`: required for condition mismatch
- `evidence_availability`: title, image, internal transaction, seller, authenticity
- `raw_status` and `normalized_target`: retained separately
- `assigned_product_id_at_review` and `current_canonical_product_id`
- `feed_action_quality`: correct, directionally protective, wrong, or unverifiable
- `api_enrichment_status`: success, HTTP error, application error, fallback source

For the next benchmark:

1. Obtain the pre-review product ID and post-review product ID for `needsMod` rows.
2. Obtain deletion reason codes or manually adjudicate deletion with PriceCharting.
3. Treat a correct issue detection with human routing separately from a wrong automatic action.
4. Score product/variant detection separately from final workflow action.
5. Use a fresh holdout after the label schema and prompt are frozen.
6. Do not calculate a new headline accuracy until every holdout row, including agreements, receives
   an independent label.

## Immediate Product Changes

1. Keep all model recommendations in human review; no AI confidence or auto-accept.
2. Validate the new explicit finish/printing/language/packaging/card-code gates on a fresh cohort;
   define object-type and accessory rules before automating them.
3. Retrieve sibling product candidates before allowing a product-reassignment recommendation.
4. Add image-hash duplicate evidence. Two final listings used byte-identical images and the same PSA
   certificate.
5. Add explicit PriceCharting half-grade and unsupported-grader policy.
6. Surface “not publicly verifiable” instead of making the model invent a deletion explanation.
