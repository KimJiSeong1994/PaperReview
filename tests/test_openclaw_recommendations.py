from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.openclaw_recommendations import (
    OpenClawArtifactError,
    derive_artifact_date,
    import_openclaw_artifact,
    safe_user_id,
)
from src.recommendations_artifacts import load_recommendation_artifact


def _raw(user_id: str = "Jipyheonjeon") -> dict[str, object]:
    return {
        "run_at": "2026-04-25T11:33:04+00:00",
        "user_id": user_id,
        "scoring_mode": "openclaw:listwise",
        "score_stats": {"keywords": {"n": 1, "mean": 4.7}},
        "variants": {
            "keywords": [
                {
                    "title": "Graph Pooling for Graph Neural Networks",
                    "authors": ["A. Researcher"],
                    "year": 2026,
                    "score": 4.7,
                    "rank": 1,
                    "reason": "Matches SOUL and bookmark profile.",
                }
            ],
            "soul": [
                {
                    "title": "Personalized Research Agents",
                    "year": 2026,
                    "score": 4.5,
                    "rank": 2,
                    "reason": "Extends the user's research trajectory.",
                }
            ],
        },
    }


def test_import_openclaw_artifact_writes_existing_notification_layout(tmp_path: Path) -> None:
    source = tmp_path / "openclaw" / "artifacts" / "2026-04-25" / "raw.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(_raw(), ensure_ascii=False), encoding="utf-8")

    result = import_openclaw_artifact(source, tmp_path / "recommendations")

    assert result.user_id == "Jipyheonjeon"
    assert result.date == "2026-04-25"
    assert result.variant_count == 2
    assert result.item_count == 2
    assert result.destination_path == tmp_path / "recommendations" / "Jipyheonjeon" / "2026-04-25" / "raw.json"

    loaded = load_recommendation_artifact(tmp_path / "recommendations", "Jipyheonjeon", limit=10)
    assert loaded["latest_run_at"] == "2026-04-25T11:33:04+00:00"
    assert loaded["scoring_mode"] == "openclaw:listwise"
    assert loaded["raw_count"] == 2
    assert loaded["grouped_items"][0]["title"] == "Graph Pooling for Graph Neural Networks"


def test_import_rejects_unsafe_user_id_and_invalid_date(tmp_path: Path) -> None:
    assert safe_user_id("safe_user-1") == "safe_user-1"
    with pytest.raises(OpenClawArtifactError):
        safe_user_id("../escape")

    source = tmp_path / "raw.json"
    source.write_text(json.dumps(_raw("../escape")), encoding="utf-8")
    with pytest.raises(OpenClawArtifactError):
        import_openclaw_artifact(source, tmp_path / "recommendations")

    source.write_text(json.dumps(_raw()), encoding="utf-8")
    with pytest.raises(OpenClawArtifactError):
        import_openclaw_artifact(source, tmp_path / "recommendations", date_override="2026-02-30")


def test_derive_artifact_date_falls_back_to_source_path(tmp_path: Path) -> None:
    source = tmp_path / "artifacts" / "2026-04-24" / "raw.json"
    assert derive_artifact_date({"run_at": "not-a-date"}, source) == "2026-04-24"
    assert derive_artifact_date(_raw(), source, date_override="2026-04-26") == "2026-04-26"
