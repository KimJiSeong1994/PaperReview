from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.search_eval import skillopt_compatibility as compat
from src.search_eval.skillopt_compatibility import (
    APPROVED_ARCHIVE_SHA256,
    APPROVED_FILE_ENTRIES,
    APPROVED_SOURCE_INVENTORY_IDENTITY,
    APPROVED_PEELED_COMMIT,
    APPROVED_TAG_OBJECT,
    APPROVED_TREE_GIT_SHA1,
    CANONICAL_PYTHON_INTERPRETER,
    CANONICAL_RENDERED_CONFIG_BYTES,
    CANONICAL_SPLIT_ITEM_BYTES,
    CANONICAL_SPLIT_MANIFEST_BYTES,
    BASE_CONFIG_SHA256,
    CANDIDATE_PATH,
    CONFIG_SHA256,
    EVAL_ARGV,
    EVAL_OUT_ROOT,
    EVAL_REGISTRY_SHA256,
    EXPECTED_EVIDENCE_CEILING,
    LOADER_PATH,
    OVERLAY_IMMUTABLE_OBJECT_VERSION,
    OVERLAY_MANIFEST_VERSION,
    OVERLAY_SCHEMA_NAME,
    OVERLAY_SCHEMA_BYTES,
    PHASE0_READY_ERROR,
    PRISTINE_SOURCE_MANIFEST_VERSION,
    PROFILE_CATALOG_VERSION,
    PROFILE_CONFIG_BASE,
    PROFILE_CONFIG_PATH,
    PROFILE_ID,
    QUERY_ANALYZER_CONTRACT_BYTES,
    QUERY_ANALYZER_CONTRACT_NAME,
    QUERY_ANALYZER_SOURCE_PATH,
    REGISTRY_PATCH_CONTRACT,
    REGISTRY_PATCH_CONTRACT_BYTES,
    REGISTRY_PATCH_CONTRACT_NAME,
    REGISTRY_PATCH_INSERTION,
    REGISTRY_PATCH_OPERATION_ID,
    REGISTRY_PATCH_PATHS,
    REQUIRED_IMPORTED_MODULES,
    REQUIRED_PROJECTED_INPUT_PATHS,
    RUNNER_IDENTITY_VERSION,
    SAME_DOMAIN_CUSTODY_EVIDENCE_VERSION,
    SKILL_INIT_PATH,
    SPLIT_DIR,
    SPLIT_MANIFEST_PATH,
    SPLIT_TEST_ITEMS_PATH,
    SPLIT_TRAIN_ITEMS_PATH,
    SPLIT_VAL_ITEMS_PATH,
    SOURCE_INVENTORY_PATH,
    SOURCE_INVENTORY_VERSION,
    SOURCE_IMMUTABLE_OBJECT_VERSION,
    STAGING_MANIFEST_VERSION,
    TRAIN_ARGV,
    TRAIN_OUT_ROOT,
    TRAIN_REGISTRY_SHA256,
    APPROVED_RUNNER_IMAGE_DIGEST,
    APPROVED_RUNNER_INTERPRETER,
    APPROVED_RUNNER_SBOM_SHA256,
    acquire_approved_source_tree_lease,
    acquire_diagnostic_staging_tree_lease,
    acquire_manifest_tree_lease,
    acquire_trusted_overlay_tree_lease,
    acquire_trusted_staging_tree_lease,
    apply_registry_patch,
    compatibility_readiness_errors,
    domain_separated_hash,
    load_compatibility_catalog,
    manifest_tree_identity,
    require_compatibility_ready,
    seal_identity_artifact,
    validate_file_entries,
    validate_overlay_manifest,
    validate_posix_relative_path,
    validate_pristine_source_manifest,
    validate_profile_catalog,
    validate_runner_identity,
    validate_query_analyzer_contract_bytes,
    validate_registry_patch_result,
    validate_same_domain_custody_evidence,
    validate_staging_manifest,
    verify_manifest_tree,
    verify_query_analyzer_source,
)
from src.search_eval.skillopt_contract import ValidationError


CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "data/search_eval/skillopt_compatibility_profiles_v1.json"
)
UPSTREAM_ROOT_ENV = "SKILLOPT_V020_UPSTREAM_ROOT"
DEVELOPER_UPSTREAM_ROOT = Path("/private/tmp/skillopt-v020-review")


def _catalog() -> dict:
    return load_compatibility_catalog(CATALOG_PATH)


def _profile() -> dict:
    return _catalog()["profiles"][PROFILE_ID]


def _exact_upstream_root() -> Path:
    configured = os.environ.get(UPSTREAM_ROOT_ENV)
    root = Path(configured) if configured else DEVELOPER_UPSTREAM_ROOT
    if not root.exists() and configured is None:
        pytest.skip(
            f"set {UPSTREAM_ROOT_ENV} to an exact Microsoft SkillOpt v0.2.0 checkout"
        )
    assert root.is_dir(), f"{UPSTREAM_ROOT_ENV} is not a directory: {root}"
    for script_path in REGISTRY_PATCH_PATHS:
        contract = REGISTRY_PATCH_CONTRACT["patches"][script_path]
        source = root / script_path
        assert source.is_file(), f"wrong SkillOpt checkout: missing {script_path}"
        payload = source.read_bytes()
        assert len(payload) == contract["base_size_bytes"], (
            f"wrong SkillOpt checkout size for {script_path}"
        )
        assert _sha(payload) == contract["base_sha256"], (
            f"wrong SkillOpt checkout hash for {script_path}"
        )
    return root


def _golden_hash(artifact_version: str, value: object) -> str:
    body = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    digest = hashlib.sha256(
        b"skillopt:" + artifact_version.encode("ascii") + b"\x00" + body
    ).hexdigest()
    return f"sha256:{digest}"


