"""Bounded RED diagnostics for the legacy SkillOpt v0 materialization.

Only the exact pinned ``skillopt/config.py`` is executed, in a restricted
namespace, to reproduce its missing-base failure.  Train, eval, provider,
network, and subprocess entry points remain forbidden.  Every other upstream
file is inspected as data under sealed file-descriptor leases.  The short
restricted-loader boundary serializes concurrent report builders and
temporarily replaces process-global network and subprocess entry points.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
import json
import os
import socket
import stat
import subprocess
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from src.search_eval.skillopt_compatibility import (
    APPROVED_ARCHIVE_SHA256,
    APPROVED_PEELED_COMMIT,
    APPROVED_SOURCE_INVENTORY_IDENTITY,
    APPROVED_TAG_OBJECT,
    APPROVED_TREE_GIT_SHA1,
    OVERLAY_MANIFEST_VERSION,
    PROFILE_ID,
    acquire_approved_source_tree_lease,
    acquire_manifest_tree_lease,
    load_compatibility_catalog,
    seal_identity_artifact,
)
from src.search_eval.skillopt_contract import ValidationError

REPORT_VERSION = "skillopt_v020_red_diagnostic_report_v1"
INPUT_MANIFEST_VERSION = "skillopt_v020_diagnostic_input_manifest_v1"
LEGACY_MATERIALIZATION_VERSION = "skillopt-search-benchmark-materialization-v0"
MATERIALIZATION_MANIFEST = "skillopt_materialization_manifest.json"
CONFIG_RELATIVE_PATH = "configs/jiphyeonjeon_search/default.yaml"
README_RELATIVE_PATH = "README.md"
EXPECTED_CANDIDATE_PATH = "outputs/train/best_skill.md"
APPROVED_PRISTINE_MANIFEST_IDENTITY = (
    "sha256:3c0af53952801d0be331ad4860a6cfc561745bd2e495df2f399afd5069095319"
)
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_INSPECTED_FILE_BYTES = 4 * 1024 * 1024
MAX_INSPECTED_AGGREGATE_BYTES = 16 * 1024 * 1024
MAX_INSPECTED_FILES = 256
MAX_INSPECTED_DIRECTORIES = 64
MAX_INSPECTED_DEPTH = 12

DIAGNOSTIC_CODES = (
    "legacy_overlay_manifest_version",
    "missing_upstream_base_config",
    "train_only_registration",
    "hidden_registration_import_error",
    "wrong_candidate_path",
    "absolute_overlay_path",
    "unsealed_free_form_argv",
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_CATALOG = (
    _PROJECT_ROOT / "data/search_eval/skillopt_compatibility_profiles_v1.json"
)
_ABSOLUTE_MANIFEST_PATH_FIELDS = (
    "output_dir",
    "config_path",
    "split_dir",
    "env_package_dir",
    "initial_skill_path",
)
_EXECUTION_KINDS = (
    "provider",
    "network",
    "subprocess",
    "train",
    "eval",
)
_REPORT_KEYS = {
    "version",
    "profile_id",
    "content_inventory_verification",
    "declared_profile_anchors",
    "authenticity_status",
    "seal_kind",
    "input_bindings",
    "status",
    "evidence_class",
    "authorization_status",
    "tested_patch",
    "execution_counts",
    "diagnostics",
    "identity",
}
_RESTRICTED_EXECUTION_LOCK = threading.RLock()


class ExecutionDenied(RuntimeError):
    """Raised before a forbidden diagnostic-harness action can execute."""


class DenySentinel:
    """Count and reject forbidden attempts at the restricted boundary."""

    def __init__(self) -> None:
        self._counts = {kind: 0 for kind in _EXECUTION_KINDS}

    def deny(self, kind: str, detail: str) -> None:
        if kind not in self._counts:
            raise ValidationError(f"unknown deny-sentinel kind: {kind}")
        self._counts[kind] += 1
        raise ExecutionDenied(f"{kind} denied before execution: {detail}")

    def guarded_import(
        self,
        name: str,
        globals: Mapping[str, Any] | None = None,
        locals: Mapping[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name in {"scripts.train", "train"} or name.endswith(".scripts.train"):
            self.deny("train", name)
        if name in {"scripts.eval_only", "eval_only"} or name.endswith(
            ".scripts.eval_only"
        ):
            self.deny("eval", name)
        if level != 0 or name.split(".", 1)[0] not in {
            "__future__",
            "copy",
            "os",
            "typing",
            "yaml",
        }:
            self.deny("provider", name)
        return builtins.__import__(name, globals, locals, fromlist, level)

    def counts(self) -> dict[str, int]:
        """Return actual forbidden attempts; successful reports require all zero."""

        return dict(self._counts)


@contextmanager
def _restricted_execution_boundary(sentinel: DenySentinel) -> Iterator[None]:
    """Serialize, install, and reliably restore process-global denial hooks."""

    def deny_network(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        sentinel.deny("network", "socket entry point")

    def deny_subprocess(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        sentinel.deny("subprocess", "process entry point")

    replacements = (
        (socket, "socket", deny_network),
        (socket, "create_connection", deny_network),
        (socket, "create_server", deny_network),
        (subprocess, "Popen", deny_subprocess),
        (subprocess, "run", deny_subprocess),
        (subprocess, "call", deny_subprocess),
        (subprocess, "check_call", deny_subprocess),
        (subprocess, "check_output", deny_subprocess),
        (subprocess, "getoutput", deny_subprocess),
        (subprocess, "getstatusoutput", deny_subprocess),
        (os, "system", deny_subprocess),
    )
    with _RESTRICTED_EXECUTION_LOCK:
        installed: list[tuple[Any, str, Any, Any]] = []
        try:
            for owner, name, replacement in replacements:
                original = getattr(owner, name)
                setattr(owner, name, replacement)
                installed.append((owner, name, original, replacement))
            yield
        finally:
            ownership_drift: list[str] = []
            for owner, name, _, replacement in reversed(installed):
                try:
                    current = getattr(owner, name)
                except BaseException:
                    ownership_drift.append(f"{owner.__name__}.{name}")
                else:
                    if current is not replacement:
                        ownership_drift.append(f"{owner.__name__}.{name}")
            restoration_failures: list[str] = []
            for owner, name, original, _ in reversed(installed):
                try:
                    setattr(owner, name, original)
                except BaseException:
                    restoration_failures.append(f"{owner.__name__}.{name}")
            if ownership_drift or restoration_failures:
                details = []
                if ownership_drift:
                    drifted = ", ".join(reversed(ownership_drift))
                    details.append(f"lost hook ownership: {drifted}")
                if restoration_failures:
                    failed = ", ".join(reversed(restoration_failures))
                    details.append(f"could not restore hooks: {failed}")
                raise ValidationError(
                    f"restricted execution boundary {'; '.join(details)}"
                )


def build_red_diagnostic_report(
    *,
    source_root: str | Path,
    materialized_root: str | Path,
    profile_catalog_path: str | Path = DEFAULT_PROFILE_CATALOG,
) -> dict[str, Any]:
    """Inspect exact v0.2.0 source plus a legacy overlay and return sealed RED evidence."""

    catalog = load_compatibility_catalog(profile_catalog_path)
    profile = catalog["profiles"][PROFILE_ID]
    pristine_manifest = profile["pristine_source_manifest"]
    source_path = Path(source_root)
    overlay_path = Path(materialized_root)
    with acquire_approved_source_tree_lease(
        source_path, pristine_manifest
    ) as source_lease:
        overlay_manifest = _snapshot_manifest(overlay_path)
        with acquire_manifest_tree_lease(
            overlay_path,
            overlay_manifest,
            expected_identity=overlay_manifest["identity"],
        ) as overlay_lease:
            materialization = _load_json_bytes(
                overlay_lease.read_bytes(MATERIALIZATION_MANIFEST),
                "materialization manifest",
            )
            materialization_bytes = overlay_lease.read_bytes(MATERIALIZATION_MANIFEST)
            config = _decode_text(
                overlay_lease.read_bytes(CONFIG_RELATIVE_PATH), "materialized config"
            )
            readme = _decode_text(
                overlay_lease.read_bytes(README_RELATIVE_PATH), "materialized README"
            )
            upstream_train = _decode_text(
                source_lease.read_bytes("scripts/train.py"), "upstream train registry"
            )
            upstream_eval = _decode_text(
                source_lease.read_bytes("scripts/eval_only.py"),
                "upstream eval registry",
            )
            loader_source = _decode_text(
                source_lease.read_bytes("skillopt/config.py"),
                "upstream config loader",
            )
            sentinel = DenySentinel()
            missing_base_proof = _prove_missing_base_through_exact_loader(
                loader_source=loader_source,
                config_path=overlay_path / CONFIG_RELATIVE_PATH,
                overlay_root=overlay_path,
                sentinel=sentinel,
            )
            registry_proof = _prove_exact_registry_behavior(
                upstream_train=upstream_train,
                upstream_eval=upstream_eval,
            )
            diagnostics = _diagnose(
                materialization=materialization,
                config=config,
                readme=readme,
                upstream_train=upstream_train,
                upstream_eval=upstream_eval,
                expected_candidate_path=profile["outputs"]["candidate_path"],
                missing_base_proof=missing_base_proof,
                registry_proof=registry_proof,
            )

    payload = {
        "version": REPORT_VERSION,
        "profile_id": PROFILE_ID,
        "content_inventory_verification": {
            "status": "verified",
            "verification_kind": "approved_manifest_fd_lease",
            "tracked_inventory_identity": APPROVED_SOURCE_INVENTORY_IDENTITY,
            "pristine_source_manifest_identity": pristine_manifest["identity"],
        },
        "declared_profile_anchors": {
            "tag_object": APPROVED_TAG_OBJECT,
            "peeled_commit": APPROVED_PEELED_COMMIT,
            "tree_git_sha1": APPROVED_TREE_GIT_SHA1,
            "archive_sha256": APPROVED_ARCHIVE_SHA256,
        },
        "authenticity_status": "unverified",
        "seal_kind": "self_asserted_integrity",
        "input_bindings": {
            "materialization_manifest_sha256": _sha256(materialization_bytes),
            "overlay_tree_identity": overlay_manifest["identity"],
        },
        "status": "invalid",
        "evidence_class": "diagnostic",
        "authorization_status": "not_authorized",
        "tested_patch": None,
        "execution_counts": sentinel.counts(),
        "diagnostics": diagnostics,
    }
    return validate_diagnostic_report(seal_identity_artifact(payload, REPORT_VERSION))


def validate_diagnostic_report(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate exact RED semantics and the report's domain-separated identity seal."""

    if not isinstance(value, Mapping) or set(value) != _REPORT_KEYS:
        raise ValidationError("diagnostic report has invalid keys")
    if value.get("version") != REPORT_VERSION:
        raise ValidationError("diagnostic report version is unsupported")
    sealed = seal_identity_artifact(value, REPORT_VERSION)
    if dict(value) != sealed:
        raise ValidationError("diagnostic report identity does not match payload")
    if value.get("profile_id") != PROFILE_ID:
        raise ValidationError("diagnostic report profile_id is not approved")
    expected_verification = {
        "status": "verified",
        "verification_kind": "approved_manifest_fd_lease",
        "tracked_inventory_identity": APPROVED_SOURCE_INVENTORY_IDENTITY,
        "pristine_source_manifest_identity": APPROVED_PRISTINE_MANIFEST_IDENTITY,
    }
    if value.get("content_inventory_verification") != expected_verification:
        raise ValidationError("diagnostic report content inventory is not verified")
    expected_anchors = {
        "tag_object": APPROVED_TAG_OBJECT,
        "peeled_commit": APPROVED_PEELED_COMMIT,
        "tree_git_sha1": APPROVED_TREE_GIT_SHA1,
        "archive_sha256": APPROVED_ARCHIVE_SHA256,
    }
    if value.get("declared_profile_anchors") != expected_anchors:
        raise ValidationError("diagnostic report declared profile anchors changed")
    if value.get("authenticity_status") != "unverified":
        raise ValidationError("diagnostic report authenticity must remain unverified")
    if value.get("seal_kind") != "self_asserted_integrity":
        raise ValidationError("diagnostic report seal kind is invalid")
    bindings = value.get("input_bindings")
    if not isinstance(bindings, Mapping) or set(bindings) != {
        "materialization_manifest_sha256",
        "overlay_tree_identity",
    }:
        raise ValidationError("diagnostic report input bindings are invalid")
    if not _is_sha256(bindings["materialization_manifest_sha256"]):
        raise ValidationError("diagnostic report manifest sha256 is invalid")
    if not _is_identity(bindings["overlay_tree_identity"]):
        raise ValidationError("diagnostic report overlay identity is invalid")
    if value.get("status") != "invalid":
        raise ValidationError("diagnostic report status must remain invalid")
    if value.get("evidence_class") != "diagnostic":
        raise ValidationError("diagnostic report evidence_class must remain diagnostic")
    if value.get("authorization_status") != "not_authorized":
        raise ValidationError("diagnostic report must remain not_authorized")
    if value.get("tested_patch") is not None:
        raise ValidationError("diagnostic report must never promote tested_patch")
    execution_counts = value.get("execution_counts")
    expected_counts = {kind: 0 for kind in _EXECUTION_KINDS}
    if execution_counts != expected_counts:
        raise ValidationError("diagnostic report recorded forbidden execution attempts")
    diagnostics = value.get("diagnostics")
    if not isinstance(diagnostics, list):
        raise ValidationError("diagnostic report diagnostics must be a list")
    if [item.get("code") for item in diagnostics if isinstance(item, Mapping)] != list(
        DIAGNOSTIC_CODES
    ) or len(diagnostics) != len(DIAGNOSTIC_CODES):
        raise ValidationError("diagnostic report codes are invalid or out of order")
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, Mapping) or set(diagnostic) != {
            "code",
            "observed",
            "expected",
            "proof",
        }:
            raise ValidationError("diagnostic report entry has invalid keys")
        if not isinstance(diagnostic["proof"], Mapping) or not diagnostic["proof"]:
            raise ValidationError("diagnostic report proof must be a nonempty object")
    if diagnostics != _expected_diagnostics():
        raise ValidationError(
            "diagnostic report findings do not match the RED contract"
        )
    return json.loads(_canonical_json_bytes(value))


