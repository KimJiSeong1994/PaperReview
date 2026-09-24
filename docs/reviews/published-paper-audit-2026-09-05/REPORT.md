# 게시 논문 리뷰 수정 기록

발행 대상: 개별 논문 리뷰 62편. IC2는 사용자 요청에 따라 보류했다.

원문 대조, 독립 비판 검토, 수정 후 사실 검증을 거쳐 필요한 내용을 수정했다. 기존 핵심 그림 196개와 URL·최초 발행일·태그·카테고리는 유지했다. 검토·발행 과정 기록은 이 폴더에만 두고 공개 본문에는 넣지 않았다.

PR: https://github.com/KimJiSeong1994/PaperReview/pull/263

현재 상태: 62편 발행 및 실제 URL 검증 완료. 본문·그림·논문 메타데이터·PaperWiki 동기화가 일치한다. 상세 증거는 publication-receipt.json 참조.

## 주요 교정

- SkillOpt: 학습·선택·테스트 분리와 실제 52개 평가 조건.
- SEED: 최고 또는 동률인 집계 비교 10/12 → 9/12.
- SDNE·GIN: 제곱오차의 β² 가중과 충분조건/필요조건 구분.
- HistWords·Kulkarni: 집계 단위와 표준편차에 관한 잘못된 비판 삭제.
- FRM: FPF 성능 비교에 추가 Stage B 학습 예산이 포함됨을 명시.
- PIG-GNN: GATv2 구조·Zipf 순위 관계·KL 식의 내부 불일치, 추가 도시 실험·평가 설정 보강.
- 논문 제목·저자·판본·표/그림 앵커 및 과도한 성과 일반화 교정.

## 검증

- 원래 그림 196개 URL·순서 보존; 공개 이미지 응답 및 파일 확인.
- 62개 게시 스키마·논문 메타데이터·서버 본문 렌더링 검증.
- KaTeX 수식 검사 및 블로그/SEO 테스트 56개 통과.
- PaperWiki 기존 원고 61개를 백업 후 동기화하고 ETGNN 원고 1개 생성. 기존 YAML 메타데이터 22개 보존·검증.
- 논문 모델을 직접 재학습한 결과는 아님.

## 포스팅별 기록

