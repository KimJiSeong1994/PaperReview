"""Strict compatibility contracts for Microsoft SkillOpt v0.2.0 profiles."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import stat
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Any, NoReturn

from .skillopt_contract import ValidationError


PROFILE_CATALOG_VERSION = "skillopt-compatibility-profiles-v1"
PRISTINE_SOURCE_MANIFEST_VERSION = "pristine_source_manifest_v1"
OVERLAY_MANIFEST_VERSION = "overlay_manifest_v1"
STAGING_MANIFEST_VERSION = "staging_manifest_v1"
RUNNER_IDENTITY_VERSION = "runner_identity_v1"
SAME_DOMAIN_CUSTODY_EVIDENCE_VERSION = "same_domain_custody_evidence_v1"

PRISTINE_SOURCE_VERSION = PRISTINE_SOURCE_MANIFEST_VERSION
OVERLAY_VERSION = OVERLAY_MANIFEST_VERSION
STAGING_VERSION = STAGING_MANIFEST_VERSION
CUSTODY_EVIDENCE_VERSION = SAME_DOMAIN_CUSTODY_EVIDENCE_VERSION

PROFILE_ID = "microsoft-skillopt-v0.2.0-e4ea6a6771e7"
REPO_URL = "https://github.com/microsoft/SkillOpt"
SOURCE_VERSION = "v0.2.0"
SOURCE_IMMUTABLE_OBJECT_VERSION = "git-object:e4ea6a6771e797ef820cdd8bfea64c57e0481065"
OVERLAY_IMMUTABLE_OBJECT_VERSION = "skillopt-overlay-contract-v1"
SOURCE_AUTHORITY = "github.com/microsoft/SkillOpt"
PROFILE_CONFIG_PATH = "configs/jiphyeonjeon_search/default.yaml"
PROFILE_CONFIG_BASE = "configs/_base_/default.yaml"
PROFILE_CONFIG_BASE_REFERENCE = "../_base_/default.yaml"
LOADER_PATH = "skillopt/config.py"
TRAIN_OUT_ROOT = "outputs/train"
EVAL_OUT_ROOT = "outputs/eval"
CANDIDATE_PATH = "outputs/train/best_skill.md"
SPLIT_DIR = "data/jiphyeonjeon_search_split"
SPLIT_MANIFEST_PATH = f"{SPLIT_DIR}/split_manifest.json"
SPLIT_TRAIN_ITEMS_PATH = f"{SPLIT_DIR}/train/items.json"
SPLIT_VAL_ITEMS_PATH = f"{SPLIT_DIR}/val/items.json"
SPLIT_TEST_ITEMS_PATH = f"{SPLIT_DIR}/test/items.json"
SKILL_INIT_PATH = "skillopt/envs/jiphyeonjeon_search/skills/initial.md"
ADAPTER_PATH = "skillopt/envs/jiphyeonjeon_search/adapter.py"
CANONICAL_PYTHON_INTERPRETER = "/usr/local/bin/python"

APPROVED_TAG_OBJECT = "51d0a4d96e88558c84dee637f98e24e3fb2d1547"
APPROVED_PEELED_COMMIT = "e4ea6a6771e797ef820cdd8bfea64c57e0481065"
APPROVED_TREE_GIT_SHA1 = "5a603e937a20f1078059f94039a50028c022487a"
APPROVED_ARCHIVE_SHA256 = (
    "dec3f6b81cbc56fcd6a3e6fbe3bd640331c760f39dd73952f1631ae3d6d20f87"
)
SOURCE_INVENTORY_VERSION = "skillopt_source_inventory_v020"
APPROVED_SOURCE_INVENTORY_IDENTITY = (
    "sha256:b62a1830d8143ce18d6d6e7165a8b205bedbf0718994ee5e16450617d0b64b8c"
)
SOURCE_INVENTORY_PATH = (
    Path(__file__).resolve().parents[2]
    / "data/search_eval/skillopt_source_inventory_v020.json"
)


def _top_reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _validate_inventory_path(value: Any) -> str:
    if not isinstance(value, str) or value == "":
        raise ValidationError("invalid source inventory path")
    if "\x00" in value or "\\" in value:
        raise ValidationError("invalid source inventory path")
    normalized = unicodedata.normalize("NFC", value)
    if normalized != value:
        raise ValidationError("invalid source inventory path")
    path = PurePosixPath(value)
    if path.is_absolute() or value in {".", ".."}:
        raise ValidationError("invalid source inventory path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValidationError("invalid source inventory path")
    return value


def _load_approved_source_inventory() -> dict[str, Any]:
    try:
        raw = SOURCE_INVENTORY_PATH.read_bytes()
        inventory = json.loads(raw, object_pairs_hook=_top_reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "approved SkillOpt source inventory is unreadable"
        ) from exc
    if not isinstance(inventory, Mapping):
        raise ValidationError("approved SkillOpt source inventory must be an object")
    if set(inventory) != {"version", "tree_git_sha1", "files", "identity"}:
        raise ValidationError("approved SkillOpt source inventory has invalid keys")
    if inventory["version"] != SOURCE_INVENTORY_VERSION:
        raise ValidationError("approved SkillOpt source inventory version mismatch")
    if inventory["tree_git_sha1"] != APPROVED_TREE_GIT_SHA1:
        raise ValidationError("approved SkillOpt source inventory tree mismatch")
    files = inventory["files"]
    if not isinstance(files, list) or len(files) != 311:
        raise ValidationError(
            "approved SkillOpt source inventory must contain 311 files"
        )
    seen: set[str] = set()
    seen_folded: set[str] = set()
    for index, entry in enumerate(files):
        if not isinstance(entry, Mapping):
            raise ValidationError(
                f"source inventory file entry {index} must be an object"
            )
        if set(entry) != {"path", "kind", "mode", "size_bytes", "sha256"}:
            raise ValidationError(
                f"source inventory file entry {index} has invalid keys"
            )
        if entry["kind"] != "file" or entry["mode"] not in {"0644", "0755"}:
            raise ValidationError(f"source inventory file entry {index} is invalid")
        try:
            path = _validate_inventory_path(entry["path"])
        except ValidationError as exc:
            raise ValidationError(
                f"source inventory file entry {index} has invalid path"
            ) from exc
        folded = unicodedata.normalize("NFC", path).casefold()
        if path in seen or folded in seen_folded:
            raise ValidationError(
                f"source inventory file entry {index} has invalid path"
            )
        if type(entry["size_bytes"]) is not int or entry["size_bytes"] < 0:
            raise ValidationError(
                f"source inventory file entry {index} has invalid size"
            )
        if not isinstance(entry["sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", entry["sha256"]
        ):
            raise ValidationError(
                f"source inventory file entry {index} has invalid sha256"
            )
        seen.add(path)
        seen_folded.add(folded)
    if [entry["path"] for entry in files] != sorted(entry["path"] for entry in files):
        raise ValidationError("approved SkillOpt source inventory must be path sorted")
    payload = {key: inventory[key] for key in ("version", "tree_git_sha1", "files")}
    body = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    identity = (
        "sha256:"
        + hashlib.sha256(
            b"skillopt:" + SOURCE_INVENTORY_VERSION.encode("ascii") + b"\x00" + body
        ).hexdigest()
    )
    if (
        identity != APPROVED_SOURCE_INVENTORY_IDENTITY
        or inventory["identity"] != identity
    ):
        raise ValidationError("approved SkillOpt source inventory identity mismatch")
    return inventory


APPROVED_SOURCE_INVENTORY = _load_approved_source_inventory()
APPROVED_FILE_ENTRIES: tuple[dict[str, Any], ...] = tuple(
    dict(entry) for entry in APPROVED_SOURCE_INVENTORY["files"]
)

APPROVED_FILE_BY_PATH = {entry["path"]: entry for entry in APPROVED_FILE_ENTRIES}
REQUIREMENTS_SHA256 = APPROVED_FILE_BY_PATH["requirements.txt"]["sha256"]
TRAIN_REGISTRY_SHA256 = APPROVED_FILE_BY_PATH["scripts/train.py"]["sha256"]
EVAL_REGISTRY_SHA256 = APPROVED_FILE_BY_PATH["scripts/eval_only.py"]["sha256"]
CONFIG_SHA256 = APPROVED_FILE_BY_PATH["skillopt/config.py"]["sha256"]
BASE_CONFIG_SHA256 = APPROVED_FILE_BY_PATH["configs/_base_/default.yaml"]["sha256"]
PHASE0_READY_ERROR = (
    "phase3_external_verification_required: Phase 3 sealed external verification "
    "is required before this compatibility profile can be marked ready"
)
QUERY_ANALYZER_CONTRACT_NAME = "canonical_query_analyzer_product_contract"
OVERLAY_SCHEMA_NAME = "generated_overlay_schema"
REGISTRY_PATCH_CONTRACT_NAME = "registry_patch_contract"
QUERY_ANALYZER_CONTRACT_PATH = "overlay/contracts/query_analyzer_product_contract.json"
OVERLAY_SCHEMA_PATH = "overlay/schema/generated_overlay_schema.json"
REGISTRY_PATCH_CONTRACT_PATH = "overlay/contracts/registry_patch_contract.json"
QUERY_ANALYZER_SOURCE_PATH = "app/QueryAgent/query_analyzer.py"
QUERY_ANALYZER_SOURCE_SHA256 = (
    "5a31c5d06d363558f1d74355168d90deb562840a5f1ba87566a7ffa64a755f59"
)
QUERY_ANALYZER_ALLOWED_INTENTS = (
    "author_search",
    "comparison",
    "latest_research",
    "method_search",
    "paper_search",
    "problem_solving",
    "survey",
    "topic_exploration",
    "unknown",
)


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


QUERY_ANALYZER_CONTRACT = {
    "artifact": QUERY_ANALYZER_CONTRACT_NAME,
    "contract_version": "query_analyzer_contract_v1",
    "production_source": {
        "path": QUERY_ANALYZER_SOURCE_PATH,
        "sha256": QUERY_ANALYZER_SOURCE_SHA256,
    },
    "raw_model_output_v1": {
        "additional_properties": False,
        "fields": {
            "analysis_details": {"max_length": 4096, "type": "string"},
            "confidence": {"maximum": 1.0, "minimum": 0.0, "type": "number"},
            "core_concepts": {
                "items": {"max_length": 160, "type": "string"},
                "max_items": 5,
                "type": "array",
            },
            "improved_query": {"max_length": 1024, "type": "string"},
            "is_academic": {
                "default_when_missing": True,
                "normalization": "bool",
                "type": "any_json",
            },
            "intent": {
                "allowed": list(QUERY_ANALYZER_ALLOWED_INTENTS[:-1]),
                "type": "string",
            },
            "keywords": {
                "items": {"max_length": 160, "type": "string"},
                "max_items": 7,
                "type": "array",
            },
            "research_area": {"max_length": 256, "type": "string"},
            "search_filters": {
                "additional_properties": False,
                "fields": {
                    "category": {"nullable": True, "type": "string"},
                    "min_citations": {
                        "minimum": 0,
                        "nullable": True,
                        "type": "integer",
                    },
                    "year_end": {"nullable": True, "type": "integer"},
                    "year_start": {"nullable": True, "type": "integer"},
                },
                "type": "object",
            },
            "search_strategy": {"max_length": 2048, "type": "string"},
            "source_queries": {
                "additional_properties": True,
                "default_when_missing": {},
                "fields": {
                    "arxiv": {
                        "default_when_missing": "original_query",
                        "normalization": "passthrough",
                        "type": "any_json",
                    },
                    "dblp": {
                        "default_when_missing": "original_query",
                        "normalization": "passthrough",
                        "type": "any_json",
                    },
                    "google_scholar": {
                        "default_when_missing": "original_query",
                        "type": "any_json",
                    },
                    "scholar_queries": {
                        "alias_of": "google_scholar",
                        "optional": True,
                        "precedence": "when_present",
                        "type": "any_json",
                    },
                },
                "type": "object",
            },
        },
        "type": "object",
    },
    "normalized_query_analysis_v1": {
        "additional_properties": False,
        "common_required_fields": [
            "confidence",
            "improved_query",
            "intent",
            "is_academic",
            "keywords",
            "original_query",
            "search_filters",
            "source_queries",
        ],
        "fields": {
            "analysis_details": {
                "max_length": 4096,
                "optional": True,
                "type": "string",
            },
            "confidence": {"maximum": 1.0, "minimum": 0.0, "type": "number"},
            "core_concepts": {
                "max_items": 5,
                "optional": True,
                "type": "array[string]",
            },
            "error": {"max_length": 512, "optional": True, "type": "string"},
            "improved_query": {"max_length": 1024, "type": "string"},
            "is_academic": {"type": "boolean"},
            "intent": {
                "allowed": list(QUERY_ANALYZER_ALLOWED_INTENTS),
                "type": "string",
            },
            "keywords": {"max_items": 7, "type": "array[string]"},
            "original_query": {"max_length": 1024, "type": "string"},
            "research_area": {
                "max_length": 256,
                "optional": True,
                "type": "string",
            },
            "search_filters": {
                "fields": {
                    "category": "string|null",
                    "min_citations": "integer>=0|null",
                    "year_end": "integer|null",
                    "year_start": "integer|null",
                },
                "type": "object",
            },
            "search_strategy": {
                "max_length": 2048,
                "optional": True,
                "type": "string",
            },
            "source_queries": {
                "additional_properties": False,
                "fields": {
                    "arxiv": {
                        "default_when_missing": "original_query",
                        "type": "any_json",
                    },
                    "dblp": {
                        "default_when_missing": "original_query",
                        "type": "any_json",
                    },
                    "google_scholar": {"type": "any_json"},
                    "scholar_queries": {
                        "max_items": 3,
                        "optional": True,
                        "type": "array[string]",
                    },
                    "default": {
                        "equals": "original_query",
                        "type": "string",
                    },
                },
                "type": "object",
            },
        },
        "optional_fields": [
            "analysis_details",
            "core_concepts",
            "error",
            "research_area",
            "search_strategy",
        ],
        "type": "object",
    },
    "production_normalization_v1": {
        "branches": {
            "empty_query": {
                "absent_keys": [
                    "analysis_details",
                    "core_concepts",
                    "error",
                    "research_area",
                    "search_strategy",
                ],
                "allowed_keys": [
                    "confidence",
                    "improved_query",
                    "intent",
                    "is_academic",
                    "keywords",
                    "original_query",
                    "search_filters",
                    "source_queries",
                ],
                "is_academic": True,
                "required_keys": [
                    "confidence",
                    "improved_query",
                    "intent",
                    "is_academic",
                    "keywords",
                    "original_query",
                    "search_filters",
                    "source_queries",
                ],
                "scholar_queries": "omitted",
                "source_query_absent_keys": ["scholar_queries"],
                "source_query_allowed_keys": [
                    "arxiv",
                    "dblp",
                    "default",
                    "google_scholar",
                ],
                "source_query_required_keys": [
                    "arxiv",
                    "dblp",
                    "default",
                    "google_scholar",
                ],
                "source_query_values": "original_query",
            },
            "exception_fallback": {
                "absent_keys": ["error"],
                "allowed_keys": [
                    "analysis_details",
                    "confidence",
                    "core_concepts",
                    "improved_query",
                    "intent",
                    "is_academic",
                    "keywords",
                    "original_query",
                    "research_area",
                    "search_filters",
                    "search_strategy",
                    "source_queries",
                ],
                "is_academic_default": True,
                "required_keys": [
                    "analysis_details",
                    "confidence",
                    "improved_query",
                    "intent",
                    "is_academic",
                    "keywords",
                    "original_query",
                    "search_filters",
                    "source_queries",
                ],
                "scholar_queries": "omitted",
                "source_query_absent_keys": ["scholar_queries"],
                "source_query_allowed_keys": [
                    "arxiv",
                    "dblp",
                    "default",
                    "google_scholar",
                ],
                "source_query_required_keys": [
                    "arxiv",
                    "dblp",
                    "default",
                    "google_scholar",
                ],
                "source_queries": "generate_source_specific_queries",
            },
            "no_client_fallback": {
                "absent_keys": [
                    "core_concepts",
                    "error",
                    "research_area",
                    "search_strategy",
                ],
                "allowed_keys": [
                    "analysis_details",
                    "confidence",
                    "improved_query",
                    "intent",
                    "is_academic",
                    "keywords",
                    "original_query",
                    "search_filters",
                    "source_queries",
                ],
                "is_academic": True,
                "required_keys": [
                    "analysis_details",
                    "confidence",
                    "improved_query",
                    "intent",
                    "is_academic",
                    "keywords",
                    "original_query",
                    "search_filters",
                    "source_queries",
                ],
                "scholar_queries": "omitted",
                "source_query_absent_keys": ["scholar_queries"],
                "source_query_allowed_keys": [
                    "arxiv",
                    "dblp",
                    "default",
                    "google_scholar",
                ],
                "source_query_required_keys": [
                    "arxiv",
                    "dblp",
                    "default",
                    "google_scholar",
                ],
                "source_queries": "keyword_fallback",
            },
            "unified_llm_success": {
                "absent_keys": ["analysis_details", "error"],
                "allowed_keys": [
                    "confidence",
                    "core_concepts",
                    "improved_query",
                    "intent",
                    "is_academic",
                    "keywords",
                    "original_query",
                    "research_area",
                    "search_filters",
                    "search_strategy",
                    "source_queries",
                ],
                "is_academic": "bool(raw.is_academic default true)",
                "required_keys": [
                    "confidence",
                    "core_concepts",
                    "improved_query",
                    "intent",
                    "is_academic",
                    "keywords",
                    "original_query",
                    "research_area",
                    "search_filters",
                    "search_strategy",
                    "source_queries",
                ],
                "scholar_queries": "present",
                "source_query_absent_keys": [],
                "source_query_allowed_keys": [
                    "arxiv",
                    "dblp",
                    "default",
                    "google_scholar",
                    "scholar_queries",
                ],
                "source_query_required_keys": [
                    "arxiv",
                    "dblp",
                    "default",
                    "google_scholar",
                    "scholar_queries",
                ],
            },
        },
        "scholar_queries": {
            "alias_precedence": "source_queries.scholar_queries_over_google_scholar",
            "list": "truthy_items_stringified_stripped_first_3",
            "string": "base_then_distinct_improved_query_then_first_5_keywords_first_3",
            "unexpected": "google_scholar_string_else_original_query_singleton",
        },
    },
    "scope": {
        "allowed": "query_analyzer_standard_search",
        "forbidden_production_expansion": [
            "deep_review",
            "hyde",
            "llm_search",
            "relevance_filter_prompt_optimization",
            "rollout_above_zero",
        ],
    },
}
QUERY_ANALYZER_CONTRACT_BYTES = _canonical_json_bytes(QUERY_ANALYZER_CONTRACT)
REQUIRED_PROJECTED_INPUT_PATHS = (
    ADAPTER_PATH,
    PROFILE_CONFIG_PATH,
    SKILL_INIT_PATH,
    SPLIT_MANIFEST_PATH,
    SPLIT_TRAIN_ITEMS_PATH,
    SPLIT_VAL_ITEMS_PATH,
    SPLIT_TEST_ITEMS_PATH,
)
REGISTRY_PATCH_PATHS = ("scripts/train.py", "scripts/eval_only.py")
REQUIRED_IMPORTED_MODULES = {
    "skillopt.config": "skillopt/config.py",
    "skillopt.envs.jiphyeonjeon_search.adapter": ADAPTER_PATH,
    "scripts.train": "scripts/train.py",
    "scripts.eval_only": "scripts/eval_only.py",
}
TRAIN_ARGV = [
    CANONICAL_PYTHON_INTERPRETER,
    "scripts/train.py",
    "--config",
    PROFILE_CONFIG_PATH,
    "--split_dir",
    SPLIT_DIR,
    "--out_root",
    TRAIN_OUT_ROOT,
]
EVAL_ARGV = [
    CANONICAL_PYTHON_INTERPRETER,
    "scripts/eval_only.py",
    "--config",
    PROFILE_CONFIG_PATH,
    "--skill",
    CANDIDATE_PATH,
    "--split",
    "all",
    "--split_dir",
    SPLIT_DIR,
    "--out_root",
    EVAL_OUT_ROOT,
]

CANONICAL_EXECUTION_KNOBS = {
    "accumulation": 1,
    "analyst_workers": 1,
    "batch_size": 3,
    "edit_budget": 1,
    "env_name": "jiphyeonjeon_search",
    "eval_test": True,
    "failure_only": True,
    "gate_metric": "mixed",
    "gate_mixed_weight": 0.8,
    "lr_control_mode": "fixed",
    "lr_scheduler": "constant",
    "max_analyst_rounds": 1,
    "merge_batch_size": 1,
    "min_edit_budget": 1,
    "minibatch_size": 1,
    "mock": True,
    "num_epochs": 1,
    "seed": 42,
    "sel_env_num": 2,
    "skill_init": SKILL_INIT_PATH,
    "skill_update_mode": "patch",
    "split_dir": SPLIT_DIR,
    "split_mode": "split_dir",
    "test_env_num": 2,
    "train_size": 3,
    "use_gate": True,
    "use_meta_skill": False,
    "use_skill_aware_reflection": False,
    "use_slow_update": False,
    "workers": 1,
}
CANONICAL_RENDERED_CONFIG = {
    "_base_": PROFILE_CONFIG_BASE_REFERENCE,
    "train": {
        "num_epochs": 1,
        "train_size": 3,
        "batch_size": 3,
        "accumulation": 1,
        "seed": 42,
    },
    "gradient": {
        "minibatch_size": 1,
        "merge_batch_size": 1,
        "analyst_workers": 1,
        "max_analyst_rounds": 1,
        "failure_only": True,
    },
    "optimizer": {
        "learning_rate": 1,
        "min_learning_rate": 1,
        "lr_scheduler": "constant",
        "lr_control_mode": "fixed",
        "skill_update_mode": "patch",
        "use_slow_update": False,
        "use_meta_skill": False,
        "use_skill_aware_reflection": False,
    },
    "evaluation": {
        "use_gate": True,
        "gate_metric": "mixed",
        "gate_mixed_weight": 0.8,
        "sel_env_num": 2,
        "test_env_num": 2,
        "eval_test": True,
    },
    "env": {
        "name": "jiphyeonjeon_search",
        "skill_init": SKILL_INIT_PATH,
        "split_mode": "split_dir",
        "split_dir": SPLIT_DIR,
        "workers": 1,
        "mock": True,
    },
}
CANONICAL_RENDERED_CONFIG_BYTES = b"""_base_: ../_base_/default.yaml
train:
  num_epochs: 1
  train_size: 3
  batch_size: 3
  accumulation: 1
  seed: 42
