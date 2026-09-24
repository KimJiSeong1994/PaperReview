from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.search_eval.release_holdout import (
    APPROVAL_AGGREGATE_AUTHORITY,
    PartialHoldoutExposureError,
    RELEASE_HOLDOUT_AUTHORITY,
    RELEASE_HOLDOUT_AUTHORITY_CONTEXT_ENV,
    RELEASE_HOLDOUT_MANIFEST_VERSION,
    ReleaseHoldoutAggregate,
    ReleaseHoldoutAttemptError,
    ValidatedReleaseHoldoutEvaluation,
    evaluate_release_holdout,
    load_release_holdout_manifest,
    load_validated_release_holdout_evaluation,
    seal_release_holdout_manifest,
    write_release_holdout_manifest,
)
from src.search_eval.skillopt_contract import ValidationError
from src.search_eval.skillopt_run_contract import canonical_json_bytes, canonical_value_hash
from tests.fixtures.release_holdout_authority import release_manifest_payload


BASELINE = "sha256:" + "1" * 64
CANDIDATE = "sha256:" + "2" * 64
THRESHOLDS = {"ndcg_delta": 0.01, "safety": 1.0}


def _manifest(tmp_path: Path, generation: str = "holdout:generation-1"):
    return write_release_holdout_manifest(
        tmp_path / f"{generation.replace(':', '-')}.json",
        release_manifest_payload(
            tmp_path,
            generation_id=generation,
            object_version="immutable-object:v1",
            issuer_identity="holdout-authority:v1",
            evaluator_identity="release-evaluator:v1",
        ),
    )


def _selection(baseline: str = BASELINE, candidate: str = CANDIDATE):
    return {
        "status": "passed",
        "baseline_eval_hash": baseline,
        "candidate_eval_hash": candidate,
        "evidence_hash": "sha256:" + "b" * 64,
    }


def _kwargs(tmp_path: Path, manifest, evaluator, **overrides):
    values = {
        "manifest": manifest,
        "state_root": tmp_path / "state",
        "baseline_sha256": BASELINE,
        "candidate_sha256": CANDIDATE,
        "thresholds": THRESHOLDS,
        "evaluator_identity": "release-evaluator:v1",
        "contract_identity": "retrieval-eval:v1",
        "nonce": "one-shot-nonce-1",
        "selection_evidence": _selection(),
        "evaluator": evaluator,
    }
    values.update(overrides)
    return values


def _accepted(_manifest):
    return ReleaseHoldoutAggregate(
        sample_count=12,
        metrics={"ndcg_delta": 0.02, "safety": 1.0},
        threshold_results={"ndcg_delta": True, "safety": True},
    )


def _generation_root(state_root: Path, manifest) -> Path:
    generations = list((state_root / "generations").iterdir())
    assert len(generations) == 1
    return generations[0]


def _holdout_object_path(manifest) -> Path:
    context = manifest.authority_context
    receipt = manifest["immutable_store_receipt"]
    return context.store_root / context.namespace / receipt["object_key"]


def _rewrite_canonical(path: Path, mutate) -> None:
    value = json.loads(path.read_text())
    mutate(value)
    if path.name == "journal.json":
        unsigned = dict(value)
        unsigned.pop("journal_hash", None)
        from src.search_eval.skillopt_run_contract import canonical_value_hash

        value["journal_hash"] = canonical_value_hash(unsigned)
    path.write_bytes(canonical_json_bytes(value))


def test_manifest_is_exact_sealed_external_authority(tmp_path: Path):
    manifest = _manifest(tmp_path)
    assert manifest["authority_classification"] == RELEASE_HOLDOUT_AUTHORITY
    assert manifest.manifest_hash.startswith("sha256:")
    assert load_release_holdout_manifest(manifest.manifest_path).manifest_hash == manifest.manifest_hash

    raw = manifest.persisted_manifest()
    raw["extra"] = True
    with pytest.raises(ValidationError, match="schema mismatch"):
        seal_release_holdout_manifest({k: v for k, v in raw.items() if k != "manifest_hash"})