def _entry(path: str, payload: bytes) -> dict:
    return {
        "path": path,
        "kind": "file",
        "mode": "0644",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _assert_live_query_analysis_contract(
    result: dict, branch_name: str, *, expected_key_set: str = "allowed_keys"
) -> None:
    contract = compat.QUERY_ANALYZER_CONTRACT
    normalized = contract["normalized_query_analysis_v1"]
    branch = contract["production_normalization_v1"]["branches"][branch_name]
    result_keys = set(result)
    source_query_keys = set(result["source_queries"])

    assert expected_key_set in {"allowed_keys", "required_keys"}
    assert result_keys == set(branch[expected_key_set])
    assert set(branch["required_keys"]) <= result_keys
    assert set(branch["absent_keys"]).isdisjoint(result_keys)
    assert set(branch["allowed_keys"]) | set(branch["absent_keys"]) == set(
        normalized["fields"]
    )
    assert source_query_keys == set(branch["source_query_allowed_keys"])
    assert set(branch["source_query_required_keys"]) <= source_query_keys
    assert set(branch["source_query_absent_keys"]).isdisjoint(source_query_keys)
    assert set(branch["source_query_allowed_keys"]) | set(
        branch["source_query_absent_keys"]
    ) == set(normalized["fields"]["source_queries"]["fields"])

    assert type(result["is_academic"]) is bool
    assert isinstance(result["intent"], str)
    assert isinstance(result["keywords"], list)
    assert isinstance(result["improved_query"], str)
    assert isinstance(result["search_filters"], dict)
    assert type(result["confidence"]) is float
    assert isinstance(result["original_query"], str)
    assert isinstance(result["source_queries"], dict)
    if "analysis_details" in result:
        assert isinstance(result["analysis_details"], str)
    if "core_concepts" in result:
        assert isinstance(result["core_concepts"], list)
    if "research_area" in result:
        assert isinstance(result["research_area"], str)
    if "search_strategy" in result:
        assert isinstance(result["search_strategy"], str)
    if "scholar_queries" in result["source_queries"]:
        assert isinstance(result["source_queries"]["scholar_queries"], list)


def _logical(name: str, path: str, payload: bytes, projection: str) -> dict:
    return {"name": name, **_entry(path, payload), "projection": projection}


def _argv_identity(kind: str, argv: list[str]) -> str:
    return domain_separated_hash(f"{STAGING_MANIFEST_VERSION}:{kind}_argv", argv)


def _execution_config(rendered_config_sha256: str) -> dict:
    return {
        "relative_config_path": PROFILE_CONFIG_PATH,
        "relative_config_base": PROFILE_CONFIG_BASE,
        "loader_path": LOADER_PATH,
        "loader_sha256": CONFIG_SHA256,
        "rendered_config_sha256": rendered_config_sha256,
        "compatibility_modes": ["hard", "mixed", "soft"],
        "train_out_root": TRAIN_OUT_ROOT,
        "eval_out_root": EVAL_OUT_ROOT,
        "candidate_path": CANDIDATE_PATH,
        "train_argv": TRAIN_ARGV,
        "train_argv_identity": _argv_identity("train", TRAIN_ARGV),
        "eval_argv": EVAL_ARGV,
        "eval_argv_identity": _argv_identity("eval", EVAL_ARGV),
        "num_epochs": 1,
        "train_size": 3,
        "batch_size": 3,
        "minibatch_size": 1,
        "merge_batch_size": 1,
        "accumulation": 1,
        "seed": 42,
        "analyst_workers": 1,
        "skill_update_mode": "patch",
        "edit_budget": 1,
        "min_edit_budget": 1,
        "lr_scheduler": "constant",
        "lr_control_mode": "fixed",
        "use_slow_update": False,
        "use_meta_skill": False,
        "use_skill_aware_reflection": False,
        "gate_metric": "mixed",
        "gate_mixed_weight": 0.8,
        "sel_env_num": 2,
        "test_env_num": 2,
        "eval_test": True,
        "mock": True,
        "max_analyst_rounds": 1,
        "failure_only": True,
        "use_gate": True,
        "env_name": "jiphyeonjeon_search",
        "skill_init": SKILL_INIT_PATH,
        "split_mode": "split_dir",
        "split_dir": SPLIT_DIR,
        "workers": 1,
    }


def _reseal_profile(profile: dict) -> dict:
    clone = copy.deepcopy(profile)
    clone["identity"] = seal_identity_artifact(clone, PROFILE_CATALOG_VERSION)[
        "identity"
    ]
    return clone


def _reseal_catalog(profile: dict) -> dict:
    return seal_identity_artifact(
        {"version": PROFILE_CATALOG_VERSION, "profiles": {PROFILE_ID: profile}},
        PROFILE_CATALOG_VERSION,
    )


def _with_overlay_and_staging(profile: dict) -> dict:
    clone = copy.deepcopy(profile)
    payloads = {
        "skillopt/envs/jiphyeonjeon_search/adapter.py": (
            b"class JiphyeonjeonSearchAdapter:\n    env_name = 'jiphyeonjeon_search'\n"
        ),
        PROFILE_CONFIG_PATH: CANONICAL_RENDERED_CONFIG_BYTES,
        SKILL_INIT_PATH: (
            b"# Initial skill\n\nAnalyze query intent and retrieve grounded evidence.\n"
        ),
        SPLIT_MANIFEST_PATH: CANONICAL_SPLIT_MANIFEST_BYTES,
        SPLIT_TRAIN_ITEMS_PATH: CANONICAL_SPLIT_ITEM_BYTES["train"],
        SPLIT_VAL_ITEMS_PATH: CANONICAL_SPLIT_ITEM_BYTES["val"],
        SPLIT_TEST_ITEMS_PATH: CANONICAL_SPLIT_ITEM_BYTES["test"],
    }
    train_contract = REGISTRY_PATCH_CONTRACT["patches"]["scripts/train.py"]
    eval_contract = REGISTRY_PATCH_CONTRACT["patches"]["scripts/eval_only.py"]
    train_patch = {
        "path": "scripts/train.py",
        "kind": "file",
        "mode": "0644",
        "size_bytes": train_contract["result_size_bytes"],
        "sha256": train_contract["result_sha256"],
    }
    eval_patch = {
        "path": "scripts/eval_only.py",
        "kind": "file",
        "mode": "0644",
        "size_bytes": eval_contract["result_size_bytes"],
        "sha256": eval_contract["result_sha256"],
    }
    contract = _logical(
        QUERY_ANALYZER_CONTRACT_NAME,
        "overlay/contracts/query_analyzer_product_contract.json",
        QUERY_ANALYZER_CONTRACT_BYTES,
        "metadata",
    )
    schema = _logical(
        OVERLAY_SCHEMA_NAME,
        "overlay/schema/generated_overlay_schema.json",
        OVERLAY_SCHEMA_BYTES,
        "metadata",
    )
    registry_contract = _logical(
        REGISTRY_PATCH_CONTRACT_NAME,
        "overlay/contracts/registry_patch_contract.json",
        REGISTRY_PATCH_CONTRACT_BYTES,
        "metadata",
    )
    projected = [
        _logical(
            f"projected_{path.replace('/', '_').replace('.', '_')}",
            path,
            payloads[path],
            "staged",
        )
        for path in REQUIRED_PROJECTED_INPUT_PATHS
    ]
    logical_files = sorted(
        [contract, schema, registry_contract, *projected],
        key=lambda item: (item["name"], item["path"]),
    )
    overlay = seal_identity_artifact(
        {
            "version": OVERLAY_MANIFEST_VERSION,
            "profile_id": PROFILE_ID,
            "contract_sha256": contract["sha256"],
            "schema_sha256": schema["sha256"],
            "immutable_object_version": OVERLAY_IMMUTABLE_OBJECT_VERSION,
            "logical_files": logical_files,
        },
        OVERLAY_MANIFEST_VERSION,
    )

    pristine_by_path = {
        entry["path"]: entry for entry in clone["pristine_source_manifest"]["files"]
    }
    staged_by_path = {path: dict(entry) for path, entry in pristine_by_path.items()}
    staged_by_path["scripts/train.py"] = train_patch
    staged_by_path["scripts/eval_only.py"] = eval_patch
    for path in REQUIRED_PROJECTED_INPUT_PATHS:
        staged_by_path[path] = _entry(path, payloads[path])
    staged_tree = sorted(staged_by_path.values(), key=lambda item: item["path"])
    allowlisted_diff = sorted(
        [
            {
                "path": "scripts/train.py",
                "change": "modify",
                "before_sha256": pristine_by_path["scripts/train.py"]["sha256"],
                "after_sha256": train_patch["sha256"],
                "mode": "0644",
            },
            {
                "path": "scripts/eval_only.py",
                "change": "modify",
                "before_sha256": pristine_by_path["scripts/eval_only.py"]["sha256"],
                "after_sha256": eval_patch["sha256"],
                "mode": "0644",
            },
            {
                "path": "skillopt/envs/jiphyeonjeon_search/adapter.py",
                "change": "add",
                "before_sha256": None,
                "after_sha256": staged_by_path[
                    "skillopt/envs/jiphyeonjeon_search/adapter.py"
                ]["sha256"],
                "mode": "0644",
            },
            *[
                {
                    "path": path,
                    "change": "add",
                    "before_sha256": None,
                    "after_sha256": staged_by_path[path]["sha256"],
                    "mode": staged_by_path[path]["mode"],
                }
                for path in REQUIRED_PROJECTED_INPUT_PATHS
                if path != "skillopt/envs/jiphyeonjeon_search/adapter.py"
            ],
        ],
        key=lambda item: item["path"],
    )
    expected_modules = sorted(
        [
            {
                "module_path": "skillopt.config",
                "file_path": "skillopt/config.py",
                "sha256": CONFIG_SHA256,
            },
            {
                "module_path": "skillopt.envs.jiphyeonjeon_search.adapter",
                "file_path": "skillopt/envs/jiphyeonjeon_search/adapter.py",
                "sha256": staged_by_path[
                    "skillopt/envs/jiphyeonjeon_search/adapter.py"
                ]["sha256"],
            },
            {
                "module_path": "scripts.train",
                "file_path": "scripts/train.py",
                "sha256": train_patch["sha256"],
            },
            {
                "module_path": "scripts.eval_only",
                "file_path": "scripts/eval_only.py",
                "sha256": eval_patch["sha256"],
            },
        ],
        key=lambda item: (item["module_path"], item["file_path"]),
    )
    execution_config = _execution_config(staged_by_path[PROFILE_CONFIG_PATH]["sha256"])
    staging = seal_identity_artifact(
        {
            "version": STAGING_MANIFEST_VERSION,
            "pristine_source_identity": clone["pristine_source_manifest"]["identity"],
            "overlay_identity": overlay["identity"],
            "allowlisted_diff": allowlisted_diff,
            "staged_tree": staged_tree,
            "staged_tree_identity": manifest_tree_identity(staged_tree),
            "execution_config": execution_config,
            "execution_config_identity": domain_separated_hash(
                f"{STAGING_MANIFEST_VERSION}:execution_config", execution_config
            ),
            "train_registry_patch_sha256": train_patch["sha256"],
            "eval_registry_patch_sha256": eval_patch["sha256"],
            "registry_patches": [
                {"path": path, **dict(REGISTRY_PATCH_CONTRACT["patches"][path])}
                for path in REGISTRY_PATCH_PATHS
            ],
            "expected_imported_modules": expected_modules,
        },
        STAGING_MANIFEST_VERSION,
    )
    clone["overlay_manifest"] = overlay
    clone["staging_manifest"] = staging
    clone["evidence_ceiling"] = [
        diagnostic
        for diagnostic in clone["evidence_ceiling"]
        if diagnostic["code"] not in {"overlay_manifest", "staging_manifest"}
    ]
    return _reseal_profile(clone)


def _structurally_resolved_profile() -> dict:
    profile = _with_overlay_and_staging(_profile())
    staging = profile["staging_manifest"]
    dependency_lock_sha256 = _sha(
        b"pip-compile lock for skillopt compatibility fixture\n"
    )
    image_digest = APPROVED_RUNNER_IMAGE_DIGEST
    profile["full_dependency_lock"] = {
        "sha256": dependency_lock_sha256,
        "format": "pip-compile",
        "complete": True,
    }
    runner = seal_identity_artifact(
        {
            "version": RUNNER_IDENTITY_VERSION,
            "staging_identity": staging["identity"],
            "image_ref": "ghcr.io/microsoft/skillopt@" + image_digest,
            "image_digest": image_digest,
            "python_version": "3.11.9",
            "interpreter_path": CANONICAL_PYTHON_INTERPRETER,
            "interpreter_sha256": APPROVED_RUNNER_INTERPRETER["sha256"],
            "dependency_lock_sha256": dependency_lock_sha256,
            "sbom_sha256": APPROVED_RUNNER_SBOM_SHA256,
            "build_provenance_sha256": _sha(b"slsa provenance fixture\n"),
            "image_inventory": {
                "image_digest": image_digest,
                "sbom_sha256": APPROVED_RUNNER_SBOM_SHA256,
                "interpreters": [APPROVED_RUNNER_INTERPRETER],
            },
            "verifier_id": "paper-review-agent",
            "verifier_version": "2026.07.18",
        },
        RUNNER_IDENTITY_VERSION,
    )
    custody = seal_identity_artifact(
        {
            "version": SAME_DOMAIN_CUSTODY_EVIDENCE_VERSION,
            "subject_runner_identity": runner["identity"],
            "issuer_workload": "skillopt-build-workload",
            "issued_at": "2026-07-17T00:00:00Z",
            "expires_at": "2026-07-18T00:00:00Z",
            "source_immutable_object_version": SOURCE_IMMUTABLE_OBJECT_VERSION,
            "overlay_immutable_object_version": OVERLAY_IMMUTABLE_OBJECT_VERSION,
            "retention_mode": "governance-compliance",
            "acl_snapshot_sha256": _sha(b"custody acl snapshot fixture\n"),
            "runner_image_digest": runner["image_digest"],
            "verifier_id": runner["verifier_id"],
            "verifier_version": runner["verifier_version"],
            "verified": True,
            "immutable": True,
        },
        SAME_DOMAIN_CUSTODY_EVIDENCE_VERSION,
    )
    tested_patch = {
        "profile_id": PROFILE_ID,
        "staging_identity": staging["identity"],
        "runner_identity": runner["identity"],
        "report_identity": "sha256:" + _sha(b"tested patch report fixture\n"),
        "status": "passed",
        "imported_modules": staging["expected_imported_modules"],
        "outputs": {
            "train_out_root": TRAIN_OUT_ROOT,
            "eval_out_root": EVAL_OUT_ROOT,
            "candidate_path": CANDIDATE_PATH,
        },
        "provider_count": 0,
        "network_count": 0,
        "subprocess_count": 0,
        "config_identity": staging["execution_config_identity"],
        "train_argv_identity": staging["execution_config"]["train_argv_identity"],
        "eval_argv_identity": staging["execution_config"]["eval_argv_identity"],
        "observed_interpreter": {
            "path": runner["interpreter_path"],
            "python_version": runner["python_version"],
            "sha256": runner["interpreter_sha256"],
        },
        "verified": True,
    }
    profile["runner_identity"] = runner
    profile["custody_evidence"] = custody
    profile["tested_patch"] = tested_patch
    profile["evidence_ceiling"] = []
    return _reseal_profile(profile)


def _write_manifest_tree(
    root: Path, entries: list[dict], payloads: dict[str, bytes]
) -> None:
    for entry in entries:
        target = root / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payloads[entry["path"]])
        target.chmod(int(entry["mode"], 8))


