#!/usr/bin/env python3
"""Require healthy service JSON and the expected published blog through SSR and API."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


_REVISION = re.compile(r"[0-9a-f]{40}\Z")


class ReadinessError(RuntimeError):
    """The deployed service does not satisfy the production readiness contract."""


def check_service_process(pid: int, proc_root: Path = Path("/proc")) -> None:
    """Verify exact argv tokens, never a substring that also accepts workers=10."""
    if pid <= 0:
        raise ReadinessError("service PID must be positive")
    try:
        argv = (proc_root / str(pid) / "cmdline").read_bytes().decode().split("\0")
    except (OSError, UnicodeError) as exc:
        raise ReadinessError("could not read managed service command") from exc
    workers = []
    for index, argument in enumerate(argv):
        if argument == "--workers":
            workers.append(argv[index + 1] if index + 1 < len(argv) else "")
        elif argument.startswith("--workers="):
            workers.append(argument.partition("=")[2])
    if workers != ["1"] or "api_server:app" not in argv or "--reload" in argv:
        raise ReadinessError(
            "managed service must run api_server:app with exactly one explicit worker"
        )


class _SsrParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.canonicals: list[str] = []
        self.h1_text: list[str] = []
        self.page_text: list[str] = []
        self.json_ld: list[str] = []
        self._h1_depth = 0
        self._json_ld_depth = 0
        self._article_depth = 0
        self._ignored_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style", "template", "noscript"}:
            if (
                not self._ignored_tags
                and tag == "script"
                and values.get("type") == "application/ld+json"
            ):
                self._json_ld_depth = 1
            self._ignored_tags.append(tag)
            return
        if self._ignored_tags:
            return
        if tag == "link" and "canonical" in (values.get("rel") or "").split():
            self.canonicals.append(values.get("href") or "")
        if tag == "h1":
            self._h1_depth += 1
        if tag == "div" and (
            self._article_depth
            or "blog-detail-content" in (values.get("class") or "").split()
        ):
            self._article_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_tags:
            if tag == self._ignored_tags[-1]:
                self._ignored_tags.pop()
                if tag == "script":
                    self._json_ld_depth = 0
            return
        if tag == "h1" and self._h1_depth:
            self._h1_depth -= 1
        if tag == "div" and self._article_depth:
            self._article_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._json_ld_depth:
            self.json_ld.append(data)
        elif self._ignored_tags:
            return
        elif self._h1_depth:
            self.h1_text.append(data)
        elif self._article_depth:
            self.page_text.append(data)


def _fetch(url: str, timeout: float) -> tuple[int, bytes, str]:
    request = Request(url, headers={"User-Agent": "paperreview-deploy-readiness/1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), response.headers.get_content_type()
    except HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get_content_type()
    except (OSError, URLError) as exc:
        raise ReadinessError(f"request failed for {url}: {exc}") from exc


def _expected_post(posts_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(posts_path.read_text(encoding="utf-8"))
        posts = payload["posts"]
        if not isinstance(posts, list):
            raise TypeError("posts must be a list")
        post = next(
            item
            for item in posts
            if isinstance(item, dict) and item.get("published") is True
        )
        required_strings = ("id", "title", "slug", "content")
        if any(
            not isinstance(post.get(field), str) or not post[field]
            for field in required_strings
        ):
            raise TypeError("published post has invalid required fields")
        if post.get("deep_content") is not None and not isinstance(
            post.get("deep_content"), str
        ):
            raise TypeError("published post deep_content must be a string or null")
    except (OSError, ValueError, KeyError, StopIteration, TypeError) as exc:
        raise ReadinessError(
            f"could not select a known published blog post: {exc}"
        ) from exc
    return post


def _json_object(body: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise ReadinessError(f"{label} response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ReadinessError(f"{label} response must be a JSON object")
    return value


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _content_probe(content: str) -> str:
    for paragraph in content.split("\n\n"):
        if paragraph.lstrip().startswith("#"):
            continue
        plain = re.sub(r"!?(?:\[([^]]+)\])\([^)]+\)", r"\1", paragraph)
        plain = re.sub(r"[#*`_>|~-]", " ", plain)
        normalized = _normalized_text(plain)
        if len(normalized) >= 32:
            return normalized[:80]
    return _normalized_text(content)[:80]


def _blog_posting_nodes(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    graph = value.get("@graph")
    nodes = graph if isinstance(graph, list) else [value]
    return [
        node
        for node in nodes
        if isinstance(node, dict)
        and (
            node.get("@type") == "BlogPosting"
            or "BlogPosting" in (node.get("@type") or [])
        )
    ]


def _check_ssr(body: bytes, expected: dict[str, Any], slug: str) -> None:
    try:
        document = body.decode("utf-8")
    except UnicodeError as exc:
        raise ReadinessError("published blog SSR is not UTF-8") from exc
    parser = _SsrParser()
    parser.feed(document)
    expected_path = f"/blog/{slug}"
    if (
        len(parser.canonicals) != 1
        or urlsplit(parser.canonicals[0]).path != expected_path
    ):
        raise ReadinessError(f"published blog SSR canonical does not identify {slug!r}")
    if _normalized_text("".join(parser.h1_text)) != _normalized_text(expected["title"]):
        raise ReadinessError(f"published blog SSR H1 does not match {slug!r}")
    page_text = _normalized_text(" ".join(parser.page_text))
    if _content_probe(expected["content"]) not in page_text:
        raise ReadinessError(
            f"published blog SSR main article text does not match {slug!r}"
        )

    postings: list[dict[str, Any]] = []
    for raw in parser.json_ld:
        try:
            postings.extend(_blog_posting_nodes(json.loads(raw)))
        except (ValueError, TypeError):
            continue
    if not any(
        node.get("headline") == expected["title"]
        and (
            not expected.get("deep_content")
            or node.get("articleBody") == expected["content"]
        )
        and urlsplit(str(node.get("url", ""))).path == expected_path
        for node in postings
    ):
        raise ReadinessError(
            f"published blog SSR structured data does not match {slug!r}"
        )


def check_ready(
    base_url: str,
    posts_path: Path,
    *,
    timeout: float,
    expected_revision: str | None = None,
    expected_pid: int | None = None,
    allow_legacy_attestation: bool = False,
) -> dict[str, Any]:
    if timeout <= 0:
        raise ReadinessError("request timeout must be positive")
    if expected_revision is not None and not _REVISION.fullmatch(expected_revision):
        raise ReadinessError("expected revision must be a full lowercase Git SHA")
    if expected_pid is not None and expected_pid <= 0:
        raise ReadinessError("expected PID must be positive")
    base = base_url.rstrip("/")
    expected = _expected_post(posts_path)
    slug = expected["slug"]
    encoded_slug = quote(slug, safe="")

    status, body, _ = _fetch(f"{base}/health", timeout)
    health = _json_object(body, label="health")
    if status != 200 or health.get("status") != "healthy":
        raise ReadinessError(
            f"health must be HTTP 200 with status=healthy, got {status} {health!r}"
        )
    has_revision = "deployment_revision" in health
    has_pid = "process_id" in health
    if has_revision != has_pid:
        raise ReadinessError("health deployment attestation is incomplete")
    if expected_revision is not None or expected_pid is not None:
        if expected_revision is None or expected_pid is None:
            raise ReadinessError("expected revision and PID must be supplied together")
        if not has_revision and allow_legacy_attestation:
            pass
        else:
            if health.get("deployment_revision") != expected_revision:
                raise ReadinessError(
                    f"health deployment revision must be {expected_revision}, "
                    f"got {health.get('deployment_revision')!r}"
                )
            if (
                type(health.get("process_id")) is not int
                or health.get("process_id") != expected_pid
            ):
                raise ReadinessError(
                    f"health process ID must be {expected_pid}, got {health.get('process_id')!r}"
                )

    status, body, _ = _fetch(f"{base}/blog/{encoded_slug}", timeout)
    if status != 200:
        raise ReadinessError(f"published blog SSR failed for {slug!r} (HTTP {status})")
    _check_ssr(body, expected, slug)

    status, body, _ = _fetch(f"{base}/api/blog/posts/{encoded_slug}", timeout)
    post = _json_object(body, label="published blog API")
    compared_fields = ("id", "title", "slug", "content", "deep_content", "published")
    mismatches = [
        field for field in compared_fields if post.get(field) != expected.get(field)
    ]
    if status != 200 or mismatches:
        raise ReadinessError(
            f"published blog API failed for {slug!r} (HTTP {status}, mismatches={mismatches})"
        )
    return health


def _write_health_metadata(path: Path, health: dict[str, Any]) -> None:
    revision = health.get("deployment_revision")
    process_id = health.get("process_id")
    has_attestation = "deployment_revision" in health and "process_id" in health
    if has_attestation and (
        not isinstance(revision, str)
        or not _REVISION.fullmatch(revision)
        or type(process_id) is not int
        or process_id <= 0
    ):
        raise ReadinessError("health deployment attestation has invalid types")
    payload = {
        "attestation_mode": "supported" if has_attestation else "legacy",
        "deployment_revision": revision if has_attestation else None,
        "process_id": process_id if has_attestation else None,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def wait_until_ready(
    base_url: str,
    posts_path: Path,
    *,
    timeout: float,
    attempts: int,
    interval: float,
    expected_revision: str | None = None,
    expected_pid: int | None = None,
    allow_legacy_attestation: bool = False,
    record_health_metadata: Path | None = None,
    deadline: float | None = None,
) -> None:
    if attempts < 1 or interval < 0 or deadline is not None and deadline <= 0:
        raise ReadinessError(
            "attempts and deadline must be positive; interval must be non-negative"
        )
    end = time.monotonic() + deadline if deadline is not None else None
    last_error: ReadinessError | None = None
    completed_attempts = 0
    for attempt in range(1, attempts + 1):
        remaining = end - time.monotonic() if end is not None else None
        if remaining is not None and remaining <= 0:
            break
        completed_attempts = attempt
        try:
            health = check_ready(
                base_url,
                posts_path,
                timeout=min(timeout, remaining) if remaining is not None else timeout,
                expected_revision=expected_revision,
                expected_pid=expected_pid,
                allow_legacy_attestation=allow_legacy_attestation,
            )
            if record_health_metadata is not None:
                _write_health_metadata(record_health_metadata, health)
            print(f"readiness passed on attempt {attempt}")
            return
        except ReadinessError as exc:
            last_error = exc
            if attempt < attempts:
                sleep_for = interval
                if end is not None:
                    sleep_for = min(sleep_for, max(0.0, end - time.monotonic()))
                if sleep_for:
                    time.sleep(sleep_for)
    raise ReadinessError(
        f"readiness failed after {completed_attempts} attempts: {last_error or 'deadline expired'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--posts", type=Path, required=True)
    parser.add_argument("--request-timeout", type=float, default=5)
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--interval", type=float, default=2)
    parser.add_argument("--deadline", type=float)
    parser.add_argument("--expected-revision")
    parser.add_argument("--expected-pid", type=int)
    parser.add_argument("--service-pid", type=int)
    parser.add_argument("--allow-legacy-attestation", action="store_true")
    parser.add_argument("--record-health-metadata", type=Path)
    args = parser.parse_args()
    try:
        if args.service_pid is not None:
            check_service_process(args.service_pid)
        wait_until_ready(
            args.base_url,
            args.posts,
            timeout=args.request_timeout,
            attempts=args.attempts,
            interval=args.interval,
            deadline=args.deadline,
            expected_revision=args.expected_revision,
            expected_pid=args.expected_pid,
            allow_legacy_attestation=args.allow_legacy_attestation,
            record_health_metadata=args.record_health_metadata,
        )
    except ReadinessError as exc:
        raise SystemExit(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