gradient:
  minibatch_size: 1
  merge_batch_size: 1
  analyst_workers: 1
  max_analyst_rounds: 1
  failure_only: true
optimizer:
  learning_rate: 1
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
  sel_env_num: 2
  test_env_num: 2
  eval_test: true
env:
  name: jiphyeonjeon_search
  skill_init: skillopt/envs/jiphyeonjeon_search/skills/initial.md
  split_mode: split_dir
  split_dir: data/jiphyeonjeon_search_split
  workers: 1
  mock: true
"""

CANONICAL_SPLIT_ITEMS = {
    "train": [
        {"id": "train-1", "query": "graph retrieval", "split": "train"},
        {"id": "train-2", "query": "agent memory", "split": "train"},
        {"id": "train-3", "query": "hybrid ranking", "split": "train"},
    ],
    "val": [
        {"id": "val-1", "query": "paper title lookup", "split": "val"},
        {"id": "val-2", "query": "author search", "split": "val"},
    ],
    "test": [
        {"id": "test-1", "query": "recent survey", "split": "test"},
        {"id": "test-2", "query": "method comparison", "split": "test"},
    ],
}
CANONICAL_SPLIT_ITEM_BYTES = {
    split: _canonical_json_bytes(items)
    for split, items in CANONICAL_SPLIT_ITEMS.items()
}
CANONICAL_SPLIT_MANIFEST = {
    "dataset": "jiphyeonjeon_search",
    "logical_splits": {
        "optimizer_test": "test",
        "selection": "val",
        "training": "train",
    },
    "splits": {
        split: {
            "count": len(items),
            "items_path": f"{SPLIT_DIR}/{split}/items.json",
        }
        for split, items in CANONICAL_SPLIT_ITEMS.items()
    },
    "version": "jiphyeonjeon_search_split_v1",
}
CANONICAL_SPLIT_MANIFEST_BYTES = _canonical_json_bytes(CANONICAL_SPLIT_MANIFEST)

REGISTRY_PATCH_OPERATION_ID = "unconditional_jiphyeonjeon_registration_v1"
REGISTRY_PATCH_INSERTION = (
    b"    from skillopt.envs.jiphyeonjeon_search.adapter import "
    b"JiphyeonjeonSearchAdapter\n"
    b'    _ENV_REGISTRY["jiphyeonjeon_search"] = JiphyeonjeonSearchAdapter\n'
)
REGISTRY_PATCH_RESULTS = {
    "scripts/train.py": {
        "sha256": "a795cb8dc65de9751f981f9cbab981bd82f5828495ab448e32f03d86ead25905",
        "size_bytes": 26481,
    },
    "scripts/eval_only.py": {
        "sha256": "0579f1b9711dbcdf84a384d8dce3850243e5bd6f26d1f4ffd091d82f435d7d19",
        "size_bytes": 22938,
    },
}
REGISTRY_PATCH_CONTRACT = {
    "artifact": REGISTRY_PATCH_CONTRACT_NAME,
    "patches": {
        path: {
            "base_sha256": APPROVED_FILE_BY_PATH[path]["sha256"],
            "base_size_bytes": APPROVED_FILE_BY_PATH[path]["size_bytes"],
            "idempotent": True,
            "insertion_sha256": hashlib.sha256(REGISTRY_PATCH_INSERTION).hexdigest(),
            "insertion_size_bytes": len(REGISTRY_PATCH_INSERTION),
            "operation_id": REGISTRY_PATCH_OPERATION_ID,
            "result_sha256": REGISTRY_PATCH_RESULTS[path]["sha256"],
            "result_size_bytes": REGISTRY_PATCH_RESULTS[path]["size_bytes"],
        }
        for path in REGISTRY_PATCH_PATHS
    },
    "version": "registry_patch_contract_v2",
}


def _registry_patch_contract(script_path: str) -> Mapping[str, Any]:
    try:
        return REGISTRY_PATCH_CONTRACT["patches"][script_path]
    except (KeyError, TypeError) as exc:
        raise ValidationError(
            f"unsupported registry patch path: {script_path}"
        ) from exc


def _payload_matches(payload: bytes, *, size_bytes: int, sha256: str) -> bool:
    return len(payload) == size_bytes and hashlib.sha256(payload).hexdigest() == sha256


def _required_script_structure(
    tree: ast.Module, script_path: str
) -> dict[str, ast.FunctionDef]:
    functions: dict[str, ast.FunctionDef] = {}
    for name in ("_register_builtins", "get_adapter", "parse_args", "main"):
        matches = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        ]
        if len(matches) != 1:
            raise ValidationError(
                f"{script_path} must preserve exactly one {name} function"
            )
        functions[name] = matches[0]

    registry_declarations = [
        node
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "_ENV_REGISTRY"
    ]
    if len(registry_declarations) != 1:
        raise ValidationError(
            f"{script_path} must preserve the _ENV_REGISTRY declaration"
        )
    if any(
        isinstance(node, ast.Name) and node.id == "ENV_REGISTRY"
        for node in ast.walk(tree)
    ):
        raise ValidationError(f"{script_path} must not introduce ENV_REGISTRY")

    get_adapter = functions["get_adapter"]
    if not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_register_builtins"
        for node in ast.walk(get_adapter)
    ):
        raise ValidationError(f"{script_path} get_adapter must call _register_builtins")
    if not any(
        isinstance(node, ast.Name) and node.id == "_ENV_REGISTRY"
        for node in ast.walk(get_adapter)
    ):
        raise ValidationError(f"{script_path} get_adapter must use _ENV_REGISTRY")

    main_guards = [
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        and len(node.test.ops) == 1
        and isinstance(node.test.ops[0], ast.Eq)
        and len(node.test.comparators) == 1
        and isinstance(node.test.comparators[0], ast.Constant)
        and node.test.comparators[0].value == "__main__"
    ]
    if len(main_guards) != 1 or not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "main"
        for node in ast.walk(main_guards[0])
    ):
        raise ValidationError(f"{script_path} must preserve its main guard")
    return functions


_REGISTRY_PATCH_AST_NODES = (
    ast.parse(b"def _registration_fixture():\n" + REGISTRY_PATCH_INSERTION).body[0].body
)


def validate_registry_patch_result(script_path: str, payload: bytes) -> None:
    """Validate the complete pinned script, its exact inverse, and its AST delta."""

    if not isinstance(payload, bytes):
        raise ValidationError("registry patch payload must be bytes")
    contract = _registry_patch_contract(script_path)
    if not _payload_matches(
        payload,
        size_bytes=contract["result_size_bytes"],
        sha256=contract["result_sha256"],
    ):
        raise ValidationError(f"{script_path} registry patch result is not approved")
    if payload.count(REGISTRY_PATCH_INSERTION) != 1:
        raise ValidationError(
            f"{script_path} must contain exactly one registry insertion"
        )

    base = payload.replace(REGISTRY_PATCH_INSERTION, b"", 1)
    if not _payload_matches(
        base,
        size_bytes=contract["base_size_bytes"],
        sha256=contract["base_sha256"],
    ):
        raise ValidationError(f"{script_path} registry patch inverse is not approved")

    try:
        base_tree = ast.parse(base, filename=script_path)
        result_tree = ast.parse(payload, filename=script_path)
    except (SyntaxError, ValueError) as exc:
        raise ValidationError(
            f"{script_path} registry patch is not valid Python"
        ) from exc
    _required_script_structure(base_tree, script_path)
    result_functions = _required_script_structure(result_tree, script_path)
    registration_indexes = [
        index
        for index in range(len(result_functions["_register_builtins"].body) - 1)
        if all(
            ast.dump(
                result_functions["_register_builtins"].body[index + offset],
                include_attributes=False,
            )
            == ast.dump(expected, include_attributes=False)
            for offset, expected in enumerate(_REGISTRY_PATCH_AST_NODES)
        )
    ]
    if len(registration_indexes) != 1:
        raise ValidationError(
            f"{script_path} must register Jiphyeonjeon exactly once in _register_builtins"
        )
    registration_index = registration_indexes[0]
    del result_functions["_register_builtins"].body[
        registration_index : registration_index + len(_REGISTRY_PATCH_AST_NODES)
    ]
    if ast.dump(result_tree, include_attributes=False) != ast.dump(
        base_tree, include_attributes=False
    ):
        raise ValidationError(
            f"{script_path} registry patch changes upstream AST structure"
        )


def _insert_registry_registration(script_path: str, payload: bytes) -> bytes:
    """Insert the registration at the structural boundary; callers anchor the bytes."""

    if REGISTRY_PATCH_INSERTION in payload:
        raise ValidationError(
            f"{script_path} registry insertion already exists unexpectedly"
        )
    try:
        base_tree = ast.parse(payload, filename=script_path)
    except (SyntaxError, ValueError) as exc:
        raise ValidationError(
            f"{script_path} registry patch base is not valid Python"
        ) from exc
    _required_script_structure(base_tree, script_path)
    marker = b"\n\ndef get_adapter(cfg: dict):"
    if payload.count(marker) != 1:
        raise ValidationError(
            f"{script_path} lacks the approved registry insertion boundary"
        )
    insertion_offset = payload.index(marker) + 1
    return (
        payload[:insertion_offset]
        + REGISTRY_PATCH_INSERTION
        + payload[insertion_offset:]
    )


def apply_registry_patch(script_path: str, payload: bytes) -> bytes:
    """Apply the sole approved SkillOpt v0.2.0 registry insertion idempotently."""

    if not isinstance(payload, bytes):
        raise ValidationError("registry patch payload must be bytes")
    contract = _registry_patch_contract(script_path)
    if _payload_matches(
        payload,
        size_bytes=contract["result_size_bytes"],
        sha256=contract["result_sha256"],
    ):
        validate_registry_patch_result(script_path, payload)
        return payload
    if not _payload_matches(
        payload,
        size_bytes=contract["base_size_bytes"],
        sha256=contract["base_sha256"],
    ):
        raise ValidationError(f"{script_path} registry patch base is not approved")
    result = _insert_registry_registration(script_path, payload)
    validate_registry_patch_result(script_path, result)
    return result


REGISTRY_PATCH_CONTRACT_BYTES = _canonical_json_bytes(REGISTRY_PATCH_CONTRACT)
OVERLAY_SCHEMA = {
    "artifact": OVERLAY_SCHEMA_NAME,
    "logical_file_projections": ["metadata", "staged"],
    "metadata_anchors": [
        QUERY_ANALYZER_CONTRACT_NAME,
        OVERLAY_SCHEMA_NAME,
        REGISTRY_PATCH_CONTRACT_NAME,
    ],
    "profile_id": PROFILE_ID,
    "required_staged_inputs": list(REQUIRED_PROJECTED_INPUT_PATHS),
    "version": "generated_overlay_schema_v1",
}
OVERLAY_SCHEMA_BYTES = _canonical_json_bytes(OVERLAY_SCHEMA)


def _metadata_entry(name: str, path: str, payload: bytes) -> dict[str, Any]:
    return {
        "name": name,
        "path": path,
        "kind": "file",
        "mode": "0644",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "projection": "metadata",
    }


QUERY_ANALYZER_CONTRACT_BYTES_SHA256 = hashlib.sha256(
    QUERY_ANALYZER_CONTRACT_BYTES
).hexdigest()
QUERY_ANALYZER_CONTRACT_SHA256 = QUERY_ANALYZER_CONTRACT_BYTES_SHA256
OVERLAY_SCHEMA_SHA256 = hashlib.sha256(OVERLAY_SCHEMA_BYTES).hexdigest()
REGISTRY_PATCH_CONTRACT_SHA256 = hashlib.sha256(
    REGISTRY_PATCH_CONTRACT_BYTES
).hexdigest()
QUERY_ANALYZER_CONTRACT_ENTRY = _metadata_entry(
    QUERY_ANALYZER_CONTRACT_NAME,
    QUERY_ANALYZER_CONTRACT_PATH,
    QUERY_ANALYZER_CONTRACT_BYTES,
)
OVERLAY_SCHEMA_ENTRY = _metadata_entry(
    OVERLAY_SCHEMA_NAME, OVERLAY_SCHEMA_PATH, OVERLAY_SCHEMA_BYTES
)
REGISTRY_PATCH_CONTRACT_ENTRY = _metadata_entry(
    REGISTRY_PATCH_CONTRACT_NAME,
    REGISTRY_PATCH_CONTRACT_PATH,
    REGISTRY_PATCH_CONTRACT_BYTES,
)

APPROVED_RUNNER_IMAGE_DIGEST = (
    "sha256:" + hashlib.sha256(b"skillopt-runner-image-v1\n").hexdigest()
)
APPROVED_RUNNER_SBOM_SHA256 = hashlib.sha256(
    b"cyclonedx:skillopt-runner-v1\n"
).hexdigest()
APPROVED_RUNNER_INTERPRETER = {
    "path": CANONICAL_PYTHON_INTERPRETER,
    "python_version": "3.11.9",
    "sha256": hashlib.sha256(b'#!/bin/sh\nexec python3 "$@"\n').hexdigest(),
}

MAX_CATALOG_JSON_BYTES = 1_048_576

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA256_IDENTITY_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ARTIFACT_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_PYTHON_PATCH_RE = re.compile(r"^3\.\d+\.\d+$")
_MODES = ("hard", "mixed", "soft")
_FILE_MODES = {"0644", "0755"}
_UNRESOLVED_CODES = (
    "custody",
    "full_dependency_lock",
    "image_digest",
    "overlay_manifest",
    "staging_manifest",
    "tested_patch",
)

EXPECTED_EVIDENCE_CEILING: tuple[dict[str, str], ...] = (
    {
        "code": "custody",
        "level": "evidence_ceiling",
        "message": "Same-domain custody evidence is unresolved.",
    },
    {
        "code": "full_dependency_lock",
        "level": "evidence_ceiling",
        "message": "A full dependency lock is unresolved.",
    },
    {
        "code": "image_digest",
        "level": "evidence_ceiling",
        "message": "Runner image digest is unresolved.",
    },
    {
        "code": "overlay_manifest",
        "level": "evidence_ceiling",
        "message": "Overlay manifest evidence is unresolved.",
    },
    {
        "code": "staging_manifest",
        "level": "evidence_ceiling",
        "message": "Staging manifest evidence is unresolved.",
    },
    {
        "code": "tested_patch",
        "level": "evidence_ceiling",
        "message": "A tested SkillOpt compatibility patch is unresolved.",
    },
)

_CATALOG_KEYS = {"version", "profiles", "identity"}
_PROFILE_KEYS = {
    "version",
    "profile_id",
    "source_name",
    "source_version",
    "pristine_source_manifest",
    "overlay_manifest",
    "staging_manifest",
    "runner_identity",
    "custody_evidence",
    "train_registry",
    "eval_registry",
    "config",
    "compatibility_modes",
    "outputs",
    "tested_patch",
    "full_dependency_lock",
    "evidence_ceiling",
    "identity",
}
_PRISTINE_KEYS = {
    "version",
    "repo_url",
    "tag_object",
    "peeled_commit",
    "archive_sha256",
    "tree_git_sha1",
    "immutable_object_version",
    "fetched_at",
    "source_authority",
    "files",
    "identity",
}
_OVERLAY_KEYS = {
    "version",
    "profile_id",
    "contract_sha256",
    "schema_sha256",
    "immutable_object_version",
    "logical_files",
    "identity",
}
_STAGING_KEYS = {
    "version",
    "pristine_source_identity",
    "overlay_identity",
    "allowlisted_diff",
    "staged_tree",
    "staged_tree_identity",
    "execution_config",
    "execution_config_identity",
    "train_registry_patch_sha256",
    "eval_registry_patch_sha256",
    "registry_patches",
    "expected_imported_modules",
    "identity",
}
_EXECUTION_CONFIG_KEYS = {
    "relative_config_path",
    "relative_config_base",
    "loader_path",
    "loader_sha256",
    "rendered_config_sha256",
    "compatibility_modes",
    "train_out_root",
    "eval_out_root",
    "candidate_path",
    "train_argv",
    "train_argv_identity",
    "eval_argv",
    "eval_argv_identity",
    "num_epochs",
    "train_size",
    "batch_size",
    "minibatch_size",
    "merge_batch_size",
    "accumulation",
    "seed",
    "analyst_workers",
    "skill_update_mode",
    "edit_budget",
    "min_edit_budget",
    "lr_scheduler",
    "lr_control_mode",
    "use_slow_update",
    "use_meta_skill",
    "use_skill_aware_reflection",
    "gate_metric",
    "gate_mixed_weight",
    "sel_env_num",
    "test_env_num",
    "eval_test",
    "mock",
    "max_analyst_rounds",
    "failure_only",
    "use_gate",
    "env_name",
    "skill_init",
    "split_mode",
    "split_dir",
    "workers",
}
_EXPECTED_MODULE_KEYS = {"module_path", "file_path", "sha256"}
_RUNNER_KEYS = {
    "version",
    "staging_identity",
    "image_ref",
    "image_digest",
    "python_version",
    "interpreter_path",
    "interpreter_sha256",
    "dependency_lock_sha256",
    "sbom_sha256",
    "build_provenance_sha256",
    "image_inventory",
    "verifier_id",
    "verifier_version",
    "identity",
}
_CUSTODY_KEYS = {
    "version",
    "subject_runner_identity",
    "issuer_workload",
    "issued_at",
    "expires_at",
    "source_immutable_object_version",
    "overlay_immutable_object_version",
    "retention_mode",
    "acl_snapshot_sha256",
    "runner_image_digest",
    "verifier_id",
    "verifier_version",
    "verified",
    "immutable",
    "identity",
}
_REGISTRY_KEYS = {"path", "sha256"}
_CONFIG_KEYS = {
    "relative_config_path",
    "relative_config_base",
    "loader_path",
    "loader_sha256",
    "base_sha256",
}
_OUTPUT_KEYS = {"train_out_root", "eval_out_root", "candidate_path"}
_TESTED_PATCH_KEYS = {
    "profile_id",
    "staging_identity",
    "runner_identity",
    "report_identity",
    "status",
    "imported_modules",
    "outputs",
    "provider_count",
    "network_count",
    "subprocess_count",
    "config_identity",
    "train_argv_identity",
    "eval_argv_identity",
    "observed_interpreter",
    "verified",
}
_FULL_LOCK_KEYS = {"sha256", "format", "complete"}
_RUNNER_IMAGE_INVENTORY_KEYS = {"image_digest", "sbom_sha256", "interpreters"}
_RUNNER_INTERPRETER_KEYS = {"path", "python_version", "sha256"}


def domain_separated_hash(artifact_version: str, value: Any) -> str:
    """Hash a JSON value under the SkillOpt artifact-version domain."""

    if not isinstance(artifact_version, str) or not _ARTIFACT_VERSION_RE.fullmatch(
        artifact_version
    ):
        raise ValidationError(
            "artifact_version must match the strict artifact-version syntax"
        )
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    digest = hashlib.sha256(
        b"skillopt:" + artifact_version.encode("ascii") + b"\x00" + encoded
    ).hexdigest()
    return f"sha256:{digest}"


def seal_identity_artifact(
    payload: Mapping[str, Any], artifact_version: str | None = None
) -> dict[str, Any]:
    """Return a canonical copy of ``payload`` with a verified identity seal."""

    _require_mapping(payload, "payload")
    version = (
        artifact_version if artifact_version is not None else payload.get("version")
    )
    if not isinstance(version, str) or not version:
        raise ValidationError("artifact_version must be provided")
    if payload.get("version") != version:
        raise ValidationError("payload.version must equal artifact_version")
    without_identity = {
        key: value for key, value in payload.items() if key != "identity"
    }
    canonical = _canonicalize(without_identity)
    canonical["identity"] = domain_separated_hash(version, canonical)
    return canonical


def manifest_tree_identity(
    files: Iterable[Mapping[str, Any]], artifact_version: str = STAGING_MANIFEST_VERSION
) -> str:
    return domain_separated_hash(
        f"{artifact_version}:file_tree", {"files": validate_file_entries(files)}
    )


def validate_posix_relative_path(value: Any, field: str = "path") -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    if value == "":
        raise ValidationError(f"{field} must not be empty")
    if "\x00" in value:
        raise ValidationError(f"{field} must not contain NUL")
    if "\\" in value:
        raise ValidationError(f"{field} must use POSIX separators")
    normalized = unicodedata.normalize("NFC", value)
    if normalized != value:
        raise ValidationError(f"{field} must be NFC normalized")
    if any(segment in {"", ".", ".."} for segment in value.split("/")):
        raise ValidationError(f"{field} must not contain empty or dot segments")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValidationError(f"{field} must be relative")
    if value in {".", ".."} or any(part in {"", ".", ".."} for part in path.parts):
        raise ValidationError(f"{field} must not contain dot segments")
    return value


def validate_posix_absolute_path(value: Any, field: str = "path") -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValidationError(f"{field} must be an absolute POSIX path")
    if "\x00" in value or "\\" in value or unicodedata.normalize("NFC", value) != value:
        raise ValidationError(f"{field} must be a normalized absolute POSIX path")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts[1:]):
        raise ValidationError(f"{field} must not contain empty or dot segments")
    return value


def validate_file_entries(entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(entries, (str, bytes)) or not isinstance(entries, Iterable):
        raise ValidationError("files must be a list")
    normalized: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    seen_folded: set[str] = set()
    for index, entry in enumerate(entries):
        _require_mapping(entry, f"files[{index}]")
        _exact_keys(
            entry, {"path", "kind", "mode", "size_bytes", "sha256"}, f"files[{index}]"
        )
        path = validate_posix_relative_path(entry["path"], f"files[{index}].path")
        folded = unicodedata.normalize("NFC", path).casefold()
        if path in seen_paths:
            raise ValidationError(f"duplicate file path: {path}")
        if folded in seen_folded:
            raise ValidationError(f"NFC/casefold path collision: {path}")
        if entry["kind"] != "file":
            raise ValidationError(f"files[{index}].kind must be file")
        if entry["mode"] not in _FILE_MODES:
            raise ValidationError(f"files[{index}].mode must be 0644 or 0755")
        if type(entry["size_bytes"]) is not int or entry["size_bytes"] < 0:
            raise ValidationError(
                f"files[{index}].size_bytes must be a nonnegative int"
            )
        _require_sha256(entry["sha256"], f"files[{index}].sha256")
        seen_paths.add(path)
        seen_folded.add(folded)
        normalized.append(
            {
                "path": path,
                "kind": "file",
                "mode": entry["mode"],
                "size_bytes": entry["size_bytes"],
                "sha256": entry["sha256"],
            }
        )
    return sorted(normalized, key=lambda item: item["path"])


def _validate_logical_file_entries(
    entries: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(entries, (str, bytes)) or not isinstance(entries, Iterable):
        raise ValidationError("logical_files must be a list")
    normalized: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    file_entries: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        _require_mapping(entry, f"logical_files[{index}]")
        _exact_keys(
            entry,
            {"name", "path", "kind", "mode", "size_bytes", "sha256", "projection"},
            f"logical_files[{index}]",
        )
        name = _require_nonempty_string(entry["name"], f"logical_files[{index}].name")
        if name in seen_names:
            raise ValidationError(f"duplicate logical file name: {name}")
        seen_names.add(name)
        file_entry = {
            "path": entry["path"],
            "kind": entry["kind"],
            "mode": entry["mode"],
            "size_bytes": entry["size_bytes"],
            "sha256": entry["sha256"],
        }
        file_entries.append(file_entry)
        if entry["projection"] not in {"metadata", "staged"}:
            raise ValidationError(
                f"logical_files[{index}].projection must be metadata or staged"
            )
        normalized.append(
            {"name": name, **file_entry, "projection": entry["projection"]}
        )
    by_path = {entry["path"]: entry for entry in validate_file_entries(file_entries)}
    for entry in normalized:
        entry.update(by_path[entry["path"]])
    return sorted(normalized, key=lambda item: (item["name"], item["path"]))


class VerifiedManifestLease:
    """Hold verified file descriptors for one immutable caller evidence window."""

    def __init__(
        self,
        root: str | Path,
        manifest: Mapping[str, Any],
        *,
        expected_identity: str,
    ) -> None:
        _require_mapping(manifest, "manifest")
        version = _require_nonempty_string(manifest.get("version"), "manifest.version")
        _require_identity(manifest.get("identity"), "manifest.identity")
        _require_exact(manifest["identity"], expected_identity, "manifest.identity")
        if (
            seal_identity_artifact(manifest, version)["identity"]
            != manifest["identity"]
        ):
            raise ValidationError("manifest identity does not match payload")
        self.root_path = Path(root)
        self.expected = {
            entry["path"]: entry
            for entry in validate_file_entries(_manifest_files(manifest))
        }
        self.expected_directories = _manifest_parent_directories(self.expected)
        self.root_fd = -1
        self.directory_fds: dict[str, int] = {}
        self.directory_stats: dict[str, os.stat_result] = {}
        self.file_fds: dict[str, int] = {}
        self.file_stats: dict[str, os.stat_result] = {}
        self.root_stat: os.stat_result | None = None
        self._active = False
        self._acquire()

    @property
    def active(self) -> bool:
        return self._active

    def __enter__(self) -> VerifiedManifestLease:
        if not self._active:
            raise ValidationError("manifest lease is closed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            if exc_type is None:
                self.verify_live()
        finally:
            self._close_fds()
        return False

    def read_bytes(self, relative: str) -> bytes:
        if not self._active:
            raise ValidationError("manifest lease is closed")
        relative = validate_posix_relative_path(relative)
        if relative not in self.file_fds:
            raise ValidationError(f"path is not covered by manifest lease: {relative}")
        fd = self.file_fds[relative]
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)

    def verify_live(self) -> None:
        if not self._active or self.root_stat is None:
            raise ValidationError("manifest lease is closed")
        try:
            path_root_stat = self.root_path.lstat()
        except OSError as exc:
            raise ValidationError("leased root path no longer resolves") from exc
        current_root_stat = os.fstat(self.root_fd)
        if not _same_inode(path_root_stat, current_root_stat):
            raise ValidationError("leased root was replaced at its path")
        if _stat_changed(self.root_stat, current_root_stat):
            raise ValidationError("leased root changed during evidence window")
        actual_files, actual_directories = _inventory_manifest_tree_at(self.root_fd)
        _require_exact(actual_files, set(self.expected), "leased manifest paths")
        _require_exact(
            actual_directories,
            self.expected_directories,
            "leased manifest directories",
        )
        self._verify_held_directories()
        for relative, entry in self.expected.items():
            held_fd = self.file_fds[relative]
            before = self.file_stats[relative]
            held_stat = os.fstat(held_fd)
            reopened_fd = _open_manifest_file_at(self.root_fd, relative)
            try:
                path_stat = os.fstat(reopened_fd)
            finally:
                os.close(reopened_fd)
            if not _same_inode(held_stat, path_stat):
                raise ValidationError(f"leased manifest path was replaced: {relative}")
            if _stat_changed(before, held_stat):
                raise ValidationError(f"leased manifest file changed: {relative}")
            _require_exact(
                _sha256_fd(held_fd), entry["sha256"], f"leased sha256 {relative}"
            )
        self._verify_held_directories()
        try:
            final_path_root_stat = self.root_path.lstat()
        except OSError as exc:
            raise ValidationError("leased root path no longer resolves") from exc
        final_root_stat = os.fstat(self.root_fd)
        if not _same_inode(final_path_root_stat, final_root_stat):
            raise ValidationError("leased root was replaced at its path")
        if _stat_changed(self.root_stat, final_root_stat):
            raise ValidationError("leased root changed during evidence window")

    def close(self) -> None:
        """Verify one final time, then close; no path claim survives this call."""

        try:
            self.verify_live()
        finally:
            self._close_fds()

    def _acquire(self) -> None:
        try:
            path_stat = self.root_path.lstat()
            if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
                raise ValidationError("root must be a real directory")
            self.root_fd = _open_root_dir(self.root_path)
            self.root_stat = os.fstat(self.root_fd)
            if not _same_inode(path_stat, self.root_stat):
                raise ValidationError("root changed while opening")
            actual_files, actual_directories = _inventory_manifest_tree_at(self.root_fd)
            _require_exact(actual_files, set(self.expected), "manifest paths")
            _require_exact(
                actual_directories,
                self.expected_directories,
                "manifest directories",
            )
            for relative in sorted(
                self.expected_directories, key=lambda path: (path.count("/"), path)
            ):
                parent_fd, name = self._held_parent_and_name(relative)
                directory_fd = _open_manifest_dir_at(parent_fd, name, relative)
                self.directory_fds[relative] = directory_fd
                directory_stat = os.fstat(directory_fd)
                if not stat.S_ISDIR(directory_stat.st_mode):
                    raise ValidationError(
                        f"manifest path is not a directory: {relative}"
                    )
                self.directory_stats[relative] = directory_stat
            for relative, entry in self.expected.items():
                fd = _open_manifest_file_at(self.root_fd, relative)
                self.file_fds[relative] = fd
                fd_stat = os.fstat(fd)
                if not stat.S_ISREG(fd_stat.st_mode):
                    raise ValidationError(f"manifest path is not a file: {relative}")
                _require_exact(
                    f"{stat.S_IMODE(fd_stat.st_mode):04o}",
                    entry["mode"],
                    f"mode {relative}",
                )
                _require_exact(fd_stat.st_size, entry["size_bytes"], f"size {relative}")
                _require_exact(_sha256_fd(fd), entry["sha256"], f"sha256 {relative}")
                self.file_stats[relative] = fd_stat
            self._active = True
        except BaseException:
            self._close_fds()
            raise

    def _held_parent_and_name(self, relative: str) -> tuple[int, str]:
        path = PurePosixPath(relative)
        parent = path.parent.as_posix()
        parent_fd = self.root_fd if parent == "." else self.directory_fds[parent]
        return parent_fd, path.name

    def _verify_held_directories(self) -> None:
        for relative in sorted(
            self.expected_directories, key=lambda path: (path.count("/"), path)
        ):
            held_fd = self.directory_fds[relative]
            before = self.directory_stats[relative]
            held_stat = os.fstat(held_fd)
            parent_fd, name = self._held_parent_and_name(relative)
            reopened_fd = _open_manifest_dir_at(parent_fd, name, relative)
            try:
                path_stat = os.fstat(reopened_fd)
            finally:
                os.close(reopened_fd)
            if not _same_inode(held_stat, path_stat):
                raise ValidationError(
                    f"leased manifest directory was replaced: {relative}"
                )
            if _stat_changed(before, held_stat):
                raise ValidationError(f"leased manifest directory changed: {relative}")

    def _close_fds(self) -> None:
        for fd in self.file_fds.values():
            try:
                os.close(fd)
            except OSError:
                pass
        self.file_fds.clear()
        self.file_stats.clear()
        for relative in sorted(
            self.directory_fds, key=lambda path: (path.count("/"), path), reverse=True
        ):
            try:
                os.close(self.directory_fds[relative])
            except OSError:
                pass
        self.directory_fds.clear()
        self.directory_stats.clear()
        if self.root_fd >= 0:
            try:
                os.close(self.root_fd)
            except OSError:
                pass
        self.root_fd = -1
        self._active = False


def acquire_manifest_tree_lease(
    root: str | Path, manifest: Mapping[str, Any], *, expected_identity: str
) -> VerifiedManifestLease:
    """Low-level explicit-anchor API; production callers should use trusted wrappers."""

    return VerifiedManifestLease(root, manifest, expected_identity=expected_identity)


def verify_manifest_tree(
    root: str | Path, manifest: Mapping[str, Any], *, expected_identity: str
) -> None:
    """Perform immediate verification only; no mutable-path claim survives return."""

    lease = acquire_manifest_tree_lease(
        root, manifest, expected_identity=expected_identity
    )
    lease.close()


def acquire_approved_source_tree_lease(
    root: str | Path, pristine_manifest: Mapping[str, Any]
) -> VerifiedManifestLease:
    """Verify source bytes against the compiled approved inventory trust root."""

    validated = validate_pristine_source_manifest(pristine_manifest)
    _require_exact(
        APPROVED_SOURCE_INVENTORY["identity"],
        APPROVED_SOURCE_INVENTORY_IDENTITY,
        "approved source inventory trust root",
    )
    return VerifiedManifestLease(
        root, validated, expected_identity=validated["identity"]
    )


def acquire_diagnostic_overlay_tree_lease(
    root: str | Path,
    profile: Mapping[str, Any],
    *,
    custody_as_of: datetime | str | None = None,
) -> VerifiedManifestLease:
    """Acquire a structurally validated overlay lease for diagnostic evidence only."""

    validated = validate_compatibility_profile(profile, custody_as_of=custody_as_of)
    overlay = validated["overlay_manifest"]
    if overlay is None:
        raise ValidationError("diagnostic overlay lease requires overlay_manifest")
    return VerifiedManifestLease(root, overlay, expected_identity=overlay["identity"])


def acquire_diagnostic_staging_tree_lease(
    root: str | Path,
    profile: Mapping[str, Any],
    *,
    custody_as_of: datetime | str | None = None,
) -> VerifiedManifestLease:
    """Acquire a structurally validated staged-tree lease for diagnostics only."""

    validated = validate_compatibility_profile(profile, custody_as_of=custody_as_of)
    staging = validated["staging_manifest"]
    if staging is None:
        raise ValidationError("diagnostic staging lease requires staging_manifest")
    lease = VerifiedManifestLease(root, staging, expected_identity=staging["identity"])
    try:
        _validate_canonical_staged_bytes(lease, staging["execution_config"])
    except BaseException:
        lease._close_fds()
        raise
    return lease


def acquire_trusted_overlay_tree_lease(
    root: str | Path, profile: Mapping[str, Any]
) -> VerifiedManifestLease:
    """Deny production overlay custody until Phase 0 external approval exists."""

    require_compatibility_ready(profile)


def acquire_trusted_staging_tree_lease(
    root: str | Path, profile: Mapping[str, Any]
) -> VerifiedManifestLease:
    """Deny production staged-tree custody until Phase 0 external approval exists."""

    require_compatibility_ready(profile)


def verify_query_analyzer_source(path: str | Path) -> None:
    source_path = Path(path)
    _require_exact(
        source_path.as_posix().endswith(QUERY_ANALYZER_SOURCE_PATH), True, "source path"
    )
    _require_exact(
        hashlib.sha256(source_path.read_bytes()).hexdigest(),
        QUERY_ANALYZER_SOURCE_SHA256,
        "QueryAnalyzer production source sha256",
    )


def validate_pristine_source_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    _require_mapping(value, "pristine_source_manifest")
    _exact_keys(value, _PRISTINE_KEYS, "pristine_source_manifest")
    if value["version"] != PRISTINE_SOURCE_MANIFEST_VERSION:
        raise ValidationError("pristine_source_manifest.version is unsupported")
    if value["repo_url"] != REPO_URL:
        raise ValidationError("pristine_source_manifest.repo_url is not approved")
    _require_exact(value["tag_object"], APPROVED_TAG_OBJECT, "tag_object")
    _require_exact(value["peeled_commit"], APPROVED_PEELED_COMMIT, "peeled_commit")
    _require_exact(value["archive_sha256"], APPROVED_ARCHIVE_SHA256, "archive_sha256")
    _require_exact(value["tree_git_sha1"], APPROVED_TREE_GIT_SHA1, "tree_git_sha1")
    _require_exact(
        value["immutable_object_version"],
        SOURCE_IMMUTABLE_OBJECT_VERSION,
        "immutable_object_version",
    )
    _require_utc_timestamp(value["fetched_at"], "fetched_at")
    _require_exact(value["source_authority"], SOURCE_AUTHORITY, "source_authority")
    files = validate_file_entries(value["files"])
    _require_approved_files(files, "pristine_source_manifest.files")
    normalized = dict(value)
    normalized["files"] = files
    return _verify_identity(normalized, PRISTINE_SOURCE_MANIFEST_VERSION)


def validate_overlay_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    _require_mapping(value, "overlay_manifest")
    _exact_keys(value, _OVERLAY_KEYS, "overlay_manifest")
    if value["version"] != OVERLAY_MANIFEST_VERSION:
        raise ValidationError("overlay_manifest.version is unsupported")
    _require_exact(value["profile_id"], PROFILE_ID, "overlay_manifest.profile_id")
    _require_exact(
        value["immutable_object_version"],
        OVERLAY_IMMUTABLE_OBJECT_VERSION,
        "overlay_manifest.immutable_object_version",
    )
    logical_files = _validate_logical_file_entries(value["logical_files"])
    by_name = {entry["name"]: entry for entry in logical_files}
    if QUERY_ANALYZER_CONTRACT_NAME not in by_name:
        raise ValidationError(
            "overlay_manifest must include the named product contract"
        )
    if OVERLAY_SCHEMA_NAME not in by_name:
        raise ValidationError("overlay_manifest must include the named overlay schema")
    if REGISTRY_PATCH_CONTRACT_NAME not in by_name:
        raise ValidationError(
            "overlay_manifest must include the registry patch contract"
        )
    _require_exact(
        by_name[QUERY_ANALYZER_CONTRACT_NAME],
        QUERY_ANALYZER_CONTRACT_ENTRY,
        "overlay_manifest canonical product contract",
    )
    _require_exact(
        by_name[OVERLAY_SCHEMA_NAME],
        OVERLAY_SCHEMA_ENTRY,
        "overlay_manifest canonical schema",
    )
    _require_exact(
        by_name[REGISTRY_PATCH_CONTRACT_NAME],
        REGISTRY_PATCH_CONTRACT_ENTRY,
        "overlay_manifest canonical registry patch contract",
    )
    _require_exact(
        value["contract_sha256"],
        QUERY_ANALYZER_CONTRACT_SHA256,
        "overlay_manifest.contract_sha256",
    )
    _require_exact(
        value["schema_sha256"],
        OVERLAY_SCHEMA_SHA256,
        "overlay_manifest.schema_sha256",
    )
    normalized = dict(value)
    normalized["logical_files"] = logical_files
    return _verify_identity(normalized, OVERLAY_MANIFEST_VERSION)


def validate_staging_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    _require_mapping(value, "staging_manifest")
    _exact_keys(value, _STAGING_KEYS, "staging_manifest")
    if value["version"] != STAGING_MANIFEST_VERSION:
        raise ValidationError("staging_manifest.version is unsupported")
    _require_identity(
        value["pristine_source_identity"], "staging_manifest.pristine_source_identity"
    )
    _require_identity(value["overlay_identity"], "staging_manifest.overlay_identity")
    allowlisted_diff = _validate_allowlisted_diff(value["allowlisted_diff"])
    staged_tree = validate_file_entries(value["staged_tree"])
    expected_tree_identity = manifest_tree_identity(staged_tree)
    _require_exact(
        value["staged_tree_identity"],
        expected_tree_identity,
        "staging_manifest.staged_tree_identity",
    )
    execution_config = _validate_execution_config(value["execution_config"])
    execution_identity = domain_separated_hash(
        f"{STAGING_MANIFEST_VERSION}:execution_config", execution_config
    )
    _require_exact(
        value["execution_config_identity"],
        execution_identity,
        "staging_manifest.execution_config_identity",
    )
    _require_nonzero_sha256(
        value["train_registry_patch_sha256"],
        "staging_manifest.train_registry_patch_sha256",
    )
    _require_nonzero_sha256(
        value["eval_registry_patch_sha256"],
        "staging_manifest.eval_registry_patch_sha256",
    )
    expected_registry_patches = [
        {"path": path, **dict(REGISTRY_PATCH_CONTRACT["patches"][path])}
        for path in REGISTRY_PATCH_PATHS
    ]
    _require_exact(
        value["registry_patches"],
        expected_registry_patches,
        "staging_manifest.registry_patches",
    )
    expected_modules = _validate_expected_modules(value["expected_imported_modules"])
    normalized = dict(value)
    normalized["allowlisted_diff"] = allowlisted_diff
    normalized["staged_tree"] = staged_tree
    normalized["execution_config"] = execution_config
    normalized["registry_patches"] = expected_registry_patches
    normalized["expected_imported_modules"] = expected_modules
    return _verify_identity(normalized, STAGING_MANIFEST_VERSION)


def validate_runner_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    _require_mapping(value, "runner_identity")
    _exact_keys(value, _RUNNER_KEYS, "runner_identity")
    if value["version"] != RUNNER_IDENTITY_VERSION:
        raise ValidationError("runner_identity.version is unsupported")
    _require_identity(value["staging_identity"], "runner_identity.staging_identity")
    image_ref = _require_nonempty_string(
        value["image_ref"], "runner_identity.image_ref"
    )
    image_digest = _require_image_digest(
        value["image_digest"], "runner_identity.image_digest"
    )
    _require_exact(
        image_digest,
        APPROVED_RUNNER_IMAGE_DIGEST,
        "runner_identity.image_digest",
    )
    if image_ref.lower() in {"scratch", "none", "null"}:
        raise ValidationError(
            "runner_identity.image_ref must be a concrete image reference"
        )
    if "@" not in image_ref or image_ref.rsplit("@", 1)[1] != image_digest:
        raise ValidationError(
            "runner_identity.image_ref must be pinned to image_digest"
        )
    _require_python_patch(value["python_version"], "runner_identity.python_version")
    _require_exact(
        value["interpreter_path"],
        CANONICAL_PYTHON_INTERPRETER,
        "runner_identity.interpreter_path",
    )
    _require_exact(
        value["interpreter_path"],
        TRAIN_ARGV[0],
        "runner_identity.interpreter_path",
    )
    _require_exact(
        value["interpreter_path"],
        EVAL_ARGV[0],
        "runner_identity.interpreter_path",
    )
    _require_exact(
        value["interpreter_sha256"],
        APPROVED_RUNNER_INTERPRETER["sha256"],
        "runner_identity.interpreter_sha256",
    )
    _require_nonzero_sha256(
        value["dependency_lock_sha256"], "runner_identity.dependency_lock_sha256"
    )
    _require_exact(
        value["sbom_sha256"],
        APPROVED_RUNNER_SBOM_SHA256,
        "runner_identity.sbom_sha256",
    )
    _require_nonzero_sha256(
        value["build_provenance_sha256"], "runner_identity.build_provenance_sha256"
    )
    _require_nonempty_string(value["verifier_id"], "runner_identity.verifier_id")
    _require_nonempty_string(
        value["verifier_version"], "runner_identity.verifier_version"
    )
    inventory = _validate_runner_image_inventory(value["image_inventory"])
    _require_exact(
        inventory["image_digest"], image_digest, "image_inventory.image_digest"
    )
    _require_exact(
        inventory["sbom_sha256"], value["sbom_sha256"], "image_inventory.sbom_sha256"
    )
    _require_exact(
        inventory["interpreters"],
        [APPROVED_RUNNER_INTERPRETER],
        "image_inventory.interpreters",
    )
    normalized = dict(value)
    normalized["image_inventory"] = inventory
    return _verify_identity(normalized, RUNNER_IDENTITY_VERSION)


def validate_same_domain_custody_evidence(
    value: Mapping[str, Any], *, as_of: datetime | str | None = None
) -> dict[str, Any]:
    _require_mapping(value, "custody_evidence")
    _exact_keys(value, _CUSTODY_KEYS, "custody_evidence")
    if value["version"] != SAME_DOMAIN_CUSTODY_EVIDENCE_VERSION:
        raise ValidationError("custody_evidence.version is unsupported")
    _require_identity(
        value["subject_runner_identity"], "custody_evidence.subject_runner_identity"
    )
    _require_nonempty_string(
        value["issuer_workload"], "custody_evidence.issuer_workload"
    )
    _require_utc_timestamp(value["issued_at"], "custody_evidence.issued_at")
    _require_utc_timestamp(value["expires_at"], "custody_evidence.expires_at")
    issued = _parse_utc(value["issued_at"])
    expires = _parse_utc(value["expires_at"])
    if issued >= expires:
        raise ValidationError("custody_evidence.issued_at must be before expires_at")
    if expires - issued > timedelta(seconds=86_400):
        raise ValidationError("custody_evidence TTL must be at most 86400 seconds")
    current = _as_utc(as_of) if as_of is not None else datetime.now(timezone.utc)
    if issued > current or current >= expires:
        raise ValidationError("custody_evidence is not valid at as_of")
    _require_exact(
        value["source_immutable_object_version"],
        SOURCE_IMMUTABLE_OBJECT_VERSION,
        "custody_evidence.source_immutable_object_version",
    )
    _require_exact(
        value["overlay_immutable_object_version"],
        OVERLAY_IMMUTABLE_OBJECT_VERSION,
        "custody_evidence.overlay_immutable_object_version",
    )
    _require_exact(
        value["retention_mode"],
        "governance-compliance",
        "custody_evidence.retention_mode",
    )
    _require_nonzero_sha256(
        value["acl_snapshot_sha256"], "custody_evidence.acl_snapshot_sha256"
    )
    _require_image_digest(
        value["runner_image_digest"], "custody_evidence.runner_image_digest"
    )
    _require_nonempty_string(value["verifier_id"], "custody_evidence.verifier_id")
    _require_nonempty_string(
        value["verifier_version"], "custody_evidence.verifier_version"
    )
    if value["issuer_workload"] == value["verifier_id"]:
        raise ValidationError("custody_evidence issuer must differ from verifier")
    if value["verified"] is not True:
        raise ValidationError("custody_evidence.verified must be true")
    if value["immutable"] is not True:
        raise ValidationError("custody_evidence.immutable must be true")
    return _verify_identity(dict(value), SAME_DOMAIN_CUSTODY_EVIDENCE_VERSION)


def validate_compatibility_profile(
    value: Mapping[str, Any], *, custody_as_of: datetime | str | None = None
) -> dict[str, Any]:
    _require_mapping(value, "profile")
    _exact_keys(value, _PROFILE_KEYS, "profile")
    if value["version"] != PROFILE_CATALOG_VERSION:
        raise ValidationError("profile.version is unsupported")
    _require_exact(value["profile_id"], PROFILE_ID, "profile.profile_id")
    _require_exact(value["source_name"], "Microsoft SkillOpt", "profile.source_name")
    _require_exact(value["source_version"], SOURCE_VERSION, "profile.source_version")

    pristine = validate_pristine_source_manifest(value["pristine_source_manifest"])
    overlay = None
    if value["overlay_manifest"] is not None:
        overlay = validate_overlay_manifest(value["overlay_manifest"])

    staging = None
    if value["staging_manifest"] is not None:
        if overlay is None:
            raise ValidationError("staging_manifest requires overlay_manifest")
        staging = validate_staging_manifest(value["staging_manifest"])
        _require_exact(
            staging["pristine_source_identity"],
            pristine["identity"],
            "staging_manifest.pristine_source_identity",
        )
        _require_exact(
            staging["overlay_identity"],
            overlay["identity"],
            "staging_manifest.overlay_identity",
        )

    train_registry = _validate_registry(
        value["train_registry"], "train_registry", "scripts/train.py"
    )
    eval_registry = _validate_registry(
        value["eval_registry"], "eval_registry", "scripts/eval_only.py"
    )
    _require_exact(
        train_registry["sha256"], TRAIN_REGISTRY_SHA256, "train_registry.sha256"
    )
    _require_exact(
        eval_registry["sha256"], EVAL_REGISTRY_SHA256, "eval_registry.sha256"
    )
    config = _validate_config(value["config"])
    modes = _validate_modes(value["compatibility_modes"])
    outputs = _validate_outputs(value["outputs"])
    evidence_ceiling = _validate_evidence_ceiling(value["evidence_ceiling"])
    full_lock = _validate_nullable_full_lock(value["full_dependency_lock"])

    runner = None
    if value["runner_identity"] is not None:
        if staging is None:
            raise ValidationError("runner_identity requires staging_manifest")
        runner = validate_runner_identity(value["runner_identity"])
        _require_exact(
            runner["staging_identity"],
            staging["identity"],
            "runner_identity.staging_identity",
        )
        if full_lock is None:
            raise ValidationError("runner_identity requires full_dependency_lock")
        _require_exact(
            runner["dependency_lock_sha256"],
            full_lock["sha256"],
            "runner_identity.dependency_lock_sha256",
        )

    tested_patch = _validate_nullable_tested_patch(
        value["tested_patch"], staging, runner
    )

    custody = None
    if value["custody_evidence"] is not None:
        if runner is None:
            raise ValidationError("custody_evidence requires runner_identity")
        custody = validate_same_domain_custody_evidence(
            value["custody_evidence"], as_of=custody_as_of
        )
        _require_exact(
            custody["subject_runner_identity"],
            runner["identity"],
            "custody_evidence.subject_runner_identity",
        )
        _require_exact(
            custody["runner_image_digest"],
            runner["image_digest"],
            "custody_evidence.runner_image_digest",
        )
        _require_exact(
            custody["verifier_id"],
            runner["verifier_id"],
            "custody_evidence.verifier_id",
        )
        _require_exact(
            custody["verifier_version"],
            runner["verifier_version"],
            "custody_evidence.verifier_version",
        )

    _require_exact(
        config["relative_config_path"],
        PROFILE_CONFIG_PATH,
        "config.relative_config_path",
    )
    _require_exact(
        config["relative_config_base"],
        PROFILE_CONFIG_BASE,
        "config.relative_config_base",
    )
    _require_exact(config["loader_path"], LOADER_PATH, "config.loader_path")
    _require_exact(config["loader_sha256"], CONFIG_SHA256, "config.loader_sha256")
    _require_exact(config["base_sha256"], BASE_CONFIG_SHA256, "config.base_sha256")
    _require_exact(modes, list(_MODES), "compatibility_modes")
    _require_exact(outputs["train_out_root"], TRAIN_OUT_ROOT, "outputs.train_out_root")
    _require_exact(outputs["eval_out_root"], EVAL_OUT_ROOT, "outputs.eval_out_root")
    _require_exact(outputs["candidate_path"], CANDIDATE_PATH, "outputs.candidate_path")
    if not outputs["candidate_path"].startswith(outputs["train_out_root"] + "/"):
        raise ValidationError(
            "outputs.candidate_path must be derived from train_out_root"
        )
    if staging is not None:
        _require_exact(
            staging["execution_config"],
            {
                "relative_config_path": PROFILE_CONFIG_PATH,
                "relative_config_base": PROFILE_CONFIG_BASE,
                "loader_path": LOADER_PATH,
                "loader_sha256": CONFIG_SHA256,
                "rendered_config_sha256": staging["execution_config"][
                    "rendered_config_sha256"
                ],
                "compatibility_modes": list(_MODES),
                "train_out_root": TRAIN_OUT_ROOT,
                "eval_out_root": EVAL_OUT_ROOT,
                "candidate_path": CANDIDATE_PATH,
                "train_argv": TRAIN_ARGV,
                "train_argv_identity": domain_separated_hash(
                    f"{STAGING_MANIFEST_VERSION}:train_argv", TRAIN_ARGV
                ),
                "eval_argv": EVAL_ARGV,
                "eval_argv_identity": domain_separated_hash(
                    f"{STAGING_MANIFEST_VERSION}:eval_argv", EVAL_ARGV
                ),
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
            },
            "staging_manifest.execution_config",
        )
        _validate_staging_relations(pristine, overlay, staging)

    unresolved_codes = _derived_unresolved_codes(
        overlay=overlay,
        staging=staging,
        runner=runner,
        custody=custody,
        tested_patch=tested_patch,
        full_lock=full_lock,
    )
    expected_codes = [diagnostic["code"] for diagnostic in evidence_ceiling]
    if unresolved_codes != expected_codes:
        raise ValidationError(
            "profile.evidence_ceiling must exactly match unresolved artifacts"
        )

    normalized = dict(value)
    normalized["pristine_source_manifest"] = pristine
    normalized["overlay_manifest"] = overlay
    normalized["staging_manifest"] = staging
    normalized["runner_identity"] = runner
    normalized["custody_evidence"] = custody
    normalized["train_registry"] = train_registry
    normalized["eval_registry"] = eval_registry
    normalized["config"] = config
    normalized["compatibility_modes"] = modes
    normalized["outputs"] = outputs
    normalized["tested_patch"] = tested_patch
    normalized["full_dependency_lock"] = full_lock
    normalized["evidence_ceiling"] = evidence_ceiling
    return _verify_identity(normalized, PROFILE_CATALOG_VERSION)


def compatibility_readiness_errors(
    profile: Mapping[str, Any], *, custody_as_of: datetime | str | None = None
) -> list[str]:
    validated = validate_compatibility_profile(profile, custody_as_of=custody_as_of)
    derived = _derived_unresolved_codes(
        overlay=validated["overlay_manifest"],
        staging=validated["staging_manifest"],
        runner=validated["runner_identity"],
        custody=validated["custody_evidence"],
        tested_patch=validated["tested_patch"],
        full_lock=validated["full_dependency_lock"],
    )
    diagnostics = {
        diagnostic["code"]: f"{diagnostic['code']}: {diagnostic['message']}"
        for diagnostic in validated["evidence_ceiling"]
    }
    errors = [diagnostics[code] for code in derived]
    if not errors:
        errors.append(PHASE0_READY_ERROR)
    return errors


def require_compatibility_ready(
    profile: Mapping[str, Any], *, custody_as_of: datetime | str | None = None
) -> NoReturn:
    validated = validate_compatibility_profile(profile, custody_as_of=custody_as_of)
    errors = compatibility_readiness_errors(validated, custody_as_of=custody_as_of)
    raise ValidationError("; ".join(errors))


def validate_profile_catalog(
    value: Mapping[str, Any], *, custody_as_of: datetime | str | None = None
) -> dict[str, Any]:
    _require_mapping(value, "catalog")
    _exact_keys(value, _CATALOG_KEYS, "catalog")
    if value["version"] != PROFILE_CATALOG_VERSION:
        raise ValidationError("catalog.version is unsupported")
    _require_mapping(value["profiles"], "catalog.profiles")
    if set(value["profiles"]) != {PROFILE_ID}:
        raise ValidationError(
            "catalog.profiles must contain exactly the approved SkillOpt profile"
        )
    profile = validate_compatibility_profile(
        value["profiles"][PROFILE_ID], custody_as_of=custody_as_of
    )
    normalized = {
        "version": PROFILE_CATALOG_VERSION,
        "profiles": {PROFILE_ID: profile},
        "identity": value["identity"],
    }
    return _verify_identity(normalized, PROFILE_CATALOG_VERSION)


def load_compatibility_catalog(
    path: str | Path, *, custody_as_of: datetime | str | None = None
) -> dict[str, Any]:
    catalog_path = Path(path)
    raw = catalog_path.read_bytes()
    if len(raw) > MAX_CATALOG_JSON_BYTES:
        raise ValidationError("compatibility catalog JSON is too large")
    try:
        text = raw.decode("utf-8")
        decoded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as exc:
        raise ValidationError("compatibility catalog must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid compatibility catalog JSON: {exc}") from exc
    return validate_profile_catalog(decoded, custody_as_of=custody_as_of)


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if isinstance(value, tuple):
        return _canonicalize(list(value))
    return value


def _verify_identity(value: Mapping[str, Any], artifact_version: str) -> dict[str, Any]:
    identity = value.get("identity")
    _require_identity(identity, "identity")
    sealed = seal_identity_artifact(value, artifact_version)
    if identity != sealed["identity"]:
        raise ValidationError(f"{artifact_version} identity does not match payload")
    return sealed


def _manifest_files(manifest: Mapping[str, Any]) -> Any:
    if "logical_files" in manifest:
        return [
            {
                field: entry[field]
                for field in ("path", "kind", "mode", "size_bytes", "sha256")
            }
            for entry in manifest["logical_files"]
        ]
    for key in ("files", "staged_tree"):
        if key in manifest:
            return manifest[key]
    raise ValidationError("manifest must contain files, logical_files, or staged_tree")


def _open_root_dir(root: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(root, flags)
    except OSError as exc:
        raise ValidationError("root must be a real directory") from exc


def _open_manifest_file_at(root_fd: int, relative: str) -> int:
    parts = PurePosixPath(relative).parts
    parent_fds: list[int] = []
    current_fd = root_fd
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    file_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        file_flags |= os.O_NOFOLLOW
    try:
        for part in parts[:-1]:
            parent_fd = os.open(part, directory_flags, dir_fd=current_fd)
            parent_fds.append(parent_fd)
            current_fd = parent_fd
        return os.open(parts[-1], file_flags, dir_fd=current_fd)
    except FileNotFoundError as exc:
        raise ValidationError(f"missing manifest file: {relative}") from exc
    except NotADirectoryError as exc:
        raise ValidationError(
            f"manifest parent is not a directory: {relative}"
        ) from exc
    except OSError as exc:
        raise ValidationError(f"cannot safely open manifest file: {relative}") from exc
    finally:
        for parent_fd in reversed(parent_fds):
            os.close(parent_fd)


def _manifest_parent_directories(paths: Iterable[str]) -> set[str]:
    directories: set[str] = set()
    for relative in paths:
        parent = PurePosixPath(relative).parent
        while parent.as_posix() != ".":
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def _inventory_manifest_tree_at(root_fd: int) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    _inventory_manifest_dir_at(root_fd, "", files, directories)
    return files, directories


def _inventory_manifest_dir_at(
    directory_fd: int,
    prefix: str,
    files: set[str],
    directories: set[str],
) -> None:
    try:
        names = os.listdir(directory_fd)
    except OSError as exc:
        raise ValidationError("cannot safely list manifest directory") from exc
    for name in sorted(names):
        relative = validate_posix_relative_path(f"{prefix}/{name}" if prefix else name)
        try:
            entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise ValidationError(
                f"manifest tree changed while reading: {relative}"
            ) from exc
        except OSError as exc:
            raise ValidationError(
                f"cannot safely stat manifest path: {relative}"
            ) from exc
        if stat.S_ISLNK(entry_stat.st_mode):
            raise ValidationError(f"unexpected symlink in manifest tree: {relative}")
        if stat.S_ISREG(entry_stat.st_mode):
            files.add(relative)
            continue
        if stat.S_ISDIR(entry_stat.st_mode):
            directories.add(relative)
            child_fd = _open_manifest_dir_at(directory_fd, name, relative)
            try:
                child_fd_stat = os.fstat(child_fd)
                if not _same_inode(entry_stat, child_fd_stat) or not stat.S_ISDIR(
                    child_fd_stat.st_mode
                ):
                    raise ValidationError(
                        f"manifest directory changed while opening: {relative}"
                    )
                _inventory_manifest_dir_at(child_fd, relative, files, directories)
                post_child_stat = os.fstat(child_fd)
                if _stat_changed(child_fd_stat, post_child_stat):
                    raise ValidationError(
                        f"manifest directory changed while reading: {relative}"
                    )
            finally:
                os.close(child_fd)
            continue
        raise ValidationError(f"unexpected special file in manifest tree: {relative}")


def _open_manifest_dir_at(parent_fd: int, name: str, relative: str) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError as exc:
        raise ValidationError(f"missing manifest directory: {relative}") from exc
    except NotADirectoryError as exc:
        raise ValidationError(f"manifest path is not a directory: {relative}") from exc
    except OSError as exc:
        raise ValidationError(
            f"cannot safely open manifest directory: {relative}"
        ) from exc


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _sha256_fd(fd: int) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _stat_changed(before: os.stat_result, after: os.stat_result) -> bool:
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    return any(getattr(before, field) != getattr(after, field) for field in fields)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValidationError(f"nonfinite JSON value is not allowed: {value}")


def _require_mapping(value: Any, field: str) -> None:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{field} must be an object")


def _exact_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValidationError(f"{field} keys mismatch; missing={missing} extra={extra}")


def _require_exact(actual: Any, expected: Any, field: str) -> None:
    if actual != expected:
        raise ValidationError(f"{field} must equal approved value")


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{field} must be a nonempty string")
    return value


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValidationError(f"{field} must be lowercase sha256 hex")
    return value


def _require_nonzero_sha256(value: Any, field: str) -> str:
    digest = _require_sha256(value, field)
    if digest == "0" * 64:
        raise ValidationError(f"{field} must be a nonzero sha256 hex")
    return digest


def _require_git_sha1(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _GIT_SHA1_RE.fullmatch(value):
        raise ValidationError(f"{field} must be lowercase git sha1 hex")
    return value


def _require_identity(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_IDENTITY_RE.fullmatch(value):
        raise ValidationError(f"{field} must be a sha256 identity")
    return value


def _require_image_digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not _IMAGE_DIGEST_RE.fullmatch(value)
        or value == "sha256:" + "0" * 64
    ):
        raise ValidationError(f"{field} must be a nonzero sha256 image digest")
    return value


def _require_python_patch(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _PYTHON_PATCH_RE.fullmatch(value):
        raise ValidationError(f"{field} must be an exact Python patch version")
    return value


def _require_utc_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _UTC_RE.fullmatch(value):
        raise ValidationError(f"{field} must be UTC ISO-8601 with Z")
    _parse_utc(value)
    return value


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _as_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        _require_utc_timestamp(value, "as_of")
        return _parse_utc(value)
    if value.tzinfo is None:
        raise ValidationError("as_of must be timezone-aware")
    return value.astimezone(timezone.utc)


def _require_approved_files(files: Sequence[Mapping[str, Any]], field: str) -> None:
    if list(files) != validate_file_entries(APPROVED_FILE_ENTRIES):
        raise ValidationError(f"{field} must equal approved SkillOpt v0.2.0 file pins")


def _validate_path_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list")
    return sorted(validate_posix_relative_path(item, f"{field}[]") for item in value)


def _validate_allowlisted_diff(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValidationError("allowlisted_diff must be a list")
    normalized: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, record in enumerate(value):
        _require_mapping(record, f"allowlisted_diff[{index}]")
        _exact_keys(
            record,
            {"path", "change", "before_sha256", "after_sha256", "mode"},
            f"allowlisted_diff[{index}]",
        )
        path = validate_posix_relative_path(
            record["path"], f"allowlisted_diff[{index}].path"
        )
        if path in seen_paths:
            raise ValidationError(f"duplicate allowlisted diff path: {path}")
        seen_paths.add(path)
        change = record["change"]
        if change not in {"add", "modify"}:
            raise ValidationError("allowlisted_diff.change must be add or modify")
        before = record["before_sha256"]
        after = record["after_sha256"]
        if before is not None:
            before = _require_nonzero_sha256(
                before, f"allowlisted_diff[{index}].before_sha256"
            )
        if after is not None:
            after = _require_nonzero_sha256(
                after, f"allowlisted_diff[{index}].after_sha256"
            )
        if change == "add" and before is not None:
            raise ValidationError("add diff records must have null before_sha256")
        if change == "modify" and (before is None or after is None):
            raise ValidationError("modify diff records require before and after sha256")
        if change == "add" and after is None:
            raise ValidationError("add diff records require after_sha256")
        if record["mode"] not in _FILE_MODES:
            raise ValidationError("allowlisted_diff.mode must be 0644 or 0755")
        normalized.append(
            {
                "path": path,
                "change": change,
                "before_sha256": before,
                "after_sha256": after,
                "mode": record["mode"],
            }
        )
    return sorted(normalized, key=lambda item: item["path"])


def _validate_modes(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError("compatibility_modes must be a list")
    modes = sorted(value)
    if modes != list(_MODES):
        raise ValidationError("compatibility_modes must be hard/soft/mixed")
    return modes


def _validate_argv(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{field} must be a nonempty list")
    argv = []
    for index, item in enumerate(value):
        argv.append(_require_nonempty_string(item, f"{field}[{index}]"))
    return argv


def _validate_execution_config(value: Any) -> dict[str, Any]:
    _require_mapping(value, "execution_config")
    _exact_keys(value, _EXECUTION_CONFIG_KEYS, "execution_config")
    config_path = validate_posix_relative_path(
        value["relative_config_path"], "relative_config_path"
    )
    config_base = validate_posix_relative_path(
        value["relative_config_base"], "relative_config_base"
    )
    loader_path = validate_posix_relative_path(value["loader_path"], "loader_path")
    loader_sha256 = _require_nonzero_sha256(value["loader_sha256"], "loader_sha256")
    rendered_config_sha256 = _require_nonzero_sha256(
        value["rendered_config_sha256"], "rendered_config_sha256"
    )
    train_out_root = validate_posix_relative_path(
        value["train_out_root"], "train_out_root"
    )
    eval_out_root = validate_posix_relative_path(
        value["eval_out_root"], "eval_out_root"
    )
    candidate_path = validate_posix_relative_path(
        value["candidate_path"], "candidate_path"
    )
    if not candidate_path.startswith(train_out_root + "/"):
        raise ValidationError("candidate_path must be derived from train_out_root")
    train_argv = _validate_argv(value["train_argv"], "train_argv")
    eval_argv = _validate_argv(value["eval_argv"], "eval_argv")
    _require_exact(train_argv, TRAIN_ARGV, "train_argv")
    _require_exact(eval_argv, EVAL_ARGV, "eval_argv")
    _require_exact(train_argv[0], CANONICAL_PYTHON_INTERPRETER, "train_argv[0]")
    _require_exact(eval_argv[0], CANONICAL_PYTHON_INTERPRETER, "eval_argv[0]")
    _require_exact(train_argv[3], config_path, "train_argv config path")
    _require_exact(eval_argv[3], config_path, "eval_argv config path")
    _require_exact(train_argv[5], SPLIT_DIR, "train_argv split_dir")
    _require_exact(eval_argv[9], SPLIT_DIR, "eval_argv split_dir")
    _require_exact(
        value["train_argv_identity"],
        domain_separated_hash(f"{STAGING_MANIFEST_VERSION}:train_argv", train_argv),
        "train_argv_identity",
    )
    _require_exact(
        value["eval_argv_identity"],
        domain_separated_hash(f"{STAGING_MANIFEST_VERSION}:eval_argv", eval_argv),
        "eval_argv_identity",
    )
    _require_exact(value["num_epochs"], 1, "num_epochs")
    _require_exact(value["train_size"], 3, "train_size")
    _require_exact(value["batch_size"], 3, "batch_size")
    _require_exact(value["minibatch_size"], 1, "minibatch_size")
    _require_exact(value["merge_batch_size"], 1, "merge_batch_size")
    _require_exact(value["accumulation"], 1, "accumulation")
    _require_exact(value["seed"], 42, "seed")
    _require_exact(value["analyst_workers"], 1, "analyst_workers")
    _require_exact(value["skill_update_mode"], "patch", "skill_update_mode")
    _require_exact(value["edit_budget"], 1, "edit_budget")
    _require_exact(value["min_edit_budget"], 1, "min_edit_budget")
    _require_exact(value["lr_scheduler"], "constant", "lr_scheduler")
    _require_exact(value["lr_control_mode"], "fixed", "lr_control_mode")
    _require_exact(value["use_slow_update"], False, "use_slow_update")
    _require_exact(value["use_meta_skill"], False, "use_meta_skill")
    _require_exact(
        value["use_skill_aware_reflection"], False, "use_skill_aware_reflection"
    )
    _require_exact(value["gate_metric"], "mixed", "gate_metric")
    _require_exact(value["gate_mixed_weight"], 0.8, "gate_mixed_weight")
    _require_exact(value["sel_env_num"], 2, "sel_env_num")
    _require_exact(value["test_env_num"], 2, "test_env_num")
    _require_exact(value["eval_test"], True, "eval_test")
    _require_exact(value["mock"], True, "mock")
    _require_exact(value["max_analyst_rounds"], 1, "max_analyst_rounds")
    _require_exact(value["failure_only"], True, "failure_only")
    _require_exact(value["use_gate"], True, "use_gate")
    _require_exact(value["env_name"], "jiphyeonjeon_search", "env_name")
    _require_exact(
        value["skill_init"],
        SKILL_INIT_PATH,
        "skill_init",
    )
    _require_exact(value["split_mode"], "split_dir", "split_mode")
    _require_exact(value["split_dir"], SPLIT_DIR, "split_dir")
    _require_exact(value["workers"], 1, "workers")
    return {
        "relative_config_path": config_path,
        "relative_config_base": config_base,
        "loader_path": loader_path,
        "loader_sha256": loader_sha256,
        "rendered_config_sha256": rendered_config_sha256,
        "compatibility_modes": _validate_modes(value["compatibility_modes"]),
        "train_out_root": train_out_root,
        "eval_out_root": eval_out_root,
        "candidate_path": candidate_path,
        "train_argv": train_argv,
        "train_argv_identity": value["train_argv_identity"],
        "eval_argv": eval_argv,
        "eval_argv_identity": value["eval_argv_identity"],
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


def _validate_expected_modules(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValidationError("expected_imported_modules must be a nonempty list")
    normalized = []
    seen: set[tuple[str, str]] = set()
    for index, module in enumerate(value):
        _require_mapping(module, f"expected_imported_modules[{index}]")
        _exact_keys(
            module,
            _EXPECTED_MODULE_KEYS,
            f"expected_imported_modules[{index}]",
        )
        module_path = _require_nonempty_string(
            module["module_path"], f"expected_imported_modules[{index}].module_path"
        )
        file_path = validate_posix_relative_path(
            module["file_path"], f"expected_imported_modules[{index}].file_path"
        )
        digest = _require_nonzero_sha256(
            module["sha256"], f"expected_imported_modules[{index}].sha256"
        )
        identity_key = (module_path, file_path)
        if identity_key in seen:
            raise ValidationError(
                "expected_imported_modules contains duplicate module entries"
            )
        seen.add(identity_key)
        normalized.append(
            {"module_path": module_path, "file_path": file_path, "sha256": digest}
        )
    return sorted(normalized, key=lambda item: (item["module_path"], item["file_path"]))


def _validate_registry(value: Any, field: str, expected_path: str) -> dict[str, str]:
    _require_mapping(value, field)
    _exact_keys(value, _REGISTRY_KEYS, field)
    path = validate_posix_relative_path(value["path"], f"{field}.path")
    _require_exact(path, expected_path, f"{field}.path")
    _require_sha256(value["sha256"], f"{field}.sha256")
    return {"path": path, "sha256": value["sha256"]}


def _validate_config(value: Any) -> dict[str, str]:
    _require_mapping(value, "config")
    _exact_keys(value, _CONFIG_KEYS, "config")
    relative_config_path = validate_posix_relative_path(
        value["relative_config_path"], "config.relative_config_path"
    )
    relative_config_base = validate_posix_relative_path(
        value["relative_config_base"], "config.relative_config_base"
    )
    loader_path = validate_posix_relative_path(
        value["loader_path"], "config.loader_path"
    )
    loader_sha256 = _require_nonzero_sha256(
        value["loader_sha256"], "config.loader_sha256"
    )
    base_sha256 = _require_nonzero_sha256(value["base_sha256"], "config.base_sha256")
    return {
        "relative_config_path": relative_config_path,
        "relative_config_base": relative_config_base,
        "loader_path": loader_path,
        "loader_sha256": loader_sha256,
        "base_sha256": base_sha256,
    }


def _validate_outputs(value: Any) -> dict[str, str]:
    _require_mapping(value, "outputs")
    _exact_keys(value, _OUTPUT_KEYS, "outputs")
    train_out_root = validate_posix_relative_path(
        value["train_out_root"], "outputs.train_out_root"
    )
    eval_out_root = validate_posix_relative_path(
        value["eval_out_root"], "outputs.eval_out_root"
    )
    candidate_path = validate_posix_relative_path(
        value["candidate_path"], "outputs.candidate_path"
    )
    return {
        "train_out_root": train_out_root,
        "eval_out_root": eval_out_root,
        "candidate_path": candidate_path,
    }


def _load_strict_json_bytes(payload: bytes, field: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{field} must be canonical UTF-8 JSON/YAML") from exc


def validate_query_analyzer_contract_bytes(
    payload: bytes, *, production_source: str | Path | None = None
) -> dict[str, Any]:
    if payload != QUERY_ANALYZER_CONTRACT_BYTES:
        raise ValidationError(
            "QueryAnalyzer contract bytes drifted from canonical contract"
        )
    decoded = _load_strict_json_bytes(payload, "QueryAnalyzer contract")
    _require_exact(decoded, QUERY_ANALYZER_CONTRACT, "QueryAnalyzer semantic contract")
    raw_fields = decoded["raw_model_output_v1"]["fields"]
    normalized = decoded["normalized_query_analysis_v1"]
    normalized_fields = normalized["fields"]
    required = {
        "intent",
        "keywords",
        "core_concepts",
        "research_area",
        "improved_query",
        "search_strategy",
        "search_filters",
        "confidence",
        "analysis_details",
        "is_academic",
        "source_queries",
    }
    _require_exact(set(raw_fields), required, "raw_model_output_v1 fields")
    if not required | {"original_query", "error"} == set(normalized_fields):
        raise ValidationError("normalized_query_analysis_v1 fields drifted")
    common_required_fields = {
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
    _require_exact(
        set(normalized["common_required_fields"]),
        common_required_fields,
        "normalized common required fields",
    )
    _require_exact(
        set(normalized["optional_fields"]),
        optional_fields,
        "normalized optional fields",
    )
    _require_exact(
        common_required_fields | optional_fields,
        set(normalized_fields),
        "normalized declared field partition",
    )
    for field in optional_fields:
        _require_exact(
            normalized_fields[field].get("optional"),
            True,
            f"normalized optional field {field}",
        )
    _require_exact(
        raw_fields["is_academic"],
        {
            "default_when_missing": True,
            "normalization": "bool",
            "type": "any_json",
        },
        "raw is_academic semantics",
    )
    raw_source_fields = raw_fields["source_queries"]["fields"]
    _require_exact(
        set(raw_source_fields),
        {"arxiv", "dblp", "google_scholar", "scholar_queries"},
        "raw source_queries fields",
    )
    _require_exact(
        raw_source_fields["scholar_queries"]["alias_of"],
        "google_scholar",
        "raw scholar_queries alias",
    )
    _require_exact(
        raw_source_fields["scholar_queries"]["precedence"],
        "when_present",
        "raw scholar_queries precedence",
    )
    normalized_source_fields = normalized_fields["source_queries"]["fields"]
    _require_exact(
        set(normalized_source_fields),
        {"arxiv", "dblp", "google_scholar", "scholar_queries", "default"},
        "normalized source_queries fields",
    )
    _require_exact(
        normalized_source_fields["scholar_queries"],
        {"max_items": 3, "optional": True, "type": "array[string]"},
        "normalized scholar_queries semantics",
    )
    normalization = decoded["production_normalization_v1"]
    branches = normalization["branches"]
    _require_exact(
        set(branches),
        {
            "empty_query",
            "exception_fallback",
            "no_client_fallback",
            "unified_llm_success",
        },
        "QueryAnalyzer normalization branches",
    )
    expected_branch_keys = {
        "empty_query": (
            common_required_fields,
            common_required_fields,
            optional_fields,
        ),
        "exception_fallback": (
            common_required_fields | optional_fields - {"error"},
            common_required_fields | {"analysis_details"},
            {"error"},
        ),
        "no_client_fallback": (
            common_required_fields | {"analysis_details"},
            common_required_fields | {"analysis_details"},
            optional_fields - {"analysis_details"},
        ),
        "unified_llm_success": (
            common_required_fields
            | {"core_concepts", "research_area", "search_strategy"},
            common_required_fields
            | {"core_concepts", "research_area", "search_strategy"},
            {"analysis_details", "error"},
        ),
    }
    source_query_fields = set(normalized_source_fields)
    for branch_name, (allowed, branch_required, absent) in expected_branch_keys.items():
        branch = branches[branch_name]
        _require_exact(
            set(branch["allowed_keys"]), allowed, f"{branch_name} allowed keys"
        )
        _require_exact(
            set(branch["required_keys"]),
            branch_required,
            f"{branch_name} required keys",
        )
        _require_exact(set(branch["absent_keys"]), absent, f"{branch_name} absent keys")
        _require_exact(
            allowed | absent,
            set(normalized_fields),
            f"{branch_name} complete key partition",
        )
        _require_exact(
            branch_required <= allowed,
            True,
            f"{branch_name} required keys allowed",
        )
        expected_source_allowed = source_query_fields
        expected_source_absent: set[str] = set()
        if branch_name != "unified_llm_success":
            expected_source_allowed = source_query_fields - {"scholar_queries"}
            expected_source_absent = {"scholar_queries"}
        _require_exact(
            set(branch["source_query_allowed_keys"]),
            expected_source_allowed,
            f"{branch_name} source query allowed keys",
        )
        _require_exact(
            set(branch["source_query_required_keys"]),
            expected_source_allowed,
            f"{branch_name} source query required keys",
        )
        _require_exact(
            set(branch["source_query_absent_keys"]),
            expected_source_absent,
            f"{branch_name} source query absent keys",
        )
        _require_exact(
            expected_source_allowed | expected_source_absent,
            source_query_fields,
            f"{branch_name} complete source query key partition",
        )
    _require_exact(
        normalization["scholar_queries"]["alias_precedence"],
        "source_queries.scholar_queries_over_google_scholar",
        "scholar_queries alias precedence",
    )
    _require_exact(
        decoded["scope"]["allowed"],
        "query_analyzer_standard_search",
        "QueryAnalyzer allowed scope",
    )
    if production_source is not None:
        verify_query_analyzer_source(production_source)
    return decoded


def _validate_canonical_staged_bytes(
    lease: VerifiedManifestLease, execution_config: Mapping[str, Any]
) -> None:
    config_bytes = lease.read_bytes(PROFILE_CONFIG_PATH)
    if config_bytes != CANONICAL_RENDERED_CONFIG_BYTES:
        raise ValidationError("rendered config bytes are not canonical")
    _require_exact(
        config_bytes.splitlines()[0],
        f"_base_: {PROFILE_CONFIG_BASE_REFERENCE}".encode("ascii"),
        "rendered config _base_ reference",
    )
    for knob, expected in CANONICAL_EXECUTION_KNOBS.items():
        _require_exact(expected, execution_config[knob], f"execution config {knob}")

    manifest_bytes = lease.read_bytes(SPLIT_MANIFEST_PATH)
    if manifest_bytes != CANONICAL_SPLIT_MANIFEST_BYTES:
        raise ValidationError("split manifest bytes are not canonical")
    split_manifest = _load_strict_json_bytes(manifest_bytes, "split manifest")
    _require_exact(split_manifest, CANONICAL_SPLIT_MANIFEST, "split manifest schema")
    _require_exact(
        split_manifest["logical_splits"]["selection"], "val", "selection split"
    )
    _require_exact(
        split_manifest["logical_splits"]["optimizer_test"],
        "test",
        "optimizer test split",
    )
    minimums = {"train": 3, "val": 2, "test": 2}
    item_paths = {
        "train": SPLIT_TRAIN_ITEMS_PATH,
        "val": SPLIT_VAL_ITEMS_PATH,
        "test": SPLIT_TEST_ITEMS_PATH,
    }
    for split, path in item_paths.items():
        payload = lease.read_bytes(path)
        if payload != CANONICAL_SPLIT_ITEM_BYTES[split]:
            raise ValidationError(f"{split} split item bytes are not canonical")
        items = _load_strict_json_bytes(payload, f"{split} split items")
        if not isinstance(items, list) or len(items) < minimums[split]:
            raise ValidationError(
                f"{split} split must contain at least {minimums[split]} items"
            )
        _require_exact(
            split_manifest["splits"][split]["count"], len(items), f"{split} split count"
        )
        seen_ids: set[str] = set()
        for index, item in enumerate(items):
            _require_mapping(item, f"{split} items[{index}]")
            _exact_keys(item, {"id", "query", "split"}, f"{split} items[{index}]")
            item_id = _require_nonempty_string(item["id"], f"{split} items[{index}].id")
            if item_id in seen_ids:
                raise ValidationError(f"duplicate {split} item id: {item_id}")
            seen_ids.add(item_id)
            _require_nonempty_string(item["query"], f"{split} items[{index}].query")
            _require_exact(item["split"], split, f"{split} items[{index}].split")

    for script_path in REGISTRY_PATCH_PATHS:
        payload = lease.read_bytes(script_path)
        validate_registry_patch_result(script_path, payload)


def _validate_runner_image_inventory(value: Any) -> dict[str, Any]:
    _require_mapping(value, "runner_identity.image_inventory")
    _exact_keys(value, _RUNNER_IMAGE_INVENTORY_KEYS, "runner_identity.image_inventory")
    image_digest = _require_image_digest(
        value["image_digest"], "runner_identity.image_inventory.image_digest"
    )
    sbom_sha256 = _require_nonzero_sha256(
        value["sbom_sha256"], "runner_identity.image_inventory.sbom_sha256"
    )
    interpreters = value["interpreters"]
    if not isinstance(interpreters, list) or len(interpreters) != 1:
        raise ValidationError(
            "runner_identity.image_inventory.interpreters must have one entry"
        )
    interpreter = interpreters[0]
    _require_mapping(interpreter, "runner_identity.image_inventory.interpreters[0]")
    _exact_keys(
        interpreter,
        _RUNNER_INTERPRETER_KEYS,
        "runner_identity.image_inventory.interpreters[0]",
    )
    normalized_interpreter = {
        "path": validate_posix_absolute_path(
            interpreter["path"], "runner_identity.image_inventory.interpreters[0].path"
        ),
        "python_version": _require_python_patch(
            interpreter["python_version"],
            "runner_identity.image_inventory.interpreters[0].python_version",
        ),
        "sha256": _require_nonzero_sha256(
            interpreter["sha256"],
            "runner_identity.image_inventory.interpreters[0].sha256",
        ),
    }
    return {
        "image_digest": image_digest,
        "sbom_sha256": sbom_sha256,
        "interpreters": [normalized_interpreter],
    }


def _validate_staging_relations(
    pristine: Mapping[str, Any],
    overlay: Mapping[str, Any] | None,
    staging: Mapping[str, Any],
) -> None:
    if overlay is None:
        raise ValidationError("staging relations require overlay_manifest")
    pristine_by_path = {entry["path"]: entry for entry in pristine["files"]}
    overlay_by_path = {
        entry["path"]: entry
        for entry in overlay["logical_files"]
        if entry["projection"] == "staged"
    }
    metadata_overlay_by_path = {
        entry["path"]: entry
        for entry in overlay["logical_files"]
        if entry["projection"] == "metadata"
    }
    staged_by_path = {entry["path"]: entry for entry in staging["staged_tree"]}
    diff_by_path = {record["path"]: record for record in staging["allowlisted_diff"]}
    _require_exact(
        metadata_overlay_by_path,
        {
            QUERY_ANALYZER_CONTRACT_PATH: QUERY_ANALYZER_CONTRACT_ENTRY,
            OVERLAY_SCHEMA_PATH: OVERLAY_SCHEMA_ENTRY,
            REGISTRY_PATCH_CONTRACT_PATH: REGISTRY_PATCH_CONTRACT_ENTRY,
        },
        "overlay metadata projections",
    )
    _require_exact(
        set(overlay_by_path),
        set(REQUIRED_PROJECTED_INPUT_PATHS),
        "overlay staged projections",
    )
    required_diff_paths = set(REQUIRED_PROJECTED_INPUT_PATHS) | set(
        REGISTRY_PATCH_PATHS
    )
    _require_exact(set(diff_by_path), required_diff_paths, "allowlisted_diff paths")

    for path, before in pristine_by_path.items():
        if path in diff_by_path:
            continue
        staged = staged_by_path.get(path)
        if staged is None:
            raise ValidationError(
                f"unchanged upstream file missing from staged_tree: {path}"
            )
        _require_exact(staged, before, f"unchanged staged_tree entry {path}")

    for path, record in diff_by_path.items():
        if path not in required_diff_paths:
            raise ValidationError(f"unapproved allowlisted diff path: {path}")
        before = pristine_by_path.get(path)
        after = staged_by_path.get(path)
        overlay_after = overlay_by_path.get(path)
        if record["change"] == "add":
            if before is not None:
                raise ValidationError(f"add diff path already exists upstream: {path}")
            if after is None:
                raise ValidationError(f"add diff path missing from staged_tree: {path}")
            _require_exact(
                record["after_sha256"], after["sha256"], f"add diff after {path}"
            )
        elif record["change"] == "modify":
            if before is None:
                raise ValidationError(f"modify diff path missing upstream: {path}")
            if after is None:
                raise ValidationError(
                    f"modify diff path missing from staged_tree: {path}"
                )
            _require_exact(
                record["before_sha256"], before["sha256"], f"modify diff before {path}"
            )
            _require_exact(
                record["after_sha256"], after["sha256"], f"modify diff after {path}"
            )
        _require_exact(record["mode"], after["mode"], f"diff mode {path}")
        if overlay_after is not None:
            if after is None:
                raise ValidationError(
                    f"projected overlay path missing from staged_tree: {path}"
                )
            _require_exact(
                after,
                {
                    key: overlay_after[key]
                    for key in ("path", "kind", "mode", "size_bytes", "sha256")
                },
                f"overlay staged entry {path}",
            )
            _require_exact(
                record["after_sha256"], overlay_after["sha256"], f"overlay after {path}"
            )

    for path in staged_by_path:
        if path not in pristine_by_path and path not in diff_by_path:
            raise ValidationError(
                f"staged_tree contains unallowlisted added path: {path}"
            )

    for script_path, patch_field in (
        ("scripts/train.py", "train_registry_patch_sha256"),
        ("scripts/eval_only.py", "eval_registry_patch_sha256"),
    ):
        if script_path not in diff_by_path:
            raise ValidationError(
                f"{script_path} must be allowlisted as a registry patch"
            )
        staged = staged_by_path.get(script_path)
        if staged is None:
            raise ValidationError(f"{script_path} missing from staged_tree")
        _require_exact(staging[patch_field], staged["sha256"], patch_field)
        _require_exact(
            diff_by_path[script_path]["after_sha256"],
            staged["sha256"],
            f"{script_path} diff hash",
        )
        patch_contract = REGISTRY_PATCH_CONTRACT["patches"][script_path]
        pristine_script = pristine_by_path.get(script_path)
        if pristine_script is None:
            raise ValidationError(f"{script_path} missing from pristine source")
        _require_exact(
            diff_by_path[script_path]["before_sha256"],
            patch_contract["base_sha256"],
            f"{script_path} pristine patch base",
        )
        _require_exact(
            pristine_script["size_bytes"],
            patch_contract["base_size_bytes"],
            f"{script_path} pristine patch base size",
        )
        _require_exact(
            staged["sha256"],
            patch_contract["result_sha256"],
            f"{script_path} constrained patch result",
        )
        _require_exact(
            staged["size_bytes"],
            patch_contract["result_size_bytes"],
            f"{script_path} constrained patch result size",
        )

    _require_exact(
        staging["registry_patches"],
        [
            {"path": path, **dict(REGISTRY_PATCH_CONTRACT["patches"][path])}
            for path in REGISTRY_PATCH_PATHS
        ],
        "staging registry patch bindings",
    )

    module_by_path = {
        entry["file_path"]: entry for entry in staging["expected_imported_modules"]
    }
    module_paths = {
        entry["module_path"]: entry["file_path"] for entry in module_by_path.values()
    }
    _require_exact(module_paths, REQUIRED_IMPORTED_MODULES, "expected_imported_modules")
    for module in staging["expected_imported_modules"]:
        staged = staged_by_path.get(module["file_path"])
        if staged is None:
            raise ValidationError(
                f"expected module file missing from staged_tree: {module['file_path']}"
            )
        _require_exact(
            module["sha256"],
            staged["sha256"],
            f"expected module hash {module['file_path']}",
        )

    config_entry = staged_by_path.get(PROFILE_CONFIG_PATH)
    if config_entry is None:
        raise ValidationError("argv-referenced config missing from staged_tree")
    _require_exact(
        staging["execution_config"]["rendered_config_sha256"],
        config_entry["sha256"],
        "execution_config.rendered_config_sha256",
    )
    _require_exact(
        config_entry["sha256"],
        hashlib.sha256(CANONICAL_RENDERED_CONFIG_BYTES).hexdigest(),
        "canonical rendered config hash",
    )
    canonical_split_payloads = {
        SPLIT_MANIFEST_PATH: CANONICAL_SPLIT_MANIFEST_BYTES,
        SPLIT_TRAIN_ITEMS_PATH: CANONICAL_SPLIT_ITEM_BYTES["train"],
        SPLIT_VAL_ITEMS_PATH: CANONICAL_SPLIT_ITEM_BYTES["val"],
        SPLIT_TEST_ITEMS_PATH: CANONICAL_SPLIT_ITEM_BYTES["test"],
    }
    for path, payload in canonical_split_payloads.items():
        _require_exact(
            staged_by_path[path]["sha256"],
            hashlib.sha256(payload).hexdigest(),
            f"canonical split artifact {path}",
        )
    for input_path in (
        PROFILE_CONFIG_PATH,
        SPLIT_MANIFEST_PATH,
        SPLIT_TRAIN_ITEMS_PATH,
        SPLIT_VAL_ITEMS_PATH,
        SPLIT_TEST_ITEMS_PATH,
        SKILL_INIT_PATH,
    ):
        if input_path not in staged_by_path:
            raise ValidationError(
                f"argv-referenced input missing from staged_tree: {input_path}"
            )


def _validate_evidence_ceiling(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValidationError("evidence_ceiling must be a list")
    normalized: list[dict[str, str]] = []
    for index, diagnostic in enumerate(value):
        _require_mapping(diagnostic, f"evidence_ceiling[{index}]")
        _exact_keys(
            diagnostic, {"code", "level", "message"}, f"evidence_ceiling[{index}]"
        )
        code = diagnostic["code"]
        level = diagnostic["level"]
        message = diagnostic["message"]
        if (
            not isinstance(code, str)
            or not isinstance(level, str)
            or not isinstance(message, str)
        ):
            raise ValidationError("evidence_ceiling entries must be strings")
        normalized.append({"code": code, "level": level, "message": message})
    normalized = sorted(normalized, key=lambda item: item["code"])
    expected_by_code = {item["code"]: item for item in EXPECTED_EVIDENCE_CEILING}
    for diagnostic in normalized:
        if diagnostic["code"] not in _UNRESOLVED_CODES:
            raise ValidationError("evidence_ceiling contains unknown diagnostic code")
        if diagnostic["level"] != "evidence_ceiling":
            raise ValidationError("evidence_ceiling level must be evidence_ceiling")
        if diagnostic != expected_by_code[diagnostic["code"]]:
            raise ValidationError(
                "evidence_ceiling messages must equal the approved diagnostics"
            )
    return normalized


def _validate_nullable_tested_patch(
    value: Any, staging: Mapping[str, Any] | None, runner: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    if value is None:
        return None
    if staging is None:
        raise ValidationError("tested_patch requires staging_manifest")
    if runner is None:
        raise ValidationError("tested_patch requires runner_identity")
    _require_mapping(value, "tested_patch")
    _exact_keys(value, _TESTED_PATCH_KEYS, "tested_patch")
    _require_exact(value["profile_id"], PROFILE_ID, "tested_patch.profile_id")
    _require_exact(
        value["staging_identity"], staging["identity"], "tested_patch.staging_identity"
    )
    _require_exact(
        value["runner_identity"], runner["identity"], "tested_patch.runner_identity"
    )
    _require_identity(value["report_identity"], "tested_patch.report_identity")
    _require_exact(value["status"], "passed", "tested_patch.status")
    imported_modules = _validate_expected_modules(value["imported_modules"])
    _require_exact(
        imported_modules,
        staging["expected_imported_modules"],
        "tested_patch.imported_modules",
    )
    _require_exact(
        value["outputs"],
        {
            "train_out_root": TRAIN_OUT_ROOT,
            "eval_out_root": EVAL_OUT_ROOT,
            "candidate_path": CANDIDATE_PATH,
        },
        "tested_patch.outputs",
    )
    _require_exact(value["provider_count"], 0, "tested_patch.provider_count")
    _require_exact(value["network_count"], 0, "tested_patch.network_count")
    _require_exact(value["subprocess_count"], 0, "tested_patch.subprocess_count")
    _require_exact(
        value["config_identity"],
        staging["execution_config_identity"],
        "tested_patch.config_identity",
    )
    _require_exact(
        value["train_argv_identity"],
        staging["execution_config"]["train_argv_identity"],
        "tested_patch.train_argv_identity",
    )
    _require_exact(
        value["eval_argv_identity"],
        staging["execution_config"]["eval_argv_identity"],
        "tested_patch.eval_argv_identity",
    )
    observed_interpreter = value["observed_interpreter"]
    _require_mapping(observed_interpreter, "tested_patch.observed_interpreter")
    _exact_keys(
        observed_interpreter,
        _RUNNER_INTERPRETER_KEYS,
        "tested_patch.observed_interpreter",
    )
    _require_exact(
        observed_interpreter,
        {
            "path": runner["interpreter_path"],
            "python_version": runner["python_version"],
            "sha256": runner["interpreter_sha256"],
        },
        "tested_patch.observed_interpreter",
    )
    if value["verified"] is not True:
        raise ValidationError("tested_patch.verified must be true")
    normalized = dict(value)
    normalized["imported_modules"] = imported_modules
    return normalized


def _validate_nullable_full_lock(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    _require_mapping(value, "full_dependency_lock")
    _exact_keys(value, _FULL_LOCK_KEYS, "full_dependency_lock")
    _require_nonzero_sha256(value["sha256"], "full_dependency_lock.sha256")
    _require_nonempty_string(value["format"], "full_dependency_lock.format")
    if value["complete"] is not True:
        raise ValidationError("full_dependency_lock.complete must be true")
    return dict(value)


def _derived_unresolved_codes(
    *,
    overlay: Mapping[str, Any] | None,
    staging: Mapping[str, Any] | None,
    runner: Mapping[str, Any] | None,
    custody: Mapping[str, Any] | None,
    tested_patch: Mapping[str, Any] | None,
    full_lock: Mapping[str, Any] | None,
) -> list[str]:
    derived: list[str] = []
    if overlay is None:
        derived.append("overlay_manifest")
    if staging is None:
        derived.append("staging_manifest")
    if runner is None:
        derived.append("image_digest")
    if custody is None:
        derived.append("custody")
    if tested_patch is None:
        derived.append("tested_patch")
    if full_lock is None:
        derived.append("full_dependency_lock")
    return sorted(derived)