def test_catalog_pins_null_overlay_and_staging_until_evidence_exists() -> None:
    profile = _profile()
    pristine = profile["pristine_source_manifest"]

    assert profile["overlay_manifest"] is None
    assert profile["staging_manifest"] is None
    assert pristine["fetched_at"] == "2026-07-18T00:00:00Z"
    assert pristine["immutable_object_version"] == SOURCE_IMMUTABLE_OBJECT_VERSION
    assert pristine["tag_object"] == APPROVED_TAG_OBJECT
    assert pristine["peeled_commit"] == APPROVED_PEELED_COMMIT
    assert pristine["tree_git_sha1"] == APPROVED_TREE_GIT_SHA1
    assert pristine["archive_sha256"] == APPROVED_ARCHIVE_SHA256
    assert {entry["path"]: entry for entry in pristine["files"]} == {
        entry["path"]: entry for entry in APPROVED_FILE_ENTRIES
    }
    assert len(pristine["files"]) == 311
    assert [diagnostic["code"] for diagnostic in profile["evidence_ceiling"]] == [
        "custody",
        "full_dependency_lock",
        "image_digest",
        "overlay_manifest",
        "staging_manifest",
        "tested_patch",
    ]


def test_source_inventory_identity_count_and_catalog_size_limit() -> None:
    inventory = json.loads(SOURCE_INVENTORY_PATH.read_text(encoding="utf-8"))

    assert SOURCE_INVENTORY_PATH.stat().st_size < 1_048_576
    assert CATALOG_PATH.stat().st_size < 1_048_576
    assert inventory["version"] == SOURCE_INVENTORY_VERSION
    assert inventory["identity"] == APPROVED_SOURCE_INVENTORY_IDENTITY
    assert inventory["tree_git_sha1"] == APPROVED_TREE_GIT_SHA1
    assert len(inventory["files"]) == 311
    assert inventory["files"] == list(APPROVED_FILE_ENTRIES)


def test_registry_insertion_core_transform_is_offline_and_bounded() -> None:
    synthetic = (
        b"_ENV_REGISTRY: dict[str, type] = {}\n\n"
        b"def _register_builtins() -> None:\n"
        b"    pass\n\n"
        b"def get_adapter(cfg: dict):\n"
        b"    _register_builtins()\n"
        b"    return _ENV_REGISTRY[cfg['env']]\n\n"
        b"def parse_args():\n"
        b"    pass\n\n"
        b"def main():\n"
        b"    pass\n\n"
        b"if __name__ == '__main__':\n"
        b"    main()\n"
    )

    transformed = compat._insert_registry_registration("synthetic.py", synthetic)
    offset = transformed.index(REGISTRY_PATCH_INSERTION)
    assert transformed[:offset] == synthetic[:offset]
    assert transformed[offset + len(REGISTRY_PATCH_INSERTION) :] == synthetic[offset:]
    assert transformed.replace(REGISTRY_PATCH_INSERTION, b"", 1) == synthetic
    with pytest.raises(ValidationError, match="already exists"):
        compat._insert_registry_registration("synthetic.py", transformed)


def test_registry_patch_is_exact_idempotent_and_byte_preserving() -> None:
    upstream_root = _exact_upstream_root()

    assert len(REGISTRY_PATCH_INSERTION) == 153
    for script_path in REGISTRY_PATCH_PATHS:
        contract = REGISTRY_PATCH_CONTRACT["patches"][script_path]
        base = (upstream_root / script_path).read_bytes()
        result = apply_registry_patch(script_path, base)

        assert contract == {
            "base_sha256": _sha(base),
            "base_size_bytes": len(base),
            "idempotent": True,
            "insertion_sha256": _sha(REGISTRY_PATCH_INSERTION),
            "insertion_size_bytes": 153,
            "operation_id": REGISTRY_PATCH_OPERATION_ID,
            "result_sha256": _sha(result),
            "result_size_bytes": len(result),
        }
        assert apply_registry_patch(script_path, result) == result
        validate_registry_patch_result(script_path, result)
        assert result.count(REGISTRY_PATCH_INSERTION) == 1

        offset = result.index(REGISTRY_PATCH_INSERTION)
        assert result[:offset] == base[:offset]
        assert result[offset + len(REGISTRY_PATCH_INSERTION) :] == base[offset:]
        assert result.replace(REGISTRY_PATCH_INSERTION, b"", 1) == base

        tree = ast.parse(result, filename=script_path)
        function_names = {
            node.name for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        assert {
            "_register_builtins",
            "get_adapter",
            "parse_args",
            "main",
        } <= function_names
        assert any(
            isinstance(node, ast.Name) and node.id == "_ENV_REGISTRY"
            for node in ast.walk(tree)
        )
        assert not any(
            isinstance(node, ast.Name) and node.id == "ENV_REGISTRY"
            for node in ast.walk(tree)
        )
        assert any(
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            for node in tree.body
        )


def test_registry_patch_rejects_every_noncanonical_input() -> None:
    upstream_root = _exact_upstream_root()
    train = (upstream_root / "scripts/train.py").read_bytes()
    patched = apply_registry_patch("scripts/train.py", train)

    with pytest.raises(ValidationError, match="base is not approved"):
        apply_registry_patch("scripts/train.py", train + b"\n")
    with pytest.raises(ValidationError, match="result is not approved"):
        validate_registry_patch_result("scripts/train.py", patched + b"\n")
    with pytest.raises(ValidationError, match="base is not approved"):
        apply_registry_patch(
            "scripts/train.py",
            b"print('train')\nENV_REGISTRY = {'jiphyeonjeon_search': object}\n",
        )
    with pytest.raises(ValidationError, match="unsupported"):
        apply_registry_patch("scripts/other.py", train)


def test_trusted_staged_byte_validation_checks_complete_registry_scripts() -> None:
    upstream_root = _exact_upstream_root()
    payloads = {
        PROFILE_CONFIG_PATH: CANONICAL_RENDERED_CONFIG_BYTES,
        SPLIT_MANIFEST_PATH: CANONICAL_SPLIT_MANIFEST_BYTES,
        SPLIT_TRAIN_ITEMS_PATH: CANONICAL_SPLIT_ITEM_BYTES["train"],
        SPLIT_VAL_ITEMS_PATH: CANONICAL_SPLIT_ITEM_BYTES["val"],
        SPLIT_TEST_ITEMS_PATH: CANONICAL_SPLIT_ITEM_BYTES["test"],
        **{
            script_path: apply_registry_patch(
                script_path, (upstream_root / script_path).read_bytes()
            )
            for script_path in REGISTRY_PATCH_PATHS
        },
    }

    class MemoryLease:
        def read_bytes(self, relative: str) -> bytes:
            return payloads[relative]

    execution_config = _execution_config(_sha(CANONICAL_RENDERED_CONFIG_BYTES))
    compat._validate_canonical_staged_bytes(MemoryLease(), execution_config)

    payloads["scripts/train.py"] = b"print('tiny arbitrary replacement')\n"
    with pytest.raises(ValidationError, match="result is not approved"):
        compat._validate_canonical_staged_bytes(MemoryLease(), execution_config)


def test_configured_upstream_root_fails_closed_on_wrong_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wrong_root = tmp_path / "wrong-skillopt"
    (wrong_root / "scripts").mkdir(parents=True)
    (wrong_root / "scripts/train.py").write_bytes(b"print('wrong')\n")
    (wrong_root / "scripts/eval_only.py").write_bytes(b"print('wrong')\n")
    monkeypatch.setenv(UPSTREAM_ROOT_ENV, str(wrong_root))

    with pytest.raises(AssertionError, match="wrong SkillOpt checkout"):
        _exact_upstream_root()


def test_source_inventory_loader_rejects_malformed_shapes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def write_inventory(files: object) -> None:
        inventory_path.write_text(
            json.dumps(
                {
                    "version": SOURCE_INVENTORY_VERSION,
                    "tree_git_sha1": APPROVED_TREE_GIT_SHA1,
                    "files": files,
                    "identity": APPROVED_SOURCE_INVENTORY_IDENTITY,
                }
            ),
            encoding="utf-8",
        )

    inventory_path = tmp_path / "inventory.json"
    monkeypatch.setattr(compat, "SOURCE_INVENTORY_PATH", inventory_path)

    write_inventory("not-a-list")
    with pytest.raises(ValidationError):
        compat._load_approved_source_inventory()

    files = [dict(entry) for entry in APPROVED_FILE_ENTRIES]
    files[0] = "not-an-object"
    write_inventory(files)
    with pytest.raises(ValidationError):
        compat._load_approved_source_inventory()

    files = [dict(entry) for entry in APPROVED_FILE_ENTRIES]
    files[0]["path"] = "../escape"
    write_inventory(files)
    with pytest.raises(ValidationError):
        compat._load_approved_source_inventory()

    files = [dict(entry) for entry in APPROVED_FILE_ENTRIES]
    files[0]["size_bytes"] = -1
    write_inventory(files)
    with pytest.raises(ValidationError):
        compat._load_approved_source_inventory()

    files = [dict(entry) for entry in APPROVED_FILE_ENTRIES]
    files[0]["path"] = files[1]["path"].swapcase()
    write_inventory(files)
    with pytest.raises(ValidationError):
        compat._load_approved_source_inventory()


def test_full_inventory_rejects_noncritical_file_drift_and_mode_hash_changes() -> None:
    profile = copy.deepcopy(_profile())
    files_by_path = {
        entry["path"]: index
        for index, entry in enumerate(profile["pristine_source_manifest"]["files"])
    }
    readme_index = files_by_path["README.md"]
    profile["pristine_source_manifest"]["files"][readme_index]["sha256"] = "a" * 64
    profile["pristine_source_manifest"] = seal_identity_artifact(
        profile["pristine_source_manifest"], PRISTINE_SOURCE_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(profile)))

    profile = copy.deepcopy(_profile())
    script_index = files_by_path["scripts/run_searchqa.sh"]
    assert profile["pristine_source_manifest"]["files"][script_index]["mode"] == "0755"
    profile["pristine_source_manifest"]["files"][script_index]["mode"] = "0644"
    profile["pristine_source_manifest"] = seal_identity_artifact(
        profile["pristine_source_manifest"], PRISTINE_SOURCE_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(profile)))


