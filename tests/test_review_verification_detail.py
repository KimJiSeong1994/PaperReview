"""Per-claim verification results: persisted with each claim and returned by the detail endpoint."""

import json
import os
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.DeepAgent.tools.fact_verification import (
    Claim,
    ClaimEvidence,
    ClaimType,
    Evidence,
    MatchType,
    VerificationStatus,
    claims_with_verification,
)

_JWT_SECRET = os.environ.get("JWT_SECRET", "test-jwt-secret-for-testing-only")


def _claim(cid, kind=ClaimType.STATISTICAL):
    return Claim(id=cid, text=f"claim {cid}", claim_type=kind, source_paper_id="p1", report_section="결과")


def _evidence(cid, score, status, text="x"):
    return Evidence(id=f"e-{cid}-{score}", claim_id=cid, paper_id="p1", text=text, estimated_section="Results",
                    match_type=MatchType.PARAPHRASE, similarity_score=score, verification_status=status)


def test_claims_with_verification_merges_best_evidence():
    claims = [_claim("c1"), _claim("c2"), _claim("c3", ClaimType.INTERPRETIVE)]
    evidences = [
        ClaimEvidence(claims[0], [_evidence("c1", 0.41, VerificationStatus.PARTIALLY_VERIFIED),
                                  _evidence("c1", 0.9234, VerificationStatus.VERIFIED, text="E" * 500)]),
        ClaimEvidence(claims[1], []),  # linked, nothing found
    ]
    c1, c2, c3 = claims_with_verification(claims, evidences)
    assert c1["text"] == "claim c1" and c1["claim_type"] == "statistical"  # original fields kept
    assert (c1["verification_status"], c1["evidence"], c1["confidence"]) == ("verified", "E" * 300, 0.923)
    assert c1["evidence_source"] == {"paper_id": "p1", "section": "Results"}
    assert (c2["verification_status"], c2["evidence"], c2["evidence_source"], c2["confidence"]) == (
        "unverified", None, None, None)
    assert c3["verification_status"] is None and c3["evidence"] is None  # never linked (interpretive)


def _auth(username):
    from routers.deps.storage import _get_user_db

    db = _get_user_db()
    if db.get(username) is None:
        db.create_account(username, {"password_hash": "x", "role": "user", "created_at": ""})
    payload = {
        "sub": username, "account_incarnation": db.get(username)["account_incarnation"], "role": "user",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1), "iat": datetime.now(timezone.utc),
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, _JWT_SECRET, algorithm='HS256')}"}


@pytest.fixture
def session_with_claims(tmp_path):
    import routers.reviews as reviews

    headers = _auth("verify_owner")
    from routers.deps.storage import _get_user_db

    verifications = tmp_path / "ws" / "verifications"
    verifications.mkdir(parents=True)
    new = claims_with_verification(
        [_claim("c1")], [ClaimEvidence(_claim("c1"), [_evidence("c1", 0.8, VerificationStatus.CONTRADICTED, "원문")])]
    )
    old = {"id": "c0", "text": "old claim", "claim_type": "factual", "source_paper_id": "p1", "report_section": "s"}
    (verifications / "claims_1.json").write_text(json.dumps({"claims": new + [old]}), encoding="utf-8")
    consensus = [{"topic": "memory", "consensus_level": "strong", "supporting_papers": ["p1", "p2"]}]
    (verifications / "crossrefs_1.json").write_text(
        json.dumps({"cross_references": [], "consensus": consensus}), encoding="utf-8")
    sid = "test-verification-detail"
    with reviews.review_sessions_lock:
        reviews.review_sessions[sid] = {
            "status": "completed", "username": "verify_owner",
            "account_incarnation": _get_user_db().get("verify_owner")["account_incarnation"],
            "workspace_path": str(tmp_path / "ws"), "num_papers": 2, "verification_stats": None,
        }
    yield sid, headers, consensus
    with reviews.review_sessions_lock:
        reviews.review_sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_endpoint_returns_claim_results_and_consensus(client, session_with_claims):
    sid, headers, consensus = session_with_claims
    body = (await client.get(f"/api/deep-review/verification/{sid}", headers=headers)).json()
    by_id = {c["id"]: c for c in body["claims"]}
    assert by_id["c1"]["verification_status"] == "contradicted" and by_id["c1"]["evidence"] == "원문"
    assert by_id["c1"]["evidence_source"] == {"paper_id": "p1", "section": "Results"}
    # A session saved before this change still loads; the new fields are null.
    assert by_id["c0"]["text"] == "old claim"
    assert [by_id["c0"][k] for k in ("verification_status", "evidence", "evidence_source", "confidence")] == [None] * 4
    assert body["consensus"] == consensus