def test_caller_cannot_self_mint_manifest_issuer_or_store(tmp_path: Path):
    payload = release_manifest_payload(
        tmp_path,
        generation_id="holdout:self-mint",
        object_version="immutable-object:v1",
        issuer_identity="holdout-authority:v1",
        evaluator_identity="release-evaluator:v1",
    )
    payload["issuer_identity"] = "attacker:v1"
    with pytest.raises(ValidationError, match="issuer is not authorized"):
        seal_release_holdout_manifest(payload)

    payload = release_manifest_payload(
        tmp_path,
        generation_id="holdout:wrong-store",
        object_version="immutable-object:v1",
        issuer_identity="holdout-authority:v1",
        evaluator_identity="release-evaluator:v1",
    )
    receipt = dict(payload["immutable_store_receipt"])
    receipt["store_id"] = "attacker-store:v1"
    receipt.pop("receipt_hash")
    receipt["receipt_hash"] = canonical_value_hash(receipt)
    payload["immutable_store_receipt"] = receipt
    with pytest.raises(ValidationError, match="store receipt store_id mismatch"):
        seal_release_holdout_manifest(payload)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("namespace", "attacker-namespace", "namespace mismatch"),
        ("object_version", "attacker-version:v9", "object_version mismatch"),
        ("retention_mode", "mutable", "retention_mode mismatch"),
        ("acl_receipt_hash", "sha256:" + "9" * 64, "acl_receipt_hash mismatch"),
        ("receipt_issuer_identity", "attacker-receipt:v1", "receipt_issuer_identity mismatch"),
    ),
)
def test_manifest_receipt_must_match_deployment_authority_exactly(
    tmp_path: Path, field: str, replacement: str, message: str
) -> None:
    payload = release_manifest_payload(
        tmp_path,
        generation_id=f"holdout:wrong-{field}",
        object_version="immutable-object:v1",
        issuer_identity="holdout-authority:v1",
        evaluator_identity="release-evaluator:v1",
    )
    receipt = dict(payload["immutable_store_receipt"])
    receipt[field] = replacement
    receipt.pop("receipt_hash")
    receipt["receipt_hash"] = canonical_value_hash(receipt)
    payload["immutable_store_receipt"] = receipt
    with pytest.raises(ValidationError, match=message):
        seal_release_holdout_manifest(payload)


def test_manifest_rejects_wrong_context_hash_and_verifier(tmp_path: Path):
    payload = release_manifest_payload(
        tmp_path,
        generation_id="holdout:wrong-context",
        object_version="immutable-object:v1",
        issuer_identity="holdout-authority:v1",
        evaluator_identity="release-evaluator:v1",
    )
    payload["authority_context_hash"] = "sha256:" + "9" * 64
    with pytest.raises(ValidationError, match="authority context mismatch"):
        seal_release_holdout_manifest(payload)
    payload = release_manifest_payload(
        tmp_path,
        generation_id="holdout:wrong-verifier",
        object_version="immutable-object:v1",
        issuer_identity="holdout-authority:v1",
        evaluator_identity="release-evaluator:v1",
    )
    payload["verifier_identity"] = "attacker-verifier:v1"
    with pytest.raises(ValidationError, match="verifier is not authorized"):
        seal_release_holdout_manifest(payload)


def test_expired_or_rotated_authority_context_invalidates_capability(tmp_path: Path):
    manifest = _manifest(tmp_path)
    evaluation = evaluate_release_holdout(**_kwargs(tmp_path, manifest, _accepted))
    reference = evaluation.capability_reference()
    context_path = Path(os.environ[RELEASE_HOLDOUT_AUTHORITY_CONTEXT_ENV])
    context = json.loads(context_path.read_bytes())
    context["expires_at"] = "2021-01-01T00:00:00Z"
    context.pop("context_hash")
    context["context_hash"] = canonical_value_hash(context)
    context_path.write_bytes(canonical_json_bytes(context))
    with pytest.raises(ValidationError, match="not currently valid|rotated"):
        load_validated_release_holdout_evaluation(reference)


def test_authority_rotation_during_evaluation_quarantines_generation(tmp_path: Path):
    manifest = _manifest(tmp_path)
    context_path = Path(os.environ[RELEASE_HOLDOUT_AUTHORITY_CONTEXT_ENV])

    def rotate(_manifest):
        context = json.loads(context_path.read_bytes())
        context["allowed_manifest_issuers"].append("rotated-authority:v1")
        context.pop("context_hash")
        context["context_hash"] = canonical_value_hash(context)
        context_path.write_bytes(canonical_json_bytes(context))
        return _accepted(_manifest)

    with pytest.raises(ReleaseHoldoutAttemptError, match="authority rotated"):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, rotate))
    root = _generation_root(tmp_path / "state", manifest)
    status = json.loads((root / "status.json").read_bytes())
    assert status["state"] == "quarantined"
    assert status["reason"] == "authority_context_rotated"