def test_phase0_readiness_fails_closed_even_when_structurally_resolved() -> None:
    profile = _structurally_resolved_profile()

    assert compatibility_readiness_errors(
        profile, custody_as_of="2026-07-17T12:00:00Z"
    ) == [PHASE0_READY_ERROR]
    with pytest.raises(ValidationError, match="Phase 3 sealed external verification"):
        require_compatibility_ready(profile, custody_as_of="2026-07-17T12:00:00Z")


def test_readiness_derives_six_unresolved_slots_bidirectionally() -> None:
    profile = _profile()

    assert compatibility_readiness_errors(profile) == [
        "custody: Same-domain custody evidence is unresolved.",
        "full_dependency_lock: A full dependency lock is unresolved.",
        "image_digest: Runner image digest is unresolved.",
        "overlay_manifest: Overlay manifest evidence is unresolved.",
        "staging_manifest: Staging manifest evidence is unresolved.",
        "tested_patch: A tested SkillOpt compatibility patch is unresolved.",
    ]
    cleared = copy.deepcopy(profile)
    cleared["evidence_ceiling"] = []
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(cleared)))

    partial = _with_overlay_and_staging(profile)
    partial["overlay_manifest"] = None
    partial["evidence_ceiling"].append(
        next(
            item
            for item in EXPECTED_EVIDENCE_CEILING
            if item["code"] == "overlay_manifest"
        )
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(partial)))


def test_domain_hash_is_order_sensitive_for_arrays_and_strict_on_versions() -> None:
    payload = {"version": "example_v1", "b": [2, 1], "a": "cafe"}

    assert domain_separated_hash("example_v1", payload) == _golden_hash(
        "example_v1", payload
    )
    assert seal_identity_artifact(payload, "example_v1")["identity"] == _golden_hash(
        "example_v1", payload
    )
    assert domain_separated_hash(
        "example_v1", {"items": [1, 2]}
    ) != domain_separated_hash("example_v1", {"items": [2, 1]})
    for version in ("bad\nversion", "bad version", ""):
        with pytest.raises(ValidationError):
            domain_separated_hash(version, payload)


def test_overlay_cross_binds_contract_and_schema_named_logical_files() -> None:
    overlay = _with_overlay_and_staging(_profile())["overlay_manifest"]

    validated = validate_overlay_manifest(overlay)
    by_name = {entry["name"]: entry for entry in validated["logical_files"]}
    assert (
        validated["contract_sha256"] == by_name[QUERY_ANALYZER_CONTRACT_NAME]["sha256"]
    )
    assert validated["schema_sha256"] == by_name[OVERLAY_SCHEMA_NAME]["sha256"]

    bad = copy.deepcopy(overlay)
    bad["contract_sha256"] = "a" * 64
    bad = seal_identity_artifact(bad, OVERLAY_MANIFEST_VERSION)
    with pytest.raises(ValidationError):
        validate_overlay_manifest(bad)


def test_query_analyzer_contract_is_semantic_source_bound_and_drift_closed(
    tmp_path: Path,
) -> None:
    source = Path(__file__).resolve().parents[1] / QUERY_ANALYZER_SOURCE_PATH

    contract = validate_query_analyzer_contract_bytes(
        QUERY_ANALYZER_CONTRACT_BYTES, production_source=source
    )
    assert contract["raw_model_output_v1"]["fields"]["confidence"] == {
        "maximum": 1.0,
        "minimum": 0.0,
        "type": "number",
    }
    raw_fields = contract["raw_model_output_v1"]["fields"]
    normalized = contract["normalized_query_analysis_v1"]
    normalized_fields = normalized["fields"]
    assert raw_fields["is_academic"]["normalization"] == "bool"
    assert raw_fields["source_queries"]["fields"]["scholar_queries"] == {
        "alias_of": "google_scholar",
        "optional": True,
        "precedence": "when_present",
        "type": "any_json",
    }
    assert normalized_fields["source_queries"]["fields"]["scholar_queries"] == {
        "max_items": 3,
        "optional": True,
        "type": "array[string]",
    }
    assert set(normalized["common_required_fields"]) == {
        "confidence",
        "improved_query",
        "intent",
        "is_academic",
        "keywords",
        "original_query",
        "search_filters",
        "source_queries",
    }
    optional_fields = {
        "analysis_details",
        "core_concepts",
        "error",
        "research_area",
        "search_strategy",
    }
    assert set(normalized["optional_fields"]) == optional_fields
    assert all(
        normalized_fields[field]["optional"] is True for field in optional_fields
    )
    branches = contract["production_normalization_v1"]["branches"]
    assert set(branches) == {
        "empty_query",
        "exception_fallback",
        "no_client_fallback",
        "unified_llm_success",
    }
    for branch in branches.values():
        assert set(branch["allowed_keys"]) | set(branch["absent_keys"]) == set(
            normalized_fields
        )
        assert set(branch["required_keys"]) <= set(branch["allowed_keys"])
        assert set(branch["source_query_allowed_keys"]) | set(
            branch["source_query_absent_keys"]
        ) == set(normalized_fields["source_queries"]["fields"])
        assert set(branch["source_query_required_keys"]) <= set(
            branch["source_query_allowed_keys"]
        )
    assert contract["scope"]["allowed"] == "query_analyzer_standard_search"
    assert "deep_review" in contract["scope"]["forbidden_production_expansion"]
    verify_query_analyzer_source(source)

    drifted = json.loads(QUERY_ANALYZER_CONTRACT_BYTES)
    drifted["normalized_query_analysis_v1"]["fields"]["confidence"]["maximum"] = 2.0
    with pytest.raises(ValidationError):
        validate_query_analyzer_contract_bytes(
            json.dumps(drifted, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )

    fake_source = tmp_path / QUERY_ANALYZER_SOURCE_PATH
    fake_source.parent.mkdir(parents=True)
    fake_source.write_bytes(source.read_bytes() + b"\n# drift\n")
    with pytest.raises(ValidationError):
        validate_query_analyzer_contract_bytes(
            QUERY_ANALYZER_CONTRACT_BYTES, production_source=fake_source
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            {
                "is_academic": 0,
                "improved_query": "improved",
                "keywords": ["alpha", "beta"],
                "source_queries": {
                    "arxiv": ["raw", "arxiv"],
                    "dblp": None,
                    "google_scholar": [" first ", 7, None, "third"],
                },
            },
            {
                "is_academic": False,
                "arxiv": ["raw", "arxiv"],
                "dblp": None,
                "google_scholar": "first",
                "scholar_queries": ["first", "7", "third"],
            },
        ),
        (
            {
                "improved_query": "improved",
                "keywords": ["alpha", "beta"],
                "source_queries": {
                    "arxiv": "arxiv",
                    "dblp": "dblp",
                    "google_scholar": "ignored",
                    "scholar_queries": " alias ",
                },
            },
            {
                "is_academic": True,
                "arxiv": "arxiv",
                "dblp": "dblp",
                "google_scholar": "alias",
                "scholar_queries": ["alias", "improved", "alpha beta"],
            },
        ),
        (
            {
                "source_queries": {
                    "google_scholar": "google fallback",
                    "scholar_queries": None,
                }
            },
            {
                "is_academic": True,
                "arxiv": "fixture query",
                "dblp": "fixture query",
                "google_scholar": "google fallback",
                "scholar_queries": ["google fallback"],
            },
        ),
        (
            {},
            {
                "is_academic": True,
                "arxiv": "fixture query",
                "dblp": "fixture query",
                "google_scholar": "fixture query",
                "scholar_queries": ["fixture query"],
            },
        ),
    ],
)
def test_query_analyzer_contract_matches_production_success_normalization(
    monkeypatch: pytest.MonkeyPatch,
    raw: dict,
    expected: dict,
) -> None:
    from app.QueryAgent import query_analyzer as production

    production._analysis_cache.clear()
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(raw)))]
    )
    monkeypatch.setattr(
        production,
        "create_chat_completion",
        lambda *args, **kwargs: response,
    )
    analyzer = object.__new__(production.QueryAnalyzer)
    analyzer.client = object()
    analyzer.model = "fixture-model"

    result = analyzer.analyze_and_prepare("fixture query")

    _assert_live_query_analysis_contract(result, "unified_llm_success")
    assert result["is_academic"] is expected["is_academic"]
    assert result["source_queries"] == {
        "arxiv": expected["arxiv"],
        "dblp": expected["dblp"],
        "google_scholar": expected["google_scholar"],
        "scholar_queries": expected["scholar_queries"],
        "default": "fixture query",
    }


