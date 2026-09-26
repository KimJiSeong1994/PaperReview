"""Fake-only public acquisition and workflow contract fixtures."""

import ast
import hashlib
import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from src.related_paper_wiki import (
    PUBLIC_SEEDS,
    collect_review_build_wiki,
    load_seed_queries,
    main,
)
from src.recommendation_candidates import CandidateValidationError

RUN = "2026-09-25T00:00:00Z"


class Provider:
    def __init__(self, status="searched"):
        self.calls = []
        self.status = status

    def __call__(self, seed, deadline):
        self.calls.append((seed, deadline))
        payload = b"public-response"
        return [
            {
                "title": "Public paper",
                "doi": "10.1234/a",
                "year": 2026,
                "query": "PRIVATE",
                "reason": "PRIVATE",
                "score": float("nan"),
            }
        ], [
            {
                "status": self.status,
                "response_sha256": hashlib.sha256(payload).hexdigest(),
                "response_bytes": len(payload),
                "query": "PRIVATE",
            }
        ]


def collect(tmp_path, **kwargs):
    return collect_review_build_wiki(
        candidate_root=tmp_path / "candidates",
        final_root=tmp_path / "final",
        run_at=RUN,
        **kwargs,
    )


def test_public_fixed_seeds_never_read_legacy_or_private_inputs(tmp_path):
    (tmp_path / "bookmarks.db").write_text("PRIVATE")
    (tmp_path / "papers.json").write_text('{"papers":[{"title":"PRIVATE"}]}')
    provider = Provider()
    result = collect(tmp_path, source_qualified=True, attempt=provider, clock=lambda: 0)
    assert load_seed_queries() == [
        "graph neural networks",
        "information retrieval",
        "urban mobility",
    ]
    assert [seed for seed, _ in provider.calls] == list(PUBLIC_SEEDS)
    assert len(provider.calls) == 3
    assert all(deadline == 10 for _, deadline in provider.calls)
    assert result["availability"] == "fixture"
    assert result["item_count"] == 3
    assert not (tmp_path / "final").exists()
    for artifact in (tmp_path / "candidates").rglob("*"):
        if artifact.is_file():
            assert "PRIVATE" not in artifact.read_text()
            assert "related_review_score" not in artifact.read_text()
    receipt = json.loads(
        next((tmp_path / "candidates").rglob("*.receipt.json")).read_text()
    )
    assert receipt["public_seed_manifest"]["seeds"] == list(PUBLIC_SEEDS)
    assert len(receipt["manifest_sha256"]) == 64
    assert all("response_sha256" in evidence for evidence in receipt["attempts"])
    wiki = next((tmp_path / "candidates").rglob("*.wiki.md")).read_text()
    assert "Public paper" in wiki and "Canonical key: doi:10.1234/a" in wiki


def test_disabled_source_is_empty_without_provider_dispatch(tmp_path):
    def forbidden(*args):
        raise AssertionError("dispatch forbidden")

    result = collect(tmp_path, attempt=forbidden, clock=lambda: 0)
    assert result["status"] == "empty" and result["availability"] == "disabled"
    assert result["attempt_count"] == 0
    assert result["acquisition_status"] == "disabled"


def test_failures_retry_once_six_total_and_no_raw_error(tmp_path):
    provider = Provider("error")
    result = collect(tmp_path, source_qualified=True, attempt=provider, clock=lambda: 0)
    assert len(provider.calls) == 6
    assert result["status"] == "empty"
    assert result["item_count"] == 0
    assert result["acquisition_status"] == "error"


def test_cli_failed_acquisition_has_distinct_exit_and_persisted_health(
    tmp_path, monkeypatch, capsys
):
    from src import related_paper_wiki

    original = related_paper_wiki.collect_review_build_wiki
    monkeypatch.setattr(
        related_paper_wiki,
        "collect_review_build_wiki",
        lambda **kwargs: original(**kwargs, attempt=Provider("error"), clock=lambda: 0),
    )
    code = main(
        [
            "--candidate-root",
            str(tmp_path / "candidates"),
            "--final-root",
            str(tmp_path / "final"),
            "--run-at",
            RUN,
            "--source-qualified",
        ]
    )
    assert code == 3
    result = json.loads(capsys.readouterr().out)
    assert result["acquisition_status"] == "error"
    snapshot = json.loads(
        (
            tmp_path
            / "candidates/public/local_public/current-local_public-public-seeds-v1.json"
        ).read_text()
    )
    assert snapshot["acquisition_status"] == "error"