def load_diagnostic_report(path: str | Path) -> dict[str, Any]:
    """Load and validate one bounded UTF-8 JSON report."""

    report_path = Path(path)
    payload = report_path.read_bytes()
    if len(payload) > MAX_JSON_BYTES:
        raise ValidationError("diagnostic report is too large")
    return validate_diagnostic_report(_load_json_bytes(payload, "diagnostic report"))


def canonical_report_bytes(report: Mapping[str, Any]) -> bytes:
    """Return canonical newline-terminated bytes after strict validation."""

    return _canonical_json_bytes(validate_diagnostic_report(report))


def _diagnose(
    *,
    materialization: Any,
    config: str,
    readme: str,
    upstream_train: str,
    upstream_eval: str,
    expected_candidate_path: str,
    missing_base_proof: Mapping[str, Any],
    registry_proof: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(materialization, Mapping):
        raise ValidationError("materialization manifest must be an object")
    version = materialization.get("version")
    if version != LEGACY_MATERIALIZATION_VERSION:
        raise ValidationError("input is not the exact legacy materialization manifest")

    base_ref = _parse_single_scalar(config, "_base_")
    if base_ref != "../_base_/default.yaml":
        raise ValidationError("legacy materialized config base reference changed")
    if missing_base_proof != {
        "base_reference": "../_base_/default.yaml",
        "loader_path": "skillopt/config.py",
        "load_config_observed": "FileNotFoundError",
    }:
        raise ValidationError("missing base was not proved through exact load_config")

    registration = materialization.get("registration_snippet")
    if not isinstance(registration, str):
        raise ValidationError("legacy registration_snippet must be text")
    if "scripts/train.py" not in readme or "scripts/eval_only.py" in readme:
        raise ValidationError("legacy train-only registration instructions changed")
    if registry_proof != {
        "ast_verified": True,
        "environment_absent": True,
        "get_adapter_unknown_environment": "ValueError",
        "registries": ["scripts/train.py", "scripts/eval_only.py"],
    }:
        raise ValidationError("approved upstream registry behavior changed")
    if (
        "jiphyeonjeon_search" in upstream_train
        or "jiphyeonjeon_search" in upstream_eval
    ):
        raise ValidationError("legacy environment unexpectedly exists upstream")
    hidden_import = _has_hidden_import_error(registration)
    if not hidden_import:
        raise ValidationError("legacy registration no longer hides ImportError")

    candidate_path = materialization.get("expected_best_skill")
    if candidate_path != "ckpt/<run>/best_skill.md":
        raise ValidationError("legacy expected_best_skill changed")
    if expected_candidate_path != EXPECTED_CANDIDATE_PATH:
        raise ValidationError("approved profile candidate path changed")

    for field in _ABSOLUTE_MANIFEST_PATH_FIELDS:
        path_value = materialization.get(field)
        if not isinstance(path_value, str) or not Path(path_value).is_absolute():
            raise ValidationError(f"legacy materialization {field} is not absolute")
    if str(materialization["split_dir"]) not in config:
        raise ValidationError("legacy config no longer embeds its absolute split path")
    if str(materialization["initial_skill_path"]) not in config:
        raise ValidationError("legacy config no longer embeds its absolute skill path")

    train_command = materialization.get("train_command")
    if not isinstance(train_command, str) or not train_command.startswith(
        "python scripts/train.py --config "
    ):
        raise ValidationError("legacy train_command changed")
    forbidden_seals = {"train_argv", "train_argv_identity", "command_identity"}
    if forbidden_seals & set(materialization):
        raise ValidationError("legacy command unexpectedly became sealed argv")

    return _expected_diagnostics()


def _expected_diagnostics() -> list[dict[str, Any]]:
    return [
        {
            "code": "legacy_overlay_manifest_version",
            "observed": LEGACY_MATERIALIZATION_VERSION,
            "expected": OVERLAY_MANIFEST_VERSION,
            "proof": {"manifest": MATERIALIZATION_MANIFEST},
        },
        {
            "code": "missing_upstream_base_config",
            "observed": "FileNotFoundError",
            "expected": "sealed configs/_base_/default.yaml",
            "proof": {
                "base_reference": "../_base_/default.yaml",
                "loader_path": "skillopt/config.py",
                "load_config_observed": "FileNotFoundError",
            },
        },
        {
            "code": "train_only_registration",
            "observed": ["scripts/train.py"],
            "expected": ["scripts/train.py", "scripts/eval_only.py"],
            "proof": {
                "ast_verified": True,
                "environment_absent": True,
                "get_adapter_unknown_environment": "ValueError",
                "registries": ["scripts/train.py", "scripts/eval_only.py"],
            },
        },
        {
            "code": "hidden_registration_import_error",
            "observed": "except ImportError: pass",
            "expected": "registration import failures are fatal",
            "proof": {
                "ast_verified": True,
                "exact_try_shape": True,
            },
        },
        {
            "code": "wrong_candidate_path",
            "observed": "ckpt/<run>/best_skill.md",
            "expected": EXPECTED_CANDIDATE_PATH,
            "proof": {"profile_bound": True},
        },
        {
            "code": "absolute_overlay_path",
            "observed": list(_ABSOLUTE_MANIFEST_PATH_FIELDS),
            "expected": "POSIX-relative sealed overlay paths",
            "proof": {"config_embeds_absolute_paths": True},
        },
        {
            "code": "unsealed_free_form_argv",
            "observed": "train_command:string",
            "expected": "sealed argv array and identity",
            "proof": {"argv_identity_present": False},
        },
    ]


def _prove_missing_base_through_exact_loader(
    *,
    loader_source: str,
    config_path: Path,
    overlay_root: Path,
    sentinel: DenySentinel,
) -> dict[str, str]:
    try:
        tree = ast.parse(loader_source, filename="skillopt/config.py")
    except SyntaxError as exc:
        raise ValidationError(
            "approved upstream config loader is invalid Python"
        ) from exc
    load_functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "load_config"
    ]
    if len(load_functions) != 1:
        raise ValidationError("approved upstream load_config definition changed")

    overlay_root_resolved = overlay_root.resolve(strict=True)

    def restricted_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if not isinstance(file, (str, os.PathLike)) or mode not in {"r", "rt"}:
            raise ValidationError(
                "exact config loader attempted unsupported file access"
            )
        candidate = Path(file).resolve(strict=False)
        try:
            candidate.relative_to(overlay_root_resolved)
        except ValueError as exc:
            raise ValidationError(
                "exact config loader escaped materialized root"
            ) from exc
        return builtins.open(candidate, mode, *args, **kwargs)

    restricted_builtins = dict(vars(builtins))
    restricted_builtins["__import__"] = sentinel.guarded_import
    restricted_builtins["open"] = restricted_open
    namespace: dict[str, Any] = {
        "__builtins__": restricted_builtins,
        "__file__": "skillopt/config.py",
        "__name__": "_skillopt_v020_config_diagnostic",
        "__package__": None,
    }
    try:
        with _restricted_execution_boundary(sentinel):
            exec(compile(tree, "skillopt/config.py", "exec"), namespace, namespace)
            load_config = namespace.get("load_config")
            if not callable(load_config):
                raise ValidationError("approved upstream load_config is not callable")
            load_config(str(config_path))
    except FileNotFoundError as exc:
        missing = Path(exc.filename or "").resolve(strict=False)
        expected = (config_path.parent / "../_base_/default.yaml").resolve(strict=False)
        if missing != expected:
            raise ValidationError(
                "exact load_config failed for an unexpected path"
            ) from exc
    except ExecutionDenied as exc:
        raise ValidationError(
            "exact config loader attempted a forbidden action"
        ) from exc
    else:
        raise ValidationError("legacy upstream base config unexpectedly exists")
    return {
        "base_reference": "../_base_/default.yaml",
        "loader_path": "skillopt/config.py",
        "load_config_observed": "FileNotFoundError",
    }


