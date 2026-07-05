# SkillOpt Deep Review Baseline Skill v0

Scope: `deep_review_analysis_prompt`.

This baseline preserves the current DeepReview analysis prompt path while making
future SkillOpt improvements explicit, reproducible, and rollback-safe.

Required safety constraints:
- DeepReview analysis prompt path must only adjust reviewer guidance for the LLM analysis prompt.
- Do not change paper loading, workspace persistence, session ownership, or report serving behavior.
- Do not bypass fact verification, advisor validation, schema validation, or loud failure semantics.
- Do not enable production rollout without an approved hash-bound policy artifact and explicit env gate.
- Preserve evidence-based critique: cite paper content, separate strengths from limitations, and never invent results.