def test_query_analyzer_contract_matches_production_default_and_fallback_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.QueryAgent import query_analyzer as production

    analyzer = object.__new__(production.QueryAnalyzer)
    analyzer.client = object()
    analyzer.model = "fixture-model"
    empty = analyzer.analyze_and_prepare("  ")
    _assert_live_query_analysis_contract(empty, "empty_query")
    assert empty["is_academic"] is True
    assert empty["source_queries"] == {
        "arxiv": "  ",
        "dblp": "  ",
        "google_scholar": "  ",
        "default": "  ",
    }

    analyzer.client = None
    no_client = analyzer.analyze_and_prepare("graph retrieval")
    _assert_live_query_analysis_contract(no_client, "no_client_fallback")
    assert no_client["is_academic"] is True
    assert no_client["source_queries"] == {
        "arxiv": "ti:graph AND ti:retrieval",
        "dblp": "graph retrieval",
        "google_scholar": "graph retrieval",
        "default": "graph retrieval",
    }

    analyzer.client = object()

    analysis_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "intent": "paper_search",
                            "keywords": ["failed", "query"],
                            "core_concepts": ["retrieval"],
                            "research_area": "Information Retrieval",
                            "improved_query": "failed query retrieval",
                            "search_strategy": "Search exact terms",
                            "search_filters": {},
                            "confidence": 0.75,
                            "analysis_details": "Recovered through analyze_query",
                        }
                    )
                )
            )
        ]
    )
    topic_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps({"is_academic": True}))
            )
        ]
    )
    source_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "arxiv": "fallback arxiv",
                            "dblp": "fallback dblp",
                            "google_scholar": "failed query",
                        }
                    )
                )
            )
        ]
    )

    def exception_then_live_fallback(*args, **kwargs):
        system_prompt = kwargs["messages"][0]["content"]
        if "perform THREE tasks" in system_prompt:
            raise RuntimeError("fixture failure")
        if "You classify whether" in system_prompt:
            return topic_response
        if "source-specific academic search queries" in system_prompt:
            return source_response
        return analysis_response

    monkeypatch.setattr(
        production,
        "create_chat_completion",
        exception_then_live_fallback,
    )

    failed = analyzer.analyze_and_prepare("failed query")
    _assert_live_query_analysis_contract(failed, "exception_fallback")
    assert failed["is_academic"] is True
    assert failed["source_queries"] == {
        "arxiv": "fallback arxiv",
        "dblp": "fallback dblp",
        "google_scholar": "failed query",
        "default": "failed query",
    }

    production._analysis_cache.clear()
    monkeypatch.setattr(
        production,
        "create_chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fixture failure")),
    )
    fully_fallback = analyzer.analyze_and_prepare("hard failed query")
    _assert_live_query_analysis_contract(
        fully_fallback,
        "exception_fallback",
        expected_key_set="required_keys",
    )
    assert fully_fallback["analysis_details"] == (
        "Fallback analysis using simple keyword extraction"
    )


def test_staging_diff_tree_registry_and_module_relations_are_enforced() -> None:
    profile = _with_overlay_and_staging(_profile())
    staging = validate_staging_manifest(profile["staging_manifest"])

    assert {
        entry["module_path"]: entry["file_path"]
        for entry in staging["expected_imported_modules"]
    } == REQUIRED_IMPORTED_MODULES
    validate_profile_catalog(_reseal_catalog(profile))

    bad = copy.deepcopy(profile)
    bad["staging_manifest"]["allowlisted_diff"][0]["after_sha256"] = "a" * 64
    bad["staging_manifest"] = seal_identity_artifact(
        bad["staging_manifest"], STAGING_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(bad)))

    tiny = copy.deepcopy(profile)
    replacement = b"print('tiny arbitrary replacement')\n"
    script_path = "scripts/train.py"
    staged_entry = next(
        entry
        for entry in tiny["staging_manifest"]["staged_tree"]
        if entry["path"] == script_path
    )
    staged_entry.update(_entry(script_path, replacement))
    next(
        record
        for record in tiny["staging_manifest"]["allowlisted_diff"]
        if record["path"] == script_path
    )["after_sha256"] = staged_entry["sha256"]
    tiny["staging_manifest"]["train_registry_patch_sha256"] = staged_entry["sha256"]
    next(
        module
        for module in tiny["staging_manifest"]["expected_imported_modules"]
        if module["file_path"] == script_path
    )["sha256"] = staged_entry["sha256"]
    tiny["staging_manifest"]["staged_tree_identity"] = manifest_tree_identity(
        tiny["staging_manifest"]["staged_tree"]
    )
    tiny["staging_manifest"] = seal_identity_artifact(
        tiny["staging_manifest"], STAGING_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(tiny)))

    bad = copy.deepcopy(profile)
    bad["staging_manifest"]["expected_imported_modules"][0]["sha256"] = "b" * 64
    bad["staging_manifest"] = seal_identity_artifact(
        bad["staging_manifest"], STAGING_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(bad)))


def test_projection_bijection_rejects_omissions_unmatched_overlay_and_arbitrary_diffs() -> (
    None
):
    profile = _with_overlay_and_staging(_profile())

    bad = copy.deepcopy(profile)
    omitted = PROFILE_CONFIG_PATH
    bad["overlay_manifest"]["logical_files"] = [
        entry
        for entry in bad["overlay_manifest"]["logical_files"]
        if entry["path"] != omitted
    ]
    bad["overlay_manifest"] = seal_identity_artifact(
        bad["overlay_manifest"], OVERLAY_MANIFEST_VERSION
    )
    bad["staging_manifest"]["overlay_identity"] = bad["overlay_manifest"]["identity"]
    bad["staging_manifest"] = seal_identity_artifact(
        bad["staging_manifest"], STAGING_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(bad)))

    bad = copy.deepcopy(profile)
    changed_split = _entry(
        SPLIT_VAL_ITEMS_PATH,
        b'[{"id":"val-1","query":"too small","split":"val"}]\n',
    )
    next(
        entry
        for entry in bad["overlay_manifest"]["logical_files"]
        if entry["path"] == SPLIT_VAL_ITEMS_PATH
    ).update(changed_split)
    bad["overlay_manifest"] = seal_identity_artifact(
        bad["overlay_manifest"], OVERLAY_MANIFEST_VERSION
    )
    next(
        entry
        for entry in bad["staging_manifest"]["staged_tree"]
        if entry["path"] == SPLIT_VAL_ITEMS_PATH
    ).update(changed_split)
    next(
        record
        for record in bad["staging_manifest"]["allowlisted_diff"]
        if record["path"] == SPLIT_VAL_ITEMS_PATH
    )["after_sha256"] = changed_split["sha256"]
    bad["staging_manifest"]["overlay_identity"] = bad["overlay_manifest"]["identity"]
    bad["staging_manifest"]["staged_tree_identity"] = manifest_tree_identity(
        bad["staging_manifest"]["staged_tree"]
    )
    bad["staging_manifest"] = seal_identity_artifact(
        bad["staging_manifest"], STAGING_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(bad)))

    bad = copy.deepcopy(profile)
    bad["staging_manifest"]["allowlisted_diff"] = [
        record
        for record in bad["staging_manifest"]["allowlisted_diff"]
        if record["path"] != SKILL_INIT_PATH
    ]
    bad["staging_manifest"] = seal_identity_artifact(
        bad["staging_manifest"], STAGING_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(bad)))

    bad = copy.deepcopy(profile)
    bad["staging_manifest"]["allowlisted_diff"].append(
        {
            "path": "README.md",
            "change": "modify",
            "before_sha256": next(
                entry["sha256"]
                for entry in bad["pristine_source_manifest"]["files"]
                if entry["path"] == "README.md"
            ),
            "after_sha256": _sha(b"arbitrary readme patch\n"),
            "mode": "0644",
        }
    )
    bad["staging_manifest"] = seal_identity_artifact(
        bad["staging_manifest"], STAGING_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(bad)))


def test_projection_bijection_rejects_delete_and_staged_overlay_metadata_drift() -> (
    None
):
    profile = _with_overlay_and_staging(_profile())

    bad = copy.deepcopy(profile)
    delete_record = next(
        record
        for record in bad["staging_manifest"]["allowlisted_diff"]
        if record["path"] == SPLIT_TEST_ITEMS_PATH
    )
    delete_record["change"] = "delete"
    delete_record["before_sha256"] = delete_record["after_sha256"]
    delete_record["after_sha256"] = None
    bad["staging_manifest"] = seal_identity_artifact(
        bad["staging_manifest"], STAGING_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(bad)))

    bad = copy.deepcopy(profile)
    overlay_config = next(
        entry
        for entry in bad["overlay_manifest"]["logical_files"]
        if entry["path"] == PROFILE_CONFIG_PATH
    )
    overlay_config["size_bytes"] += 1
    bad["overlay_manifest"] = seal_identity_artifact(
        bad["overlay_manifest"], OVERLAY_MANIFEST_VERSION
    )
    bad["staging_manifest"]["overlay_identity"] = bad["overlay_manifest"]["identity"]
    bad["staging_manifest"] = seal_identity_artifact(
        bad["staging_manifest"], STAGING_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(bad)))