def _prove_exact_registry_behavior(
    *, upstream_train: str, upstream_eval: str
) -> dict[str, Any]:
    registries = [
        ("scripts/train.py", upstream_train),
        ("scripts/eval_only.py", upstream_eval),
    ]
    for label, source in registries:
        try:
            tree = ast.parse(source, filename=label)
        except SyntaxError as exc:
            raise ValidationError(
                f"approved upstream registry is invalid: {label}"
            ) from exc
        if any(
            isinstance(node, ast.Constant) and node.value == "jiphyeonjeon_search"
            for node in ast.walk(tree)
        ):
            raise ValidationError(
                f"approved upstream registry already contains environment: {label}"
            )
        registry_initializers = [
            node
            for node in tree.body
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "_ENV_REGISTRY"
                and isinstance(node.value, ast.Dict)
                and not node.value.keys
            )
            or (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "_ENV_REGISTRY"
                    for target in node.targets
                )
                and isinstance(node.value, ast.Dict)
                and not node.value.keys
            )
        ]
        if len(registry_initializers) != 1:
            raise ValidationError(
                f"approved upstream registry initializer changed: {label}"
            )
        adapter_functions = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "get_adapter"
        ]
        if len(adapter_functions) != 1 or not _has_unknown_environment_branch(
            adapter_functions[0]
        ):
            raise ValidationError(
                f"approved upstream get_adapter behavior changed: {label}"
            )
    return {
        "ast_verified": True,
        "environment_absent": True,
        "get_adapter_unknown_environment": "ValueError",
        "registries": [label for label, _ in registries],
    }


