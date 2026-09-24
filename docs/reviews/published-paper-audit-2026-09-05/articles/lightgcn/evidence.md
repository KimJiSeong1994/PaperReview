# Evidence — LightGCN: Simplifying and Powering Graph Convolution Network for Recommendation

## Primary source read
- arXiv:2002.02126, official HTML: https://arxiv.org/html/2002.02126

## Method anchors
- §2.2 removes NGCF feature transforms, nonlinearities, or both under the same split/protocol; §3 introduces LightGCN as neighbor-only propagation plus layer combination.
- Table 1 gives the direct NGCF ablation, while Figure 1 traces loss and recall during training.

## Result checks
- Table 1: on Gowalla, NGCF-fn has recall 0.1742 and NDCG 0.1476 versus NGCF 0.1547 and 0.1307; on Amazon-Book it is 0.0399/0.0303 versus 0.0330/0.0254.
- The authors state a 9.57% relative recall improvement for the joint removal in their ablation discussion.

## Limits retained in article
- The direct ablation is on two datasets and a two-layer setting; broader performance claims rely on the later benchmark comparisons.
- The paper reports the effects within NGCF-style recommendation, not that feature transforms and nonlinearities are generally harmful in GNNs.

## Figure preservation
- lightgcn-fig1-ngcf-ablation.png and lightgcn-fig2-architecture.png remain in their existing order with captions.