def test_overlay_rejects_canonical_contract_and_schema_metadata_drift() -> None:
    overlay = copy.deepcopy(_with_overlay_and_staging(_profile())["overlay_manifest"])
    contract = next(
        entry
        for entry in overlay["logical_files"]
        if entry["name"] == QUERY_ANALYZER_CONTRACT_NAME
    )
    contract["path"] = "overlay/contracts/renamed.json"
    overlay = seal_identity_artifact(overlay, OVERLAY_MANIFEST_VERSION)
    with pytest.raises(ValidationError):
        validate_overlay_manifest(overlay)

    overlay = copy.deepcopy(_with_overlay_and_staging(_profile())["overlay_manifest"])
    schema = next(
        entry
        for entry in overlay["logical_files"]
        if entry["name"] == OVERLAY_SCHEMA_NAME
    )
    schema["sha256"] = _sha(b"different schema bytes\n")
    overlay["schema_sha256"] = schema["sha256"]
    overlay = seal_identity_artifact(overlay, OVERLAY_MANIFEST_VERSION)
    with pytest.raises(ValidationError):
        validate_overlay_manifest(overlay)


def test_execution_config_frozen_mock_fields_and_argv_identities_are_exact(
    tmp_path: Path,
) -> None:
    profile = _with_overlay_and_staging(_profile())
    execution_config = profile["staging_manifest"]["execution_config"]

    assert execution_config["train_argv"] == TRAIN_ARGV
    assert execution_config["eval_argv"] == EVAL_ARGV
    assert execution_config["num_epochs"] == 1
    assert execution_config["batch_size"] == 3
    assert execution_config["minibatch_size"] == 1
    assert execution_config["merge_batch_size"] == 1
    assert execution_config["analyst_workers"] == 1
    assert execution_config["train_size"] == 3
    assert execution_config["gate_mixed_weight"] == 0.8
    assert execution_config["mock"] is True
    assert execution_config["max_analyst_rounds"] == 1
    assert execution_config["failure_only"] is True
    assert execution_config["use_gate"] is True
    assert execution_config["env_name"] == "jiphyeonjeon_search"
    assert execution_config["split_mode"] == "split_dir"
    assert execution_config["split_dir"] == SPLIT_DIR
    assert execution_config["workers"] == 1
    upstream_root = _exact_upstream_root()
    loader_source = upstream_root / LOADER_PATH
    base_source = upstream_root / PROFILE_CONFIG_BASE
    assert _sha(loader_source.read_bytes()) == CONFIG_SHA256
    assert _sha(base_source.read_bytes()) == BASE_CONFIG_SHA256

    spec = importlib.util.spec_from_file_location(
        "_skillopt_v020_config_compatibility_test", loader_source
    )
    assert spec is not None and spec.loader is not None
    upstream_config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream_config)

    staged_root = tmp_path / "staged"
    config_path = staged_root / PROFILE_CONFIG_PATH
    base_path = staged_root / PROFILE_CONFIG_BASE
    config_path.parent.mkdir(parents=True)
    base_path.parent.mkdir(parents=True)
    config_path.write_bytes(CANONICAL_RENDERED_CONFIG_BYTES)
    base_path.write_bytes(base_source.read_bytes())

    structured = upstream_config.load_config(str(config_path))
    flattened = upstream_config.flatten_config(structured)
    assert structured["model"]["backend"] == "azure_openai"
    for knob, expected in compat.CANONICAL_EXECUTION_KNOBS.items():
        flattened_key = "env" if knob == "env_name" else knob
        assert flattened[flattened_key] == expected

    base_path.unlink()
    with pytest.raises(FileNotFoundError):
        upstream_config.load_config(str(config_path))
    split_manifest = json.loads(CANONICAL_SPLIT_MANIFEST_BYTES)
    assert split_manifest["logical_splits"]["selection"] == "val"
    assert split_manifest["logical_splits"]["optimizer_test"] == "test"
    assert {
        split: len(json.loads(payload))
        for split, payload in CANONICAL_SPLIT_ITEM_BYTES.items()
    } == {
        "train": 3,
        "val": 2,
        "test": 2,
    }
    assert execution_config["train_out_root"] != execution_config["eval_out_root"]
    assert TRAIN_ARGV == [
        "/usr/local/bin/python",
        "scripts/train.py",
        "--config",
        "configs/jiphyeonjeon_search/default.yaml",
        "--split_dir",
        "data/jiphyeonjeon_search_split",
        "--out_root",
        "outputs/train",
    ]
    assert EVAL_ARGV == [
        "/usr/local/bin/python",
        "scripts/eval_only.py",
        "--config",
        "configs/jiphyeonjeon_search/default.yaml",
        "--skill",
        "outputs/train/best_skill.md",
        "--split",
        "all",
        "--split_dir",
        "data/jiphyeonjeon_search_split",
        "--out_root",
        "outputs/eval",
    ]
    assert "--out-root" not in TRAIN_ARGV + EVAL_ARGV
    assert "--mock" not in TRAIN_ARGV + EVAL_ARGV
    assert "--candidate" not in EVAL_ARGV

    bad = copy.deepcopy(profile)
    bad["staging_manifest"]["execution_config"]["num_epochs"] = 2
    bad["staging_manifest"] = seal_identity_artifact(
        bad["staging_manifest"], STAGING_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(bad)))

    bad = copy.deepcopy(profile)
    bad["staging_manifest"]["staged_tree"] = [
        entry
        for entry in bad["staging_manifest"]["staged_tree"]
        if entry["path"] != SPLIT_MANIFEST_PATH
    ]
    bad["staging_manifest"]["staged_tree_identity"] = manifest_tree_identity(
        bad["staging_manifest"]["staged_tree"]
    )
    bad["staging_manifest"] = seal_identity_artifact(
        bad["staging_manifest"], STAGING_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(bad)))

    bad = copy.deepcopy(profile)
    bad["staging_manifest"]["execution_config"]["rendered_config_sha256"] = _sha(
        b"stale rendered config\n"
    )
    bad["staging_manifest"]["execution_config_identity"] = domain_separated_hash(
        f"{STAGING_MANIFEST_VERSION}:execution_config",
        bad["staging_manifest"]["execution_config"],
    )
    bad["staging_manifest"] = seal_identity_artifact(
        bad["staging_manifest"], STAGING_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(bad)))


def test_tested_patch_declaration_cross_binds_but_does_not_authorize_readiness() -> (
    None
):
    profile = _structurally_resolved_profile()
    tested_patch = profile["tested_patch"]

    assert tested_patch["provider_count"] == 0
    assert tested_patch["network_count"] == 0
    assert tested_patch["subprocess_count"] == 0
    assert (
        tested_patch["imported_modules"]
        == profile["staging_manifest"]["expected_imported_modules"]
    )
    assert compatibility_readiness_errors(
        profile, custody_as_of="2026-07-17T12:00:00Z"
    ) == [PHASE0_READY_ERROR]

    bad = copy.deepcopy(profile)
    bad["tested_patch"]["network_count"] = 1
    bad = _reseal_profile(bad)
    with pytest.raises(ValidationError):
        validate_profile_catalog(
            _reseal_catalog(bad), custody_as_of="2026-07-17T12:00:00Z"
        )


def test_runner_rejects_floating_refs_mismatched_digest_and_zero_hashes() -> None:
    runner = copy.deepcopy(_structurally_resolved_profile()["runner_identity"])

    runner["image_ref"] = "example.com/floating:latest"
    runner = seal_identity_artifact(runner, RUNNER_IDENTITY_VERSION)
    with pytest.raises(ValidationError):
        validate_runner_identity(runner)

    runner = copy.deepcopy(_structurally_resolved_profile()["runner_identity"])
    runner["image_ref"] = "example.com/skill@sha256:" + "9" * 64
    runner = seal_identity_artifact(runner, RUNNER_IDENTITY_VERSION)
    with pytest.raises(ValidationError):
        validate_runner_identity(runner)

    for field in ("dependency_lock_sha256", "sbom_sha256", "build_provenance_sha256"):
        zero = copy.deepcopy(_structurally_resolved_profile()["runner_identity"])
        zero[field] = "0" * 64
        zero = seal_identity_artifact(zero, RUNNER_IDENTITY_VERSION)
        with pytest.raises(ValidationError):
            validate_runner_identity(zero)

    runner = copy.deepcopy(_structurally_resolved_profile()["runner_identity"])
    runner["interpreter_path"] = "/usr/bin/python3"
    runner = seal_identity_artifact(runner, RUNNER_IDENTITY_VERSION)
    with pytest.raises(ValidationError):
        validate_runner_identity(runner)

    runner = copy.deepcopy(_structurally_resolved_profile()["runner_identity"])
    runner["interpreter_sha256"] = "0" * 64
    runner = seal_identity_artifact(runner, RUNNER_IDENTITY_VERSION)
    with pytest.raises(ValidationError):
        validate_runner_identity(runner)

    runner = copy.deepcopy(_structurally_resolved_profile()["runner_identity"])
    runner["interpreter_sha256"] = "a" * 64
    runner["image_inventory"]["interpreters"][0]["sha256"] = "a" * 64
    runner = seal_identity_artifact(runner, RUNNER_IDENTITY_VERSION)
    with pytest.raises(ValidationError):
        validate_runner_identity(runner)

    profile = _structurally_resolved_profile()
    profile["tested_patch"]["observed_interpreter"]["sha256"] = "a" * 64
    profile = _reseal_profile(profile)
    with pytest.raises(ValidationError):
        validate_profile_catalog(
            _reseal_catalog(profile), custody_as_of="2026-07-17T12:00:00Z"
        )


