"""Standalone trust-boundary fixtures; no application, credentials or user data."""

import itertools
import json
import math
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src import recommendation_candidates as candidates
from src.recommendation_candidates import (
    CandidateValidationError,
    TrustedReceiverPolicy,
    load_candidate_snapshot,
    make_candidate_snapshot,
    merge_candidate_pool,
    normalize_candidate,
    write_candidate_snapshot,
)

NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)
PUBLIC = TrustedReceiverPolicy(
    "local_public", "public", "registered", public_source_qualified=True
)
PRIVATE_A = TrustedReceiverPolicy(
    "owner_local", "private", "registered", "incarnation-a"
)
PRIVATE_B = TrustedReceiverPolicy(
    "owner_local", "private", "registered", "incarnation-b"
)
EXTERNAL_A = TrustedReceiverPolicy("openclaw", "private", "external", "incarnation-a")


def snapshot(records, policy=PUBLIC, **kwargs):
    return make_candidate_snapshot(
        records,
        policy=policy,
        source_run_id="run-1",
        collected_at=kwargs.pop("collected_at", NOW),
        now=NOW,
        **kwargs,
    )


def test_allowlist_and_nonfinite_unused_scores_are_not_identity_or_rank():
    base = {
        "title": "A paper",
        "doi": "https://doi.org/10.1234/ABC",
        "authors": [{"name": "Author", "notes": "SECRET"}],
    }
    expected = snapshot([base])
    for score in (1, 5, 100, float("nan"), float("inf"), -math.inf):
        raw = {
            **base,
            "score": score,
            "rank": score,
            "doc_id": "legacy",
            "reason": "SECRET",
            "query": "SECRET",
            "notes": "SECRET",
            "report": "SECRET",
            "profile": "SECRET",
            "feedback": "SECRET",
            "private_attribution": "SECRET",
            "source": "SECRET",
            "user_id": "SECRET",
        }
        actual = snapshot([raw])
        assert actual.checksum == expected.checksum
        assert (
            merge_candidate_pool([actual]).checksum
            == merge_candidate_pool([expected]).checksum
        )
        assert "SECRET" not in json.dumps(actual.records[0].to_paper())
    assert expected.records[0].canonical_key == "doi:10.1234/abc"


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", "x" * 513),
        ("abstract", "x" * 8001),
        ("authors", ["x"] * 21),
        ("authors", ["x" * 129]),
        ("categories", ["x"] * 17),
        ("categories", ["x" * 129]),
        ("url", "https://example.org/" + "x" * 2048),
        ("url", "javascript:alert(1)"),
        ("url", "https://user:secret@example.org/a"),
        ("url", "https://example.org/a?query=SECRET"),
        ("year", float("nan")),
        ("year", True),
        ("year", 0),
        ("publication_date", "2026-02-30"),
        ("publication_date", 2026),
        ("doi", "not-a-doi"),
        ("arxiv_id", "wrong"),
        ("openalex_id", "bad"),
        ("semantic_scholar_id", "bad"),
        ("pmid", "bad"),
        ("title", "\x00bad"),
    ],
)
def test_field_rejections_have_payload_free_counts(field, value):
    result = snapshot([{"title": "Valid", field: value}])
    assert result.status == "empty"
    assert sum(result.rejected_counts.values()) == 1
    assert not result.records


def test_exact_field_bounds():
    record = normalize_candidate(
        {
            "title": "t" * 512,
            "abstract": "a" * 8000,
            "authors": [str(i).zfill(128) for i in range(20)],
            "categories": [str(i) for i in range(16)],
            "url": "https://example.org/" + "x" * (2048 - len("https://example.org/")),
        }
    )
    assert len(record.metadata["authors"]) == 20


@pytest.mark.parametrize("value", [None, [], "text", 42])
def test_nonmapping_record(value):
    assert snapshot([value]).rejected_counts == {"invalid_record": 1}


