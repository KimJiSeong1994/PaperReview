from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from routers.geo_comparisons import (
    AXES,
    GeoComparisonError,
    load_geo_comparisons,
    validate_comparisons,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/blog/geo-comparisons.json"


def _cell(state: str = "known") -> dict:
    if state == "known":
        return {
            "state": state,
            "value": "paper-supported value",
            "reason": None,
            "sources": ["https://arxiv.org/abs/2404.16130"],
        }
    return {"state": state, "value": None, "reason": "not established", "sources": []}


def _document() -> dict:
    def hub(slug: str) -> dict:
        return {
            "question": "Which conditions fit this method?",
            "axes": list(AXES),
            "entries": [{"slug": slug, "values": {axis: _cell() for axis in AXES}}],
            "limits": "Do not compare unlike benchmarks as a ranking.",
            "source_note": "Claims are scoped to each primary paper.",
        }

    return {
        "schema_version": 1,
        "comparisons": {"graphrag": hub("graph-entry"), "gnn": hub("gnn-entry")},
    }


def test_comparison_contract_accepts_all_axes_and_states() -> None:
    document = _document()
    document["comparisons"]["gnn"]["entries"][0]["values"]["cost"] = _cell("unknown")
    document["comparisons"]["gnn"]["entries"][0]["values"]["failure_conditions"] = _cell(
        "not_applicable"
    )
    result = validate_comparisons(
        document,
        series_members={"graphrag": ["graph-entry"], "gnn": ["gnn-entry"]},
        published_slugs={"graph-entry", "gnn-entry"},
    )
    assert tuple(result) == ("graphrag", "gnn")


def test_comparison_schema_version_rejects_boolean_alias() -> None:
    document = _document()
    document["schema_version"] = True
    with pytest.raises(GeoComparisonError, match="schema_version"):
        validate_comparisons(document)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda doc: doc["comparisons"]["gnn"].update(axes=list(AXES[:-1])),
        lambda doc: doc["comparisons"]["gnn"]["entries"].append(
            copy.deepcopy(doc["comparisons"]["gnn"]["entries"][0])
        ),
        lambda doc: doc["comparisons"]["gnn"]["entries"][0]["values"].pop("cost"),
        lambda doc: doc["comparisons"]["gnn"]["entries"][0]["values"]["cost"].update(
            state="unknown", value="invented", reason="unknown"
        ),
        lambda doc: doc["comparisons"]["gnn"]["entries"][0]["values"]["cost"].update(
            sources=["javascript:alert(1)"]
        ),
    ],
)
def test_comparison_contract_rejects_malformed_graphs(mutation) -> None:
    document = _document()
    mutation(document)
    with pytest.raises(GeoComparisonError):
        validate_comparisons(document)


def test_checked_in_source_and_projections_are_exact() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/sync_geo_comparisons.py"), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    source = json.loads(SOURCE.read_text(encoding="utf-8"))["comparisons"]
    spec = importlib.util.spec_from_file_location(
        "geo_generated", ROOT / "routers/geo_comparisons_generated.py"
    )
    assert spec and spec.loader
    generated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generated)
    assert generated.GEO_COMPARISONS == source
    ts_source = (ROOT / "web-ui/src/seo/geoComparisons.generated.ts").read_text(encoding="utf-8")
    payload = ts_source.split("export const GEO_COMPARISONS: GeoComparisons = ", 1)[1].rsplit(";", 1)[0]
    assert json.loads(payload) == source


def test_runtime_falls_back_when_generated_object_is_malformed(tmp_path) -> None:
    malformed = tmp_path / "geo_generated.py"
    malformed.write_text("raise RuntimeError('must never execute')\n", encoding="utf-8")
    assert load_geo_comparisons(generated_path=malformed) == {}


def test_check_mode_detects_generated_byte_drift(tmp_path, monkeypatch) -> None:
    script_spec = importlib.util.spec_from_file_location(
        "sync_geo_comparisons", ROOT / "scripts/sync_geo_comparisons.py"
    )
    assert script_spec and script_spec.loader
    script = importlib.util.module_from_spec(script_spec)
    script_spec.loader.exec_module(script)
    python_output = tmp_path / "geo.py"
    typescript_output = tmp_path / "geo.ts"
    monkeypatch.setattr(script, "PYTHON_OUTPUT", python_output)
    monkeypatch.setattr(script, "TYPESCRIPT_OUTPUT", typescript_output)
    assert script.sync(source=SOURCE)
    python_output.write_text("# drift\n", encoding="utf-8")
    assert not script.sync(check=True, source=SOURCE)


def test_only_three_geo_json_files_escape_blog_ignore() -> None:
    expected = {
        "data/blog/geo-comparisons.json",
        "data/blog/geo-pilot.json",
        "data/blog/geo-pilot-observation.json",
    }
    for relative in expected:
        result = subprocess.run(
            ["git", "check-ignore", "-q", relative], cwd=ROOT, check=False
        )
        assert result.returncode == 1, relative
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "data/blog/unrelated-private.json"],
        cwd=ROOT,
        check=False,
    )
    assert ignored.returncode == 0