def test_provider_exception_is_sanitized(tmp_path):
    def fail(*args):
        raise ValueError("PRIVATE")

    result = collect(tmp_path, source_qualified=True, attempt=fail, clock=lambda: 0)
    assert result["status"] == "empty"
    assert (
        "PRIVATE"
        not in next((tmp_path / "candidates").rglob("*.receipt.json")).read_text()
    )


@pytest.mark.parametrize(
    "mode,health", [("success", "ready"), ("empty", "empty"), ("partial", "degraded")]
)
def test_collector_health_serialized_current_reload(tmp_path, mode, health):
    from src.recommendation_candidates import (
        TrustedReceiverPolicy,
        load_current_candidate_snapshot,
    )
    from datetime import datetime

    def provider(seed, deadline):
        if mode == "empty":
            return [], [{"status": "searched_empty"}]
        if mode == "partial" and seed == PUBLIC_SEEDS[0]:
            return [], [{"status": "error"}]
        return Provider()(seed, deadline)

    result = collect(tmp_path, source_qualified=True, attempt=provider, clock=lambda: 0)
    policy = TrustedReceiverPolicy(
        "local_public", "public", "public-seeds-v1", public_source_qualified=True
    )
    loaded = load_current_candidate_snapshot(
        tmp_path / "candidates",
        final_root=tmp_path / "final",
        policy=policy,
        now=datetime.fromisoformat(RUN.replace("Z", "+00:00")),
    )
    assert result["acquisition_status"] == loaded.acquisition_status == health
    if mode == "partial":
        assert "partial_failure" in loaded.acquisition_reasons


def test_no_late_publication_after_total_deadline(tmp_path):
    now = [0]
    calls = []

    def slow(seed, deadline):
        calls.append(seed)
        now[0] = 61
        return Provider()(seed, deadline)

    result = collect(
        tmp_path, source_qualified=True, attempt=slow, clock=lambda: now[0]
    )
    assert result["code"] == "collection_deadline"
    assert len(calls) == 1
    assert not (tmp_path / "candidates").exists()


def test_attempt_timeout_discards_late_result(tmp_path):
    now = [0]

    def slow(seed, deadline):
        now[0] = deadline
        return Provider()(seed, deadline)

    result = collect(
        tmp_path, source_qualified=True, attempt=slow, clock=lambda: now[0]
    )
    assert result["item_count"] == 0
    assert result["attempt_count"] == 6


def test_stop_prevents_dispatch_and_publication(tmp_path):
    class Stopped:
        def is_set(self):
            return True

    provider = Provider()
    result = collect(
        tmp_path,
        source_qualified=True,
        attempt=provider,
        clock=lambda: 0,
        stop_event=Stopped(),
    )
    assert result["code"] == "collection_deadline" and not provider.calls


def test_overlap_and_symlink_rejected_before_dispatch(tmp_path):
    provider = Provider()
    with pytest.raises(CandidateValidationError, match="final_root_overlap"):
        collect_review_build_wiki(
            candidate_root=tmp_path / "final/staging",
            final_root=tmp_path / "final",
            run_at=RUN,
            source_qualified=True,
            attempt=provider,
        )
    target = tmp_path / "outside"
    target.mkdir()
    (tmp_path / "candidates").symlink_to(target, target_is_directory=True)
    with pytest.raises(CandidateValidationError, match="unsafe_path"):
        collect(tmp_path, source_qualified=True, attempt=provider)
    assert not provider.calls


@pytest.mark.parametrize(
    "args",
    [
        ["--bookmarks-db", "PRIVATE"],
        ["--papers-json", "PRIVATE"],
        ["--query", "PRIVATE"],
    ],
)
def test_legacy_cli_inputs_removed(args, capsys):
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out) == {"code": "invalid_arguments"}


