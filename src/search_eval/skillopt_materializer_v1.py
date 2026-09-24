"""Materialize the v1 canonical-reward SkillOpt benchmark for paper search.

This module writes the files that the upstream Microsoft SkillOpt trainer expects
for a custom environment: split data, seed skill, env package, and YAML config.
It remains dev-only and does not import ``skillopt`` at runtime, so CI can verify
the integration without installing external optimizer dependencies.
"""

from __future__ import annotations

import json
import os
import shlex
import stat
import sys
import textwrap
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .skillopt_adapter import canonical_file_hash
from .skillopt_contract import (
    V1_ALLOWED_SCOPE,
    ValidationError,
    load_json,
    validate_dataset_contract,
    validate_execution_control,
)
from .query_analyzer_pilot import load_baseline_skill
from .query_analysis_reward import (
    ALGORITHM_VERSION,
    GATE_MIXED_WEIGHT,
    algorithm_identity,
    canonical_domain_hash,
    load_reward_corpus,
)
from app.QueryAgent.query_analysis_contract import (
    NORMALIZED_QUERY_ANALYSIS_VERSION,
    RAW_MODEL_OUTPUT_VERSION,
)

ENV_NAME = "jiphyeonjeon_search"
MATERIALIZATION_VERSION = "skillopt-search-benchmark-materialization-v1"
STAGING_VERSION = "skillopt-search-benchmark-staging-v1"
SKILLOPT_V020_EXACT_CHECKOUT_IDENTITY = (
    "sha256:21c466d5af0cced487939400c80d1d8c032ea4d574b18316a7a7e38b1cecea5b"
)
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REWARD_CORPUS_PATH = (
    _REPO_ROOT / "data/search_eval/skillopt_reward_corpus_v1.json"
)
_REWARD_SOURCE_PATH = Path(__file__).with_name("query_analysis_reward.py")
_QUERY_CONTRACT_SOURCE_PATH = _REPO_ROOT / "app/QueryAgent/query_analysis_contract.py"
_REWARD_RUNTIME_DIR = "reward_runtime"
OPTIMIZER_SPLIT_MAPPING = {
    "training": "train",
    "selection": "val",
    "optimizer_test": "test",
}


def materialize_skillopt_search_benchmark_v1(
    *,
    output_dir: str | Path,
    dataset_path: str | Path,
    control_path: str | Path,
    baseline_skill_path: str | Path,
    reward_corpus_path: str | Path = DEFAULT_REWARD_CORPUS_PATH,
) -> dict[str, Any]:
    """Write a SkillOpt-compatible benchmark tree and return its manifest."""
    output = Path(os.path.abspath(output_dir))
    dataset = load_json(dataset_path)
    control = load_json(control_path)
    baseline_skill = load_baseline_skill(baseline_skill_path)
    reward_corpus = load_reward_corpus(reward_corpus_path)
    validate_dataset_contract(dataset)
    validate_execution_control(control)
    if (
        control.get("scope") != V1_ALLOWED_SCOPE
        or control.get("fast_mode") is not False
        or control.get("use_llm_search") is not False
    ):
        raise ValidationError(
            "SkillOpt materialization requires standard QueryAnalyzer search scope only"
        )

    lease = _create_output_lease(output)
    try:
        return _materialize_with_lease(
            lease=lease,
            dataset=dataset,
            control=control,
            baseline_skill=baseline_skill,
            reward_corpus=reward_corpus,
            dataset_path=Path(dataset_path),
            control_path=Path(control_path),
            baseline_skill_path=Path(baseline_skill_path),
            reward_corpus_path=Path(reward_corpus_path),
        )
    finally:
        os.close(lease.root_fd)


class _OutputLease:
    def __init__(self, *, root: Path, root_fd: int) -> None:
        self.root = root
        self.root_fd = root_fd
        stat_result = os.fstat(root_fd)
        self.identity = (stat_result.st_dev, stat_result.st_ino)


def _create_output_lease(output: Path) -> _OutputLease:
    if output == Path(output.anchor):
        raise ValidationError("SkillOpt v1 output root cannot be the filesystem root")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    current_fd = os.open(output.anchor, directory_flags)
    try:
        for component in output.parent.parts[1:]:
            next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        try:
            os.mkdir(output.name, 0o700, dir_fd=current_fd)
        except FileExistsError as exc:
            raise ValidationError(
                "SkillOpt v1 output root must not already exist"
            ) from exc
        root_fd = os.open(output.name, directory_flags, dir_fd=current_fd)
        return _OutputLease(root=output, root_fd=root_fd)
    except OSError as exc:
        raise ValidationError(
            "SkillOpt v1 output root parent must be a real no-symlink directory"
        ) from exc
    finally:
        os.close(current_fd)


def _lease_relative(lease: _OutputLease, path: Path) -> tuple[str, ...]:
    absolute = Path(os.path.abspath(path))
    try:
        relative = absolute.relative_to(lease.root)
    except ValueError as exc:
        raise ValidationError("SkillOpt v1 write escaped the output root") from exc
    if not relative.parts or ".." in relative.parts:
        raise ValidationError("SkillOpt v1 write path is invalid")
    root_stat = os.fstat(lease.root_fd)
    if (root_stat.st_dev, root_stat.st_ino) != lease.identity:
        raise ValidationError("SkillOpt v1 output root lease rotated")
    try:
        named_root_stat = os.lstat(lease.root)
    except OSError as exc:
        raise ValidationError("SkillOpt v1 output root lease disappeared") from exc
    if (
        not stat.S_ISDIR(named_root_stat.st_mode)
        or (named_root_stat.st_dev, named_root_stat.st_ino) != lease.identity
    ):
        raise ValidationError("SkillOpt v1 output root name rotated")
    return relative.parts


