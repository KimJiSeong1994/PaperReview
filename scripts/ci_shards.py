"""Explicit CI partition, pytest receipts, and fail-closed aggregate audit.

Load with ``pytest -p scripts.ci_shards --ci-shard=...``. Every shard collects
all tests before partitioning, so new files default to core and collection
errors cannot disappear behind an ignore list.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

SHARDS = ("backend-core", "offline-optimizer", "poster-browser")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
# Runtime policy/authorization tests deliberately stay in the default core.
OFFLINE_OPTIMIZER = frozenset(
    {
        "tests/test_skillopt_adapter_skeleton.py",
        "tests/test_skillopt_automation_adversarial.py",
        "tests/test_skillopt_candidate_generation.py",
        "tests/test_skillopt_compatibility.py",
        "tests/test_skillopt_compatibility_overlay.py",
        "tests/test_skillopt_continuous_optimizer.py",
        "tests/test_skillopt_cron_runner.py",
        "tests/test_skillopt_deep_review_artifacts.py",
        "tests/test_skillopt_deep_review_cron_runner.py",
        "tests/test_skillopt_identity_vectors.py",
        "tests/test_skillopt_materialization_and_approval.py",
        "tests/test_skillopt_materializer_v1.py",
        "tests/test_skillopt_observability.py",
        "tests/test_skillopt_orchestrator.py",
        "tests/test_skillopt_query_analysis_reward.py",
        "tests/test_skillopt_query_analyzer_pilot.py",
        "tests/test_skillopt_release_holdout.py",
        "tests/test_skillopt_reward_anti_gaming.py",
        "tests/test_skillopt_reward_precision_and_gate.py",
        "tests/test_skillopt_run_contract.py",
        "tests/test_skillopt_search_artifacts.py",
        "tests/test_skillopt_shadow_eval.py",
    }
)
POSTER_BROWSER = frozenset(
    {
        "tests/test_poster_browser_security.py",
        "tests/test_poster_export_contract.py",
    }
)
# These optional upstream fixtures already skip in the original full suite.
# Browser/platform/dependency skips are NOT allowed on the Linux CI runners.
OPTIONAL_UPSTREAM = {
    "tests/test_skillopt_compatibility.py": "set SKILLOPT_V020_UPSTREAM_ROOT to an exact Microsoft SkillOpt v0.2.0 checkout",
    "tests/test_skillopt_compatibility_overlay.py": "pinned upstream checkout is unavailable:",
    "tests/test_skillopt_materializer_v1.py": "exact SkillOpt v0.2.0 checkout unavailable",
    "tests/integration/skillopt_upstream/test_v020_compatibility_overlay.py": "; exact-source integration was not requested",
    "tests/integration/skillopt_upstream/test_v020_mock_train_eval.py": "; developer exact-source check not requested",
    "tests/integration/skillopt_upstream/test_v020_materializer_v1.py": "exact SkillOpt v0.2.0 source unavailable:",
}


def shard_for(nodeid: str) -> str:
    path = nodeid.split("::", 1)[0]
    if path in OFFLINE_OPTIMIZER:
        return "offline-optimizer"
    if path in POSTER_BROWSER:
        return "poster-browser"
    return "backend-core"


def allowed_skip(nodeid: str, reason: str) -> bool:
    if (
        sys.platform != "linux"
        and nodeid
        == "tests/test_frontend_release.py::test_linux_exchange_keeps_both_complete_directories"
        and "renameat2 is Linux-specific" in reason
    ):
        return True
    path = nodeid.split("::", 1)[0]
    expected = OPTIONAL_UPSTREAM.get(path)
    return bool(expected and expected in reason)


def validate_inventory(nodes: list[str]) -> None:
    if not nodes or len(nodes) != len(set(nodes)):
        raise ValueError("Empty or duplicate full collection")
    paths = {node.split("::", 1)[0] for node in nodes}
    missing = (OFFLINE_OPTIMIZER | POSTER_BROWSER) - paths
    if missing:
        raise ValueError(f"Inventory files absent from collection: {sorted(missing)}")
    if OFFLINE_OPTIMIZER & POSTER_BROWSER:
        raise ValueError("Overlapping inventory")


def pytest_addoption(parser):
    parser.addoption("--ci-shard", choices=SHARDS)
    parser.addoption("--ci-receipt", default="ci-results/receipt.json")


def pytest_configure(config):
    if config.getoption("--ci-shard"):
        config.pluginmanager.register(ShardReceipt(config), "ci-shard-receipt")


class ShardReceipt:
    def __init__(self, config):
        self.config = config
        self.shard = config.getoption("--ci-shard")
        self.nodes = []
        self.selected = []
        self.reports = []
        self.collection_errors = []

    def pytest_collection_modifyitems(self, session, config, items):
        self.nodes = sorted(item.nodeid for item in items)
        validate_inventory(self.nodes)
        selected = [item for item in items if shard_for(item.nodeid) == self.shard]
        rejected = [item for item in items if shard_for(item.nodeid) != self.shard]
        self.selected = sorted(item.nodeid for item in selected)
        config.hook.pytest_deselected(items=rejected)
        items[:] = selected

    def pytest_collectreport(self, report):
        if report.failed or report.skipped:
            self.collection_errors.append(str(report.longrepr))

    def pytest_runtest_logreport(self, report):
        self.reports.append(
            {
                "nodeid": report.nodeid,
                "when": report.when,
                "outcome": report.outcome,
                "xfail": hasattr(report, "wasxfail"),
                "reason": str(report.longrepr) if report.skipped else "",
            }
        )

    def pytest_sessionfinish(self, session, exitstatus):
        receipt = {
            "schema": 1,
            "shard": self.shard,
            "exitstatus": int(exitstatus),
            "sha": os.environ.get("GITHUB_SHA", "local"),
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
            "all_nodes": self.nodes,
            "selected": self.selected,
            "reports": self.reports,
            "collection_errors": self.collection_errors,
        }
        path = Path(self.config.getoption("--ci-receipt"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, indent=2) + "\n")


def positive_attempt(value: object) -> int:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdecimal()
        or int(value) <= 0
    ):
        raise ValueError(f"Invalid run_attempt: {value!r}")
    return int(value)


def audit_receipts(receipts: list[dict], needs: dict) -> list[str]:
    if set(needs) != set(SHARDS) or any(
        needs[shard].get("result") != "success" for shard in SHARDS
    ):
        raise ValueError(
            "Every shard job must succeed (no missing/skipped/cancelled jobs)"
        )
    if Counter(row.get("shard") for row in receipts) != Counter(SHARDS):
        raise ValueError("Missing or duplicate shard receipts")
    baseline = receipts[0]["all_nodes"]
    validate_inventory(baseline)
    local = not any(
        key in os.environ
        for key in (
            "GITHUB_SHA",
            "GITHUB_RUN_ID",
            "GITHUB_RUN_ATTEMPT",
            "GITHUB_ACTIONS",
        )
    )
    current_attempt = (
        None if local else positive_attempt(os.environ.get("GITHUB_RUN_ATTEMPT"))
    )
    union = []
    for receipt in receipts:
        shard = receipt["shard"]
        if (
            receipt.get("schema") != 1
            or receipt.get("exitstatus") != 0
            or receipt.get("collection_errors")
        ):
            raise ValueError(f"{shard}: unsuccessful execution/collection")
        for key, env in (
            ("sha", "GITHUB_SHA"),
            ("run_id", "GITHUB_RUN_ID"),
        ):
            identity = os.environ.get(env, "local" if local else None)
            if not identity or receipt.get(key) != identity:
                raise ValueError(f"{shard}: stale {key}")
        if local:
            if receipt.get("run_attempt") != "local":
                raise ValueError(f"{shard}: invalid local run_attempt")
        elif positive_attempt(receipt.get("run_attempt")) > current_attempt:
            raise ValueError(f"{shard}: future run_attempt")
        if receipt["all_nodes"] != baseline:
            raise ValueError(f"{shard}: full collection differs")
        expected = sorted(node for node in baseline if shard_for(node) == shard)
        if not expected or receipt["selected"] != expected:
            raise ValueError(f"{shard}: selection differs from inventory")
        reports = receipt["reports"]
        seen = set()
        phases = set()
        for report in reports:
            node = report["nodeid"]
            phase = (node, report["when"])
            if (
                node not in expected
                or phase in phases
                or report["when"] not in {"setup", "call", "teardown"}
            ):
                raise ValueError(f"{shard}: extra/duplicate execution report")
            phases.add(phase)
            if report["outcome"] not in {"passed", "skipped"}:
                raise ValueError(f"{shard}: failed test {node}")
            if (
                report["outcome"] == "skipped"
                and not report["xfail"]
                and not allowed_skip(node, report["reason"])
            ):
                raise ValueError(f"{shard}: unexpected skip {node}: {report['reason']}")
            if report["when"] == "call" or (
                report["when"] == "setup" and report["outcome"] == "skipped"
            ):
                seen.add(node)
        if seen != set(expected) or any(
            (node, phase) not in phases
            for node in expected
            for phase in ("setup", "teardown")
        ):
            raise ValueError(f"{shard}: incomplete test outcomes")
        union.extend(receipt["selected"])
    if Counter(union) != Counter(baseline):
        raise ValueError("Partition union differs from original collection")
    return baseline


def aggregate(root: Path, needs: dict) -> dict:
    from coverage import Coverage, CoverageData

    receipts = [
        json.loads((root / shard / "receipt.json").read_text()) for shard in SHARDS
    ]
    nodes = audit_receipts(receipts, needs)
    files = [root / shard / ".coverage" for shard in SHARDS]
    expected_sources = {
        str(path)
        for package in ("routers", "app", "src")
        for path in (REPOSITORY_ROOT / package).rglob("*.py")
        if path.is_file()
    }
    if not expected_sources:
        raise ValueError("Empty repository Python source inventory")
    for path in files:
        data = CoverageData(basename=str(path))
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Missing coverage: {path}")
        data.read()
        if not data.measured_files():
            raise ValueError(f"Empty measured coverage: {path}")
        measured = set(data.measured_files())
        if measured != expected_sources:
            raise ValueError(
                f"Coverage source inventory differs: {path}; "
                f"missing={sorted(expected_sources - measured)}; "
                f"unexpected={sorted(measured - expected_sources)}"
            )
    coverage = Coverage(data_file=str(root / ".coverage"), config_file=False)
    coverage.combine(data_paths=[str(path) for path in files], strict=True, keep=True)
    coverage.save()
    total = coverage.report(show_missing=True)
    if total < 15:
        raise ValueError(f"Combined coverage {total:.2f}% is below 15%")
    return {
        "nodes": len(nodes),
        "union_equal": True,
        "duplicates": 0,
        "coverage_percent": total,
        "coverage_inputs": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = aggregate(args.aggregate, json.loads(os.environ["SHARD_NEEDS"]))
        (args.aggregate / "aggregate.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
    except (ValueError, KeyError, OSError) as exc:
        print(f"CI aggregate failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
