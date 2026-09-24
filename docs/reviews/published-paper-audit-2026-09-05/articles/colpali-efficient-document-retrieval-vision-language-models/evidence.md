# Evidence — ColPali

| Claim | Primary source anchor | Type | Confidence |
| --- | --- | --- |
| ColPali encodes document-page images with a vision-language model and uses late interaction for query-page scoring. | Faysse et al., arXiv:2407.01449v6, §§3–4 | method | high |
| ViDoRe evaluates visual document retrieval across several document domains and layouts. | §2 | benchmark | high |
| The OCR-free pipeline avoids explicit text extraction but has page-image storage and late-interaction costs. | §5 and efficiency discussion | scope limitation | high |

Method map: document page image → VLM patch embeddings; query → token embeddings; MaxSim late interaction → page ranking.

Primary HTML read: https://arxiv.org/html/2407.01449 (§§2–5 and tables).
