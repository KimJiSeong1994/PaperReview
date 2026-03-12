"""
PDF proxy and resolver endpoints:
  GET  /api/pdf/proxy     - Proxy PDF downloads from allowed academic domains
  GET  /api/pdf/resolve   - Resolve a paper title/DOI to a PDF URL
  POST /api/pdf/resolve-batch - Batch resolve multiple papers
"""

import asyncio
import logging
import re
from typing import List, Optional
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .deps import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["pdf"])

# ── Constants ─────────────────────────────────────────────────────────

ALLOWED_DOMAINS: set[str] = {
    "arxiv.org",
    "export.arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "ncbi.nlm.nih.gov",
    "europepmc.org",
    "core.ac.uk",
    "semanticscholar.org",
    "dl.acm.org",
}

_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
_HTTPX_TIMEOUT = 30.0
_UNPAYWALL_EMAIL = "paperreview@example.com"


# ── Pydantic models ──────────────────────────────────────────────────

class PdfResolveResponse(BaseModel):
    pdf_url: Optional[str] = None
    source: Optional[str] = None


class PaperResolveRequest(BaseModel):
    title: str
    doi: Optional[str] = None


class BatchResolveRequest(BaseModel):
    papers: List[PaperResolveRequest]


class BatchResolveResponse(BaseModel):
    results: List[PdfResolveResponse]


# ── Helpers ───────────────────────────────────────────────────────────

def _is_allowed_url(url: str) -> bool:
    """Return True if *url* belongs to one of the allowed academic domains."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        return any(hostname == domain or hostname.endswith(f".{domain}") for domain in ALLOWED_DOMAINS)
    except Exception:
        return False


def _extract_arxiv_id(text: str) -> Optional[str]:
    """Extract an arXiv ID (e.g. 2301.12345) from a string, or return None."""
    match = _ARXIV_ID_RE.search(text)
    if match:
        return match.group(0)
    return None


async def _resolve_single(
    client: httpx.AsyncClient,
    title: str,
    doi: Optional[str] = None,
) -> PdfResolveResponse:
    """Core resolution logic shared by single and batch endpoints."""

    # ── 1. arXiv ID shortcut ──────────────────────────────────────────
    arxiv_id = _extract_arxiv_id(title)
    if arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
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
                    return PdfResolveResponse(pdf_url=pdf_url, source="unpaywall")
        except httpx.RequestError:
            pass

    # ── 3. Semantic Scholar (title search → openAccessPdf) ───────────
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
                    return PdfResolveResponse(pdf_url=pdf_url, source="semantic_scholar")
                # If S2 has an arXiv ID in externalIds, build URL from it
                ext_ids = results[0].get("externalIds") or {}
                s2_arxiv_id = ext_ids.get("ArXiv")
                if s2_arxiv_id:
                    return PdfResolveResponse(
                        pdf_url=f"https://arxiv.org/pdf/{s2_arxiv_id}.pdf",
                        source="arxiv",
                    )
    except httpx.RequestError:
        pass

    # ── 4. arXiv API title search (fallback) ─────────────────────────
    try:
        arxiv_search_url = (
            "http://export.arxiv.org/api/query"
            f"?search_query=ti:%22{quote(title)}%22&max_results=1"
        )
        resp = await client.get(arxiv_search_url)
        if resp.status_code == 200:
            body = resp.text
            # Extract arXiv ID from Atom XML <id> tag
            import re as _re
            id_match = _re.search(r"<id>http://arxiv\.org/abs/([^<]+)</id>", body)
            if id_match:
                found_id = id_match.group(1).strip()
                return PdfResolveResponse(
                    pdf_url=f"https://arxiv.org/pdf/{found_id}.pdf",
                    source="arxiv",
                )
    except httpx.RequestError:
        pass

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
            detail=f"URL domain is not in the allowed list: {ALLOWED_DOMAINS}",
        )

    logger.info("Proxying PDF request: %s", url)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=_HTTPX_TIMEOUT) as client:
            resp = await client.get(url)
    except httpx.TimeoutException:
        logger.warning("Timeout while fetching PDF: %s", url)
        raise HTTPException(status_code=504, detail="Upstream PDF server timed out")
    except httpx.RequestError as exc:
        logger.error("Request error while fetching PDF: %s – %s", url, exc)
        raise HTTPException(status_code=502, detail="Failed to reach the PDF server")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="PDF not found at the given URL")
    if resp.status_code >= 400:
        logger.warning("Upstream returned %d for %s", resp.status_code, url)
        raise HTTPException(
            status_code=502,
            detail=f"Upstream server returned HTTP {resp.status_code}",
        )

    return StreamingResponse(
        iter([resp.content]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/pdf/resolve", response_model=PdfResolveResponse)
@limiter.limit("20/minute")
async def resolve_pdf(
    request: Request,
    title: str = Query(..., description="Paper title to search for"),
    doi: Optional[str] = Query(None, description="DOI of the paper"),
) -> PdfResolveResponse:
    """Try to find an open-access PDF URL for a paper."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=_HTTPX_TIMEOUT) as client:
        result = await _resolve_single(client, title, doi)

    if result.pdf_url:
        logger.info("Resolved PDF for '%s': %s (%s)", title[:50], result.pdf_url, result.source)
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
    resolution chain as the single endpoint (arXiv ID → Unpaywall → S2 → arXiv search).
    """
    papers = body.papers[:20]  # Cap at 20 papers per batch
    semaphore = asyncio.Semaphore(5)

    async def resolve_with_limit(paper: PaperResolveRequest) -> PdfResolveResponse:
        async with semaphore:
            async with httpx.AsyncClient(follow_redirects=True, timeout=_HTTPX_TIMEOUT) as client:
                return await _resolve_single(client, paper.title, paper.doi)

    results = await asyncio.gather(
        *(resolve_with_limit(p) for p in papers),
        return_exceptions=True,
    )

    resolved = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.warning("Batch resolve error for '%s': %s", papers[i].title[:50], r)
            resolved.append(PdfResolveResponse(pdf_url=None, source=None))
        else:
            resolved.append(r)

    found = sum(1 for r in resolved if r.pdf_url)
    logger.info("Batch resolve: %d/%d papers found PDF URLs", found, len(papers))
    return BatchResolveResponse(results=resolved)