def _secure_parent_fd(lease: _OutputLease, parts: tuple[str, ...]) -> int:
    directory_flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    current_fd = os.dup(lease.root_fd)
    try:
        for component in parts:
            try:
                os.mkdir(component, 0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError as exc:
        os.close(current_fd)
        raise ValidationError(
            "SkillOpt v1 output contains a symlink or unexpected path"
        ) from exc


def _secure_write(lease: _OutputLease, path: Path, payload: bytes) -> None:
    parts = _lease_relative(lease, path)
    parent_fd = _secure_parent_fd(lease, parts[:-1])
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(parts[-1], flags, 0o600, dir_fd=parent_fd)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise ValidationError(
            "SkillOpt v1 output write was not exclusive and contained"
        ) from exc
    finally:
        os.close(parent_fd)


def _materialize_with_lease(
    *,
    lease: _OutputLease,
    dataset: Mapping[str, Any],
    control: Mapping[str, Any],
    baseline_skill: str,
    reward_corpus: Mapping[str, Any],
    dataset_path: Path,
    control_path: Path,
    baseline_skill_path: Path,
    reward_corpus_path: Path,
) -> dict[str, Any]:
    output = lease.root

    split_root = output / "data" / f"{ENV_NAME}_split"
    env_root = output / "skillopt" / "envs" / ENV_NAME
    config_path = output / "configs" / ENV_NAME / "default.yaml"
    skill_path = env_root / "skills" / "initial.md"

    _write_split_files(lease, split_root, reward_corpus)
    reward_runtime = _write_env_package(
        lease,
        env_root,
        reward_corpus_path=Path(reward_corpus_path),
    )
    _secure_write(lease, skill_path, baseline_skill.encode("utf-8"))
    _secure_write(
        lease,
        config_path,
        _config_yaml(split_root=split_root, skill_path=skill_path).encode("utf-8"),
    )
    readme_path = output / "README.md"
    _secure_write(lease, readme_path, _readme(config_path=config_path).encode("utf-8"))

    generated_file_hashes = _generated_file_hashes(output)
    execution_binding = {
        "reward_runtime": reward_runtime,
        "optimizer_split_mapping": dict(OPTIMIZER_SPLIT_MAPPING),
        "source_hashes": {
            "reward_corpus_file": canonical_file_hash(reward_corpus_path),
            "reward_scorer_source": canonical_file_hash(_REWARD_SOURCE_PATH),
            "query_contract_source": canonical_file_hash(_QUERY_CONTRACT_SOURCE_PATH),
        },
        "generated_file_hashes": generated_file_hashes,
    }
    manifest = {
        "version": MATERIALIZATION_VERSION,
        "env_name": ENV_NAME,
        "scope": V1_ALLOWED_SCOPE,
        "output_dir": str(output),
        "config_path": str(config_path),
        "split_dir": str(split_root),
        "env_package_dir": str(env_root),
        "initial_skill_path": str(skill_path),
        "optimizer_split_mapping": dict(OPTIMIZER_SPLIT_MAPPING),
        "source_hashes": {
            "dataset_file": canonical_file_hash(dataset_path),
            "control_file": canonical_file_hash(control_path),
            "baseline_skill_file": canonical_file_hash(baseline_skill_path),
            "reward_corpus_file": canonical_file_hash(reward_corpus_path),
            "reward_scorer_source": canonical_file_hash(_REWARD_SOURCE_PATH),
            "query_contract_source": canonical_file_hash(_QUERY_CONTRACT_SOURCE_PATH),
        },
        "dataset_hash": dataset["dataset_hash"],
        "execution_control_hash": control["control_hash"],
        "reward_runtime": reward_runtime,
        "generated_file_hashes": generated_file_hashes,
        "execution_identity": canonical_domain_hash(
            "skillopt_materialized_execution_v1", execution_binding
        ),
        "execution_status": "logical_bundle_only",
        "staging_required": True,
    }
    _secure_write(
        lease,
        output / "skillopt_materialization_manifest.json",
        (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    validate_skillopt_materialization_manifest_v1(manifest)
    return manifest


def validate_skillopt_materialization_manifest_v1(manifest: Mapping[str, Any]) -> None:
    required = {
        "version",
        "env_name",
        "scope",
        "output_dir",
        "config_path",
        "split_dir",
        "env_package_dir",
        "initial_skill_path",
        "optimizer_split_mapping",
        "source_hashes",
        "dataset_hash",
        "execution_control_hash",
        "reward_runtime",
        "generated_file_hashes",
        "execution_identity",
        "execution_status",
        "staging_required",
    }
    if set(manifest) != required:
        raise ValidationError(
            "skillopt_materialization keys do not match the reward-bound contract"
        )
    if manifest.get("version") != MATERIALIZATION_VERSION:
        raise ValidationError("skillopt_materialization.version is invalid")
    if manifest.get("env_name") != ENV_NAME:
        raise ValidationError("skillopt_materialization.env_name is invalid")
    if manifest.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("skillopt_materialization.scope is invalid")
    if manifest.get("optimizer_split_mapping") != OPTIMIZER_SPLIT_MAPPING:
        raise ValidationError("skillopt_materialization optimizer split routing drifted")
    if (
        manifest.get("config_path")
        != str(
            Path(str(manifest.get("output_dir")))
            / "configs"
            / ENV_NAME
            / "default.yaml"
        )
        or manifest.get("execution_status") != "logical_bundle_only"
        or manifest.get("staging_required") is not True
    ):
        raise ValidationError("skillopt_materialization logical bundle routing drifted")
    source_hashes = manifest.get("source_hashes")
    expected_source_keys = {
        "dataset_file",
        "control_file",
        "baseline_skill_file",
        "reward_corpus_file",
        "reward_scorer_source",
        "query_contract_source",
    }
    if (
        not isinstance(source_hashes, Mapping)
        or set(source_hashes) != expected_source_keys
    ):
        raise ValidationError(
            "skillopt_materialization.source_hashes must bind all canonical inputs"
        )
    if any(
        not isinstance(value, str) or not value.startswith("sha256:")
        for value in source_hashes.values()
    ):
        raise ValidationError(
            "skillopt_materialization.source_hashes must be sha256 digests"
        )

    reward_runtime = manifest.get("reward_runtime")
    required_reward_keys = {
        "algorithm_version",
        "algorithm_identity",
        "corpus_hash",
        "corpus_relative_path",
        "corpus_file_hash",
        "canonical_scorer_source_hash",
        "emitted_scorer_hash",
        "query_contract_versions",
        "query_contract_source_hash",
        "emitted_query_contract_hash",
        "gate_metric",
        "gate_mixed_weight",
        "strict_tie_rejection",
    }
    if (
        not isinstance(reward_runtime, Mapping)
        or set(reward_runtime) != required_reward_keys
    ):
        raise ValidationError("skillopt_materialization.reward_runtime is invalid")
    if (
        reward_runtime.get("algorithm_version") != ALGORITHM_VERSION
        or reward_runtime.get("algorithm_identity") != algorithm_identity()
        or reward_runtime.get("gate_metric") != "mixed"
        or reward_runtime.get("gate_mixed_weight") != GATE_MIXED_WEIGHT
        or reward_runtime.get("strict_tie_rejection") is not True
    ):
        raise ValidationError("skillopt_materialization reward semantics drifted")
    if reward_runtime.get("query_contract_versions") != {
        "raw": RAW_MODEL_OUTPUT_VERSION,
        "normalized": NORMALIZED_QUERY_ANALYSIS_VERSION,
    }:
        raise ValidationError("skillopt_materialization query contract version drifted")
    if reward_runtime.get("canonical_scorer_source_hash") != source_hashes.get(
        "reward_scorer_source"
    ) or reward_runtime.get("query_contract_source_hash") != source_hashes.get(
        "query_contract_source"
    ):
        raise ValidationError(
            "skillopt_materialization canonical source hashes drifted"
        )

    generated = manifest.get("generated_file_hashes")
    if not isinstance(generated, Mapping) or not generated:
        raise ValidationError(
            "skillopt_materialization generated_file_hashes is invalid"
        )
    if any(
        not isinstance(path, str)
        or path.startswith("/")
        or ".." in Path(path).parts
        or not isinstance(digest, str)
        or not digest.startswith("sha256:")
        for path, digest in generated.items()
    ):
        raise ValidationError(
            "skillopt_materialization generated file binding is invalid"
        )
    expected_corpus_relative = (
        f"skillopt/envs/{ENV_NAME}/{_REWARD_RUNTIME_DIR}/reward_corpus.json"
    )
    scorer_relative = (
        f"skillopt/envs/{ENV_NAME}/{_REWARD_RUNTIME_DIR}/query_analysis_reward.py"
    )
    contract_relative = (
        f"skillopt/envs/{ENV_NAME}/{_REWARD_RUNTIME_DIR}/query_analysis_contract.py"
    )
    if (
        reward_runtime.get("corpus_relative_path") != expected_corpus_relative
        or reward_runtime.get("corpus_file_hash")
        != source_hashes.get("reward_corpus_file")
        or generated.get(expected_corpus_relative)
        != reward_runtime.get("corpus_file_hash")
        or generated.get(scorer_relative) != reward_runtime.get("emitted_scorer_hash")
        or generated.get(contract_relative)
        != reward_runtime.get("emitted_query_contract_hash")
        or reward_runtime.get("emitted_query_contract_hash")
        != reward_runtime.get("query_contract_source_hash")
    ):
        raise ValidationError(
            "skillopt_materialization reward runtime byte bindings drifted"
        )
    output = Path(str(manifest.get("output_dir")))
    _validate_optimizer_split_files(output / "data" / f"{ENV_NAME}_split")
    for relative_path, expected_hash in generated.items():
        path = output / relative_path
        try:
            path_stat = path.lstat()
            if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_nlink != 1:
                raise ValidationError(
                    "skillopt_materialization generated file is not an isolated regular file"
                )
            observed_hash = canonical_file_hash(path)
        except OSError as exc:
            raise ValidationError(
                "skillopt_materialization generated file is missing"
            ) from exc
        if observed_hash != expected_hash:
            raise ValidationError(
                "skillopt_materialization generated file hash mismatch"
            )

    execution_binding = {
        "reward_runtime": dict(reward_runtime),
        "optimizer_split_mapping": dict(OPTIMIZER_SPLIT_MAPPING),
        "source_hashes": {
            "reward_corpus_file": source_hashes["reward_corpus_file"],
            "reward_scorer_source": source_hashes["reward_scorer_source"],
            "query_contract_source": source_hashes["query_contract_source"],
        },
        "generated_file_hashes": dict(generated),
    }
    if manifest.get("execution_identity") != canonical_domain_hash(
        "skillopt_materialized_execution_v1", execution_binding
    ):
        raise ValidationError("skillopt_materialization execution identity mismatch")


def stage_skillopt_search_benchmark_v1(
    *,
    upstream_checkout: str | Path,
    materialization_manifest: Mapping[str, Any],
    staging_dir: str | Path,
) -> dict[str, Any]:
    """Create one contained, executable SkillOpt v0.2.0 staging tree.

    The materialization manifest describes a logical bundle.  This function is
    the only v1 boundary that advertises commands: it binds the exact upstream
    checkout, revalidates the bundle lease and hashes, installs both registry
    anchors, resolves the config inheritance inside the checkout, and creates
    isolated output roots before making every other staged file read-only.
    """
    validate_skillopt_materialization_manifest_v1(materialization_manifest)
    bundle_root = Path(str(materialization_manifest["output_dir"]))
    bundle_lease = _open_existing_directory_lease(bundle_root, "materialized bundle")
    upstream_root = Path(os.path.abspath(upstream_checkout))
    upstream_lease = _open_existing_directory_lease(upstream_root, "upstream checkout")
    stage = Path(os.path.abspath(staging_dir))
    stage_lease: _OutputLease | None = None
    try:
        _verify_existing_directory_lease(bundle_lease, "materialized bundle")
        validate_skillopt_materialization_manifest_v1(materialization_manifest)
        upstream_hashes = _directory_file_hashes(
            upstream_lease, reject_git=True, ignore_runtime_cache=True
        )
        upstream_identity = canonical_domain_hash(
            "skillopt_v020_exact_checkout", upstream_hashes
        )
        if upstream_identity != SKILLOPT_V020_EXACT_CHECKOUT_IDENTITY:
            raise ValidationError("SkillOpt upstream checkout is not exact pinned v0.2.0")

        stage_lease = _create_output_lease(stage)
        _copy_checkout_to_stage(
            source_lease=upstream_lease,
            destination_lease=stage_lease,
        )
        _copy_bundle_to_stage(
            bundle_lease=bundle_lease,
            destination_lease=stage_lease,
            generated_hashes=materialization_manifest["generated_file_hashes"],
        )

        staged_config = stage / "configs" / ENV_NAME / "default.yaml"
        staged_split = stage / "data" / f"{ENV_NAME}_split"
        staged_skill = stage / "skillopt" / "envs" / ENV_NAME / "skills" / "initial.md"
        _replace_staged_file(
            stage_lease,
            staged_config,
            _config_yaml(split_root=staged_split, skill_path=staged_skill).encode(
                "utf-8"
            ),
        )

        for relative_script in ("scripts/train.py", "scripts/eval_only.py"):
            script_path = stage / relative_script
            original = script_path.read_text(encoding="utf-8")
            patched = _patch_registry_source(original, script_name=relative_script)
            _replace_staged_file(stage_lease, script_path, patched.encode("utf-8"))

        train_out = stage / "outputs" / "train"
        eval_out = stage / "outputs" / "eval"
        _secure_make_directory(stage_lease, train_out)
        _secure_make_directory(stage_lease, eval_out)
        best_skill = train_out / "best_skill.md"
        train_argv = [
            sys.executable,
            "scripts/train.py",
            "--config",
            str(staged_config),
            "--out_root",
            str(train_out),
        ]
        eval_argv = [
            sys.executable,
            "scripts/eval_only.py",
            "--config",
            str(staged_config),
            "--skill",
            str(best_skill),
            "--split",
            "all",
            "--split_dir",
            str(staged_split),
            "--out_root",
            str(eval_out),
        ]
        staged_hashes = _directory_file_hashes(
            stage_lease,
            excluded_prefixes=("outputs/train", "outputs/eval"),
        )
        staging_binding = {
            "upstream_identity": upstream_identity,
            "logical_execution_identity": materialization_manifest["execution_identity"],
            "staged_file_hashes": staged_hashes,
            "optimizer_split_mapping": dict(OPTIMIZER_SPLIT_MAPPING),
            "train_argv": train_argv,
            "eval_argv": eval_argv,
            "train_out_root": str(train_out),
            "eval_out_root": str(eval_out),
        }
        manifest = {
            "version": STAGING_VERSION,
            "execution_status": "staged_executable",
            "staging_dir": str(stage),
            "upstream_identity": upstream_identity,
            "logical_execution_identity": materialization_manifest["execution_identity"],
            "staged_file_hashes": staged_hashes,
            "config_path": str(staged_config),
            "split_dir": str(staged_split),
            "env_package_dir": str(stage / "skillopt" / "envs" / ENV_NAME),
            "initial_skill_path": str(staged_skill),
            "optimizer_split_mapping": dict(OPTIMIZER_SPLIT_MAPPING),
            "train_argv": train_argv,
            "eval_argv": eval_argv,
            "train_command": shlex.join(train_argv),
            "eval_command": shlex.join(eval_argv),
            "train_out_root": str(train_out),
            "eval_out_root": str(eval_out),
            "expected_best_skill": str(best_skill),
            "registration_targets": ["scripts/train.py", "scripts/eval_only.py"],
            "staging_identity": canonical_domain_hash(
                "skillopt_staged_execution_v1", staging_binding
            ),
        }
        _secure_write(
            stage_lease,
            stage / ".jiphyeonjeon" / "staging_manifest.json",
            (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode(
                "utf-8"
            ),
        )
        _make_stage_immutable(stage, writable_roots=(train_out, eval_out))
        validate_skillopt_staging_manifest_v1(manifest)
        _verify_existing_directory_lease(upstream_lease, "upstream checkout")
        if (
            _directory_file_hashes(
                upstream_lease, reject_git=True, ignore_runtime_cache=True
            )
            != upstream_hashes
        ):
            raise ValidationError("SkillOpt upstream checkout changed during staging")
        _verify_existing_directory_lease(bundle_lease, "materialized bundle")
        validate_skillopt_materialization_manifest_v1(materialization_manifest)
        return manifest
    finally:
        os.close(upstream_lease.root_fd)
        os.close(bundle_lease.root_fd)
        if stage_lease is not None:
            os.close(stage_lease.root_fd)


def validate_skillopt_staging_manifest_v1(manifest: Mapping[str, Any]) -> None:
    """Fail closed if an executable v1 staging tree or its bindings drift."""
    required = {
        "version",
        "execution_status",
        "staging_dir",
        "upstream_identity",
        "logical_execution_identity",
        "staged_file_hashes",
        "config_path",
        "split_dir",
        "env_package_dir",
        "initial_skill_path",
        "optimizer_split_mapping",
        "train_argv",
        "eval_argv",
        "train_command",
        "eval_command",
        "train_out_root",
        "eval_out_root",
        "expected_best_skill",
        "registration_targets",
        "staging_identity",
    }
    if set(manifest) != required:
        raise ValidationError("SkillOpt staging manifest keys are invalid")
    if (
        manifest.get("version") != STAGING_VERSION
        or manifest.get("execution_status") != "staged_executable"
        or manifest.get("upstream_identity") != SKILLOPT_V020_EXACT_CHECKOUT_IDENTITY
        or manifest.get("registration_targets")
        != ["scripts/train.py", "scripts/eval_only.py"]
        or manifest.get("optimizer_split_mapping") != OPTIMIZER_SPLIT_MAPPING
    ):
        raise ValidationError("SkillOpt staging identity or registration drifted")
    stage = Path(str(manifest.get("staging_dir")))
    expected_config = stage / "configs" / ENV_NAME / "default.yaml"
    expected_split = stage / "data" / f"{ENV_NAME}_split"
    expected_env = stage / "skillopt" / "envs" / ENV_NAME
    expected_skill = expected_env / "skills" / "initial.md"
    expected_train_out = stage / "outputs" / "train"
    expected_eval_out = stage / "outputs" / "eval"
    expected_best = expected_train_out / "best_skill.md"
    if (
        manifest.get("config_path") != str(expected_config)
        or manifest.get("split_dir") != str(expected_split)
        or manifest.get("env_package_dir") != str(expected_env)
        or manifest.get("initial_skill_path") != str(expected_skill)
        or manifest.get("train_out_root") != str(expected_train_out)
        or manifest.get("eval_out_root") != str(expected_eval_out)
        or manifest.get("expected_best_skill") != str(expected_best)
    ):
        raise ValidationError("SkillOpt staged path routing drifted")
    lease = _open_existing_directory_lease(stage, "staging tree")
    try:
        observed = _directory_file_hashes(
            lease,
            excluded_prefixes=(
                ".jiphyeonjeon/staging_manifest.json",
                "outputs/train",
                "outputs/eval",
            ),
        )
        if observed != manifest.get("staged_file_hashes"):
            raise ValidationError("SkillOpt staged immutable file hash mismatch")
        _validate_optimizer_split_files(expected_split)
        train_argv = manifest.get("train_argv")
        eval_argv = manifest.get("eval_argv")
        if (
            not isinstance(train_argv, list)
            or not all(isinstance(value, str) for value in train_argv)
            or not isinstance(eval_argv, list)
            or not all(isinstance(value, str) for value in eval_argv)
            or manifest.get("train_command") != shlex.join(train_argv)
            or manifest.get("eval_command") != shlex.join(eval_argv)
            or train_argv
            != [
                sys.executable,
                "scripts/train.py",
                "--config",
                str(expected_config),
                "--out_root",
                str(expected_train_out),
            ]
            or eval_argv
            != [
                sys.executable,
                "scripts/eval_only.py",
                "--config",
                str(expected_config),
                "--skill",
                str(expected_best),
                "--split",
                "all",
                "--split_dir",
                str(expected_split),
                "--out_root",
                str(expected_eval_out),
            ]
        ):
            raise ValidationError("SkillOpt staged executable argv drifted")
        binding = {
            "upstream_identity": manifest["upstream_identity"],
            "logical_execution_identity": manifest["logical_execution_identity"],
            "staged_file_hashes": manifest["staged_file_hashes"],
            "optimizer_split_mapping": manifest["optimizer_split_mapping"],
            "train_argv": train_argv,
            "eval_argv": eval_argv,
            "train_out_root": manifest["train_out_root"],
            "eval_out_root": manifest["eval_out_root"],
        }
        if manifest.get("staging_identity") != canonical_domain_hash(
            "skillopt_staged_execution_v1", binding
        ):
            raise ValidationError("SkillOpt staging execution identity mismatch")
        from yaml import safe_load

        config = safe_load(Path(str(manifest["config_path"])).read_text("utf-8"))
        base_ref = config.get("_base_") if isinstance(config, Mapping) else None
        if not isinstance(base_ref, str):
            raise ValidationError("SkillOpt staged config base is missing")
        base_path = (Path(str(manifest["config_path"])).parent / base_ref).resolve()
        try:
            base_path.relative_to(stage.resolve())
        except ValueError as exc:
            raise ValidationError("SkillOpt staged config base escaped checkout") from exc
        if not base_path.is_file():
            raise ValidationError("SkillOpt staged config base is unresolved")
    finally:
        os.close(lease.root_fd)


def _open_existing_directory_lease(root: Path, label: str) -> _OutputLease:
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(root, flags)
    except OSError as exc:
        raise ValidationError(f"SkillOpt {label} must be a real directory") from exc
    return _OutputLease(root=root, root_fd=fd)


def _verify_existing_directory_lease(lease: _OutputLease, label: str) -> None:
    current = os.fstat(lease.root_fd)
    try:
        named = os.lstat(lease.root)
    except OSError as exc:
        raise ValidationError(f"SkillOpt {label} lease disappeared") from exc
    if (
        not stat.S_ISDIR(named.st_mode)
        or (current.st_dev, current.st_ino) != lease.identity
        or (named.st_dev, named.st_ino) != lease.identity
    ):
        raise ValidationError(f"SkillOpt {label} lease rotated")


def _directory_file_hashes(
    lease: _OutputLease,
    *,
    reject_git: bool = False,
    ignore_runtime_cache: bool = False,
    excluded_prefixes: tuple[str, ...] = (),
) -> dict[str, str]:
    _verify_existing_directory_lease(lease, "directory")
    hashes: dict[str, str] = {}
    for path in sorted(lease.root.rglob("*")):
        relative = path.relative_to(lease.root).as_posix()
        if any(relative == item or relative.startswith(item + "/") for item in excluded_prefixes):
            continue
        if ignore_runtime_cache and (
            "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        item_stat = path.lstat()
        if stat.S_ISLNK(item_stat.st_mode):
            raise ValidationError("SkillOpt directory contains a symlink")
        if stat.S_ISDIR(item_stat.st_mode):
            if reject_git and path.name == ".git":
                raise ValidationError("SkillOpt exact checkout must not contain Git metadata")
            continue
        if not stat.S_ISREG(item_stat.st_mode) or item_stat.st_nlink != 1:
            raise ValidationError("SkillOpt directory contains a non-isolated file")
        hashes[relative] = canonical_file_hash(path)
    _verify_existing_directory_lease(lease, "directory")
    return hashes


def _copy_checkout_to_stage(
    *, source_lease: _OutputLease, destination_lease: _OutputLease
) -> None:
    for relative in _directory_file_hashes(
        source_lease, reject_git=True, ignore_runtime_cache=True
    ):
        source = source_lease.root / relative
        payload = source.read_bytes()
        _secure_write(destination_lease, destination_lease.root / relative, payload)


def _copy_bundle_to_stage(
    *,
    bundle_lease: _OutputLease,
    destination_lease: _OutputLease,
    generated_hashes: Mapping[str, str],
) -> None:
    for relative, expected_hash in sorted(generated_hashes.items()):
        source = bundle_lease.root / relative
        if canonical_file_hash(source) != expected_hash:
            raise ValidationError("SkillOpt bundle changed during staging")
        destination = destination_lease.root / relative
        if destination.exists():
            raise ValidationError("SkillOpt bundle staging path collides with upstream")
        _secure_write(destination_lease, destination, source.read_bytes())


def _patch_registry_source(source: str, *, script_name: str) -> str:
    anchor = 'def _register_builtins() -> None:\n'
    if source.count(anchor) != 1:
        raise ValidationError(f"SkillOpt {script_name} registry anchor is ambiguous")
    registration = textwrap.indent(
        textwrap.dedent(
            f'''\
            from skillopt.envs.{ENV_NAME}.adapter import JiphyeonjeonSearchAdapter
            existing = _ENV_REGISTRY.get("{ENV_NAME}")
            if existing is not None and existing is not JiphyeonjeonSearchAdapter:
                raise RuntimeError("conflicting {ENV_NAME} registry entry")
            _ENV_REGISTRY["{ENV_NAME}"] = JiphyeonjeonSearchAdapter
            '''
        ),
        "    ",
    )
    return source.replace(anchor, anchor + registration, 1)


def _replace_staged_file(lease: _OutputLease, path: Path, payload: bytes) -> None:
    relative = _lease_relative(lease, path)
    parent_fd = _secure_parent_fd(lease, relative[:-1])
    flags = os.O_WRONLY | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(relative[-1], flags, dir_fd=parent_fd)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise ValidationError("SkillOpt staged file replacement failed closed") from exc
    finally:
        os.close(parent_fd)


def _secure_make_directory(lease: _OutputLease, path: Path) -> None:
    parts = _lease_relative(lease, path)
    fd = _secure_parent_fd(lease, parts)
    os.close(fd)


def _make_stage_immutable(stage: Path, *, writable_roots: tuple[Path, ...]) -> None:
    writable = {root.resolve() for root in writable_roots}
    for path in sorted(stage.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        resolved = path.resolve()
        if any(resolved == root or root in resolved.parents for root in writable):
            path.chmod(0o700 if path.is_dir() else 0o600)
        elif path.is_dir():
            path.chmod(0o555)
        else:
            path.chmod(0o444)
    stage.chmod(0o555)


def _write_split_files(
    lease: _OutputLease, split_root: Path, corpus: Mapping[str, Any]
) -> None:
    queries = sorted(corpus["queries"], key=lambda item: item["query_id"])
    if len(queries) < 3:
        raise ValidationError(
            "SkillOpt reward corpus requires at least three queries for isolated splits"
        )
    grouped = {"train": [], "selection": [], "test": []}
    selection_index = len(queries) - 2
    test_index = len(queries) - 1
    for index, item in enumerate(queries):
        split = (
            "selection"
            if index == selection_index
            else "test"
            if index == test_index
            else "train"
        )
        logical_split = {
            "train": "training",
            "selection": "selection",
            "test": "optimizer_test",
        }[split]
        upstream_split = OPTIMIZER_SPLIT_MAPPING[logical_split]
        grouped[split].append(
            {
                "id": item["query_id"],
                "reward_query_id": item["query_id"],
                "query": item["original_query"],
                "split": split,
                "logical_split": logical_split,
                "upstream_split": upstream_split,
                "group_id": item["query_id"],
                "intent": item["expected_intent"],
                "task_type": item["expected_intent"],
            }
        )
    for split, items in grouped.items():
        split_dir = split_root / split
        _secure_write(
            lease,
            split_dir / "items.json",
            (json.dumps(items, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
        )
    # Upstream SkillOpt SplitDataLoader expects train/val/test directories.
    # Preserve the domain contract name (`selection`) and mirror it as `val`
    # for live optimizer compatibility.
    val_dir = split_root / "val"
    _secure_write(
        lease,
        val_dir / "items.json",
        (json.dumps(grouped["selection"], indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        ),
    )
    split_manifest = {
        "version": "jiphyeonjeon_search_split_v1",
        "dataset": ENV_NAME,
        "logical_splits": dict(OPTIMIZER_SPLIT_MAPPING),
        "materialization_aliases": {"selection": "val"},
        "splits": {
            "train": {
                "count": len(grouped["train"]),
                "items_path": f"data/{ENV_NAME}_split/train/items.json",
            },
            "val": {
                "count": len(grouped["selection"]),
                "items_path": f"data/{ENV_NAME}_split/val/items.json",
            },
            "test": {
                "count": len(grouped["test"]),
                "items_path": f"data/{ENV_NAME}_split/test/items.json",
            },
        },
    }
    _secure_write(
        lease,
        split_root / "split_manifest.json",
        (json.dumps(split_manifest, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        ),
    )


def _validate_optimizer_split_files(split_root: Path) -> None:
    try:
        split_manifest = json.loads(
            (split_root / "split_manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("SkillOpt optimizer split manifest is invalid") from exc
    expected_paths = {
        physical: f"data/{ENV_NAME}_split/{physical}/items.json"
        for physical in ("train", "val", "test")
    }
    if (
        set(split_manifest)
        != {
            "version",
            "dataset",
            "logical_splits",
            "materialization_aliases",
            "splits",
        }
        or split_manifest.get("version") != "jiphyeonjeon_search_split_v1"
        or split_manifest.get("dataset") != ENV_NAME
        or split_manifest.get("logical_splits") != OPTIMIZER_SPLIT_MAPPING
        or split_manifest.get("materialization_aliases") != {"selection": "val"}
        or not isinstance(split_manifest.get("splits"), Mapping)
        or set(split_manifest["splits"]) != set(expected_paths)
    ):
        raise ValidationError("SkillOpt optimizer split routing is invalid")
    expected_logical = {
        "train": "training",
        "val": "selection",
        "test": "optimizer_test",
    }
    for physical, items_path in expected_paths.items():
        metadata = split_manifest["splits"].get(physical)
        try:
            items = json.loads(
                (split_root / physical / "items.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError("SkillOpt optimizer split items are invalid") from exc
        if (
            not isinstance(metadata, Mapping)
            or set(metadata) != {"count", "items_path"}
            or metadata.get("count") != len(items)
            or metadata.get("items_path") != items_path
            or not isinstance(items, list)
            or not items
            or any(
                not isinstance(item, Mapping)
                or item.get("logical_split") != expected_logical[physical]
                or item.get("upstream_split") != physical
                for item in items
            )
        ):
            raise ValidationError("SkillOpt optimizer split item metadata drifted")


def _write_env_package(
    lease: _OutputLease, env_root: Path, *, reward_corpus_path: Path
) -> dict[str, Any]:
    _secure_write(lease, env_root / "__init__.py", b"")
    reward_root = env_root / _REWARD_RUNTIME_DIR
    _secure_write(lease, reward_root / "__init__.py", b"")
    contract_bytes = _QUERY_CONTRACT_SOURCE_PATH.read_bytes()
    reward_source = _materialized_reward_source(
        _REWARD_SOURCE_PATH.read_text(encoding="utf-8")
    )
    corpus_bytes = reward_corpus_path.read_bytes()
    _secure_write(lease, reward_root / "query_analysis_contract.py", contract_bytes)
    _secure_write(
        lease, reward_root / "query_analysis_reward.py", reward_source.encode("utf-8")
    )
    _secure_write(
        lease,
        reward_root / "validation.py",
        (
            "class ValidationError(ValueError):\n"
            '    """Fail-closed materialized reward contract violation."""\n'
        ).encode("utf-8"),
    )
    _secure_write(lease, reward_root / "reward_corpus.json", corpus_bytes)
    runtime_hashes = {
        "corpus": canonical_file_hash(reward_root / "reward_corpus.json"),
        "scorer": canonical_file_hash(reward_root / "query_analysis_reward.py"),
        "query_contract": canonical_file_hash(
            reward_root / "query_analysis_contract.py"
        ),
        "validation": canonical_file_hash(reward_root / "validation.py"),
    }
    _secure_write(lease, env_root / "dataloader.py", _dataloader_py().encode("utf-8"))
    _secure_write(
        lease,
        env_root / "rollout.py",
        _rollout_py(runtime_hashes=runtime_hashes).encode("utf-8"),
    )
    _secure_write(lease, env_root / "adapter.py", _adapter_py().encode("utf-8"))
    corpus = load_reward_corpus(reward_root / "reward_corpus.json")
    return {
        "algorithm_version": ALGORITHM_VERSION,
        "algorithm_identity": algorithm_identity(),
        "corpus_hash": corpus["corpus_hash"],
        "corpus_relative_path": (
            f"skillopt/envs/{ENV_NAME}/{_REWARD_RUNTIME_DIR}/reward_corpus.json"
        ),
        "corpus_file_hash": runtime_hashes["corpus"],
        "canonical_scorer_source_hash": canonical_file_hash(_REWARD_SOURCE_PATH),
        "emitted_scorer_hash": runtime_hashes["scorer"],
        "query_contract_versions": {
            "raw": RAW_MODEL_OUTPUT_VERSION,
            "normalized": NORMALIZED_QUERY_ANALYSIS_VERSION,
        },
        "query_contract_source_hash": canonical_file_hash(_QUERY_CONTRACT_SOURCE_PATH),
        "emitted_query_contract_hash": runtime_hashes["query_contract"],
        "gate_metric": "mixed",
        "gate_mixed_weight": GATE_MIXED_WEIGHT,
        "strict_tie_rejection": True,
    }


def _materialized_reward_source(source: str) -> str:
    production_contract_import = "from app.QueryAgent.query_analysis_contract import ("
    local_contract_import = "from .query_analysis_contract import ("
    production_validation_import = "from .skillopt_contract import ValidationError"
    local_validation_import = "from .validation import ValidationError"
    if (
        source.count(production_contract_import) != 1
        or source.count(production_validation_import) != 1
    ):
        raise ValidationError("canonical reward source imports drifted")
    return source.replace(production_contract_import, local_contract_import, 1).replace(
        production_validation_import, local_validation_import, 1
    )


def _dataloader_py() -> str:
    return textwrap.dedent(
        '''
        from __future__ import annotations

        import json
        from pathlib import Path

        from skillopt.datasets.base import SplitDataLoader


        class JiphyeonjeonSearchDataLoader(SplitDataLoader):
            """Load paper-search SkillOpt items from split_dir JSON files."""

            def load_split_items(self, split_path: str) -> list[dict]:
                json_files = sorted(Path(split_path).glob("*.json"))
                if not json_files:
                    raise FileNotFoundError(f"No .json file found in {split_path}")
                with json_files[0].open(encoding="utf-8") as f:
                    raw = json.load(f)
                return [dict(item, id=str(item["id"])) for item in raw]
        '''
    ).lstrip()


def _rollout_py(*, runtime_hashes: Mapping[str, str]) -> str:
    source = textwrap.dedent(
        r"""
        from __future__ import annotations

        import hashlib
        import importlib
        import json
        import os
        from pathlib import Path

        from skillopt.model import chat_target
        from skillopt.model.backend_config import is_target_exec_backend
        from skillopt.model.codex_harness import run_target_exec

        _EXPECTED_RUNTIME_HASHES = __RUNTIME_HASHES__
        _RUNTIME_FILES = {
            "corpus": "reward_corpus.json",
            "scorer": "query_analysis_reward.py",
            "query_contract": "query_analysis_contract.py",
            "validation": "validation.py",
        }

        def _verified_reward_runtime():
            runtime_root = Path(__file__).with_name("reward_runtime")
            for name, filename in _RUNTIME_FILES.items():
                path = runtime_root / filename
                try:
                    payload = path.read_bytes()
                except OSError as exc:
                    raise RuntimeError(
                        f"materialized SkillOpt reward runtime missing: {name}"
                    ) from exc
                observed = "sha256:" + hashlib.sha256(payload).hexdigest()
                if observed != _EXPECTED_RUNTIME_HASHES[name]:
                    raise RuntimeError(
                        f"materialized SkillOpt reward runtime hash mismatch: {name}"
                    )
            module = importlib.import_module(
                ".reward_runtime.query_analysis_reward", package=__package__
            )
            corpus = module.load_reward_corpus(runtime_root / "reward_corpus.json")
            return module, corpus


        def _score_prediction_with_evidence(prediction: str, item: dict) -> dict:
            module, corpus = _verified_reward_runtime()
            evaluated = module.evaluate_query_analysis_reward_with_evidence(
                prediction,
                query_id=str(item["reward_query_id"]),
                corpus=corpus,
            )
            evaluated["sealed_evidence"] = module.validate_sealed_reward_evidence(
                evaluated["sealed_evidence"]
            )
            return evaluated


        def _score_prediction(prediction: str, item: dict) -> dict:
            return _score_prediction_with_evidence(prediction, item)["reward"]


        def _canonical_json_bytes(value: dict) -> bytes:
            return (
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")


        def _open_evidence_directory(out_root: str) -> int:
            root = Path(os.path.abspath(out_root))
            if root == Path(root.anchor):
                raise RuntimeError("sealed evidence output root cannot be the filesystem root")
            directory_flags = os.O_RDONLY | os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                directory_flags |= os.O_NOFOLLOW
            current_fd = os.open(root.anchor, directory_flags)
            try:
                for component in root.parts[1:]:
                    try:
                        os.mkdir(component, 0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                    next_fd = os.open(component, directory_flags, dir_fd=current_fd)
                    os.close(current_fd)
                    current_fd = next_fd
                try:
                    os.mkdir("sealed_evidence", 0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                return os.open("sealed_evidence", directory_flags, dir_fd=current_fd)
            except OSError as exc:
                raise RuntimeError(
                    "sealed evidence output path contains a symlink or invalid component"
                ) from exc
            finally:
                os.close(current_fd)


        def _exclusive_atomic_write(parent_fd: int, name: str, payload: bytes) -> None:
            if not name or name in {".", ".."} or "/" in name or "\\" in name:
                raise RuntimeError("sealed evidence filename is invalid")
            temporary = f".{name}.{os.getpid()}.tmp"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = None
            try:
                fd = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("short sealed evidence write")
                    view = view[written:]
                os.fsync(fd)
                os.close(fd)
                fd = None
                os.link(
                    temporary,
                    name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                os.unlink(temporary, dir_fd=parent_fd)
                os.fsync(parent_fd)
            except OSError as exc:
                if fd is not None:
                    os.close(fd)
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except OSError:
                    pass
                raise RuntimeError(
                    "sealed evidence write was not exclusive, atomic, and contained"
                ) from exc


        def _persist_sealed_evidence(out_root: str, evidence_rows: list[dict]) -> None:
            if len(evidence_rows) > 4096:
                raise RuntimeError("sealed evidence batch exceeds bounded index")
            module, _corpus = _verified_reward_runtime()
            evidence_fd = _open_evidence_directory(out_root)
            try:
                entries = []
                for ordinal, row in enumerate(evidence_rows):
                    evidence = module.validate_sealed_reward_evidence(row)
                    identity = evidence["evidence_identity"]
                    identity_token = identity.removeprefix("sha256:")
                    filename = f"{ordinal:04d}-{identity_token}.json"
                    payload = _canonical_json_bytes(evidence)
                    _exclusive_atomic_write(evidence_fd, filename, payload)
                    entries.append(
                        {
                            "ordinal": ordinal,
                            "relative_path": filename,
                            "evidence_identity": identity,
                            "file_hash": "sha256:" + hashlib.sha256(payload).hexdigest(),
                        }
                    )
                index = {
                    "version": "skillopt-sealed-evidence-index-v1",
                    "count": len(entries),
                    "entries": entries,
                }
                _exclusive_atomic_write(
                    evidence_fd, "index.json", _canonical_json_bytes(index)
                )
            finally:
                os.close(evidence_fd)


        def _upstream_gate_components(reward: dict) -> tuple[float, float]:
            module, _corpus = _verified_reward_runtime()
            hard = module.round_half_even_12(reward["hard"])
            canonical_mixed = module.mixed_gate_score(
                hard=hard,
                soft=reward["soft"],
                weight=module.GATE_MIXED_WEIGHT,
            )
            weight = module.GATE_MIXED_WEIGHT
            soft = (canonical_mixed - (1.0 - weight) * hard) / weight
            if (1.0 - weight) * hard + weight * soft != canonical_mixed:
                raise RuntimeError("upstream mixed-gate pre-rounding is not exact")
            return hard, soft


        def _rollout_one(item: dict, skill_content: str, *, max_completion_tokens: int, exec_timeout: int, evidence_sink: list[dict] | None = None) -> dict:
            user = (
                "Analyze this Jiphyeonjeon paper-search query for the standard QueryAnalyzer path.\\n"
                "Return strict JSON matching raw_model_output_v1 with is_academic, intent, "
                "keywords, improved_query, confidence, and source_queries. "
                "source_queries must include arxiv, dblp, and google_scholar; optional "
                "core_concepts, research_area, search_strategy, search_filters, and "
                "scholar_queries must follow the same strict contract.\\n\\n"
                f"Query: {item['query']}\\n"
                f"Intent: {item.get('intent', '')}\\n"
                "Do not request tools, network access, HyDE, use_llm_search, or "
                "RelevanceFilter changes."
            )
            if is_target_exec_backend():
                prompt = f"{skill_content}\n\n{user}\n\nReturn only the requested JSON."
                prediction, _raw = run_target_exec(
                    work_dir=os.getcwd(),
                    prompt=prompt,
                    model="",
                    timeout=exec_timeout,
                    allow_file_edits=False,
                )
            else:
                prediction, _usage = chat_target(
                    system=skill_content,
                    user=user,
                    max_completion_tokens=max_completion_tokens,
                )
            evaluated = _score_prediction_with_evidence(prediction, item)
            reward = evaluated["reward"]
            if evidence_sink is not None:
                evidence_sink.append(evaluated["sealed_evidence"])
            hard, soft = _upstream_gate_components(reward)
            module, _corpus = _verified_reward_runtime()
            reflection_projection = module.build_reward_reflection_projection(reward)
            task_id = str(item["id"])
            invalid_reason = reward["invalid_reason"]
            if hard:
                fail_reason = ""
            elif invalid_reason == "forbidden_or_scope_directive":
                fail_reason = "forbidden_or_scope_directive"
            elif str(invalid_reason or "").startswith("invalid_schema_or_json:"):
                fail_reason = "invalid_schema_or_json"
            else:
                fail_reason = "hard_gate_failed"
            return {
                "id": task_id,
                "hard": hard,
                "soft": soft,
                "fail_reason": fail_reason,
                "n_turns": 1,
                "reflection_projection": reflection_projection,
            }


        def run_batch(*, items: list[dict], skill_content: str, out_root: str, workers: int = 4, max_completion_tokens: int = 4096, exec_timeout: int = 600) -> list[dict]:
            del workers
            evidence_rows = []
            results = [
                _rollout_one(
                    item,
                    skill_content,
                    max_completion_tokens=max_completion_tokens,
                    exec_timeout=exec_timeout,
                    evidence_sink=evidence_rows,
                )
                for item in items
            ]
            _persist_sealed_evidence(out_root, evidence_rows)
            return results
        """
    ).lstrip()
    return source.replace(
        "__RUNTIME_HASHES__",
        json.dumps(dict(runtime_hashes), sort_keys=True, ensure_ascii=True),
        1,
    )


def _adapter_py() -> str:
    return textwrap.dedent(
        '''
        from __future__ import annotations

        from skillopt.datasets.base import BatchSpec
        from skillopt.envs.base import EnvAdapter
        from skillopt.envs.jiphyeonjeon_search.dataloader import JiphyeonjeonSearchDataLoader
        from skillopt.envs.jiphyeonjeon_search.rollout import run_batch


        class JiphyeonjeonSearchAdapter(EnvAdapter):
            """SkillOpt adapter for Jiphyeonjeon standard paper search."""

            def __init__(self, split_dir: str = "", data_path: str = "", split_mode: str = "split_dir", split_ratio: str = "3:1:1", split_seed: int = 42, split_output_dir: str = "", workers: int = 4, analyst_workers: int = 4, failure_only: bool = False, minibatch_size: int = 4, edit_budget: int = 4, seed: int = 42, limit: int = 0, max_completion_tokens: int = 2048, exec_timeout: int = 600) -> None:
                self.workers = workers
                self.analyst_workers = analyst_workers
                self.failure_only = failure_only
                self.minibatch_size = minibatch_size
                self.edit_budget = edit_budget
                self.max_completion_tokens = int(max_completion_tokens)
                self.exec_timeout = int(exec_timeout)
                self.dataloader = JiphyeonjeonSearchDataLoader(split_dir=split_dir, data_path=data_path, split_mode=split_mode, split_ratio=split_ratio, split_seed=split_seed, split_output_dir=split_output_dir, seed=seed, limit=limit)

            def setup(self, cfg: dict) -> None:
                super().setup(cfg)
                self.dataloader.setup(cfg)

            def get_dataloader(self):
                return self.dataloader

            def build_env_from_batch(self, batch: BatchSpec, **kwargs):
                return list(batch.payload or [])

            def build_train_env(self, batch_size: int, seed: int, **kwargs):
                batch = self.dataloader.build_train_batch(batch_size=batch_size, seed=seed, **kwargs)
                return self.build_env_from_batch(batch, **kwargs)

            def build_eval_env(self, env_num: int, split: str, seed: int, **kwargs):
                batch = self.dataloader.build_eval_batch(env_num=env_num, split=split, seed=seed, **kwargs)
                return self.build_env_from_batch(batch, **kwargs)

            def rollout(self, env_manager, skill_content: str, out_dir: str, **kwargs) -> list[dict]:
                return run_batch(items=list(env_manager), skill_content=skill_content, out_root=out_dir, workers=self.workers, max_completion_tokens=self.max_completion_tokens, exec_timeout=self.exec_timeout)

            def reflect(self, results: list[dict], skill_content: str, out_dir: str, **kwargs) -> list[dict]:
                del skill_content, out_dir, kwargs
                projections = []
                for row in results:
                    projection = row.get("reflection_projection")
                    if not isinstance(projection, dict):
                        raise ValueError("missing bounded reward reflection projection")
                    if set(projection) != {"version", "categories", "hard", "soft", "components", "counts"}:
                        raise ValueError("unbounded reward reflection projection")
                    if projection["version"] != "query_analysis_reflection_projection_v1":
                        raise ValueError("reward reflection projection version drifted")
                    projections.append(projection)
                candidates = [
                    projection
                    for projection in projections
                    if float(projection["hard"]) < 1.0 or float(projection["soft"]) < 1.0
                ]
                if not candidates:
                    return []
                allowed = {
                    "forbidden_or_scope_directive",
                    "invalid_schema_or_json",
                    "hard_gate_failed",
                    "ndcg_deficit",
                    "mrr_deficit",
                    "recall_deficit",
                    "query_constraint_deficit",
                }
                allowed_components = {
                    "ndcg_at_10",
                    "mrr_at_10",
                    "recall_at_10",
                    "intent_match",
                    "required_term_coverage",
                    "source_query_structure",
                    "anchored_ratio",
                    "unique_variant_ratio",
                    "schema_bound_field_ratio",
                    "non_drift_compactness",
                    "query_constraint_score",
                }
                allowed_counts = {
                    "emitted_variant_count",
                    "unique_variant_count",
                    "ranking_count",
                    "merged_document_count_at_10",
                }
                categories = set()
                for projection in candidates:
                    projection_categories = projection["categories"]
                    components = projection["components"]
                    counts = projection["counts"]
                    if (
                        not isinstance(projection_categories, list)
                        or not isinstance(components, dict)
                        or set(components) != allowed_components
                        or not isinstance(counts, dict)
                        or set(counts) != allowed_counts
                        or any(
                            type(value) is not int or not 0 <= value <= 10
                            for value in counts.values()
                        )
                        or any(
                            type(value) not in {int, float}
                            or not 0.0 <= float(value) <= 1.0
                            for value in components.values()
                        )
                    ):
                        raise ValueError("unbounded reward reflection projection fields")
                    categories.update(str(value) for value in projection_categories)
                    for key, category in {
                        "ndcg_at_10": "ndcg_deficit",
                        "mrr_at_10": "mrr_deficit",
                        "recall_at_10": "recall_deficit",
                        "query_constraint_score": "query_constraint_deficit",
                    }.items():
                        value = components.get(key)
                        if type(value) not in {int, float} or not 0.0 <= float(value) <= 1.0:
                            raise ValueError("unbounded reward reflection metric component")
                        if float(value) < 1.0:
                            categories.add(category)
                categories = sorted(categories)
                if any(category not in allowed for category in categories):
                    raise ValueError("unbounded SkillOpt reflection failure category")
                average_hard = round(
                    sum(float(row["hard"]) for row in candidates)
                    / len(candidates),
                    12,
                )
                average_soft = round(
                    sum(float(row["soft"]) for row in candidates)
                    / len(candidates),
                    12,
                )
                category_directives = {
                    "forbidden_or_scope_directive": "Keep every emitted field retrieval-only and remove tool or scope directives.",
                    "invalid_schema_or_json": "Return one strict raw_model_output_v1 JSON object with all required fields.",
                    "hard_gate_failed": "Preserve the original research intent in compact source-specific queries.",
                    "ndcg_deficit": "Improve graded top-ten ordering while preserving the query scope.",
                    "mrr_deficit": "Place the first relevant paper earlier with precise source queries.",
                    "recall_deficit": "Cover more relevant papers using compact complementary query variants.",
                    "query_constraint_deficit": "Strengthen intent, required-term, source-structure, and compactness constraints.",
                }
                content = "\\n".join(
                    ["", "## Deterministic reward feedback"]
                    + [f"- {category_directives[category]}" for category in categories]
                )
                return [{
                    "patch": {
                        "edits": [{"op": "append", "content": content}],
                        "reasoning": (
                            f"categories={','.join(categories)};"
                            f"hard={average_hard:.12f};soft={average_soft:.12f}"
                        ),
                    },
                    "source_type": "failure",
                    "batch_size": len(candidates),
                }]

            def get_task_types(self) -> list[str]:
                seen = []
                for item in self.dataloader.train_items + self.dataloader.val_items + self.dataloader.test_items:
                    task_type = str(item.get("task_type") or "paper_search")
                    if task_type not in seen:
                        seen.append(task_type)
                return seen or ["paper_search"]
        '''
    ).lstrip()


def _config_yaml(*, split_root: Path, skill_path: Path) -> str:
    return textwrap.dedent(
        f"""
        _base_: ../_base_/default.yaml
        model:
          reasoning_effort: medium
        train:
          batch_size: 4
          accumulation: 1
          num_epochs: 4
        gradient:
          minibatch_size: 4
          merge_batch_size: 4
        optimizer:
          learning_rate: 4
          min_learning_rate: 1
          lr_scheduler: constant
          lr_control_mode: fixed
          skill_update_mode: patch
          use_slow_update: false
          use_meta_skill: false
          use_skill_aware_reflection: false
        evaluation:
          use_gate: true
          gate_metric: mixed
          gate_mixed_weight: 0.8
        env:
          name: {ENV_NAME}
          skill_init: {skill_path}
          split_mode: split_dir
          split_dir: {split_root}
          workers: 4
          max_completion_tokens: 2048
          exec_timeout: 600
          limit: 0
        """
    ).lstrip()


def _generated_file_hashes(output: Path) -> dict[str, str]:
    generated: dict[str, str] = {}
    for root_name in ("configs", "data", "skillopt"):
        root = output / root_name
        for path in sorted(
            candidate for candidate in root.rglob("*") if candidate.is_file()
        ):
            relative = path.relative_to(output).as_posix()
            generated[relative] = canonical_file_hash(path)
    if not generated:
        raise ValidationError("SkillOpt materialization generated no execution files")
    return generated


def _registration_snippet() -> str:
    return textwrap.dedent(
        """
        try:
            from skillopt.envs.jiphyeonjeon_search.adapter import JiphyeonjeonSearchAdapter
            _ENV_REGISTRY["jiphyeonjeon_search"] = JiphyeonjeonSearchAdapter
        except ImportError:
            pass
        """
    ).strip()


def _readme(*, config_path: Path) -> str:
    return textwrap.dedent(
        f"""
        # Jiphyeonjeon SkillOpt Search Benchmark

        Generated dev-only benchmark for Microsoft SkillOpt.

        This directory is a logical, non-executable bundle. Do not copy or symlink
        files into an upstream checkout and do not run `{config_path}` directly.

        Create the hermetic executable checkout only with
        `stage_skillopt_search_benchmark_v1(...)`, passing the exact pinned upstream
        checkout, this bundle's validated manifest, and a new staging directory.
        Run only the returned `train_argv` and `eval_argv`. The upstream physical
        `test/` directory is the optimizer-visible logical `optimizer_test` split;
        it is not the independent release holdout used by approval.
        """
    ).lstrip()