def test_resealed_pin_drift_and_cross_binding_mismatches_are_rejected() -> None:
    profile = copy.deepcopy(_profile())
    profile["pristine_source_manifest"]["tag_object"] = "a" * 40
    profile["pristine_source_manifest"] = seal_identity_artifact(
        profile["pristine_source_manifest"], PRISTINE_SOURCE_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        validate_profile_catalog(_reseal_catalog(_reseal_profile(profile)))

    resolved = _structurally_resolved_profile()
    resolved["staging_manifest"]["overlay_identity"] = "sha256:" + "a" * 64
    resolved["staging_manifest"] = seal_identity_artifact(
        resolved["staging_manifest"], STAGING_MANIFEST_VERSION
    )
    resolved["runner_identity"]["staging_identity"] = resolved["staging_manifest"][
        "identity"
    ]
    resolved["runner_identity"] = seal_identity_artifact(
        resolved["runner_identity"], RUNNER_IDENTITY_VERSION
    )
    resolved = _reseal_profile(resolved)
    with pytest.raises(ValidationError):
        validate_profile_catalog(
            _reseal_catalog(resolved), custody_as_of="2026-07-17T12:00:00Z"
        )


def test_path_rules_reject_split_segments_bool_sizes_and_collisions() -> None:
    for bad in ("", ".", "..", "/abs", "a/../b", "a//b", "a/./b", "a\\b", "a\x00b"):
        with pytest.raises(ValidationError):
            validate_posix_relative_path(bad)

    with pytest.raises(ValidationError):
        validate_file_entries(
            [
                {
                    "path": "x",
                    "kind": "file",
                    "mode": "0644",
                    "size_bytes": True,
                    "sha256": "a" * 64,
                }
            ]
        )
    with pytest.raises(ValidationError):
        validate_file_entries(
            [
                {
                    "path": "Cafe",
                    "kind": "file",
                    "mode": "0644",
                    "size_bytes": 1,
                    "sha256": "a" * 64,
                },
                {
                    "path": "cafe",
                    "kind": "file",
                    "mode": "0644",
                    "size_bytes": 1,
                    "sha256": "b" * 64,
                },
            ]
        )


def test_low_level_manifest_verifier_is_explicit_and_rejects_drift(
    tmp_path: Path,
) -> None:
    payloads = {"requirements.txt": b"alpha\n", "scripts/train.py": b"print('train')\n"}
    entries = sorted(
        [_entry(path, payload) for path, payload in payloads.items()],
        key=lambda entry: entry["path"],
    )
    manifest = seal_identity_artifact(
        {"version": "test_manifest_v1", "files": entries}, "test_manifest_v1"
    )
    root = tmp_path / "root"
    moved = tmp_path / "moved"
    _write_manifest_tree(root, entries, payloads)
    _write_manifest_tree(moved, entries, payloads)

    verify_manifest_tree(root, manifest, expected_identity=manifest["identity"])
    verify_manifest_tree(moved, manifest, expected_identity=manifest["identity"])
    with acquire_manifest_tree_lease(
        root, manifest, expected_identity=manifest["identity"]
    ) as lease:
        assert lease.active
        assert lease.read_bytes("requirements.txt") == b"alpha\n"
        lease.verify_live()
    assert lease.active is False
    with pytest.raises(ValidationError):
        verify_manifest_tree(
            root, {"files": entries}, expected_identity=manifest["identity"]
        )
    with pytest.raises(ValidationError):
        verify_manifest_tree(root, manifest, expected_identity="sha256:" + "a" * 64)

    extra_root = tmp_path / "extra"
    _write_manifest_tree(extra_root, entries, payloads)
    (extra_root / "extra.txt").write_bytes(b"x")
    with pytest.raises(ValidationError):
        verify_manifest_tree(
            extra_root, manifest, expected_identity=manifest["identity"]
        )

    nested_extra_root = tmp_path / "nested-extra"
    _write_manifest_tree(nested_extra_root, entries, payloads)
    (nested_extra_root / "scripts" / "extra.py").write_bytes(b"print('extra')\n")
    with pytest.raises(ValidationError):
        verify_manifest_tree(
            nested_extra_root, manifest, expected_identity=manifest["identity"]
        )

    byte_root = tmp_path / "byte"
    _write_manifest_tree(byte_root, entries, payloads)
    (byte_root / "requirements.txt").write_bytes(b"alphA\n")
    with pytest.raises(ValidationError):
        verify_manifest_tree(
            byte_root, manifest, expected_identity=manifest["identity"]
        )

    symlink_root = tmp_path / "symlink"
    _write_manifest_tree(symlink_root, entries, payloads)
    (tmp_path / "outside.txt").write_bytes(b"outside")
    (symlink_root / "requirements.txt").unlink()
    (symlink_root / "requirements.txt").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(ValidationError):
        verify_manifest_tree(
            symlink_root, manifest, expected_identity=manifest["identity"]
        )

    parent_symlink_root = tmp_path / "parent-symlink"
    _write_manifest_tree(parent_symlink_root, entries, payloads)
    (parent_symlink_root / "scripts" / "train.py").unlink()
    (parent_symlink_root / "scripts").rmdir()
    (tmp_path / "outside-scripts").mkdir()
    (tmp_path / "outside-scripts" / "train.py").write_bytes(b"print('train')\n")
    (parent_symlink_root / "scripts").symlink_to(tmp_path / "outside-scripts")
    with pytest.raises(ValidationError):
        verify_manifest_tree(
            parent_symlink_root, manifest, expected_identity=manifest["identity"]
        )

    directory_symlink_root = tmp_path / "directory-symlink"
    _write_manifest_tree(directory_symlink_root, entries, payloads)
    (tmp_path / "outside-dir").mkdir()
    (directory_symlink_root / "unexpected-link").symlink_to(
        tmp_path / "outside-dir", target_is_directory=True
    )
    with pytest.raises(ValidationError):
        verify_manifest_tree(
            directory_symlink_root, manifest, expected_identity=manifest["identity"]
        )

    if hasattr(os, "mkfifo"):
        fifo_root = tmp_path / "fifo"
        _write_manifest_tree(fifo_root, entries, payloads)
        try:
            os.mkfifo(fifo_root / "unexpected-fifo")
        except OSError:
            pass
        else:
            with pytest.raises(ValidationError):
                verify_manifest_tree(
                    fifo_root, manifest, expected_identity=manifest["identity"]
                )


def test_manifest_lease_rejects_extra_empty_directory(tmp_path: Path) -> None:
    payload = b"sealed evidence\n"
    entries = [_entry("nested/evidence.txt", payload)]
    manifest = seal_identity_artifact(
        {"version": "empty_dir_manifest_v1", "files": entries},
        "empty_dir_manifest_v1",
    )
    root = tmp_path / "empty-directory"
    _write_manifest_tree(root, entries, {"nested/evidence.txt": payload})
    (root / "nested" / "unexpected-empty").mkdir()

    with pytest.raises(ValidationError, match="manifest directories"):
        acquire_manifest_tree_lease(
            root, manifest, expected_identity=manifest["identity"]
        )


def test_manifest_lease_detects_same_path_replacement_before_release(
    tmp_path: Path,
) -> None:
    payloads = {"evidence.txt": b"sealed evidence\n"}
    entries = [_entry("evidence.txt", payloads["evidence.txt"])]
    manifest = seal_identity_artifact(
        {"version": "lease_manifest_v1", "files": entries}, "lease_manifest_v1"
    )
    root = tmp_path / "leased"
    _write_manifest_tree(root, entries, payloads)

    with pytest.raises(ValidationError, match="replaced|changed"):
        with acquire_manifest_tree_lease(
            root, manifest, expected_identity=manifest["identity"]
        ) as lease:
            assert lease.read_bytes("evidence.txt") == b"sealed evidence\n"
            replacement = root / "replacement.tmp"
            replacement.write_bytes(b"hostile evidence\n")
            os.replace(replacement, root / "evidence.txt")


def test_manifest_lease_detects_restored_file_aba_when_directory_ctime_is_sound(
    tmp_path: Path,
) -> None:
    payload = b"sealed evidence\n"
    entries = [_entry("evidence.txt", payload)]
    manifest = seal_identity_artifact(
        {"version": "file_aba_manifest_v1", "files": entries},
        "file_aba_manifest_v1",
    )
    root = tmp_path / "file-aba"
    _write_manifest_tree(root, entries, {"evidence.txt": payload})
    lease = acquire_manifest_tree_lease(
        root, manifest, expected_identity=manifest["identity"]
    )
    before = lease.root_stat
    assert before is not None

    original = root / "original.saved"
    hostile = root / "hostile.tmp"
    os.replace(root / "evidence.txt", original)
    hostile.write_bytes(b"hostile evidence\n")
    os.replace(hostile, root / "evidence.txt")
    (root / "evidence.txt").unlink()
    os.replace(original, root / "evidence.txt")

    if not compat._stat_changed(before, os.fstat(lease.root_fd)):
        lease.close()
        pytest.skip(
            "filesystem does not expose directory metadata drift for restored file ABA"
        )
    with pytest.raises(ValidationError, match="root changed"):
        lease.close()
    assert lease.active is False


def test_manifest_lease_detects_restored_nested_parent_aba_when_ctime_is_sound(
    tmp_path: Path,
) -> None:
    payload = b"print('sealed')\n"
    entries = [_entry("scripts/train.py", payload)]
    manifest = seal_identity_artifact(
        {"version": "parent_aba_manifest_v1", "files": entries},
        "parent_aba_manifest_v1",
    )
    root = tmp_path / "parent-aba"
    _write_manifest_tree(root, entries, {"scripts/train.py": payload})
    lease = acquire_manifest_tree_lease(
        root, manifest, expected_identity=manifest["identity"]
    )
    before = lease.root_stat
    assert before is not None

    original = root / "scripts.saved"
    os.replace(root / "scripts", original)
    (root / "scripts").mkdir()
    (root / "scripts" / "train.py").write_bytes(payload)
    (root / "scripts" / "train.py").unlink()
    (root / "scripts").rmdir()
    os.replace(original, root / "scripts")

    if not compat._stat_changed(before, os.fstat(lease.root_fd)):
        lease.close()
        pytest.skip(
            "filesystem does not expose directory metadata drift for restored parent ABA"
        )
    with pytest.raises(ValidationError, match="root changed"):
        lease.close()
    assert lease.active is False


def test_manifest_lease_close_closes_all_held_directory_and_file_fds(
    tmp_path: Path,
) -> None:
    payload = b"sealed evidence\n"
    entries = [_entry("one/two/evidence.txt", payload)]
    manifest = seal_identity_artifact(
        {"version": "close_fds_manifest_v1", "files": entries},
        "close_fds_manifest_v1",
    )
    root = tmp_path / "close-fds"
    _write_manifest_tree(root, entries, {"one/two/evidence.txt": payload})
    lease = acquire_manifest_tree_lease(
        root, manifest, expected_identity=manifest["identity"]
    )
    held_fds = [lease.root_fd, *lease.directory_fds.values(), *lease.file_fds.values()]

    lease.close()

    assert lease.active is False
    assert lease.root_fd == -1
    assert lease.directory_fds == {}
    assert lease.file_fds == {}
    for fd in held_fds:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
def test_manifest_lease_acquire_closes_all_fds_on_base_exception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    interrupt_type: type[BaseException],
) -> None:
    payload = b"sealed evidence\n"
    entries = [_entry("nested/evidence.txt", payload)]
    manifest = seal_identity_artifact(
        {"version": "interrupt_manifest_v1", "files": entries},
        "interrupt_manifest_v1",
    )
    root = tmp_path / "interrupted-acquire"
    _write_manifest_tree(root, entries, {"nested/evidence.txt": payload})
    opened_fds: list[int] = []
    original_open_root = compat._open_root_dir
    original_open_directory = compat._open_manifest_dir_at
    original_open_file = compat._open_manifest_file_at

    def track_root(path: Path) -> int:
        fd = original_open_root(path)
        opened_fds.append(fd)
        return fd

    def track_file(root_fd: int, relative: str) -> int:
        fd = original_open_file(root_fd, relative)
        opened_fds.append(fd)
        return fd

    def track_directory(parent_fd: int, name: str, relative: str) -> int:
        fd = original_open_directory(parent_fd, name, relative)
        opened_fds.append(fd)
        return fd

    def interrupt_hash(fd: int) -> str:
        raise interrupt_type()

    monkeypatch.setattr(compat, "_open_root_dir", track_root)
    monkeypatch.setattr(compat, "_open_manifest_dir_at", track_directory)
    monkeypatch.setattr(compat, "_open_manifest_file_at", track_file)
    monkeypatch.setattr(compat, "_sha256_fd", interrupt_hash)
    lease = object.__new__(compat.VerifiedManifestLease)

    with pytest.raises(interrupt_type):
        lease.__init__(root, manifest, expected_identity=manifest["identity"])

    assert opened_fds
    assert lease.active is False
    assert lease.root_fd == -1
    assert lease.directory_fds == {}
    assert lease.file_fds == {}
    for fd in opened_fds:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
