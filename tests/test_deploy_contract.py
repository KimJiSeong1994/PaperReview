from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import check_deploy_ready


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
REVISION = "a" * 40


def test_deploy_requires_success_or_explicitly_unaffected_checks() -> None:
    workflow = WORKFLOW.read_text()
    deploy = workflow[workflow.index("  deploy:") :]
    condition = deploy[deploy.index("    if:") : deploy.index("    environment:")]
    assert (
        "needs: [changes, backend, skillopt-v020-exact-source, frontend-build]"
        in deploy
    )
    assert "always() && !cancelled()" in condition
    assert "needs.changes.result == 'success'" in condition
    assert "needs.backend.result == 'success'" in condition
    assert "needs.frontend-build.result == 'success'" in condition
    assert (
        "(needs.skillopt-v020-exact-source.result == 'success' || "
        "(needs.changes.outputs.skillopt == 'false' && "
        "needs.skillopt-v020-exact-source.result == 'skipped'))"
    ) in condition


def test_required_check_names_remain_and_main_always_builds_artifact() -> None:
    workflow = WORKFLOW.read_text()
    assert "\n  backend:\n" in workflow
    for job in ("skillopt-v020-exact-source", "frontend-build"):
        assert f"\n  {job}:\n    needs: changes\n" in workflow
    frontend = workflow[
        workflow.index("  frontend-build:") : workflow.index("  deploy:")
    ]
    assert (
        "if: github.event_name == 'push' || needs.changes.outputs.frontend == 'true'"
        in frontend
    )
    assert "actions/upload-artifact@v4" in frontend
    assert "name: frontend-dist" in frontend
    # Build already type-checks every referenced TypeScript project.
    scripts = json.loads((ROOT / "web-ui/package.json").read_text())["scripts"]
    assert scripts["build"].startswith("tsc -b &&")
    assert "run: npm run build" in frontend
    assert "run: npx tsc --noEmit" not in frontend


def test_only_superseded_pull_requests_are_cancelled() -> None:
    workflow = WORKFLOW.read_text()
    concurrency = workflow[: workflow.index("\njobs:")]
    assert (
        "group: ci-${{ github.event.pull_request.number || github.run_id }}"
        in concurrency
    )
    assert (
        "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in concurrency
    )
    deploy = workflow[workflow.index("  deploy:") :]
    assert "group: production-deploy" in deploy
    assert "cancel-in-progress: false" in deploy


def test_backend_retains_full_suite_and_coverage_gate() -> None:
    workflow = WORKFLOW.read_text()
    backend = workflow[
        workflow.index("  backend:") : workflow.index("  skillopt-v020-exact-source:")
    ]
    assert "needs: [backend-core, offline-optimizer, poster-browser]" in backend
    assert "if: always()" in backend
    assert "SHARD_NEEDS: ${{ toJSON(needs) }}" in backend
    assert "python scripts/ci_shards.py --aggregate ci-results" in backend
    for shard, following in (
        ("backend-core", "offline-optimizer"),
        ("offline-optimizer", "poster-browser"),
        ("poster-browser", "backend"),
    ):
        job = workflow[
            workflow.index(f"  {shard}:") : workflow.index(f"  {following}:")
        ]
        assert "\n    if:" not in job
        assert "\n    needs:" not in job
        assert f"pytest tests/ -p scripts.ci_shards --ci-shard={shard}" in job
        assert (
            "--cov=routers --cov=app --cov=src --cov-report= --cov-fail-under=0" in job
        )
        assert "--ignore" not in job and "--deselect" not in job
        assert "include-hidden-files: true" in job
        assert "if-no-files-found: error" in job
        upload = job[job.index("      - uses: actions/upload-artifact@v4") :]
        assert f"name: {shard}" in upload
        assert "overwrite: true" in upload
        assert "if:" not in upload
        assert "--torch-backend=cpu" in job
        assert f"name: {shard}" in backend
        if shard == "poster-browser":
            assert "playwright install --with-deps chromium" in job
            assert "CHROME_DEVEL_SANDBOX" in job
        else:
            assert "playwright install" not in job
    assert workflow.count("overwrite: true") == 3


def _post() -> dict[str, object]:
    return {
        "id": "post-id",
        "title": "Known Post",
        "slug": "known-post",
        "content": "A sufficiently distinctive readiness paragraph for the real article body.",
        "deep_content": "Deep article body",
        "published": True,
    }


