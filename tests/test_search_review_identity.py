"""Search identity must survive a deep-review handoff with colliding storage IDs."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock


def test_deep_review_uses_exact_selected_record_not_ambiguous_storage_id(monkeypatch, tmp_path):
    from app.DeepAgent import deep_review_agent as module
    from app.DeepAgent.tools import paper_loader

    selected = {"doc_id": "same-title-id", "title": "Shared title", "doi": "10.1234/second", "result_key": "doi:10.1234/second"}
    loader = MagicMock(side_effect=AssertionError("Exact selection must not reload storage IDs"))
    monkeypatch.setattr(paper_loader, "load_papers_from_ids", loader)
    received = []

    def analyze(payload):
        paper = json.loads(payload["paper_json"])
        received.append(paper)
        return {"analysis": "Verified selected paper", "doi": paper["doi"]}

    monkeypatch.setattr(module, "analyze_paper_deep", SimpleNamespace(invoke=analyze))
    agent = module.DeepReviewAgent.__new__(module.DeepReviewAgent)
    agent.num_researchers = 1
    agent.workspace = MagicMock(session_id="identity", session_path=tmp_path)
    agent.workspace.load_all_analyses.return_value = [{"analysis": "Verified selected paper"}]
    result = agent.review_papers(["same-title-id"], verbose=False, papers_data=[selected])

    assert result["status"] == "completed"
    assert received == [selected]
    loader.assert_not_called()
    assert agent.workspace.save_researcher_analysis.call_args.kwargs["paper_id"] == selected["result_key"]
    saved = agent.workspace.save_selected_papers.call_args.args[0]
    assert saved == [selected]
    assert saved[0] is not selected


def test_explicit_empty_selection_does_not_fall_back_to_storage(monkeypatch, tmp_path):
    from app.DeepAgent import deep_review_agent as module
    from app.DeepAgent.tools import paper_loader

    loader = MagicMock(side_effect=AssertionError("No implicit paper substitution"))
    monkeypatch.setattr(paper_loader, "load_papers_from_ids", loader)
    agent = module.DeepReviewAgent.__new__(module.DeepReviewAgent)
    agent.num_researchers = 1
    agent.workspace = MagicMock(session_id="identity", session_path=tmp_path)
    result = agent.review_papers(["stale-id"], verbose=False, papers_data=[])
    assert result["status"] == "failed"
    loader.assert_not_called()
