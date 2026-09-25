"""Deterministic evaluator arithmetic and artifact adversaries; no live capture."""
import copy
import math
from pathlib import Path
import subprocess
import sys

import pytest

from src.search_eval import judged_replay as jr
from src.search_eval.retrieval_eval import RetrievalDocument, _score_query

MATRIX = Path("data/search_eval/search_review_matrix_v1.json")
FIXTURE = Path("data/search_eval/search_review_synthetic_v1.json")


def artifacts():
    return jr.read_json(MATRIX), jr.read_json(FIXTURE, "capture"), jr.read_json(FIXTURE, "judgments")


def manifest():
    config = {"clean_source": True, "harness_digest": jr.digest("test-harness"), "identity_helper_digest": jr.digest("test-identities"),
              "dependencies": [["synthetic-test-dependency", "1"]], "python": sys.version,
              "policy_and_model_defaults_tree": jr.digest("source"), "model_environment": {}, "scoring_year": 2026}
    return {"revision": jr.BASELINE_REVISION, "tree": jr.digest("source"), "config": jr.digest(config), "configuration": config}


def make_run(matrix, capture, mode):
    rows = []
    for q in matrix["queries"]:
        ranked = [p["paper_key"] for p in q["required_candidates"]]
        records = [{"result_key": k, "title": "Synthetic, not human judged"} for k in ranked]
        rows.append({"query_id": q["query_id"], "ranked": ranked, "records": records, "request_keys": [], "replay_misses": [], "source_outcomes": {}, "call_counts": {}, "elapsed_ms": 0.0})
    return jr.run_artifact(matrix, capture, mode, manifest(), rows, "2026-02-01T00:00:00+00:00")


def row(grade=3, required=False, excluded=False):
    return {"grade": grade, "required": required, "excluded": excluded}


def test_exact_arithmetic_duplicates_exclusion_and_unknown():
    judgments = {"a": row(3, True), "b": row(2, True), "wrong": row(3, False, True)}
    scores = jr.score_identities(["wrong", "a", "a", "unknown", "b"], judgments)
    expected = (7 / math.log2(3) + 3 / math.log2(6)) / (7 + 3 / math.log2(3))
    assert scores["nDCG@10"] == pytest.approx(expected)
    assert scores["MRR@10"] == 0.5
    assert scores["Recall@5"] == 1
    assert scores["Recall@10"] == 1
    assert scores["wrong_paper_handoff_rate"] == 1
    assert jr.score_identities(["a"] * 10, judgments)["Recall@10"] == 0.5


def test_phrase_diagnostic_exclusion_precedes_positive_and_duplicate_credit():
    labels = {"must_include": ["alpha", "beta"], "acceptable": [], "must_exclude": ["forbidden"]}
    docs = [RetrievalDocument("alpha forbidden"), RetrievalDocument("same", "alpha", paper_key="doi:x"), RetrievalDocument("same", "beta", paper_key="doi:x")]
    score = _score_query(query_id="q", labels=labels, docs=docs)
    assert score.recall_at_10 == 0.5
    assert score.mrr_at_10 == 0.5
    assert score.wrong_paper_handoff == 1
    assert score.ndcg_at_10 == round((7 / math.log2(3)) / (7 + 7 / math.log2(3)), 6)


def test_checked_in_matrix_is_finite_and_synthetic_is_nonhuman():
    matrix, capture, judgments = artifacts()
    jr.validate_matrix(matrix)
    jr.validate_capture(matrix, capture)
    jr.validate_judgments(matrix, capture, judgments)
    assert sum(q["split"] == "holdout" for q in matrix["queries"]) == 16
    assert all(r["author_id"] is None and r["reviewer_id"] is None for r in judgments["rows"])