def _posts_file(tmp_path: Path) -> Path:
    posts = tmp_path / "posts.json"
    posts.write_text(json.dumps({"posts": [_post()]}))
    return posts


def _ssr(post: dict[str, object] | None = None) -> bytes:
    value = post or _post()
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "BlogPosting",
                "headline": value["title"],
                "url": f"https://jiphyeonjeon.kr/blog/{value['slug']}",
                "articleBody": value["content"],
            }
        ],
    }
    return (
        "<html><head>"
        f'<link rel="canonical" href="https://jiphyeonjeon.kr/blog/{value["slug"]}">'
        f'<script type="application/ld+json">{json.dumps(graph)}</script>'
        "</head><body><main>"
        f"<h1>{value['title']}</h1>"
        f'<div class="blog-detail-content">{value["content"]}</div>'
        "</main></body></html>"
    ).encode()


def test_deploy_is_serialized_and_uses_exact_workflow_sha() -> None:
    workflow = WORKFLOW.read_text()
    deploy = workflow[workflow.index("  deploy:") :]
    assert "group: production-deploy" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "timeout-minutes: 15" in deploy
    assert "actions/checkout@v4" in deploy
    assert "ref: ${{ github.sha }}" in deploy
    assert 'git checkout --detach --force "$DEPLOY_SHA"' in workflow
    assert "DEPLOY_SHA: ${{ github.sha }}" in workflow
    assert "origin/main" not in deploy


def test_deploy_uses_release_namespace_worker_attestation_and_strict_readiness() -> (
    None
):
    workflow = WORKFLOW.read_text()[WORKFLOW.read_text().index("  deploy:") :]
    assert 'frontend_release.py" promote' in workflow
    assert 'frontend_release.py" rollback' in workflow
    assert "check_deploy_ready.py" in workflow
    assert "systemctl restart paperreview" in workflow
    assert workflow.count("systemctl restart paperreview") == 2
    assert workflow.count("check_deploy_ready.py") >= 4
    assert 'REMOTE_RELEASE="/tmp/paperreview-deploy-$RELEASE_ID"' in workflow
    assert "/tmp/paperreview-deploy-$DEPLOY_SHA" not in workflow
    assert '--expected-revision "$DEPLOY_SHA"' in workflow
    assert '--expected-revision "$PREVIOUS_SHA"' in workflow
    assert '--expected-pid "$SERVICE_PID"' in workflow
    assert "/proc/$SERVICE_PID/cmdline" in workflow
    assert workflow.count('--service-pid "$SERVICE_PID"') == 4
    assert "pkill" not in workflow
    assert "setsid" not in workflow
    assert "rm -rf" not in workflow
    assert "--workers 2" not in workflow


def test_failed_same_sha_rerun_has_distinct_remote_namespace() -> None:
    workflow = WORKFLOW.read_text()
    assert (
        "RELEASE_ID: deploy-${{ github.run_id }}-${{ github.run_attempt }}" in workflow
    )
    assert workflow.count('REMOTE_RELEASE="/tmp/paperreview-deploy-$RELEASE_ID"') >= 4


def test_first_rollback_records_and_branches_on_previous_health_capability() -> None:
    workflow = WORKFLOW.read_text()[WORKFLOW.read_text().index("  deploy:") :]
    assert "backend.previous.health.json" in workflow
    assert "--allow-legacy-attestation" in workflow
    assert (
        '--record-health-metadata "$REMOTE_RELEASE/backend.previous.health.json"'
        in workflow
    )
    assert 'if test "$ATTESTATION_MODE" = supported' in workflow
    assert 'elif test "$ATTESTATION_MODE" = legacy' in workflow
    assert 'test "$(git -C "$APP_ROOT" rev-parse HEAD)" = "$PREVIOUS_SHA"' in workflow
    assert (
        "backend.previous.health.json"
        in workflow[workflow.index("Roll back frontend") :]
    )


def test_readiness_requires_exact_health_ssr_and_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posts = _posts_file(tmp_path)
    seen: list[str] = []

    def fetch(url: str, timeout: float):
        seen.append(url)
        if url.endswith("/health"):
            return (
                200,
                json.dumps(
                    {
                        "status": "healthy",
                        "deployment_revision": REVISION,
                        "process_id": 42,
                    }
                ).encode(),
                "application/json",
            )
        if url.endswith("/api/blog/posts/known-post"):
            return 200, json.dumps(_post()).encode(), "application/json"
        return 200, _ssr(), "text/html"

    monkeypatch.setattr(check_deploy_ready, "_fetch", fetch)
    check_deploy_ready.check_ready(
        "http://127.0.0.1:8000",
        posts,
        timeout=1,
        expected_revision=REVISION,
        expected_pid=42,
    )
    assert [url.rsplit("/", 1)[-1] for url in seen] == [
        "health",
        "known-post",
        "known-post",
    ]


