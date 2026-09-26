"""Author-only receiver fixtures: local temporary artifacts and fake authority."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from types import SimpleNamespace

import pytest

from scripts.import_openclaw_recommendation_artifact import main
from src import openclaw_recommendations as receiver
from src.openclaw_recommendations import (
    OpenClawArtifactError,
    import_openclaw_artifact,
    load_and_validate_openclaw_raw,
)
from src.recommendation_candidates import TrustedReceiverPolicy

NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)
PUBLIC = TrustedReceiverPolicy(
    "openclaw", "public", "registered", public_source_qualified=True
)
PRIVATE = TrustedReceiverPolicy("openclaw", "private", "registered", "inc-a")


class Authority:
    def __init__(self, *, deleted=False):
        self.deleted = deleted
        self.calls = []
        self.inside = False

    def validate_principal(self, username, incarnation):
        assert not self.inside
        self.calls.append("validate")
        if (username, incarnation) != ("alice", "inc-a"):
            raise ValueError("PRIVATE")
        return {"account_incarnation": incarnation}

    @contextmanager
    def account_guard(self, username, incarnation):
        self.calls.append("guard")
        if self.deleted:
            raise ValueError("PRIVATE deleted")
        self.inside = True
        try:
            yield {"account_incarnation": incarnation}
        finally:
            self.inside = False


def raw(score=1):
    return {
        "user_id": "forged-b",
        "scope": "public",
        "query": "PRIVATE",
        "variants": {
            "PRIVATE interest": [
                {
                    "title": "Paper",
                    "doi": "10.1234/a",
                    "score": score,
                    "reason": "PRIVATE",
                }
            ]
        },
    }


def stage(tmp_path, payload=None, **kwargs):
    source = tmp_path / "raw.json"
    source.write_text(json.dumps(raw() if payload is None else payload))
    return import_openclaw_artifact(
        source,
        candidate_root=tmp_path / "candidates",
        final_root=tmp_path / "serving",
        policy=kwargs.pop("policy", PUBLIC),
        source_run_id="run-1",
        collected_at=NOW,
        now=NOW,
        **kwargs,
    )


def test_candidate_only_sanitized_staging_preserves_source(tmp_path):
    result = stage(tmp_path)
    assert not (tmp_path / "serving").exists()
    assert (tmp_path / "raw.json").exists()
    assert (
        result.destination_path
        == tmp_path / "candidates/public/openclaw/current-openclaw-registered.json"
    )
    assert result.snapshot.source_run_id == "run-1"
    assert "PRIVATE" not in result.destination_path.read_text()
    assert "forged-b" not in result.destination_path.read_text()
    assert result.snapshot.records[0].canonical_key == "doi:10.1234/a"
    assert result.as_dict()["code"] == "candidate_staged"
    assert "destination_path" not in result.as_dict()


def test_private_json_cannot_select_owner_and_guard_wraps_write(tmp_path, monkeypatch):
    db = Authority()
    original = receiver.write_candidate_snapshot

    def guarded(*args, **kwargs):
        assert db.inside
        return original(*args, **kwargs)

    monkeypatch.setattr(receiver, "write_candidate_snapshot", guarded)
    result = stage(tmp_path, policy=PRIVATE, username="alice", user_db=db)
    assert result.snapshot.account_incarnation == "inc-a"
    assert result.snapshot.scope == "private"
    assert db.calls == ["validate", "guard"]


@pytest.mark.parametrize("username,deleted", [("bob", False), ("alice", True)])
def test_wrong_owner_and_delete_between_validation_and_commit(
    tmp_path, username, deleted
):
    with pytest.raises(OpenClawArtifactError, match="principal_rejected") as exc:
        stage(
            tmp_path,
            policy=PRIVATE,
            username=username,
            user_db=Authority(deleted=deleted),
        )
    assert "PRIVATE" not in str(exc.value)
    assert not (tmp_path / "candidates").exists()
    assert not (tmp_path / "serving").exists()


def test_private_requires_authority(tmp_path):
    with pytest.raises(OpenClawArtifactError, match="principal_required"):
        stage(tmp_path, policy=PRIVATE)


def test_source_disabled(tmp_path):
    policy = TrustedReceiverPolicy(
        "local_public", "public", "registered", public_source_qualified=True
    )
    with pytest.raises(OpenClawArtifactError, match="source_disabled"):
        stage(tmp_path, policy=policy)


@pytest.mark.parametrize(
    "payload,code",
    [
        ([], "invalid_root"),
        ({}, "variant_limit"),
        ({"variants": {}}, "variant_limit"),
        ({"variants": {str(i): [] for i in range(17)}}, "variant_limit"),
        ({"variants": {"x": {}}}, "invalid_variant"),
        ({"variants": {"": []}}, "invalid_variant"),
        ({"variants": {"x": [None]}}, "invalid_record"),
        ({"variants": {"x": [{"title": "A"}] * 10001}}, "record_limit"),
    ],
)
def test_malformed_variants(tmp_path, payload, code):
    with pytest.raises(OpenClawArtifactError, match=code):
        stage(tmp_path, payload)
    assert not (tmp_path / "serving").exists()


def test_private_aggregate_cap_across_variants(tmp_path):
    payload = {
        "variants": {"one": [{"title": "A"}] * 251, "two": [{"title": "B"}] * 250}
    }
    with pytest.raises(OpenClawArtifactError, match="record_limit"):
        stage(tmp_path, payload, policy=PRIVATE, username="alice", user_db=Authority())


def test_external_score_nan_invariance(tmp_path):
    baseline = stage(tmp_path).snapshot.checksum
    for score in (100, -1, float("nan"), float("inf")):
        assert stage(tmp_path, raw(score)).snapshot.checksum == baseline


def test_size_limit_before_parse_and_observed_stream_growth(tmp_path, monkeypatch):
    source = tmp_path / "raw.json"
    source.write_bytes(b"x" * 129)
    monkeypatch.setattr(receiver, "MAX_BYTES", 128)
    with pytest.raises(OpenClawArtifactError, match="size_limit"):
        load_and_validate_openclaw_raw(source, policy=PUBLIC)
    # Simulate a file growing after its initial stat; observed bytes remain bounded.
    monkeypatch.setattr(
        receiver.os, "fstat", lambda fd: SimpleNamespace(st_mode=0o100600, st_size=1)
    )
    with pytest.raises(OpenClawArtifactError, match="size_limit"):
        load_and_validate_openclaw_raw(source, policy=PUBLIC)


def test_symlink_input_and_destination_rejected(tmp_path):
    original = tmp_path / "original.json"
    original.write_text(json.dumps(raw()))
    link = tmp_path / "link.json"
    link.symlink_to(original)
    with pytest.raises(OpenClawArtifactError, match="unsafe_path"):
        load_and_validate_openclaw_raw(link, policy=PUBLIC)
    (tmp_path / "candidates").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "candidates/public").symlink_to(
        tmp_path / "elsewhere", target_is_directory=True
    )
    with pytest.raises(OpenClawArtifactError, match="unsafe_path"):
        stage(tmp_path)


def test_deadline_before_read_and_after_read(tmp_path):
    source = tmp_path / "raw.json"
    source.write_text(json.dumps(raw()))
    with pytest.raises(OpenClawArtifactError, match="deadline_exceeded"):
        load_and_validate_openclaw_raw(
            source, policy=PUBLIC, deadline=1, clock=lambda: 1
        )
    ticks = iter([0, 0, 2])
    with pytest.raises(OpenClawArtifactError, match="deadline_exceeded"):
        load_and_validate_openclaw_raw(
            source, policy=PUBLIC, deadline=1, clock=lambda: next(ticks)
        )


def test_atomic_failure_cleans_temp_no_final_write(tmp_path, monkeypatch):
    from src import recommendation_candidates

    def fail(*args, **kwargs):
        raise OSError("PRIVATE path")

    monkeypatch.setattr(recommendation_candidates.os, "replace", fail)
    with pytest.raises(OpenClawArtifactError, match="staging_failed") as exc:
        stage(tmp_path)
    assert "PRIVATE" not in str(exc.value)
    assert not list((tmp_path / "candidates").rglob("*.tmp"))
    assert not (tmp_path / "serving").exists()
    assert (tmp_path / "raw.json").exists()


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["PRIVATE", "--artifacts-dir", "PRIVATE"],
        ["PRIVATE", "--skip-existing"],
        ["PRIVATE", "--source", "unknown"],
    ],
)
def test_cli_invalid_arguments_never_echo_payload(args, capsys):
    assert main(args) == 2
    assert json.loads(capsys.readouterr().err) == {"code": "invalid_arguments"}


def cli_args(tmp_path):
    return [
        str(tmp_path / "raw.json"),
        "--candidate-root",
        str(tmp_path / "candidates"),
        "--final-root",
        str(tmp_path / "serving"),
        "--source",
        "openclaw",
        "--scope",
        "public",
        "--provenance-id",
        "registered",
        "--source-run-id",
        "run-1",
        "--collected-at",
        NOW.isoformat(),
    ]


def test_cli_unqualified_source_disabled(tmp_path, capsys):
    assert main(cli_args(tmp_path)) == 2
    assert json.loads(capsys.readouterr().err) == {"code": "source_disabled"}


@pytest.mark.parametrize("budget", ["nan", "inf", "-1", "0"])
def test_cli_invalid_budget(tmp_path, capsys, budget):
    assert (
        main(cli_args(tmp_path) + ["--source-qualified", "--budget-seconds", budget])
        == 2
    )
    assert json.loads(capsys.readouterr().err) == {"code": "invalid_budget"}


@pytest.mark.parametrize("kind", ["fifo", "directory"])
def test_raw_nonregular_input_is_rejected(tmp_path, kind):
    path = tmp_path / "raw.json"
    if kind == "fifo":
        os.mkfifo(path)
    else:
        path.mkdir()
    with pytest.raises(OpenClawArtifactError, match="invalid_source_file"):
        load_and_validate_openclaw_raw(path, policy=PUBLIC)


def test_raw_read_uses_captured_directory_after_ancestor_swap(tmp_path, monkeypatch):
    parent = tmp_path / "source"
    parent.mkdir()
    path = parent / "raw.json"
    path.write_text(json.dumps(raw()))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / path.name).write_text("PRIVATE invalid")
    original = receiver.open_directory

    def swap(directory, **kwargs):
        fd = original(directory, **kwargs)
        parent.rename(tmp_path / "captured")
        parent.symlink_to(outside, target_is_directory=True)
        return fd

    monkeypatch.setattr(receiver, "open_directory", swap)
    records, variants, observed = load_and_validate_openclaw_raw(path, policy=PUBLIC)
    assert records[0]["title"] == "Paper"
    assert variants == 1 and observed > 0


def test_raw_fifo_leaf_swap_uses_nonblocking_open(tmp_path, monkeypatch):
    path = tmp_path / "raw.json"
    path.write_text(json.dumps(raw()))
    original = os.open

    def swap(name, flags, *args, **kwargs):
        if name == path.name:
            path.unlink()
            os.mkfifo(path)
            assert flags & os.O_NONBLOCK
        return original(name, flags, *args, **kwargs)

    monkeypatch.setattr(receiver.os, "open", swap)
    with pytest.raises(OpenClawArtifactError, match="invalid_source_file"):
        load_and_validate_openclaw_raw(path, policy=PUBLIC)