def test_openalex_stream_size_bounded_before_json(monkeypatch):
    from src.collector.paper.openalex_searcher import OpenAlexSearcher

    class Response:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield b"x" * 5
            yield b"y" * 5

        def json(self):
            raise AssertionError("must not parse response before bound")

    response = Response()
    calls = []
    searcher = OpenAlexSearcher()

    def get(url, **kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(searcher.session, "get", get)
    monkeypatch.setattr(
        "src.collector.paper.openalex_searcher.time.monotonic", lambda: 0
    )
    attempts = []
    try:
        assert (
            searcher.search_public(
                PUBLIC_SEEDS[0], deadline=10, attempts=attempts, max_response_bytes=8
            )
            == []
        )
    finally:
        searcher.close()
    assert calls[0]["stream"] is True
    assert calls[0]["timeout"] <= 10
    assert calls[0]["params"]["per_page"] == 8
    assert attempts[0]["status"] == "error"
    assert response.closed


def test_openalex_expired_deadline_never_dispatches(monkeypatch):
    from src.collector.paper.openalex_searcher import OpenAlexSearcher

    searcher = OpenAlexSearcher()

    def forbidden(*args, **kwargs):
        raise AssertionError("must not dispatch")

    monkeypatch.setattr(searcher.session, "get", forbidden)
    monkeypatch.setattr(
        "src.collector.paper.openalex_searcher.time.monotonic", lambda: 11
    )
    attempts = []
    try:
        assert (
            searcher.search_public(PUBLIC_SEEDS[0], deadline=10, attempts=attempts)
            == []
        )
    finally:
        searcher.close()
    assert attempts[0]["status"] == "timeout"


@pytest.mark.parametrize(
    "body,expected",
    [
        (
            {
                "results": [
                    {
                        "display_name": "Public work",
                        "id": "https://openalex.org/W1",
                        "publication_year": 2026,
                        "authorships": [],
                    }
                ]
            },
            1,
        ),
        ([], 0),
        ({"results": "bad"}, 0),
    ],
)
def test_openalex_bounded_parse_and_response_digest(monkeypatch, body, expected):
    from src.collector.paper.openalex_searcher import OpenAlexSearcher

    payload = json.dumps(body).encode()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield payload[:3]
            yield payload[3:]

    searcher = OpenAlexSearcher()
    monkeypatch.setattr(searcher.session, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        "src.collector.paper.openalex_searcher.time.monotonic", lambda: 0
    )
    attempts = []
    try:
        result = searcher.search_public(PUBLIC_SEEDS[0], deadline=10, attempts=attempts)
    finally:
        searcher.close()
    assert len(result) == expected
    assert attempts[0]["response_sha256"] == hashlib.sha256(payload).hexdigest()
    assert attempts[0]["response_bytes"] == len(payload)


def test_workflow_command_contract_has_no_private_bridge_or_mutable_deploy():
    text = (
        Path(__file__).parents[1] / ".github/workflows/daily-recommendations.yml"
    ).read_text()
    for forbidden in (
        "_create_token",
        "JIPHYEONJEON_TOKEN",
        "ssh-keyscan",
        "tail -",
        "checkout -f",
        "reset --hard",
        "--skip-existing",
        "--papers-json",
        "paper-recommender",
        "import_openclaw",
    ):
        assert forbidden not in text
    for required in (
        "cancel-in-progress: false",
        "timeout-minutes: 15",
        "TemporaryDirectory",
        "StrictHostKeyChecking=yes",
        "timeout --signal=TERM --kill-after=5s 780s",
        'git("rev-parse", "HEAD")',
        'git("status", "--porcelain", "--untracked-files=all")',
        "source_disabled",
        "collect_related_papers_for_wiki.py",
        "generate_daily_recommendations.py",
        "subprocess.DEVNULL",
    ):
        assert required in text


@pytest.mark.parametrize("returncode", [0, 1, "timeout", "sigterm", "sigint"])
def test_workflow_command_spy_transport_cleanup(
    monkeypatch, capsys, tmp_path, returncode
):
    workflow = (
        Path(__file__).parents[1] / ".github/workflows/daily-recommendations.yml"
    ).read_text()
    program = textwrap.dedent(workflow.split("        run: |\n", 1)[1])
    for key, value in {
        "RELEASE_PATH": "/approved/release",
        "RELEASE_SHA": "a" * 40,
        "DATA_ROOT": "/approved/data",
        "PUBLIC_SOURCE_QUALIFIED": "false",
        "DEPLOY_HOST": "example.org",
        "DEPLOY_USER": "deploy",
        "DEPLOY_KEY": "TRANSPORT_PRIVATE_MARKER",
        "DEPLOY_KNOWN_HOSTS": "pinned-host",
    }.items():
        monkeypatch.setenv(key, value)
    calls = []
    handlers = {}
    unrelated = tmp_path / "unrelated-key"
    unrelated.write_text("untouched")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        key = Path(command[command.index("-i") + 1])
        assert key.read_text() == "TRANSPORT_PRIVATE_MARKER"
        assert key.stat().st_mode & 0o777 == 0o600
        assert (key.parent / "known_hosts").exists()
        assert "TRANSPORT_PRIVATE_MARKER" not in kwargs["input"]
        assert "TRANSPORT_PRIVATE_MARKER" not in " ".join(command)
        assert kwargs["timeout"] == 810
        # Evaluate only the actual argv assignments, never remote checks or
        # subprocess calls. Private bookmarks belong to the local ranker,
        # not the public collector; both use the configured external data root.
        names = {
            "CONFIG",
            "release",
            "data",
            "python",
            "common",
            "collector",
            "daily",
            "child_env",
        }
        assignments = [
            node
            for node in ast.parse(kwargs["input"]).body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in names
                for target in node.targets
            )
        ]
        scope = {"Path": Path, "run_at": RUN, "os": os}
        exec(
            compile(
                ast.Module(body=assignments, type_ignores=[]),
                "<remote-argv-fixture>",
                "exec",
            ),
            scope,
        )
        assert "--bookmarks-db" not in scope["collector"]
        assert "--users-db" not in scope["collector"]
        assert "--events-db" not in scope["collector"]
        assert scope["child_env"]["DATA_DIR"] == "/approved/data"
        assert scope["child_env"]["EVENTS_DB_PATH"] == "/approved/data/events.db"
        assert (
            scope["child_env"]["FEATURE_FLAGS_DB_PATH"]
            == "/approved/data/feature_flags.db"
        )
        remote_calls = [
            node
            for node in ast.walk(ast.parse(kwargs["input"]))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "command"
        ]
        assert len(remote_calls) == 1
        assert any(
            keyword.arg == "env"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "child_env"
            for keyword in remote_calls[0].keywords
        )
        for flag, filename in (
            ("--bookmarks-db", "bookmarks.db"),
            ("--users-db", "users.db"),
            ("--events-db", "events.db"),
        ):
            assert (
                scope["daily"][scope["daily"].index(flag) + 1]
                == f"/approved/data/{filename}"
            )
        if returncode == "timeout":
            raise subprocess.TimeoutExpired(command, 810, stderr="PRIVATE")
        if returncode in {"sigterm", "sigint"}:
            import signal

            signum = signal.SIGTERM if returncode == "sigterm" else signal.SIGINT
            handlers[signum](signum, None)
        return subprocess.CompletedProcess(command, returncode)

    monkeypatch.setattr(subprocess, "run", run)
    # Avoid changing test-runner signal handlers while evaluating the workflow.
    monkeypatch.setattr(
        "signal.signal", lambda signum, handler: handlers.__setitem__(signum, handler)
    )
    if returncode:
        with pytest.raises(SystemExit):
            exec(compile(program, "<workflow-fixture>", "exec"), {})
    else:
        exec(compile(program, "<workflow-fixture>", "exec"), {})
    assert len(calls) == 1
    key = Path(calls[0][0][calls[0][0].index("-i") + 1])
    assert not key.exists() and not key.parent.exists()
    assert "DEPLOY_KEY" not in os.environ
    assert unrelated.read_text() == "untouched"
    assert "TRANSPORT_PRIVATE_MARKER" not in capsys.readouterr().out


def test_provider_process_timeout_joins_before_capacity_release(monkeypatch):
    from src import related_paper_wiki

    events = []

    class Connection:
        def poll(self, timeout):
            events.append("poll")
            return False

        def close(self):
            events.append("close")

    class Process:
        alive = True

        def start(self):
            events.append("start")

        def is_alive(self):
            return self.alive

        def terminate(self):
            events.append("terminate")

        def kill(self):
            events.append("kill")
            self.alive = False

        def join(self, timeout=None):
            events.append("join")

    class Context:
        def Pipe(self, duplex):
            return Connection(), Connection()

        def Process(self, **kwargs):
            return Process()

    monkeypatch.setattr(
        related_paper_wiki.multiprocessing, "get_context", lambda mode: Context()
    )
    monkeypatch.setattr(related_paper_wiki.time, "monotonic", lambda: 0)
    assert related_paper_wiki._provider_attempt(PUBLIC_SEEDS[0], 10) == (
        [],
        [{"status": "timeout"}],
    )
    assert events[-4:] == ["terminate", "join", "kill", "join"]