def test_identity_conservative_and_does_not_use_storage_ids():
    assert normalize_candidate({"title": "Same", "doc_id": "1"}) == normalize_candidate(
        {"title": "Same", "doc_id": "2"}
    )
    pool = merge_candidate_pool(
        [
            snapshot(
                [
                    {"title": "Same", "doi": "10.1234/a"},
                    {"title": "Same", "doi": "10.1234/b"},
                    {"title": "Same", "authors": ["One"]},
                    {"title": "Same", "authors": ["Two"]},
                ]
            )
        ]
    )
    assert len(pool.records) == 4


def test_aliases_only_unambiguous_and_owner_filtered_first():
    arxiv = {"title": "Paper", "arxiv_id": "2401.12345v2"}
    public = snapshot([arxiv, {**arxiv, "doi": "10.1234/a"}])
    assert len(merge_candidate_pool([public]).records) == 1
    private = snapshot([{**arxiv, "doi": "10.1234/b"}], PRIVATE_A)
    assert len(merge_candidate_pool([public, private], public_only=True).records) == 1
    pool = merge_candidate_pool([public, private], account_incarnation="incarnation-a")
    assert len(pool.records) == 3


def test_priority_missing_fill_and_private_projection():
    public = snapshot([{"title": "Public title", "doi": "10.1234/a"}])
    owner = snapshot(
        [{"title": "Owner title", "doi": "10.1234/a", "abstract": "OWNER"}], PRIVATE_A
    )
    external = snapshot(
        [
            {
                "title": "External",
                "doi": "10.1234/a",
                "abstract": "EXTERNAL",
                "venue": "Venue",
            }
        ],
        EXTERNAL_A,
    )
    pool = merge_candidate_pool(
        [external, owner, public], account_incarnation="incarnation-a"
    )
    assert pool.records[0].metadata == {
        "title": "Public title",
        "doi": "10.1234/a",
        "abstract": "OWNER",
        "venue": "Venue",
    }
    assert pool.records[0].sources == ("local_public", "openclaw", "owner_local")
    for kwargs in ({"public_only": True}, {"account_incarnation": "incarnation-b"}, {}):
        projected = merge_candidate_pool([external, owner, public], **kwargs)
        assert projected.records[0].metadata == public.records[0].metadata
        assert projected.records[0].sources == ("local_public",)
        assert projected.rejected_counts == {"owner_filtered": 2}
    assert (
        merge_candidate_pool([owner], account_incarnation="incarnation-b").status
        == "empty"
    )


def test_permutation_and_freshness_tiebreak():
    old = snapshot(
        [{"title": "Old", "doi": "10.1234/a"}], collected_at=NOW - timedelta(hours=1)
    )
    new = snapshot([{"title": "New", "doi": "10.1234/a"}, {"title": "Other"}])
    private = snapshot(
        [{"title": "Private", "doi": "10.1234/a", "venue": "Venue"}], PRIVATE_A
    )
    outcomes = [
        merge_candidate_pool(order, account_incarnation="incarnation-a")
        for order in itertools.permutations([old, new, private])
    ]
    assert all(result == outcomes[0] for result in outcomes)
    assert (
        next(
            r for r in outcomes[0].records if r.canonical_key.startswith("doi:")
        ).metadata["title"]
        == "New"
    )
    assert (
        snapshot([{"title": "A"}, {"title": "B"}]).checksum
        == snapshot([{"title": "B"}, {"title": "A"}]).checksum
    )


@pytest.mark.parametrize(
    "collected,code",
    [
        (NOW + timedelta(microseconds=1), "future_snapshot"),
        (NOW - timedelta(hours=36, microseconds=1), "stale_snapshot"),
        (NOW.replace(tzinfo=None), "invalid_time"),
        ("2026-09-25T09:00:00+09:00", "invalid_time"),
    ],
)
def test_time_boundaries(collected, code):
    with pytest.raises(CandidateValidationError, match=code):
        snapshot([], collected_at=collected)