@pytest.mark.parametrize("mutate", [
    lambda j: j["rows"].append(copy.deepcopy(j["rows"][0])),
    lambda j: j["rows"][0].update(grade=True),
    lambda j: j["rows"][0].update(grade=3.0),
    lambda j: j["rows"][0].update(grade=4),
    lambda j: j["rows"][0].update(required=True, excluded=True),
    lambda j: j.update(capture_hash=jr.digest("other capture")),
    lambda j: j.update(matrix_hash=jr.digest("other matrix")),
])
def test_invalid_judgments_even_when_resealed(mutate):
    matrix, capture, judgments = artifacts()
    mutate(judgments)
    judgments = jr.seal(judgments, "judgment_hash")
    with pytest.raises(jr.InvalidArtifact):
        jr.validate_judgments(matrix, capture, judgments)


def test_stale_hash_rejected_and_duplicate_json_keys_rejected(tmp_path):
    matrix, _, _ = artifacts()
    matrix["queries"][0]["query"] = "forged"
    with pytest.raises(jr.InvalidArtifact, match="hash mismatch"):
        jr.validate_matrix(matrix)
    path = tmp_path / "duplicate.json"
    path.write_text('{"version":1,"version":2}')
    with pytest.raises(jr.InvalidArtifact, match="duplicate JSON key"):
        jr.read_json(path)


def test_exact_rewrite_key_has_no_original_or_network_fallback():
    _, capture, _ = artifacts()
    original = jr.effective_http("GET", "https://example.invalid/search?q=원문&limit=50")
    rewritten = jr.effective_http("GET", "https://example.invalid/search?q=translated+query&limit=50")
    capture["entries"] = [{"request_key": jr.digest(original), "request": original, "response": [], "status": "ok", "origin": {"kind": "synthetic"}}]
    transport = jr.FrozenTransport(capture)
    assert transport.call(original) == []
    assert transport.call(original) == []
    with pytest.raises(jr.ReplayMiss):
        transport.call(rewritten, lambda: pytest.fail("network fallback"))
    assert transport.ledger == [jr.digest(original), jr.digest(original), jr.digest(rewritten)]
    assert transport.misses == [jr.digest(rewritten)]


def test_semantic_http_syntax_and_secrets():
    first = jr.effective_http("GET", "https://example.invalid/search?q=a+NOT+b&api_key=secret")
    second = jr.effective_http("GET", "https://example.invalid/search?q=a+b&api_key=other")
    assert first["effective_query"] == "a NOT b"
    assert jr.digest(first) != jr.digest(second)
    assert "secret" not in jr.canonical(first).decode()
    with pytest.raises(jr.InvalidArtifact, match="secret"):
        jr.effective_http("POST", "https://example.invalid/search", '{"api_key":"secret"}')


def test_capture_conflicts_require_explicit_resolution():
    _, capture, _ = artifacts()
    capture["entries"] = []
    transport = jr.FrozenTransport(capture, recording=True)
    request = jr.effective_http("GET", "https://example.invalid/search?q=a")
    assert transport.call(request, lambda: [1]) == [1]
    with pytest.raises(jr.InvalidArtifact, match="conflicting"):
        transport.call(request, lambda: [2])
    assert capture["entries"][0]["response"] == [1]
    assert capture["entries"][0]["origin"]["kind"] == "synthetic"
    assert transport.conflicts == [jr.digest(request)]


def test_synthetic_fixed_pool_cannot_pass_even_with_perfect_scores():
    matrix, capture, judgments = artifacts()
    b, c = make_run(matrix, capture, "standard"), make_run(matrix, capture, "fast")
    report = jr.compare(matrix, capture, judgments, b, c, "fixed_pool")
    assert report["promotion_decision"] == "inconclusive"
    assert "fixed_pool_is_not_retrieval_evidence" in report["qualification_reasons"]
    assert not report["regressions"]
    assert "holdout/language=ko" in report["slices"]


def test_top10_required_retention_and_unknown_coverage_are_separate():
    matrix, capture, judgments = artifacts()
    b, c = make_run(matrix, capture, "standard"), make_run(matrix, capture, "fast")
    required = c["per_query"][0]["ranked"][0]
    c["per_query"][0]["ranked"] = [f"unknown:{i}" for i in range(10)] + [required]
    c["per_query"][0]["records"] = [{"result_key": k} for k in c["per_query"][0]["ranked"]]
    c = jr.seal(c, "run_hash")
    report = jr.compare(matrix, capture, judgments, b, c, "routed_replay")
    assert report["promotion_decision"] == "inconclusive"
    assert report["per_query"][0]["required_hit_losses"] == [required]
    assert len(report["per_query"][0]["coverage"]["unjudged_top10"]) == 10
    assert "all:Recall@10" in report["regressions"]


