# Independent critical findings — checkpoint

These are external editorial artifacts, never published inside the paper articles. Final critic reports supersede this rolling checkpoint. Source anchors are in the associated primary PDFs and critics' handoffs.

## Semantics/causality: first 12

- Systematic LSC comparison: method/results/figures pass.
- Tahmasebi survey: official 2021 chapter now downloaded as `sources/tahmasebi-2021.pdf` (92p). Actual title ends in **Change Detection**, including published version. Fix H1/Paper/References; eight evaluation items do appear in §8.2. Do not infer publication-before-SemEval-2020 from 2021 date. Remove `(논문 외 비판)` labels.
- Giulianelli: remove four `(논문 외 비판)` heading labels; retain source-backed methodological limits.
- Periti/Montanelli contextual survey: remove five `(논문 외 비판/해석)` labels; published title and author order checked.
- Kulkarni: delete false criticism that Eq.9 uses variance while calling it standard deviation. It uses sqrt(Var). Keep separately supported B≈1000 versus 0.0001 reporting ambiguity.
- DSG: shared global diffusion D does not imply every word's posterior must change at the same rate. Narrow to lack of word-specific prior volatility. Remove review labels.
- Ethayarajh: restore actual subtitle; MEV shows a single static vector/first-PC limit, not impossibility of a finite set of semantic vectors. Narrow to one vector.
- TWEC: static analogy task is favored by shared coordinates, not almost trivial merely from alignment. Remove review labels.
- HistWords: remove false 28-versus-nine inconsistency. The 28 are individual shift relations grouped into nine target-word rows in Table 2.
- DCWE: remove `이 글은...굵게`, `논문 외 환산`, and review labels; retain substantive explanation.
- Boundary: remove wiki-role division, Korean application/preregistration proposals, external PRISMA yardstick and reviewer-program text (§7.2–7.4). Retain paper's 21-study coding, 14/21 human GT, 9/21 dispersion, recommendations and academic limits.
- PAPG: remove inferred coauthor lineage, uncited-literature audit, wiki/KGSS/Korean migration program (§6.3–6.4). Preserve primary-paper numerical inconsistencies only where anchored.

## Graphs: first 3

- SDNE: B weights residual by beta, hence squared loss by beta² (Eq.3), not beta. Delete unsupported extra shrinking beyond unlabeled-node removal for YouTube 1.1M→22,693. Replace assumed single-run with repetition/variance not reported. Replace misuse of statistical power with lack of significance comparison against strong LINE baseline. Remove reader/wiki-process tables.
- GNN+: use correct primary 2502.09263v3. Appendix B.2/Table14 fixed-all-six configuration and Appendix C.1 earlier-GNN lineage qualify tuning/Transformer-only criticisms. Five binary toggles plus continuous dropout, not six binary switches. Parameter-budget mismatch is unreported control, not established inequality.
- HAN: narrow universal claimed winning conditions to evaluated DBLP/ACM observations. HGB specific accusation needs exact source or generalize conservatively. Remove wiki/series cross-navigation from paper explanation.

## RAG/agents: first 3

- SkillOpt CRITICAL: optimization selects on D_sel from candidates built on D_tr; D_test is final reporting only (PDF §3.1 Eq.2–3). Replace current argmax over D_test.
- SkillOpt: 52 cells = direct-chat 7×6=42 plus GPT-5.5 two harnesses×five tasks=10. Do not invent a 126-cell target population and call the observed cells curated/self-selected. Bound compute-comparison critique to lack of comparable per-baseline total optimization tokens/API cost. Remove author/process commentary.
- SEED: best/tied aggregate comparisons are 9/12, not 10/12. Add Qwen2.5-3B Search 45.7 < Skill-SD 47.8, alongside the two existing losses. Avoid claiming vision Stage1 analyzer/data missing when common appendix settings specify 180×8 and GLM-5.2.
- Deep GraphRAG: gain combines 72B-teacher SFT and DW-GRPO; do not attribute all to DW-GRPO alone. k=3 bounds per-level retained candidates, not global constant cost. Latency causal attribution to visited-node count is not isolated experimentally.

## Semantics additional findings (13–18)

