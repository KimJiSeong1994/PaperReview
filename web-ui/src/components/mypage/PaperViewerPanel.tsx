import { useState, useCallback, useRef, useEffect, memo } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import { resolvePdfUrl, batchResolvePdfUrls, getS2ReaderUrl, generatePdfHighlights, explainMathFormula } from '../../api/client';
import type { HighlightItem, MathExplanation } from '../../api/client';
import './PaperViewerPanel.css';

// Configure pdf.js worker via CDN (avoids Vite bundling issues with import.meta.url)
pdfjs.GlobalWorkerOptions.workerSrc = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

// ── Types ──────────────────────────────────────────────────────────────

interface BookmarkPaper {
  title: string;
  authors: string[];
  year?: number | string;
  pdf_url?: string | null;
  doi?: string | null;
  arxiv_id?: string | null;
  url?: string | null;
  source?: string | null;
  review?: Record<string, unknown>;
  review_highlights?: Record<string, unknown>[];
}

interface ResolvedUrl {
  pdf_url: string | null;
  source: string | null;
}

export interface PaperViewerPanelProps {
  bookmarkDetail: Record<string, unknown> | null;
  loadingDetail: boolean;
  hasSelectedBookmark: boolean;
  autoSelectFirst?: boolean;
}

// ── Helpers ────────────────────────────────────────────────────────────

const ZOOM_STEP = 0.15;
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3.0;
const ZOOM_DEFAULT = 1.0;
const PAGE_BUFFER = 2; // render ±2 pages around the visible one
const ESTIMATED_PAGE_HEIGHT = 1100; // fallback height for placeholder pages

/** Memoised wrapper – only re-renders when its own props change. */
const MemoPage = memo(function MemoPage({
  pageNumber,
  scale,
  width,
}: {
  pageNumber: number;
  scale?: number;
  width?: number;
}) {
  return (
    <Page
      pageNumber={pageNumber}
      scale={scale}
      width={width}
      renderTextLayer={true}
      renderAnnotationLayer={true}
    />
  );
});

function buildPdfSrc(pdfUrl: string): string {
  try {
    const hostname = new URL(pdfUrl).hostname;
    if (hostname === 'arxiv.org' || hostname.endsWith('.arxiv.org')) {
      return pdfUrl;
    }
  } catch {
    // Invalid URL — fall through to proxy
  }
  return `/api/pdf/proxy?url=${encodeURIComponent(pdfUrl)}`;
}

function formatAuthors(authors: string[]): string {
  if (!authors || authors.length === 0) return '';
  if (authors.length === 1) return authors[0];
  if (authors.length === 2) return authors.join(', ');
  return `${authors[0]} et al.`;
}

function paperExternalUrl(paper: BookmarkPaper): string | null {
  if (paper.doi) return `https://doi.org/${paper.doi}`;
  if (paper.url) return paper.url;
  return null;
}

// ── Icons (inline SVGs, no external dependency) ───────────────────────

function IconFilePdf() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
      <path d="M4 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V5.5L9.5 0H4zm5.5 1.5v3h3L9.5 1.5zM4.5 8.5h.75c.69 0 1.25.56 1.25 1.25S5.94 11 5.25 11H4.5V8.5zm.75 1.5h-.25v-.5h.25c.138 0 .25.112.25.25S5.388 10 5.25 10zM7 8.5h.9c.33 0 .6.27.6.6v1.3c0 .33-.27.6-.6.6H7V8.5zm.5.5v1h.4a.1.1 0 0 0 .1-.1V9.1a.1.1 0 0 0-.1-.1H7.5zm1.5 0h1.25v.5H9.5v.25h.75V10H9.5V11H9V8.5h1z" />
    </svg>
  );
}

function IconFileText() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  );
}

function IconChevronLeft() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="15 18 9 12 15 6" />
    </svg>
  );
}

function IconChevronRight() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function IconZoomIn() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
      <line x1="11" y1="8" x2="11" y2="14" />
      <line x1="8" y1="11" x2="14" y2="11" />
    </svg>
  );
}

function IconZoomOut() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
      <line x1="8" y1="11" x2="14" y2="11" />
    </svg>
  );
}

function IconExternalLink() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  );
}

function IconAlertCircle() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  );
}

function IconFitWidth() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 9V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v4" />
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <line x1="7" y1="12" x2="17" y2="12" />
      <polyline points="10 9 7 12 10 15" />
      <polyline points="14 9 17 12 14 15" />
    </svg>
  );
}

function IconBookOpen() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
      <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
    </svg>
  );
}

// ── Component ──────────────────────────────────────────────────────────