def test_forged_run_manifest_or_capture_binding_is_invalid():
    matrix, capture, judgments = artifacts()
    capture["baseline"] = manifest()
    capture = jr.seal(capture, "capture_hash")
    judgments["capture_hash"] = capture["capture_hash"]
    judgments = jr.seal(judgments, "judgment_hash")
    b, c = make_run(matrix, capture, "standard"), make_run(matrix, capture, "fast")
    b["manifest"]["tree"] = jr.digest("forged tree")
    b["manifest"]["configuration"]["policy_and_model_defaults_tree"] = b["manifest"]["tree"]
    b["manifest"]["config"] = jr.digest(b["manifest"]["configuration"])
    b = jr.seal(b, "run_hash")
    with pytest.raises(jr.InvalidArtifact, match="pinned revision"):
        jr.compare(matrix, capture, judgments, b, c, "routed_replay")
    b = make_run(matrix, capture, "standard")
    b["capture_hash"] = jr.digest("other capture")
    b = jr.seal(b, "run_hash")
    with pytest.raises(jr.InvalidArtifact, match="binding mismatch"):
        jr.compare(matrix, capture, judgments, b, c, "routed_replay")


def test_pool_above_eighty_is_ineligible_not_silently_truncated():
    matrix, capture, judgments = artifacts()
    capture["pools"]["c01-en"] += [f"identity:{i}" for i in range(80)]
    capture = jr.seal(capture, "capture_hash")
    judgments["capture_hash"] = capture["capture_hash"]
    judgments = jr.seal(judgments, "judgment_hash")
    report = jr.compare(matrix, capture, judgments, make_run(matrix, capture, "standard"), make_run(matrix, capture, "fast"), "routed_replay")
    assert report["promotion_decision"] == "inconclusive"
    assert "c01-en:candidate_bound_exceeded" in report["qualification_reasons"]
    assert report["per_query"][0]["coverage"]["pool_size"] == 81


def test_cli_validate_and_compare_write_real_artifact(tmp_path):
    matrix, capture, _ = artifacts()
    b, c = tmp_path / "baseline.json", tmp_path / "candidate.json"
    jr.write_json(b, make_run(matrix, capture, "standard"))
    jr.write_json(c, make_run(matrix, capture, "fast"))
    common = ["--matrix", str(MATRIX), "--capture", str(FIXTURE), "--judgments", str(FIXTURE)]
    assert subprocess.run([sys.executable, "-m", "src.search_eval.judged_replay", "validate", *common], capture_output=True).returncode == 0
    report_path = tmp_path / "report.json"
    result = subprocess.run([sys.executable, "-m", "src.search_eval.judged_replay", "compare", *common, "--baseline", str(b), "--candidate", str(c), "--scope", "routed_replay", "--out", str(report_path)], capture_output=True)
    assert result.returncode == 3, result.stderr.decode()
    report = jr.read_json(report_path)
    assert report["promotion_decision"] == "inconclusive"
    assert report["report_hash"] == jr.seal(report, "report_hash")["report_hash"]
    assert report["input_hashes"]["baseline"] == jr.read_json(b)["run_hash"]


def test_replay_cli_writes_missing_environment_artifact(monkeypatch, tmp_path):
    matrix, capture, _ = artifacts()
    monkeypatch.setattr(jr, "current_manifest", manifest)
    async def unavailable(*args, **kwargs):
        run = make_run(matrix, capture, "fast")
        for q in run["per_query"]:
            q["ranked"], q["records"] = [], []
            q["replay_misses"] = ["runtime_unavailable:missing_dependency"]
        return run["per_query"], jr.FrozenTransport(capture)
    monkeypatch.setattr(jr, "execute_queries", unavailable)
    path = tmp_path / "run.json"
    code = jr.main(["replay", "--matrix", str(MATRIX), "--capture", str(FIXTURE), "--mode", "fast", "--out", str(path)])
    assert code == 3
    run = jr.read_json(path)
    jr.validate_run(matrix, capture, run, "fast")
    assert all(q["replay_misses"] for q in run["per_query"])


