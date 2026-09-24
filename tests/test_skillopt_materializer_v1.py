from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest

from src.search_eval import (
    materialize_skillopt_search_benchmark_v1 as exported_materialize_v1,
    stage_skillopt_search_benchmark_v1 as exported_stage_v1,
)
from src.search_eval.query_analysis_reward import (
    algorithm_identity,
    build_reward_reflection_projection,
    evaluate_query_analysis_reward,
    load_reward_corpus,
    validate_sealed_reward_evidence,
)
from src.search_eval.skillopt_contract import ValidationError
from src.search_eval.skillopt_materializer_v1 import (
    ENV_NAME,
    MATERIALIZATION_VERSION,
    OPTIMIZER_SPLIT_MAPPING,
    STAGING_VERSION,
    materialize_skillopt_search_benchmark_v1,
    stage_skillopt_search_benchmark_v1,
    validate_skillopt_materialization_manifest_v1,
    validate_skillopt_staging_manifest_v1,
)

DATASET = "data/search_eval/skillopt_paper_search_v0.json"
CONTROL = "data/search_eval/skillopt_execution_control_v0.json"
BASELINE_SKILL = "docs/skillopt_search/baseline_skill.md"
REWARD_CORPUS = "data/search_eval/skillopt_reward_corpus_v1.json"


def _materialize(tmp_path: Path) -> dict:
    return materialize_skillopt_search_benchmark_v1(
        output_dir=tmp_path / "materialized",
        dataset_path=DATASET,
        control_path=CONTROL,
        baseline_skill_path=BASELINE_SKILL,
    )