def _has_unknown_environment_branch(function: ast.FunctionDef) -> bool:
    calls_register = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_register_builtins"
        for node in ast.walk(function)
    )
    assigns_env = any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "env_name"
            for target in node.targets
        )
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "cfg"
        and node.value.func.attr == "get"
        and len(node.value.args) == 2
        and all(isinstance(arg, ast.Constant) for arg in node.value.args)
        and node.value.args[0].value == "env"
        and node.value.args[1].value == "alfworld"
        for node in function.body
    )
    unknown_branch = False
    for node in function.body:
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        comparison = node.test
        if not (
            isinstance(comparison.left, ast.Name)
            and comparison.left.id == "env_name"
            and len(comparison.ops) == 1
            and isinstance(comparison.ops[0], ast.NotIn)
            and len(comparison.comparators) == 1
            and isinstance(comparison.comparators[0], ast.Name)
            and comparison.comparators[0].id == "_ENV_REGISTRY"
        ):
            continue
        raises = [item for item in node.body if isinstance(item, ast.Raise)]
        unknown_branch = len(raises) == 1 and isinstance(raises[0].exc, ast.Call)
        if unknown_branch:
            exception = raises[0].exc
            unknown_branch = (
                isinstance(exception.func, ast.Name)
                and exception.func.id == "ValueError"
                and any(
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and "Unknown environment" in value.value
                    for value in ast.walk(exception)
                )
            )
    return calls_register and assigns_env and unknown_branch