def test_replay_blocks_uninstrumented_network():
    import socket
    from contextlib import ExitStack
    _, capture, _ = artifacts()
    transport = jr.FrozenTransport(capture)
    with ExitStack() as stack:
        jr.install_transports(stack, transport)
        with pytest.raises(jr.ReplayMiss, match="forbidden"):
            socket.getaddrinfo("example.invalid", 443)
    assert transport.misses == ["unintercepted_network"]


@pytest.fixture
def recording_route(monkeypatch):
    """Controlled ASGI source; execute_queries and its collector/drain stay real."""
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from types import ModuleType, SimpleNamespace
    from fastapi import APIRouter

    router = APIRouter(prefix="/api")
    generations = []
    state = SimpleNamespace(counts={}, calls=[], late={}, failed_drain=None)
    agent = SimpleNamespace(
        deduplicator=SimpleNamespace(deduplicate=lambda papers: papers),
        _operation_generation_runtime=(threading.Lock(), {"test": generations}),
    )
    search = ModuleType("routers.search")
    search.router = router
    search.search_agent = agent
    search.query_analyzer = SimpleNamespace(
        analyze_and_prepare=lambda query, apply_skillopt_policy=False: {
            "is_academic": True, "original_query": query,
        }
    )
    search._hybrid_ranker = SimpleNamespace()
    search.get_optional_user = lambda: None
    search._get_cached_result = lambda *args, **kwargs: None
    search._set_cache = lambda *args, **kwargs: None

    @router.post("/search")
    async def controlled_search(body: dict):
        query = body["query"]
        state.calls.append(query)
        papers = [
            {"doi": f"10.1234/{query}-{i}", "title": f"{query} record {i}"}
            for i in range(state.counts.get(query, 0))
        ]
        agent.deduplicator.deduplicate(papers)
        if state.failed_drain is not None:
            generations.append(SimpleNamespace(_executor=state.failed_drain))
        if query in state.late:
            release = threading.Event()
            executor = ThreadPoolExecutor(max_workers=1)
            # Only shutdown releases the observation: it necessarily happens
            # after ASGI response completion and before next-query admission.
            class OwnedExecutor:
                def shutdown(self, wait, cancel_futures):
                    release.set()
                    executor.shutdown(wait=wait, cancel_futures=cancel_futures)
                    observation.result()

            started = threading.Event()
            def late_observation():
                started.set()
                assert release.wait(5), "query worker was not drained"
                agent.deduplicator.deduplicate([state.late[query]])
            observation = executor.submit(late_observation)
            assert started.wait(5)
            generations.append(SimpleNamespace(_executor=OwnedExecutor()))
        return {"results": {"arxiv": papers}, "metadata": {"query": query}}

    routers_module = ModuleType("routers")
    routers_module.search = search
    graph_module = ModuleType("src.graph_rag")
    graph_module.hybrid_ranker = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "routers", routers_module)
    monkeypatch.setitem(sys.modules, "routers.search", search)
    monkeypatch.setitem(sys.modules, "src.graph_rag", graph_module)
    yield state, search
    jr.drain_operations(search)


