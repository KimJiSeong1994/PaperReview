# Baseline Skill — Jiphyeonjeon Paper Search v0

## Scope
This baseline describes the existing QueryAnalyzer standard search policy for offline SkillOpt experiments. It is documentation and evaluation input only; it is not loaded by production code in PR1.

## Invariants
- Optimize only the QueryAnalyzer standard search path for v1.
- Do not include `use_llm_search` in v1 promotion.
- Do not enable `use_llm_search` in v1 promotion.
- Do not enable HyDE prompt optimization in v1 promotion.
- Do not promote RelevanceFilter prompt optimization in v1 promotion.
- Preserve the production confidence gate: only high-confidence improved queries may replace the original user query.
- Preserve source-specific query contracts for arXiv, DBLP, Google Scholar, and default search.
- Preserve Korean, English, and mixed-language intent understanding.

## Search policy
1. Identify academic intent and reject clearly non-academic queries.
2. Preserve exact-title and author-centric queries instead of over-expanding them.
3. For broad topic or survey queries, add concise technical synonyms and source-specific phrasing.
4. For recency queries, retain the user's freshness constraint in metadata rather than hiding it in rewritten prose.
5. When confidence is low, prefer the original query and expose uncertainty through metadata.

## Rollback
If candidate evaluation fails, revert to this baseline skill hash and keep production behavior unchanged.