def _literal_subscript_key(node: ast.Subscript) -> Any:
    return node.slice.value if isinstance(node.slice, ast.Constant) else None


def _snapshot_manifest(root: Path) -> dict[str, Any]:
    """Snapshot an untrusted tree using only no-follow, FD-relative reads."""

    open_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        root_fd = os.open(root, open_flags)
    except OSError as exc:
        raise ValidationError("materialized root is unreadable") from exc
    try:
        root_stat = os.fstat(root_fd)
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ValidationError("materialized root must be a real directory")
        state: dict[str, Any] = {
            "entries": [],
            "directory_count": 1,
            "aggregate_bytes": 0,
        }
        _snapshot_directory(root_fd, (), 0, state)
        try:
            final_root_stat = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise ValidationError(
                "materialized root changed during inspection"
            ) from exc
        if not _same_snapshot_stat(root_stat, final_root_stat):
            raise ValidationError("materialized root changed during inspection")
        entries = state["entries"]
    finally:
        os.close(root_fd)

    entries.sort(key=lambda item: item["path"])
    required = {MATERIALIZATION_MANIFEST, CONFIG_RELATIVE_PATH, README_RELATIVE_PATH}
    if not required <= {entry["path"] for entry in entries}:
        raise ValidationError("materialized tree is missing required diagnostic inputs")
    return seal_identity_artifact(
        {"version": INPUT_MANIFEST_VERSION, "files": entries},
        INPUT_MANIFEST_VERSION,
    )