def test_legacy_preflight_records_capability_without_revision_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = tmp_path / "previous-health.json"

    def fetch(url: str, timeout: float):
        if url.endswith("/health"):
            return 200, b'{"status":"healthy"}', "application/json"
        if url.endswith("/api/blog/posts/known-post"):
            return 200, json.dumps(_post()).encode(), "application/json"
        return 200, _ssr(), "text/html"

    monkeypatch.setattr(check_deploy_ready, "_fetch", fetch)
    check_deploy_ready.wait_until_ready(
        "http://127.0.0.1:8000",
        _posts_file(tmp_path),
        timeout=1,
        attempts=1,
        interval=0,
        expected_revision=REVISION,
        expected_pid=42,
        allow_legacy_attestation=True,
        record_health_metadata=metadata,
    )
    assert json.loads(metadata.read_text()) == {
        "attestation_mode": "legacy",
        "deployment_revision": None,
        "process_id": None,
    }


def test_attested_preflight_records_previous_revision_and_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = tmp_path / "previous-health.json"

    def fetch(url: str, timeout: float):
        if url.endswith("/health"):
            health = {
                "status": "healthy",
                "deployment_revision": REVISION,
                "process_id": 42,
            }
            return 200, json.dumps(health).encode(), "application/json"
        if url.endswith("/api/blog/posts/known-post"):
            return 200, json.dumps(_post()).encode(), "application/json"
        return 200, _ssr(), "text/html"

    monkeypatch.setattr(check_deploy_ready, "_fetch", fetch)
    check_deploy_ready.wait_until_ready(
        "http://127.0.0.1:8000",
        _posts_file(tmp_path),
        timeout=1,
        attempts=1,
        interval=0,
        expected_revision=REVISION,
        expected_pid=42,
        allow_legacy_attestation=True,
        record_health_metadata=metadata,
    )
    assert json.loads(metadata.read_text()) == {
        "attestation_mode": "supported",
        "deployment_revision": REVISION,
        "process_id": 42,
    }


@pytest.mark.parametrize("health", [[], "healthy", {"status": ["healthy"]}])
def test_readiness_wraps_invalid_health_json_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, health: object
) -> None:
    monkeypatch.setattr(
        check_deploy_ready,
        "_fetch",
        lambda url, timeout: (200, json.dumps(health).encode(), "application/json"),
    )
    with pytest.raises(check_deploy_ready.ReadinessError):
        check_deploy_ready.check_ready(
            "http://127.0.0.1:8000", _posts_file(tmp_path), timeout=1
        )


def test_legacy_preflight_rejects_partial_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    health = {"status": "healthy", "deployment_revision": REVISION}
    monkeypatch.setattr(
        check_deploy_ready,
        "_fetch",
        lambda url, timeout: (200, json.dumps(health).encode(), "application/json"),
    )
    with pytest.raises(check_deploy_ready.ReadinessError, match="incomplete"):
        check_deploy_ready.check_ready(
            "http://127.0.0.1:8000",
            _posts_file(tmp_path),
            timeout=1,
            expected_revision=REVISION,
            expected_pid=42,
            allow_legacy_attestation=True,
        )


@pytest.mark.parametrize(
    "health",
    [
        {"status": "healthy", "deployment_revision": "b" * 40, "process_id": 42},
        {"status": "healthy", "deployment_revision": REVISION, "process_id": 43},
        {"status": "healthy", "deployment_revision": REVISION, "process_id": "42"},
    ],
)
def test_readiness_rejects_wrong_revision_or_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, health: dict[str, object]
) -> None:
    monkeypatch.setattr(
        check_deploy_ready,
        "_fetch",
        lambda url, timeout: (200, json.dumps(health).encode(), "application/json"),
    )
    with pytest.raises(check_deploy_ready.ReadinessError):
        check_deploy_ready.check_ready(
            "http://127.0.0.1:8000",
            _posts_file(tmp_path),
            timeout=1,
            expected_revision=REVISION,
            expected_pid=42,
        )


