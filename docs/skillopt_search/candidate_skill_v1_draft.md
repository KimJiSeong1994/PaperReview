# Candidate Skill — Jiphyeonjeon Paper Search v1

## Scope
Apply this policy only to the QueryAnalyzer standard search path: academic
classification, intent analysis, and source-specific query generation. It
governs the `source_queries` object and nothing downstream of it.

## Safety invariants
- Do not enable `use_llm_search` from this policy.
- Do not enable HyDE from this policy.
- Do not promote RelevanceFilter from this policy.
- Do not alter retrieval, ranking, caching, or source selection behavior.

## Intent classification
- When a query names a person and asks for their work, classify `author_search`.
- When a query has two or more unrelated common senses and the academic sense is
  not stated, classify the closest listed intent and treat the query as
  ambiguous for the disambiguation rule below. Do not invent a new intent value.
- Prefer `method_search` over `topic_exploration` when the query names a
  specific technique, architecture, or algorithm.

## Canonical-work anchoring
A short technical query often targets one seminal paper rather than a topic.
When the query names a technique whose canonical paper is well known, place the
canonical title as a quoted phrase in the first Google Scholar variant and as a
`ti:` term in the arXiv query. Do not replace the user's query with the title —
add it as one alternative alongside the decomposed terms.

Decomposing such a query into generic component words is the main way the
canonical paper is lost.

## Source-specific query rules

### arXiv
- Use field syntax: `(ti:A OR ti:B) OR (abs:A AND abs:B)`.
- For `author_search`, use `au:"Last, First"` combined with a topic term:
  `au:"Hinton, Geoffrey" AND (ti:capsule OR abs:capsule)`. Do not express an
  author query with `ti:`/`abs:` terms alone.
- Keep each field term to one or two words. Multi-word `ti:` terms match poorly.

### DBLP
- Emit 2 to 4 keywords. This is a hard limit, not a target. DBLP returns HTTP
  500 for long queries and the client truncates anything longer, so a 5+ word
  query is silently rewritten and the extra terms are wasted.
- Use nouns and proper technique names only. Drop verbs, prepositions, and
  qualifiers such as "using", "based", "via", "survey of".
- For `author_search`, emit the author surname plus one topic keyword.

### Google Scholar
- Emit 2 to 3 variants ordered specific to broad.
- Variant 1: quoted exact phrases from the query, plus the canonical title when
  the anchoring rule applies.
- Variant 2: the same concepts rephrased with standard field terminology.
- Variant 3: one adjacent framing that would surface the same work under a
  different name. Omit this variant rather than padding it with synonyms of
  variant 1.

## Ambiguity handling
When the query has a plausible non-academic or wrong-field reading, add one
domain-anchoring term to every source query — the research area, venue family,
or a companion technical term. Examples of readings to exclude: an "agent" query
matching real-estate or generic software agents; an "attention" query matching
only vision saliency maps.

Add the anchor as an extra term. Do not drop the user's original words to make
room for it.

## Language
- Translate non-English queries to English for `arxiv`, `dblp`, and
  `google_scholar`.
- Preserve the user's original wording in `improved_query` when the query names
  a proper noun, a title, or an author, so that Korean-language sources can
  still match it.

## Confidence
- Report confidence below 0.5 when the intent is ambiguous after applying the
  disambiguation rule.
- When confidence is below 0.5, keep `improved_query` close to the original
  query. Expose the uncertainty through `search_filters` and `search_strategy`
  rather than by rewriting the query more aggressively.
