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
            "reading_guide": [{"title": "Start here", "description": "Identify the task."}],
            "axes": list(AXES),
            "entries": [
                {"slug": slug, "label": "Method", "values": {axis: _cell() for axis in AXES}}
            ],
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


@pytest.mark.parametrize("hub_id", ["graphrag", "gnn"])
@pytest.mark.parametrize(
    "mutation",
    [
        lambda hub: hub.pop("reading_guide"),
        lambda hub: hub.update(reading_guide=[]),
        lambda hub: hub.update(reading_guide={}),
        lambda hub: hub.update(
            reading_guide=[{"title": "Step", "description": "Read."}] * 7
        ),
        lambda hub: hub.update(reading_guide=["Read."]),
        lambda hub: hub["reading_guide"][0].pop("title"),
        lambda hub: hub["reading_guide"][0].pop("description"),
        lambda hub: hub["reading_guide"][0].update(title=" "),
        lambda hub: hub["reading_guide"][0].update(description=""),
        lambda hub: hub["reading_guide"][0].update(title=1),
        lambda hub: hub["reading_guide"][0].update(description=None),
        lambda hub: hub["reading_guide"][0].update(slug="extra-field"),
        lambda hub: hub["entries"][0].pop("label"),
        lambda hub: hub["entries"][0].update(label=" "),
        lambda hub: hub["entries"][0].update(label=None),
        lambda hub: hub["entries"][0].update(label=7),
    ],
)
def test_reading_contract_is_required_and_strict(hub_id, mutation) -> None:
    document = _document()
    mutation(document["comparisons"][hub_id])
    with pytest.raises(GeoComparisonError):
        validate_comparisons(document)


@pytest.mark.parametrize("step_count", [1, 6])
def test_reading_guide_boundaries_and_detached_result(step_count) -> None:
    document = _document()
    document["comparisons"]["gnn"]["reading_guide"] = [
        {"title": f"Step {index}", "description": "Read the primary evidence."}
        for index in range(step_count)
    ]
    result = validate_comparisons(document)
    assert len(result["gnn"]["reading_guide"]) == step_count
    result["gnn"]["reading_guide"][0]["title"] = "Changed"
    result["gnn"]["entries"][0]["label"] = "Changed"
    assert document["comparisons"]["gnn"]["reading_guide"][0]["title"] == "Step 0"
    assert document["comparisons"]["gnn"]["entries"][0]["label"] == "Method"


def test_canonical_reading_content_preserves_scope_and_evidence() -> None:
    comparisons = validate_comparisons(json.loads(SOURCE.read_text(encoding="utf-8")))
    assert [entry["label"] for entry in comparisons["graphrag"]["entries"]] == [
        "MS GraphRAG", "LightRAG", "Deep GraphRAG"
    ]
    assert [entry["label"] for entry in comparisons["gnn"]["entries"]] == [
        "GCN", "GraphSAGE", "GNNExplainer", "GNN+"
    ]
    assert len(comparisons["gnn"]["reading_guide"]) == 5
    deep = comparisons["graphrag"]["entries"][2]["values"]
    assert deep["traceability"]["state"] == "unknown"
    assert "LLM으로 동일 개체인지 확인" in deep["graph_construction"]["value"]
    assert "최종 답변 생성에는 별도의" in deep["evaluation_context"]["value"]
    assert "전체 비용 비교는 제공하지 않는다" in deep["cost"]["value"]
    gnn = comparisons["gnn"]["entries"]
    assert all(entry["values"]["graph_construction"]["state"] == "not_applicable" for entry in gnn)
    assert "두 학습 목적을 모두 다룬다" in gnn[1]["values"]["evaluation_context"]["value"]
    assert "인과 원인이나 개입 효과를 뜻하지 않는다" in gnn[2]["values"]["traceability"]["value"]
    assert "10개는" in gnn[3]["values"]["evaluation_context"]["value"]
    assert "네 개는 node classification" in gnn[3]["values"]["evaluation_context"]["value"]
    assert all(
        cell["sources"]
        for hub in comparisons.values()
        for entry in hub["entries"]
        for cell in entry["values"].values()
    )


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
    assert "  label: string;" in ts_source
    assert "  reading_guide: Array<{ title: string; description: string }>;" in ts_source
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