@pytest.mark.parametrize("first_count,exceeded", [(60, False), (78, False), (81, True)])
def test_execute_queries_records_independent_pools_and_bound(
    recording_route, first_count, exceeded
):
    import asyncio

    state, _ = recording_route
    matrix, capture, judgments = artifacts()
    first, second = matrix["queries"][:2]
    state.counts = {first["query"]: first_count, second["query"]: 60}
    first_old = set(capture["pools"][first["query_id"]])
    second_old = set(capture["pools"][second["query_id"]])
    state.late[first["query"]] = {"doi": "10.1234/late-first", "title": "Late first"}
    rows, transport = asyncio.run(
        jr.execute_queries(matrix, capture, "fast", manifest(), recording=True)
    )
    assert state.calls == [q["query"] for q in matrix["queries"]], rows
    assert all(not row["replay_misses"] for row in rows), rows
    first_keys = {f"doi:10.1234/{first['query'].lower()}-{i}" for i in range(first_count)}
    second_keys = {f"doi:10.1234/{second['query'].lower()}-{i}" for i in range(60)}
    assert set(capture["pools"][first["query_id"]]) == first_old | first_keys | {"doi:10.1234/late-first"}
    assert set(capture["pools"][second["query_id"]]) == second_old | second_keys
    assert not first_keys.intersection(capture["pools"][second["query_id"]])
    assert "doi:10.1234/late-first" not in capture["pools"][second["query_id"]]
    assert len(first_keys | second_keys) > 80
    sealed_pool = copy.deepcopy(capture["pools"])
    transport.candidates.add("doi:10.1234/post-run")
    state.late[first["query"]]["doi"] = "10.1234/mutated"
    assert capture["pools"] == sealed_pool
    assert rows[0]["source_outcomes"] == {"query": first["query"]}

    capture = jr.seal(capture, "capture_hash")
    judgments["capture_hash"] = capture["capture_hash"]
    judgments = jr.seal(judgments, "judgment_hash")
    report = jr.compare(
        matrix, capture, judgments, make_run(matrix, capture, "standard"),
        make_run(matrix, capture, "fast"), "routed_replay",
    )
    bound_reasons = [r for r in report["qualification_reasons"] if "candidate_bound_exceeded" in r]
    assert bound_reasons == ([f"{first['query_id']}:candidate_bound_exceeded"] if exceeded else [])
    # Per-query bound eligibility is not synthetic evidence qualification.
    assert report["promotion_decision"] == "inconclusive"


def test_execute_queries_drain_failure_stops_before_next_request(recording_route):
    import asyncio

    state, search = recording_route
    matrix, capture, _ = artifacts()
    generations = search.search_agent._operation_generation_runtime[1]["test"]

    class FailedDrain:
        def shutdown(self, **kwargs):
            raise RuntimeError("underlying worker did not drain")

    state.failed_drain = FailedDrain()
    try:
        with pytest.raises(RuntimeError, match="did not drain"):
            asyncio.run(jr.execute_queries(matrix, capture, "fast", manifest(), recording=True))
        assert state.calls == [matrix["queries"][0]["query"]]
    finally:
        generations.clear()


