"""
PDF proxy and resolver endpoints:
  GET /api/pdf/proxy     - Proxy PDF downloads from allowed academic domains
  GET /api/pdf/resolve   - Resolve a paper title/DOI to a PDF URL
"""

import logging
import re
from typing import Optional
from urllib.parse import urlparse

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
    "biorxiv.org",
    "medrxiv.org",
    "ncbi.nlm.nih.gov",
    "europepmc.org",
    "core.ac.uk",
    "semanticscholar.org",
}

_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?$")
_HTTPX_TIMEOUT = 30.0
_UNPAYWALL_EMAIL = "paperreview@example.com"


# ── Pydantic models ──────────────────────────────────────────────────

class PdfResolveResponse(BaseModel):
    pdf_url: Optional[str] = None
    source: Optional[str] = None


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


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/pdf/proxy")
@limiter.limit("30/minute")
async def proxy_pdf(
    request: Request,
    url: str = Query(..., description="PDF URL to proxy"),
) -> StreamingResponse:
    """Proxy a PDF download from an allowed academic domain.

    This avoids CORS issues when the frontend needs to display PDFs
    hosted on third-party academic servers.
    """
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
    """Try to find an open-access PDF URL for a paper.

    Resolution strategy (first match wins):
    1. If *title* looks like an arXiv ID or contains 'arxiv', construct the URL directly.
    2. If *doi* is provided, query the Unpaywall API.
    3. Fall back to the Semantic Scholar API.
    """

    # ── 1. arXiv shortcut ─────────────────────────────────────────────
    arxiv_id = _extract_arxiv_id(title)
    if arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        logger.info("Resolved via arXiv ID: %s -> %s", arxiv_id, pdf_url)
        return PdfResolveResponse(pdf_url=pdf_url, source="arxiv")

    if "arxiv" in title.lower():
        # Try harder: look for an ID embedded somewhere in the title string
        for token in title.split():
            aid = _extract_arxiv_id(token)
            if aid:
                pdf_url = f"https://arxiv.org/pdf/{aid}.pdf"
                logger.info("Resolved via arXiv token: %s -> %s", aid, pdf_url)
                return PdfResolveResponse(pdf_url=pdf_url, source="arxiv")

    async with httpx.AsyncClient(follow_redirects=True, timeout=_HTTPX_TIMEOUT) as client:

        # ── 2. Unpaywall (requires DOI) ──────────────────────────────
        if doi:
            unpaywall_url = (
                f"https://api.unpaywall.org/v2/{doi}"
                f"?email={_UNPAYWALL_EMAIL}"
            )
            try:
                resp = await client.get(unpaywall_url)
                if resp.status_code == 200:
                    data = resp.json()
                    best_oa = data.get("best_oa_location") or {}
                    pdf_url = best_oa.get("url_for_pdf") or best_oa.get("url")
                    if pdf_url:
                        logger.info("Resolved via Unpaywall (DOI=%s): %s", doi, pdf_url)
                        return PdfResolveResponse(pdf_url=pdf_url, source="unpaywall")
                else:
                    logger.debug("Unpaywall returned %d for DOI=%s", resp.status_code, doi)
            except httpx.RequestError as exc:
                logger.warning("Unpaywall request failed for DOI=%s: %s", doi, exc)

        # ── 3. Semantic Scholar ───────────────────────────────────────
        s2_url = (
            "https://api.semanticscholar.org/graph/v1/paper/search"
            f"?query={title}&fields=openAccessPdf&limit=1"
        )
        try:
            resp = await client.get(s2_url)
            if resp.status_code == 200:
                results = resp.json().get("data") or []
                if results:
                    oa_pdf = results[0].get("openAccessPdf") or {}
                    pdf_url = oa_pdf.get("url")
                    if pdf_url:
                        logger.info("Resolved via Semantic Scholar: %s", pdf_url)
                        return PdfResolveResponse(pdf_url=pdf_url, source="semantic_scholar")
            else:
                logger.debug("Semantic Scholar returned %d for title=%s", resp.status_code, title)
        except httpx.RequestError as exc:
            logger.warning("Semantic Scholar request failed: %s", exc)

    # Nothing found
    logger.info("Could not resolve PDF for title=%s, doi=%s", title, doi)
    return PdfResolveResponse(pdf_url=None, source=None)