def _load_rollout(env_dir: Path, monkeypatch: pytest.MonkeyPatch):
    skillopt = types.ModuleType("skillopt")
    skillopt.__path__ = []
    model = types.ModuleType("skillopt.model")
    model.chat_target = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("provider call is forbidden")
    )
    backend = types.ModuleType("skillopt.model.backend_config")
    backend.is_target_exec_backend = lambda: False
    harness = types.ModuleType("skillopt.model.codex_harness")
    harness.run_target_exec = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("target execution is forbidden")
    )
    for name, module in {
        "skillopt": skillopt,
        "skillopt.model": model,
        "skillopt.model.backend_config": backend,
        "skillopt.model.codex_harness": harness,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    package_name = f"materialized_v1_{abs(hash(str(env_dir)))}"
    package = types.ModuleType(package_name)
    package.__path__ = [str(env_dir)]
    monkeypatch.setitem(sys.modules, package_name, package)
    module_name = f"{package_name}.rollout"
    spec = importlib.util.spec_from_file_location(module_name, env_dir / "rollout.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def _load_adapter(env_dir: Path, monkeypatch: pytest.MonkeyPatch):
    skillopt = types.ModuleType("skillopt")
    skillopt.__path__ = []
    datasets = types.ModuleType("skillopt.datasets")
    datasets.__path__ = []
    envs = types.ModuleType("skillopt.envs")
    envs.__path__ = []
    generated_env = types.ModuleType("skillopt.envs.jiphyeonjeon_search")
    generated_env.__path__ = [str(env_dir)]
    datasets_base = types.ModuleType("skillopt.datasets.base")
    datasets_base.BatchSpec = object
    envs_base = types.ModuleType("skillopt.envs.base")
    envs_base.EnvAdapter = object
    dataloader = types.ModuleType(
        "skillopt.envs.jiphyeonjeon_search.dataloader"
    )
    dataloader.JiphyeonjeonSearchDataLoader = object
    rollout = types.ModuleType("skillopt.envs.jiphyeonjeon_search.rollout")
    rollout.run_batch = lambda **_kwargs: []
    for name, module in {
        "skillopt": skillopt,
        "skillopt.datasets": datasets,
        "skillopt.datasets.base": datasets_base,
        "skillopt.envs": envs,
        "skillopt.envs.base": envs_base,
        "skillopt.envs.jiphyeonjeon_search": generated_env,
        "skillopt.envs.jiphyeonjeon_search.dataloader": dataloader,
        "skillopt.envs.jiphyeonjeon_search.rollout": rollout,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    module_name = "skillopt.envs.jiphyeonjeon_search.adapter"
    spec = importlib.util.spec_from_file_location(module_name, env_dir / "adapter.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def _raw_golden() -> tuple[dict, str]:
    case = json.loads(
        Path("tests/fixtures/skillopt_query_analysis_reward_golden.json").read_text(
            encoding="utf-8"
        )
    )["cases"][0]
    raw = copy.deepcopy(case["analysis"])
    raw.pop("original_query")
    raw["source_queries"].pop("default")
    return case, json.dumps(raw, ensure_ascii=False)


def test_v1_materialization_is_distinct_reward_bound_and_privacy_minimal(
    tmp_path: Path,
):
    manifest = _materialize(tmp_path)
    assert exported_materialize_v1 is materialize_skillopt_search_benchmark_v1
    validate_skillopt_materialization_manifest_v1(manifest)
    assert manifest["version"] == MATERIALIZATION_VERSION
    assert manifest["execution_status"] == "logical_bundle_only"
    assert manifest["staging_required"] is True
    assert "train_command" not in manifest
    assert "eval_command" not in manifest
    assert manifest["reward_runtime"]["algorithm_identity"] == algorithm_identity()
    assert manifest["reward_runtime"]["gate_mixed_weight"] == 0.8
    assert manifest["reward_runtime"]["strict_tie_rejection"] is True

    env_dir = Path(manifest["env_package_dir"])
    rollout_text = (env_dir / "rollout.py").read_text(encoding="utf-8")
    for forbidden in (
        "_score_text",
        "predicted_answer",
        "target_system_prompt",
        "target_user_prompt",
        "reference_text",
        "conversation.json",
        "must_include",
    ):
        assert forbidden not in rollout_text
    scorer = (env_dir / "reward_runtime/query_analysis_reward.py").read_text(
        encoding="utf-8"
    )
    assert "app.QueryAgent" not in scorer
    assert "src.search_eval" not in scorer
    assert (env_dir / "reward_runtime/query_analysis_contract.py").read_bytes() == Path(
        "app/QueryAgent/query_analysis_contract.py"
    ).read_bytes()
    assert (env_dir / "reward_runtime/reward_corpus.json").read_bytes() == Path(
        REWARD_CORPUS
    ).read_bytes()


def test_v1_generated_rollout_matches_canonical_reward_and_emits_bounded_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = _materialize(tmp_path)
    case, prediction = _raw_golden()
    rollout = _load_rollout(Path(manifest["env_package_dir"]), monkeypatch)
    item = {
        "id": case["query_id"],
        "reward_query_id": case["query_id"],
        "query": case["analysis"]["original_query"],
        "intent": case["analysis"]["intent"],
    }
    materialized = rollout._score_prediction(prediction, item)
    production = evaluate_query_analysis_reward(
        prediction, query_id=case["query_id"], corpus=REWARD_CORPUS
    )
    assert materialized == production

    rollout.chat_target = lambda **_kwargs: (prediction, {})
    expected_hard, expected_soft = rollout._upstream_gate_components(production)
    result = rollout._rollout_one(
        item,
        "private candidate policy text",
        max_completion_tokens=128,
        exec_timeout=10,
    )
    assert set(result) == {
        "id",
        "hard",
        "soft",
        "fail_reason",
        "n_turns",
        "reflection_projection",
    }
    projection = result.pop("reflection_projection")
    assert set(projection) == {
        "version",
        "categories",
        "hard",
        "soft",
        "components",
        "counts",
    }
    assert result == {
        "id": case["query_id"],
        "hard": expected_hard,
        "soft": expected_soft,
        "fail_reason": "",
        "n_turns": 1,
    }
    assert list((tmp_path / "predictions").rglob("*")) == []

    output_root = tmp_path / "rollout-output"
    batch_results = rollout.run_batch(
        items=[item],
        skill_content="private candidate policy text",
        out_root=str(output_root),
        workers=1,
        max_completion_tokens=128,
        exec_timeout=10,
    )
    assert batch_results[0]["reflection_projection"] == projection
    assert "sealed_evidence" not in batch_results[0]
    index = json.loads(
        (output_root / "sealed_evidence/index.json").read_text(encoding="utf-8")
    )
    assert index["version"] == "skillopt-sealed-evidence-index-v1"
    assert index["count"] == 1
    entry = index["entries"][0]
    evidence_path = output_root / "sealed_evidence" / entry["relative_path"]
    evidence = validate_sealed_reward_evidence(
        json.loads(evidence_path.read_text(encoding="utf-8"))
    )
    assert evidence["evidence_identity"] == entry["evidence_identity"]
    assert evidence["ordered_variants"]
    assert evidence["rankings"]
    assert evidence["merged_documents"]
    assert "ordered_variants" not in json.dumps(batch_results, sort_keys=True)


def test_v1_generated_rollout_evidence_sink_is_exclusive_and_no_follow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = _materialize(tmp_path)
    case, prediction = _raw_golden()
    rollout = _load_rollout(Path(manifest["env_package_dir"]), monkeypatch)
    rollout.chat_target = lambda **_kwargs: (prediction, {})
    item = {
        "id": case["query_id"],
        "reward_query_id": case["query_id"],
        "query": case["analysis"]["original_query"],
        "intent": case["analysis"]["intent"],
    }
    output_root = tmp_path / "exclusive-output"
    kwargs = {
        "items": [item],
        "skill_content": "candidate",
        "out_root": str(output_root),
        "workers": 1,
    }
    rollout.run_batch(**kwargs)
    with pytest.raises(RuntimeError, match="exclusive, atomic, and contained"):
        rollout.run_batch(**kwargs)

    outside = tmp_path / "outside"
    outside.mkdir()
    symlink_root = tmp_path / "symlink-output"
    symlink_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink or invalid component"):
        rollout.run_batch(**{**kwargs, "out_root": str(symlink_root)})
    assert list(outside.iterdir()) == []

    sentinel = outside / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink or invalid component"):
        rollout.run_batch(
            **{**kwargs, "out_root": str(parent / "link" / "escaped")}
        )
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
    assert set(outside.iterdir()) == {sentinel}


def test_v1_reflection_uses_bounded_projection_for_schema_valid_low_soft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = _materialize(tmp_path)
    adapter_module = _load_adapter(Path(manifest["env_package_dir"]), monkeypatch)
    adapter = object.__new__(adapter_module.JiphyeonjeonSearchAdapter)
    projection = build_reward_reflection_projection(
        {
            "hard": 1.0,
            "soft": 0.1,
            "invalid_reason": None,
            "metrics": {
                "ndcg_at_10": 0.1,
                "mrr_at_10": 0.2,
                "recall_at_10": 0.3,
                "intent_match": 1.0,
                "required_term_coverage": 0.4,
                "source_query_structure": 1.0,
                "anchored_ratio": 0.5,
                "unique_variant_ratio": 0.5,
                "schema_bound_field_ratio": 1.0,
                "non_drift_compactness": 0.6,
                "query_constraint_score": 0.4,
            },
            "evidence": {
                "emitted_variant_count": 1,
                "unique_variant_count": 1,
                "ranking_count": 1,
                "merged_document_count_at_10": 1,
            },
        }
    )
    result = adapter.reflect(
        [
            {
                "id": "must-not-appear",
                "hard": 1.0,
                "soft": 0.1,
                "reflection_projection": projection,
            }
        ],
        "private policy must not appear",
        str(tmp_path / "reflection"),
    )
    assert result and result[0]["batch_size"] == 1
    serialized = json.dumps(result, sort_keys=True)
    assert "ndcg_deficit" in serialized
    assert "query_constraint_deficit" in serialized
    assert "must-not-appear" not in serialized
    assert "private policy" not in serialized


@pytest.mark.parametrize(
    "relative_path",
    [
        "skillopt/envs/jiphyeonjeon_search/reward_runtime/reward_corpus.json",
        "skillopt/envs/jiphyeonjeon_search/reward_runtime/query_analysis_reward.py",
        "skillopt/envs/jiphyeonjeon_search/reward_runtime/query_analysis_contract.py",
        "configs/jiphyeonjeon_search/default.yaml",
    ],
)
def test_v1_manifest_and_runtime_fail_closed_on_generated_input_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
):
    manifest = _materialize(tmp_path)
    rollout = _load_rollout(Path(manifest["env_package_dir"]), monkeypatch)
    path = Path(manifest["output_dir"]) / relative_path
    path.write_bytes(path.read_bytes() + b"\n# tampered\n")
    with pytest.raises(ValidationError, match="generated file hash mismatch"):
        validate_skillopt_materialization_manifest_v1(manifest)
    if "reward_runtime" in relative_path:
        with pytest.raises(RuntimeError, match="reward runtime hash mismatch"):
            rollout._score_prediction(
                "{}",
                {"id": "synthetic-gnn-001", "reward_query_id": "synthetic-gnn-001"},
            )


def test_v1_contract_version_and_execution_identity_mutation_are_rejected(
    tmp_path: Path,
):
    manifest = _materialize(tmp_path)
    mutated = copy.deepcopy(manifest)
    mutated["reward_runtime"]["query_contract_versions"]["raw"] = "forged"
    with pytest.raises(ValidationError, match="query contract version drifted"):
        validate_skillopt_materialization_manifest_v1(mutated)

    mutated = copy.deepcopy(manifest)
    mutated["execution_identity"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="execution identity mismatch"):
        validate_skillopt_materialization_manifest_v1(mutated)

    mutated = copy.deepcopy(manifest)
    mutated["execution_status"] = "staged_executable"
    with pytest.raises(ValidationError, match="logical bundle routing drifted"):
        validate_skillopt_materialization_manifest_v1(mutated)


def test_v1_reward_corpus_splits_are_isolated_and_complete(tmp_path: Path):
    manifest = _materialize(tmp_path)
    split_root = Path(manifest["split_dir"])
    split_ids = {
        split: {
            item["id"]
            for item in json.loads(
                (split_root / split / "items.json").read_text(encoding="utf-8")
            )
        }
        for split in ("train", "selection", "test")
    }
    assert all(split_ids.values())
    assert split_ids["train"].isdisjoint(split_ids["selection"])
    assert split_ids["train"].isdisjoint(split_ids["test"])
    assert split_ids["selection"].isdisjoint(split_ids["test"])
    assert set().union(*split_ids.values()) == {
        item["query_id"] for item in load_reward_corpus(REWARD_CORPUS)["queries"]
    }
    assert (split_root / "selection/items.json").read_bytes() == (
        split_root / "val/items.json"
    ).read_bytes()
    split_manifest = json.loads(
        (split_root / "split_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["optimizer_split_mapping"] == OPTIMIZER_SPLIT_MAPPING
    assert split_manifest["logical_splits"] == OPTIMIZER_SPLIT_MAPPING
    assert split_manifest["materialization_aliases"] == {"selection": "val"}
    optimizer_test = json.loads(
        (split_root / "test/items.json").read_text(encoding="utf-8")
    )
    assert all(item["split"] == "test" for item in optimizer_test)
    assert all(item["logical_split"] == "optimizer_test" for item in optimizer_test)
    assert all(item["upstream_split"] == "test" for item in optimizer_test)


def test_v1_materializer_is_blind_to_external_release_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    sentinel = "G006_RELEASE_SENTINEL_7b2ee387_not_optimizer_visible"
    approval_root = tmp_path / "approval-only"
    approval_root.mkdir()
    release_manifest = approval_root / "release_manifest.json"
    release_manifest.write_text(
        json.dumps(
            {
                "release_path": f"/{sentinel}/items.json",
                "release_hash": f"sha256:{sentinel}",
                "holdout_generation": sentinel,
                "labels": [sentinel],
            }
        ),
        encoding="utf-8",
    )
    original_open = Path.open
    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text

    def deny_release_open(path: Path, *args, **kwargs):
        if path.resolve() == release_manifest.resolve():
            raise AssertionError("materializer must not read the release manifest")
        return original_open(path, *args, **kwargs)

    def deny_release_read_bytes(path: Path):
        if path.resolve() == release_manifest.resolve():
            raise AssertionError("materializer must not read release bytes")
        return original_read_bytes(path)

    def deny_release_read_text(path: Path, *args, **kwargs):
        if path.resolve() == release_manifest.resolve():
            raise AssertionError("materializer must not read release text")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_release_open)
    monkeypatch.setattr(Path, "read_bytes", deny_release_read_bytes)
    monkeypatch.setattr(Path, "read_text", deny_release_read_text)
    manifest = _materialize(tmp_path)

    serialized_contract = json.dumps(manifest, sort_keys=True)
    assert sentinel not in serialized_contract
    assert "release_manifest" not in manifest["source_hashes"]
    assert set(manifest["source_hashes"]) == {
        "dataset_file",
        "control_file",
        "baseline_skill_file",
        "reward_corpus_file",
        "reward_scorer_source",
        "query_contract_source",
    }
    for path in Path(manifest["output_dir"]).rglob("*"):
        if path.is_file():
            assert sentinel.encode("utf-8") not in original_read_bytes(path)

    generated_readme = (Path(manifest["output_dir"]) / "README.md").read_text(
        encoding="utf-8"
    )
    assert "stage_skillopt_search_benchmark_v1" in generated_readme
    assert "Copy or symlink" not in generated_readme


def test_v1_rejects_existing_or_symlink_output_without_outside_mutation(
    tmp_path: Path,
):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    output = tmp_path / "materialized"
    output.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValidationError, match="must not already exist|no-symlink"):
        materialize_skillopt_search_benchmark_v1(
            output_dir=output,
            dataset_path=DATASET,
            control_path=CONTROL,
            baseline_skill_path=BASELINE_SKILL,
        )
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
    assert set(outside.iterdir()) == {sentinel}


def test_v1_staging_binds_exact_checkout_and_dual_registration(tmp_path: Path):
    upstream = Path(
        os.environ.get(
            "SKILLOPT_V020_UPSTREAM_ROOT",
            "/private/tmp/skillopt-g003.P0eTFo/source",
        )
    )
    if not upstream.is_dir():
        pytest.skip("exact SkillOpt v0.2.0 checkout unavailable")
    logical = _materialize(tmp_path)
    staged = stage_skillopt_search_benchmark_v1(
        upstream_checkout=upstream,
        materialization_manifest=logical,
        staging_dir=tmp_path / "staged",
    )
    assert exported_stage_v1 is stage_skillopt_search_benchmark_v1
    assert staged["version"] == STAGING_VERSION
    validate_skillopt_staging_manifest_v1(staged)
    assert Path(staged["expected_best_skill"]).parent == Path(
        staged["train_out_root"]
    )
    for target in staged["registration_targets"]:
        source = (Path(staged["staging_dir"]) / target).read_text("utf-8")
        assert source.count('_ENV_REGISTRY["jiphyeonjeon_search"] =') == 1
        assert "conflicting jiphyeonjeon_search registry entry" in source
    config = Path(staged["config_path"]).read_text("utf-8")
    assert str(Path(staged["split_dir"])) in config
    assert str(Path(staged["initial_skill_path"])) in config
