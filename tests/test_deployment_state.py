from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import deployment_state


SHA_A = "a" * 40
SHA_B = "b" * 40


def _inputs(tmp_path: Path) -> tuple[Path, Path, list[str]]:
    previous_sha = tmp_path / "previous.sha"
    previous_sha.write_text(SHA_A + "\n")
    previous_health = tmp_path / "previous-health.json"
    previous_health.write_text(
        json.dumps(
            {
                "attestation_mode": "supported",
                "deployment_revision": SHA_A,
                "process_id": 42,
            }
        )
    )
    helpers: list[str] = []
    for name in ("frontend_release.py", "check_deploy_ready.py", "deployment_state.py"):
        source = tmp_path / f"source-{name}"
        source.write_text(f"# {name}\n")
        helpers.append(f"{name}={source}")
    return previous_sha, previous_health, helpers


def _begin(tmp_path: Path, release_id: str = "release-1") -> tuple[Path, Path]:
    state_root = tmp_path / ".deploy-state"
    previous_sha, previous_health, helpers = _inputs(tmp_path)
    record = deployment_state.begin(
        state_root,
        release_id,
        SHA_B,
        previous_sha,
        previous_health,
        tmp_path / "web-ui" / "dist",
        helpers,
    )
    return state_root, record


def test_begin_persists_owned_recovery_record_and_exact_helper_copies(tmp_path: Path) -> None:
    state_root, record_path = _begin(tmp_path)
    release_dir = record_path.parent
    marker = json.loads((state_root / "in-progress.json").read_text())
    record = json.loads(record_path.read_text())

    assert marker == {"release_id": "release-1", "recovery_record": str(record_path)}
    assert record["previous_sha"] == SHA_A
    assert record["target_sha"] == SHA_B
    assert record["frontend_promotion_intent"] is False
    assert (release_dir / "previous.sha").read_text().strip() == SHA_A
    assert json.loads((release_dir / "backend.previous.health.json").read_text())["process_id"] == 42
    assert set(record["helpers"]) == {
        "frontend_release.py",
        "check_deploy_ready.py",
        "deployment_state.py",
    }
    assert (release_dir / "frontend_release.py").read_text() == "# frontend_release.py\n"
    deployment_state.assert_owner(state_root, "release-1")


def test_existing_owner_blocks_new_attempt_without_overwriting_recovery(tmp_path: Path) -> None:
    state_root, record_path = _begin(tmp_path)
    marker_path = state_root / "in-progress.json"
    before_marker = marker_path.read_bytes()
    before_record = record_path.read_bytes()
    previous_sha, previous_health, helpers = _inputs(tmp_path)

    with pytest.raises(deployment_state.DeploymentStateError, match="already owned"):
        deployment_state.begin(
            state_root,
            "release-2",
            "c" * 40,
            previous_sha,
            previous_health,
            tmp_path / "web-ui" / "dist",
            helpers,
        )

    assert marker_path.read_bytes() == before_marker
    assert record_path.read_bytes() == before_record
    assert not (state_root / "releases" / "release-2").exists()


def test_only_owner_can_mark_or_clear_and_failed_attempt_cannot_clear_other_marker(
    tmp_path: Path,
) -> None:
    state_root, record_path = _begin(tmp_path)
    marker_path = state_root / "in-progress.json"
    before = marker_path.read_bytes()

    with pytest.raises(deployment_state.DeploymentStateError, match="belongs"):
        deployment_state.mark_frontend(state_root, "release-2")
    with pytest.raises(deployment_state.DeploymentStateError, match="belongs"):
        deployment_state.clear(state_root, "release-2")
    assert marker_path.read_bytes() == before

    deployment_state.mark_frontend(state_root, "release-1")
    assert (record_path.parent / "frontend-promotion.intent").is_file()
    assert json.loads(record_path.read_text())["frontend_promotion_intent"] is True
    deployment_state.clear(state_root, "release-1")
    assert not marker_path.exists()
    assert record_path.is_file()
    deployment_state.ensure_clear(state_root)


def test_ensure_clear_reports_existing_recovery_owner(tmp_path: Path) -> None:
    state_root, _ = _begin(tmp_path)
    with pytest.raises(deployment_state.DeploymentStateError, match="release-1"):
        deployment_state.ensure_clear(state_root)
