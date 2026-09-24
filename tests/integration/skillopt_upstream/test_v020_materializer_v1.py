from __future__ import annotations

import importlib
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from src.search_eval.query_analysis_reward import (
    mixed_gate_score,
    validate_sealed_reward_evidence,
)
from src.search_eval.skillopt_materializer_v1 import (
    ENV_NAME,
    OPTIMIZER_SPLIT_MAPPING,
    materialize_skillopt_search_benchmark_v1,
    stage_skillopt_search_benchmark_v1,
    validate_skillopt_staging_manifest_v1,
)
from src.search_eval.skillopt_run_contract import INPUT_ARTIFACT_NAMES

UPSTREAM_ROOT_ENV = "SKILLOPT_V020_UPSTREAM_ROOT"
EXACT_SOURCE_REQUIRED_ENV = "SKILLOPT_V020_EXACT_SOURCE_REQUIRED"
DEVELOPER_UPSTREAM_ROOT = Path("/private/tmp/skillopt-v020-review")
DATASET = Path("data/search_eval/skillopt_paper_search_v0.json").resolve()
CONTROL = Path("data/search_eval/skillopt_execution_control_v0.json").resolve()
BASELINE = Path("docs/skillopt_search/baseline_skill.md").resolve()
CORPUS = Path("data/search_eval/skillopt_reward_corpus_v1.json").resolve()


def _upstream_root() -> Path:
    configured = os.environ.get(UPSTREAM_ROOT_ENV)
    root = Path(configured) if configured else DEVELOPER_UPSTREAM_ROOT
    if root.is_dir():
        return root
    message = f"exact SkillOpt v0.2.0 source unavailable: {root}"
    if os.environ.get(EXACT_SOURCE_REQUIRED_ENV) == "1":
        pytest.fail(message)
    pytest.skip(message)


def _raw_response(query: dict) -> str:
    original = query["original_query"]
    required = list(query["required_terms"])
    keywords = required or [word for word in original.split()[:2] if word]
    return json.dumps(
        {
            "is_academic": True,
            "intent": query["expected_intent"],
            "keywords": keywords,
            "core_concepts": keywords[:2],
            "research_area": "paper retrieval",
            "improved_query": original,
            "search_strategy": "source-specific compact retrieval",
            "search_filters": {},
            "confidence": 0.9,
            "source_queries": {
                "arxiv": original,
                "dblp": original,
                "google_scholar": original,
                "scholar_queries": [original],
            },
        },
        ensure_ascii=False,
    )


def _clear_upstream_modules() -> None:
    for name in list(sys.modules):
        if (
            name == "skillopt"
            or name.startswith("skillopt.")
            or name == "scripts"
            or name.startswith("scripts.")
        ):
            sys.modules.pop(name, None)


