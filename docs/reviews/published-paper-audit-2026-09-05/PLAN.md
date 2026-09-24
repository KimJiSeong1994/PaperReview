# Published paper-review revision plan

User-authorized outcome: deeply check the other published paper reviews against their primary papers, correct the articles, preserve their original core figures, and publish the revisions using the established IPCCF workflow.

The publication snapshot contains 76 posts: 69 paper-review entries and 7 engineering entries. IPCCF is already completed. The initial scope is the remaining 63 individual-paper reviews; whether to include the five conference-trend articles has been asked separately. The snapshot fixes the scope so new posts arriving during the task do not silently extend it.

## Acceptance criteria

- Each article is read alongside the actual primary paper, including its main method/equations, experimental setup and numerical results, and limits of the conclusions.
- Preserve accurate explanations and article depth; correct substantive mistakes and unsupported inferences. Do not force factual changes when none are needed.
- Published text contains paper explanations only. Review criteria, agent process, code-audit reports, deployment notes, and checklists stay in separate evidence artifacts.
- Preserve the existing figure assets, their order, explanatory placement, and attribution. Preserve the URL, initial publication date, author, tags, category, and thumbnail.
- Every article has an evidence ledger and a concrete change record. Missing primary evidence is an explicit incomplete state, not a successful review.
- Following the author pass, perform separate skeptical and factual verification passes, then integrate accepted corrections.
- Synchronize PaperWiki; validate Markdown/math/figures/paper metadata; change only the authorized post records on the latest repository base.
- Respect protected-branch CI before merge. Apply the merged records atomically with backups, preserving concurrent unrelated posts. Verify exact live body, figures, and metadata.

## Work allocation

- `semantics_causality.json`: 21 papers covering lexical semantics, interpretability, social simulation, causal analysis, and time-series forecasting.
- `graphs_recommendation.json`: 21 papers covering graph learning, recommendation, quantum graph models, urban modelling, and reasoning.
- `rag_agents.json`: 21 papers covering retrieval, graph memory, skills, and agent systems.

Each author owns only its assigned `articles/<slug>/` directories. The leader owns integration, cross-review assignment, source mapping, validation, PaperWiki synchronization, publication, and completion evidence. No author publishes or changes the shared post database.

## Evidence and progress

`manifest.json` fixes the article list. `original.json` and `original.md` preserve each original article. `source-candidates.json` provides unverified search candidates only. Author outputs are `revised.md`, `evidence.md`, and `review.json`. Subsequent cross-review artifacts record accepted/rejected findings and final verification.

Stop only when every in-scope article is verified and published, or when a specific unrecoverable missing-evidence/authority condition prevents an identified article from proceeding. Report exact completed and unresolved counts; never label the whole corpus reviewed on the basis of automated text cleanup alone.

## User steering

The user instructed to proceed with the remaining articles while IC2 full-text access is blocked. Release scope is now 62 individual-paper articles. IC2 remains explicitly deferred and its production record must not be changed. PIG-GNN full text was recovered from the authors' official laboratory site and remains in scope. The five conference-trend posts were not added to the individual-paper scope.