def _snapshot_directory(
    directory_fd: int,
    relative_parts: tuple[str, ...],
    depth: int,
    state: dict[str, Any],
) -> None:
    if depth > MAX_INSPECTED_DEPTH:
        raise ValidationError("materialized tree exceeds maximum depth")
    before = os.fstat(directory_fd)
    try:
        names = sorted(os.listdir(directory_fd))
    except OSError as exc:
        raise ValidationError("materialized tree is unreadable") from exc
    for name in names:
        try:
            child_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise ValidationError(
                "materialized tree changed during inspection"
            ) from exc
        child_parts = (*relative_parts, name)
        relative = PurePosixPath(*child_parts).as_posix()
        child_depth = len(child_parts)
        if child_depth > MAX_INSPECTED_DEPTH:
            raise ValidationError("materialized tree exceeds maximum depth")
        if stat.S_ISLNK(child_stat.st_mode):
            raise ValidationError("materialized tree must not contain symlinks")
        if stat.S_ISDIR(child_stat.st_mode):
            state["directory_count"] += 1
            if state["directory_count"] > MAX_INSPECTED_DIRECTORIES:
                raise ValidationError("materialized tree has too many directories")
            _snapshot_child_directory(
                directory_fd, name, child_stat, child_parts, child_depth, state
            )
            continue
        if not stat.S_ISREG(child_stat.st_mode):
            raise ValidationError("materialized tree must contain only regular files")
        _snapshot_file(directory_fd, name, relative, child_stat, state)
    after = os.fstat(directory_fd)
    if not _same_snapshot_stat(before, after):
        raise ValidationError("materialized tree changed during inspection")


