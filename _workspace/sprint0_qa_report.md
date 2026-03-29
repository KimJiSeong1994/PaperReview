# Sprint 0 QA Validation Report

**Date**: 2026-03-29
**Validator**: qa-validator
**Scope**: 7 files modified in Sprint 0 (infra hardening, auth security, FAISS startup)

---

## 1. Import Correctness

### 1.1 `routers/deps/auth.py` line 14: `from .config import ENVIRONMENT`
- **Status**: PASS
- **Evidence**: `routers/deps/config.py` line 33 defines `ENVIRONMENT = os.getenv("ENVIRONMENT", "development")`. Import path is correct (relative within `deps` package).

### 1.2 `routers/auth.py` line 17: `from .deps.auth import _decode_jwt`
- **Status**: PASS
- **Evidence**: `routers/deps/auth.py` line 31 defines `def _decode_jwt(request: Request) -> dict:`. The function is also re-exported via `routers/deps/__init__.py` line 43. Import path `from .deps.auth import _decode_jwt` is valid (auth.py is in `routers/`, importing from `routers/deps/auth.py`).

### 1.3 `routers/auth.py` line 16: `from .deps import ... _JWT_SECRET`
- **Status**: PASS
- **Evidence**: `routers/deps/__init__.py` line 42 re-exports `_JWT_SECRET` from `.auth`. The variable is defined in `routers/deps/auth.py` line 19 and conditionally assigned at line 26.

### 1.4 `api_server.py` line 67: `from src.graph.embedding_generator import EmbeddingGenerator`
- **Status**: PASS
- **Evidence**: `routers/deps/config.py` line 24 adds `PROJECT_ROOT / "src"` to `sys.path`. Since `api_server.py` imports from `routers` at line 29 (which triggers `routers/deps/__init__.py` -> `routers/deps/config.py`), `sys.path` is configured before the lazy import at line 67. Additionally, the import is inside a `try/except` block (lines 66-77) providing graceful fallback.

---

## 2. Existing Code Compatibility

### 2.1 `_JWT_SECRET` re-export chain
- **Status**: PASS
- **Flow**: `routers/deps/auth.py` defines `_JWT_SECRET` -> `routers/deps/__init__.py` re-exports it -> `routers/auth.py` imports via `from .deps import _JWT_SECRET`. Chain is unbroken.

### 2.2 `_decode_token` usage scope
- **Status**: PASS
- **Evidence**: Grep shows `_decode_token` is used in exactly 2 places, both within `routers/auth.py`:
  - Line 144: definition
  - Line 199: call in `verify_token` endpoint
- No external callers exist. The rename/delegation is fully contained within `routers/auth.py`.

### 2.3 Health check `"random-fallback"` value and `"healthy"` logic
- **Status**: FAIL (Minor - Degraded reporting is overly strict)
- **File**: `api_server.py` line 190
- **Code**: `status = "healthy" if all(v in ("ok", "configured") for v in checks.values()) else "degraded"`
- **Issue**: When `JWT_SECRET` is not set in development mode, `checks["jwt_secret"]` = `"random-fallback"`. This value is NOT in `("ok", "configured")`, so health reports `"degraded"` even though the app is fully functional in development.
- **Impact**: Monitoring systems may fire false alerts in development environments.
- **Fix**: Either:
  - (A) Add `"random-fallback"` to the healthy set: `v in ("ok", "configured", "random-fallback")`
  - (B) Report jwt_secret as `"configured (random)"` and keep the healthy set unchanged
  - (C) Only include the jwt_secret check when `ENVIRONMENT == "production"`

---

## 3. Security Verification

### 3.1 Production JWT_SECRET enforcement
- **Status**: PASS
- **File**: `routers/deps/auth.py` lines 20-27
- **Logic**: When `ENVIRONMENT == "production"` and `JWT_SECRET` is unset, `RuntimeError` is raised at module import time. This will crash the app on startup -- correct and desired behavior.
- **Note**: The `ENVIRONMENT` variable defaults to `"development"` (config.py line 33), so existing deployments without `ENVIRONMENT` set will NOT break.

### 3.2 LEGACY_PASSWORD_SALT missing -- safe degradation
- **Status**: PASS
- **File**: `routers/auth.py` lines 30-35, 50-51
- **Logic**: When `_LEGACY_PASSWORD_SALT` is empty string (default), line 50 evaluates `if not _LEGACY_PASSWORD_SALT:` as `True` and returns `False` immediately. Legacy SHA-256 passwords cannot be verified, but the app does not crash. A clear warning is logged at startup (lines 31-35).

### 3.3 `_decode_token` delegation preserves 401 error codes
- **Status**: PASS
- **File**: `routers/auth.py` lines 144-152
- **Logic**: `_decode_token` builds a fake `Request` with the token in the Authorization header, then calls `_decode_jwt(req)`. The `_decode_jwt` function (deps/auth.py lines 31-47) raises `HTTPException(status_code=401)` for all error cases:
  - Missing/invalid header -> 401
  - Expired token -> 401
  - Invalid token -> 401
  - Missing `sub` claim -> 401
- The `verify_token` endpoint (line 197-200) does NOT catch HTTPException, so 401 propagates to the caller correctly.
- **Note**: The fake Request construction (lines 146-151) creates a minimal ASGI scope. This works because `_decode_jwt` only accesses `request.headers.get("Authorization")`, which Starlette's Request correctly resolves from the scope headers.

---

## 4. FAISS Verification

### 4.1 `_ensure_faiss_index()` safe skip when embeddings.json missing
- **Status**: PASS
- **File**: `api_server.py` lines 62-63
- **Logic**: `if not json_path.exists(): return` with a `logger.warning` -- clean early return, no crash.

