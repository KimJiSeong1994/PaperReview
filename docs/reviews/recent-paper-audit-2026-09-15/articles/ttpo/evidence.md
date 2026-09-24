# Evidence audit — TTPO

**Review date:** 2026-09-15 (Asia/Seoul)  
**Article mode:** deep academic paper review; revision/polish.  
**Primary version:** Wang et al., *TTPO: Test-Time Policy Optimization*, arXiv:2608.27448v1, submitted 2026-08-27. [arXiv record](https://arxiv.org/abs/2608.27448v1) · [versioned PDF](https://arxiv.org/pdf/2608.27448v1).  
**Retrieval sufficiency:** sufficient for the paper’s stated method, numerical tables, figure labels, and the article’s bounded critiques. The review recomputes displayed averages/differences only; it does not retrain a model or rerun a benchmark.

## Evidence ledger

| Claim | Source anchor | Evidence type | Confidence | Review boundary |
| --- | --- | --- | --- | --- |
| v1 was submitted 2026-08-27 and lists eleven authors, Zhejiang University and Alibaba Group. | [arXiv record](https://arxiv.org/abs/2608.27448v1) | paper metadata | high | It is a preprint. |
| TTPO samples K rollouts, clusters answers by mathematical equivalence, uses the largest cluster as pseudo-label, and partitions agreeing `P` from disagreeing `N`. | [§3.1](https://arxiv.org/pdf/2608.27448v1#page=3) | paper-reported | high | This is pseudo-label routing, not verified ground truth. |
| `P` receives answer-conditioned forward-KL distillation; `N` receives GRPO with token masking. | [§§3.3–3.4](https://arxiv.org/pdf/2608.27448v1#page=4) | paper-reported | high | The negative branch still has false penalties when a disagreeing rollout is correct. |
| The text describes teacher/student as prompt-prefix variants of `pi_theta`, but Appendix A fixes teacher base weights with LoRA disabled while updating student LoRA. | [§3.1](https://arxiv.org/pdf/2608.27448v1#page=3), [Appendix A](https://arxiv.org/pdf/2608.27448v1#page=12) | paper-evidenced internal mismatch | high | “Prompt-only difference” is accurate only before the student update; article labels this as a source inconsistency. |
| TTPO uses K=64, selects Ktrain=8 at fixed 50/50 positive/negative composition, samples up to 16,000 tokens, and backpropagates through the first 1,024 completion tokens. | [§4.1](https://arxiv.org/pdf/2608.27448v1#page=6), [Appendix A](https://arxiv.org/pdf/2608.27448v1#page=12) | paper-reported | high | Cost and learning signal are not token-length neutral. |
| Results are best saved-checkpoint values: TTPO/OPSD train 100 steps with 25-step saves; GRPO/TTRL train 500 steps. | [§4.1](https://arxiv.org/pdf/2608.27448v1#page=6) | paper-reported | high | In TTT, checkpoint choice is made on the same test problems used for learning. |
| Table 1 averages are 40.1/58.6/62.6 for TTPO and 39.7/58.4/61.7 for label-supervised OPSD, at 1.7B/4B/8B. | [Table 1](https://arxiv.org/pdf/2608.27448v1#page=6) | paper-reported / recomputed | high | Cellwise TTPO vs. OPSD is 10 wins, 3 losses, 2 ties; all losses are HMMT25. |
| Table 2 TTT averages are 38.0→45.2, 57.4→61.1, and 60.7→65.3. | [Table 2](https://arxiv.org/pdf/2608.27448v1#page=7) | paper-reported / recomputed | high | Of nine metric cells, TTPO leads both baselines in eight and ties OPSD-TTT at 4B BRUMO25 (66.9). |
| The prose says the 1.7B gain over TTRL is +5.4, while Table 2 gives 45.2−40.2=+5.0. | [§4.2 and Table 2](https://arxiv.org/pdf/2608.27448v1#page=7) | paper-evidenced arithmetic discrepancy | high | Article flags the source error rather than reproducing it. |
| Figure 3 supports the 1.7B/AIME26 TTT decomposition 37.8→45.7→46.7→48.9: +7.9 without privileged answer, +1.0 for pseudo-label condition, +2.2 for negative GRPO. | [Fig. 3](https://arxiv.org/pdf/2608.27448v1#page=8) | figure evidence / direct computation | high | It is one configuration, not a universal causal allocation. |
| Figure 1(a) labels 13/87 and 21/79 but its common-axis line plot is ambiguous against the text’s conditional “79% of negatives” wording; 85% is not shown in that figure. | [Fig. 1; §3.2](https://arxiv.org/pdf/2608.27448v1#page=1) | paper-evidenced internal mismatch | high | The article preserves both readings (21% versus ~9% false penalty) as unresolved. |
| Paper tables give no benchmark counts, seed repetitions, dispersion, confidence intervals, or significance tests; plotted uncertainty bands are undefined. | full v1 review | source-absence audit | medium-high | Absence in v1 cannot show that such results do not exist elsewhere. |

## Method map

| Component / step | Role | Input → output | Assumption | Source anchor |
| --- | --- | --- | --- | --- |
| Majority routing | Produce a pseudo-label | K completion answers → largest equivalence cluster → P/N | Majority correlates with the right answer often enough | [§3.1](https://arxiv.org/pdf/2608.27448v1#page=3) |
| Positive OPSD | Transfer dense teacher distribution | agreeing trajectory + answer-conditioned teacher → forward KL | Agreeing answer prevents arbitrary-target corruption | [§3.3](https://arxiv.org/pdf/2608.27448v1#page=4) |
| Token weighting | Focus positive gradient | normalized entropy/divergence → Soft-OR weight | Those signals identify unconverged positions | [Eq. 4](https://arxiv.org/pdf/2608.27448v1#page=4) |
| Negative GRPO | Penalize minority rollouts | disagreement reward → negative group advantage | Most disagreements are wrong | [§3.4](https://arxiv.org/pdf/2608.27448v1#page=5) |
| Token masking | Reduce local false penalty | `-log p*(1-H)` → top 50% positions | High-confidence low-probability positions identify errors | [Eqs. 6–7](https://arxiv.org/pdf/2608.27448v1#page=5) |

## Exact result table

| Result claim | Metric / dataset / setup | Exact value | Comparator | Source anchor | Caveat |
| --- | --- | ---: | --- | --- | --- |
| Label-data setting | TTPO average, 1.7B / 4B / 8B | 40.1 / 58.6 / 62.6 | OPSD† 39.7 / 58.4 / 61.7 | [Table 1](https://arxiv.org/pdf/2608.27448v1#page=6) | Five benchmarks; no dispersion accompanies the table. |
| TTT setting | TTPO average, 1.7B / 4B / 8B | 45.2 / 61.1 / 65.3 | base 38.0 / 57.4 / 60.7 | [Table 2](https://arxiv.org/pdf/2608.27448v1#page=7) | Learns on and selects checkpoints using test problems. |
| 1.7B TTT arithmetic | TTPO vs. OPSD-TTT / TTRL | +3.3 / +5.0 | 45.2−41.9 / 45.2−40.2 | [Table 2](https://arxiv.org/pdf/2608.27448v1#page=7) | Paper prose prints +5.4 for the latter. |
| Direct target distribution | Non-thinking evaluation gain, 1.7B / 4B / 8B | +25.2 / +30.6 / +36.4 | OPSD† +7.1 / +5.8 / +3.5 | [Table 7](https://arxiv.org/pdf/2608.27448v1#page=15) | TTT table does not supply paired non-thinking scores. |
| Cross-task study | 1.7B trained on one / tested on others | 6 held-out pairs exceed base | example: HMMT26 28.8→32.3 | [Fig. 4](https://arxiv.org/pdf/2608.27448v1#page=8) | 1.7B only. |
| Checkpoint curve | AIME26 TTT | TTPO 48.9 at 75; 47.8 at 100 | OPSD Leakage 47.5 at 100 | [Fig. 5](https://arxiv.org/pdf/2608.27448v1#page=9) | Peak-to-peak and same-step gaps answer different questions. |

## Critique log

| Critique | Label | Action | Reason | Final-prose location |
| --- | --- | --- | --- | --- |
| The negative penalty is always correct. | paper-evidenced / source discrepancy | softened | Paper admits false penalties; Figure 1 leaves their rate internally inconsistent. | §§2.1–2.2 |
| The teacher and student only differ in prompts during all training. | paper-evidenced internal mismatch | corrected | Appendix A fixes base teacher and updates student LoRA. | §3.1 |
| TTPO exceeds OPSD in every labeled-setting cell. | paper-evidenced | corrected | Table 1 has 3 losses and 2 ties. | §5 |
| TTPO beats both TTT baselines in every cell. | paper-evidenced | corrected | 4B BRUMO25 ties OPSD-TTT. | §6 |
| The reported small margins establish superiority. | direct inference from setup | softened | Counts/dispersion/CI/seeds are unreported in v1. | §§5, 9.2 |
| “Better than ground truth” demonstrates better supervision. | direct inference from setup | softened | Ground-truth routing starves the two branches; no non-starving variant is tested. | §8.1 |
| The method is broadly validated beyond verifiable math. | paper-stated limitation | rejected | Appendix F limits domain scope. | §9.1 |

## Supplemental source-reference evidence

- [Official repository](https://github.com/ZJU-REAL/TTPO) is linked from the current arXiv record. A 2026-09-14 artifact audit found training, voting, trainer, and think/non-think evaluation material; only TTPO launch scripts were split by 1B/4B/8B scale. The repository has no license file in that audit. This describes availability, not a reproduction of paper cells.

## Checklist outcome

All changes preserve the original figure URLs and attributions. Major claims and every stated number in `revised.md` are mapped to the v1 paper or labeled reviewer computation; the article retains a References section and confines unverified concerns to explicit uncertainty language.
