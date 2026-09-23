# Published easy-reading prose review

## Scope

Reviewed all 81 published easy-reading articles and their excerpts using the actual `im-not-ai` Korean humanization skill and its quick rules. The reviewed publication was the evidence base: this pass changes wording and punctuation, not scientific claims. Existing detailed bodies, titles, URLs, indexing policy, figures, tables, and references are preserved.

Three writers reviewed 27 articles each. A separate semantic critic checked every proposed sentence edit; a verifier checked immutable inputs, exact edit-ledger reconstruction, numeric and technical tokens, protected blocks, official change-rate gates, source mapping, and guarded publication.

## Editorial decisions

- Correct awkward subject–verb combinations: `이슈 해결률을 올린다고 보이지 않는다` → `이슈 해결률을 올린다고 보여 주지 않는다`.
- Use direct phrasing without changing the claim: `가장 먼저 필요한 것은 신뢰할 수 있는 자동 verifier다` → `신뢰할 수 있는 자동 verifier가 가장 먼저 필요하다`.
- Preserve task definitions as task definitions: NeuroGravity continues to describe `절대량을 복원하는 문제를 다룬다`, rather than claiming every missing flow is successfully recovered.
- Match isolated closing sentences to each article's established register.
- Remove unnecessary connecting commas, while restoring the comma before `특히` in InCoder where it marks a useful focus shift.
- Keep already-natural passages unchanged. Preserve legitimate technical, contrastive, and source punctuation rather than maximizing a style score.

## Verification and publication

Per-article edit ledgers, original/final hashes, actual skill summaries and official change-rate results are retained in the local publication report. Natural or protected forms that resemble C-11 remain; the report does not claim a perfect or independently certified humanization grade. A stricter stylistic assessment can use the skill's Claude Code strict three-call mode.

PaperWiki remains the reviewed source: source manuscripts are hash-checked, backed up and updated before promoting the same bodies and excerpts to the blog. Publication changes only `content`, `excerpt`, `reading_time_min`, and `updated_at` for affected posts. Each detailed body and all unrelated records are compared against the original snapshot.

Final review: 81 articles, 66 with accepted changes (53 bodies and 18 excerpts, with 5 overlapping), 90 sentence-level edits, and 15 articles retained unchanged. Official change rates are 0.0–1.0% (rounded by the upstream verifier). Source-preservation validation passed for all 81 articles. Independent semantic review approved all 90 final edits after the InCoder comma repair.

Validation: 72 backend reading/reference/SEO tests, 40 frontend reading/detail/reference tests, and the TypeScript/Vite production build passed. Preview validation also passed for all 89 stored/API articles, both SSR reading views of each changed article (132 views), RSS and sitemap. Twelve desktop/mobile browser cases decoded 36 easy-reading images and preserved detailed reading and back navigation. The same release is checked on production before Wiki manuscripts are marked published.

See [per-article edit ledger](easy-reading-prose-polish.json) for original/final hashes, preserved detailed-body hashes, official change-rate results and exact accepted edits.