def test_persisted_capability_requires_narrow_reference_and_revalidates_store(tmp_path: Path):
    manifest = _manifest(tmp_path)
    evaluation = evaluate_release_holdout(**_kwargs(tmp_path, manifest, _accepted))
    with pytest.raises(ValidationError, match="reference schema"):
        load_validated_release_holdout_evaluation(evaluation.record_path)  # type: ignore[arg-type]
    loaded = load_validated_release_holdout_evaluation(evaluation.capability_reference())
    assert loaded.evaluation_hash == evaluation.evaluation_hash
    _holdout_object_path(manifest).write_bytes(b"tampered")
    with pytest.raises(ValidationError, match="exact bytes mismatch"):
        load_validated_release_holdout_evaluation(evaluation.capability_reference())


def test_persisted_capability_rejects_relocation_and_full_journal_rewrite(tmp_path: Path):
    manifest = _manifest(tmp_path)
    evaluation = evaluate_release_holdout(**_kwargs(tmp_path, manifest, _accepted))
    reference = evaluation.capability_reference()
    relocated = dict(reference)
    relocated["record_path"] = str(tmp_path / "relocated.json")
    with pytest.raises(ValidationError, match="not canonical"):
        load_validated_release_holdout_evaluation(relocated)
    root = evaluation.record_path.parent
    _rewrite_canonical(
        root / "journal.json",
        lambda value: value["events"][0].update(reason="attacker_recommitted"),
    )
    with pytest.raises(ValidationError, match="precommit event mismatch"):
        load_validated_release_holdout_evaluation(reference)


def test_precommit_is_committed_before_holdout_read_and_terminal_is_aggregate_only(tmp_path: Path):
    manifest = _manifest(tmp_path)
    reads = 0

    def evaluator(_manifest):
        nonlocal reads
        reads += 1
        root = _generation_root(tmp_path / "state", manifest)
        precommit = json.loads((root / "precommit.json").read_text())
        assert precommit["baseline_sha256"] == BASELINE
        assert precommit["candidate_sha256"] == CANDIDATE
        assert precommit["nonce"] == "one-shot-nonce-1"
        assert precommit["selection_evidence"]["status"] == "passed"
        return _accepted(_manifest)

    result = evaluate_release_holdout(**_kwargs(tmp_path, manifest, evaluator))
    assert isinstance(result, ValidatedReleaseHoldoutEvaluation)
    assert result["outcome"] == "accepted"
    assert result["authority_classification"] == APPROVAL_AGGREGATE_AUTHORITY
    assert reads == 1
    persisted = result.record_path.read_text()
    for forbidden in ("query_id", "labels", "per_query", "holdout_path", "private_detail"):
        assert forbidden not in persisted


def test_evaluator_reads_validated_bytes_during_object_aba_replace_and_restore(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    object_path = _holdout_object_path(manifest)
    original = object_path.read_bytes()
    observed: list[bytes] = []

    def evaluator(capability):
        object_path.replace(object_path.with_suffix(".original"))
        object_path.write_bytes(b'{"private":"attacker-substitute"}\n')
        try:
            observed.append(capability.read_holdout_bytes())
        finally:
            object_path.unlink()
            object_path.with_suffix(".original").replace(object_path)
        return _accepted(capability)

    result = evaluate_release_holdout(**_kwargs(tmp_path, manifest, evaluator))

    assert result["outcome"] == "accepted"
    assert observed == [original]


def test_persistent_object_replacement_during_evaluation_is_quarantined(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    object_path = _holdout_object_path(manifest)

    def evaluator(capability):
        assert capability.read_holdout_bytes() != b"attacker-substitute"
        object_path.write_bytes(b"attacker-substitute")
        return _accepted(capability)

    with pytest.raises(ReleaseHoldoutAttemptError, match="rotated during evaluation"):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, evaluator))

    root = _generation_root(tmp_path / "state", manifest)
    status = json.loads((root / "status.json").read_text())
    assert status["state"] == "quarantined"
    assert status["incident_hash"].startswith("sha256:")


def test_same_exact_pair_replays_without_holdout_reread(tmp_path: Path):
    manifest = _manifest(tmp_path)
    calls = 0

    def evaluator(value):
        nonlocal calls
        calls += 1
        return _accepted(value)

    first = evaluate_release_holdout(**_kwargs(tmp_path, manifest, evaluator))
    second = evaluate_release_holdout(**_kwargs(tmp_path, manifest, evaluator))
    assert first.evaluation_hash == second.evaluation_hash
    assert second.replayed is True
    assert calls == 1


