"""Materialize a real SkillOpt-compatible benchmark for paper search.

This module writes the files that the upstream Microsoft SkillOpt trainer expects
for a custom environment: split data, seed skill, env package, and YAML config.
It remains dev-only and does not import ``skillopt`` at runtime, so CI can verify
the integration without installing external optimizer dependencies.
"""
from __future__ import annotations

import json
import textwrap
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .skillopt_adapter import canonical_file_hash
from .skillopt_contract import V1_ALLOWED_SCOPE, ValidationError, load_json, validate_dataset_contract, validate_execution_control
from .query_analyzer_pilot import load_baseline_skill

ENV_NAME = "jiphyeonjeon_search"


def materialize_skillopt_search_benchmark(
    *,
    output_dir: str | Path,
    dataset_path: str | Path,
    control_path: str | Path,
    baseline_skill_path: str | Path,
) -> dict[str, Any]:
    """Write a SkillOpt-compatible benchmark tree and return its manifest."""
    output = Path(output_dir)
    dataset = load_json(dataset_path)
    control = load_json(control_path)
    baseline_skill = load_baseline_skill(baseline_skill_path)
    validate_dataset_contract(dataset)
    validate_execution_control(control)
    if control.get("scope") != V1_ALLOWED_SCOPE or control.get("fast_mode") is not False or control.get("use_llm_search") is not False:
        raise ValidationError("SkillOpt materialization requires standard QueryAnalyzer search scope only")

    split_root = output / "data" / f"{ENV_NAME}_split"
    env_root = output / "skillopt" / "envs" / ENV_NAME
    config_path = output / "configs" / ENV_NAME / "default.yaml"
    skill_path = env_root / "skills" / "initial.md"

    _write_split_files(split_root, dataset)
    _write_env_package(env_root)
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(baseline_skill, encoding="utf-8")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(_config_yaml(split_root=split_root, skill_path=skill_path), encoding="utf-8")
    readme_path = output / "README.md"
    readme_path.write_text(_readme(config_path=config_path), encoding="utf-8")

    manifest = {
        "version": "skillopt-search-benchmark-materialization-v0",
        "env_name": ENV_NAME,
        "scope": V1_ALLOWED_SCOPE,
        "output_dir": str(output),
        "config_path": str(config_path),
        "split_dir": str(split_root),
        "env_package_dir": str(env_root),
        "initial_skill_path": str(skill_path),
        "source_hashes": {
            "dataset_file": canonical_file_hash(dataset_path),
            "control_file": canonical_file_hash(control_path),
            "baseline_skill_file": canonical_file_hash(baseline_skill_path),
        },
        "dataset_hash": dataset["dataset_hash"],
        "execution_control_hash": control["control_hash"],
        "registration_snippet": _registration_snippet(),
        "train_command": f"python scripts/train.py --config {config_path}",
        "expected_best_skill": "ckpt/<run>/best_skill.md",
    }
    (output / "skillopt_materialization_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    validate_skillopt_materialization_manifest(manifest)
    return manifest


def validate_skillopt_materialization_manifest(manifest: Mapping[str, Any]) -> None:
    required = {
        "version",
        "env_name",
        "scope",
        "output_dir",
        "config_path",
        "split_dir",
        "env_package_dir",
        "initial_skill_path",
        "source_hashes",
        "dataset_hash",
        "execution_control_hash",
        "registration_snippet",
        "train_command",
        "expected_best_skill",
    }
    missing = required - set(manifest)
    if missing:
        raise ValidationError(f"skillopt_materialization missing required keys: {sorted(missing)}")
    if manifest.get("env_name") != ENV_NAME:
        raise ValidationError("skillopt_materialization.env_name is invalid")
    if manifest.get("scope") != V1_ALLOWED_SCOPE:
        raise ValidationError("skillopt_materialization.scope is invalid")
    source_hashes = manifest.get("source_hashes")
    if not isinstance(source_hashes, Mapping) or set(source_hashes) != {"dataset_file", "control_file", "baseline_skill_file"}:
        raise ValidationError("skillopt_materialization.source_hashes must bind dataset/control/baseline")
    if any(not isinstance(value, str) or not value.startswith("sha256:") for value in source_hashes.values()):
        raise ValidationError("skillopt_materialization.source_hashes must be sha256 digests")


def _write_split_files(split_root: Path, dataset: Mapping[str, Any]) -> None:
    grouped = {"train": [], "selection": [], "test": []}
    for item in dataset["queries"]:
        split = item["split"]
        grouped[split].append(
            {
                "id": item["query_id"],
                "query": item["query_text"],
                "split": item["split"],
                "group_id": item["group_id"],
                "locale": item["locale"],
                "intent": item["intent"],
                "task_type": item["intent"],
                "labels": item["labels"],
            }
        )
    for split, items in grouped.items():
        split_dir = split_root / split
        split_dir.mkdir(parents=True, exist_ok=True)
        (split_dir / "items.json").write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Upstream SkillOpt SplitDataLoader expects train/val/test directories.
    # Preserve the domain contract name (`selection`) and mirror it as `val`
    # for live optimizer compatibility.
    val_dir = split_root / "val"
    val_dir.mkdir(parents=True, exist_ok=True)
    (val_dir / "items.json").write_text(
        json.dumps(grouped["selection"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_env_package(env_root: Path) -> None:
    env_root.mkdir(parents=True, exist_ok=True)
    (env_root / "__init__.py").write_text("", encoding="utf-8")
    (env_root / "dataloader.py").write_text(_dataloader_py(), encoding="utf-8")
    (env_root / "rollout.py").write_text(_rollout_py(), encoding="utf-8")
    (env_root / "adapter.py").write_text(_adapter_py(), encoding="utf-8")


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


def _rollout_py() -> str:
    return textwrap.dedent(
        r'''
        from __future__ import annotations

        import json
        import os
        from pathlib import Path

        from skillopt.model import chat_target
        from skillopt.model.backend_config import is_target_exec_backend
        from skillopt.model.codex_harness import run_target_exec


        def _score_text(text: str, labels: dict) -> tuple[int, float]:
            haystack = (text or "").lower()
            must_include = [str(v).lower() for v in labels.get("must_include", [])]
            acceptable = [str(v).lower() for v in labels.get("acceptable", [])]
            must_exclude = [str(v).lower() for v in labels.get("must_exclude", [])]
            if any(label in haystack for label in must_exclude):
                return 0, 0.0
            must_hits = sum(1 for label in must_include if label in haystack)
            acceptable_hits = sum(1 for label in acceptable if label in haystack)
            hard = int(bool(must_include) and must_hits == len(must_include))
            denom = max(len(must_include) * 2 + len(acceptable), 1)
            soft = min((must_hits * 2 + acceptable_hits) / denom, 1.0)
            return hard, soft


        def _rollout_one(item: dict, skill_content: str, *, max_completion_tokens: int, prediction_dir: str, exec_timeout: int) -> dict:
            user = (
                "Analyze this Jiphyeonjeon paper-search query for the standard QueryAnalyzer path.\\n"
                "Return JSON with improved_query, keywords, and source_queries only.\\n\\n"
                f"Query: {item['query']}\\n"
                f"Intent: {item.get('intent', '')}\\n"
                f"Locale: {item.get('locale', '')}"
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
            hard, soft = _score_text(prediction, item.get("labels", {}))
            task_id = str(item["id"])
            expected = {
                "must_include": item.get("labels", {}).get("must_include", []),
                "acceptable": item.get("labels", {}).get("acceptable", []),
                "must_exclude": item.get("labels", {}).get("must_exclude", []),
            }
            fail_reason = "" if hard else (
                "missing required paper-search labels: "
                + json.dumps(expected, ensure_ascii=False)
            )
            pred_root = Path(prediction_dir) / task_id
            pred_root.mkdir(parents=True, exist_ok=True)
            conversation = [
                {"role": "system", "content": skill_content},
                {"role": "user", "content": user},
                {"role": "assistant", "content": prediction},
                {"role": "system", "content": f"hard={hard} soft={soft} fail_reason={fail_reason}"},
            ]
            (pred_root / "conversation.json").write_text(
                json.dumps(conversation, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            (pred_root / "target_system_prompt.txt").write_text(skill_content, encoding="utf-8")
            (pred_root / "target_user_prompt.txt").write_text(user, encoding="utf-8")
            return {
                "id": task_id,
                "hard": hard,
                "soft": soft,
                "predicted_answer": prediction,
                "query": item.get("query", ""),
                "split": item.get("split", ""),
                "group_id": item.get("group_id", ""),
                "intent": item.get("intent", ""),
                "task_description": item.get("query", ""),
                "task_type": item.get("task_type", "paper_search"),
                "target_system_prompt": skill_content,
                "target_user_prompt": user,
                "reference_text": json.dumps(expected, ensure_ascii=False),
                "fail_reason": fail_reason,
                "n_turns": 1,
            }


        def run_batch(*, items: list[dict], skill_content: str, out_root: str, workers: int = 4, max_completion_tokens: int = 4096, exec_timeout: int = 600) -> list[dict]:
            os.makedirs(out_root, exist_ok=True)
            prediction_dir = os.path.join(out_root, "predictions")
            os.makedirs(prediction_dir, exist_ok=True)
            results = [
                _rollout_one(
                    item,
                    skill_content,
                    max_completion_tokens=max_completion_tokens,
                    prediction_dir=prediction_dir,
                    exec_timeout=exec_timeout,
                )
                for item in items
            ]
            Path(out_root, "rollouts.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
            return results
        '''
    ).lstrip()


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
        f'''
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
        env:
          name: {ENV_NAME}
          skill_init: {skill_path}
          split_mode: split_dir
          split_dir: {split_root}
          workers: 4
          max_completion_tokens: 2048
          exec_timeout: 600
          limit: 0
        '''
    ).lstrip()


def _registration_snippet() -> str:
    return textwrap.dedent(
        '''
        try:
            from skillopt.envs.jiphyeonjeon_search.adapter import JiphyeonjeonSearchAdapter
            _ENV_REGISTRY["jiphyeonjeon_search"] = JiphyeonjeonSearchAdapter
        except ImportError:
            pass
        '''
    ).strip()


def _readme(*, config_path: Path) -> str:
    return textwrap.dedent(
        f'''
        # Jiphyeonjeon SkillOpt Search Benchmark

        Generated dev-only benchmark for Microsoft SkillOpt.

        1. Copy or symlink this generated `skillopt/envs/jiphyeonjeon_search` package into a SkillOpt checkout.
        2. Add the registration snippet from `skillopt_materialization_manifest.json` to SkillOpt `scripts/train.py`.
        3. Run: `python scripts/train.py --config {config_path}`.
        4. Copy the resulting `best_skill.md` back into this repo and run the offline retrieval approval pipeline.
        '''
    ).lstrip()