@pytest.mark.parametrize(
    "bad_ssr", [b"<html>known-post</html>", _ssr({**_post(), "slug": "other"})]
)
def test_readiness_rejects_soft_404_or_wrong_article(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_ssr: bytes
) -> None:
    def fetch(url: str, timeout: float):
        if url.endswith("/health"):
            return 200, b'{"status":"healthy"}', "application/json"
        return 200, bad_ssr, "text/html"

    monkeypatch.setattr(check_deploy_ready, "_fetch", fetch)
    with pytest.raises(check_deploy_ready.ReadinessError, match="SSR"):
        check_deploy_ready.check_ready(
            "http://127.0.0.1:8000", _posts_file(tmp_path), timeout=1
        )


def test_readiness_rejects_api_content_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrong = {**_post(), "content": "wrong article"}

    def fetch(url: str, timeout: float):
        if url.endswith("/health"):
            return 200, b'{"status":"healthy"}', "application/json"
        if "/api/" in url:
            return 200, json.dumps(wrong).encode(), "application/json"
        return 200, _ssr(), "text/html"

    monkeypatch.setattr(check_deploy_ready, "_fetch", fetch)
    with pytest.raises(check_deploy_ready.ReadinessError, match="content"):
        check_deploy_ready.check_ready(
            "http://127.0.0.1:8000", _posts_file(tmp_path), timeout=1
        )


def test_wait_deadline_caps_request_and_sleep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = iter([10.0, 10.0, 10.2, 10.2, 10.5, 10.5])
    timeouts: list[float] = []
    sleeps: list[float] = []
    monkeypatch.setattr(check_deploy_ready.time, "monotonic", lambda: next(clock))

    def fail(*args, timeout: float, **kwargs):
        timeouts.append(timeout)
        raise check_deploy_ready.ReadinessError("still starting")

    monkeypatch.setattr(check_deploy_ready, "check_ready", fail)
    monkeypatch.setattr(check_deploy_ready.time, "sleep", sleeps.append)
    with pytest.raises(check_deploy_ready.ReadinessError):
        check_deploy_ready.wait_until_ready(
            "http://127.0.0.1:8000",
            _posts_file(tmp_path),
            timeout=5,
            attempts=3,
            interval=2,
            deadline=1,
        )
    assert timeouts and all(timeout <= 1 for timeout in timeouts)
    assert sleeps and all(sleep <= 1 for sleep in sleeps)


@pytest.mark.parametrize(
    "arguments,accepted",
    [
        (["uvicorn", "api_server:app", "--workers", "1"], True),
        (["uvicorn", "api_server:app", "--workers=1"], True),
        (["uvicorn", "api_server:app", "--workers", "10"], False),
        (["uvicorn", "api_server:app", "--workers", "1", "--workers", "2"], False),
        (["uvicorn", "api_server:app", "--workers=2"], False),
        (["uvicorn", "api_server:app"], False),
        (["uvicorn", "api_server:app", "--workers", "1", "--reload"], False),
        (["uvicorn", "other:app", "--workers", "1"], False),
    ],
)
def test_single_worker_contract_uses_exact_process_arguments(
    tmp_path, arguments, accepted
):
    process = tmp_path / "123"
    process.mkdir()
    (process / "cmdline").write_bytes(("\0".join(arguments) + "\0").encode())
    if accepted:
        check_deploy_ready.check_service_process(123, tmp_path)
    else:
        with pytest.raises(check_deploy_ready.ReadinessError):
            check_deploy_ready.check_service_process(123, tmp_path)


@pytest.mark.parametrize(
    "container", ["bootstrap", "script", "style", "template", "footer"]
)
def test_readiness_requires_article_text_not_inert_state_or_footer(container):
    post = _post()
    body = str(post["content"])
    hidden = {
        "bootstrap": '<script id="blog-bootstrap" type="application/json">'
        + json.dumps({"post": post})
        + "</script>",
        "script": "<script>" + body + "</script>",
        "style": "<style>/*" + body + "*/</style>",
        "template": "<template><div>" + body + "</div></template>",
        "footer": "<footer>" + body + "</footer>",
    }[container]
    original = _ssr(post).decode()
    visible = '<div class="blog-detail-content">' + body + "</div>"
    assert visible in original
    replacement = '<div class="blog-detail-content">' + hidden + "</div>"
    if container == "footer":
        replacement = '<div class="blog-detail-content"></div>' + hidden
    document = original.replace(visible, replacement)
    with pytest.raises(check_deploy_ready.ReadinessError):
        check_deploy_ready._check_ssr(document.encode(), post, str(post["slug"]))