@pytest.mark.parametrize(
    "tamper",
    (
        "status_evaluation_hash",
        "status_reason",
        "status_incident_hash",
        "journal_terminal_reason",
    ),
)
def test_canonical_terminal_semantic_tampering_quarantines_instead_of_replay(
    tmp_path: Path, tamper: str
):
    manifest = _manifest(tmp_path)
    calls = 0

    def evaluator(value):
        nonlocal calls
        calls += 1
        return _accepted(value)

    evaluate_release_holdout(**_kwargs(tmp_path, manifest, evaluator))
    root = _generation_root(tmp_path / "state", manifest)
    if tamper == "status_evaluation_hash":
        _rewrite_canonical(root / "status.json", lambda value: value.update(evaluation_hash="sha256:" + "f" * 64))
    elif tamper == "status_reason":
        _rewrite_canonical(root / "status.json", lambda value: value.update(reason="rejected"))
    elif tamper == "status_incident_hash":
        _rewrite_canonical(root / "status.json", lambda value: value.update(incident_hash="sha256:" + "e" * 64))
    else:
        _rewrite_canonical(root / "journal.json", lambda value: value["events"][-1].update(reason="rejected"))

    with pytest.raises(ReleaseHoldoutAttemptError, match="corrupt"):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, evaluator))
    assert calls == 1
    status = json.loads((root / "status.json").read_text())
    assert status["state"] == "quarantined"
    assert status["incident_hash"].startswith("sha256:")


def test_concurrent_duplicate_is_exactly_once(tmp_path: Path):
    manifest = _manifest(tmp_path)
    calls = 0
    guard = threading.Lock()

    def evaluator(value):
        nonlocal calls
        with guard:
            calls += 1
        return _accepted(value)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: evaluate_release_holdout(**_kwargs(tmp_path, manifest, evaluator)),
                range(8),
            )
        )
    assert calls == 1
    assert len({result.evaluation_hash for result in results}) == 1
    assert sum(result.replayed for result in results) == 7


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"candidate_sha256": "sha256:" + "3" * 64, "selection_evidence": _selection(candidate="sha256:" + "3" * 64)}, "different request"),
        ({"nonce": "another-nonce"}, "different request"),
        ({"thresholds": {"ndcg_delta": 0.02, "safety": 1.0}}, "different request"),
    ),
)
def test_different_pair_nonce_or_request_emits_incident_and_invalidates_evidence(tmp_path: Path, override, message):
    manifest = _manifest(tmp_path)
    evaluate_release_holdout(**_kwargs(tmp_path, manifest, _accepted))
    with pytest.raises(ReleaseHoldoutAttemptError, match=message):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, _accepted, **override))
    root = _generation_root(tmp_path / "state", manifest)
    status = json.loads((root / "status.json").read_text())
    assert status["state"] == "quarantined"
    incident = json.loads(next((root / "incidents").iterdir()).read_text())
    assert incident["evidence_valid"] is False
    assert incident["rotation_required"] is True
    with pytest.raises(ReleaseHoldoutAttemptError, match="quarantined"):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, _accepted))


@pytest.mark.parametrize(
    ("error", "reason"),
    (
        (TimeoutError("slow"), "timeout"),
        (RuntimeError("provider"), "evaluation_error"),
        (PartialHoldoutExposureError("partial"), "partial_exposure"),
    ),
)
def test_every_failed_or_partial_attempt_quarantines_and_cannot_rerun(tmp_path: Path, error, reason):
    manifest = _manifest(tmp_path)
    calls = 0

    def evaluator(_manifest):
        nonlocal calls
        calls += 1
        raise error

    with pytest.raises(ReleaseHoldoutAttemptError):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, evaluator))
    root = _generation_root(tmp_path / "state", manifest)
    status = json.loads((root / "status.json").read_text())
    assert status["state"] == "quarantined"
    assert status["reason"] == reason
    with pytest.raises(ReleaseHoldoutAttemptError, match="quarantined"):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, evaluator))
    assert calls == 1