def _snapshot_child_directory(
    parent_fd: int,
    name: str,
    expected_stat: os.stat_result,
    relative_parts: tuple[str, ...],
    depth: int,
    state: dict[str, Any],
) -> None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        child_fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise ValidationError("materialized tree changed during inspection") from exc
    try:
        opened_stat = os.fstat(child_fd)
        if not stat.S_ISDIR(opened_stat.st_mode) or not _same_snapshot_stat(
            expected_stat, opened_stat
        ):
            raise ValidationError("materialized tree changed during inspection")
        _snapshot_directory(child_fd, relative_parts, depth, state)
        try:
            final_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise ValidationError(
                "materialized tree changed during inspection"
            ) from exc
        if not _same_snapshot_stat(opened_stat, final_stat):
            raise ValidationError("materialized tree changed during inspection")
    finally:
        os.close(child_fd)


def _snapshot_file(
    parent_fd: int,
    name: str,
    relative: str,
    expected_stat: os.stat_result,
    state: dict[str, Any],
) -> None:
    if expected_stat.st_nlink != 1:
        raise ValidationError("materialized tree must not contain hardlinked files")
    if len(state["entries"]) >= MAX_INSPECTED_FILES:
        raise ValidationError("materialized tree has too many files")
    if expected_stat.st_size > MAX_INSPECTED_FILE_BYTES:
        raise ValidationError("materialized tree contains an oversized file")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        file_fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise ValidationError("materialized tree changed during inspection") from exc
    try:
        opened_stat = os.fstat(file_fd)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_nlink != 1
            or not _same_snapshot_stat(expected_stat, opened_stat)
        ):
            raise ValidationError("materialized tree changed during inspection")
        payload = _read_bounded_fd(file_fd, MAX_INSPECTED_FILE_BYTES)
        final_fd_stat = os.fstat(file_fd)
        try:
            final_name_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise ValidationError(
                "materialized tree changed during inspection"
            ) from exc
        if not _same_snapshot_stat(
            opened_stat, final_fd_stat
        ) or not _same_snapshot_stat(opened_stat, final_name_stat):
            raise ValidationError("materialized tree changed during inspection")
    finally:
        os.close(file_fd)
    state["aggregate_bytes"] += len(payload)
    if state["aggregate_bytes"] > MAX_INSPECTED_AGGREGATE_BYTES:
        raise ValidationError("materialized tree exceeds aggregate byte limit")
    state["entries"].append(
        {
            "path": relative,
            "kind": "file",
            "mode": "0755" if opened_stat.st_mode & stat.S_IXUSR else "0644",
            "size_bytes": len(payload),
            "sha256": _sha256(payload),
        }
    )


