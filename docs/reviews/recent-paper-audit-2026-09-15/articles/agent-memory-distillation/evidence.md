# Evidence audit — Agent Memory Distillation

**Review date:** 2026-09-15 (Asia/Seoul)  
**Article mode:** deep academic paper review; revision/polish.  
**Primary version:** Kim, Kim, & Hwang, *Agent Memory Distillation: Empowering Small LLM Agents with Hierarchical Teacher Memory*, arXiv:2608.07169v1, submitted 2026-08-07, marked “Under review.” [arXiv record](https://arxiv.org/abs/2608.07169v1) · [versioned HTML](https://arxiv.org/html/2608.07169v1) · [PDF](https://arxiv.org/pdf/2608.07169v1).  
**Retrieval sufficiency:** sufficient for the article’s method, reported results, and bounded critique. No independent benchmark execution was performed. Official project and public code were checked only as supplemental artifacts; the paper is authoritative for reported results.

## Evidence ledger

| Claim | Source anchor | Evidence type | Confidence | Review boundary |
| --- | --- | --- | --- | --- |
| The paper is a 2026-08-07 v1 preprint by Taeil Kim, Kangsan Kim, and Sung Ju Hwang, under review. | [arXiv record](https://arxiv.org/abs/2608.07169v1) | paper metadata | high | Do not describe it as peer-reviewed or venue-published. |
| AMD leaves student parameters unchanged and transfers teacher experience through external memory. | [§§1, 3.1](https://arxiv.org/html/2608.07169v1#S1) | paper-reported | high | “Training-free” does not mean collection, embedding, context, or inference are free. |
| Successful teacher trajectories form WF, ST, and FN banks. WF gives task strategy; ST holds labeled executions and observations; FN gives function-level examples plus optional documentation. | [§3.2](https://arxiv.org/html/2608.07169v1#S3.SS2) | paper-reported | high | Final trajectory success does not establish that every intermediate call was error-free. |
| WF/ST are injected before execution; FN is looked up after a tool-call error. | [§3.3](https://arxiv.org/html/2608.07169v1#S3.SS3), [Algorithm 1](https://arxiv.org/html/2608.07169v1#A1) | paper-reported | high | FN is not a universal static prompt block. |
| The principal configuration uses `text-embedding-3-small`, a threshold, and k=1 at each retrieval locus. | [Appendix C](https://arxiv.org/html/2608.07169v1#A3) | paper-reported | high | k=1 means one WF, one ST per predicted label, and one FN per failing function—not one memory per task. |
| Table 1 reports four-student mean gains of +27.2pp/+11.2pp/+3.4pp on AppWorld/BFCL V3/ToolSandbox. | [Table 1, §4.2](https://arxiv.org/html/2608.07169v1#S4.T1) | paper-reported | high | Main memory construction and evaluation occur within each benchmark; call this within-benchmark evidence. |
| Cross-split uses a 7:3 construction/evaluation split; self-excluded retrieval forbids a task from accessing its own memory. Both Table 6 variants use Qwen3-4B only. | [Appendix B.3, Table 6](https://arxiv.org/html/2608.07169v1#A2.SS3) | paper-reported | high | This is transfer from other tasks in the same benchmark, not cross-benchmark or changed-API transfer. |
| The component ablation makes ST the large marginal contributor in several cells, but FN is not uniformly additive. | [Table 2](https://arxiv.org/html/2608.07169v1#S5.T2) | paper-reported | high | E.g., Llama3.1-8B AppWorld declines from 30.36 (WF+ST) to 27.38 (+FN). |
| “Text WF / code ST / code FN” reaches 49.40 versus all-text 26.19 in one AppWorld/Qwen3-4B representation ablation. | [§5.5, Table 4](https://arxiv.org/html/2608.07169v1#S5.SS5) | paper-reported | high | It is a narrow configuration; no token- or information-matched modality control is reported. |
| Teacher strength alone does not rank student outcome in the Qwen3-4B teacher ablation. | [Table 3](https://arxiv.org/html/2608.07169v1#S5.T3) | paper-reported | high | The paper suggests teacher–student compatibility; it does not identify a selection rule. |
| Interaction turns decrease in selected cases, but full end-to-end economic cost is not reported. | [§4.2, Fig. 3](https://arxiv.org/html/2608.07169v1#S4.SS2), [Appendix C](https://arxiv.org/html/2608.07169v1#A3) | direct inference from setup | high | Teacher runs, memory generation, embeddings, decomposition, prompt tokens, latency, and reuse rate are not fully costed. |
| The stated limitations are text-based fixed-tool environments, frozen offline memory, distribution shift, and teacher suitability. | [Limitations](https://arxiv.org/html/2608.07169v1#S6) | paper-reported | high | Keep these separate from reviewer inference about reproduction. |

## Method map

| Component / step | Role | Input → output | Assumption | Source anchor |
| --- | --- | --- | --- | --- |
| Teacher collection | Build source set | teacher task runs → successful trajectories | A final success provides useful evidence | [§3.1–3.2](https://arxiv.org/html/2608.07169v1#S3) |
| Workflow (WF) | Give global plan | task/query + trajectory → generalizable insight | Typed placeholders preserve reusable procedure | [§3.2](https://arxiv.org/html/2608.07169v1#S3.SS2) |
| Subtask (ST) | Give executable middle-scale examples | trajectory → labels, segments, calls/code, observations | A student can decompose a new instruction into aligned labels | [§3.2](https://arxiv.org/html/2608.07169v1#S3.SS2), [Appendix C](https://arxiv.org/html/2608.07169v1#A3) |
| Function (FN) | Repair observable call errors | successful call/example/(optional schema) → function index | Function names and error signals are available | [§§3.2–3.3](https://arxiv.org/html/2608.07169v1#S3) |
| Proactive retrieval | Set initial context | instruction + generated labels → WF/ST | Semantic similarity retrieves relevant other-task examples | [§3.3](https://arxiv.org/html/2608.07169v1#S3.SS3) |
| Reactive retrieval | Correct a failed call | tool error → function-name-filtered FN hint | Errors expose the function-level problem | [Algorithm 1](https://arxiv.org/html/2608.07169v1#A1) |

## Exact result table

| Result claim | Metric / dataset / setup | Exact value | Comparator | Source anchor | Caveat |
| --- | --- | ---: | --- | --- | --- |
| Qwen3-4B AMD, main | AppWorld success | 49.40 | zero-shot 14.88 | [Table 1](https://arxiv.org/html/2608.07169v1#S4.T1) | Main within-benchmark setup. |
| Qwen3-4B AMD, main | BFCL V3 accuracy | 38.50 | zero-shot 15.50 | [Table 1](https://arxiv.org/html/2608.07169v1#S4.T1) | Same qualifier. |
| Qwen3-4B AMD, main | ToolSandbox success | 20.16 | zero-shot 16.28 | [Table 1](https://arxiv.org/html/2608.07169v1#S4.T1) | Same qualifier. |
| Full AMD, cross-split | AppWorld / BFCL / ToolSandbox | 41.07 / 30.65 / 22.92 | zero-shot 16.07 / 16.13 / 16.67 | [Table 6](https://arxiv.org/html/2608.07169v1#A2.T6) | Qwen3-4B only, 7:3 bank/eval split. |
| Full AMD, self-excluded | AppWorld / BFCL / ToolSandbox | 46.43 / 31.00 / 23.26 | zero-shot 14.88 / 15.50 / 16.28 | [Table 6](https://arxiv.org/html/2608.07169v1#A2.T6) | Larger bank than cross-split; not a direct numerical decomposition. |
| Five-run AMD | AppWorld / BFCL / ToolSandbox | 49.60±0.91 / 38.67±0.58 / 20.16±0.78 | zero-shot 14.48±0.69 / 15.33±0.76 / 16.54±0.44 | [Table 5](https://arxiv.org/html/2608.07169v1#A2.T5) | Standard deviation; Qwen3-4B only. |
| Teacher ablation | Qwen3-4B AppWorld | GPT-5-mini: 49.40; DeepSeek V4 Pro: 38.10 | Teacher scores 50.00 vs. 81.55 | [Table 3](https://arxiv.org/html/2608.07169v1#S5.T3) | Supports non-monotonicity, not the cause. |

## Critique log

| Critique | Label | Action | Reason | Final-prose location |
| --- | --- | --- | --- | --- |
| Main evaluation is not strictly task-disjoint. | paper-evidenced | retained | Appendix B.3 adds dedicated disjoint protocols. | §§5.3, 6.2 |
| A smaller number of interaction turns proves AMD is cheaper. | direct inference from setup | softened | Total lifecycle costs are not reported. | §§6.4, 8.2 |
| Hierarchical components have independently identified causal effects. | direct inference from setup | softened | Ablations are informative but show exceptions and lack all matched controls. | §7 |
| AMD generalizes to open-ended coding or multimodal agents. | paper-evidenced limitation | retained as unresolved | Authors explicitly limit the evaluated setting. | §8.3 |
| Public code proves paper-cell reproducibility. | source-reference evidence / direct inference | softened | A pinned code snapshot exists, but its release artifacts do not establish table-to-config provenance. | §8.4 |
| Stronger teachers are intrinsically worse. | speculative | rejected | The ablation reports outcomes, not a causal mechanism. | §7.3 says “suggests compatibility.” |

## Supplemental source-reference evidence

- Official project page: [agent-memory-distillation.github.io](https://agent-memory-distillation.github.io/) presents the paper and implementation links; it is not used to establish experimental details beyond the paper.
- Pinned public source snapshot: `taeilkim2465/agentic_memory_distillation@2895d10c07105432325b088f4803dc94a10003c9:README.md:L66-L100` documents benchmark overlay setup. `toolsandbox/common/roles/memory_augmented_agent.py:L25-L34,L99-L132,L148-L182` shows static WF/ST and error-triggered FN paths. This is supplemental: it does not identify the data/configuration that produced a paper-table cell. The repository was active at the pinned 2026-08-10 commit; no independent release-based reproduction was performed.

## Checklist outcome

All major method and number claims in `revised.md` map to a primary anchor above. The article distinguishes paper-reported evidence from direct inference, preserves attributed CC BY 4.0 figure captions, contains references, and omits speculative critique.
