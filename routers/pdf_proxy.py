"""
PDF proxy and resolver endpoints:
  GET  /api/pdf/proxy     - Proxy PDF downloads from allowed academic domains
  GET  /api/pdf/resolve   - Resolve a paper title/DOI to a PDF URL
  POST /api/pdf/resolve-batch - Batch resolve multiple papers
"""

import asyncio
import ipaddress
import logging
import os
import re
import socket
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .deps import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["pdf"])

# ── Constants ─────────────────────────────────────────────────────────

ALLOWED_DOMAINS: set[str] = {
    # Preprints
    "arxiv.org",
    "export.arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    # Publishers
    "ieeexplore.ieee.org",
    "dl.acm.org",
    "link.springer.com",
    "openaccess.thecvf.com",
    "proceedings.mlr.press",
    "proceedings.neurips.cc",
    "papers.nips.cc",
    "aclanthology.org",
    "www.nature.com",
    "www.science.org",
    "pnas.org",
    "journals.aps.org",
    "iopscience.iop.org",
    "www.mdpi.com",
    "www.frontiersin.org",
    "onlinelibrary.wiley.com",
    "www.sciencedirect.com",
    "academic.oup.com",
    "royalsocietypublishing.org",
    "journals.plos.org",
    "www.cell.com",
    "www.jmlr.org",
    "openreview.net",
    "eprint.iacr.org",
    "www.cambridge.org",
    "journals.sagepub.com",
    "www.tandfonline.com",
    "www.annualreviews.org",
    # Aggregators
    "ncbi.nlm.nih.gov",
    "europepmc.org",
    "core.ac.uk",
    "semanticscholar.org",
    "unpaywall.org",
    "pdfs.semanticscholar.org",
    "huggingface.co",
    "cdn-lfs.huggingface.co",
}

_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
_HTTPX_TIMEOUT = 30.0
_UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", "paperreview@example.com")

_MAX_REDIRECTS = 5

# ── Private-IP ranges for SSRF protection ────────────────────────────

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_private_ip(hostname: str) -> bool:
    """Return True if *hostname* resolves to a private/loopback IP address."""
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
        for family, _type, _proto, _canonname, sockaddr in addr_infos:
            ip = ipaddress.ip_address(sockaddr[0])
            for network in _PRIVATE_NETWORKS:
                if ip in network:
                    return True
    except (socket.gaierror, ValueError, OSError):
        # If we cannot resolve the hostname, treat it as blocked.
        return True
    return False


# ── Pydantic models ──────────────────────────────────────────────────

class PdfResolveResponse(BaseModel):
    pdf_url: Optional[str] = None
    source: Optional[str] = None


class PaperResolveRequest(BaseModel):
    title: str
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None


class BatchResolveRequest(BaseModel):
    papers: List[PaperResolveRequest]


class BatchResolveResponse(BaseModel):
    results: List[PdfResolveResponse]


# ── TTL Cache for resolve results ────────────────────────────────────

_RESOLVE_CACHE_MAXSIZE = 2000
_RESOLVE_CACHE_TTL = 6 * 3600  # 6 hours in seconds
_resolve_cache: Dict[str, Tuple[PdfResolveResponse, float]] = {}
_resolve_cache_lock = asyncio.Lock()


def _cache_key(title: str, doi: Optional[str]) -> str:
    """Build a normalised cache key from title and optional DOI."""
    key = title.strip().lower()
    if doi:
        key += "|" + doi.strip().lower()
    return key


async def _cache_get(title: str, doi: Optional[str]) -> Optional[PdfResolveResponse]:
    """Return a cached result if it exists and is still valid."""
    key = _cache_key(title, doi)
    async with _resolve_cache_lock:
        entry = _resolve_cache.get(key)
        if entry is None:
            return None
        result, ts = entry
        if time.monotonic() - ts > _RESOLVE_CACHE_TTL:
            del _resolve_cache[key]
            return None
        return result


async def _cache_put(title: str, doi: Optional[str], result: PdfResolveResponse) -> None:
    """Store a successful result in the cache, evicting oldest if full."""
    key = _cache_key(title, doi)
    async with _resolve_cache_lock:
        # Evict expired entries if we are at capacity
        if len(_resolve_cache) >= _RESOLVE_CACHE_MAXSIZE and key not in _resolve_cache:
            now = time.monotonic()
            expired_keys = [
                k for k, (_, ts) in _resolve_cache.items()
                if now - ts > _RESOLVE_CACHE_TTL
            ]
            for k in expired_keys:
                del _resolve_cache[k]
            # If still full, evict the oldest entry
            if len(_resolve_cache) >= _RESOLVE_CACHE_MAXSIZE:
                oldest_key = min(_resolve_cache, key=lambda k: _resolve_cache[k][1])
                del _resolve_cache[oldest_key]
        _resolve_cache[key] = (result, time.monotonic())