def test_explicit_stale_corpus_and_empty():
    assert snapshot([], collected_at=NOW - timedelta(hours=36)).status == "empty"
    policy = replace(PUBLIC, allow_stale_public_corpus=True)
    result = snapshot(
        [{"title": "Old corpus"}], policy, collected_at=NOW - timedelta(days=30)
    )
    assert result.degraded and result.status == "degraded"
    with pytest.raises(CandidateValidationError, match="invalid_stale_policy"):
        replace(EXTERNAL_A, allow_stale_public_corpus=True)
    assert snapshot([]).records == ()


def test_source_qualification_and_owner_authority():
    with pytest.raises(CandidateValidationError, match="unqualified_public"):
        TrustedReceiverPolicy("openclaw", "public", "registration")
    with pytest.raises(CandidateValidationError, match="missing_owner"):
        TrustedReceiverPolicy("openclaw", "private", "registration")
    result = snapshot([{"title": "A", "scope": "public", "user_id": "b"}], PRIVATE_A)
    assert result.scope == "private" and result.account_incarnation == "incarnation-a"


@pytest.mark.parametrize("policy,cap", [(PUBLIC, 10000), (PRIVATE_A, 500)])
def test_record_caps(policy, cap):
    assert len(snapshot([{"title": "A"}] * cap, policy).records) == cap
    with pytest.raises(CandidateValidationError, match="record_limit"):
        snapshot([{"title": "A"}] * (cap + 1), policy)


def test_roundtrip_permissions_and_hash(tmp_path):
    root, final = tmp_path / "staging", tmp_path / "final"
    original = snapshot([{"title": "A"}], PRIVATE_A)
    path = write_candidate_snapshot(original, root=root, final_root=final)
    assert (
        path
        == root / "private" / "incarnation-a" / "current-owner_local-registered.json"
    )
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert os.stat(path.parent).st_mode & 0o777 == 0o700
    assert os.stat(path.parent.parent).st_mode & 0o777 == 0o700
    loaded = load_candidate_snapshot(
        path, root=root, final_root=final, policy=PRIVATE_A, now=NOW
    )
    assert loaded == original
    with pytest.raises(CandidateValidationError, match="policy_mismatch"):
        load_candidate_snapshot(
            path, root=root, final_root=final, policy=PRIVATE_B, now=NOW
        )
    raw = json.loads(path.read_text())
    raw["records"][0]["title"] = "tampered"
    path.write_text(json.dumps(raw))
    with pytest.raises(CandidateValidationError, match="checksum_mismatch"):
        load_candidate_snapshot(
            path, root=root, final_root=final, policy=PRIVATE_A, now=NOW
        )


@pytest.mark.parametrize(
    "payload", ["[]", "null", "{", '{"schema":"wrong","records":[]}']
)
def test_malformed_envelope(tmp_path, payload):
    path = tmp_path / "bad.json"
    path.write_text(payload)
    with pytest.raises(CandidateValidationError):
        load_candidate_snapshot(
            path,
            root=tmp_path,
            final_root=tmp_path.parent / "unrelated-final",
            policy=PUBLIC,
            now=NOW,
        )


def test_paths_and_symlinks(tmp_path):
    root, final = tmp_path / "staging", tmp_path / "final"
    root.mkdir()
    final.mkdir()
    for run in ("../escape", "/escape", "a/b", "", "a.json", "a\\nb"):
        with pytest.raises(CandidateValidationError, match="invalid_identifier"):
            make_candidate_snapshot(
                [], policy=PUBLIC, source_run_id=run, collected_at=NOW, now=NOW
            )
    with pytest.raises(CandidateValidationError, match="final_root_overlap"):
        write_candidate_snapshot(snapshot([]), root=final / "staging", final_root=final)
    with pytest.raises(CandidateValidationError, match="unsafe_path"):
        load_candidate_snapshot(
            "../outside", root=root, final_root=final, policy=PUBLIC, now=NOW
        )
    (root / "public").symlink_to(final, target_is_directory=True)
    with pytest.raises(CandidateValidationError, match="unsafe_path"):
        write_candidate_snapshot(snapshot([]), root=root, final_root=final)
    with pytest.raises(CandidateValidationError, match="unsafe_path"):
        load_candidate_snapshot(
            "public/x", root=root, final_root=final, policy=PUBLIC, now=NOW
        )