- DW2V: remove citation-lineage audit, asserted equivalence to DBE, later-literature status claims, wiki/social-science application program (§1.3, §7.3–7.4); preserve actual PPMI method, Table8 .4427 and 3 figures.
- DBE: remove external Garg/Kozlowski lineage, Korean-corpus/wiki program, unsupported world-history framing (§1.3, §7.3–7.5). Prior-driven iraq vectors with 64/76 absent slices are adequately grounded without historical extrapolation.
- ROME: content passes; add real full-paper URL/path to evidence (NeurIPS PDF hash 6f1d43d5a82a37e89b0665b33bf3a182).
- Structural Probe and Is Attention Interpretable: pass with full ACL PDF evidence.
- IC2: evidence needs actual full-paper source, not DOI metadata alone. Keep source-backed intervention-proxy caveat.

## Graphs additional findings (4–6)

- DeepWalk: online SGD/streaming terminology is not false advertising. State that reported experiments use offline-generated walks and §4.4.1's streaming variant is not experimentally evaluated. Remove wiki/reader-process material.
- GAT: citation datasets 100 runs versus PPI 10 runs, not all100. Attention sum versus average differs only by fixed-head-count scale; avoid a purported contradiction. Remove wiki/reader-process material.
- GIN: irrational epsilon is sufficient, not necessary. Do not claim float/rational epsilon invalidates implementation; theoretical existence does not guarantee training finds injectivity. Recast GIN-epsilon/GIN-0 result as optimization/generalization behavior. Retain justified validation-selection and noninjective mean-readout caveats. Remove wiki/reader-process material.

## Semantics final additions/corrections

- Tahmasebi 2021 correction supersedes earlier count: official publication §6.3 lists TEN evaluation recommendations, not eight. Include pretrained-model contamination/source and falsifiability/control conditions. Other eight: frequency-matched positive/negative sets; raw-text grounding; outside-world grounding; sparse evidence; change-type differentiation; change timing; scalability across time points; justified evaluation judgments.
- CIC: record actual arXiv v1 full PDF source for method/numbers; source_paths empty + abs/DOI is insufficient provenance. Replace author-process introduction with a concise bibliographic distinction if needed; original v1 versus later journal publication must not be conflated.
- PCM: record Nature full HTML/PDF and anchor Eq1–5/results .8681→.1871; current source_paths empty is not sufficient provenance.
- TimesFM: record PMLR das24c.pdf or arXiv full PDF; remove §6.4 fairness checklist and §8.4 deployment question table plus defensive “not a checklist” sentence. Retain substantive experimental limits in normal prose.

## Graphs additional findings (7–9)

- GraphSAGE: remove figure caption's agent-team regeneration process, reader question table and wiki-navigation prose. Inference embedding randomness requires the condition that random sampling is retained at inference. Core method/table/51% and 7.4% checks pass.
- GCN: do not attribute a formal oversmoothing finding to the original paper; it observes depth-related performance degradation in Appendix B. Remove agent-team design/critique caption process and reader tables.
- GNNExplainer: no globally smallest subgraph guarantee; use compact/budget-constrained. Prediction fidelity is optimized but unique/complete model faithfulness is not guaranteed. GAT attention is node/edge-specific; critique the ATT comparator's separately trained GAT instead. Remove §8 dated code/dependency/porting audit, publication-warning checklist, reader questions and duplicate alignment line. Preserve all seven images.

## RAG/agents additional findings (4–6)

- RAGU: HippoRAG2 retains both MuSiQue and 2Wiki advantage, not only MuSiQue. Table2(b): 2Wiki63.5 vs58.0; BioASQ72.4 vs72.9. Comparing absolute F1 gains across different tasks does not refute scaling ratios; narrow to two probes and one model family. ≤1pp Meno/Qwen point estimates do not establish zero effect; Qwen inference is not free. System comparison does not isolate entity integration or directly measure graph quality; 3B–14B AC differences ≤1.5pp are an observed bound only. Remove promotional/derisive reviewer voice and reader tables.
- GoA: graph is a real query-specific directed prompt/context execution structure, although not a learned GNN; do not call it mere vocabulary. Selection-only baseline is absent, so cannot allocate most gains to filtering versus message passing. Replace coin-toss dismissal of 54.78 vs54.71 with uncertainty about stable .07pp advantage. Remove reviewer rhetoric and fix incomplete Li et al. reference if source metadata available.
- CausalRAG: question generation is an unspecified LLM; do not assert GPT-4o-mini also generates questions. It is specified for retrieval-time/evaluation calls. Say sample size not explicitly reported, not impossible to infer. Preserve actual Fig6 disagreement (.842 at k5/s3 vs .824 at k5/s5). Remove §8.4 current GitHub/Liner audit.