export default function PaperViewerPanel({
  bookmarkDetail,
  loadingDetail,
  hasSelectedBookmark,
  autoSelectFirst = false,
}: PaperViewerPanelProps) {
  const papers: BookmarkPaper[] = bookmarkDetail?.papers ?? [];


  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [numPages, setNumPages] = useState<number | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInputValue, setPageInputValue] = useState('1');
  const [zoom, setZoom] = useState(ZOOM_DEFAULT);
  const [fitWidth, setFitWidth] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [documentKey, setDocumentKey] = useState(0);

  // Semantic Reader fallback state
  const [readerUrl, setReaderUrl] = useState<string | null>(null);

  // PDF overlay highlight state
  const [pdfHighlights, setPdfHighlights] = useState<HighlightItem[]>([]);
  const [highlightingPdf, setHighlightingPdf] = useState(false);

  // Auto-resolve: cache of resolved pdf_urls keyed by paper title
  const [resolvedUrls, setResolvedUrls] = useState<Record<string, ResolvedUrl>>({});
  const [resolving, setResolving] = useState(false);
  const [resolveProgress, setResolveProgress] = useState<{ done: number; total: number } | null>(null);

  // PDF highlight popover state
  const [hlPopover, setHlPopover] = useState<{ hl: HighlightItem; x: number; y: number } | null>(null);

  // Math formula popover state
  const [mathPopover, setMathPopover] = useState<{
    x: number;
    y: number;
    loading: boolean;
    explanation?: MathExplanation;
    formulaText: string;
  } | null>(null);

  const pdfAreaRef = useRef<HTMLDivElement>(null);
  const docScrollRef = useRef<HTMLDivElement>(null);
  const pdfDocRef = useRef<{ numPages: number; getPage: (i: number) => Promise<{ getTextContent: () => Promise<{ items: { str: string; transform: number[] }[] }> }> } | null>(null);
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const pageHeights = useRef<Map<number, number>>(new Map());
  const isScrollingToPage = useRef(false);
  const [visiblePages, setVisiblePages] = useState<Set<number>>(new Set([1, 2, 3]));
  const zoomRafRef = useRef<number | null>(null);
  const pendingZoomRef = useRef<number | null>(null);
  const [containerWidth, setContainerWidth] = useState<number>(600);

  // H-4: track the index for which we last started resolving, to discard stale results
  const resolveRequestIndexRef = useRef<number | null>(null);
  // H-5: track whether auto-select has fired for the current bookmarkDetail
  const autoSelectTriggered = useRef(false);

  // Reset viewer state AND auto-resolve PDF URLs in a single effect
  // to avoid race conditions between separate reset/resolve effects
  useEffect(() => {
    // ── Reset all viewer state ──
    setSelectedIndex(null);
    setNumPages(null);
    setCurrentPage(1);
    setPageInputValue('1');
    setZoom(ZOOM_DEFAULT);
    setFitWidth(false);
    setPdfError(null);
    setPdfLoading(false);
    setDocumentKey(0);
    setResolvedUrls({});
    setResolving(false);
    setResolveProgress(null);
    setReaderUrl(null);
    // H-5: reset auto-select trigger so the first paper is re-selected on new bookmark
    autoSelectTriggered.current = false;
    resolveRequestIndexRef.current = null;

    // ── Auto-resolve PDF URLs for papers without pdf_url ──
    const currentPapers: BookmarkPaper[] = bookmarkDetail?.papers ?? [];
    if (currentPapers.length === 0) return;

    const needResolve = currentPapers.filter(p => !p.pdf_url);
    if (needResolve.length === 0) return;

    let cancelled = false;
    setResolving(true);
    setResolveProgress({ done: 0, total: needResolve.length });

    (async () => {
      try {
        const data = await batchResolvePdfUrls(
          needResolve.map(p => ({ title: p.title, doi: p.doi || undefined, arxiv_id: p.arxiv_id || undefined })),
        );
        if (cancelled) return;

        const newResolved: Record<string, ResolvedUrl> = {};
        let doneCount = 0;
        needResolve.forEach((paper, i) => {
          const r = data.results?.[i];
          if (r?.pdf_url) {
            newResolved[paper.title] = { pdf_url: r.pdf_url, source: r.source };
            doneCount++;
          }
        });
        setResolvedUrls(newResolved);
        setResolveProgress({ done: doneCount, total: needResolve.length });
      } catch (err) {
        console.error('PDF batch resolve error:', err);
      } finally {
        if (!cancelled) setResolving(false);
      }
    })();

    return () => { cancelled = true; };
  }, [bookmarkDetail]);

  // Track container width for fit-width mode
  useEffect(() => {
    const el = docScrollRef.current;
    if (!el) return;
    const obs = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        // Subtract padding (2 * 16px)
        setContainerWidth(Math.max(300, entry.contentRect.width - 32));
      }
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // Track visible page + virtualization via IntersectionObserver
  useEffect(() => {
    const scrollEl = docScrollRef.current;
    if (!scrollEl || !numPages) return;

    const intersecting = new Set<number>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const page = Number(entry.target.getAttribute('data-page'));
          if (isNaN(page)) continue;
          if (entry.isIntersecting) intersecting.add(page);
          else intersecting.delete(page);
        }

        if (intersecting.size === 0) return;

        // Update current page (most visible)
        if (!isScrollingToPage.current) {
          const best = Math.min(...intersecting);
          setCurrentPage(best);
          setPageInputValue(String(best));
        }

        // Build render window: visible pages ± buffer
        const minPage = Math.min(...intersecting);
        const maxPage = Math.max(...intersecting);
        const renderFrom = Math.max(1, minPage - PAGE_BUFFER);
        const renderTo = Math.min(numPages, maxPage + PAGE_BUFFER);
        const newVisible = new Set<number>();
        for (let p = renderFrom; p <= renderTo; p++) newVisible.add(p);
        setVisiblePages(newVisible);
      },
      { root: scrollEl, rootMargin: '200px 0px', threshold: 0 },
    );

    pageRefs.current.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [numPages, documentKey]);

  const selectedPaper = selectedIndex !== null ? papers[selectedIndex] ?? null : null;

  // Get effective pdf_url: from paper data or resolved cache
  const getEffectivePdfUrl = (paper: BookmarkPaper | null): string | null => {
    if (!paper) return null;
    if (paper.pdf_url) return paper.pdf_url;
    return resolvedUrls[paper.title]?.pdf_url ?? null;
  };

  const effectivePdfUrl = getEffectivePdfUrl(selectedPaper);
  const pdfSrc = effectivePdfUrl ? buildPdfSrc(effectivePdfUrl) : null;

  // On-demand resolve: when clicking a paper without pdf_url, resolve individually
  // H-4: uses a ref to track the "current" request index; stale responses are silently dropped
  // Fetch S2 Reader URL for a paper (fire-and-forget, updates readerUrl state)
  const fetchReaderUrl = useCallback(async (paper: BookmarkPaper, requestIndex: number) => {
    setReaderUrl(null);
    try {
      const result = await getS2ReaderUrl(
        paper.title,
        paper.doi || undefined,
        paper.arxiv_id || undefined,
      );
      if (resolveRequestIndexRef.current !== requestIndex) return;
      setReaderUrl(result.reader_url);
      // If S2 returned a PDF URL and we don't have one yet, use it as fallback
      if (result.pdf_url && !paper.pdf_url && !resolvedUrls[paper.title]?.pdf_url) {
        setResolvedUrls(prev => ({
          ...prev,
          [paper.title]: { pdf_url: result.pdf_url!, source: 'semantic_scholar' },
        }));
      }
    } catch {
      // Ignore — reader link simply won't appear
    }
  }, [resolvedUrls]);

  const resolveAndSelect = useCallback(async (index: number) => {
    // Mark this as the active request, cancelling any in-flight prior request
    resolveRequestIndexRef.current = index;
    const requestIndex = index;

    setSelectedIndex(index);
    setNumPages(null);
    setCurrentPage(1);
    setPageInputValue('1');
    setPdfError(null);
    setDocumentKey(k => k + 1);
    setPdfHighlights([]);
    setHlPopover(null);
    setMathPopover(null);

    const paper = papers[index];
    if (!paper) return;

    // Fetch S2 Reader URL in parallel
    fetchReaderUrl(paper, requestIndex);

    // Already has pdf_url (from data or resolved cache)
    if (paper.pdf_url || resolvedUrls[paper.title]?.pdf_url) {
      setPdfLoading(true);
      return;
    }

    // Try to resolve on-demand via api client
    setPdfLoading(true);
    try {
      const data = await resolvePdfUrl(paper.title, paper.doi || undefined, paper.arxiv_id || undefined);
      // H-4: discard result if a newer selection was made while we were awaiting
      if (resolveRequestIndexRef.current !== requestIndex) return;
      if (data.pdf_url) {
        setResolvedUrls(prev => ({
          ...prev,
          [paper.title]: { pdf_url: data.pdf_url, source: data.source },
        }));
        return;
      }
    } catch {
      // Ignore errors — will show "not available"
      if (resolveRequestIndexRef.current !== requestIndex) return;
    }
    setPdfLoading(false);
  }, [papers, resolvedUrls, fetchReaderUrl]);

  // Auto-select first paper when autoSelectFirst is enabled (e.g., from search results)
  useEffect(() => {
    if (autoSelectFirst && papers.length > 0 && !autoSelectTriggered.current) {
      autoSelectTriggered.current = true;
      resolveAndSelect(0);
    }
  }, [autoSelectFirst, papers.length, resolveAndSelect]);

  // PDF text extraction helper — uses position info to restore line breaks and spacing (up to 40 pages)
  const extractPdfText = useCallback(async (pdfDoc: { numPages: number; getPage: (i: number) => Promise<{ getTextContent: () => Promise<{ items: { str: string; transform: number[] }[] }> }> }): Promise<string> => {
    const pages: string[] = [];
    const maxPages = Math.min(pdfDoc.numPages, 40);
    for (let i = 1; i <= maxPages; i++) {
      const page = await pdfDoc.getPage(i);
      const content = await page.getTextContent();
      const items = content.items;

      // Use position info to reconstruct line breaks and word spacing
      let pageText = '';
      let lastY: number | null = null;
      let lastRight = 0;

      for (const item of items) {
        if (!item.str) continue;
        const [, , , , tx, ty] = item.transform; // transform matrix [a,b,c,d,tx,ty]
        const fontSize = Math.abs(item.transform[0]) || 12;

        if (lastY !== null) {
          const yDiff = Math.abs(ty - lastY);
          if (yDiff > fontSize * 0.5) {
            // Line break
            pageText += '\n';
            lastRight = 0;
          } else {
            // Same line — insert space based on gap
            const gap = tx - lastRight;
            if (gap > fontSize * 0.3) {
              pageText += ' ';
            }
          }
        }

        pageText += item.str;
        lastY = ty;
        lastRight = tx + (item.width || item.str.length * fontSize * 0.5);
      }

      pages.push(pageText);
    }
    return pages.join('\n\n');
  }, []);

  // PDF overlay highlight handler — extract text from PDF and call LLM
  const handleAutoHighlightPdf = useCallback(async () => {
    if (!pdfDocRef.current) return;
    setHighlightingPdf(true);
    try {
      const text = await extractPdfText(pdfDocRef.current);
      const title = selectedPaper?.title || '';
      const result = await generatePdfHighlights(text, title);
      setPdfHighlights(result.highlights);
    } catch (err) {
      console.error('PDF highlight failed:', err);
    } finally {
      setHighlightingPdf(false);
    }
  }, [selectedPaper, extractPdfText]);

  // Apply PDF overlay highlights onto the react-pdf text layer spans.
  // Uses global text construction across all pages for cross-page matching,
  // plus MutationObserver for auto-reapply when new text layers render.
  useEffect(() => {
    const scrollEl = docScrollRef.current;
    if (!scrollEl) return;

    // Normalise common ligature characters to their ASCII equivalents
    function normalizeLigatures(text: string): string {
      return text
        .replace(/\ufb01/g, 'fi')
        .replace(/\ufb02/g, 'fl')
        .replace(/\ufb00/g, 'ff')
        .replace(/\ufb03/g, 'ffi')
        .replace(/\ufb04/g, 'ffl');
    }

    const applyHighlights = () => {
      if (pdfHighlights.length === 0) return;

      // Step 1: Clear previous highlights
      scrollEl.querySelectorAll('span[data-pdf-hl]').forEach(span => {
        (span as HTMLElement).style.backgroundColor = '';
        (span as HTMLElement).style.borderRadius = '';
        span.removeAttribute('data-pdf-hl');
        (span as HTMLElement).title = '';
      });

      // Step 2: Build global text and span index across ALL rendered pages
      const textLayers = scrollEl.querySelectorAll('.react-pdf__Page__textContent');
      if (textLayers.length === 0) return;

      // Build normalised text and a char→span mapping at build time.
      // Each char in normText maps to a span, so no reverse-mapping is needed.
      const charToSpan: HTMLSpanElement[] = [];
      let normText = '';

      textLayers.forEach(layer => {
        const spans = Array.from(layer.querySelectorAll('span')) as HTMLSpanElement[];
        for (const span of spans) {
          const raw = span.textContent || '';
          if (!raw) continue;
          const t = normalizeLigatures(raw).replace(/\s+/g, ' ');
          // Add space between spans if needed
          if (normText.length > 0 && !normText.endsWith(' ') && !t.startsWith(' ')) {
            normText += ' ';
            charToSpan.push(span); // space char belongs to this span
          }
          for (let ci = 0; ci < t.length; ci++) {
            charToSpan.push(span);
          }
          normText += t;
        }
      });

      if (normText.length === 0) return;

      const normTextLower = normText.toLowerCase();

      // Step 3: Match each highlight and colour the exact spans
      for (const hl of pdfHighlights) {
        const hlText = normalizeLigatures(hl.text).replace(/\s+/g, ' ').trim().toLowerCase();
        if (hlText.length < 5) continue;

        // Strategy 1: exact match on normalised text
        let matchIdx = normTextLower.indexOf(hlText);
        let matchLen = hlText.length;

        // Strategy 2: progressively shorter prefix (only colour what matched)
        if (matchIdx === -1 && hlText.length > 60) {
          for (const ratio of [0.8, 0.6]) {
            const pLen = Math.floor(hlText.length * ratio);
            const partial = hlText.slice(0, pLen);
            const idx = normTextLower.indexOf(partial);
            if (idx !== -1) {
              matchIdx = idx;
              matchLen = pLen;
              break;
            }
          }
        }

        if (matchIdx === -1) continue;

        // Colour the spans that own the matched characters
        const matchEnd = matchIdx + matchLen;
        const colored = new Set<HTMLSpanElement>();
        for (let ci = matchIdx; ci < matchEnd && ci < charToSpan.length; ci++) {
          const span = charToSpan[ci];
          if (!colored.has(span)) {
            colored.add(span);
            span.style.backgroundColor = (hl.color || '#a5b4fc') + '40';
            span.style.borderRadius = '2px';
            span.setAttribute('data-pdf-hl', hl.id);
            span.title = hl.memo || hl.category || '';
          }
        }
      }
    };

    // Initial application with retry for text layer rendering
    let attempts = 0;
    const tryApply = () => {
      const hasTextLayers = scrollEl.querySelector('.react-pdf__Page__textContent span');
      if (hasTextLayers) {
        applyHighlights();
      } else if (attempts < 10) {
        attempts++;
        setTimeout(tryApply, 500);
      }
    };
    const timer = setTimeout(tryApply, 300);

    // MutationObserver: debounced reapply when text layers change (zoom / scroll / virtualisation)
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;
    const observer = new MutationObserver(() => {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(applyHighlights, 200);
    });
    observer.observe(scrollEl, { childList: true, subtree: true });

    return () => {
      clearTimeout(timer);
      if (debounceTimer) clearTimeout(debounceTimer);
      observer.disconnect();
    };
  }, [pdfHighlights, visiblePages, documentKey, zoom, fitWidth]);

  // Mark math formula spans in the PDF text layer
  useEffect(() => {
    const scrollEl = docScrollRef.current;
    if (!scrollEl || !numPages) return;

    const mathPattern = /[∀∃∈∉∪∩⊆⊇⊂⊃≤≥≠≈∝∞∑∏∫√∂∇αβγδεζηθλμνξπρστφχψω]/;

    const markMathSpans = () => {
      const textLayers = scrollEl.querySelectorAll('.react-pdf__Page__textContent');
      textLayers.forEach(layer => {
        const spans = Array.from(layer.querySelectorAll('span')) as HTMLSpanElement[];
        for (const span of spans) {
          const text = span.textContent || '';
          // Only mark spans that contain math characters and have some length,
          // and skip spans already marked as highlights
          if (mathPattern.test(text) && text.length > 1 && !span.hasAttribute('data-pdf-hl')) {
            span.classList.add('pdf-math-formula');
            span.setAttribute('data-math-formula', 'true');
          }
        }
      });
    };

    const timer = setTimeout(markMathSpans, 800);
    const observer = new MutationObserver(markMathSpans);
    observer.observe(scrollEl, { childList: true, subtree: true });
    return () => { clearTimeout(timer); observer.disconnect(); };
  }, [numPages, documentKey, visiblePages, zoom, fitWidth]);

  // Click handler for PDF highlight spans and math formula spans → show popover
  useEffect(() => {
    const scrollEl = docScrollRef.current;
    if (!scrollEl) return;

    const handleClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      const hlId = target.getAttribute('data-pdf-hl');
      const isMath = target.getAttribute('data-math-formula') === 'true';

      // Highlight popover takes priority over math popover
      if (hlId) {
        setMathPopover(null);
        const hl = pdfHighlights.find(h => h.id === hlId);
        if (!hl) return;
        const rect = target.getBoundingClientRect();
        setHlPopover({
          hl,
          x: rect.left + rect.width / 2,
          y: rect.bottom + 8,
        });
        return;
      }

      // Math formula click (only when no highlight attribute)
      if (isMath) {
        setHlPopover(null);
        const rect = target.getBoundingClientRect();

        // Collect formula text from adjacent math-formula spans
        const formulaText = target.textContent || '';

        // Collect surrounding context (~200 chars) from sibling spans
        const parent = target.parentElement;
        let contextBefore = '';
        let contextAfter = '';
        if (parent) {
          const siblings = Array.from(parent.querySelectorAll('span')) as HTMLSpanElement[];
          const idx = siblings.indexOf(target);
          // Gather before
          for (let i = idx - 1; i >= 0 && contextBefore.length < 200; i--) {
            contextBefore = (siblings[i].textContent || '') + ' ' + contextBefore;
          }
          // Gather after
          for (let i = idx + 1; i < siblings.length && contextAfter.length < 200; i++) {
            contextAfter += ' ' + (siblings[i].textContent || '');
          }
        }
        const context = (contextBefore.trim() + ' ' + formulaText + ' ' + contextAfter.trim()).trim();
        const paperTitle = selectedPaper?.title || '';

        setMathPopover({
          x: rect.left + rect.width / 2,
          y: rect.bottom + 8,
          loading: true,
          formulaText,
        });

        explainMathFormula(formulaText, context, paperTitle)
          .then(explanation => {
            setMathPopover(prev => prev ? { ...prev, loading: false, explanation } : null);
          })
          .catch(err => {
            console.error('Math explain failed:', err);
            setMathPopover(prev => prev ? {
              ...prev,
              loading: false,
              explanation: {
                explanation: 'Failed to analyze formula. Please try again.',
                variables: [],
                formula_type: 'other',
              },
            } : null);
          });
        return;
      }

      // Click outside → close both popovers
      setHlPopover(null);
      setMathPopover(null);
    };

    scrollEl.addEventListener('click', handleClick);
    return () => scrollEl.removeEventListener('click', handleClick);
  }, [pdfHighlights, selectedPaper]);

  const handleDocumentLoadSuccess = useCallback((pdf: { numPages: number }) => {
    setNumPages(pdf.numPages);
    setPdfLoading(false);
    setPdfError(null);
    pdfDocRef.current = pdf;
  }, []);

  const handleDocumentLoadError = useCallback((err: Error) => {
    setPdfLoading(false);
    setPdfError(err.message || 'Failed to load PDF.');
  }, []);

  const scrollToPage = useCallback((page: number) => {
    const el = pageRefs.current.get(page);
    if (el) {
      isScrollingToPage.current = true;
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setCurrentPage(page);
      setPageInputValue(String(page));
      setTimeout(() => { isScrollingToPage.current = false; }, 600);
    }
  }, []);

  const goToPrevPage = useCallback(() => {
    const prev = Math.max(1, currentPage - 1);
    scrollToPage(prev);
  }, [currentPage, scrollToPage]);

  const goToNextPage = useCallback(() => {
    const next = Math.min(numPages ?? currentPage, currentPage + 1);
    scrollToPage(next);
  }, [currentPage, numPages, scrollToPage]);

  const handlePageInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setPageInputValue(e.target.value);
  }, []);

  const handlePageInputCommit = useCallback(() => {
    const parsed = parseInt(pageInputValue, 10);
    if (!isNaN(parsed) && numPages !== null) {
      const clamped = Math.min(numPages, Math.max(1, parsed));
      scrollToPage(clamped);
    } else {
      setPageInputValue(String(currentPage));
    }
  }, [pageInputValue, numPages, currentPage, scrollToPage]);

  const handlePageInputKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') handlePageInputCommit();
      if (e.key === 'Escape') setPageInputValue(String(currentPage));
    },
    [handlePageInputCommit, currentPage],
  );

  const handleZoomIn = useCallback(() => {
    setFitWidth(false);
    setZoom((z) => Math.min(ZOOM_MAX, parseFloat((z + ZOOM_STEP).toFixed(2))));
  }, []);

  const handleZoomOut = useCallback(() => {
    setFitWidth(false);
    setZoom((z) => Math.max(ZOOM_MIN, parseFloat((z - ZOOM_STEP).toFixed(2))));
  }, []);

  const handleFitWidth = useCallback(() => {
    setFitWidth((fw) => !fw);
  }, []);

  const effectiveWidth = fitWidth ? containerWidth : undefined;
  const effectiveScale = fitWidth ? undefined : zoom;

  // Ctrl+Scroll → PDF zoom (debounced via rAF to avoid per-event re-renders)
  useEffect(() => {
    const el = pdfAreaRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();

      // Accumulate delta into pending zoom
      const current = pendingZoomRef.current ?? zoom;
      const step = e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP;
      pendingZoomRef.current = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, parseFloat((current + step).toFixed(2))));

      // Batch into a single rAF
      if (zoomRafRef.current === null) {
        zoomRafRef.current = requestAnimationFrame(() => {
          zoomRafRef.current = null;
          if (pendingZoomRef.current !== null) {
            setFitWidth(false);
            setZoom(pendingZoomRef.current);
            pendingZoomRef.current = null;
          }
        });
      }
    };
    el.addEventListener('wheel', handler, { passive: false });
    return () => {
      el.removeEventListener('wheel', handler);
      if (zoomRafRef.current !== null) cancelAnimationFrame(zoomRafRef.current);
    };
  }, [zoom]);

  // ── Render ─────────────────────────────────────────────────────────

  const renderSemanticReaderFallback = () => {
    const externalUrl = selectedPaper ? paperExternalUrl(selectedPaper) : null;
    return (
      <div className="paper-viewer-no-pdf">
        <span className="paper-viewer-no-pdf-icon"><IconAlertCircle /></span>
        <div>
          <div className="paper-viewer-no-pdf-title">PDF not available</div>
          <div className="paper-viewer-no-pdf-desc">Open access PDF could not be found for this paper.</div>
        </div>
        {readerUrl && (
          <a
            className="paper-viewer-no-pdf-link paper-viewer-reader-link"
            href={readerUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            <IconBookOpen /> Open in Semantic Reader
          </a>
        )}
        {externalUrl && (
          <a
            className="paper-viewer-no-pdf-link"
            href={externalUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            <IconExternalLink /> View Paper
          </a>
        )}
      </div>
    );
  };

  const renderPdfArea = () => {
    if (!selectedPaper) {
      return (
        <div className="paper-viewer-placeholder">
          <span className="paper-viewer-placeholder-icon">
            <IconFileText />
          </span>
          <span>Select a paper to view</span>
        </div>
      );
    }

    if (!pdfSrc) {
      // Still resolving PDF — show waiting indicator
      if (resolving || pdfLoading) {
        return (
          <div className="paper-viewer-loading">
            <div className="paper-viewer-spinner" />
            <span>Searching for PDF...</span>
          </div>
        );
      }

      // PDF not found — show fallback with Semantic Reader link (if available)
      return renderSemanticReaderFallback();
    }

    return (
      <>
        <div
          className="paper-viewer-doc-scroll"
          ref={docScrollRef}
        >
          <Document
            key={documentKey}
            file={pdfSrc}
            onLoadSuccess={handleDocumentLoadSuccess}
            onLoadError={handleDocumentLoadError}
            loading={
              <div className="paper-viewer-loading">
                <div className="paper-viewer-spinner" />
                <span>Loading PDF...</span>
              </div>
            }
            error={
              <div className="paper-viewer-error">
                <span className="paper-viewer-error-icon">
                  <IconAlertCircle />
                </span>
                <span>{pdfError ?? 'Failed to load PDF.'}</span>
                <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
                  <button
                    className="paper-viewer-error-retry"
                    onClick={() => {
                      setPdfError(null);
                      setPdfLoading(true);
                      setDocumentKey(k => k + 1);
                    }}
                  >
                    Retry
                  </button>
                  {selectedPaper && paperExternalUrl(selectedPaper) && (
                    <a
                      className="paper-viewer-error-retry"
                      href={paperExternalUrl(selectedPaper)!}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ textDecoration: 'none' }}
                    >
                      View Paper
                    </a>
                  )}
                </div>
              </div>
            }
          >
            {numPages !== null && Array.from({ length: numPages }, (_, i) => {
              const pageNum = i + 1;
              const shouldRender = visiblePages.has(pageNum);
              const knownHeight = pageHeights.current.get(pageNum);
              return (
                <div
                  key={pageNum}
                  data-page={pageNum}
                  ref={(el) => {
                    if (el) {
                      pageRefs.current.set(pageNum, el);
                      // Cache rendered page height for placeholder sizing
                      if (el.offsetHeight > 50) {
                        pageHeights.current.set(pageNum, el.offsetHeight);
                      }
                    } else {
                      pageRefs.current.delete(pageNum);
                    }
                  }}
                  style={{ marginBottom: '8px' }}
                >
                  {shouldRender ? (
                    <MemoPage
                      pageNumber={pageNum}
                      scale={effectiveScale}
                      width={effectiveWidth}
                    />
                  ) : (
                    <div style={{ height: knownHeight || ESTIMATED_PAGE_HEIGHT, background: 'var(--bg-secondary, #f5f5f5)' }} />
                  )}
                </div>
              );
            })}
          </Document>

          {pdfLoading && numPages === null && (
            <div className="paper-viewer-loading">
              <div className="paper-viewer-spinner" />
              <span>Loading PDF...</span>
            </div>
          )}
        </div>

        <div className="paper-viewer-toolbar">
          {/* Navigation */}
          <div className="paper-viewer-toolbar-group">
            <button
              className="paper-viewer-icon-btn"
              title="Previous page"
              onClick={goToPrevPage}
              disabled={currentPage <= 1}
            >
              <IconChevronLeft />
            </button>
            <div className="paper-viewer-page-info">
              <input
                className="paper-viewer-page-input"
                type="text"
                inputMode="numeric"
                value={pageInputValue}
                onChange={handlePageInputChange}
                onBlur={handlePageInputCommit}
                onKeyDown={handlePageInputKeyDown}
                aria-label="Page number"
              />
              <span className="paper-viewer-page-total">
                / {numPages ?? '—'}
              </span>
            </div>
            <button
              className="paper-viewer-icon-btn"
              title="Next page"
              onClick={goToNextPage}
              disabled={numPages === null || currentPage >= numPages}
            >
              <IconChevronRight />
            </button>
          </div>

          <div className="paper-viewer-toolbar-sep" />

          {/* Zoom */}
          <div className="paper-viewer-toolbar-group">
            <button
              className="paper-viewer-icon-btn"
              title="Zoom out"
              onClick={handleZoomOut}
              disabled={fitWidth || zoom <= ZOOM_MIN}
            >
              <IconZoomOut />
            </button>
            <span className="paper-viewer-zoom-label">
              {fitWidth ? 'fit' : `${Math.round(zoom * 100)}%`}
            </span>
            <button
              className="paper-viewer-icon-btn"
              title="Zoom in"
              onClick={handleZoomIn}
              disabled={fitWidth || zoom >= ZOOM_MAX}
            >
              <IconZoomIn />
            </button>
          </div>

          <div className="paper-viewer-toolbar-sep" />

          {/* Fit width */}
          <button
            className={`paper-viewer-fit-btn${fitWidth ? ' active' : ''}`}
            title="Fit to width"
            onClick={handleFitWidth}
          >
            <IconFitWidth />
            Fit width
          </button>

          <div className="paper-viewer-toolbar-sep" />

          {/* PDF overlay highlight button — works without bookmark */}
          <button
            className={`paper-viewer-fit-btn paper-viewer-pdf-hl-btn${pdfHighlights.length > 0 ? ' active' : ''}`}
            title="Auto-highlight key findings on PDF"
            onClick={handleAutoHighlightPdf}
            disabled={highlightingPdf || !pdfDocRef.current}
          >
            {highlightingPdf ? (
              <><span className="paper-viewer-resolve-spinner" /> Highlighting...</>
            ) : (
              <>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2L15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2z"/></svg>
                {pdfHighlights.length > 0 ? `Highlights (${pdfHighlights.length})` : 'Auto Highlight'}
              </>
            )}
          </button>

          <div className="paper-viewer-toolbar-spacer" />
        </div>
      </>
    );
  };

  return (
    <div className="paper-viewer-panel">
      {/* ── Left: Paper list ── */}
      <div className="paper-viewer-list">
        <div className="paper-viewer-list-header">
          <span>Papers</span>
          {resolving && (
            <span className="paper-viewer-resolve-status">
              <span className="paper-viewer-resolve-spinner" />
              Searching PDFs...
            </span>
          )}
          {!resolving && resolveProgress && (
            <span className="paper-viewer-resolve-done">
              {resolveProgress.done}/{resolveProgress.total} found
            </span>
          )}
        </div>



        <div className="paper-viewer-list-scroll">
          {loadingDetail ? (
            <div className="paper-viewer-list-loading">Loading papers...</div>
          ) : !hasSelectedBookmark ? (
            <div className="paper-viewer-list-empty">No bookmark selected</div>
          ) : papers.length === 0 ? (
            <div className="paper-viewer-list-empty">No papers in this bookmark</div>
          ) : (
            papers.map((paper, index) => {
              const hasPdf = Boolean(getEffectivePdfUrl(paper));
              const isSelected = selectedIndex === index;
              return (
                <div
                  key={paper.doi || paper.title}
                  className={`paper-viewer-item${isSelected ? ' selected' : ''}`}
                  onClick={() => resolveAndSelect(index)}
                  title={paper.title}
                >
                  {hasPdf && (
                    <span className="paper-viewer-item-pdf-icon" title="PDF available">
                      <IconFilePdf />
                    </span>
                  )}
                  <div className="paper-viewer-item-content">
                    <div className="paper-viewer-item-title">{paper.title}</div>
                    <div className="paper-viewer-item-meta">
                      {formatAuthors(paper.authors)}
                      {paper.year ? ` · ${paper.year}` : ''}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* ── Center: PDF viewer ── */}
      <div className="paper-viewer-pdf-area" ref={pdfAreaRef}>{renderPdfArea()}</div>

      {/* ── Highlight popover (reuses bookmark popover CSS) ── */}
      {hlPopover && (
        <div className="mypage-hl-popover" style={{ left: hlPopover.x, top: hlPopover.y }}>
          <button className="mypage-hl-popover-close" onClick={() => setHlPopover(null)}>&times;</button>
          {(hlPopover.hl.category || hlPopover.hl.strength_or_weakness || hlPopover.hl.confidence_level) && (
            <div className="mypage-hl-popover-badges">
              {hlPopover.hl.category && (
                <span className="mypage-hl-badge mypage-hl-badge-strength">
                  {hlPopover.hl.category}
                </span>
              )}
              {hlPopover.hl.strength_or_weakness && (
                <span className={`mypage-hl-badge mypage-hl-badge-${hlPopover.hl.strength_or_weakness}`}>
                  {hlPopover.hl.strength_or_weakness === 'strength' ? 'Strength' : 'Weakness'}
                </span>
              )}
              {hlPopover.hl.confidence_level && (
                <span className="mypage-hl-badge mypage-hl-badge-confidence">
                  Confidence {hlPopover.hl.confidence_level}/5
                </span>
              )}
            </div>
          )}
          {hlPopover.hl.memo && <div className="mypage-hl-popover-memo">{hlPopover.hl.memo}</div>}
          {hlPopover.hl.question_for_authors && (
            <div className="mypage-hl-popover-question">
              <span className="mypage-hl-popover-question-label">Question for Authors</span>
              {hlPopover.hl.question_for_authors}
            </div>
          )}
          {hlPopover.hl.implication && (
            <div className="mypage-hl-popover-implication">
              <span className="mypage-hl-popover-implication-label">Implication</span>
              {hlPopover.hl.implication}
            </div>
          )}
        </div>
      )}

      {/* ── Math formula popover (reuses highlight popover CSS) ── */}
      {mathPopover && (
        <div className="mypage-hl-popover" style={{ left: mathPopover.x, top: mathPopover.y }}>
          <button className="mypage-hl-popover-close" onClick={() => setMathPopover(null)}>&times;</button>
          <div className="mypage-hl-popover-badges">
            <span className="mypage-hl-badge mypage-hl-badge-strength">
              {mathPopover.explanation?.formula_type || 'Formula'}
            </span>
          </div>
          {mathPopover.loading ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#9ca3af', fontSize: 12 }}>
              <span className="paper-viewer-resolve-spinner" />
              Analyzing formula...
            </div>
          ) : mathPopover.explanation ? (
            <>
              <div className="mypage-hl-popover-memo">{mathPopover.explanation.explanation}</div>
              {mathPopover.explanation.variables.length > 0 && (
                <div className="mypage-hl-popover-question">
                  <span className="mypage-hl-popover-question-label">Variables</span>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    {mathPopover.explanation.variables.map((v, i) => (
                      <span key={i} style={{ fontSize: 11 }}>
                        <strong style={{ color: '#a5b4fc' }}>{v.symbol}</strong>: {v.meaning}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