def _read_bounded_fd(file_fd: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        try:
            chunk = os.read(file_fd, min(64 * 1024, limit + 1 - size))
        except OSError as exc:
            raise ValidationError("materialized tree is unreadable") from exc
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            raise ValidationError("materialized tree contains an oversized file")


def _same_snapshot_stat(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        stat.S_IFMT(left.st_mode),
        left.st_size,
        left.st_nlink,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        stat.S_IFMT(right.st_mode),
        right.st_size,
        right.st_nlink,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


def _has_hidden_import_error(snippet: str) -> bool:
    try:
        tree = ast.parse(snippet)
    except SyntaxError as exc:
        raise ValidationError("legacy registration_snippet is invalid Python") from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Try):
        return False
    try_node = tree.body[0]
    if try_node.orelse or try_node.finalbody or len(try_node.handlers) != 1:
        return False
    if len(try_node.body) != 2:
        return False
    import_node, assignment = try_node.body
    if not (
        isinstance(import_node, ast.ImportFrom)
        and import_node.level == 0
        and import_node.module == "skillopt.envs.jiphyeonjeon_search.adapter"
        and len(import_node.names) == 1
        and import_node.names[0].name == "JiphyeonjeonSearchAdapter"
        and import_node.names[0].asname is None
    ):
        return False
    if not (
        isinstance(assignment, ast.Assign)
        and len(assignment.targets) == 1
        and isinstance(assignment.targets[0], ast.Subscript)
        and isinstance(assignment.targets[0].value, ast.Name)
        and assignment.targets[0].value.id == "_ENV_REGISTRY"
        and _literal_subscript_key(assignment.targets[0]) == "jiphyeonjeon_search"
        and isinstance(assignment.value, ast.Name)
        and assignment.value.id == "JiphyeonjeonSearchAdapter"
    ):
        return False
    handler = try_node.handlers[0]
    return (
        isinstance(handler.type, ast.Name)
        and handler.type.id == "ImportError"
        and handler.name is None
        and len(handler.body) == 1
        and isinstance(handler.body[0], ast.Pass)
    )


def _parse_single_scalar(config: str, key: str) -> str:
    matches = []
    for line in config.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}:"):
            matches.append(stripped.split(":", 1)[1].strip())
    if len(matches) != 1 or not matches[0]:
        raise ValidationError(f"materialized config must contain exactly one {key}")
    return matches[0]


def _load_json_bytes(payload: bytes, field: str) -> Any:
    if len(payload) > MAX_JSON_BYTES:
        raise ValidationError(f"{field} is too large")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValidationError(f"{field} contains duplicate JSON key: {key}")
            result[key] = item
        return result

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValidationError(f"{field} contains invalid JSON constant: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{field} must be strict UTF-8 JSON") from exc


def _decode_text(payload: bytes, field: str) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"{field} must be UTF-8") from exc


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_identity(value: Any) -> bool:
    return (
        isinstance(value, str) and value.startswith("sha256:") and _is_sha256(value[7:])
    )


__all__ = [
    "DEFAULT_PROFILE_CATALOG",
    "DenySentinel",
    "DIAGNOSTIC_CODES",
    "ExecutionDenied",
    "REPORT_VERSION",
    "build_red_diagnostic_report",
    "canonical_report_bytes",
    "load_diagnostic_report",
    "validate_diagnostic_report",
]
