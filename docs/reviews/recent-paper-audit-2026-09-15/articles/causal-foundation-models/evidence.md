# Causal Foundation Models — evidence ledger and revision audit

**Review date:** 2026-09-15 (Asia/Seoul). **Primary scope:** arXiv:2609.03003v1, submitted 2026-09-02; the paper remains a v1 preprint. Companion-code observations are limited to `layer6ai-labs/cfms@549bcb72ac7ab5820843b889866913afe56c08dd` (2026-09-04 UTC).

## Evidence ledger

| Claim | Source anchor | Evidence type | Confidence | Notes |
| --- | --- | --- | --- | --- |
| CFM estimates causal quantities on new data through in-context learning without model updates. | [arXiv abstract](https://arxiv.org/abs/2609.03003v1), [§1](https://arxiv.org/html/2609.03003v1#S1) | paper-reported | high | Does not mean zero preprocessing or zero execution cost. |
| CEPO, CATE and ATE have different estimands. | [Eqs. 2–6](https://arxiv.org/html/2609.03003v1#S2.E2) | paper-reported | high | CATE is a conditional mean, not observed individual counterfactuals. |
| Do-PFN/CausalPFN/CausalFM predict CID-PPD/CEPO-PPD/CDTE-PPD with different prior assumptions. | [Table 1](https://arxiv.org/html/2609.03003v1#S3.T1), [Eqs. 22–24](https://arxiv.org/html/2609.03003v1#S2.SS5) | paper-reported | high | Do not collapse “CFM” into CausalFM. |
| Point-estimation consistency result is conditional on positivity and prior-support identification. | [§3.1.1](https://arxiv.org/html/2609.03003v1#S3.SS1.SSS1) | paper-reported | high | It is not a finite-checkpoint/off-prior/calibration guarantee. |
| RealCause-Lalonde uses CPS 16,177 and PSID 2,675 with 10 realizations each. | [§4.1](https://arxiv.org/html/2609.03003v1#S4.SS1) | paper-reported | high | Outcomes are generated to satisfy conditional ignorability. |
| CATE uses 90/10 split; ATE is separately fit on full data. | `layer6ai-labs/cfms@549bcb72:scripts/run_benchmark.py:L261-L269`, `:L286-L354` | source-reference | high | ATE is not an aggregation of held-out CATE predictions. |
| CausalPFN wrapper standardizes data and limits context/neighbors. | `layer6ai-labs/cfms@549bcb72:causal_bench/wrap_causalpfn.py:L90-L180` | source-reference | high | Companion benchmark wrapper, not a universal CFM property. |
| Hidden-confounding robustness is not directly measured. | §4.1 construction above | direct inference from setup | high | The semi-synthetic DGP guarantees conditional ignorability. |
| CATE identification does not by itself identify a full CDTE coupling. | [CDTE definition](https://arxiv.org/html/2609.03003v1#S2.SS5) | direct inference from setup | medium | The article’s two-world example is explanatory, not a paper experiment. |
| New query walkthrough: context loading, two CEPO queries, and posterior-mean subtraction explain the CausalPFN CATE path. | [Figure 1](https://arxiv.org/html/2609.03003v1#S1.F1), [§§3.1–3.2](https://arxiv.org/html/2609.03003v1#S3) | paper-reported synthesis | high | Added to make the API-level method sequence concrete without claiming automatic covariate selection. |

## Method map

| Component | Role | Input → output | Assumption | Source |
| --- | --- | --- | --- | --- |
| SCM prior | Generates synthetic causal worlds | prior → observational context and interventional labels | actual task resembles relevant prior support | [§3.2](https://arxiv.org/html/2609.03003v1#S3.SS2) |
| Causal prior-data loss | Amortizes Bayesian prediction | $(X,T,Y)$ context + query → target distribution | target and prior are specified correctly | [§3.1.1](https://arxiv.org/html/2609.03003v1#S3.SS1.SSS1) |
| Frozen CFM | Applies learned mapping | new context/query → CEPO/CATE-related output | no per-task weights update; context path remains | [Figure 1](https://arxiv.org/html/2609.03003v1#S1.F1) |
| RealCause benchmark | Measures point-effect error and task-stage time | 20 cohort-realization tasks → PEHE/ATE/runtime | conditional ignorability by construction | [§4](https://arxiv.org/html/2609.03003v1#S4) |

## Exact result table

Paper Table 3 values; PEHE is displayed in the paper’s $\times10^3$ scale. Lower is better.

| Method | CPS PEHE | PSID PEHE | CATE avg rank | CPS ATE rel. error | PSID ATE rel. error | ATE avg rank | CPU median CATE runtime (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CausalPFN | 8.97 ± 0.06 | 14.00 ± 0.41 | 1.75 ± 0.16 | 0.17 ± 0.03 | 0.24 ± 0.04 | 2.65 ± 0.26 | 18.4 |
| Do-PFN | 11.96 ± 0.09 | 20.20 ± 0.39 | 4.80 ± 0.21 | 0.88 ± 0.01 | 0.89 ± 0.01 | 6.50 ± 0.30 | 115.1 |
| CausalFM | 12.34 ± 0.02 | 22.27 ± 0.43 | 6.60 ± 0.22 | 0.94 ± 0.00 | 0.95 ± 0.00 | 7.80 ± 0.26 | 31.2 |
| T-Learner | 9.04 ± 0.08 | 13.65 ± 0.47 | 1.40 ± 0.11 | 0.28 ± 0.04 | 0.04 ± 0.01 | 2.25 ± 0.27 | 1803.0 |
| IPW | — | — | — | 0.15 ± 0.03 | 0.08 ± 0.02 | 2.05 ± 0.20 | — |

Source: [Table 3](https://arxiv.org/html/2609.03003v1#S4.T3). The time column includes task-specific tuning/training/inference for classical estimators and excludes CFM pretraining; it is neither pure forward latency nor comparable total research cost.

## Critique log

| Critique | Label | Action | Reason | Final prose location |
| --- | --- | --- | --- | --- |
| “No fine-tuning” could be read as no data preparation/selection. | paper-evidenced + source-reference | retained and qualified | wrapper/context path establishes remaining operations | §4.4, §7.4 |
| CausalPFN’s speed could be read as full lifecycle superiority. | paper-evidenced | retained and qualified | pretraining excluded; classical HPO included | §6.5 |
| CATE result could be read as universal CFM superiority. | paper-evidenced | softened | T-Learner has better pooled CATE rank; benchmark is narrow | §6.3, conclusion |
| Posterior output could be read as calibrated uncertainty. | direct inference from setup | retained as boundary | benchmark does not establish interval calibration | §7.3 |
| Extracted paper figures have cleared reuse rights. | source-reference | omitted from public prose; flagged | arXiv’s non-exclusive distribution licence is not a reuse clearance | uncertainty below |

## Uncertainties

- The direct-extracted CFM figure files retain attribution and source links, but the reviewed evidence does not establish a public reuse licence for them; this is a publication-rights check, not a technical-result correction.
- No newer arXiv version was present on 2026-09-15; claims are v1-specific.