def test_diagnostic_staging_validation_closes_all_fds_on_base_exception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    interrupt_type: type[BaseException],
) -> None:
    payload = b"sealed staged bytes\n"
    entries = [_entry("evidence.txt", payload)]
    staging = seal_identity_artifact(
        {
            "version": "interrupt_staging_v1",
            "staged_tree": entries,
            "execution_config": {},
        },
        "interrupt_staging_v1",
    )
    root = tmp_path / "interrupted-staging"
    _write_manifest_tree(root, entries, {"evidence.txt": payload})
    captured: dict[str, object] = {}

    def validated_profile(
        profile: object, *, custody_as_of: object = None
    ) -> dict[str, object]:
        return {"staging_manifest": staging}

    def interrupt_validation(
        lease: compat.VerifiedManifestLease, execution_config: object
    ) -> None:
        captured["lease"] = lease
        captured["fds"] = [
            lease.root_fd,
            *lease.directory_fds.values(),
            *lease.file_fds.values(),
        ]
        raise interrupt_type()

    monkeypatch.setattr(compat, "validate_compatibility_profile", validated_profile)
    monkeypatch.setattr(
        compat, "_validate_canonical_staged_bytes", interrupt_validation
    )

    with pytest.raises(interrupt_type):
        acquire_diagnostic_staging_tree_lease(root, {})

    lease = captured["lease"]
    assert isinstance(lease, compat.VerifiedManifestLease)
    assert lease.active is False
    assert lease.root_fd == -1
    assert lease.directory_fds == {}
    assert lease.file_fds == {}
    for fd in captured["fds"]:
        assert isinstance(fd, int)
        with pytest.raises(OSError):
            os.fstat(fd)


def test_trusted_wrappers_reject_resealed_hostile_adapter(tmp_path: Path) -> None:
    profile = copy.deepcopy(_profile())
    readme = next(
        entry
        for entry in profile["pristine_source_manifest"]["files"]
        if entry["path"] == "README.md"
    )
    readme["sha256"] = "a" * 64
    profile["pristine_source_manifest"] = seal_identity_artifact(
        profile["pristine_source_manifest"], PRISTINE_SOURCE_MANIFEST_VERSION
    )
    with pytest.raises(ValidationError):
        acquire_approved_source_tree_lease(
            tmp_path, profile["pristine_source_manifest"]
        )

    staged = _with_overlay_and_staging(_profile())
    hostile_adapter = b"raise RuntimeError('hostile adapter imported')\n"
    hostile_entry = _entry(compat.ADAPTER_PATH, hostile_adapter)
    overlay = staged["overlay_manifest"]
    overlay_adapter = next(
        entry
        for entry in overlay["logical_files"]
        if entry["path"] == compat.ADAPTER_PATH
    )
    overlay_adapter.update(hostile_entry)
    staged["overlay_manifest"] = seal_identity_artifact(
        overlay, OVERLAY_MANIFEST_VERSION
    )

    staging = staged["staging_manifest"]
    staging["overlay_identity"] = staged["overlay_manifest"]["identity"]
    staging_adapter = next(
        entry
        for entry in staging["staged_tree"]
        if entry["path"] == compat.ADAPTER_PATH
    )
    staging_adapter.update(hostile_entry)
    staging["staged_tree_identity"] = manifest_tree_identity(staging["staged_tree"])
    next(
        record
        for record in staging["allowlisted_diff"]
        if record["path"] == compat.ADAPTER_PATH
    )["after_sha256"] = hostile_entry["sha256"]
    next(
        module
        for module in staging["expected_imported_modules"]
        if module["file_path"] == compat.ADAPTER_PATH
    )["sha256"] = hostile_entry["sha256"]
    staged["staging_manifest"] = seal_identity_artifact(
        staging, STAGING_MANIFEST_VERSION
    )
    staged = _reseal_profile(staged)

    assert validate_profile_catalog(_reseal_catalog(staged))["profiles"][PROFILE_ID]
    for trusted_api in (
        acquire_trusted_overlay_tree_lease,
        acquire_trusted_staging_tree_lease,
    ):
        assert "custody_as_of" not in inspect.signature(trusted_api).parameters
        with pytest.raises(ValidationError, match="unresolved"):
            trusted_api(tmp_path, staged)


def test_strict_json_rejects_duplicate_nonfinite_and_oversize(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"version":"x","version":"y"}', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_compatibility_catalog(duplicate)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"version": NaN}', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_compatibility_catalog(nonfinite)

    oversize = tmp_path / "oversize.json"
    oversize.write_bytes(b" " * (1_048_577))
    with pytest.raises(ValidationError):
        load_compatibility_catalog(oversize)


def test_fixed_time_custody_validation_rejects_expired_long_ttl_and_self_verified() -> (
    None
):
    custody = _structurally_resolved_profile()["custody_evidence"]

    assert validate_same_domain_custody_evidence(custody, as_of="2026-07-17T00:00:00Z")[
        "identity"
    ]
    assert validate_same_domain_custody_evidence(custody, as_of="2026-07-17T23:59:59Z")[
        "identity"
    ]
    for as_of in ("2026-07-16T23:59:59Z", "2026-07-18T00:00:00Z"):
        with pytest.raises(ValidationError):
            validate_same_domain_custody_evidence(custody, as_of=as_of)

    long_ttl = copy.deepcopy(custody)
    long_ttl["expires_at"] = "2026-07-18T00:00:01Z"
    long_ttl = seal_identity_artifact(long_ttl, SAME_DOMAIN_CUSTODY_EVIDENCE_VERSION)
    with pytest.raises(ValidationError):
        validate_same_domain_custody_evidence(long_ttl, as_of="2026-07-17T12:00:00Z")

    self_verified = copy.deepcopy(custody)
    self_verified["issuer_workload"] = self_verified["verifier_id"]
    self_verified = seal_identity_artifact(
        self_verified, SAME_DOMAIN_CUSTODY_EVIDENCE_VERSION
    )
    with pytest.raises(ValidationError):
        validate_same_domain_custody_evidence(
            self_verified, as_of="2026-07-17T12:00:00Z"
        )

    zero_acl = copy.deepcopy(custody)
    zero_acl["acl_snapshot_sha256"] = "0" * 64
    zero_acl = seal_identity_artifact(zero_acl, SAME_DOMAIN_CUSTODY_EVIDENCE_VERSION)
    with pytest.raises(ValidationError):
        validate_same_domain_custody_evidence(zero_acl, as_of="2026-07-17T12:00:00Z")


def test_catalog_custody_null_never_ages_out() -> None:
    assert (
        load_compatibility_catalog(CATALOG_PATH, custody_as_of="2099-01-01T00:00:00Z")[
            "profiles"
        ][PROFILE_ID]["custody_evidence"]
        is None
    )