def test_bounded_read_and_atomic_failure(tmp_path, monkeypatch):
    root, final = tmp_path / "staging", tmp_path / "final"
    original = snapshot([{"title": "Original"}])
    path = write_candidate_snapshot(original, root=root, final_root=final)
    before = path.read_bytes()
    monkeypatch.setattr(candidates, "MAX_BYTES", 32)
    with pytest.raises(CandidateValidationError, match="size_limit"):
        load_candidate_snapshot(
            path, root=root, final_root=final, policy=PUBLIC, now=NOW
        )
    with pytest.raises(CandidateValidationError, match="size_limit"):
        write_candidate_snapshot(original, root=root, final_root=final)
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.tmp"))


def test_failed_replace_cleans_unique_temp(tmp_path, monkeypatch):
    root, final = tmp_path / "staging", tmp_path / "final"
    path = write_candidate_snapshot(
        snapshot([{"title": "Original"}]), root=root, final_root=final
    )
    before = path.read_bytes()

    def fail_replace(*args, **kwargs):
        raise OSError("simulated")

    monkeypatch.setattr(candidates.os, "replace", fail_replace)
    with pytest.raises(OSError):
        write_candidate_snapshot(
            snapshot([{"title": "New"}]), root=root, final_root=final
        )
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.tmp"))


def test_loaded_raw_score_nan_does_not_change_checksum(tmp_path):
    root, final = tmp_path / "staging", tmp_path / "final"
    original = snapshot([{"title": "A"}])
    path = write_candidate_snapshot(original, root=root, final_root=final)
    raw = json.loads(path.read_text())
    raw["records"][0].update(score=float("nan"), reason="PRIVATE", query="PRIVATE")
    path.write_text(json.dumps(raw))
    loaded = load_candidate_snapshot(
        path, root=root, final_root=final, policy=PUBLIC, now=NOW
    )
    assert loaded == original


def test_mutated_snapshot_cannot_merge_or_write(tmp_path):
    altered = snapshot([{"title": "A"}])
    altered.records[0].metadata["title"] = "Tampered"
    assert merge_candidate_pool([altered]).rejected_counts == {"invalid_snapshot": 1}
    with pytest.raises(CandidateValidationError, match="checksum_mismatch"):
        write_candidate_snapshot(
            altered, root=tmp_path / "staging", final_root=tmp_path / "final"
        )


@pytest.mark.parametrize(
    "metadata",
    [
        {"year": 2027},
        {"publication_date": "2026-09-26"},
    ],
)
def test_future_publication_relative_to_frozen_now(metadata):
    result = snapshot([{"title": "Future", **metadata}])
    assert result.status == "empty"
    assert result.rejected_counts == {"future_publication": 1}


def test_publication_cutoff_inclusive_and_canonical_key_only():
    result = snapshot([{"title": "Today", "publication_date": "2026-09-25"}])
    assert result.status == "ready"
    paper = result.records[0].to_paper()
    assert "canonical_key" in paper and "canonical_id" not in paper


def test_merge_does_not_fill_conflicting_publication_year():
    public = snapshot([{"title": "Public", "doi": "10.1234/a", "year": 2025}])
    private = snapshot(
        [{"title": "Private", "doi": "10.1234/a", "publication_date": "2024-01-01"}],
        PRIVATE_A,
    )
    merged = merge_candidate_pool(
        [private, public], account_incarnation="incarnation-a"
    )
    assert merged.records[0].metadata["year"] == 2025
    assert "publication_date" not in merged.records[0].metadata
    matching = snapshot(
        [{"title": "Private", "doi": "10.1234/a", "publication_date": "2025-01-01"}],
        PRIVATE_A,
    )
    merged = merge_candidate_pool(
        [matching, public], account_incarnation="incarnation-a"
    )
    assert merged.records[0].metadata["publication_date"] == "2025-01-01"


