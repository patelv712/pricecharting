# Ten-Listing Manual Verification

**Audit date:** July 29, 2026  
**Scope:** Ten user-selected PriceCharting review rows  
**Evidence used:** source row, original cached eBay image, PriceCharting catalog page, public
PriceCharting sold-listing data, and the original eBay page when it remained accessible

## Important Limitation

PriceCharting's export does not include a deletion reason. Public inspection can verify product,
variant, condition, and some transaction facts, but it cannot rule out a cancelled transaction,
duplicate/relist, seller manipulation, or an internal authenticity decision.

Accordingly:

- **Confirmed feed error** means the exported condition/action is directly contradicted by public
  evidence, including PriceCharting's own public sales bucket.
- **Likely feed/reviewer error** means all observable evidence supports tracking or correcting the
  sale, but an unexported internal deletion reason remains possible.
- **Deletion defensible** means the image or catalog exposes a concrete reason not to keep the sale
  on its assigned product. This does not imply deletion is better than product reassignment.

## Results

| Listing ID | Historical row | Verdict | Assigned PriceCharting page | Better page/action |
|---|---|---|---|---|
| `376471407335` | deleted; PSA 10; $1,038.28 | **Deletion defensible; assigned product is wrong** | [DON!! Card Championship 2024](https://www.pricecharting.com/game/one-piece-promo/don-card-championship-2024) | [DON!! Card Championship 2023](https://www.pricecharting.com/game/one-piece-promo/don-card-championship-2023), PSA 10 |
| `187335545174` | deleted; ungraded; $6.95 | **Deletion defensible; not a feed error** | [Japanese Buggy OP09-042 base](https://www.pricecharting.com/game/one-piece-japanese-emperors-in-the-new-world/buggy-op09-042) | [Japanese Buggy alternate art](https://www.pricecharting.com/game/one-piece-japanese-emperors-in-the-new-world/buggy-alternate-art-op09-042) |
| `267686069139` | deleted; ungraded; $12.99 | **Likely feed/reviewer error (moderate)** | [Golisopod ex #246](https://www.pricecharting.com/game/pokemon-paradox-rift/golisopod-ex-246) | Keep on assigned product as ungraded |
| `357457930630` | deleted; PSA 10; $900.00 | **Deletion defensible; product and condition are wrong** | [DON!! Card Championship 2024](https://www.pricecharting.com/game/one-piece-promo/don-card-championship-2024) | [DON!! Card Championship 2023](https://www.pricecharting.com/game/one-piece-promo/don-card-championship-2023), Grade 9 / ID 5 |
| `388666503217` | deleted; ungraded; $999.99 | **Likely feed/reviewer error (strong)** | [Tohoku's Pikachu #88/SM-P](https://www.pricecharting.com/game/pokemon-japanese-promo/tohoku%27s-pikachu-88sm-p) | Keep on assigned product as ungraded |
| `326848667135` | deleted; Grade 1; $10.50 | **Deletion defensible; not enough evidence to call a feed error** | [Typhlosion #28](https://www.pricecharting.com/game/pokemon-expedition/typhlosion-28) | If retained, condition must be ungraded / ID 1, not Grade 1 |
| `136774539819` | ignored; ungraded; $34.00 | **Confirmed feed condition error** | [Squirtle #1](https://www.pricecharting.com/game/pokemon-tcg-classic-blastoise-deck/squirtle-1) | Keep product; change condition to CGC 10 / ID 17 |
| `287361315070` | deleted; ungraded; $225.46 | **Deletion defensible; assigned product is wrong** | [Pokemon Mega Evolution booster box](https://www.pricecharting.com/game/pokemon-mega-evolution/booster-box) | [Pokemon Chaos Rising booster box](https://www.pricecharting.com/game/pokemon-chaos-rising/booster-box) |
| `117226612085` | deleted; ungraded; $2.80 | **Likely feed/reviewer error (moderate)** | [Koraidon ex #254](https://www.pricecharting.com/game/pokemon-scarlet-%26-violet/koraidon-ex-254) | Keep on assigned product as ungraded |
| `277278272084` | deleted; PSA 10; $149.88 | **Likely feed/reviewer error (moderate)** | [Japanese Rotom V #104](https://www.pricecharting.com/game/pokemon-japanese-lost-abyss/rotom-v-104) | Keep on assigned product as PSA 10 |

## Evidence By Listing

### 376471407335

- The cached image shows the seated-Luffy Championship '23 World Final DON!! card.
- The PSA label reads Gem Mint 10 and certificate `101214753`.
- The original [eBay listing](https://www.ebay.com/itm/376471407335) remains public: sold for
  $1,038.28 after 26 bids, condition PSA 10, with eBay Authenticity Guarantee.
- The assigned Championship 2024 page has different artwork: Luffy reaches toward the viewer and
  the card is marked Championship 2024.
- PriceCharting has a distinct Championship 2023 page, product ID `7063757`, with the seated-Luffy
  artwork and matching `Championship '23 World Final` sales.
- The sale should be reassigned to Championship 2023 as PSA 10. It must not remain on the assigned
  Championship 2024 product.

### 187335545174

- The visible card number is OP09-042, but the full-art/parallel artwork does not match the assigned
  Japanese base printing.
- PriceCharting has a distinct Japanese alternate-art OP09-042 product.
- The sale should not remain on the assigned base page. Deletion is therefore defensible, although
  reassignment to the alternate-art page would preserve a valid sale.
- The prior multimodal `ignored` decision was wrong because it over-weighted the card number.

### 267686069139

- The image shows one raw English Golisopod ex with collector number 246/182.
- Artwork, number, language, object count, and ungraded condition match the assigned product.
- The $12.99 price is low relative to the current guide but not self-evidently impossible.
- The original eBay transaction page is no longer publicly inspectable, so this remains likely
  rather than confirmed.

### 357457930630

- The image is the seated-Luffy Championship '23 World Final DON!! card, while the assigned
  Championship 2024 page has different Luffy artwork.
- The title and exported condition say PSA 10, but the slab label visibly reads Mint 9,
  certificate `108111260`.
- The correct product is Championship 2023, product ID `7063757`, and the correct condition is
  Grade 9 / ID 5.
- Deletion is defensible for the assigned product. Reassignment plus condition correction would
  preserve the valid sale.

### 388666503217

- The image and eBay item specifics identify Japanese Tohoku's Pikachu 088/SM-P, Holo, ungraded.
- The [original eBay page](https://www.ebay.com/itm/388666503217) shows one unit sold at $999.99.
- Buyer feedback attached to this item says the card arrived as described and was packed well.
- The listing is a multi-quantity listing and the price is a major outlier. Those are review
  signals, but neither disproves the completed matching sale.

### 326848667135

- The image is the correct Expedition Typhlosion 28/165, but it is raw and severely creased.
- "PSA 1 CNTNDR" means PSA 1 contender; it is not a PSA-graded Grade 1 card.
- Therefore the exported pre-review condition 9 was wrong. If tracked, it belongs in ungraded.
- The extreme damage makes deletion a reasonable pricing-quality decision. Because the export has
  no reason code or explicit damaged-card policy, the exact reviewer rationale cannot be proven.

### 136774539819

- The image shows a CGC Gem Mint 10 slab for Squirtle 001/034.
- The row says ungraded and historical `ignored`, which would confirm the wrong condition.
- The exact $34 sale was also placed in PriceCharting's public ungraded sold-listings bucket.
- This is the only row in this group where PriceCharting's public classification independently
  corroborates the exported condition mistake.

### 287361315070

- The image and title say `Mega Evolution: Chaos Rising`, factory-sealed 36-pack booster box.
- The assigned product ID `10616084` is the booster box for the separate Pokemon Mega Evolution
  set.
- PriceCharting's correct Chaos Rising booster-box page is product ID `12579973`.
- The sale is invalid for the assigned page. Reassignment would be more useful than deletion, but
  this is not evidence of a bad deletion label.

### 117226612085

- The image shows one raw English gold Koraidon ex, collector number 254/198.
- Artwork, number, set, language, and ungraded condition match the assigned product.
- The $2.80 price is low but does not by itself prove an invalid transaction.
- With no accessible transaction page or internal reason, this is a moderate likely feed/reviewer
  error, not a confirmed one.

### 277278272084

- The slab label reads `2022 POKEMON JPN.SWSH F/A/ROTOM V LOST ABYSS #104 GEM MT 10`.
- Card, Japanese set, collector number, PSA company, and grade all match the assigned row.
- The $149.88 price is elevated relative to surrounding public comparables, which may explain why
  it was reviewed, but a high price alone is not proof that the sale is invalid.
- The transaction page and internal reason are unavailable, so this remains a moderate likely
  feed/reviewer error.

## Bottom Line

The evidence does **not** support treating all ten as datafeed errors:

- 1 confirmed feed condition error: `136774539819`
- 1 strong likely feed/reviewer error: `388666503217`
- 3 moderate likely feed/reviewer errors: `267686069139`, `117226612085`,
  `277278272084`
- 5 defensible deletions: `376471407335`, `187335545174`, `357457930630`,
  `326848667135`, `287361315070`

For the four likely deletion errors, authoritative confirmation still requires PriceCharting's
internal deletion reason or transaction record.
