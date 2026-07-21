"""Deterministic diagnostic overlay and staged-tree construction for SkillOpt."""

from __future__ import annotations

import asyncio
import builtins
import copy
import ctypes
import hashlib
import importlib
import importlib.machinery
from importlib._bootstrap_external import _NamespacePath
import inspect
import io
import json
import marshal
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import types
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, Iterator, NoReturn

from .skillopt_compatibility import (
    ADAPTER_PATH,
    CANDIDATE_PATH,
    CANONICAL_EXECUTION_KNOBS,
    CANONICAL_RENDERED_CONFIG_BYTES,
    CANONICAL_SPLIT_ITEM_BYTES,
    CANONICAL_SPLIT_MANIFEST_BYTES,
    CONFIG_SHA256,
    EVAL_ARGV,
    EVAL_OUT_ROOT,
    EXPECTED_EVIDENCE_CEILING,
    LOADER_PATH,
    OVERLAY_IMMUTABLE_OBJECT_VERSION,
    OVERLAY_MANIFEST_VERSION,
    OVERLAY_SCHEMA_BYTES,
    OVERLAY_SCHEMA_NAME,
    OVERLAY_SCHEMA_PATH,
    OVERLAY_SCHEMA_SHA256,
    PROFILE_CATALOG_VERSION,
    PROFILE_CONFIG_BASE,
    PROFILE_CONFIG_PATH,
    PROFILE_ID,
    QUERY_ANALYZER_CONTRACT_BYTES,
    QUERY_ANALYZER_CONTRACT_NAME,
    QUERY_ANALYZER_CONTRACT_PATH,
    QUERY_ANALYZER_CONTRACT_SHA256,
    REGISTRY_PATCH_CONTRACT,
    REGISTRY_PATCH_CONTRACT_BYTES,
    REGISTRY_PATCH_CONTRACT_NAME,
    REGISTRY_PATCH_CONTRACT_PATH,
    REGISTRY_PATCH_PATHS,
    REQUIRED_IMPORTED_MODULES,
    REQUIRED_PROJECTED_INPUT_PATHS,
    SKILL_INIT_PATH,
    SPLIT_MANIFEST_PATH,
    SPLIT_TEST_ITEMS_PATH,
    SPLIT_TRAIN_ITEMS_PATH,
    SPLIT_VAL_ITEMS_PATH,
    STAGING_MANIFEST_VERSION,
    TRAIN_ARGV,
    TRAIN_OUT_ROOT,
    acquire_approved_source_tree_lease,
    acquire_diagnostic_overlay_tree_lease,
    acquire_diagnostic_staging_tree_lease,
    apply_registry_patch,
    domain_separated_hash,
    load_compatibility_catalog,
    manifest_tree_identity,
    seal_identity_artifact,
    validate_compatibility_profile,
)
from .skillopt_contract import ValidationError


DEFAULT_PROFILE_CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "data/search_eval/skillopt_compatibility_profiles_v1.json"
)

INITIAL_SKILL_BYTES = b"""# Jiphyeonjeon Search Skill

Analyze the paper-search query and return concise, grounded retrieval guidance.
"""

ADAPTER_MARKER = "JIPHYEONJEON_COMPATIBILITY_MARKER_V1"
EXECUTION_PROJECTION_VERSION = "execution_projection_v1"
DIAGNOSTIC_REPORT_VERSION = "skillopt_mock_execution_diagnostic_v1"

_EXECUTION_KINDS = ("provider", "network", "subprocess")
_PROTECTED_PREFIXES = ("skillopt", "scripts")
_EXECUTION_LOCK = threading.RLock()
_EXECUTION_OWNER_STACK: list[tuple[int, object]] = []
_AUDIT_HOOK_INSTALLED = False
_AUDIT_OBSERVER: tuple[int, object] | None = None


def _capture_canonical_builtin(name: str) -> Any:
    value = inspect.getattr_static(builtins, name)
    if (
        type(value) is not types.BuiltinFunctionType
        or value.__module__ != "builtins"
        or value.__name__ != name
    ):
        raise RuntimeError(f"canonical builtins.{name} is unavailable")
    return value


_CANONICAL_COMPILE = _capture_canonical_builtin("compile")
_CANONICAL_EXEC = _capture_canonical_builtin("exec")
_CANONICAL_OPEN = builtins.open
_CANONICAL_IMPORT = builtins.__import__
_CANONICAL_IMPORT_MODULE = importlib.import_module
_CANONICAL_SPEC_FROM_FILE_LOCATION = importlib.util.spec_from_file_location
_CANONICAL_META_PATH = tuple(sys.meta_path)
_CANONICAL_PATH_HOOKS = tuple(sys.path_hooks)
_CANONICAL_ADD_AUDIT_HOOK = sys.addaudithook
_CANONICAL_IMPORT_MACHINERY = tuple(
    (owner, name, inspect.getattr_static(owner, name))
    for owner, names in (
        (
            importlib.machinery.SourceFileLoader,
            ("get_code", "exec_module", "get_filename", "get_data"),
        ),
        (importlib.machinery.FileFinder, ("find_spec",)),
        (importlib.machinery.PathFinder, ("find_spec",)),
    )
    for name in names
)
_EXPECTED_EVAL_IDS = (
    "train-1",
    "train-2",
    "train-3",
    "val-1",
    "val-2",
    "test-1",
    "test-2",
)
_EXPECTED_TRAIN_ARTIFACTS = {
    CANDIDATE_PATH.removeprefix(f"{TRAIN_OUT_ROOT}/"),
    "config.json",
    "history.json",
    "runtime_state.json",
    "skills/skill_v0000.md",
    "skills/skill_v0001.md",
    "steps/step_0001/candidate_skill.md",
    "steps/step_0001/edit_apply_report.json",
    "steps/step_0001/merged_patch.json",
    "steps/step_0001/ranked_edits.json",
    "steps/step_0001/step_record.json",
    "steps/step_0001/trajectory_digest.json",
    "summary.json",
    "test_eval/summary.json",
    "test_eval_baseline/summary.json",
    "test_eval_final/summary.json",
}
_CALL_TARGETS = {
    ("scripts/train.py", "main"): "scripts.train.main",
    ("skillopt/engine/trainer.py", "train"): "ReflACTTrainer.train",
    ("skillopt/gradient/aggregate.py", "merge_patches"): "merge_patches",
    ("skillopt/optimizer/clip.py", "rank_and_select"): "rank_and_select",
    ("skillopt/optimizer/skill.py", "apply_patch_with_report"): (
        "apply_patch_with_report"
    ),
    ("skillopt/evaluation/gate.py", "evaluate_gate"): "evaluate_gate",
    ("skillopt/evaluation/gate.py", "select_gate_score"): "select_gate_score",
    ("scripts/eval_only.py", "main"): "scripts.eval_only.main",
    (ADAPTER_PATH, "setup"): "adapter.setup",
    (ADAPTER_PATH, "build_env_from_batch"): "adapter.build_env_from_batch",
    (ADAPTER_PATH, "build_train_env"): "adapter.build_train_env",
    (ADAPTER_PATH, "build_eval_env"): "adapter.build_eval_env",
    (ADAPTER_PATH, "rollout"): "adapter.rollout",
    (ADAPTER_PATH, "reflect"): "adapter.reflect",
}
_REQUIRED_CALL_COUNTS = {
    "scripts.train.main": 1,
    "ReflACTTrainer.train": 1,
    "merge_patches": 1,
    "rank_and_select": 1,
    "apply_patch_with_report": 1,
    "evaluate_gate": 1,
    "select_gate_score": 2,
    "scripts.eval_only.main": 1,
}
_EXPECTED_CALL_COUNTS = {
    "ReflACTTrainer.train": 1,
    "adapter.build_env_from_batch": 8,
    "adapter.build_eval_env": 3,
    "adapter.build_train_env": 0,
    "adapter.reflect": 1,
    "adapter.rollout": 6,
    "adapter.setup": 2,
    "apply_patch_with_report": 1,
    "evaluate_gate": 1,
    "merge_patches": 1,
    "rank_and_select": 1,
    "scripts.eval_only.main": 1,
    "scripts.train.main": 1,
    "select_gate_score": 3,
}
_CANONICAL_SPLIT_MAPPING = {
    "train": "train",
    "valid_seen": "val",
    "valid_unseen": "test",
}
_RUNTIME_CONFIG_KNOB_MAP = {
    **{key: key for key in CANONICAL_EXECUTION_KNOBS if key != "env_name"},
    "env_name": "env",
}
_DERIVED_RUNTIME_CONFIG = {
    "batches_per_epoch": 1,
    "samples_per_epoch": 3,
    "steps_per_epoch": 1,
}
_CALL_BINDING_PATHS = {
    "scripts.train.main": "scripts/train.py",
    "scripts.train.get_adapter": "scripts/train.py",
    "ReflACTTrainer.train": "skillopt/engine/trainer.py",
    "merge_patches": "skillopt/gradient/aggregate.py",
    "rank_and_select": "skillopt/optimizer/clip.py",
    "apply_patch_with_report": "skillopt/optimizer/skill.py",
    "evaluate_gate": "skillopt/evaluation/gate.py",
    "select_gate_score": "skillopt/evaluation/gate.py",
    "scripts.eval_only.main": "scripts/eval_only.py",
    "scripts.eval_only.get_adapter": "scripts/eval_only.py",
    "adapter.setup": ADAPTER_PATH,
    "adapter.build_env_from_batch": ADAPTER_PATH,
    "adapter.build_train_env": ADAPTER_PATH,
    "adapter.build_eval_env": ADAPTER_PATH,
    "adapter.rollout": ADAPTER_PATH,
    "adapter.reflect": ADAPTER_PATH,
}
_REQUIRED_CALLABLE_SPECS = {
    "scripts.train.main": ("scripts.train", "main"),
    "scripts.train.get_adapter": ("scripts.train", "get_adapter"),
    "ReflACTTrainer.train": ("skillopt.engine.trainer", "ReflACTTrainer.train"),
    "merge_patches": ("skillopt.gradient.aggregate", "merge_patches"),
    "rank_and_select": ("skillopt.optimizer.clip", "rank_and_select"),
    "apply_patch_with_report": (
        "skillopt.optimizer.skill",
        "apply_patch_with_report",
    ),
    "evaluate_gate": ("skillopt.evaluation.gate", "evaluate_gate"),
    "select_gate_score": ("skillopt.evaluation.gate", "select_gate_score"),
    "scripts.eval_only.main": ("scripts.eval_only", "main"),
    "scripts.eval_only.get_adapter": ("scripts.eval_only", "get_adapter"),
    "adapter.setup": (
        "skillopt.envs.jiphyeonjeon_search.adapter",
        "JiphyeonjeonSearchAdapter.setup",
    ),
    "adapter.build_env_from_batch": (
        "skillopt.envs.jiphyeonjeon_search.adapter",
        "JiphyeonjeonSearchAdapter.build_env_from_batch",
    ),
    "adapter.build_train_env": (
        "skillopt.envs.jiphyeonjeon_search.adapter",
        "JiphyeonjeonSearchAdapter.build_train_env",
    ),
    "adapter.build_eval_env": (
        "skillopt.envs.jiphyeonjeon_search.adapter",
        "JiphyeonjeonSearchAdapter.build_eval_env",
    ),
    "adapter.rollout": (
        "skillopt.envs.jiphyeonjeon_search.adapter",
        "JiphyeonjeonSearchAdapter.rollout",
    ),
    "adapter.reflect": (
        "skillopt.envs.jiphyeonjeon_search.adapter",
        "JiphyeonjeonSearchAdapter.reflect",
    ),
}
_PROVIDER_CALL_NAMES = {
    "chat_messages_with_deployment",
    "chat_optimizer",
    "chat_optimizer_messages",
    "chat_target",
    "chat_target_messages",
    "chat_with_deployment",
    "run_claude_code_exec",
    "run_codex_exec",
    "run_target_exec",
}
ADAPTER_BYTES = b'''"""Deterministic mock-only Jiphyeonjeon SkillOpt adapter."""
from __future__ import annotations

from skillopt.datasets.base import BatchSpec, SplitDataLoader
from skillopt.envs.base import EnvAdapter


_SUCCESS_MARKER = "JIPHYEONJEON_COMPATIBILITY_MARKER_V1"


class JiphyeonjeonSearchAdapter(EnvAdapter):
    def __init__(
        self,
        split_dir: str = "",
        data_path: str = "",
        split_mode: str = "split_dir",
        split_ratio: str = "2:1:7",
        split_seed: int = 42,
        split_output_dir: str = "",
        workers: int = 1,
        analyst_workers: int = 1,
        failure_only: bool = True,
        minibatch_size: int = 1,
        edit_budget: int = 1,
        seed: int = 42,
        limit: int = 0,
        mock: bool = True,
    ) -> None:
        if mock is not True:
            raise ValueError("JiphyeonjeonSearchAdapter is mock-only")
        if split_mode != "split_dir":
            raise ValueError("JiphyeonjeonSearchAdapter requires split_mode=split_dir")
        self.workers = int(workers)
        self.analyst_workers = int(analyst_workers)
        self.failure_only = bool(failure_only)
        self.minibatch_size = int(minibatch_size)
        self.edit_budget = int(edit_budget)
        self.dataloader = SplitDataLoader(
            split_dir=split_dir,
            data_path=data_path,
            split_mode=split_mode,
            split_ratio=split_ratio,
            split_seed=split_seed,
            split_output_dir=split_output_dir,
            seed=seed,
            limit=limit,
        )

    def setup(self, cfg: dict) -> None:
        super().setup(cfg)
        if cfg.get("mock") is not True:
            raise ValueError("JiphyeonjeonSearchAdapter is mock-only")
        self.dataloader.setup(cfg)

    def get_dataloader(self):
        return self.dataloader

    def build_env_from_batch(self, batch: BatchSpec, **kwargs):
        return list(batch.payload or [])

    def build_train_env(self, batch_size: int, seed: int, **kwargs):
        batch = self.dataloader.build_train_batch(
            batch_size=batch_size, seed=seed, **kwargs
        )
        return self.build_env_from_batch(batch, **kwargs)

    def build_eval_env(self, env_num: int, split: str, seed: int, **kwargs):
        physical_split = {
            "train": "train",
            "valid_seen": "val",
            "valid_unseen": "test",
        }.get(split, split)
        batch = self.dataloader.build_eval_batch(
            env_num=env_num, split=physical_split, seed=seed, **kwargs
        )
        return self.build_env_from_batch(batch, **kwargs)

    def rollout(
        self, env_manager, skill_content: str, out_dir: str, **kwargs
    ) -> list[dict]:
        del out_dir, kwargs
        passed = _SUCCESS_MARKER in skill_content
        return [
            {
                "id": str(item["id"]),
                "hard": int(passed),
                "soft": float(passed),
                "n_turns": 1,
                "fail_reason": "" if passed else "compatibility marker missing",
                "query": str(item.get("query", "")),
                "split": str(item.get("split", "")),
                "task_type": "paper_search",
            }
            for item in env_manager
        ]

    def reflect(
        self, results: list[dict], skill_content: str, out_dir: str, **kwargs
    ) -> list[dict]:
        del skill_content, out_dir, kwargs
        failures = [result for result in results if not result.get("hard")]
        if not failures:
            return []
        return [
            {
                "patch": {
                    "edits": [
                        {
                            "op": "append",
                            "content": "\\n\\n" + _SUCCESS_MARKER + "\\n",
                        }
                    ],
                    "reasoning": "Add the deterministic compatibility marker.",
                },
                "source_type": "failure",
                "batch_size": len(failures),
            }
        ]

    def get_task_types(self) -> list[str]:
        return ["paper_search"]
'''