## Graphs remaining findings (10–21)

- ETGNN: reconcile cited v1 with v2 (2026-07-14) actually supporting current numbers; primary Eq32 is ER-msg + ER-Emb. Verify figures/table against chosen version. Remove operational checklists.
- GQML: Table2 characterizes LINEAR equivariant maps; nonlinear encodings are constructed, not all characterized. Node-size-independent parameter counts apply to chosen 2-local generator/circuit family, not all Hom spaces (Table2 includes n-dependent dimensions). Remove exclusive “only way” and “free lunch/repackaging” rhetoric.
- LGC-ACF: actual Table4 reports cutoffs20 AND50, not a single K. NDCG5.31/4.06/14.9 are the means of improvements across those two cutoffs. Preserve grounded missing-side-info-baseline critique but bound architectural nesting claim. Full accepted manuscript accessible on ResearchGate; references same DOI.
- CoEvoT: delete guessed Vicuna7B checkpoint identity (not specified). Attribute single-run/deterministic reporting to paper instead of inferring actual repetition. Avoid checklist-Q7 label in public prose.
- LightGCN: same learnable parameter count as MF, not same computation. Exact SGC/APPNP equivalence needs specific layer weights; uniform layer aggregation still retains raw/self information.
- HGNN: hyperedges are built using pairwise kNN but resulting operator is node–hyperedge–node; don't reduce them to “just a dense graph.” No kNN-baseline/K-ablation isolates grouping benefit. W initialized identity and not described as trained, not proof of untrainability. .1 difference cannot be called within noise without SD.
- PIG-GNN: full publisher text unavailable; metadata/selected publisher text/original seven figures only. Preserve explicit source-limited status, do not call full-paper verified.
- neuroGravity: learned G and alpha also take population-containing features, so explicit PiPj factor does not make total prediction linear in population. Top8 features does not prove more than8. Low-SI source trend is not a necessary condition for transfer.
- PPE: remove source-retrieval/HTML/citation-count review log. Keep verified table/text discrepancies; figure1 box-count alone does not prove 3-vs4-stage inconsistency.
- IBA: remove dated repo audit and application checklist. Stage1 gain may become stale after Stage2 is speculation; retain only lack of post-Stage2 calibration/allocation reporting. Gamma values read from plot remain approximate.
- FRM: Table2 +FPF is not compute-matched isolation. Appendix A.2/Table3 adds StageB training (100k/200k/100k iterations, new optimizer/EMA) from selected StageA weights. Remove “carry only/direct attribution”; preserve architecture/path/objective hold-fixed with added-budget caveat. Remove repo/checklist sections and placeholder code reference.
- HetGNN: public coauthor full PDF recovered at sources/hetgnn.pdf. Personalized restart/top-type caps mean hub inclusion bias isn't established universally; frame as untested neighbor-degree sensitivity. Do not call small gaps within noise without repeated SD. Remove wiki/reader guide.

## RAG/agents remaining to item15

- HippoRAG: actual figures4, ledger0 is wrong. Change cost paragraph from writer process to AppendixG direct values (10–30x cost,6.7–13.3x time).
- LightRAG: question generator unspecified; GPT4o-mini specified for generation/judge only. Table9 question/answer mismatch is grounded but explain in body or drop summary-only warning.
- LeanRAG: pass.
- CausalRAG2: actual figures5, not4. Remove “user specified HugRAG / this review analyzes” process; concise rename/version fact only.
- MS GraphRAG: full authors Newman Cheng, Dasha Metropolitansky, Robert Osazuwa Ness. Actual figures4, not3. Remove repo-evolution audit §8.7 and reader checklist; replace “review notation” with plain reconstruction. Correct Lewis NeurIPS URL full hash6b493230205f780e1bc26945df7481e5.
- HippoRAG2: pass.
- KGP: figures5, not4; captions retain source/cropping facts but drop “for academic critique” review purpose.
- LinearRAG: figures4, not3; neutralize headings/reader guide. Scientific checks pass.
- SkillSmith: full authors Lucio M. Dery, Benedict Aaron Tjandra, Siavash Samiei, Adhiguna Kuncoro, Zohar Yahav, Jiajun Shen, Arthur Szlam. Figures4, not3. Zero-shot Composite-SNI ICL1942 beats SkillSmith1800; bound win claim to finetuned/selected transfer regimes. Input-ablation components described in §6.1; do not call composition wholly undefined.