def test_production_model_boundaries_capture_replay_lifecycle(monkeypatch):
    import threading
    from contextlib import ExitStack
    from types import SimpleNamespace
    from src.graph_rag import hybrid_ranker as hr
    from app.QueryAgent.relevance_filter import LocalRelevanceScorer

    clock = [100.0]
    monkeypatch.setattr(hr.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(hr, "_CE_CACHE", {})
    calls = []

    def model_response(client, **kwargs):
        calls.append(("hyde", kwargs))
        if kwargs.get("response_format"):
            content = '{"abstract":"Nonempty hypothetical abstract","alt_queries":["first alternative","second alternative"]}'
        elif kwargs["max_tokens"] == 200:
            content = "Nonempty fallback abstract"
        else:
            content = "first alternative\nsecond alternative"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    def scores(query, papers):
        calls.append(("ce", query))
        return [0.75 for _ in papers]

    monkeypatch.setattr(hr, "create_chat_completion", model_response)
    monkeypatch.setattr(LocalRelevanceScorer, "score_papers", scores)
    ranker = hr.HybridRanker()
    search = SimpleNamespace(
        query_analyzer=None, search_agent=SimpleNamespace(), _hybrid_ranker=ranker,
    )
    client = SimpleNamespace(base_url="https://model.invalid/v1")
    papers = [{"doi": "10.1234/model-boundary", "title": "Nonempty model candidate", "abstract": "Graph learning"}]
    _, capture, _ = artifacts()
    recording = jr.FrozenTransport(capture, recording=True)
    config = manifest()["config"]
    methods = (
        "_generate_hyde_unified", "_generate_hypothetical_abstract",
        "_generate_alt_queries", "_compute_cross_encoder_scores",
    )

    def invoke(name, deadline, event, query="graph learning"):
        if name == "_compute_cross_encoder_scores":
            return getattr(ranker, name)(query, copy.deepcopy(papers), deadline=deadline, stop_event=event)
        kwargs = {} if name == "_generate_alt_queries" else {"research_area": "graphs"}
        return getattr(ranker, name)(query, client, deadline=deadline, stop_event=event, **kwargs)

    with ExitStack() as stack:
        jr.install_model_boundaries(stack, recording, search, config)
        expected = {name: invoke(name, 200.0, threading.Event()) for name in methods}
    assert all(expected.values())
    assert len(calls) == 4
    assert len(capture["boundaries"]) == 4
    assert all("deadline" not in entry["request"]["input"] and "stop_event" not in entry["request"]["input"] for entry in capture["boundaries"])
    assert all(entry["request"]["config"] == config for entry in capture["boundaries"])

    def forbidden(*args, **kwargs):
        pytest.fail("replay/cutoff must not execute model transport")

    monkeypatch.setattr(hr, "create_chat_completion", forbidden)
    monkeypatch.setattr(LocalRelevanceScorer, "score_papers", forbidden)
    monkeypatch.setattr(hr, "_CE_CACHE", {})
    clock[0] = 500.0
    replay = jr.FrozenTransport(capture)
    with ExitStack() as stack:
        jr.install_transports(stack, replay)
        jr.install_model_boundaries(stack, replay, search, config)
        for name in methods:
            assert invoke(name, 900.0, threading.Event()) == expected[name]
        assert replay.ledger == recording.ledger
        assert replay.misses == []
        successful_ledger = list(replay.ledger)
        empty = {"_generate_hyde_unified": ("", []), "_generate_hypothetical_abstract": "",
                 "_generate_alt_queries": [], "_compute_cross_encoder_scores": []}
        for name in methods:
            stopped = threading.Event()
            stopped.set()
            assert invoke(name, 900.0, stopped) == empty[name]
            assert invoke(name, 499.0, threading.Event()) == empty[name]
        assert replay.ledger == successful_ledger
        assert replay.misses == []
        with pytest.raises(jr.ReplayMiss):
            invoke("_compute_cross_encoder_scores", 900.0, threading.Event(), query="different semantic query")
        with pytest.raises(jr.ReplayMiss):
            ranker._generate_hyde_unified(
                "graph learning", client, research_area="different domain",
                deadline=900.0, stop_event=threading.Event(),
            )
    different_config = jr.FrozenTransport(capture)
    with ExitStack() as stack:
        jr.install_model_boundaries(stack, different_config, search, jr.digest("different model config"))
        with pytest.raises(jr.ReplayMiss):
            invoke("_generate_alt_queries", 900.0, threading.Event())

    # Cancellation that arrives while reading a frozen response must also win.
    event = threading.Event()
    interrupted = jr.FrozenTransport(capture)
    frozen_call = interrupted.call
    def stop_after_lookup(*args, **kwargs):
        value = frozen_call(*args, **kwargs)
        event.set()
        return value
    monkeypatch.setattr(interrupted, "call", stop_after_lookup)
    with ExitStack() as stack:
        jr.install_model_boundaries(stack, interrupted, search, config)
        assert invoke("_compute_cross_encoder_scores", 900.0, event) == []
    assert interrupted.misses == []

    cancelled_capture = copy.deepcopy(capture)
    cancelled_capture["boundaries"] = []
    cancelled = jr.FrozenTransport(cancelled_capture, recording=True)
    with ExitStack() as stack:
        jr.install_model_boundaries(stack, cancelled, search, config)
        for name in methods:
            assert invoke(name, 900.0, event) == empty[name]
            assert invoke(name, 499.0, threading.Event()) == empty[name]
    assert cancelled_capture["boundaries"] == []
    assert cancelled.ledger == []