### 4.2 `_ensure_faiss_index()` exception handling
- **Status**: PASS
- **File**: `api_server.py` lines 66-77
- **Logic**: Entire rebuild wrapped in `try/except Exception`, logging warning on failure. Server continues startup.

### 4.3 `EmbeddingGenerator.rebuild_faiss_from_json` signature match
- **Status**: PASS
- **Call site** (api_server.py line 68-71): `EmbeddingGenerator.rebuild_faiss_from_json(json_path=str(json_path), output_dir=str(json_path.parent))`
- **Definition** (src/graph/embedding_generator.py line 197-200): `def rebuild_faiss_from_json(cls, json_path: str, output_dir: str) -> bool:`
- Parameters match exactly.

### 4.4 `SearchEngine` constructor accepts embeddings paths
- **Status**: PASS
- **Definition** (src/graph_rag/search_engine.py line 25): `def __init__(self, graph, embeddings_index_path: str = None, id_mapping_path: str = None)`
- **Call site** (routers/search.py lines 109-113): passes `embeddings_index_path` and `id_mapping_path` -- matches.

### 4.5 `GraphRAGAgent` constructor accepts embeddings paths
- **Status**: PASS
- **Definition** (app/GraphRAG/rag_agent.py lines 23-29): `def __init__(self, ..., embeddings_index_path: str = "...", id_mapping_path: str = "...", ...)`
- **Call site** (routers/deps/openai_client.py lines 33-39): passes all 5 parameters including `embeddings_index_path` and `id_mapping_path` -- matches.

---

## 5. ContextVars Verification

### 5.1 `_current_workspace` module-level declaration
- **Status**: PASS
- **File**: `app/DeepAgent/deep_review_agent.py` lines 31-33
- **Code**: `_current_workspace: contextvars.ContextVar[Optional[WorkspaceManager]] = contextvars.ContextVar('_current_workspace', default=None)`
- Module-level, typed, default=None.

### 5.2 Four tool functions use `_current_workspace.get(None)`
- **Status**: PASS
- **Evidence**:
  - `save_researcher_analysis` -- line 93: `workspace = _current_workspace.get(None)`
  - `get_all_analyses` -- line 119: `workspace = _current_workspace.get(None)`
  - `save_validation_result` -- line 142: `workspace = _current_workspace.get(None)`
  - `generate_final_report` -- line 167: `workspace = _current_workspace.get(None)`
- All 4 tools access via `.get(None)` and return error strings if workspace is None.

### 5.3 `_set_workspace_for_tools` uses `_current_workspace.set()`
- **Status**: PASS
- **File**: `app/DeepAgent/deep_review_agent.py` lines 1097-1099
- **Code**: `_current_workspace.set(self.workspace)` -- correct.
- Called at `__init__` time (line 1076) to set the default context.

### 5.4 `review_papers` uses `copy_context()` + `ctx.run()` pattern
- **Status**: PASS
- **File**: `app/DeepAgent/deep_review_agent.py` lines 1190-1195
- **Code**:
  ```python
  ctx = contextvars.copy_context()
  ctx.run(_current_workspace.set, self.workspace)
  result = ctx.run(self.agent.invoke, {"messages": [...]})
  ```
- This is the correct pattern: copy the current context, set the workspace in the copy, then run the agent within that isolated copy. This prevents workspace leaks across concurrent reviews.
- **Note**: The `_set_workspace_for_tools()` call in `__init__` (line 1076) sets the workspace in the *main* context. The `copy_context()` in `review_papers` creates an isolated copy that inherits this value and can override it safely. Both calls are complementary, not redundant.

---

## 6. `.env.example` Completeness

- **Status**: PASS
- `ENVIRONMENT=development` documented (line 6)
- `LEGACY_PASSWORD_SALT=` documented with explanation (line 12)
- Both new variables present with appropriate comments.

---

## Summary

| Category | Total | Pass | Fail | Notes |
|----------|-------|------|------|-------|
| Import Correctness | 4 | 4 | 0 | |
| Code Compatibility | 3 | 2 | 1 | Health check degraded in dev |
| Security | 3 | 3 | 0 | |
| FAISS | 5 | 5 | 0 | |
| ContextVars | 4 | 4 | 0 | |
| .env.example | 1 | 1 | 0 | |
| **Total** | **20** | **19** | **1** | |

---

## Issues Requiring Action

### ISSUE-1: Health check reports "degraded" in development mode [LOW]

- **File**: `/Users/gimjiseong/git/PaperReviewAgent/api_server.py` line 190
- **Severity**: Low (functional correctness unaffected, cosmetic/monitoring impact only)
- **Problem**: `"random-fallback"` is not in `("ok", "configured")`, causing `status = "degraded"` when JWT_SECRET is unset in development. This is technically correct (random secret IS degraded security), but may confuse developers or monitoring.
- **Recommended Fix**:
  ```python
  # Option A: Explicitly allow random-fallback as acceptable in health
  status = "healthy" if all(v in ("ok", "configured", "random-fallback") for v in checks.values()) else "degraded"

  # Option B: Keep strict — document that development mode shows "degraded" intentionally
  # (No code change, add comment explaining the intentional behavior)
  ```
- **Decision**: If "degraded" in development is intentional (defense-in-depth signal), add a comment. If not, apply Option A.

---

## Verification Not Performed (Out of Scope)

- Runtime integration test (server not running): Static analysis only. All import chains and function signatures verified by source inspection.
- Frontend impact: No frontend files were changed in Sprint 0. Backend-only changes.
- Database/persistence: No schema changes. User store (JSON) format unchanged.