@pytest.mark.parametrize("kind", ["fifo", "directory"])
def test_candidate_nonregular_input_rejected_without_blocking(tmp_path, kind):
    path = tmp_path / "input.json"
    if kind == "fifo":
        os.mkfifo(path)
    else:
        path.mkdir()
    with pytest.raises(CandidateValidationError, match="invalid_source_file"):
        load_candidate_snapshot(
            path,
            root=tmp_path,
            final_root=tmp_path.parent / "final",
            policy=PUBLIC,
            now=NOW,
        )


def test_read_stays_on_captured_directory_after_swap(tmp_path, monkeypatch):
    root, final = tmp_path / "staging", tmp_path / "final"
    original = snapshot([{"title": "Original"}])
    path = write_candidate_snapshot(original, root=root, final_root=final)
    captured = path.parent
    moved = captured.with_name("captured")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / path.name).write_text("NOT TRUSTED")
    opener = candidates.open_directory

    def swap(directory, **kwargs):
        fd = opener(directory, **kwargs)
        captured.rename(moved)
        captured.symlink_to(outside, target_is_directory=True)
        return fd

    monkeypatch.setattr(candidates, "open_directory", swap)
    assert (
        load_candidate_snapshot(
            path, root=root, final_root=final, policy=PUBLIC, now=NOW
        )
        == original
    )


@pytest.mark.parametrize("fail", [False, True])
def test_write_and_cleanup_stay_on_captured_directory(tmp_path, monkeypatch, fail):
    root, final = tmp_path / "staging", tmp_path / "final"
    original = snapshot([{"title": "Original"}])
    path = write_candidate_snapshot(original, root=root, final_root=final)
    captured = path.parent
    moved = captured.with_name("captured")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / path.name
    sentinel.write_text("untouched")
    opener = candidates.open_directory

    def swap(directory, **kwargs):
        fd = opener(directory, **kwargs)
        captured.rename(moved)
        captured.symlink_to(outside, target_is_directory=True)
        return fd

    monkeypatch.setattr(candidates, "open_directory", swap)
    if fail:

        def failed_replace(*args, **kwargs):
            raise OSError("injected")

        monkeypatch.setattr(candidates.os, "replace", failed_replace)
        with pytest.raises(OSError):
            write_candidate_snapshot(
                snapshot([{"title": "New"}]), root=root, final_root=final
            )
    else:
        write_candidate_snapshot(
            snapshot([{"title": "New"}]), root=root, final_root=final
        )
        assert (
            json.loads((moved / path.name).read_text())["records"][0]["title"] == "New"
        )
        assert (moved / path.name).stat().st_mode & 0o777 == 0o600
    assert sentinel.read_text() == "untouched"
    assert not list(moved.glob(".candidate-*.tmp"))
    assert not list(outside.glob(".candidate-*.tmp"))


def test_secure_directory_rejects_parent_and_symlink_and_closes_errors(
    tmp_path, monkeypatch
):
    from src.utils import secure_directory

    root = tmp_path / "secure"
    fd = secure_directory.open_directory(root / "nested", create=True)
    os.close(fd)
    assert root.stat().st_mode & 0o777 == 0o700
    assert (root / "nested").stat().st_mode & 0o777 == 0o700
    (root / "link").symlink_to(root / "nested", target_is_directory=True)
    opened, closed = [], []
    real_open, real_close = os.open, os.close

    def tracked_open(*args, **kwargs):
        result = real_open(*args, **kwargs)
        opened.append(result)
        return result

    def tracked_close(fd):
        closed.append(fd)
        return real_close(fd)

    monkeypatch.setattr(secure_directory.os, "open", tracked_open)
    monkeypatch.setattr(secure_directory.os, "close", tracked_close)
    with pytest.raises(OSError):
        secure_directory.open_directory(root / "link")
    assert sorted(opened) == sorted(closed)
    opened.clear()
    with pytest.raises(OSError):
        secure_directory.open_directory(root / ".." / "escape", create=True)
    assert not opened


