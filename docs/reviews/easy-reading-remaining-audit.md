# Remaining easy-reading publication audit

## Scope and result

The authorized scope is 75 existing paper-review and conference-trend posts. Seven engineering/product posts are excluded. Four reviewed releases cover 74 distinct manuscripts, with 176 core-figure placements in their easy views. The six previously completed easy views bring coverage to 80 of 81 published paper reviews.

| Release | Manuscripts | Easy-view figures | Change |
| --- | ---: | ---: | --- |
| release01 | 10 | 29 | First two reviewed groups ([PR 311](https://github.com/KimJiSeong1994/PaperReview/pull/311)) |
| release02 | 14 | 37 | Corrected ColPali/LoongReflect crops ([PR 312](https://github.com/KimJiSeong1994/PaperReview/pull/312)) |
| release03 | 20 | 45 | Source-collection identity, LightGCN crop, IC2S2 count scope ([PR 313](https://github.com/KimJiSeong1994/PaperReview/pull/313)) |
| release04 | 30 | 65 | Final reviewed group, five corrected source crops |

The IC2 article (`ic2-interventional-dynamical-causality-under-latent-confounders`, DOI 10.1098/rsif.2025.1289) retains its prior published body. The full primary paper was unavailable through the checked publisher/local/author routes; its outline is not promoted as a fully verified easy review.

## Editorial controls

Every promoted article has a primary-source evidence ledger, a separate skeptical review, correction closure, actual im-not-ai Korean editing, and a post-edit semantic check. Citation editions, metric denominators, inference scope, and figure panels were checked. Examples of corrected draft errors include mixing two attention papers, confusing title-only with abstract-inclusive conference counts, mislabeling book chapters as journal articles, confusing total training tokens with cost per point, and attributing source-table values to the wrong metrics. The paper experiments were not independently reproduced.

Reviewed PaperWiki files supply the promoted content and excerpts. Original IDs, titles, slugs, dates, tags and categories are retained. Detailed text remains unchanged except nine explicitly reviewed figure/count corrections across these releases. Older Wiki variations are preserved with exact-match replacements and backups.

## Final-release validation

- 103 related backend/frontend tests passed; TypeScript/Vite build and whitespace checks passed.
- Thirty exact API responses and sixty selected SSR reading views passed, with canonical URLs, source identity and excerpts checked.
- Sixty desktop/mobile browser cases passed: 130 decoded image instances, full-size links, reading-mode and PDF identity, reload/back navigation, and no-JavaScript navigation.
- The latest-30 RSS feed and full canonical sitemap passed.
- Independent prepublication audit verified exactly thirty selected changes, fifty-eight untouched posts, all 108 manifest assets with matching hashes, and thirty valid manuscript approvals.

Release-specific source/crop provenance is retained beside each publication note. This audit describes the checked release artifacts; deployment receipts are recorded after each production rollout.