def test_v1_materialization_executes_exact_v020_train_eval_without_provider_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    release_sentinel = "G006_EXTERNAL_RELEASE_51c04e6e_never_stage"
    approval_only = tmp_path / "approval-only"
    approval_only.mkdir()
    release_manifest = approval_only / "release_manifest.json"
    release_manifest.write_text(
        json.dumps(
            {
                "release_path": f"/{release_sentinel}/items.json",
                "release_hash": f"sha256:{release_sentinel}",
                "holdout_generation": release_sentinel,
                "labels": [release_sentinel],
            }
        ),
        encoding="utf-8",
    )
    generated = tmp_path / "generated"
    manifest = materialize_skillopt_search_benchmark_v1(
        output_dir=generated,
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE,
        reward_corpus_path=CORPUS,
    )
    staging = stage_skillopt_search_benchmark_v1(
        upstream_checkout=_upstream_root(),
        materialization_manifest=manifest,
        staging_dir=tmp_path / "exact-v020",
    )
    validate_skillopt_staging_manifest_v1(staging)
    staged = Path(staging["staging_dir"])
    assert manifest["optimizer_split_mapping"] == OPTIMIZER_SPLIT_MAPPING
    assert staging["optimizer_split_mapping"] == OPTIMIZER_SPLIT_MAPPING
    optimizer_test_items = json.loads(
        (staged / "data" / f"{ENV_NAME}_split" / "test" / "items.json").read_text(
            encoding="utf-8"
        )
    )
    assert optimizer_test_items
    assert all(
        item["logical_split"] == "optimizer_test"
        and item["upstream_split"] == "test"
        for item in optimizer_test_items
    )

    runner_input_exact_set = {
        "dataset",
        "execution_control",
        "baseline_skill",
        "generated_environment_archive",
        "dependency_lock",
        "rendered_config",
        "compatibility_profile",
        "compatibility_report",
        "pristine_source_manifest",
        "overlay_manifest",
        "staging_manifest",
        "runner_identity",
        "custody_evidence",
        "acl_snapshot",
        "immutable_store_receipt",
        "trusted_authority_policy",
    }
    assert set(INPUT_ARTIFACT_NAMES) == runner_input_exact_set
    assert "release_manifest" not in INPUT_ARTIFACT_NAMES
    sentinel_bytes = release_sentinel.encode("utf-8")
    serialized_execution = json.dumps(
        {
            "materialization_manifest": manifest,
            "staging_manifest": staging,
            "train_argv": staging["train_argv"],
            "eval_argv": staging["eval_argv"],
            "config": Path(staging["config_path"]).read_text(encoding="utf-8"),
        },
        sort_keys=True,
    ).encode("utf-8")
    assert sentinel_bytes not in serialized_execution
    for root in (generated, staged):
        for artifact in root.rglob("*"):
            if artifact.is_file():
                assert sentinel_bytes not in artifact.read_bytes()

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    responses = {
        query["original_query"]: _raw_response(query) for query in corpus["queries"]
    }
    counts = {"deterministic_target": 0, "provider": 0, "network": 0}

    def deterministic_target(*, system: str, user: str, **_kwargs):
        counts["deterministic_target"] += 1
        if "## Deterministic reward feedback" not in system:
            return "{}", {}
        matches = [response for query, response in responses.items() if query in user]
        assert len(matches) == 1
        return matches[0], {}

    def deny_network(*_args, **_kwargs):
        counts["network"] += 1
        raise AssertionError("network access is forbidden")

    def deny_provider(*_args, **_kwargs):
        counts["provider"] += 1
        raise AssertionError("provider access is forbidden")

    def deny_subprocess(*_args, **_kwargs):
        raise AssertionError("subprocess execution is forbidden")

    original_argv = list(sys.argv)
    _clear_upstream_modules()
    monkeypatch.syspath_prepend(str(staged))
    monkeypatch.chdir(staged)
    monkeypatch.setattr(socket, "socket", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(subprocess, "run", deny_subprocess)
    monkeypatch.setattr(subprocess, "Popen", deny_subprocess)
    monkeypatch.setattr(subprocess, "check_call", deny_subprocess)
    monkeypatch.setattr(subprocess, "check_output", deny_subprocess)
    try:
        rollout_module = importlib.import_module(f"skillopt.envs.{ENV_NAME}.rollout")
        adapter_module = importlib.import_module(f"skillopt.envs.{ENV_NAME}.adapter")
        rollout_module.chat_target = deterministic_target
        model_module = importlib.import_module("skillopt.model")
        for entrypoint in (
            "chat_optimizer",
            "chat_optimizer_messages",
            "chat_target",
            "chat_target_messages",
            "chat_with_deployment",
            "chat_messages_with_deployment",
        ):
            monkeypatch.setattr(model_module, entrypoint, deny_provider)

        train = importlib.import_module("scripts.train")
        eval_only = importlib.import_module("scripts.eval_only")
        config_module = importlib.import_module("skillopt.config")
        reward_module = importlib.import_module(
            f"skillopt.envs.{ENV_NAME}.reward_runtime.query_analysis_reward"
        )
        query_contract_module = importlib.import_module(
            f"skillopt.envs.{ENV_NAME}.reward_runtime.query_analysis_contract"
        )
        imported_modules = {
            "scripts/train.py": train,
            "scripts/eval_only.py": eval_only,
            "skillopt/config.py": config_module,
            f"skillopt/envs/{ENV_NAME}/reward_runtime/query_analysis_reward.py": reward_module,
            f"skillopt/envs/{ENV_NAME}/reward_runtime/query_analysis_contract.py": query_contract_module,
            f"skillopt/envs/{ENV_NAME}/rollout.py": rollout_module,
            f"skillopt/envs/{ENV_NAME}/adapter.py": adapter_module,
        }
        for relative_path, module in imported_modules.items():
            imported_path = Path(module.__file__).resolve()
            expected_path = (staged / relative_path).resolve()
            assert imported_path == expected_path
            imported_path.relative_to(staged.resolve())
            raw_bytes = imported_path.read_bytes()
            assert raw_bytes == expected_path.read_bytes()
            assert (
                "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
                == staging["staged_file_hashes"][relative_path]
            )

        train._register_builtins()
        registered = train._ENV_REGISTRY[ENV_NAME]
        train._register_builtins()
        assert train._ENV_REGISTRY[ENV_NAME] is registered
        train_out = Path(staging["train_out_root"])
        sys.argv = list(staging["train_argv"])[1:] + [
            "--num_epochs",
            "1",
            "--train_size",
            "2",
            "--batch_size",
            "2",
            "--accumulation",
            "1",
            "--minibatch_size",
            "2",
            "--merge_batch_size",
            "1",
            "--edit_budget",
            "1",
            "--sel_env_num",
            "1",
            "--test_env_num",
            "1",
            "--eval_test",
            "true",
            "--use_gate",
            "true",
        ]
        train.main()
        best_skill = Path(staging["expected_best_skill"])
        assert best_skill.is_file()
        history = json.loads((train_out / "history.json").read_text(encoding="utf-8"))
        assert history[0]["gate_metric"] == "mixed"
        assert history[0]["action"] == "accept_new_best"

        eval_only._register_builtins()
        registered = eval_only._ENV_REGISTRY[ENV_NAME]
        eval_only._register_builtins()
        assert eval_only._ENV_REGISTRY[ENV_NAME] is registered
        eval_out = Path(staging["eval_out_root"])
        sys.argv = list(staging["eval_argv"])[1:]
        eval_only.main()
        summary = json.loads(
            (eval_out / "eval_summary.json").read_text(encoding="utf-8")
        )
        assert summary["n_items"] == 4

        from skillopt.evaluation.gate import evaluate_gate, select_gate_score
        from skillopt.utils import compute_score

        adapter = adapter_module.JiphyeonjeonSearchAdapter(
            split_dir=staging["split_dir"]
        )
        adapter.setup({"split_dir": staging["split_dir"]})
        selection = adapter.build_eval_env(1, "val", 42)
        results = adapter.rollout(
            selection, best_skill.read_text(encoding="utf-8"), str(tmp_path / "gate")
        )
        assert "sealed_evidence" not in json.dumps(results, sort_keys=True)
        assert "ordered_variants" not in json.dumps(results, sort_keys=True)
        reflection = adapter.reflect(results, "private", str(tmp_path / "reflection"))
        assert "ordered_variants" not in json.dumps(reflection, sort_keys=True)
        assert "rankings" not in json.dumps(reflection, sort_keys=True)
        assert "merged_documents" not in json.dumps(reflection, sort_keys=True)
        hard, soft = compute_score(results)
        assert select_gate_score(hard, soft, "mixed", 0.8) == mixed_gate_score(
            hard=hard, soft=soft, weight=0.8
        )
        tie = evaluate_gate(
            "candidate",
            hard,
            "current",
            mixed_gate_score(hard=hard, soft=soft, weight=0.8),
            "best",
            mixed_gate_score(hard=hard, soft=soft, weight=0.8),
            1,
            2,
            cand_soft=soft,
            metric="mixed",
            mixed_weight=0.8,
        )
        assert tie.action == "reject"
        assert counts["provider"] == counts["network"] == 0
        assert counts["deterministic_target"] > 0
        validate_skillopt_staging_manifest_v1(staging)

        evidence_indexes = [
            *train_out.rglob("sealed_evidence/index.json"),
            *eval_out.rglob("sealed_evidence/index.json"),
            *(tmp_path / "gate").rglob("sealed_evidence/index.json"),
        ]
        assert evidence_indexes
        observed_full_evidence = False
        for index_path in evidence_indexes:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            assert index["version"] == "skillopt-sealed-evidence-index-v1"
            assert index["count"] == len(index["entries"])
            assert 0 < index["count"] <= 4096
            for entry in index["entries"]:
                evidence_path = index_path.parent / entry["relative_path"]
                payload = evidence_path.read_bytes()
                assert (
                    "sha256:" + hashlib.sha256(payload).hexdigest()
                    == entry["file_hash"]
                )
                evidence = validate_sealed_reward_evidence(json.loads(payload))
                assert evidence["evidence_identity"] == entry["evidence_identity"]
                if (
                    evidence["ordered_variants"]
                    and evidence["rankings"]
                    and evidence["merged_documents"]
                ):
                    observed_full_evidence = True
                    assert all(
                        ranking["results"] for ranking in evidence["rankings"]
                    )
                    assert all(
                        document["doc_id"]
                        for document in evidence["merged_documents"]
                    )
        assert observed_full_evidence

        for relative_path, module in imported_modules.items():
            imported_path = Path(module.__file__).resolve()
            assert imported_path == (staged / relative_path).resolve()
            assert (
                "sha256:" + hashlib.sha256(imported_path.read_bytes()).hexdigest()
                == staging["staged_file_hashes"][relative_path]
            )

        for root in (train_out, eval_out):
            for artifact_path in root.rglob("*"):
                if artifact_path.is_file():
                    payload = artifact_path.read_text(encoding="utf-8")
                    assert "predicted_answer" not in payload
                    assert "private candidate policy" not in payload
                    if "sealed_evidence" not in artifact_path.parts:
                        assert "reward_evidence" not in payload
                        assert "ordered_variants" not in payload
                        assert "rankings" not in payload
                        assert "merged_documents" not in payload
        for artifact in staged.rglob("*"):
            if artifact.is_file():
                assert sentinel_bytes not in artifact.read_bytes()
    finally:
        sys.argv = original_argv
        _clear_upstream_modules()