def test_cancelled_attempt_quarantines_and_spends_generation(tmp_path: Path):
    manifest = _manifest(tmp_path)

    def cancelled(_manifest):
        raise asyncio.CancelledError

    with pytest.raises(ReleaseHoldoutAttemptError, match="cancelled"):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, cancelled))
    root = _generation_root(tmp_path / "state", manifest)
    assert json.loads((root / "status.json").read_text())["state"] == "quarantined"


def test_process_interruption_after_precommit_is_quarantined_on_resume(tmp_path: Path):
    manifest = _manifest(tmp_path)
    reads = 0

    def interrupted(_manifest):
        nonlocal reads
        reads += 1
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, interrupted))
    root = _generation_root(tmp_path / "state", manifest)
    terminal = json.loads((root / "status.json").read_text())
    assert terminal["state"] == "quarantined"
    assert terminal["reason"] == "process_termination"
    with pytest.raises(ReleaseHoldoutAttemptError, match="quarantined"):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, interrupted))
    assert reads == 1
    assert json.loads((root / "status.json").read_text())["state"] == "quarantined"


def test_system_exit_is_terminalized_before_reraise(tmp_path: Path):
    manifest = _manifest(tmp_path)

    def stopped(_manifest):
        raise SystemExit(9)

    with pytest.raises(SystemExit):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, stopped))
    root = _generation_root(tmp_path / "state", manifest)
    terminal = json.loads((root / "status.json").read_text())
    assert terminal["state"] == "quarantined"
    assert terminal["reason"] == "process_termination"


def test_uncatchable_termination_recovery_quarantines_without_second_read(tmp_path: Path):
    class SimulatedHardKill(BaseException):
        pass

    manifest = _manifest(tmp_path)
    reads = 0

    def killed(_manifest):
        nonlocal reads
        reads += 1
        raise SimulatedHardKill

    with pytest.raises(SimulatedHardKill):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, killed))
    root = _generation_root(tmp_path / "state", manifest)
    assert json.loads((root / "status.json").read_text())["state"] == "precommitted"
    with pytest.raises(ReleaseHoldoutAttemptError, match="interrupted"):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, killed))
    assert reads == 1
    assert json.loads((root / "status.json").read_text())["state"] == "quarantined"


def test_rejection_spends_generation_and_replays_aggregate(tmp_path: Path):
    manifest = _manifest(tmp_path)
    calls = 0

    def rejected(_manifest):
        nonlocal calls
        calls += 1
        return ReleaseHoldoutAggregate(
            sample_count=10,
            metrics={"ndcg_delta": 0.0, "safety": 1.0},
            threshold_results={"ndcg_delta": False, "safety": True},
        )

    first = evaluate_release_holdout(**_kwargs(tmp_path, manifest, rejected))
    second = evaluate_release_holdout(**_kwargs(tmp_path, manifest, rejected))
    assert first["outcome"] == "rejected"
    assert second.replayed is True
    assert calls == 1


@pytest.mark.parametrize("filename", ("precommit.json", "status.json", "journal.json", "evaluation.json", "consumption.json"))
def test_torn_or_corrupt_state_fails_closed_and_quarantines(tmp_path: Path, filename: str):
    manifest = _manifest(tmp_path)
    evaluate_release_holdout(**_kwargs(tmp_path, manifest, _accepted))
    root = _generation_root(tmp_path / "state", manifest)
    (root / filename).write_bytes(b"{torn")

    with pytest.raises(ReleaseHoldoutAttemptError, match="corrupt"):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, _accepted))
    status = json.loads((root / "status.json").read_text())
    assert status["state"] == "quarantined"
    assert status["reason"] == "corrupt_or_torn_generation_state"


def test_raw_mapping_and_private_detail_are_rejected_then_generation_quarantines(tmp_path: Path):
    manifest = _manifest(tmp_path)

    def unsafe(_manifest):
        return {"metrics": {}, "per_query": [{"query_id": "secret"}]}

    with pytest.raises(ReleaseHoldoutAttemptError, match="failed"):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, unsafe))
    root = _generation_root(tmp_path / "state", manifest)
    assert "secret" not in "".join(path.read_text() for path in root.rglob("*.json"))


def test_selection_failure_reads_holdout_zero_times(tmp_path: Path):
    manifest = _manifest(tmp_path)
    calls = 0

    def evaluator(value):
        nonlocal calls
        calls += 1
        return _accepted(value)

    with pytest.raises(ValidationError, match="passed selection"):
        evaluate_release_holdout(
            **_kwargs(
                tmp_path,
                manifest,
                evaluator,
                selection_evidence={**_selection(), "status": "failed"},
            )
        )
    assert calls == 0
    assert not (tmp_path / "state").exists()