def test_fifo_swapped_at_leaf_open_is_nonblocking(tmp_path, monkeypatch):
    root, final = tmp_path / "staging", tmp_path / "final"
    path = write_candidate_snapshot(
        snapshot([{"title": "A"}]), root=root, final_root=final
    )
    real_open = os.open

    def swap(name, flags, *args, **kwargs):
        if name == path.name:
            path.unlink()
            os.mkfifo(path)
            assert flags & os.O_NONBLOCK
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(candidates.os, "open", swap)
    with pytest.raises(CandidateValidationError, match="invalid_source_file"):
        load_candidate_snapshot(
            path, root=root, final_root=final, policy=PUBLIC, now=NOW
        )


def test_secure_directory_component_swap_never_follows_replacement(
    tmp_path, monkeypatch
):
    from src.utils import secure_directory

    parent = tmp_path / "parent"
    (parent / "child").mkdir(parents=True)
    moved = tmp_path / "captured"
    outside = tmp_path / "outside"
    (outside / "child").mkdir(parents=True)
    expected = (parent / "child").stat().st_ino
    original = os.open

    def swap(component, flags, *args, **kwargs):
        fd = original(component, flags, *args, **kwargs)
        if component == "parent":
            parent.rename(moved)
            parent.symlink_to(outside, target_is_directory=True)
        return fd

    monkeypatch.setattr(secure_directory.os, "open", swap)
    fd = secure_directory.open_directory(parent / "child")
    try:
        assert os.fstat(fd).st_ino == expected
        assert os.fstat(fd).st_ino != (outside / "child").stat().st_ino
    finally:
        os.close(fd)


def test_current_slot_bounded_history_and_health(tmp_path):
    from src.recommendation_candidates import load_current_candidate_snapshot

    root, final = tmp_path / "staging", tmp_path / "final"
    assert (
        load_current_candidate_snapshot(root, final_root=final, policy=PUBLIC, now=NOW)
        is None
    )
    directory = root / "public" / "local_public"
    directory.mkdir(parents=True)
    for index in range(450):
        (directory / f"historical-{index}.json").write_text("unrelated")
    for index, (health, records, reasons) in enumerate(
        [
            ("ready", [{"title": "A"}], ()),
            ("empty", [], ()),
            ("disabled", [], ("source_disabled",)),
            ("error", [], ("provider_error",)),
            ("degraded", [{"title": "A"}], ("partial_failure",)),
        ]
    ):
        current = make_candidate_snapshot(
            records,
            policy=PUBLIC,
            source_run_id=f"run-{index}",
            collected_at=NOW,
            now=NOW,
            acquisition_status=health,
            acquisition_reasons=reasons,
        )
        path = write_candidate_snapshot(current, root=root, final_root=final)
        assert (
            load_current_candidate_snapshot(
                root, final_root=final, policy=PUBLIC, now=NOW
            )
            == current
        )
    assert len(list(directory.iterdir())) == 451
    assert (directory / "historical-0.json").read_text() == "unrelated"
    raw = json.loads(path.read_text())
    raw["acquisition_reasons"] = ["provider_timeout"]
    path.write_text(json.dumps(raw))
    with pytest.raises(CandidateValidationError, match="checksum_mismatch"):
        load_current_candidate_snapshot(root, final_root=final, policy=PUBLIC, now=NOW)
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(CandidateValidationError, match="invalid_source_file"):
        load_current_candidate_snapshot(root, final_root=final, policy=PUBLIC, now=NOW)
    path.unlink()
    path.symlink_to(directory / "historical-0.json")
    with pytest.raises(CandidateValidationError, match="unsafe_path"):
        load_current_candidate_snapshot(root, final_root=final, policy=PUBLIC, now=NOW)
