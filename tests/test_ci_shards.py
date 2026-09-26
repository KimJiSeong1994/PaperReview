"""Fail-closed contracts for the CI package's partition and aggregate boundary."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from coverage import CoverageData
import pytest

from scripts import ci_shards as ci


def nodes():
    return sorted(
        f"{path}::test_case" for path in ci.OFFLINE_OPTIMIZER | ci.POSTER_BROWSER
    ) + [
        "tests/test_skillopt_policy_runtime.py::test_authority",
        "tests/test_skillopt_deep_review_policy_runtime.py::test_authority",
        "tests/test_new_feature.py::test_new",
    ]


def receipts():
    all_nodes = sorted(nodes())
    result = []
    for shard in ci.SHARDS:
        selected = [node for node in all_nodes if ci.shard_for(node) == shard]
        result.append(
            {
                "schema": 1,
                "shard": shard,
                "exitstatus": 0,
                "sha": "local",
                "run_id": "local",
                "run_attempt": "local",
                "all_nodes": all_nodes.copy(),
                "selected": selected,
                "collection_errors": [],
                "reports": [
                    {
                        "nodeid": node,
                        "when": when,
                        "outcome": "passed",
                        "xfail": False,
                        "reason": "",
                    }
                    for node in selected
                    for when in ("setup", "call", "teardown")
                ],
            }
        )
    return result


@pytest.fixture(autouse=True)
def local_run(monkeypatch):
    for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_ACTIONS"):
        monkeypatch.delenv(key, raising=False)


def needs():
    return {shard: {"result": "success"} for shard in ci.SHARDS}


def test_default_core_keeps_runtime_policies_and_new_files():
    for node in nodes()[-3:]:
        assert ci.shard_for(node) == "backend-core"
    assert ci.audit_receipts(receipts(), needs()) == sorted(nodes())


@pytest.mark.parametrize("status", ["skipped", "cancelled", "failure", "", None])
@pytest.mark.parametrize("shard", ci.SHARDS)
def test_aggregate_rejects_every_unsuccessful_job(status, shard):
    state = needs()
    state[shard]["result"] = status
    with pytest.raises(ValueError, match="Every shard"):
        ci.audit_receipts(receipts(), state)


def test_missing_job_and_missing_duplicate_receipts_fail():
    state = needs()
    del state[ci.SHARDS[0]]
    with pytest.raises(ValueError, match="Every shard"):
        ci.audit_receipts(receipts(), state)
    for rows in (receipts()[:-1], receipts() + receipts()[:1]):
        with pytest.raises(ValueError, match="receipts"):
            ci.audit_receipts(rows, needs())


@pytest.mark.parametrize(
    "mutation",
    [
        "collection",
        "missing_node",
        "duplicate_node",
        "failed",
        "exit",
        "skip",
        "missing_call",
        "missing_teardown",
        "duplicate_report",
        "stale",
        "extra_execution",
    ],
)
def test_corrupted_receipts_fail_closed(mutation):
    rows = deepcopy(receipts())
    row = rows[0]
    if mutation == "collection":
        row["collection_errors"] = ["missing dependency"]
    elif mutation == "missing_node":
        row["selected"].pop()
    elif mutation == "duplicate_node":
        row["all_nodes"].append(row["all_nodes"][0])
    elif mutation == "failed":
        row["reports"][1]["outcome"] = "failed"
    elif mutation == "exit":
        row["exitstatus"] = 1
    elif mutation == "skip":
        row["reports"][1].update(outcome="skipped", reason="browser absent")
    elif mutation == "missing_call":
        row["reports"].pop(1)
    elif mutation == "missing_teardown":
        row["reports"].pop(2)
    elif mutation == "duplicate_report":
        row["reports"].append(row["reports"][0])
    elif mutation == "stale":
        row["sha"] = "old-commit"
    else:
        row["reports"][0]["nodeid"] = "tests/unselected.py::test_other"
    with pytest.raises(ValueError):
        ci.audit_receipts(rows, needs())


def test_collection_drift_and_obsolete_inventory_fail():
    rows = receipts()
    rows[1]["all_nodes"] = rows[1]["all_nodes"] + ["tests/extra.py::test_new"]
    with pytest.raises(ValueError, match="collection differs"):
        ci.audit_receipts(rows, needs())
    with pytest.raises(ValueError, match="Inventory files absent"):
        ci.validate_inventory(["tests/extra.py::test_new"])


def test_only_known_optional_upstream_skips_are_allowed():
    for path, reason in ci.OPTIONAL_UPSTREAM.items():
        assert ci.allowed_skip(path + "::test_upstream", reason)
        assert not ci.allowed_skip(path + "::test_upstream", "dependency missing")
    assert not ci.allowed_skip(
        "tests/test_poster_export_contract.py::test_render",
        "Playwright Chromium executable is not installed",
    )
    rows = receipts()
    row = rows[1]
    node = "tests/test_skillopt_compatibility.py::test_case"
    row["reports"] = [
        r for r in row["reports"] if not (r["nodeid"] == node and r["when"] == "call")
    ]
    report = next(
        r for r in row["reports"] if r["nodeid"] == node and r["when"] == "setup"
    )
    report.update(outcome="skipped", reason=ci.OPTIONAL_UPSTREAM[node.split("::")[0]])
    ci.audit_receipts(rows, needs())


def test_linux_cannot_skip_atomic_exchange(monkeypatch):
    node = "tests/test_frontend_release.py::test_linux_exchange_keeps_both_complete_directories"
    monkeypatch.setattr(ci.sys, "platform", "linux")
    assert not ci.allowed_skip(node, "renameat2 is Linux-specific")
    monkeypatch.setattr(ci.sys, "platform", "darwin")
    assert ci.allowed_skip(node, "renameat2 is Linux-specific")
    assert not ci.allowed_skip(node, "unknown failure")


@pytest.fixture
def source_repository(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    for package in ("routers", "app", "src"):
        directory = repository / package / "nested"
        directory.mkdir(parents=True)
        (directory / "sample.py").write_text("a = 1\nb = 2\nc = 3\n")
        (directory.parent / "__init__.py").write_text("")
    monkeypatch.setattr(ci, "REPOSITORY_ROOT", repository)
    return repository


def write_inputs(root: Path, repository: Path, lines=(1, 2, 3)):
    sources = list(repository.rglob("*.py"))
    for row, line in zip(receipts(), lines, strict=True):
        directory = root / row["shard"]
        directory.mkdir()
        (directory / "receipt.json").write_text(json.dumps(row))
        data = CoverageData(basename=str(directory / ".coverage"))
        data.add_lines(
            {
                str(source): [line] if source.name == "sample.py" else []
                for source in sources
            }
        )
        data.write()


def test_coverage_is_union_not_average_or_last_shard(
    tmp_path, source_repository, monkeypatch
):
    write_inputs(tmp_path, source_repository)
    (source_repository / "out_of_scope.py").write_text("unmeasured = True\n")
    monkeypatch.chdir(tmp_path)
    result = ci.aggregate(tmp_path, needs())
    assert result["coverage_percent"] == 100
    assert result["union_equal"] and result["duplicates"] == 0
    assert len(result["coverage_inputs"]) == 3


@pytest.mark.parametrize("mode", ["missing", "empty", "corrupt"])
def test_missing_empty_corrupt_coverage_fails(tmp_path, source_repository, mode):
    write_inputs(tmp_path, source_repository)
    path = tmp_path / ci.SHARDS[1] / ".coverage"
    if mode == "missing":
        path.unlink()
    else:
        path.write_bytes(b"" if mode == "empty" else b"not sqlite")
    with pytest.raises(Exception):
        ci.aggregate(tmp_path, needs())


def test_coverage_threshold_not_lowered(tmp_path, source_repository):
    write_inputs(tmp_path, source_repository)
    for source in source_repository.rglob("sample.py"):
        source.write_text("\n".join(f"x{i} = {i}" for i in range(30)) + "\n")
    with pytest.raises(ValueError, match="below 15%"):
        ci.aggregate(tmp_path, needs())


@pytest.mark.parametrize("shard", ci.SHARDS)
@pytest.mark.parametrize(
    "mode", ["one_file", "missing", "wrong", "replacement", "extra", "relative"]
)
def test_each_coverage_input_requires_exact_source_inventory(
    tmp_path, source_repository, shard, mode
):
    write_inputs(tmp_path, source_repository)
    measured = {str(path): [] for path in source_repository.rglob("*.py")}
    if mode == "one_file":
        measured = {str(source_repository / "routers" / "__init__.py"): []}
    elif mode == "missing":
        measured.pop(next(iter(measured)))
    elif mode == "wrong":
        measured = {str(tmp_path / "foreign.py"): [1]}
    elif mode == "replacement":
        measured.pop(next(iter(measured)))
        measured[str(tmp_path / "foreign.py")] = [1]
    elif mode == "extra":
        measured[str(tmp_path / "foreign.py")] = [1]
    else:
        measured = {
            str(Path(path).relative_to(source_repository)): lines
            for path, lines in measured.items()
        }
    data = CoverageData(basename=str(tmp_path / shard / ".coverage"))
    data.erase()
    data.add_lines(measured)
    data.write()
    with pytest.raises(ValueError, match="Coverage source inventory differs"):
        ci.aggregate(tmp_path, needs())


def github_receipts(monkeypatch, current="3", attempts=("1", "2", "3")):
    monkeypatch.setenv("GITHUB_SHA", "current-sha")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", current)
    rows = receipts()
    for row, attempt in zip(rows, attempts, strict=True):
        row.update(sha="current-sha", run_id="123", run_attempt=attempt)
    return rows


@pytest.mark.parametrize(
    "attempts", [("1", "2", "3"), ("1", "1", "1"), ("3", "3", "3")]
)
def test_same_run_mixed_aggregate_only_and_full_retries(monkeypatch, attempts):
    rows = github_receipts(monkeypatch, attempts=attempts)
    assert ci.audit_receipts(rows, needs()) == sorted(nodes())


@pytest.mark.parametrize("key,value", [("sha", "foreign"), ("run_id", "456")])
def test_prior_attempt_from_foreign_identity_fails(monkeypatch, key, value):
    rows = github_receipts(monkeypatch)
    rows[0][key] = value
    with pytest.raises(ValueError, match=f"stale {key}"):
        ci.audit_receipts(rows, needs())


@pytest.mark.parametrize(
    "value", [None, "", "0", "-1", "1.5", "+1", " 1", "１", "local", 1, True]
)
def test_malformed_receipt_attempt_fails(monkeypatch, value):
    rows = github_receipts(monkeypatch)
    rows[0]["run_attempt"] = value
    with pytest.raises(ValueError, match="Invalid run_attempt"):
        ci.audit_receipts(rows, needs())


@pytest.mark.parametrize("value", ["", "0", "-1", "1.5", "+1", " 1", "１", "local"])
def test_malformed_current_attempt_fails(monkeypatch, value):
    rows = github_receipts(monkeypatch, current=value)
    with pytest.raises(ValueError, match="Invalid run_attempt"):
        ci.audit_receipts(rows, needs())


def test_future_receipt_attempt_fails(monkeypatch):
    rows = github_receipts(monkeypatch)
    rows[0]["run_attempt"] = "4"
    with pytest.raises(ValueError, match="future run_attempt"):
        ci.audit_receipts(rows, needs())


@pytest.mark.parametrize("key", ["GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"])
def test_incomplete_github_context_cannot_use_local_sentinel(monkeypatch, key):
    rows = github_receipts(monkeypatch)
    monkeypatch.delenv(key)
    with pytest.raises(ValueError):
        ci.audit_receipts(rows, needs())


def test_github_actions_context_cannot_use_local_sentinel(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(ValueError, match="Invalid run_attempt"):
        ci.audit_receipts(receipts(), needs())


def test_local_context_rejects_numeric_receipt_attempt():
    rows = receipts()
    rows[0]["run_attempt"] = "1"
    with pytest.raises(ValueError, match="invalid local run_attempt"):
        ci.audit_receipts(rows, needs())