_OVERLAY_PAYLOADS: dict[str, bytes] = {
    ADAPTER_PATH: ADAPTER_BYTES,
    PROFILE_CONFIG_PATH: CANONICAL_RENDERED_CONFIG_BYTES,
    SKILL_INIT_PATH: INITIAL_SKILL_BYTES,
    SPLIT_MANIFEST_PATH: CANONICAL_SPLIT_MANIFEST_BYTES,
    SPLIT_TRAIN_ITEMS_PATH: CANONICAL_SPLIT_ITEM_BYTES["train"],
    SPLIT_VAL_ITEMS_PATH: CANONICAL_SPLIT_ITEM_BYTES["val"],
    SPLIT_TEST_ITEMS_PATH: CANONICAL_SPLIT_ITEM_BYTES["test"],
    QUERY_ANALYZER_CONTRACT_PATH: QUERY_ANALYZER_CONTRACT_BYTES,
    OVERLAY_SCHEMA_PATH: OVERLAY_SCHEMA_BYTES,
    REGISTRY_PATCH_CONTRACT_PATH: REGISTRY_PATCH_CONTRACT_BYTES,
}


class _ExecutionDenied(RuntimeError):
    """Raised before a forbidden action can cross the diagnostic boundary."""


class _ExecutionSentinel:
    def __init__(self, execution_root: Path) -> None:
        self.execution_root = execution_root.resolve(strict=True)
        self.execution_prefix = f"{self.execution_root}{os.sep}"
        self._counts = {kind: 0 for kind in _EXECUTION_KINDS}
        self.calls = {name: 0 for name in _CALL_TARGETS.values()}
        self.phase = "imports"
        self.exact_codes: dict[types.CodeType, str] = {}
        self.target_code_keys: dict[tuple[str, str], types.CodeType] = {}
        self.eval_input_ids: list[str] = []
        self.eval_result_ids: list[str] = []
        self.split_observations: list[dict[str, Any]] = []
        self._split_calls: dict[int, dict[str, Any]] = {}
        self.candidate_fd = -1
        self.candidate_payload = b""
        self.candidate_sha256 = ""
        self.eval_candidate_read_count = 0
        self.eval_candidate_read_sha256 = ""
        self.writer_open_count = 0
        self.writer_open_path = ""
        self.writer_open_mode = ""

    def bind_exact_codes(self, callables: Mapping[str, Any]) -> None:
        exact: dict[types.CodeType, str] = {}
        target_keys: dict[tuple[str, str], types.CodeType] = {}
        for label, value in callables.items():
            code = getattr(value, "__code__", None)
            if not isinstance(code, types.CodeType):
                continue
            exact[code] = label
            try:
                relative = (
                    Path(code.co_filename)
                    .resolve(strict=True)
                    .relative_to(self.execution_root)
                    .as_posix()
                )
            except (OSError, ValueError) as exc:
                raise ValidationError(
                    f"exact callable escaped execution root: {label}"
                ) from exc
            target_keys[(relative, code.co_name)] = code
        self.exact_codes = exact
        self.target_code_keys = target_keys

    def hold_candidate(self, fd: int, payload: bytes) -> None:
        if self.candidate_fd >= 0:
            raise ValidationError("candidate evidence descriptor is already held")
        self.candidate_fd = fd
        self.candidate_payload = payload
        self.candidate_sha256 = hashlib.sha256(payload).hexdigest()

    def close_candidate(self) -> None:
        if self.candidate_fd >= 0:
            os.close(self.candidate_fd)
        self.candidate_fd = -1

    def _stack_has_exact(self, label: str) -> bool:
        frame = sys._getframe(2)
        while frame is not None:
            if self.exact_codes.get(frame.f_code) == label:
                return True
            frame = frame.f_back
        return False

    def open(
        self,
        original: Any,
        file: Any,
        mode: str = "r",
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        candidate_path = self.execution_root / CANDIDATE_PATH
        try:
            supplied = os.fspath(file)
        except TypeError:
            supplied = None
        if isinstance(supplied, (str, bytes)):
            absolute = Path(os.path.abspath(os.fsdecode(supplied)))
        else:
            absolute = None
        if self.phase == "train" and absolute == candidate_path:
            if mode == "w" and self._stack_has_exact("ReflACTTrainer.train"):
                if type(file) is not str or file != str(candidate_path):
                    raise ValidationError("candidate writer used a non-canonical path")
                self.writer_open_count += 1
                self.writer_open_path = CANDIDATE_PATH
                self.writer_open_mode = mode
            elif any(character in mode for character in "wax+"):
                raise ValidationError(
                    "candidate writer escaped the exact trainer stack"
                )
        if self.phase != "eval" or absolute != candidate_path:
            return original(file, mode, *args, **kwargs)
        if (
            self.candidate_fd < 0
            or type(file) is not str
            or file != str(candidate_path)
            or mode != "r"
            or args
            or kwargs
            or not self._stack_has_exact("scripts.eval_only.main")
        ):
            raise ValidationError("eval candidate open is not canonical")
        if self.eval_candidate_read_count != 0:
            raise ValidationError("eval candidate was opened more than once")
        duplicate = os.dup(self.candidate_fd)
        payload = _read_all_fd(duplicate)
        os.close(duplicate)
        if payload != self.candidate_payload:
            raise ValidationError("held candidate descriptor bytes changed")
        return _TrackedCandidateReader(payload, self)

    def deny(self, kind: str, detail: str) -> NoReturn:
        self._counts[kind] += 1
        raise _ExecutionDenied(f"{kind} denied before execution: {detail}")

    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    def profile(self, frame: types.FrameType, event: str, arg: Any) -> None:
        filename = frame.f_code.co_filename
        if not filename.startswith(self.execution_prefix):
            return
        relative = filename.removeprefix(self.execution_prefix).replace(os.sep, "/")
        name = frame.f_code.co_name
        if (
            event == "call"
            and relative.startswith("skillopt/model/")
            and name in _PROVIDER_CALL_NAMES
        ):
            self.deny("provider", f"{relative}:{name}")
        target = _CALL_TARGETS.get((relative, name))
        if event == "call" and target is not None:
            expected_code = self.target_code_keys.get((relative, name))
            if expected_code is None or frame.f_code is not expected_code:
                raise ValidationError(
                    f"forged upstream frame rejected: {relative}:{name}"
                )
            if self.exact_codes.get(frame.f_code) != target:
                raise ValidationError(f"unbound upstream frame rejected: {target}")
            self.calls[target] += 1
        if (
            relative == ADAPTER_PATH
            and name == "build_eval_env"
            and self.phase == "eval"
        ):
            if event == "call":
                self._split_calls[id(frame)] = {
                    "logical_split": frame.f_locals.get("split"),
                    "env_num": frame.f_locals.get("env_num"),
                    "seed": frame.f_locals.get("seed"),
                }
            elif event == "return":
                observation = self._split_calls.pop(id(frame), None)
                if observation is None or not isinstance(arg, list):
                    raise ValidationError("eval split observation is incomplete")
                observation["ids"] = _item_ids(arg)
                observation["physical_splits"] = sorted(
                    {
                        str(item.get("split"))
                        for item in arg
                        if isinstance(item, Mapping)
                    }
                )
                self.split_observations.append(observation)
        if (
            event == "call"
            and self.phase == "eval"
            and relative == ADAPTER_PATH
            and name == "rollout"
        ):
            self.eval_input_ids = _item_ids(frame.f_locals.get("env_manager"))
        if (
            event == "return"
            and self.phase == "eval"
            and relative == ADAPTER_PATH
            and name == "rollout"
            and isinstance(arg, list)
        ):
            self.eval_result_ids = _item_ids(arg)


def _item_ids(items: Any) -> list[str]:
    if not isinstance(items, list) or any(
        not isinstance(item, Mapping) for item in items
    ):
        raise ValidationError("adapter items must be a list of mappings")
    return [str(item.get("id")) for item in items]


class _TrackedCandidateReader(io.StringIO):
    def __init__(self, payload: bytes, sentinel: _ExecutionSentinel) -> None:
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError("held candidate is not UTF-8") from exc
        super().__init__(content)
        self._sentinel = sentinel
        self._returned = bytearray()

    def read(self, size: int = -1) -> str:
        result = super().read(size)
        self._returned.extend(result.encode("utf-8"))
        return result

    def __exit__(self, *args: Any) -> None:
        result = super().__exit__(*args)
        payload = bytes(self._returned)
        if payload != self._sentinel.candidate_payload:
            raise ValidationError("eval did not read the exact held candidate bytes")
        self._sentinel.eval_candidate_read_count += 1
        self._sentinel.eval_candidate_read_sha256 = hashlib.sha256(payload).hexdigest()
        return result


class _CanonicalProtectedSourceLoader:
    """Compile one protected module only from held, manifest-approved bytes."""

    def __init__(
        self,
        *,
        fullname: str,
        filename: str,
        payload: bytes,
        source_sha256: str,
        is_package: bool,
    ) -> None:
        self.fullname = fullname
        self.filename = filename
        self.payload = payload
        self.source_sha256 = source_sha256
        self.package = is_package

    def create_module(self, spec: Any) -> None:
        del spec
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        if (
            module.__name__ != self.fullname
            or module.__spec__ is None
            or module.__spec__.loader is not self
            or module.__spec__.origin != self.filename
        ):
            raise ValidationError("canonical protected module spec changed")
        code = _CANONICAL_COMPILE(
            self.payload, self.filename, "exec", dont_inherit=True
        )
        _CANONICAL_EXEC(code, module.__dict__)

    def get_filename(self, fullname: str) -> str:
        if fullname != self.fullname:
            raise ImportError(fullname)
        return self.filename

    def is_package(self, fullname: str) -> bool:
        if fullname != self.fullname:
            raise ImportError(fullname)
        return self.package


class _CanonicalProtectedFinder:
    """Resolve every protected name before any ambient finder or path hook."""

    def __init__(
        self,
        root: Path,
        sources: Mapping[str, tuple[str, bytes, str, bool]],
        namespaces: Mapping[str, str],
    ) -> None:
        self.root = root
        self.sources = dict(sources)
        self.namespaces = dict(namespaces)

    def find_spec(
        self,
        fullname: str,
        path: Any = None,
        target: Any = None,
    ) -> Any:
        del path, target
        if not _is_protected_module_name(fullname):
            return None
        source = self.sources.get(fullname)
        if source is not None:
            relative, payload, source_sha256, is_package = source
            filename = str(self.root / relative)
            loader = _CanonicalProtectedSourceLoader(
                fullname=fullname,
                filename=filename,
                payload=payload,
                source_sha256=source_sha256,
                is_package=is_package,
            )
            return _CANONICAL_SPEC_FROM_FILE_LOCATION(
                fullname,
                filename,
                loader=loader,
                submodule_search_locations=(
                    [str(Path(filename).parent)] if is_package else None
                ),
            )
        namespace = self.namespaces.get(fullname)
        if namespace is not None:
            spec = importlib.machinery.ModuleSpec(fullname, None, is_package=True)
            spec.submodule_search_locations = [str(self.root / namespace)]
            return spec
        raise ModuleNotFoundError(
            f"protected module is not manifest-listed: {fullname}", name=fullname
        )


def _is_protected_module_name(name: str) -> bool:
    return any(
        name == prefix or name.startswith(f"{prefix}.")
        for prefix in _PROTECTED_PREFIXES
    )


def _protected_module_name(relative: str) -> tuple[str, bool]:
    stem = relative.removesuffix(".py")
    if stem.endswith("/__init__"):
        return stem.removesuffix("/__init__").replace("/", "."), True
    return stem.replace("/", "."), False


def _build_protected_finder(
    root: Path, lease: _ExecutionProjectionLease
) -> _CanonicalProtectedFinder:
    lease.verify_live()
    sources: dict[str, tuple[str, bytes, str, bool]] = {}
    namespaces: dict[str, str] = {}
    entries = {entry["path"]: entry for entry in lease.manifest["immutable_files"]}
    for relative, entry in sorted(entries.items()):
        if not relative.endswith(".py") or not relative.startswith(
            tuple(f"{prefix}/" for prefix in _PROTECTED_PREFIXES)
        ):
            continue
        fd = lease.file_fds[relative]
        before = os.fstat(fd)
        payload = _read_all_fd(fd)
        after = os.fstat(fd)
        observed = hashlib.sha256(payload).hexdigest()
        if _file_changed(before, after) or observed != entry["sha256"]:
            raise ValidationError(
                f"protected source changed while being held: {relative}"
            )
        name, is_package = _protected_module_name(relative)
        sources[name] = (relative, payload, observed, is_package)
        parts = relative.split("/")[:-1]
        for index in range(1, len(parts) + 1):
            namespace_name = ".".join(parts[:index])
            namespaces.setdefault(namespace_name, "/".join(parts[:index]))
    for name in sources:
        namespaces.pop(name, None)
    lease.verify_live()
    return _CanonicalProtectedFinder(root, sources, namespaces)


def _validate_canonical_import_machinery() -> None:
    changed = [
        f"{owner.__name__}.{name}"
        for owner, name, expected in _CANONICAL_IMPORT_MACHINERY
        if inspect.getattr_static(owner, name) is not expected
    ]
    if changed:
        raise ValidationError(
            "canonical import machinery was replaced: " + ", ".join(changed)
        )


def _execution_audit_hook(event: str, args: tuple[Any, ...]) -> None:
    del args
    observer = _AUDIT_OBSERVER
    if observer is None or observer[0] != threading.get_ident():
        return
    if event == "subprocess.Popen" or event in {
        "os.exec",
        "os.fork",
        "os.forkpty",
        "os.posix_spawn",
        "os.system",
    }:
        raise _ExecutionDenied(f"subprocess audit event denied: {event}")
    if event.startswith("socket."):
        raise _ExecutionDenied(f"network audit event denied: {event}")


def _ensure_execution_audit_hook() -> None:
    global _AUDIT_HOOK_INSTALLED
    if not _AUDIT_HOOK_INSTALLED:
        _CANONICAL_ADD_AUDIT_HOOK(_execution_audit_hook)
        _AUDIT_HOOK_INSTALLED = True


@contextmanager
def _restricted_execution_boundary(
    sentinel: _ExecutionSentinel,
    protected_finder: _CanonicalProtectedFinder | None = None,
) -> Iterator[None]:
    """Provide diagnostic in-process containment, not an OS sandbox."""

    global _AUDIT_OBSERVER

    def deny_network(*args: Any, **kwargs: Any) -> NoReturn:
        del args, kwargs
        sentinel.deny("network", "socket entry point")

    def deny_subprocess(*args: Any, **kwargs: Any) -> NoReturn:
        del args, kwargs
        sentinel.deny("subprocess", "process entry point")

    socket_targets = tuple(
        (socket, name, deny_network)
        for name in ("socket", "create_connection", "create_server")
        if hasattr(socket, name)
    )
    subprocess_targets = tuple(
        (subprocess, name, deny_subprocess)
        for name in (
            "Popen",
            "run",
            "call",
            "check_call",
            "check_output",
            "getoutput",
            "getstatusoutput",
        )
        if hasattr(subprocess, name)
    )
    os_targets = tuple(
        (os, name, deny_subprocess)
        for name in dir(os)
        if name in {"system", "popen", "posix_spawn", "posix_spawnp"}
        or name.startswith(("spawn", "fork", "exec"))
    )
    asyncio_targets = tuple(
        (asyncio, name, deny_subprocess)
        for name in ("create_subprocess_exec", "create_subprocess_shell")
        if hasattr(asyncio, name)
    )
    replacements = socket_targets + subprocess_targets + os_targets + asyncio_targets
    owner = threading.get_ident()
    current = threading.current_thread()
    main = threading.main_thread()
    live_threads = [thread for thread in threading.enumerate() if thread.is_alive()]
    if current is not main or live_threads != [current]:
        raise ValidationError(
            "diagnostic execution requires sole ownership by the main thread"
        )
    token = object()
    profile_callback = sentinel.profile
    with _EXECUTION_LOCK:
        _ensure_execution_audit_hook()
        _validate_canonical_import_machinery()
        if _EXECUTION_OWNER_STACK and _EXECUTION_OWNER_STACK[-1][0] != owner:
            raise ValidationError("execution boundary ownership is inconsistent")
        if _AUDIT_OBSERVER is not None:
            raise ValidationError("execution audit observer is already active")
        _EXECUTION_OWNER_STACK.append((owner, token))
        installed: list[tuple[Any, str, Any, Any]] = []
        prior_sys_profile = sys.getprofile()
        prior_thread_profile = threading.getprofile()
        prior_open = builtins.open
        prior_import = builtins.__import__
        prior_meta_path_object = sys.meta_path
        prior_meta_path = list(sys.meta_path)
        prior_path_hooks_object = sys.path_hooks
        prior_path_hooks = list(sys.path_hooks)

        def guarded_open(
            file: Any,
            mode: str = "r",
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            return sentinel.open(_CANONICAL_OPEN, file, mode, *args, **kwargs)

        try:
            _AUDIT_OBSERVER = (owner, token)
            for namespace, name, replacement in replacements:
                original = getattr(namespace, name)
                setattr(namespace, name, replacement)
                installed.append((namespace, name, original, replacement))
            builtins.open = guarded_open
            builtins.__import__ = _CANONICAL_IMPORT
            sys.meta_path = [
                *([protected_finder] if protected_finder is not None else []),
                *_CANONICAL_META_PATH,
            ]
            sys.path_hooks = list(_CANONICAL_PATH_HOOKS)
            sys.setprofile(profile_callback)
            threading.setprofile(profile_callback)
            yield
        finally:
            _AUDIT_OBSERVER = None
            ownership_drift: list[str] = []
            if not _EXECUTION_OWNER_STACK or _EXECUTION_OWNER_STACK[-1] != (
                owner,
                token,
            ):
                ownership_drift.append("execution owner stack")
            for namespace, name, _, replacement in reversed(installed):
                try:
                    current = getattr(namespace, name)
                except BaseException:
                    ownership_drift.append(f"{namespace.__name__}.{name}")
                else:
                    if current is not replacement:
                        ownership_drift.append(f"{namespace.__name__}.{name}")
            if sys.getprofile() is not profile_callback:
                ownership_drift.append("sys profile")
            if threading.getprofile() is not profile_callback:
                ownership_drift.append("threading profile")
            if builtins.open is not guarded_open:
                ownership_drift.append("builtins.open")
            if builtins.__import__ is not _CANONICAL_IMPORT:
                ownership_drift.append("builtins.__import__")
            expected_meta_path = [
                *([protected_finder] if protected_finder is not None else []),
                *_CANONICAL_META_PATH,
            ]
            if len(sys.meta_path) != len(expected_meta_path) or any(
                current is not expected
                for current, expected in zip(
                    sys.meta_path, expected_meta_path, strict=False
                )
            ):
                ownership_drift.append("sys.meta_path")
            if len(sys.path_hooks) != len(_CANONICAL_PATH_HOOKS) or any(
                current is not expected
                for current, expected in zip(
                    sys.path_hooks, _CANONICAL_PATH_HOOKS, strict=False
                )
            ):
                ownership_drift.append("sys.path_hooks")
            restoration_failures: list[str] = []
            try:
                sys.setprofile(prior_sys_profile)
            except BaseException:
                restoration_failures.append("sys profile")
            try:
                threading.setprofile(prior_thread_profile)
            except BaseException:
                restoration_failures.append("threading profile")
            try:
                builtins.open = prior_open
            except BaseException:
                restoration_failures.append("builtins.open")
            try:
                builtins.__import__ = prior_import
            except BaseException:
                restoration_failures.append("builtins.__import__")
            try:
                sys.meta_path = prior_meta_path_object
                prior_meta_path_object[:] = prior_meta_path
            except BaseException:
                restoration_failures.append("sys.meta_path")
            try:
                sys.path_hooks = prior_path_hooks_object
                prior_path_hooks_object[:] = prior_path_hooks
            except BaseException:
                restoration_failures.append("sys.path_hooks")
            for namespace, name, original, _ in reversed(installed):
                try:
                    setattr(namespace, name, original)
                except BaseException:
                    restoration_failures.append(f"{namespace.__name__}.{name}")
            if _EXECUTION_OWNER_STACK and _EXECUTION_OWNER_STACK[-1] == (
                owner,
                token,
            ):
                _EXECUTION_OWNER_STACK.pop()
            if ownership_drift or restoration_failures:
                details = []
                if ownership_drift:
                    details.append("lost hook ownership: " + ", ".join(ownership_drift))
                if restoration_failures:
                    details.append(
                        "could not restore: " + ", ".join(restoration_failures)
                    )
                raise ValidationError("execution boundary " + "; ".join(details))


class _ExecutionProjectionLease:
    """Hold and re-verify one projection while output descendants evolve."""

    def __init__(self, root: Path, manifest: Mapping[str, Any]) -> None:
        self.root = root
        self.manifest = copy.deepcopy(dict(manifest))
        self.root_fd = -1
        self.file_fds: dict[str, int] = {}
        self.file_stats: dict[str, os.stat_result] = {}
        self.directory_fds: dict[str, int] = {}
        self.directory_stats: dict[str, os.stat_result] = {}
        self.output_fds: dict[str, int] = {}
        self.output_stats: dict[str, os.stat_result] = {}
        self.output_chains: dict[str, tuple[int, ...]] = {}
        self.output_chain_stats: dict[str, tuple[os.stat_result, ...]] = {}
        self.root_stat: os.stat_result | None = None
        self._acquire()

    def __enter__(self) -> _ExecutionProjectionLease:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            self.verify_live()
        finally:
            self._close()
        return False

    def _acquire(self) -> None:
        try:
            if (
                seal_identity_artifact(self.manifest, EXECUTION_PROJECTION_VERSION)
                != self.manifest
            ):
                raise ValidationError("execution projection identity mismatch")
            root_stat = self.root.lstat()
            if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
                raise ValidationError("execution root must be a real directory")
            self.root_fd = os.open(
                self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            self.root_stat = os.fstat(self.root_fd)
            if not _same_stat_inode(root_stat, self.root_stat):
                raise ValidationError("execution root changed while opening")
            for entry in self.manifest["immutable_directories"]:
                path = self.root / entry["path"]
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                current = os.fstat(fd)
                if not stat.S_ISDIR(current.st_mode):
                    os.close(fd)
                    raise ValidationError(
                        f"immutable projection path is not a directory: {entry['path']}"
                    )
                self.directory_fds[entry["path"]] = fd
                self.directory_stats[entry["path"]] = current
            for entry in self.manifest["immutable_files"]:
                path = self.root / entry["path"]
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                current = os.fstat(fd)
                self.file_fds[entry["path"]] = fd
                self.file_stats[entry["path"]] = current
            for relative in self.manifest["mutable_roots"]:
                chain = _open_relative_directory_chain(self.root_fd, relative)
                fd = chain[-1]
                self.output_fds[relative] = fd
                self.output_stats[relative] = os.fstat(fd)
                self.output_chains[relative] = chain
                self.output_chain_stats[relative] = tuple(
                    os.fstat(component_fd) for component_fd in chain
                )
            self.verify_live()
        except BaseException:
            self._close()
            raise

    def verify_live(self) -> None:
        if self.root_fd < 0 or self.root_stat is None:
            raise ValidationError("execution projection lease is closed")
        root_path_stat = self.root.lstat()
        root_held_stat = os.fstat(self.root_fd)
        if not _same_stat_inode(root_path_stat, root_held_stat):
            raise ValidationError("execution root was replaced")
        if _directory_changed(self.root_stat, root_held_stat):
            raise ValidationError("execution root topology changed")
        expected_files = {entry["path"] for entry in self.manifest["immutable_files"]}
        expected_dirs = {
            entry["path"] for entry in self.manifest["immutable_directories"]
        }
        actual_files, actual_dirs = _projection_immutable_inventory(self.root)
        if actual_files != expected_files or actual_dirs != expected_dirs:
            raise ValidationError("execution projection immutable topology changed")
        for entry in self.manifest["immutable_directories"]:
            relative = entry["path"]
            path_stat = (self.root / relative).lstat()
            held_stat = os.fstat(self.directory_fds[relative])
            if not _same_stat_inode(path_stat, held_stat):
                raise ValidationError(
                    f"immutable projection directory was replaced: {relative}"
                )
            if _directory_changed(self.directory_stats[relative], held_stat):
                raise ValidationError(
                    f"immutable projection directory changed: {relative}"
                )
            if f"{stat.S_IMODE(held_stat.st_mode):04o}" != entry["mode"]:
                raise ValidationError(
                    f"immutable projection directory mode changed: {relative}"
                )
        for entry in self.manifest["immutable_files"]:
            relative = entry["path"]
            path_stat = (self.root / relative).lstat()
            held_stat = os.fstat(self.file_fds[relative])
            if not stat.S_ISREG(held_stat.st_mode) or held_stat.st_nlink != 1:
                raise ValidationError(
                    f"immutable projection file is not single-link regular: {relative}"
                )
            if not _same_stat_inode(path_stat, held_stat):
                raise ValidationError(
                    f"immutable projection file was replaced: {relative}"
                )
            if (
                _file_changed(self.file_stats[relative], held_stat)
                or f"{stat.S_IMODE(held_stat.st_mode):04o}" != entry["mode"]
                or held_stat.st_size != entry["size_bytes"]
                or _sha256_open_fd(self.file_fds[relative]) != entry["sha256"]
            ):
                raise ValidationError(f"immutable projection file changed: {relative}")
        outputs_fd = _open_relative_directory(self.root_fd, "outputs")
        try:
            output_names = set(os.listdir(outputs_fd))
        finally:
            os.close(outputs_fd)
        if output_names != {"train", "eval"}:
            raise ValidationError(
                "execution outputs topology must be exactly train/eval"
            )
        for relative, fd in self.output_fds.items():
            held_stat = os.fstat(fd)
            reopened = _open_relative_directory(self.root_fd, relative)
            try:
                reopened_stat = os.fstat(reopened)
            finally:
                os.close(reopened)
            if not stat.S_ISDIR(held_stat.st_mode) or not _same_stat_inode(
                reopened_stat, held_stat
            ):
                raise ValidationError(f"mutable output root was replaced: {relative}")
            if stat.S_IMODE(held_stat.st_mode) != stat.S_IMODE(
                self.output_stats[relative].st_mode
            ):
                raise ValidationError(f"mutable output root mode changed: {relative}")
            _snapshot_output_tree(self, relative)

    def _close(self) -> None:
        for collection in (self.file_fds, self.directory_fds):
            for fd in collection.values():
                try:
                    os.close(fd)
                except OSError:
                    pass
            collection.clear()
        for chain in self.output_chains.values():
            for fd in reversed(chain):
                try:
                    os.close(fd)
                except OSError:
                    pass
        self.output_chains.clear()
        self.output_chain_stats.clear()
        self.output_fds.clear()
        self.output_stats.clear()
        if self.root_fd >= 0:
            try:
                os.close(self.root_fd)
            except OSError:
                pass
        self.root_fd = -1


def _relative_path_parts(relative: str) -> tuple[str, ...]:
    if (
        not isinstance(relative, str)
        or not relative
        or relative.startswith("/")
        or "\\" in relative
    ):
        raise ValidationError("mutable evidence path must be relative POSIX")
    parts = tuple(relative.split("/"))
    if any(part in {"", ".", ".."} or "\x00" in part for part in parts):
        raise ValidationError("mutable evidence path contains an invalid component")
    return parts


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _file_open_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _open_relative_directory(root_fd: int, relative: str) -> int:
    chain = _open_relative_directory_chain(root_fd, relative)
    result = chain[-1]
    for fd in chain[:-1]:
        os.close(fd)
    return result


def _open_relative_directory_chain(root_fd: int, relative: str) -> tuple[int, ...]:
    current = root_fd
    opened: list[int] = []
    try:
        for part in _relative_path_parts(relative):
            following = os.open(part, _directory_open_flags(), dir_fd=current)
            current_stat = os.fstat(following)
            if not stat.S_ISDIR(current_stat.st_mode):
                os.close(following)
                raise ValidationError(
                    f"mutable evidence component is not a directory: {part}"
                )
            opened.append(following)
            current = following
        return tuple(opened)
    except (OSError, ValidationError) as exc:
        for fd in reversed(opened):
            try:
                os.close(fd)
            except OSError:
                pass
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError("mutable evidence directory traversal failed") from exc


def _read_all_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while chunk := os.read(fd, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


def _file_changed(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        not _same_stat_inode(first, second)
        or stat.S_IMODE(first.st_mode) != stat.S_IMODE(second.st_mode)
        or first.st_nlink != second.st_nlink
        or first.st_size != second.st_size
        or first.st_mtime_ns != second.st_mtime_ns
        or first.st_ctime_ns != second.st_ctime_ns
    )


def _verify_output_anchor(lease: _ExecutionProjectionLease, output_root: str) -> None:
    held_fd = lease.output_fds.get(output_root)
    if held_fd is None or lease.root_fd < 0:
        raise ValidationError("mutable evidence output root is not leased")
    chain = lease.output_chains.get(output_root)
    chain_stats = lease.output_chain_stats.get(output_root)
    if chain is None or chain_stats is None:
        raise ValidationError("mutable evidence output chain is not leased")
    parts = _relative_path_parts(output_root)
    parent_fd = lease.root_fd
    try:
        for index, (part, component_fd, initial_stat) in enumerate(
            zip(parts, chain, chain_stats, strict=True)
        ):
            reopened = os.open(part, _directory_open_flags(), dir_fd=parent_fd)
            try:
                held_stat = os.fstat(component_fd)
                reopened_stat = os.fstat(reopened)
                if (
                    not stat.S_ISDIR(held_stat.st_mode)
                    or not _same_stat_inode(held_stat, reopened_stat)
                    or stat.S_IMODE(held_stat.st_mode)
                    != stat.S_IMODE(initial_stat.st_mode)
                    or (
                        index < len(chain) - 1
                        and _directory_changed(initial_stat, held_stat)
                    )
                ):
                    raise ValidationError(
                        f"mutable output component was replaced: {output_root}"
                    )
            finally:
                os.close(reopened)
            parent_fd = component_fd
    except OSError as exc:
        raise ValidationError(
            f"mutable output component is unreadable: {output_root}"
        ) from exc
    if chain[-1] != held_fd:
        raise ValidationError("mutable evidence output root binding drifted")


def _open_evidence_parent(
    lease: _ExecutionProjectionLease, output_root: str, relative: str
) -> tuple[int, list[tuple[int, int, str, os.stat_result]]]:
    parts = _relative_path_parts(relative)
    current = os.dup(lease.output_fds[output_root])
    held: list[tuple[int, int, str, os.stat_result]] = []
    try:
        for part in parts[:-1]:
            parent_stat = os.fstat(current)
            child = os.open(part, _directory_open_flags(), dir_fd=current)
            child_stat = os.fstat(child)
            entry_stat = os.stat(part, dir_fd=current, follow_symlinks=False)
            if not stat.S_ISDIR(child_stat.st_mode) or not _same_stat_inode(
                entry_stat, child_stat
            ):
                os.close(child)
                raise ValidationError(
                    f"mutable evidence directory changed while opening: {part}"
                )
            held.append((current, child, part, parent_stat))
            current = child
        return current, held
    except (OSError, ValidationError) as exc:
        for parent, child, _, _ in reversed(held):
            for fd in (child, parent):
                try:
                    os.close(fd)
                except OSError:
                    pass
        if not held:
            try:
                os.close(current)
            except OSError:
                pass
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError("mutable evidence parent traversal failed") from exc


def _verify_evidence_directories(
    held: list[tuple[int, int, str, os.stat_result]], final_parent: int
) -> None:
    seen: set[int] = set()
    try:
        for parent, child, name, parent_before in reversed(held):
            parent_after = os.fstat(parent)
            if _directory_changed(parent_before, parent_after):
                raise ValidationError(
                    f"mutable evidence parent changed during read: {name}"
                )
            reopened = os.open(name, _directory_open_flags(), dir_fd=parent)
            try:
                if not _same_stat_inode(os.fstat(child), os.fstat(reopened)):
                    raise ValidationError(
                        f"mutable evidence directory was replaced: {name}"
                    )
            finally:
                os.close(reopened)
    finally:
        for parent, child, _, _ in reversed(held):
            for fd in (child, parent):
                if fd not in seen:
                    seen.add(fd)
                    try:
                        os.close(fd)
                    except OSError:
                        pass
        if final_parent not in seen:
            try:
                os.close(final_parent)
            except OSError:
                pass


def _read_output_file(
    lease: _ExecutionProjectionLease, output_root: str, relative: str
) -> tuple[bytes, os.stat_result]:
    _verify_output_anchor(lease, output_root)
    parent_fd, held = _open_evidence_parent(lease, output_root, relative)
    name = _relative_path_parts(relative)[-1]
    parent_before = os.fstat(parent_fd)
    try:
        entry_before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        fd = os.open(name, _file_open_flags(), dir_fd=parent_fd)
        try:
            opened_before = os.fstat(fd)
            if (
                not stat.S_ISREG(opened_before.st_mode)
                or opened_before.st_nlink != 1
                or not _same_stat_inode(entry_before, opened_before)
            ):
                raise ValidationError(
                    f"mutable evidence file is not single-link regular: {relative}"
                )
            payload = _read_all_fd(fd)
            opened_after = os.fstat(fd)
            if _file_changed(opened_before, opened_after):
                raise ValidationError(
                    f"mutable evidence file changed during read: {relative}"
                )
        finally:
            os.close(fd)
        reopened = os.open(name, _file_open_flags(), dir_fd=parent_fd)
        try:
            reopened_stat = os.fstat(reopened)
            if (
                not stat.S_ISREG(reopened_stat.st_mode)
                or reopened_stat.st_nlink != 1
                or not _same_stat_inode(opened_after, reopened_stat)
            ):
                raise ValidationError(f"mutable evidence file was replaced: {relative}")
        finally:
            os.close(reopened)
        if _directory_changed(parent_before, os.fstat(parent_fd)):
            raise ValidationError(
                f"mutable evidence parent changed during read: {relative}"
            )
        return payload, opened_after
    except OSError as exc:
        raise ValidationError(
            f"mutable evidence file is unreadable: {relative}"
        ) from exc
    finally:
        _verify_evidence_directories(held, parent_fd)
        _verify_output_anchor(lease, output_root)


def _hold_output_file(
    lease: _ExecutionProjectionLease, output_root: str, relative: str
) -> tuple[int, bytes, os.stat_result]:
    """Open one output by leased dir-fd and retain the exact regular-file inode."""

    _verify_output_anchor(lease, output_root)
    if "/" in relative:
        raise ValidationError("held output must be directly under its output root")
    root_fd = lease.output_fds[output_root]
    root_before = os.fstat(root_fd)
    try:
        entry = os.stat(relative, dir_fd=root_fd, follow_symlinks=False)
        fd = os.open(relative, _file_open_flags(), dir_fd=root_fd)
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not _same_stat_inode(entry, opened)
        ):
            raise ValidationError("held output is not a single-link regular file")
        payload = _read_all_fd(fd)
        if _file_changed(opened, os.fstat(fd)):
            raise ValidationError("held output changed during initial read")
        reopened = os.open(relative, _file_open_flags(), dir_fd=root_fd)
        try:
            if not _same_stat_inode(opened, os.fstat(reopened)):
                raise ValidationError("held output was replaced while opening")
        finally:
            os.close(reopened)
        if _directory_changed(root_before, os.fstat(root_fd)):
            raise ValidationError("held output root changed while opening")
        return fd, payload, opened
    except BaseException:
        if "fd" in locals():
            os.close(fd)
        raise


def _load_output_json(
    lease: _ExecutionProjectionLease, output_root: str, relative: str
) -> tuple[Any, str]:
    payload, _ = _read_output_file(lease, output_root, relative)
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError(
            f"execution artifact is not valid JSON: {relative}"
        ) from exc
    return value, hashlib.sha256(payload).hexdigest()


def _snapshot_output_tree(
    lease: _ExecutionProjectionLease, output_root: str
) -> dict[str, dict[str, Any]]:
    _verify_output_anchor(lease, output_root)
    root_fd = os.dup(lease.output_fds[output_root])
    opened_dirs: list[tuple[int, int, str, os.stat_result, tuple[str, ...]]] = []
    snapshot: dict[str, dict[str, Any]] = {}

    def walk(directory_fd: int, prefix: tuple[str, ...]) -> None:
        directory_before = os.fstat(directory_fd)
        names = tuple(sorted(os.listdir(directory_fd)))
        for name in names:
            if name in {"", ".", ".."} or "/" in name or "\x00" in name:
                raise ValidationError("mutable output contains invalid entry name")
            relative_parts = (*prefix, name)
            relative = "/".join(relative_parts)
            entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(entry.st_mode):
                raise ValidationError(f"mutable output contains symlink: {relative}")
            if stat.S_ISDIR(entry.st_mode):
                if name == "__pycache__":
                    raise ValidationError("mutable output contains __pycache__")
                child = os.open(name, _directory_open_flags(), dir_fd=directory_fd)
                child_stat = os.fstat(child)
                if not _same_stat_inode(entry, child_stat):
                    os.close(child)
                    raise ValidationError(
                        f"mutable output directory changed while opening: {relative}"
                    )
                opened_dirs.append((directory_fd, child, name, directory_before, names))
                walk(child, relative_parts)
                continue
            if name.endswith(".pyc"):
                raise ValidationError("mutable output contains .pyc")
            if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
                raise ValidationError(
                    f"mutable output file must be single-link regular: {relative}"
                )
            payload, observed = _read_output_file(lease, output_root, relative)
            snapshot[relative] = {
                "mode": f"{stat.S_IMODE(observed.st_mode):04o}",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        if names != tuple(sorted(os.listdir(directory_fd))) or _directory_changed(
            directory_before, os.fstat(directory_fd)
        ):
            raise ValidationError("mutable output directory changed during snapshot")

    try:
        walk(root_fd, ())
        for parent, child, name, parent_before, names_before in reversed(opened_dirs):
            if names_before != tuple(sorted(os.listdir(parent))) or _directory_changed(
                parent_before, os.fstat(parent)
            ):
                raise ValidationError(
                    f"mutable output parent changed during snapshot: {name}"
                )
            reopened = os.open(name, _directory_open_flags(), dir_fd=parent)
            try:
                if not _same_stat_inode(os.fstat(child), os.fstat(reopened)):
                    raise ValidationError(
                        f"mutable output directory was replaced: {name}"
                    )
            finally:
                os.close(reopened)
    except OSError as exc:
        raise ValidationError("mutable output snapshot traversal failed") from exc
    finally:
        closed: set[int] = set()
        for parent, child, _, _, _ in reversed(opened_dirs):
            for fd in (child, parent):
                if fd not in closed:
                    closed.add(fd)
                    try:
                        os.close(fd)
                    except OSError:
                        pass
        if root_fd not in closed:
            os.close(root_fd)
        _verify_output_anchor(lease, output_root)
    return dict(sorted(snapshot.items()))


def _output_entry_exists(
    lease: _ExecutionProjectionLease, output_root: str, relative: str
) -> bool:
    _verify_output_anchor(lease, output_root)
    parent_fd, held = _open_evidence_parent(lease, output_root, relative)
    name = _relative_path_parts(relative)[-1]
    parent_before = os.fstat(parent_fd)
    try:
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            exists = False
        else:
            exists = True
        if _directory_changed(parent_before, os.fstat(parent_fd)):
            raise ValidationError(
                "mutable evidence parent changed during existence check"
            )
        return exists
    finally:
        _verify_evidence_directories(held, parent_fd)
        _verify_output_anchor(lease, output_root)


def execute_staged_skillopt_mock_diagnostic(
    *,
    staged_root: str | Path,
    execution_root: str | Path,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the exact staged mock train/eval pair under a sealed diagnostic lease."""

    staged = Path(staged_root)
    execution = Path(execution_root)
    _require_absent(execution, "execution destination")
    _require_disjoint_execution_destination(execution, staged)
    original_profile = copy.deepcopy(dict(profile))
    validated = validate_compatibility_profile(profile)
    _require_phase(validated, overlay=True, staging=True)
    if validated != original_profile:
        raise ValidationError("compatibility profile is not canonical")
    _reject_preloaded_protected_modules()

    temporary: Path | None = None
    with acquire_diagnostic_staging_tree_lease(staged, validated) as staging_lease:
        temporary = _sibling_temporary_directory(execution)
        try:
            immutable_files = []
            for entry in validated["staging_manifest"]["staged_tree"]:
                payload = staging_lease.read_bytes(entry["path"])
                _write_regular_file(
                    temporary,
                    entry["path"],
                    payload,
                    mode=int(entry["mode"], 8),
                )
                immutable_files.append(dict(entry))
            for relative in (TRAIN_OUT_ROOT, EVAL_OUT_ROOT):
                (temporary / relative).mkdir(parents=True, exist_ok=False)
            temporary.chmod(0o755)
            for path in sorted(
                (item for item in temporary.rglob("*") if item.is_dir()),
                key=lambda item: len(item.parts),
            ):
                path.chmod(0o755)
            immutable_directories = _immutable_directory_entries(temporary)
            projection = seal_identity_artifact(
                {
                    "version": EXECUTION_PROJECTION_VERSION,
                    "staging_identity": validated["staging_manifest"]["identity"],
                    "staged_tree_identity": validated["staging_manifest"][
                        "staged_tree_identity"
                    ],
                    "immutable_files": immutable_files,
                    "immutable_directories": immutable_directories,
                    "mutable_roots": [TRAIN_OUT_ROOT, EVAL_OUT_ROOT],
                },
                EXECUTION_PROJECTION_VERSION,
            )
            with _ExecutionProjectionLease(temporary, projection):
                pass
            staging_lease.verify_live()
            _publish_absent(temporary, execution)
            temporary = None
        except BaseException:
            _remove_temporary(temporary)
            raise

        with _ExecutionProjectionLease(execution, projection) as execution_lease:
            staging_lease.verify_live()
            report = _run_projection(
                execution=execution,
                projection=projection,
                profile=validated,
                lease=execution_lease,
            )
            execution_lease.verify_live()
            staging_lease.verify_live()
    if dict(profile) != original_profile:
        raise ValidationError(
            "compatibility profile mutated during diagnostic execution"
        )
    return report


def _run_projection(
    *,
    execution: Path,
    projection: Mapping[str, Any],
    profile: Mapping[str, Any],
    lease: _ExecutionProjectionLease,
) -> dict[str, Any]:
    candidate_relative = CANDIDATE_PATH.removeprefix(f"{TRAIN_OUT_ROOT}/")
    if _output_entry_exists(lease, TRAIN_OUT_ROOT, candidate_relative):
        raise ValidationError("candidate must be absent before training")
    sentinel = _ExecutionSentinel(execution)
    callables_before: dict[str, dict[str, str]] = {}
    callables_after: dict[str, dict[str, str]] = {}
    imported_modules: dict[str, dict[str, str]] = {}
    report: dict[str, Any] | None = None
    cwd_fd = os.open(".", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    saved_argv_object = sys.argv
    saved_argv = list(sys.argv)
    saved_path_object = sys.path
    saved_path = list(sys.path)
    saved_modules = dict(sys.modules)
    saved_dont_write = sys.dont_write_bytecode
    trace_present = "REFLACT_CODEX_TRACE_TO_OPTIMIZER" in os.environ
    saved_trace = os.environ.get("REFLACT_CODEX_TRACE_TO_OPTIMIZER")
    try:
        protected_finder = _build_protected_finder(execution, lease)
        with _restricted_execution_boundary(sentinel, protected_finder):
            try:
                os.chdir(execution)
                sys.argv = list(TRAIN_ARGV[1:])
                sys.path = [str(execution), *saved_path]
                sys.dont_write_bytecode = True
                os.environ["REFLACT_CODEX_TRACE_TO_OPTIMIZER"] = "0"

                _detach_preloaded_repo_scripts_modules(saved_modules)
                callable_values = _preload_exact_source_closure(execution)
                sentinel.bind_exact_codes(callable_values)
                train_module = sys.modules["scripts.train"]
                _require_exact_module(train_module, execution, "scripts/train.py")
                imported_modules = _validate_loaded_source_modules(execution, profile)
                callables_before = _bind_required_callables(execution, train=None)
                sentinel.phase = "train"
                train_module.main()
                lease.verify_live()
                candidate_fd, candidate_payload, _ = _hold_output_file(
                    lease, TRAIN_OUT_ROOT, candidate_relative
                )
                sentinel.hold_candidate(candidate_fd, candidate_payload)
                candidate_evidence = _validate_candidate_lineage(lease, sentinel)
                train_snapshot = _snapshot_output_tree(lease, TRAIN_OUT_ROOT)
                train_evidence = _validate_train_outputs(lease, train_snapshot)

                sys.argv = list(EVAL_ARGV[1:])
                eval_module = sys.modules["scripts.eval_only"]
                _require_exact_module(eval_module, execution, "scripts/eval_only.py")
                imported_modules = _validate_loaded_source_modules(execution, profile)
                sentinel.phase = "eval"
                eval_module.main()
                lease.verify_live()
                if _snapshot_output_tree(lease, TRAIN_OUT_ROOT) != train_snapshot:
                    raise ValidationError(
                        "eval mutated the sealed train output snapshot"
                    )
                eval_evidence = _validate_eval_outputs(
                    execution, lease, candidate_evidence, sentinel
                )
                imported_modules = _validate_loaded_source_modules(execution, profile)
                callables_after = _bind_required_callables(execution, train=None)
                _validate_adapter_registries()
                values_after = _required_callable_values()
                if set(values_after) != set(callable_values) or any(
                    values_after[label] is not callable_values[label]
                    for label in callable_values
                ):
                    raise ValidationError(
                        "upstream callable object identities changed during run"
                    )
                if callables_after != callables_before:
                    raise ValidationError(
                        "upstream callable bindings changed during run"
                    )
                report = _build_execution_report(
                    projection=projection,
                    profile=profile,
                    sentinel=sentinel,
                    imported_modules=imported_modules,
                    callables=callables_after,
                    candidate_evidence=candidate_evidence,
                    train_snapshot=train_snapshot,
                    train_evidence=train_evidence,
                    eval_evidence=eval_evidence,
                )
                _validate_execution_report(
                    report,
                    profile,
                    lease=lease,
                    sentinel=sentinel,
                )
            finally:
                sentinel.close_candidate()
                _restore_module_snapshot(saved_modules)
                sys.dont_write_bytecode = saved_dont_write
                if trace_present:
                    assert saved_trace is not None
                    os.environ["REFLACT_CODEX_TRACE_TO_OPTIMIZER"] = saved_trace
                else:
                    os.environ.pop("REFLACT_CODEX_TRACE_TO_OPTIMIZER", None)
                sys.argv = saved_argv_object
                saved_argv_object[:] = saved_argv
                sys.path = saved_path_object
                saved_path_object[:] = saved_path
                os.fchdir(cwd_fd)
    except _ExecutionDenied as exc:
        raise ValidationError("forbidden action attempted by diagnostic run") from exc
    finally:
        os.close(cwd_fd)
    if report is None:
        raise ValidationError("diagnostic report was not produced")
    return report


def _build_execution_report(
    *,
    projection: Mapping[str, Any],
    profile: Mapping[str, Any],
    sentinel: _ExecutionSentinel,
    imported_modules: Mapping[str, Any],
    callables: Mapping[str, Any],
    candidate_evidence: Mapping[str, Any],
    train_snapshot: Mapping[str, Any],
    train_evidence: Mapping[str, Any],
    eval_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_call_observations(sentinel.calls)
    if sentinel.counts() != {kind: 0 for kind in _EXECUTION_KINDS}:
        raise ValidationError("diagnostic run attempted a forbidden boundary")
    execution_config = profile["staging_manifest"]["execution_config"]
    bindings = {
        "projection_identity": projection["identity"],
        "staging_identity": profile["staging_manifest"]["identity"],
        "profile_identity": profile["identity"],
        "train_argv_identity": execution_config["train_argv_identity"],
        "eval_argv_identity": execution_config["eval_argv_identity"],
        "config_sha256": hashlib.sha256(CANONICAL_RENDERED_CONFIG_BYTES).hexdigest(),
        "runtime_config_sha256": train_snapshot["config.json"]["sha256"],
        "import_bindings_sha256": _binding_hash("imports", imported_modules),
        "call_bindings_sha256": _binding_hash("callables", callables),
        "call_observations_sha256": _binding_hash("calls", sentinel.calls),
        "candidate_sha256": candidate_evidence["sha256"],
        "eval_candidate_read_sha256": sentinel.eval_candidate_read_sha256,
        "eval_summary_sha256": eval_evidence["summary_sha256"],
        "runtime_config_identity": train_evidence["runtime_config_identity"],
    }
    payload = {
        "version": DIAGNOSTIC_REPORT_VERSION,
        "profile_id": PROFILE_ID,
        "status": "passed",
        "evidence_class": "diagnostic",
        "authorization_status": "not_authorized",
        "authenticity_status": "unverified",
        "seal_kind": "self_asserted_integrity",
        "trusted": False,
        "tested_patch": None,
        "containment": {
            "scope": "diagnostic_in_process",
            "single_threaded": True,
            "os_sandbox": False,
            "authorization": False,
        },
        "execution_counts": {
            **sentinel.counts(),
            "train": sentinel.calls["scripts.train.main"],
            "eval": sentinel.calls["scripts.eval_only.main"],
        },
        "projection": copy.deepcopy(dict(projection)),
        "bindings": bindings,
        "imports": dict(imported_modules),
        "call_bindings": dict(callables),
        "calls": dict(sorted(sentinel.calls.items())),
        "candidate": candidate_evidence,
        "train": train_evidence,
        "eval": eval_evidence,
    }
    return seal_identity_artifact(payload, DIAGNOSTIC_REPORT_VERSION)


def _validate_execution_report(
    report: Mapping[str, Any],
    profile: Mapping[str, Any],
    *,
    lease: _ExecutionProjectionLease | None = None,
    sentinel: _ExecutionSentinel | None = None,
) -> dict[str, Any]:
    """Validate structure, then require live FDs for any passed report."""
    expected_keys = {
        "version",
        "profile_id",
        "status",
        "evidence_class",
        "authorization_status",
        "authenticity_status",
        "seal_kind",
        "trusted",
        "tested_patch",
        "containment",
        "execution_counts",
        "projection",
        "bindings",
        "imports",
        "call_bindings",
        "calls",
        "candidate",
        "train",
        "eval",
        "identity",
    }
    if not isinstance(report, Mapping) or set(report) != expected_keys:
        raise ValidationError("execution diagnostic report has invalid keys")
    if seal_identity_artifact(report, DIAGNOSTIC_REPORT_VERSION) != dict(report):
        raise ValidationError("execution diagnostic report identity mismatch")
    fixed = {
        "version": DIAGNOSTIC_REPORT_VERSION,
        "profile_id": PROFILE_ID,
        "status": "passed",
        "evidence_class": "diagnostic",
        "authorization_status": "not_authorized",
        "authenticity_status": "unverified",
        "seal_kind": "self_asserted_integrity",
        "trusted": False,
        "tested_patch": None,
        "containment": {
            "scope": "diagnostic_in_process",
            "single_threaded": True,
            "os_sandbox": False,
            "authorization": False,
        },
        "execution_counts": {
            "provider": 0,
            "network": 0,
            "subprocess": 0,
            "train": 1,
            "eval": 1,
        },
    }
    for key, expected in fixed.items():
        if report.get(key) != expected:
            raise ValidationError(f"execution diagnostic {key} is invalid")
    projection = report["projection"]
    staging = profile["staging_manifest"]
    staged_tree = staging["staged_tree"]
    expected_directories = {"outputs"}
    for entry in staged_tree:
        parts = entry["path"].split("/")[:-1]
        expected_directories.update(
            "/".join(parts[:index]) for index in range(1, len(parts) + 1)
        )
    expected_directory_entries = [
        {"path": path, "mode": "0755"} for path in sorted(expected_directories)
    ]
    projection_keys = {
        "version",
        "staging_identity",
        "staged_tree_identity",
        "immutable_files",
        "immutable_directories",
        "mutable_roots",
        "identity",
    }
    if (
        not isinstance(projection, Mapping)
        or set(projection) != projection_keys
        or projection.get("version") != EXECUTION_PROJECTION_VERSION
        or projection.get("staging_identity") != staging["identity"]
        or projection.get("staged_tree_identity") != staging["staged_tree_identity"]
        or projection.get("immutable_files") != staged_tree
        or projection.get("immutable_directories") != expected_directory_entries
        or projection.get("mutable_roots") != [TRAIN_OUT_ROOT, EVAL_OUT_ROOT]
        or seal_identity_artifact(projection, EXECUTION_PROJECTION_VERSION)
        != dict(projection)
    ):
        raise ValidationError("execution diagnostic projection is invalid")

    manifest = {entry["path"]: entry for entry in staged_tree}
    imports = report["imports"]
    if not isinstance(imports, Mapping) or not imports:
        raise ValidationError("execution diagnostic imports are invalid")
    for module_name, entry in imports.items():
        if (
            not isinstance(module_name, str)
            or not any(
                module_name == prefix or module_name.startswith(f"{prefix}.")
                for prefix in _PROTECTED_PREFIXES
            )
            or not isinstance(entry, Mapping)
            or set(entry) != {"path", "sha256"}
        ):
            raise ValidationError("execution diagnostic import entry is invalid")
        module_path = module_name.replace(".", "/")
        path = entry["path"]
        if entry["sha256"] == "namespace":
            if path != module_path or not any(
                candidate.startswith(f"{path}/") for candidate in manifest
            ):
                raise ValidationError(
                    "execution diagnostic namespace import is invalid"
                )
            continue
        if path not in {f"{module_path}.py", f"{module_path}/__init__.py"}:
            raise ValidationError("execution diagnostic import path is inconsistent")
        if path not in manifest or entry["sha256"] != manifest[path]["sha256"]:
            raise ValidationError("execution diagnostic import hash is inconsistent")
    for module_name, path in REQUIRED_IMPORTED_MODULES.items():
        if imports.get(module_name) != {
            "path": path,
            "sha256": manifest[path]["sha256"],
        }:
            raise ValidationError("execution diagnostic required import is absent")

    call_bindings = report["call_bindings"]
    if not isinstance(call_bindings, Mapping) or set(call_bindings) != set(
        _CALL_BINDING_PATHS
    ):
        raise ValidationError("execution diagnostic callable bindings are invalid")
    for label, path in _CALL_BINDING_PATHS.items():
        entry = call_bindings[label]
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"path", "source_sha256", "code_sha256"}
            or entry["path"] != path
            or entry["source_sha256"] != manifest[path]["sha256"]
            or not _is_sha256(entry["code_sha256"])
        ):
            raise ValidationError(
                f"execution diagnostic callable binding is invalid: {label}"
            )

    calls = report["calls"]
    _validate_call_observations(calls)

    candidate = report["candidate"]
    candidate_keys = {
        "path",
        "sha256",
        "size_bytes",
        "marker",
        "marker_count",
        "writer",
        "writer_observed",
        "writer_open_count",
        "writer_open_path",
        "writer_open_mode",
    }
    if (
        not isinstance(candidate, Mapping)
        or set(candidate) != candidate_keys
        or candidate.get("path") != profile["outputs"]["candidate_path"]
        or not _is_sha256(candidate.get("sha256"))
        or type(candidate.get("size_bytes")) is not int
        or candidate["size_bytes"] <= 0
        or candidate.get("marker") != ADAPTER_MARKER
        or candidate.get("marker_count") != 1
        or candidate.get("writer") != "skillopt.engine.trainer.ReflACTTrainer.train"
        or candidate.get("writer_observed") is not True
        or type(candidate.get("writer_open_count")) is not int
        or candidate["writer_open_count"] < 1
        or candidate.get("writer_open_path") != CANDIDATE_PATH
        or candidate.get("writer_open_mode") != "w"
        or calls["ReflACTTrainer.train"] != 1
    ):
        raise ValidationError("execution diagnostic candidate lineage is invalid")

    train = report["train"]
    train_keys = {
        "snapshot",
        "snapshot_identity",
        "artifact_count",
        "required_artifacts",
        "update_operation",
        "gate_metric",
        "gate_action",
        "runtime_config",
        "runtime_config_identity",
    }
    snapshot = train.get("snapshot") if isinstance(train, Mapping) else None
    if not isinstance(snapshot, Mapping):
        raise ValidationError("execution diagnostic train snapshot is invalid")
    for path, entry in snapshot.items():
        if (
            not isinstance(path, str)
            or not isinstance(entry, Mapping)
            or set(entry) != {"mode", "size_bytes", "sha256"}
            or entry["mode"] not in {"0600", "0644"}
            or type(entry["size_bytes"]) is not int
            or entry["size_bytes"] < 0
            or not _is_sha256(entry["sha256"])
        ):
            raise ValidationError("execution diagnostic train artifact is invalid")
    candidate_relative = CANDIDATE_PATH.removeprefix(f"{TRAIN_OUT_ROOT}/")
    if (
        set(train) != train_keys
        or set(snapshot) != _EXPECTED_TRAIN_ARTIFACTS
        or train.get("snapshot_identity") != _binding_hash("train_outputs", snapshot)
        or train.get("artifact_count") != len(snapshot)
        or train.get("required_artifacts") != sorted(_EXPECTED_TRAIN_ARTIFACTS)
        or train.get("update_operation") != "append"
        or train.get("gate_metric") != staging["execution_config"]["gate_metric"]
        or train.get("gate_action") != "accept_new_best"
        or train.get("runtime_config")
        != {
            **{
                runtime_key: CANONICAL_EXECUTION_KNOBS[knob]
                for knob, runtime_key in _RUNTIME_CONFIG_KNOB_MAP.items()
            },
            **_DERIVED_RUNTIME_CONFIG,
        }
        or train.get("runtime_config_identity")
        != _binding_hash("runtime_config", train.get("runtime_config"))
        or snapshot[candidate_relative]["sha256"] != candidate["sha256"]
        or snapshot[candidate_relative]["size_bytes"] != candidate["size_bytes"]
    ):
        raise ValidationError("execution diagnostic train lineage is invalid")

    eval_evidence = report["eval"]
    eval_keys = {
        "summary_path",
        "summary_sha256",
        "candidate_sha256_read",
        "candidate_read_count",
        "input_ids",
        "split_observations",
        "split",
        "n_items",
        "hard",
        "soft",
        "ids",
    }
    if (
        not isinstance(eval_evidence, Mapping)
        or set(eval_evidence) != eval_keys
        or eval_evidence.get("summary_path") != f"{EVAL_OUT_ROOT}/eval_summary.json"
        or not _is_sha256(eval_evidence.get("summary_sha256"))
        or eval_evidence.get("candidate_sha256_read") != candidate["sha256"]
        or eval_evidence.get("candidate_read_count") != 1
        or eval_evidence.get("input_ids") != list(_EXPECTED_EVAL_IDS)
        or eval_evidence.get("split") != "all"
        or eval_evidence.get("n_items") != len(_EXPECTED_EVAL_IDS)
        or eval_evidence.get("hard") != 1.0
        or eval_evidence.get("soft") != 1.0
        or eval_evidence.get("ids") != list(_EXPECTED_EVAL_IDS)
        or len(set(eval_evidence["ids"])) != len(_EXPECTED_EVAL_IDS)
    ):
        raise ValidationError("execution diagnostic eval lineage is invalid")

    bindings = report["bindings"]
    binding_keys = {
        "projection_identity",
        "staging_identity",
        "profile_identity",
        "train_argv_identity",
        "eval_argv_identity",
        "config_sha256",
        "runtime_config_sha256",
        "import_bindings_sha256",
        "call_bindings_sha256",
        "call_observations_sha256",
        "candidate_sha256",
        "eval_candidate_read_sha256",
        "eval_summary_sha256",
        "runtime_config_identity",
    }
    execution_config = staging["execution_config"]
    expected_bindings = {
        "projection_identity": projection["identity"],
        "staging_identity": staging["identity"],
        "profile_identity": profile["identity"],
        "train_argv_identity": execution_config["train_argv_identity"],
        "eval_argv_identity": execution_config["eval_argv_identity"],
        "config_sha256": execution_config["rendered_config_sha256"],
        "runtime_config_sha256": snapshot["config.json"]["sha256"],
        "import_bindings_sha256": _binding_hash("imports", imports),
        "call_bindings_sha256": _binding_hash("callables", call_bindings),
        "call_observations_sha256": _binding_hash("calls", calls),
        "candidate_sha256": candidate["sha256"],
        "eval_candidate_read_sha256": eval_evidence["candidate_sha256_read"],
        "eval_summary_sha256": eval_evidence["summary_sha256"],
        "runtime_config_identity": train["runtime_config_identity"],
    }
    if (
        not isinstance(bindings, Mapping)
        or set(bindings) != binding_keys
        or dict(bindings) != expected_bindings
    ):
        raise ValidationError("execution diagnostic bindings are invalid")
    structured = json.loads(_canonical_json_bytes(report))
    if lease is None or sentinel is None:
        raise ValidationError("passed report requires live artifact evidence")
    _validate_live_execution_report(structured, profile, lease, sentinel)
    return structured


def _validate_live_execution_report(
    report: Mapping[str, Any],
    profile: Mapping[str, Any],
    lease: _ExecutionProjectionLease,
    sentinel: _ExecutionSentinel,
) -> None:
    """Recompute final evidence while projection and candidate FDs remain live."""

    lease.verify_live()
    candidate_relative = CANDIDATE_PATH.removeprefix(f"{TRAIN_OUT_ROOT}/")
    candidate_payload, candidate_stat = _read_output_file(
        lease, TRAIN_OUT_ROOT, candidate_relative
    )
    held_stat = os.fstat(sentinel.candidate_fd)
    if (
        candidate_payload != sentinel.candidate_payload
        or not _same_stat_inode(candidate_stat, held_stat)
        or hashlib.sha256(candidate_payload).hexdigest()
        != report["candidate"]["sha256"]
    ):
        raise ValidationError("live candidate evidence does not match report")
    if (
        report["candidate"]["writer_open_count"] != sentinel.writer_open_count
        or report["candidate"]["writer_open_path"] != sentinel.writer_open_path
        or report["candidate"]["writer_open_mode"] != sentinel.writer_open_mode
    ):
        raise ValidationError("live candidate writer evidence does not match report")
    train_snapshot = _snapshot_output_tree(lease, TRAIN_OUT_ROOT)
    train_evidence = _validate_train_outputs(lease, train_snapshot)
    if train_evidence != report["train"]:
        raise ValidationError("live train evidence does not match report")
    eval_evidence = _validate_eval_outputs(
        lease.root, lease, report["candidate"], sentinel
    )
    if eval_evidence != report["eval"]:
        raise ValidationError("live eval evidence does not match report")
    if (
        report["bindings"]["runtime_config_identity"]
        != train_evidence["runtime_config_identity"]
    ):
        raise ValidationError("live runtime config binding does not match report")
    if report["bindings"]["eval_candidate_read_sha256"] != (
        sentinel.eval_candidate_read_sha256
    ):
        raise ValidationError("live eval candidate binding does not match report")
    if report["profile_id"] != profile["profile_id"]:
        raise ValidationError("live report profile does not match execution profile")


def _validate_candidate_lineage(
    lease: _ExecutionProjectionLease, sentinel: _ExecutionSentinel
) -> dict[str, Any]:
    payload = sentinel.candidate_payload
    candidate_stat = os.fstat(sentinel.candidate_fd)
    if not stat.S_ISREG(candidate_stat.st_mode) or candidate_stat.st_nlink != 1:
        raise ValidationError("candidate must be a single-link regular file")
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("candidate is not UTF-8") from exc
    if content.count(ADAPTER_MARKER) != 1:
        raise ValidationError("candidate must contain the compatibility marker once")
    if sentinel.calls.get("ReflACTTrainer.train") != 1:
        raise ValidationError("candidate was not created by observed upstream training")
    if (
        sentinel.writer_open_count < 1
        or sentinel.writer_open_path != CANDIDATE_PATH
        or sentinel.writer_open_mode != "w"
    ):
        raise ValidationError("canonical candidate writer open was not observed")
    current, current_stat = _read_output_file(
        lease,
        TRAIN_OUT_ROOT,
        CANDIDATE_PATH.removeprefix(f"{TRAIN_OUT_ROOT}/"),
    )
    if current != payload or not _same_stat_inode(candidate_stat, current_stat):
        raise ValidationError("candidate path does not bind the held trainer bytes")
    return {
        "path": CANDIDATE_PATH,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "marker": ADAPTER_MARKER,
        "marker_count": 1,
        "writer": "skillopt.engine.trainer.ReflACTTrainer.train",
        "writer_observed": True,
        "writer_open_count": sentinel.writer_open_count,
        "writer_open_path": sentinel.writer_open_path,
        "writer_open_mode": sentinel.writer_open_mode,
    }


def _validate_train_outputs(
    lease: _ExecutionProjectionLease,
    snapshot: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    paths = set(snapshot)
    if paths != _EXPECTED_TRAIN_ARTIFACTS:
        raise ValidationError("training artifacts are not exactly canonical")
    history, _ = _load_output_json(lease, TRAIN_OUT_ROOT, "history.json")
    runtime_config, _ = _load_output_json(lease, TRAIN_OUT_ROOT, "config.json")
    if not isinstance(runtime_config, Mapping) or not runtime_config:
        raise ValidationError("training runtime config is not canonical")
    relevant_runtime_config = {
        runtime_key: runtime_config.get(runtime_key)
        for _, runtime_key in _RUNTIME_CONFIG_KNOB_MAP.items()
    }
    relevant_runtime_config.update(
        {key: runtime_config.get(key) for key in _DERIVED_RUNTIME_CONFIG}
    )
    expected_runtime_config = {
        runtime_key: CANONICAL_EXECUTION_KNOBS[knob]
        for knob, runtime_key in _RUNTIME_CONFIG_KNOB_MAP.items()
    }
    expected_runtime_config.update(_DERIVED_RUNTIME_CONFIG)
    if relevant_runtime_config != expected_runtime_config:
        raise ValidationError(
            "training runtime config drifted from the canonical recipe"
        )
    if not isinstance(history, list) or len(history) != 1:
        raise ValidationError("training history is not the canonical one-step run")
    step = history[0]
    if (
        not isinstance(step, Mapping)
        or step.get("action") != "accept_new_best"
        or step.get("gate_metric") != "mixed"
    ):
        raise ValidationError(
            "training did not use the canonical mixed acceptance gate"
        )
    apply_report, _ = _load_output_json(
        lease, TRAIN_OUT_ROOT, "steps/step_0001/edit_apply_report.json"
    )
    if (
        not isinstance(apply_report, list)
        or len(apply_report) != 1
        or apply_report[0].get("op") != "append"
        or apply_report[0].get("status") != "applied_append"
    ):
        raise ValidationError("training did not apply the canonical append edit")
    return {
        "snapshot": json.loads(_canonical_json_bytes(snapshot)),
        "snapshot_identity": _binding_hash("train_outputs", snapshot),
        "artifact_count": len(snapshot),
        "required_artifacts": sorted(_EXPECTED_TRAIN_ARTIFACTS),
        "update_operation": "append",
        "gate_metric": "mixed",
        "gate_action": "accept_new_best",
        "runtime_config": relevant_runtime_config,
        "runtime_config_identity": _binding_hash(
            "runtime_config", relevant_runtime_config
        ),
    }


def _validate_eval_outputs(
    execution: Path,
    lease: _ExecutionProjectionLease,
    candidate: Mapping[str, Any],
    sentinel: _ExecutionSentinel,
) -> dict[str, Any]:
    if (
        sentinel.eval_input_ids != list(_EXPECTED_EVAL_IDS)
        or sentinel.eval_result_ids != sentinel.eval_input_ids
        or len(set(sentinel.eval_result_ids)) != 7
    ):
        raise ValidationError("eval did not observe the exact seven ordered item IDs")
    expected_splits = [
        {
            "logical_split": logical,
            "env_num": 0,
            "seed": 42,
            "ids": [
                item_id
                for item_id in _EXPECTED_EVAL_IDS
                if item_id.startswith(
                    {"train": "train-", "valid_seen": "val-", "valid_unseen": "test-"}[
                        logical
                    ]
                )
            ],
            "physical_splits": [physical],
        }
        for logical, physical in _CANONICAL_SPLIT_MAPPING.items()
    ]
    if sentinel.split_observations != expected_splits:
        raise ValidationError("eval split mapping observation is not canonical")
    if (
        sentinel.eval_candidate_read_count != 1
        or sentinel.eval_candidate_read_sha256 != candidate["sha256"]
    ):
        raise ValidationError("eval did not consume the exact held candidate once")
    if _output_entry_exists(lease, EVAL_OUT_ROOT, "best_skill.md"):
        raise ValidationError("eval must not write a best_skill candidate")
    summary, summary_sha256 = _load_output_json(
        lease, EVAL_OUT_ROOT, "eval_summary.json"
    )
    expected_skill = str(execution / CANDIDATE_PATH)
    try:
        summary_skill = summary["skill"]
    except (KeyError, TypeError) as exc:
        raise ValidationError("eval summary candidate path is invalid") from exc
    if (
        set(summary) != {"skill", "split", "n_items", "hard", "soft"}
        or summary.get("split") != "all"
        or summary.get("n_items") != 7
        or summary.get("hard") != 1.0
        or summary.get("soft") != 1.0
        or summary_skill != expected_skill
        or sentinel.candidate_sha256 != candidate["sha256"]
    ):
        raise ValidationError("eval summary is not canonical")
    return {
        "summary_path": f"{EVAL_OUT_ROOT}/eval_summary.json",
        "summary_sha256": summary_sha256,
        "candidate_sha256_read": candidate["sha256"],
        "candidate_read_count": sentinel.eval_candidate_read_count,
        "input_ids": list(sentinel.eval_input_ids),
        "split_observations": copy.deepcopy(sentinel.split_observations),
        "split": "all",
        "n_items": 7,
        "hard": 1.0,
        "soft": 1.0,
        "ids": list(sentinel.eval_result_ids),
    }


def materialize_skillopt_compatibility_overlay(
    *,
    output_dir: str | Path,
    profile_catalog_path: str | Path = DEFAULT_PROFILE_CATALOG_PATH,
) -> dict[str, Any]:
    """Atomically publish the exact ten-file diagnostic compatibility overlay."""

    output = Path(output_dir)
    _require_absent(output, "overlay destination")
    catalog = load_compatibility_catalog(profile_catalog_path)
    base_profile = catalog["profiles"][PROFILE_ID]
    _require_phase(base_profile, overlay=False, staging=False)

    logical_files = _canonical_logical_files()
    overlay_manifest = seal_identity_artifact(
        {
            "version": OVERLAY_MANIFEST_VERSION,
            "profile_id": PROFILE_ID,
            "contract_sha256": QUERY_ANALYZER_CONTRACT_SHA256,
            "schema_sha256": OVERLAY_SCHEMA_SHA256,
            "immutable_object_version": OVERLAY_IMMUTABLE_OBJECT_VERSION,
            "logical_files": sorted(
                logical_files, key=lambda entry: (entry["name"], entry["path"])
            ),
        },
        OVERLAY_MANIFEST_VERSION,
    )
    profile = _profile_with_artifact(
        base_profile, artifact="overlay_manifest", value=overlay_manifest
    )

    temporary = _sibling_temporary_directory(output)
    try:
        for path, payload in sorted(_OVERLAY_PAYLOADS.items()):
            _write_regular_file(temporary, path, payload, mode=0o644)
        _require_exact_tree(temporary, overlay_manifest["logical_files"])
        with acquire_diagnostic_overlay_tree_lease(temporary, profile):
            pass
        _publish_absent(temporary, output)
    except BaseException:
        _remove_temporary(temporary)
        raise
    with acquire_diagnostic_overlay_tree_lease(output, profile):
        pass
    return validate_compatibility_profile(profile)


def stage_skillopt_compatibility_overlay(
    *,
    source_root: str | Path,
    overlay_root: str | Path,
    staged_root: str | Path,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Atomically stage the approved source, seven projections, and two patches."""

    source = Path(source_root)
    overlay = Path(overlay_root)
    staged = Path(staged_root)
    _require_absent(staged, "staged destination")
    _require_disjoint_destination(staged, source, overlay)
    try:
        pristine_manifest = profile["pristine_source_manifest"]
    except (KeyError, TypeError) as exc:
        raise ValidationError("profile requires pristine_source_manifest") from exc

    temporary: Path | None = None
    with acquire_approved_source_tree_lease(source, pristine_manifest) as source_lease:
        _require_single_link_files(source, pristine_manifest["files"])
        with acquire_diagnostic_overlay_tree_lease(overlay, profile) as overlay_lease:
            validated = validate_compatibility_profile(profile)
            _require_phase(validated, overlay=True, staging=False)
            if (
                validated["overlay_manifest"]["logical_files"]
                != _canonical_logical_files()
            ):
                raise ValidationError("overlay logical files are not canonical")
            _require_single_link_files(
                overlay, validated["overlay_manifest"]["logical_files"]
            )
            temporary = _sibling_temporary_directory(staged)
            try:
                staged_entries: dict[str, dict[str, Any]] = {}
                for entry in validated["pristine_source_manifest"]["files"]:
                    path = entry["path"]
                    payload = source_lease.read_bytes(path)
                    if path in REGISTRY_PATCH_PATHS:
                        payload = apply_registry_patch(path, payload)
                    _write_regular_file(
                        temporary, path, payload, mode=int(entry["mode"], 8)
                    )
                    staged_entries[path] = _file_entry(path, payload, entry["mode"])

                for path in REQUIRED_PROJECTED_INPUT_PATHS:
                    if path in staged_entries:
                        raise ValidationError(
                            f"overlay projection already exists: {path}"
                        )
                    payload = overlay_lease.read_bytes(path)
                    _write_regular_file(temporary, path, payload, mode=0o644)
                    staged_entries[path] = _file_entry(path, payload, "0644")

                staged_profile = _build_staged_profile(validated, staged_entries)
                staging_manifest = staged_profile["staging_manifest"]
                _require_exact_tree(temporary, staging_manifest["staged_tree"])
                with acquire_diagnostic_staging_tree_lease(temporary, staged_profile):
                    pass
                source_lease.verify_live()
                overlay_lease.verify_live()
                _publish_absent(temporary, staged)
            except BaseException:
                _remove_temporary(temporary)
                raise

            with acquire_diagnostic_staging_tree_lease(staged, staged_profile):
                pass
            source_lease.verify_live()
            overlay_lease.verify_live()
            return validate_compatibility_profile(staged_profile)


def _build_staged_profile(
    profile: Mapping[str, Any], staged_by_path: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    if len(staged_by_path) != 318:
        raise ValidationError("staged tree must contain exactly 318 files")
    pristine_by_path = {
        entry["path"]: entry for entry in profile["pristine_source_manifest"]["files"]
    }
    overlay_by_path = {
        entry["path"]: entry
        for entry in profile["overlay_manifest"]["logical_files"]
        if entry["projection"] == "staged"
    }
    if set(overlay_by_path) != set(REQUIRED_PROJECTED_INPUT_PATHS):
        raise ValidationError("overlay staged projections are not canonical")

    allowlisted_diff = [
        {
            "path": path,
            "change": "add",
            "before_sha256": None,
            "after_sha256": staged_by_path[path]["sha256"],
            "mode": "0644",
        }
        for path in REQUIRED_PROJECTED_INPUT_PATHS
    ]
    allowlisted_diff.extend(
        {
            "path": path,
            "change": "modify",
            "before_sha256": pristine_by_path[path]["sha256"],
            "after_sha256": staged_by_path[path]["sha256"],
            "mode": staged_by_path[path]["mode"],
        }
        for path in REGISTRY_PATCH_PATHS
    )
    staged_tree = sorted(
        (dict(entry) for entry in staged_by_path.values()),
        key=lambda entry: entry["path"],
    )
    execution_config = {
        "relative_config_path": PROFILE_CONFIG_PATH,
        "relative_config_base": PROFILE_CONFIG_BASE,
        "loader_path": LOADER_PATH,
        "loader_sha256": CONFIG_SHA256,
        "rendered_config_sha256": staged_by_path[PROFILE_CONFIG_PATH]["sha256"],
        "compatibility_modes": ["hard", "mixed", "soft"],
        "train_out_root": TRAIN_OUT_ROOT,
        "eval_out_root": EVAL_OUT_ROOT,
        "candidate_path": CANDIDATE_PATH,
        "train_argv": list(TRAIN_ARGV),
        "train_argv_identity": domain_separated_hash(
            f"{STAGING_MANIFEST_VERSION}:train_argv", TRAIN_ARGV
        ),
        "eval_argv": list(EVAL_ARGV),
        "eval_argv_identity": domain_separated_hash(
            f"{STAGING_MANIFEST_VERSION}:eval_argv", EVAL_ARGV
        ),
        **CANONICAL_EXECUTION_KNOBS,
    }
    expected_modules = [
        {
            "module_path": module_path,
            "file_path": file_path,
            "sha256": staged_by_path[file_path]["sha256"],
        }
        for module_path, file_path in REQUIRED_IMPORTED_MODULES.items()
    ]
    staging_manifest = seal_identity_artifact(
        {
            "version": STAGING_MANIFEST_VERSION,
            "pristine_source_identity": profile["pristine_source_manifest"]["identity"],
            "overlay_identity": profile["overlay_manifest"]["identity"],
            "allowlisted_diff": sorted(
                allowlisted_diff, key=lambda entry: entry["path"]
            ),
            "staged_tree": staged_tree,
            "staged_tree_identity": manifest_tree_identity(staged_tree),
            "execution_config": execution_config,
            "execution_config_identity": domain_separated_hash(
                f"{STAGING_MANIFEST_VERSION}:execution_config", execution_config
            ),
            "train_registry_patch_sha256": staged_by_path["scripts/train.py"]["sha256"],
            "eval_registry_patch_sha256": staged_by_path["scripts/eval_only.py"][
                "sha256"
            ],
            "registry_patches": [
                {"path": path, **dict(REGISTRY_PATCH_CONTRACT["patches"][path])}
                for path in REGISTRY_PATCH_PATHS
            ],
            "expected_imported_modules": sorted(
                expected_modules,
                key=lambda entry: (entry["module_path"], entry["file_path"]),
            ),
        },
        STAGING_MANIFEST_VERSION,
    )
    return _profile_with_artifact(
        profile, artifact="staging_manifest", value=staging_manifest
    )


def _profile_with_artifact(
    profile: Mapping[str, Any], *, artifact: str, value: Mapping[str, Any]
) -> dict[str, Any]:
    updated = copy.deepcopy(dict(profile))
    updated[artifact] = copy.deepcopy(dict(value))
    resolved_code = artifact
    updated["evidence_ceiling"] = [
        copy.deepcopy(diagnostic)
        for diagnostic in EXPECTED_EVIDENCE_CEILING
        if diagnostic["code"] != resolved_code
        and any(
            current["code"] == diagnostic["code"]
            for current in profile["evidence_ceiling"]
        )
    ]
    return seal_identity_artifact(updated, PROFILE_CATALOG_VERSION)


def _require_phase(profile: Mapping[str, Any], *, overlay: bool, staging: bool) -> None:
    if (profile.get("overlay_manifest") is not None) is not overlay:
        raise ValidationError("profile overlay phase is not canonical")
    if (profile.get("staging_manifest") is not None) is not staging:
        raise ValidationError("profile staging phase is not canonical")
    if any(
        profile.get(field) is not None
        for field in (
            "runner_identity",
            "custody_evidence",
            "tested_patch",
            "full_dependency_lock",
        )
    ):
        raise ValidationError("profile contains evidence outside the diagnostic phase")
    expected = {
        "custody",
        "full_dependency_lock",
        "image_digest",
        "tested_patch",
    }
    if not overlay:
        expected.add("overlay_manifest")
    if not staging:
        expected.add("staging_manifest")
    observed = {diagnostic["code"] for diagnostic in profile["evidence_ceiling"]}
    if observed != expected:
        raise ValidationError("profile unresolved evidence is not canonical")


def _logical_entry(
    name: str, path: str, payload: bytes, projection: str
) -> dict[str, Any]:
    return {
        "name": name,
        **_file_entry(path, payload, "0644"),
        "projection": projection,
    }


def _canonical_logical_files() -> list[dict[str, Any]]:
    entries = [
        _logical_entry(
            name=f"projected_{path.replace('/', '_').replace('.', '_')}",
            path=path,
            payload=_OVERLAY_PAYLOADS[path],
            projection="staged",
        )
        for path in REQUIRED_PROJECTED_INPUT_PATHS
    ]
    entries.extend(
        (
            _logical_entry(
                QUERY_ANALYZER_CONTRACT_NAME,
                QUERY_ANALYZER_CONTRACT_PATH,
                QUERY_ANALYZER_CONTRACT_BYTES,
                "metadata",
            ),
            _logical_entry(
                OVERLAY_SCHEMA_NAME,
                OVERLAY_SCHEMA_PATH,
                OVERLAY_SCHEMA_BYTES,
                "metadata",
            ),
            _logical_entry(
                REGISTRY_PATCH_CONTRACT_NAME,
                REGISTRY_PATCH_CONTRACT_PATH,
                REGISTRY_PATCH_CONTRACT_BYTES,
                "metadata",
            ),
        )
    )
    return sorted(entries, key=lambda entry: (entry["name"], entry["path"]))


def _file_entry(path: str, payload: bytes, mode: str) -> dict[str, Any]:
    return {
        "path": path,
        "kind": "file",
        "mode": mode,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _write_regular_file(
    root: Path, relative: str, payload: bytes, *, mode: int
) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(payload)
    target.chmod(mode)


def _require_exact_tree(root: Path, entries: list[Mapping[str, Any]]) -> None:
    _require_single_link_files(root, entries)
    actual = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    expected = {entry["path"] for entry in entries}
    if actual != expected:
        raise ValidationError("tree paths do not exactly match the manifest")


def _require_single_link_files(root: Path, entries: list[Mapping[str, Any]]) -> None:
    for entry in entries:
        path = root / entry["path"]
        try:
            file_stat = path.lstat()
        except OSError as exc:
            raise ValidationError(
                f"manifest path is unreadable: {entry['path']}"
            ) from exc
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValidationError(f"manifest path is not regular: {entry['path']}")
        if file_stat.st_nlink != 1:
            raise ValidationError(
                f"manifest path must have one hard link: {entry['path']}"
            )


def _sibling_temporary_directory(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    return Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.tmp-", dir=str(destination.parent)
        )
    )


def _publish_absent(temporary: Path, destination: Path) -> None:
    _require_absent(destination, "destination")
    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(temporary)
    destination_bytes = os.fsencode(destination)
    try:
        if sys.platform == "darwin":
            rename = library.renamex_np
            rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
            result = rename(source_bytes, destination_bytes, 0x00000004)
        elif sys.platform.startswith("linux"):
            rename = library.renameat2
            rename.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            result = rename(-100, source_bytes, -100, destination_bytes, 0x00000001)
        else:
            raise AttributeError("exclusive rename is unsupported")
    except AttributeError as exc:
        raise ValidationError("atomic absent-only publish is unsupported") from exc
    if result != 0:
        error = ctypes.get_errno()
        raise ValidationError("atomic destination publish failed") from OSError(
            error, os.strerror(error), destination
        )


def _require_absent(path: Path, field: str) -> None:
    if os.path.lexists(path):
        raise ValidationError(f"{field} must be absent")


def _require_disjoint_destination(
    destination: Path, source: Path, overlay: Path
) -> None:
    destination_path = destination.resolve(strict=False)
    for field, root in (("source", source), ("overlay", overlay)):
        root_path = root.resolve(strict=False)
        if destination_path == root_path or root_path in destination_path.parents:
            raise ValidationError(f"staged destination must be outside {field} root")


def _remove_temporary(path: Path | None) -> None:
    if path is not None and os.path.lexists(path):
        shutil.rmtree(path)


def _require_disjoint_execution_destination(destination: Path, staged: Path) -> None:
    destination_path = destination.resolve(strict=False)
    staged_path = staged.resolve(strict=False)
    if (
        destination_path == staged_path
        or staged_path in destination_path.parents
        or destination_path in staged_path.parents
    ):
        raise ValidationError("execution destination and staged root must be disjoint")


def _immutable_directory_entries(root: Path) -> list[dict[str, str]]:
    mutable = {TRAIN_OUT_ROOT, EVAL_OUT_ROOT}
    entries = []
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in mutable or any(
            relative.startswith(f"{item}/") for item in mutable
        ):
            continue
        entries.append(
            {
                "path": relative,
                "mode": f"{stat.S_IMODE(path.lstat().st_mode):04o}",
            }
        )
    return sorted(entries, key=lambda entry: entry["path"])


def _projection_immutable_inventory(root: Path) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    mutable = {TRAIN_OUT_ROOT, EVAL_OUT_ROOT}
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        current_relative = current_path.relative_to(root).as_posix()
        if current_relative == ".":
            current_relative = ""
        for name in list(dirnames):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            path_stat = path.lstat()
            if stat.S_ISLNK(path_stat.st_mode):
                raise ValidationError(
                    f"execution projection contains symlink: {relative}"
                )
            if relative in mutable:
                dirnames.remove(name)
                continue
            directories.add(relative)
        for name in filenames:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            path_stat = path.lstat()
            if not stat.S_ISREG(path_stat.st_mode):
                raise ValidationError(
                    f"execution projection contains non-regular file: {relative}"
                )
            files.add(relative)
    return files, directories


def _same_stat_inode(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _directory_changed(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        not _same_stat_inode(first, second)
        or stat.S_IMODE(first.st_mode) != stat.S_IMODE(second.st_mode)
        or first.st_nlink != second.st_nlink
        or first.st_size != second.st_size
        or first.st_mtime_ns != second.st_mtime_ns
        or first.st_ctime_ns != second.st_ctime_ns
    )


def _sha256_open_fd(fd: int) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while chunk := os.read(fd, 1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_scripts_root() -> Path:
    return Path(__file__).resolve().parents[2].joinpath("scripts").resolve(strict=True)


def _reject_conflicting_ambient_scripts_name(name: str) -> None:
    if name in {"scripts.train", "scripts.eval_only"} or name.startswith(
        ("scripts.train.", "scripts.eval_only.")
    ):
        raise ValidationError(f"protected namespace is already loaded: {name}")


def _verify_repo_local_scripts_namespace(module: types.ModuleType) -> None:
    scripts_root = _repo_scripts_root()
    metadata = module.__dict__
    spec = metadata.get("__spec__")
    loader = metadata.get("__loader__")
    if (
        type(spec) is not importlib.machinery.ModuleSpec
        or type(spec.name) is not str
        or spec.name != "scripts"
        or spec.loader is not loader
        or type(loader) is not importlib.machinery.NamespaceLoader
        or spec.origin is not None
        or metadata.get("__file__") is not None
    ):
        raise ValidationError("preloaded scripts namespace is not canonical")
    locations = spec.submodule_search_locations
    module_paths = metadata.get("__path__")
    if type(locations) is not _NamespacePath or module_paths is not locations:
        raise ValidationError("preloaded scripts namespace is not canonical")
    namespace_state = object.__getattribute__(locations, "__dict__")
    namespace_paths = namespace_state.get("_path")
    if (
        namespace_state.get("_name") != "scripts"
        or type(namespace_paths) is not list
        or any(type(item) is not str for item in namespace_paths)
    ):
        raise ValidationError("preloaded scripts namespace is not canonical")
    resolved_locations = [Path(item).resolve(strict=True) for item in namespace_paths]
    if not resolved_locations or any(
        path != scripts_root for path in resolved_locations
    ):
        raise ValidationError("preloaded scripts namespace is not repo-local")


def _verify_repo_local_scripts_source(name: str, module: types.ModuleType) -> None:
    scripts_root = _repo_scripts_root()
    expected = scripts_root.joinpath(
        *name.removeprefix("scripts.").split(".")
    ).with_suffix(".py")
    try:
        path_stat = expected.lstat()
    except OSError as exc:
        raise ValidationError("preloaded scripts module is not repo-local") from exc
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        raise ValidationError("preloaded scripts module is not a regular source file")
    try:
        expected = expected.resolve(strict=True)
        expected.relative_to(scripts_root)
    except (OSError, ValueError) as exc:
        raise ValidationError("preloaded scripts module is not repo-local") from exc
    metadata = module.__dict__
    spec = metadata.get("__spec__")
    loader = metadata.get("__loader__")
    if (
        type(spec) is not importlib.machinery.ModuleSpec
        or type(spec.name) is not str
        or spec.name != name
        or spec.loader is not loader
        or type(loader) is not importlib.machinery.SourceFileLoader
    ):
        raise ValidationError("preloaded scripts module is not canonical")
    module_file = metadata.get("__file__")
    loader_name = loader.name
    loader_path = loader.path
    if (
        type(loader_name) is not str
        or loader_name != name
        or type(module_file) is not str
        or type(spec.origin) is not str
        or type(loader_path) is not str
        or Path(module_file).resolve(strict=True) != expected
        or Path(spec.origin).resolve(strict=True) != expected
        or Path(loader_path).resolve(strict=True) != expected
        or spec.submodule_search_locations is not None
    ):
        raise ValidationError("preloaded scripts module is not canonical")


def _verified_preloaded_repo_scripts_modules() -> tuple[str, ...]:
    verified: list[str] = []
    for name, module in sorted(sys.modules.items()):
        if name == "skillopt" or name.startswith("skillopt."):
            raise ValidationError(f"protected namespace is already loaded: {name}")
        if name != "scripts" and not name.startswith("scripts."):
            continue
        _reject_conflicting_ambient_scripts_name(name)
        if type(module) is not types.ModuleType:
            raise ValidationError(f"protected namespace is already loaded: {name}")
        if name == "scripts":
            _verify_repo_local_scripts_namespace(module)
        else:
            _verify_repo_local_scripts_source(name, module)
        verified.append(name)
    return tuple(verified)


def _reject_preloaded_protected_modules() -> None:
    _verified_preloaded_repo_scripts_modules()


def _detach_preloaded_repo_scripts_modules(
    snapshot: Mapping[str, types.ModuleType],
) -> None:
    for name in sorted(
        _verified_preloaded_repo_scripts_modules(),
        key=lambda item: item.count("."),
        reverse=True,
    ):
        if sys.modules.get(name) is not snapshot.get(name):
            raise ValidationError("preloaded scripts module changed before execution")
        sys.modules.pop(name, None)


def _restore_module_snapshot(snapshot: Mapping[str, types.ModuleType]) -> None:
    for name in set(sys.modules) - set(snapshot):
        sys.modules.pop(name, None)
    for name, module in snapshot.items():
        if sys.modules.get(name) is not module:
            sys.modules[name] = module
    if set(sys.modules) != set(snapshot) or any(
        sys.modules.get(name) is not module for name, module in snapshot.items()
    ):
        raise ValidationError("module snapshot restoration failed")


def _require_exact_module(module: Any, root: Path, expected_relative: str) -> None:
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str) or module_file.endswith((".pyc", ".pyo")):
        raise ValidationError("protected source module is not source-backed")
    try:
        relative = (
            Path(module_file)
            .resolve(strict=True)
            .relative_to(root.resolve(strict=True))
            .as_posix()
        )
    except (OSError, ValueError) as exc:
        raise ValidationError("protected source module escaped execution root") from exc
    if relative != expected_relative:
        raise ValidationError("protected source module resolved to wrong path")
    spec = getattr(module, "__spec__", None)
    loader = getattr(module, "__loader__", None)
    expected_origin = str((root / expected_relative).resolve(strict=True))
    locations = spec.submodule_search_locations if spec is not None else None
    expected_locations = (
        [str(Path(expected_origin).parent)]
        if expected_relative.endswith("/__init__.py")
        else None
    )
    if (
        spec is None
        or spec.loader is not loader
        or type(loader) is not _CanonicalProtectedSourceLoader
        or loader.fullname != module.__name__
        or loader.filename != expected_origin
        or loader.source_sha256 != _sha256_path(root / expected_relative)
        or spec.origin != expected_origin
        or Path(module_file).resolve(strict=True) != Path(expected_origin)
        or (list(locations) if locations is not None else None) != expected_locations
    ):
        raise ValidationError(
            "protected module does not use the canonical source loader"
        )


def _validate_loaded_source_modules(
    root: Path, profile: Mapping[str, Any]
) -> dict[str, dict[str, str]]:
    manifest = {
        entry["path"]: entry
        for entry in profile["staging_manifest"]["staged_tree"]
        if entry["path"].endswith(".py")
    }
    bindings: dict[str, dict[str, str]] = {}
    resolved_root = root.resolve(strict=True)
    for name, module in sorted(sys.modules.items()):
        if not any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in _PROTECTED_PREFIXES
        ):
            continue
        module_file = getattr(module, "__file__", None)
        if module_file is None and name in {
            "scripts",
            "skillopt.envs.jiphyeonjeon_search",
        }:
            paths = [Path(item).resolve(strict=True) for item in module.__path__]
            expected_namespace = resolved_root / name.replace(".", "/")
            if paths != [expected_namespace]:
                raise ValidationError(
                    f"protected namespace is not single-path execution-local: {name}"
                )
            bindings[name] = {
                "path": name.replace(".", "/"),
                "sha256": "namespace",
            }
            continue
        if not isinstance(module_file, str) or module_file.endswith((".pyc", ".pyo")):
            raise ValidationError(f"protected module is not .py source-backed: {name}")
        try:
            relative = (
                Path(module_file)
                .resolve(strict=True)
                .relative_to(resolved_root)
                .as_posix()
            )
        except (OSError, ValueError) as exc:
            raise ValidationError(
                f"protected module escaped execution root: {name}"
            ) from exc
        if relative not in manifest:
            raise ValidationError(f"protected module is not manifest-listed: {name}")
        observed = _sha256_path(resolved_root / relative)
        if observed != manifest[relative]["sha256"]:
            raise ValidationError(f"protected module source changed: {name}")
        bindings[name] = {"path": relative, "sha256": observed}
        _require_exact_module(module, root, relative)
    return bindings


def _bind_required_callables(
    root: Path, *, train: bool | None
) -> dict[str, dict[str, str]]:
    del train
    bindings: dict[str, dict[str, str]] = {}
    values = _required_callable_values()
    for label, value in values.items():
        if not callable(value) or not hasattr(value, "__code__"):
            raise ValidationError(f"required upstream callable is missing: {label}")
        source_file = inspect.getsourcefile(value)
        if source_file is None:
            raise ValidationError(f"required upstream callable has no source: {label}")
        try:
            relative = (
                Path(source_file)
                .resolve(strict=True)
                .relative_to(root.resolve(strict=True))
                .as_posix()
            )
        except (OSError, ValueError) as exc:
            raise ValidationError(
                f"required callable escaped execution root: {label}"
            ) from exc
        bindings[label] = {
            "path": relative,
            "source_sha256": _sha256_path(root / relative),
            "code_sha256": _code_hash(value.__code__),
        }
    _validate_exact_aliases(values)
    return dict(sorted(bindings.items()))


def _required_callable_values() -> dict[str, Any]:
    values: dict[str, Any] = {}
    for label, (module_name, attribute_path) in _REQUIRED_CALLABLE_SPECS.items():
        module = sys.modules.get(module_name)
        if module is None:
            raise ValidationError(f"required callable module is absent: {module_name}")
        value: Any = module
        for part in attribute_path.split("."):
            value = getattr(value, part, None)
        values[label] = value
    return values


def _validate_exact_aliases(values: Mapping[str, Any]) -> None:
    trainer = sys.modules["skillopt.engine.trainer"]
    canonical_aliases = {
        "merge_patches": values["merge_patches"],
        "rank_and_select": values["rank_and_select"],
        "apply_patch_with_report": values["apply_patch_with_report"],
        "evaluate_gate": values["evaluate_gate"],
        "select_gate_score": values["select_gate_score"],
    }
    for name, canonical in canonical_aliases.items():
        if getattr(trainer, name, None) is not canonical:
            raise ValidationError(f"trainer callable alias was replaced: {name}")
    adapter_module = sys.modules["skillopt.envs.jiphyeonjeon_search.adapter"]
    adapter_class = getattr(adapter_module, "JiphyeonjeonSearchAdapter", None)
    if not isinstance(adapter_class, type):
        raise ValidationError("canonical adapter class is missing")
    for script_name in ("scripts.train", "scripts.eval_only"):
        script = sys.modules[script_name]
        registry = getattr(script, "_ENV_REGISTRY", None)
        if not isinstance(registry, dict) or (
            "jiphyeonjeon_search" in registry
            and registry["jiphyeonjeon_search"] is not adapter_class
        ):
            raise ValidationError(f"{script_name} adapter alias was replaced")


def _validate_adapter_registries() -> None:
    adapter_class = sys.modules[
        "skillopt.envs.jiphyeonjeon_search.adapter"
    ].JiphyeonjeonSearchAdapter
    for script_name in ("scripts.train", "scripts.eval_only"):
        registry = getattr(sys.modules[script_name], "_ENV_REGISTRY", None)
        if (
            not isinstance(registry, dict)
            or registry.get("jiphyeonjeon_search") is not adapter_class
        ):
            raise ValidationError(f"{script_name} canonical adapter was not used")


def _preload_exact_source_closure(root: Path) -> dict[str, Any]:
    module_names = sorted(
        {module_name for module_name, _ in _REQUIRED_CALLABLE_SPECS.values()},
        key=lambda name: (name.startswith("scripts."), name),
    )
    for module_name in module_names:
        module = _CANONICAL_IMPORT_MODULE(module_name)
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise ValidationError(f"required module has no source file: {module_name}")
        relative = (
            Path(module_file)
            .resolve(strict=True)
            .relative_to(root.resolve(strict=True))
            .as_posix()
        )
        _require_exact_module(module, root, relative)
    values = _required_callable_values()
    _validate_exact_aliases(values)
    _validate_pinned_code_closure(values)
    return values


def _validate_pinned_code_closure(values: Mapping[str, Any]) -> None:
    forbidden_names = {
        "CDLL",
        "ExtensionFileLoader",
        "PyDLL",
        "ctypes",
        "dlopen",
        "exec_module",
        "find_spec",
        "meta_path",
        "path_hooks",
        "spec_from_file_location",
    }
    for label, value in values.items():
        codes = [value.__code__]
        while codes:
            code = codes.pop()
            if forbidden_names.intersection(code.co_names):
                raise ValidationError(
                    f"pinned callable has native-loader escape: {label}"
                )
            codes.extend(
                constant
                for constant in code.co_consts
                if isinstance(constant, types.CodeType)
            )


def _code_hash(code: types.CodeType) -> str:
    constants = tuple(
        _normalized_code(constant) if isinstance(constant, types.CodeType) else constant
        for constant in code.co_consts
    )
    normalized = code.replace(co_filename="", co_consts=constants)
    return hashlib.sha256(marshal.dumps(normalized)).hexdigest()


def _normalized_code(code: types.CodeType) -> types.CodeType:
    constants = tuple(
        _normalized_code(constant) if isinstance(constant, types.CodeType) else constant
        for constant in code.co_consts
    )
    return code.replace(co_filename="", co_consts=constants)


def _validate_call_observations(calls: Mapping[str, Any]) -> None:
    if not isinstance(calls, Mapping) or set(calls) != set(_EXPECTED_CALL_COUNTS):
        raise ValidationError("upstream call observation keys are not canonical")
    if dict(calls) != _EXPECTED_CALL_COUNTS:
        raise ValidationError("upstream call observation counts are not canonical")
    for name, minimum in _REQUIRED_CALL_COUNTS.items():
        observed = calls.get(name)
        if type(observed) is not int or observed < minimum:
            raise ValidationError(f"required upstream call was not observed: {name}")
    if calls.get("scripts.train.main") != 1 or calls.get("scripts.eval_only.main") != 1:
        raise ValidationError("train/eval main must each execute exactly once")
    for name in (
        "adapter.setup",
        "adapter.build_env_from_batch",
        "adapter.build_eval_env",
        "adapter.rollout",
        "adapter.reflect",
    ):
        if type(calls.get(name)) is not int or calls[name] < 1:
            raise ValidationError(f"adapter lifecycle call was not observed: {name}")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _binding_hash(domain: str, value: Any) -> str:
    return hashlib.sha256(
        b"skillopt:" + domain.encode("ascii") + b"\x00" + _canonical_json_bytes(value)
    ).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