def test_orchestrator_persists_merged_claims_and_consensus(monkeypatch):
    from types import SimpleNamespace

    from app.DeepAgent import review_orchestrator as ro

    claim = _claim("c1")
    monkeypatch.setattr(ro, "generate_markdown_report", lambda *a: "draft")
    monkeypatch.setattr(ro, "ClaimExtractor", lambda: SimpleNamespace(extract_claims_sync=lambda *a: [claim]))
    monkeypatch.setattr(ro, "EvidenceLinker", lambda: SimpleNamespace(find_all_evidence_sync=lambda *a: [
        ClaimEvidence(claim, [_evidence("c1", 0.7, VerificationStatus.VERIFIED, "근거")])]))
    consensus = SimpleNamespace(to_dict=lambda: {"topic": "t"})
    monkeypatch.setattr(ro, "CrossRefValidator", lambda: SimpleNamespace(
        detect_conflicts_sync=lambda claims: [], build_consensus_sync=lambda claims, refs: [consensus]))
    saved = {}
    workspace = SimpleNamespace(
        save_verification_claims=lambda claims: saved.update(claims=claims),
        save_cross_references=lambda refs, cons: saved.update(refs=refs, consensus=cons),
        log=lambda *a: None,
    )
    orchestrator = ro.ReviewOrchestrator.__new__(ro.ReviewOrchestrator)
    orchestrator.workspace = workspace
    orchestrator._verify_facts([{"id": "p1"}, {"id": "p2"}], [], {}, verbose=False)
    assert saved["claims"][0]["verification_status"] == "verified" and saved["claims"][0]["evidence"] == "근거"
    assert saved["consensus"] == [{"topic": "t"}] and saved["refs"] == []  # consensus kept without cross-refs


def test_full_mode_review_session_runs_claim_verification(monkeypatch, tmp_path):
    """start_review_session(fast_mode=False) → run_deep_review_background → verify_report_claims → saved claims."""
    import asyncio
    from functools import partial
    from types import SimpleNamespace

    from app.DeepAgent import deep_review_agent, workspace_manager
    from app.DeepAgent import review_orchestrator as ro
    from routers import reviews

    monkeypatch.setattr(
        workspace_manager, "WorkspaceManager", partial(workspace_manager.WorkspaceManager, base_path=str(tmp_path))
    )

    class FakeDeepReviewAgent:  # stands in for the deepagents researchers
        def __init__(self, model, num_researchers, workspace):
            self.workspace = workspace

        def review_papers(self, paper_ids, verbose, papers_data):
            self.workspace.save_researcher_analysis(
                "researcher_1", paper_ids[0], {"analysis_type": "deep_research", "analysis": "모델은 정확도 93%를 달성한다."}
            )
            return {"status": "completed", "workspace_path": str(self.workspace.session_path), "papers_reviewed": 1}

    claim = _claim("c1")
    seen = {}

    def extract(report, papers, analyses):
        seen.update(report=report, full_text=papers[0].get("full_text"))
        return [claim]

    monkeypatch.setattr(deep_review_agent, "DeepReviewAgent", FakeDeepReviewAgent)
    monkeypatch.setattr(reviews, "_generate_review_report_content", lambda ws, result, ids: "# 최종 리포트")
    monkeypatch.setattr(reviews, "_enrich_papers_with_abstracts", lambda papers: papers)
    monkeypatch.setattr(reviews, "_fetch_full_text", lambda paper: "the model reaches 93% accuracy on the benchmark")
    monkeypatch.setattr(ro, "ClaimExtractor", lambda: SimpleNamespace(extract_claims_sync=extract))
    monkeypatch.setattr(ro, "EvidenceLinker", lambda: SimpleNamespace(find_all_evidence_sync=lambda claims, papers: [
        ClaimEvidence(claim, [_evidence("c1", 0.88, VerificationStatus.VERIFIED, "93% accuracy")])]))

    scheduled = {}
    paper = {"title": "Memory Paper", "result_key": "k1", "abstract": "a"}
    sid = asyncio.run(reviews.start_review_session(
        [paper], ["k1"], None, fast_mode=False, schedule=lambda fn, **kw: scheduled.update(fn=fn, kw=kw)))
    assert scheduled["kw"]["fast_mode"] is False
    try:
        scheduled["fn"](**scheduled["kw"])
        session = reviews.review_sessions[sid]
        assert session["status"] == "completed"
        assert session["verification_stats"]["total_claims"] == 1 and session["verification_stats"]["verified"] == 1
        assert seen["report"] == "### Paper 1: Memory Paper\n\n모델은 정확도 93%를 달성한다."
        assert seen["full_text"] == "the model reaches 93% accuracy on the benchmark"
        files = list((tmp_path / sid / "verifications").glob("claims_*.json"))
        saved = json.loads(files[0].read_text(encoding="utf-8"))["claims"]
        assert saved[0]["verification_status"] == "verified" and saved[0]["evidence"] == "93% accuracy"
    finally:
        reviews.review_sessions.pop(sid, None)
