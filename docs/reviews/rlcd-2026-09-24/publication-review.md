# RLCD publication review

One paper-review post at `/blog/rlcd` provides an 8-minute introductory article and a 24-minute detailed review at `?view=deep`. Both versions use the original paper title and the same arXiv v3 identity. Separate canonical indexing follows the existing EvoOntology convention.

## Editorial evidence

- Compared SkillOpt and five recent posts: EvoOntology, Multi-token Prediction, RLT, TTPO, and RSI Roadmap. The audit covers introductions, explanation order, evidence, critical tone, figures, and references.
- Preserved the draft's method, prompt design, 7B/30B results, reward-model analysis, rescoring, length/diversity evidence, controls, and theoretical assumptions. Removed repeated rhetorical criticism and unused bibliography entries.
- Distinguished simulator size from the fixed LLaMA-7B downstream policy; human mean preference scores from GPT-4 comparison percentages; held-out reward-model agreement from direct human judgments.
- Limited 30B and length conclusions to the measured evidence. The few-shot Help value refers to helpfulness within the harmlessness task. Outline data are excluded from the held-out reward and 20%-human controls.
- The official repository provides harmlessness/helpfulness simulated data, omits outline prompts, and is archived. This review did not retrain models or independently reproduce benchmark runs.
- PaperWiki was updated first, and re-read normalized article bodies exactly match the blog payload. The original draft remains locally backed up.

## Independent review disposition

The skeptical reviewer initially requested clearer sample denominators, auxiliary-task scope, Dist-n definition, theory notation, and DPO citation. These were applied. A final recheck approved the narrowed human-data control, archived repository note, and alphabetized references (`OKAY`).

The verifier checked the PDF's numbers, table/page anchors, figure provenance, and payload identity and returned `PASS`. The Figure 2 first-impression instruction was not used as causal evidence of length bias. User-provided paper figures satisfy the skill's reuse condition; Figure 1 was re-extracted from the same PDF to exclude the running header while retaining the diagram.

## Validation

- 99 related backend reading-view, slug, reference, thumbnail, and SEO tests passed.
- TypeScript and Vite production build passed; existing bundle-size warning remains.
- JSON, source/payload equality, references, figure hashes, and unchanged existing 89 records verified.
- Browser and live HTTP receipts are stored alongside this review when executed.

The publication adds one record and two figure files. It requires no application-code change or new dependency.