def test_manifest_must_be_canonical_and_cannot_be_symlinked(tmp_path: Path):
    manifest = _manifest(tmp_path)
    raw = manifest.persisted_manifest()
    raw["holdout_size_bytes"] = 8
    manifest.manifest_path.write_bytes(canonical_json_bytes(raw))
    with pytest.raises(ValidationError, match="hash mismatch"):
        load_release_holdout_manifest(manifest.manifest_path)

    target = tmp_path / "target.json"
    target.write_bytes(canonical_json_bytes(manifest.persisted_manifest()))
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValidationError, match="symlink"):
        load_release_holdout_manifest(link)


def test_symlinked_state_root_cannot_escape_or_touch_outside(tmp_path: Path):
    manifest = _manifest(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("unchanged")
    state_link = tmp_path / "state-link"
    state_link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValidationError, match="must not be a symlink"):
        evaluate_release_holdout(**_kwargs(tmp_path, manifest, _accepted, state_root=state_link))
    assert sentinel.read_text() == "unchanged"
    assert sorted(path.name for path in outside.iterdir()) == ["sentinel"]


def test_symlinked_intermediate_parent_cannot_escape(tmp_path: Path):
    manifest = _manifest(tmp_path)
    outside = tmp_path / "outside-parent"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("unchanged")
    middle = tmp_path / "middle"
    middle.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValidationError, match="unsafe intermediate"):
        evaluate_release_holdout(
            **_kwargs(tmp_path, manifest, _accepted, state_root=middle / "state")
        )
    assert sentinel.read_text() == "unchanged"
    assert sorted(path.name for path in outside.iterdir()) == ["sentinel"]


def test_precreated_generation_directory_symlink_is_rejected(tmp_path: Path):
    manifest = _manifest(tmp_path)
    state = tmp_path / "state"
    generations = state / "generations"
    generations.mkdir(parents=True)
    outside = tmp_path / "outside-generation"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("unchanged")
    generation_key = hashlib.sha256(str(manifest["generation_id"]).encode()).hexdigest()
    (generations / generation_key).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValidationError, match="state directory is unsafe"):
        evaluate_release_holdout(
            **_kwargs(tmp_path, manifest, _accepted, state_root=state)
        )
    assert sentinel.read_text() == "unchanged"
    assert sorted(path.name for path in outside.iterdir()) == ["sentinel"]


def test_generation_directory_rotation_and_aba_is_detected_before_terminal_write(tmp_path: Path):
    manifest = _manifest(tmp_path)
    state = tmp_path / "state"
    outside = tmp_path / "outside-aba"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("unchanged")

    def rotate(_manifest):
        root = _generation_root(state, manifest)
        rotated = root.with_name(root.name + ".rotated")
        root.rename(rotated)
        root.symlink_to(outside, target_is_directory=True)
        return _accepted(_manifest)

    with pytest.raises(ValidationError, match="(replaced|type drifted) during transaction"):
        evaluate_release_holdout(
            **_kwargs(tmp_path, manifest, rotate, state_root=state)
        )
    assert sentinel.read_text() == "unchanged"
    assert sorted(path.name for path in outside.iterdir()) == ["sentinel"]
    rotated = next((state / "generations").glob("*.rotated"))
    assert not (rotated / "evaluation.json").exists()


def test_intermediate_parent_rotation_aba_is_detected_without_outside_write(tmp_path: Path):
    manifest = _manifest(tmp_path)
    parent = tmp_path / "leased-parent"
    state = parent / "state"
    outside = tmp_path / "outside-parent-aba"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("unchanged")

    def rotate_parent(_manifest):
        rotated = parent.with_name(parent.name + ".rotated")
        parent.rename(rotated)
        parent.symlink_to(outside, target_is_directory=True)
        return _accepted(_manifest)

    with pytest.raises(ValidationError, match="(replaced|type drifted) during transaction"):
        evaluate_release_holdout(
            **_kwargs(tmp_path, manifest, rotate_parent, state_root=state)
        )
    assert sentinel.read_text() == "unchanged"
    assert sorted(path.name for path in outside.iterdir()) == ["sentinel"]
    rotated_state = tmp_path / "leased-parent.rotated" / "state"
    root = _generation_root(rotated_state, manifest)
    assert not (root / "evaluation.json").exists()
