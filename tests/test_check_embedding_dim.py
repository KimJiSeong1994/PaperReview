"""Tests for scripts/check_embedding_dim.py (US-001 B5 dim gate).

Strategy: import the script module and call main() with monkeypatched sys.argv,
EMBEDDINGS_PATH, and OUTPUT_PATH — faster than subprocess and fully monkeypatchable.
"""

import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module import helper
# ---------------------------------------------------------------------------

def _load_module():
    """Import (or reload) the script as a module."""
    spec = importlib.util.spec_from_file_location(
        "check_embedding_dim",
        Path(__file__).resolve().parent.parent / "scripts" / "check_embedding_dim.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_embeddings(tmp_path):
    """Write a 384-d embeddings.json in tmp_path and return its Path."""
    path = tmp_path / "embeddings.json"
    path.write_text(json.dumps({"paper_1": [0.1] * 384, "paper_2": [0.2] * 384}))
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCheckEmbeddingDim:

    def test_passes_with_matching_dim_skip_api(self, tmp_path, fake_embeddings, monkeypatch):
        """Stored dim == target → exit 0, result JSON written with correct fields."""
        output_path = tmp_path / ".embedding_dim_check.json"
        mod = _load_module()
        monkeypatch.setattr(mod, "EMBEDDINGS_PATH", fake_embeddings)
        monkeypatch.setattr(mod, "OUTPUT_PATH", output_path)
        monkeypatch.setattr(sys, "argv", ["check_embedding_dim.py", "--skip-api", "--expected-dim", "384"])

        rc = mod.main()

        assert rc == 0
        assert output_path.exists()
        result = json.loads(output_path.read_text())
        assert result["stored"] == 384
        assert result["api"] is None
        assert result["target"] == 384
        assert "verified_at" in result

    def test_fails_on_dim_mismatch(self, tmp_path, monkeypatch):
        """Stored dim 128 vs expected 384 → exit 1, no output JSON."""
        emb_path = tmp_path / "embeddings.json"
        emb_path.write_text(json.dumps({"k": [0.0] * 128}))
        output_path = tmp_path / ".embedding_dim_check.json"

        mod = _load_module()
        monkeypatch.setattr(mod, "EMBEDDINGS_PATH", emb_path)
        monkeypatch.setattr(mod, "OUTPUT_PATH", output_path)
        monkeypatch.setattr(sys, "argv", ["check_embedding_dim.py", "--skip-api", "--expected-dim", "384"])

        rc = mod.main()

        assert rc == 1
        assert not output_path.exists()

    def test_fails_when_embeddings_file_missing(self, tmp_path, monkeypatch, capsys):
        """Missing embeddings file → exit 1, stdout contains 'FAIL'."""
        missing = tmp_path / "no_such_file.json"
        output_path = tmp_path / ".embedding_dim_check.json"

        mod = _load_module()
        monkeypatch.setattr(mod, "EMBEDDINGS_PATH", missing)
        monkeypatch.setattr(mod, "OUTPUT_PATH", output_path)
        monkeypatch.setattr(sys, "argv", ["check_embedding_dim.py", "--skip-api"])

        rc = mod.main()

        assert rc == 1
        captured = capsys.readouterr()
        assert "FAIL" in captured.out

    def test_skip_api_flag_prevents_openai_call(self, tmp_path, fake_embeddings, monkeypatch):
        """--skip-api must not invoke OpenAI even when OPENAI_API_KEY is present."""
        output_path = tmp_path / ".embedding_dim_check.json"
        mod = _load_module()
        monkeypatch.setattr(mod, "EMBEDDINGS_PATH", fake_embeddings)
        monkeypatch.setattr(mod, "OUTPUT_PATH", output_path)
        monkeypatch.setattr(sys, "argv", ["check_embedding_dim.py", "--skip-api", "--expected-dim", "384"])
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-key")

        mock_openai = MagicMock()
        with patch.dict(sys.modules, {"openai": mock_openai}):
            rc = mod.main()

        assert rc == 0
        mock_openai.OpenAI.assert_not_called()

    def test_missing_api_key_falls_back_gracefully(self, tmp_path, fake_embeddings, monkeypatch):
        """No OPENAI_API_KEY and no --skip-api → warning logged, still exit 0."""
        output_path = tmp_path / ".embedding_dim_check.json"
        mod = _load_module()
        monkeypatch.setattr(mod, "EMBEDDINGS_PATH", fake_embeddings)
        monkeypatch.setattr(mod, "OUTPUT_PATH", output_path)
        monkeypatch.setattr(sys, "argv", ["check_embedding_dim.py", "--expected-dim", "384"])
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        rc = mod.main()

        assert rc == 0
        result = json.loads(output_path.read_text())
        assert result["api"] is None

    def test_result_json_has_iso8601_timestamp(self, tmp_path, fake_embeddings, monkeypatch):
        """verified_at must be a valid ISO-8601 UTC timestamp within 5 minutes of now."""
        output_path = tmp_path / ".embedding_dim_check.json"
        mod = _load_module()
        monkeypatch.setattr(mod, "EMBEDDINGS_PATH", fake_embeddings)
        monkeypatch.setattr(mod, "OUTPUT_PATH", output_path)
        monkeypatch.setattr(sys, "argv", ["check_embedding_dim.py", "--skip-api", "--expected-dim", "384"])

        before = datetime.now(timezone.utc)
        rc = mod.main()
        after = datetime.now(timezone.utc)

        assert rc == 0
        result = json.loads(output_path.read_text())
        ts = datetime.fromisoformat(result["verified_at"])
        assert before - timedelta(seconds=1) <= ts <= after + timedelta(seconds=1)

    def test_api_mismatch_detected_and_reported(self, tmp_path, fake_embeddings, monkeypatch, capsys):
        """When API returns wrong dim, exit 1 and stdout mentions FAIL."""
        output_path = tmp_path / ".embedding_dim_check.json"
        mod = _load_module()
        monkeypatch.setattr(mod, "EMBEDDINGS_PATH", fake_embeddings)
        monkeypatch.setattr(mod, "OUTPUT_PATH", output_path)
        monkeypatch.setattr(sys, "argv", ["check_embedding_dim.py", "--expected-dim", "384"])
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-key")

        # Monkeypatch probe_api_dim directly to return a mismatched dim
        monkeypatch.setattr(mod, "probe_api_dim", lambda target: 1536)

        rc = mod.main()

        assert rc == 1
        captured = capsys.readouterr()
        assert "FAIL" in captured.out