# ── Singleton httpx.AsyncClient (H-2) ────────────────────────────────

_http_client: Optional[httpx.AsyncClient] = None
_http_client_lock = asyncio.Lock()


async def _get_http_client() -> httpx.AsyncClient:
    """Return the module-level singleton AsyncClient, creating it on first call."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        async with _http_client_lock:
            # Double-check after acquiring the lock
            if _http_client is None or _http_client.is_closed:
                _http_client = httpx.AsyncClient(
                    follow_redirects=False,
                    timeout=_HTTPX_TIMEOUT,
                    limits=httpx.Limits(
                        max_connections=20,
                        max_keepalive_connections=10,
                    ),
                )
    return _http_client


async def close_http_client() -> None:
    """Close the singleton client. Call during application shutdown."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


# ── Helpers ───────────────────────────────────────────────────────────

_runtime_allowed_domains: set[str] = set()


def allow_domain_at_runtime(url: str) -> None:
    """Register a domain discovered via trusted resolve APIs (Unpaywall, S2)."""
    try:
        hostname = urlparse(url).hostname
        if hostname and not _is_private_ip(hostname):
            _runtime_allowed_domains.add(hostname)
    except Exception:
        pass


def _is_allowed_url(url: str) -> bool:
    """Return True if *url* has a safe scheme, non-private IP, and an allowed domain.

    Domains are allowed if they are in the static ALLOWED_DOMAINS set or were
    dynamically registered via ``allow_domain_at_runtime`` (i.e. URLs that our
    own resolve pipeline discovered from trusted academic APIs).
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname or ""
        all_allowed = ALLOWED_DOMAINS | _runtime_allowed_domains
        if not any(hostname == domain or hostname.endswith(f".{domain}") for domain in all_allowed):
            return False
        if _is_private_ip(hostname):
            return False
        return True
    except Exception:
        return False


def _extract_arxiv_id(text: str) -> Optional[str]:
    """Extract an arXiv ID (e.g. 2301.12345) from a string, or return None."""
    match = _ARXIV_ID_RE.search(text)
    if match:
        return match.group(0)
    return None


async def _resolve_final_url(
    client: httpx.AsyncClient,
    url: str,
) -> str:
    """Follow redirects via HEAD requests, re-validating SSRF at each hop.

    Returns the final URL after all redirects have been resolved.
    Raises HTTPException if any redirect targets a disallowed URL.
    """
    current_url = url
    for _ in range(_MAX_REDIRECTS):
        resp = await client.head(current_url)
        if resp.is_redirect:
            location = resp.headers.get("location")
            if not location:
                raise HTTPException(status_code=502, detail="Redirect without Location header")
            # Resolve relative redirects
            if not location.startswith(("http://", "https://")):
                location = urljoin(str(resp.url), location)
            if not _is_allowed_url(location):
                logger.warning("Blocked redirect to disallowed URL: %s", location)
                raise HTTPException(
                    status_code=403,
                    detail="Redirect target is not in the allowed domain list",
                )
            current_url = location
        else:
            return current_url
    raise HTTPException(status_code=502, detail="Too many redirects")


async def _resolve_single(
    client: httpx.AsyncClient,
    title: str,
    doi: Optional[str] = None,
    arxiv_id: Optional[str] = None,
) -> PdfResolveResponse:
    """Core resolution logic shared by single and batch endpoints."""

    # ── 0. Explicit arXiv ID (from paper metadata) ───────────────────
    if arxiv_id:
        clean_id = arxiv_id.split("v")[0]  # strip version suffix
        pdf_url = f"https://arxiv.org/pdf/{clean_id}.pdf"
        return PdfResolveResponse(pdf_url=pdf_url, source="arxiv")

    # ── 1. arXiv ID shortcut (from title text) ───────────────────────
    extracted_id = _extract_arxiv_id(title)
    if extracted_id:
        pdf_url = f"https://arxiv.org/pdf/{extracted_id}.pdf"
        return PdfResolveResponse(pdf_url=pdf_url, source="arxiv")

    # ── 2. Unpaywall (requires DOI) ──────────────────────────────────
    if doi:
        try:
            resp = await client.get(
                f"https://api.unpaywall.org/v2/{doi}?email={_UNPAYWALL_EMAIL}"
            )
            if resp.status_code == 200:
                best_oa = resp.json().get("best_oa_location") or {}
                pdf_url = best_oa.get("url_for_pdf") or best_oa.get("url")
                if pdf_url:
                    allow_domain_at_runtime(pdf_url)
                    return PdfResolveResponse(pdf_url=pdf_url, source="unpaywall")
        except httpx.RequestError as exc:
            logger.debug("Unpaywall request failed for DOI '%s': %s", doi, exc)

    # ── 3. Semantic Scholar (title search -> openAccessPdf) ───────────
    try:
        resp = await client.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": title, "fields": "openAccessPdf,externalIds", "limit": "1"},
        )
        if resp.status_code == 200:
            results = resp.json().get("data") or []
            if results:
                oa_pdf = results[0].get("openAccessPdf") or {}
                pdf_url = oa_pdf.get("url")
                if pdf_url:
                    allow_domain_at_runtime(pdf_url)
                    return PdfResolveResponse(pdf_url=pdf_url, source="semantic_scholar")
                # If S2 has an arXiv ID in externalIds, build URL from it
                ext_ids = results[0].get("externalIds") or {}
                s2_arxiv_id = ext_ids.get("ArXiv")
                if s2_arxiv_id:
                    return PdfResolveResponse(
                        pdf_url=f"https://arxiv.org/pdf/{s2_arxiv_id}.pdf",
                        source="arxiv",
                    )
    except httpx.RequestError as exc:
        logger.debug("Semantic Scholar request failed for '%s': %s", title[:50], exc)

    # ── 4. arXiv API title search (fallback) ─────────────────────────
    try:
        arxiv_search_url = (
            "https://export.arxiv.org/api/query"
            f"?search_query=ti:%22{quote(title)}%22&max_results=1"
        )
        resp = await client.get(arxiv_search_url)
        if resp.status_code == 200:
            body = resp.text
            # Extract arXiv ID from Atom XML <id> tag
            id_match = re.search(r"<id>http://arxiv\.org/abs/([^<]+)</id>", body)
            if id_match:
                found_id = id_match.group(1).strip()
                return PdfResolveResponse(
                    pdf_url=f"https://arxiv.org/pdf/{found_id}.pdf",
                    source="arxiv",
                )
    except httpx.RequestError as exc:
        logger.debug("arXiv API request failed for '%s': %s", title[:50], exc)

    return PdfResolveResponse(pdf_url=None, source=None)


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/pdf/proxy")
@limiter.limit("30/minute")
async def proxy_pdf(
    request: Request,
    url: str = Query(..., description="PDF URL to proxy"),
) -> StreamingResponse:
    """Proxy a PDF download from an allowed academic domain."""
    if not _is_allowed_url(url):
        raise HTTPException(
            status_code=400,
            detail="URL domain is not in the allowed list",
        )

    logger.info("Proxying PDF request: %s", url)

    client = await _get_http_client()

    # C-1: Resolve the final URL via HEAD requests, re-validating SSRF at each hop
    try:
        final_url = await _resolve_final_url(client, url)
    except httpx.TimeoutException:
        logger.warning("Timeout while resolving PDF redirects: %s", url)
        raise HTTPException(status_code=504, detail="Upstream PDF server timed out")
    except httpx.RequestError as exc:
        logger.error("Request error while resolving PDF redirects: %s - %s", url, exc)
        raise HTTPException(status_code=502, detail="Failed to reach the PDF server")

    # H-1: True streaming -- open a streaming connection to the final URL
    # and yield chunks without loading the entire body into memory.
    # We capture content-length from the stream's initial headers.
    async def _stream_pdf():
        try:
            async with client.stream("GET", final_url) as stream_resp:
                if stream_resp.status_code == 404:
                    raise HTTPException(status_code=404, detail="PDF not found at the given URL")
                if stream_resp.status_code >= 400:
                    logger.warning("Upstream returned %d for %s", stream_resp.status_code, final_url)
                    raise HTTPException(
                        status_code=502,
                        detail=f"Upstream server returned HTTP {stream_resp.status_code}",
                    )
                async for chunk in stream_resp.aiter_bytes(chunk_size=64 * 1024):
                    yield chunk
        except httpx.TimeoutException:
            logger.warning("Timeout while streaming PDF: %s", final_url)
        except httpx.RequestError as exc:
            logger.error("Streaming error for %s: %s", final_url, exc)

    # Use a HEAD request to get Content-Length for the response headers
    response_headers: dict[str, str] = {
        "Content-Disposition": "inline",
        "Cache-Control": "public, max-age=3600",
    }
    try:
        head_resp = await client.head(final_url)
        cl = head_resp.headers.get("content-length")
        if cl:
            response_headers["Content-Length"] = cl
    except httpx.RequestError as exc:
        logger.debug("HEAD request for Content-Length failed for %s: %s", final_url, exc)

    return StreamingResponse(
        _stream_pdf(),
        media_type="application/pdf",
        headers=response_headers,
    )


@router.get("/pdf/resolve", response_model=PdfResolveResponse)
@limiter.limit("20/minute")
async def resolve_pdf(
    request: Request,
    title: str = Query(..., description="Paper title to search for"),
    doi: Optional[str] = Query(None, description="DOI of the paper"),
    arxiv_id: Optional[str] = Query(None, description="arXiv ID of the paper"),
) -> PdfResolveResponse:
    """Try to find an open-access PDF URL for a paper."""
    # H-3: Check cache first
    cached = await _cache_get(title, doi)
    if cached is not None:
        logger.debug("Cache hit for resolve('%s')", title[:50])
        return cached

    client = await _get_http_client()
    result = await _resolve_single(client, title, doi, arxiv_id=arxiv_id)

    if result.pdf_url:
        logger.info("Resolved PDF for '%s': %s (%s)", title[:50], result.pdf_url, result.source)
        # Only cache successful results
        await _cache_put(title, doi, result)
    else:
        logger.info("Could not resolve PDF for '%s'", title[:50])
    return result


@router.post("/pdf/resolve-batch", response_model=BatchResolveResponse)
@limiter.limit("10/minute")
async def resolve_pdf_batch(
    request: Request,
    body: BatchResolveRequest,
) -> BatchResolveResponse:
    """Batch resolve PDF URLs for multiple papers.

    Runs up to 5 concurrent lookups. Each paper goes through the same
    resolution chain as the single endpoint (arXiv ID -> Unpaywall -> S2 -> arXiv search).
    """
    papers = body.papers[:20]  # Cap at 20 papers per batch
    semaphore = asyncio.Semaphore(5)
    client = await _get_http_client()

    # H-3: Check cache first, only resolve cache misses
    cached_results: Dict[int, PdfResolveResponse] = {}
    papers_to_resolve: List[Tuple[int, PaperResolveRequest]] = []

    for i, paper in enumerate(papers):
        cached = await _cache_get(paper.title, paper.doi)
        if cached is not None:
            cached_results[i] = cached
        else:
            papers_to_resolve.append((i, paper))

    if cached_results:
        logger.debug(
            "Batch resolve: %d/%d cache hits", len(cached_results), len(papers)
        )

    async def resolve_with_limit(paper: PaperResolveRequest) -> PdfResolveResponse:
        async with semaphore:
            return await _resolve_single(client, paper.title, paper.doi, arxiv_id=paper.arxiv_id)

    # Resolve only cache misses
    if papers_to_resolve:
        fetch_results = await asyncio.gather(
            *(resolve_with_limit(p) for _, p in papers_to_resolve),
            return_exceptions=True,
        )
    else:
        fetch_results = []

    # Merge cached and freshly resolved results
    resolved: List[PdfResolveResponse] = [PdfResolveResponse()] * len(papers)
    for i, result in cached_results.items():
        resolved[i] = result

    for (idx, paper), r in zip(papers_to_resolve, fetch_results):
        if isinstance(r, Exception):
            logger.warning("Batch resolve error for '%s': %s", paper.title[:50], r)
            resolved[idx] = PdfResolveResponse(pdf_url=None, source=None)
        else:
            resolved[idx] = r
            # Only cache successful results
            if r.pdf_url:
                await _cache_put(paper.title, paper.doi, r)

    found = sum(1 for r in resolved if r.pdf_url)
    logger.info("Batch resolve: %d/%d papers found PDF URLs", found, len(papers))
    return BatchResolveResponse(results=resolved)