| 포스팅 | 수정·검증 기록 |
| --- | --- |
| [A Systematic Comparison of Contextualized Word Embeddings for Lexical Semantic Change](https://jiphyeonjeon.kr/blog/a-systematic-comparison-contextualized-word-embeddings-lexical-semantic-change) | [근거·수정 기록](articles/a-systematic-comparison-contextualized-word-embeddings-lexical-semantic-change/evidence.md) |
| [Survey of Computational Approaches to Lexical Semantic Change Detection](https://jiphyeonjeon.kr/blog/survey-computational-approaches-lexical-semantic-change-review-2026) | [근거·수정 기록](articles/survey-computational-approaches-lexical-semantic-change-review-2026/evidence.md) |
| [Analysing Lexical Semantic Change with Contextualised Word Representations](https://jiphyeonjeon.kr/blog/analysing-lexical-semantic-change-contextualised-word-representations-review-2026) | [근거·수정 기록](articles/analysing-lexical-semantic-change-contextualised-word-representations-review-2026/evidence.md) |
| [Lexical Semantic Change through Large Language Models: a Survey](https://jiphyeonjeon.kr/blog/contextualised-semantic-shift-detection-survey-review-2026) | [근거·수정 기록](articles/contextualised-semantic-shift-detection-survey-review-2026/evidence.md) |
| [Statistically Significant Detection of Linguistic Change](https://jiphyeonjeon.kr/blog/statistically-significant-detection-linguistic-change-review-2026) | [근거·수정 기록](articles/statistically-significant-detection-linguistic-change-review-2026/evidence.md) |
| [Dynamic Word Embeddings](https://jiphyeonjeon.kr/blog/dynamic-word-embeddings-dsg-review-2026) | [근거·수정 기록](articles/dynamic-word-embeddings-dsg-review-2026/evidence.md) |
| [How Contextual are Contextualized Word Representations? Comparing the Geometry of BERT, ELMo, and GPT-2 Embeddings](https://jiphyeonjeon.kr/blog/how-contextual-are-contextualized-word-representations-review-2026) | [근거·수정 기록](articles/how-contextual-are-contextualized-word-representations-review-2026/evidence.md) |
| [Training Temporal Word Embeddings with a Compass](https://jiphyeonjeon.kr/blog/training-temporal-word-embeddings-compass-twec-review-2026) | [근거·수정 기록](articles/training-temporal-word-embeddings-compass-twec-review-2026/evidence.md) |
| [Diachronic Word Embeddings Reveal Statistical Laws of Semantic Change](https://jiphyeonjeon.kr/blog/diachronic-word-embeddings-statistical-laws-semantic-change-review-2026) | [근거·수정 기록](articles/diachronic-word-embeddings-statistical-laws-semantic-change-review-2026/evidence.md) |
| [Dynamic Contextualized Word Embeddings](https://jiphyeonjeon.kr/blog/dynamic-contextualized-word-embeddings-dcwe-review-2026) | [근거·수정 기록](articles/dynamic-contextualized-word-embeddings-dcwe-review-2026/evidence.md) |
| [Structural Deep Network Embedding](https://jiphyeonjeon.kr/blog/structural-deep-network-embedding-sdne-review-2026) | [근거·수정 기록](articles/structural-deep-network-embedding-sdne-review-2026/evidence.md) |
| [Can Classic GNNs Be Strong Baselines for Graph-level Tasks? Simple Architectures Meet Excellence](https://jiphyeonjeon.kr/blog/classic-gnns-strong-baselines-graph-level-tasks-gnnplus-review-2026) | [근거·수정 기록](articles/classic-gnns-strong-baselines-graph-level-tasks-gnnplus-review-2026/evidence.md) |
| [Position: LLM-Based Social Simulations Require a Boundary](https://jiphyeonjeon.kr/blog/llm-based-social-simulations-require-boundary-review-2026) | [근거·수정 기록](articles/llm-based-social-simulations-require-boundary-review-2026/evidence.md) |
| [Population-Aligned Persona Generation for LLM-based Social Simulation](https://jiphyeonjeon.kr/blog/population-aligned-persona-generation-llm-social-simulation-review-2026) | [근거·수정 기록](articles/population-aligned-persona-generation-llm-social-simulation-review-2026/evidence.md) |
| [Dynamic Word Embeddings for Evolving Semantic Discovery](https://jiphyeonjeon.kr/blog/dynamic-word-embeddings-evolving-semantic-discovery-review-2026) | [근거·수정 기록](articles/dynamic-word-embeddings-evolving-semantic-discovery-review-2026/evidence.md) |
| [Dynamic Embeddings for Language Evolution](https://jiphyeonjeon.kr/blog/dynamic-bernoulli-embeddings-language-evolution-review-2026) | [근거·수정 기록](articles/dynamic-bernoulli-embeddings-language-evolution-review-2026/evidence.md) |
| [Heterogeneous Graph Attention Network](https://jiphyeonjeon.kr/blog/heterogeneous-graph-attention-network-han-review-2026) | [근거·수정 기록](articles/heterogeneous-graph-attention-network-han-review-2026/evidence.md) |
| [Heterogeneous Graph Neural Network](https://jiphyeonjeon.kr/blog/heterogeneous-graph-neural-network-hetgnn-review-2026) | [근거·수정 기록](articles/heterogeneous-graph-neural-network-hetgnn-review-2026/evidence.md) |
| [DeepWalk: Online Learning of Social Representations](https://jiphyeonjeon.kr/blog/deepwalk-online-learning-social-representations-review-2026) | [근거·수정 기록](articles/deepwalk-online-learning-social-representations-review-2026/evidence.md) |
| [Graph Attention Networks](https://jiphyeonjeon.kr/blog/graph-attention-networks-gat-review-2026) | [근거·수정 기록](articles/graph-attention-networks-gat-review-2026/evidence.md) |
| [How Powerful are Graph Neural Networks?](https://jiphyeonjeon.kr/blog/how-powerful-are-graph-neural-networks-gin-review-2026) | [근거·수정 기록](articles/how-powerful-are-graph-neural-networks-gin-review-2026/evidence.md) |
| [Inductive Representation Learning on Large Graphs](https://jiphyeonjeon.kr/blog/graphsage-inductive-representation-learning-large-graphs-review-2026) | [근거·수정 기록](articles/graphsage-inductive-representation-learning-large-graphs-review-2026/evidence.md) |
| [Semi-Supervised Classification with Graph Convolutional Networks](https://jiphyeonjeon.kr/blog/semi-supervised-classification-graph-convolutional-networks-review-2026) | [근거·수정 기록](articles/semi-supervised-classification-graph-convolutional-networks-review-2026/evidence.md) |
| [GNNExplainer: Generating Explanations for Graph Neural Networks](https://jiphyeonjeon.kr/blog/gnnexplainer-gnn-subgraph-feature-mask-review-2026) | [근거·수정 기록](articles/gnnexplainer-gnn-subgraph-feature-mask-review-2026/evidence.md) |
| [Explaining Temporal Graph Neural Networks via Feature-induced Information Flow](https://jiphyeonjeon.kr/blog/explaining-temporal-graph-neural-networks-feature-induced-information-flow-review-2026) | [근거·수정 기록](articles/explaining-temporal-graph-neural-networks-feature-induced-information-flow-review-2026/evidence.md) |
| [SkillOpt: Executive Strategy for Self-Evolving Agent Skills](https://jiphyeonjeon.kr/blog/skillopt-executive-strategy-self-evolving-agent-skills-deep-review-2026) | [근거·수정 기록](articles/skillopt-executive-strategy-self-evolving-agent-skills-deep-review-2026/evidence.md) |
| [SEED: Self-Evolving On-Policy Distillation for Agentic Reinforcement Learning](https://jiphyeonjeon.kr/blog/seed-self-evolving-opd-agentic-rl) | [근거·수정 기록](articles/seed-self-evolving-opd-agentic-rl/evidence.md) |
| [Locating and Editing Factual Associations in GPT](https://jiphyeonjeon.kr/blog/rome-causal-tracing) | [근거·수정 기록](articles/rome-causal-tracing/evidence.md) |
| [A Structural Probe for Finding Syntax in Word Representations](https://jiphyeonjeon.kr/blog/structural-probe) | [근거·수정 기록](articles/structural-probe/evidence.md) |
| [Quantum Machine Learning Models for Graphs](https://jiphyeonjeon.kr/blog/gqml-graphs) | [근거·수정 기록](articles/gqml-graphs/evidence.md) |
| [Is Attention Interpretable?](https://jiphyeonjeon.kr/blog/is-attention-interpretable) | [근거·수정 기록](articles/is-attention-interpretable/evidence.md) |
| [Light Graph Convolutional Collaborative Filtering With Multi-Aspect Information](https://jiphyeonjeon.kr/blog/lgc-acf) | [근거·수정 기록](articles/lgc-acf/evidence.md) |
| [CoEvoT: Co-Evolving Chain-of-Thought Prompting for Graph–LLM Reasoning](https://jiphyeonjeon.kr/blog/coevot) | [근거·수정 기록](articles/coevot/evidence.md) |
| [Deep GraphRAG: A Balanced Approach to Hierarchical Retrieval and Adaptive Integration](https://jiphyeonjeon.kr/blog/deep-graphrag) | [근거·수정 기록](articles/deep-graphrag/evidence.md) |
| [LightGCN: Simplifying and Powering Graph Convolution Network for Recommendation](https://jiphyeonjeon.kr/blog/lightgcn) | [근거·수정 기록](articles/lightgcn/evidence.md) |
| [RAGU: A Multi-Step GraphRAG Engine with a Compact Domain-Adapted LLM](https://jiphyeonjeon.kr/blog/ragu) | [근거·수정 기록](articles/ragu/evidence.md) |
| [Graph-of-Agents: A Graph-based Framework for Multi-Agent LLM Collaboration](https://jiphyeonjeon.kr/blog/goa) | [근거·수정 기록](articles/goa/evidence.md) |
| [Hypergraph Neural Networks](https://jiphyeonjeon.kr/blog/hgnn) | [근거·수정 기록](articles/hgnn/evidence.md) |
| [CausalRAG: Integrating Causal Graphs into Retrieval-Augmented Generation](https://jiphyeonjeon.kr/blog/causalrag-causal-graph-retrieval) | [근거·수정 기록](articles/causalrag-causal-graph-retrieval/evidence.md) |
| [HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models](https://jiphyeonjeon.kr/blog/hipporag-neurobiologically-inspired-long-term-memory) | [근거·수정 기록](articles/hipporag-neurobiologically-inspired-long-term-memory/evidence.md) |
| [LightRAG: Simple and Fast Retrieval-Augmented Generation](https://jiphyeonjeon.kr/blog/lightrag-dual-level-graph-rag) | [근거·수정 기록](articles/lightrag-dual-level-graph-rag/evidence.md) |
| [LeanRAG: Knowledge-Graph-Based Generation with Semantic Aggregation and Hierarchical Retrieval](https://jiphyeonjeon.kr/blog/leanrag-semantic-aggregation-hierarchical-retrieval) | [근거·수정 기록](articles/leanrag-semantic-aggregation-hierarchical-retrieval/evidence.md) |
| [CausalRAG2: Hierarchical Causal Knowledge Graph Design for RAG](https://jiphyeonjeon.kr/blog/causalrag2-hugrag-hierarchical-causal-gating) | [근거·수정 기록](articles/causalrag2-hugrag-hierarchical-causal-gating/evidence.md) |
| [From Local to Global: A Graph RAG Approach to Query-Focused Summarization](https://jiphyeonjeon.kr/blog/ms-graphrag-global-query-focused-summarization) | [근거·수정 기록](articles/ms-graphrag-global-query-focused-summarization/evidence.md) |
| [From RAG to Memory: Non-Parametric Continual Learning for Large Language Models](https://jiphyeonjeon.kr/blog/hipporag2-from-rag-to-memory) | [근거·수정 기록](articles/hipporag2-from-rag-to-memory/evidence.md) |
| [Knowledge Graph Prompting for Multi-Document Question Answering](https://jiphyeonjeon.kr/blog/knowledge-graph-prompting-multi-document-qa) | [근거·수정 기록](articles/knowledge-graph-prompting-multi-document-qa/evidence.md) |
| [Theory-informed and interpretable graph learning for urban commuting flows](https://jiphyeonjeon.kr/blog/theory-informed-interpretable-graph-learning-urban-commuting-flows) | [근거·수정 기록](articles/theory-informed-interpretable-graph-learning-urban-commuting-flows/evidence.md) |
| [Transferable human mobility network reconstruction with neuroGravity](https://jiphyeonjeon.kr/blog/transferable-human-mobility-network-reconstruction-with-neurogravity) | [근거·수정 기록](articles/transferable-human-mobility-network-reconstruction-with-neurogravity/evidence.md) |
| [LinearRAG: Linear Graph Retrieval Augmented Generation on Large-scale Corpora](https://jiphyeonjeon.kr/blog/linearrag-linear-graph-retrieval-augmented-generation) | [근거·수정 기록](articles/linearrag-linear-graph-retrieval-augmented-generation/evidence.md) |
| [SkillSmith: Learning to Compose Parametric Skills and Textual Knowledge](https://jiphyeonjeon.kr/blog/skillsmith-learning-to-compose-parametric-skills-textual-knowledge) | [근거·수정 기록](articles/skillsmith-learning-to-compose-parametric-skills-textual-knowledge/evidence.md) |
| [Dynamical Causality Under Invisible Confounders](https://jiphyeonjeon.kr/blog/cic-dynamical-causality-under-invisible-confounders) | [근거·수정 기록](articles/cic-dynamical-causality-under-invisible-confounders/evidence.md) |
| [Partial Cross Mapping Eliminates Indirect Causal Influences](https://jiphyeonjeon.kr/blog/pcm-partial-cross-mapping-eliminates-indirect-causal-influences) | [근거·수정 기록](articles/pcm-partial-cross-mapping-eliminates-indirect-causal-influences/evidence.md) |
| [LoongReflect: Boosting Long-Horizon Reflection in Search Agents via Global Perspective Distillation](https://jiphyeonjeon.kr/blog/loongreflect-long-horizon-reflection-search-agents) | [근거·수정 기록](articles/loongreflect-long-horizon-reflection-search-agents/evidence.md) |
| [From Agent Loops to Structured Graphs: A Scheduler-Theoretic Framework for LLM Agent Execution](https://jiphyeonjeon.kr/blog/from-agent-loops-to-structured-graphs-scheduler-theoretic-framework) | [근거·수정 기록](articles/from-agent-loops-to-structured-graphs-scheduler-theoretic-framework/evidence.md) |
| [Planetary Prediction Engine: Autonomous Geospatial Prediction via Intelligent Data Selection and Foundation Model Embeddings](https://jiphyeonjeon.kr/blog/planetary-prediction-engine-autonomous-geospatial-prediction) | [근거·수정 기록](articles/planetary-prediction-engine-autonomous-geospatial-prediction/evidence.md) |
| [Memory is Reconstructed, Not Retrieved: Graph Memory for LLM Agents](https://jiphyeonjeon.kr/blog/memory-is-reconstructed-not-retrieved-graph-memory-llm-agents) | [근거·수정 기록](articles/memory-is-reconstructed-not-retrieved-graph-memory-llm-agents/evidence.md) |
| [ColPali: Efficient Document Retrieval with Vision Language Models](https://jiphyeonjeon.kr/blog/colpali-efficient-document-retrieval-vision-language-models) | [근거·수정 기록](articles/colpali-efficient-document-retrieval-vision-language-models/evidence.md) |
| [WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution](https://jiphyeonjeon.kr/blog/wikiskill-compiling-agent-experience-persistent-knowledge-skill-evolution) | [근거·수정 기록](articles/wikiskill-compiling-agent-experience-persistent-knowledge-skill-evolution/evidence.md) |
| [Accelerating Scientific Research with Gemini in the Real-World](https://jiphyeonjeon.kr/blog/co-scientist-accelerating-scientific-research-gemini-real-world) | [근거·수정 기록](articles/co-scientist-accelerating-scientific-research-gemini-real-world/evidence.md) |
| [A Decoder-Only Foundation Model for Time-Series Forecasting](https://jiphyeonjeon.kr/blog/timesfm-decoder-only-foundation-model-time-series-forecasting) | [근거·수정 기록](articles/timesfm-decoder-only-foundation-model-time-series-forecasting/evidence.md) |
| [Where Reasoning Matters: Rethinking Latent Reasoning in Semantic ID-based Generative Recommendation](https://jiphyeonjeon.kr/blog/where-reasoning-matters-latent-reasoning-semantic-id-generative-recommendation) | [근거·수정 기록](articles/where-reasoning-matters-latent-reasoning-semantic-id-generative-recommendation/evidence.md) |
| [Flow Reasoning Models: Turning Flows Into Efficient Recurrent Reasoners](https://jiphyeonjeon.kr/blog/flow-reasoning-models-turning-flows-into-efficient-recurrent-reasoners) | [근거·수정 기록](articles/flow-reasoning-models-turning-flows-into-efficient-recurrent-reasoners/evidence.md) |
