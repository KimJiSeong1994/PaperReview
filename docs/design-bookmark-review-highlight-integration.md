# Bookmark Paper Review & Auto-Highlight Integration Design

## 1. Executive Summary

This document presents a comprehensive design for integrating **per-paper review** and **auto-highlight** capabilities into the bookmark paper viewer (PaperViewerPanel). Currently, reviews can only be triggered from search results, and auto-highlights only operate on bookmark-level `report_markdown`. This design extends both systems to work on individual papers within a bookmark, directly from the PaperViewerPanel.

---

## 2. Current System Analysis

### 2.1 Component Map

```
MyPage.tsx
  |-- BookmarkSidebar (left)
  |-- [bookmarks tab] ReportViewer (center)    <-- has auto-highlight, notes
  |-- [papers tab]    PaperViewerPanel (center) <-- PDF only, no review/highlights
  |-- ChatPanel (right)
```

### 2.2 Key Gaps

| Capability | Current State | Desired State |
|---|---|---|
| Per-paper review | Not available (only multi-paper deep-review from search) | Trigger review from PaperViewerPanel for any bookmarked paper |
| Auto-highlight on review | Only on bookmark's `report_markdown` | On per-paper review result AND on bookmark report |
| Highlight display in PaperViewerPanel | Not available | Review highlights panel alongside PDF |
| Review persistence | `review_sessions` in-memory only, report in workspace filesystem | Persisted to bookmark JSON alongside papers |
| Review from bookmark | Must go back to search, re-find papers | One-click review from paper list |

### 2.3 Data Flow Gaps

```
Current:
  Search -> select papers -> POST /api/deep-review -> poll status -> get report -> save as bookmark

Missing:
  Bookmark -> select paper -> POST /api/paper-review -> poll status -> save review to bookmark[paper_index]
```

---

## 3. Paper Review Expert: Review Pipeline Design

### 3.1 Per-Paper Review vs. Deep Review Comparison

| Dimension | Deep Review (existing) | Per-Paper Review (new) |
|---|---|---|
| Input | Multiple paper IDs | Single paper metadata + optional PDF text |
| Agent topology | N researchers + 1 advisor (multi-agent) | Single GPT-4.1 call (fast mode only) |
| Output | Full markdown report with cross-paper synthesis | Structured single-paper analysis |
| Duration | 30-120s | 10-30s |
| Storage | Workspace filesystem + review_sessions | Directly in bookmark JSON per paper |
| Trigger | Search results page | PaperViewerPanel paper list item |

### 3.2 Per-Paper Review Prompt Design

The per-paper review uses a specialized prompt distinct from the full deep-review. It produces a structured JSON response (not free-form markdown) to enable programmatic display and highlight extraction.

**System prompt:**
```
You are a senior reviewer at a top-tier venue (Nature/Science/ICML/NeurIPS).
Analyze the given paper and produce a structured review.
```

**Output schema:**
```json
{
  "summary": "2-3 sentence overview of the paper's contribution",
  "strengths": [
    {"point": "...", "evidence": "...", "significance": "high|medium|low"}
  ],
  "weaknesses": [
    {"point": "...", "evidence": "...", "severity": "major|minor"}
  ],
  "methodology_assessment": {
    "rigor": 1-5,
    "novelty": 1-5,
    "reproducibility": 1-5,
    "commentary": "..."
  },
  "key_contributions": ["..."],
  "questions_for_authors": ["..."],
  "overall_score": 1-10,
  "confidence": 1-5,
  "detailed_review_markdown": "Full markdown review text (~800+ chars)"
}
```

### 3.3 Input Sources (Priority Order)

1. **Full text from PDF**: If the PDF is loaded via react-pdf, the text layer is already rendered. We can extract text from pdfjs `getPage().getTextContent()` and send it to the backend.
2. **Abstract from paper metadata**: Available in `bookmarkDetail.papers[i].abstract` or fetchable from arXiv/S2.
3. **Metadata only**: Title + authors + year -- produces a limited review with lower confidence.

### 3.4 Review Pipeline Flow

```
User clicks "Review" on paper item in PaperViewerPanel
  |
  v
Frontend: POST /api/paper-review
  {
    bookmark_id: string,
    paper_index: number,
    paper: { title, authors, year, abstract?, full_text?, doi?, arxiv_id? }
  }
  |
  v
Backend:
  1. Enrich paper (fetch abstract from arXiv if missing)
  2. Call GPT-4.1 with per-paper review prompt
  3. Parse structured JSON response
  4. Run auto-highlight extraction on detailed_review_markdown
  5. Save review + highlights to bookmark.papers[paper_index].review
  6. Return review result
  |
  v
Frontend: Display review panel alongside PDF
```

---

## 4. Backend Architect: API & Data Model Design

### 4.1 New API Endpoints

#### `POST /api/bookmarks/{bookmark_id}/papers/{paper_index}/review`

Start a per-paper review for a specific paper within a bookmark.

**Request:**
```python
class PaperReviewRequest(BaseModel):
    full_text: Optional[str] = None      # Extracted from PDF if available
    abstract: Optional[str] = None       # Override abstract
    review_mode: str = "fast"            # "fast" only for now
```

**Response:**
```python
class PaperReviewResponse(BaseModel):
    success: bool
    session_id: str                      # For polling if async
    status: str                          # "completed" | "processing"
    review: Optional[PaperReview] = None # Immediate result if sync
```

**Implementation strategy:** Synchronous for fast mode (10-30s timeout acceptable with loading UI). If full_text is provided, runs deeper analysis. Falls back to abstract-only review.

#### `GET /api/bookmarks/{bookmark_id}/papers/{paper_index}/review`

Retrieve cached review for a paper.

**Response:** Returns stored `PaperReview` or 404.

#### `DELETE /api/bookmarks/{bookmark_id}/papers/{paper_index}/review`

Remove a per-paper review.

#### `POST /api/bookmarks/{bookmark_id}/papers/{paper_index}/auto-highlight`

Run auto-highlight on a per-paper review's `detailed_review_markdown`.

Uses the existing `generate_highlights()` from `highlight_service.py` but targets the paper-level review text instead of the bookmark-level report.

### 4.2 Data Model Extension

**Current bookmark structure (in bookmarks.json):**
```json
{
  "id": "bm_...",
  "papers": [
    { "title": "...", "authors": [...], "year": "...", "doi": "..." }
  ],
  "report_markdown": "...",
  "highlights": [...],
  "notes": "..."
}
```

**Extended structure:**
```json
{
  "id": "bm_...",
  "papers": [
    {
      "title": "...",
      "authors": [...],
      "year": "...",
      "doi": "...",
      "review": {
        "summary": "...",
        "strengths": [...],
        "weaknesses": [...],
        "methodology_assessment": {...},
        "key_contributions": [...],
        "questions_for_authors": [...],
        "overall_score": 7,
        "confidence": 4,
        "detailed_review_markdown": "...",
        "created_at": "2026-03-14T...",
        "model": "gpt-4.1",
        "input_type": "abstract|full_text|metadata"
      },
      "review_highlights": [
        {
          "id": "rhl_...",
          "text": "...",
          "color": "#a5b4fc",
          "memo": "...",
          "category": "finding",
          "significance": 4,
          "section": "...",
          "implication": "...",
          "strength_or_weakness": "strength",
          "question_for_authors": "...",
          "confidence_level": 4,
          "created_at": "..."
        }
      ]
    }
  ],
  "report_markdown": "...",
  "highlights": [...],
  "notes": "..."
}
```

**Key design decisions:**
- `review` lives inside each paper object, not at the bookmark level. This keeps per-paper and per-bookmark data cleanly separated.
- `review_highlights` is also per-paper, parallel to the bookmark-level `highlights` array. This avoids collision between bookmark-report highlights and paper-review highlights.
- The existing `highlights` array continues to work for bookmark-level report highlights.

### 4.3 New Router File: `routers/paper_reviews.py`

To avoid further bloating `bookmarks.py`, create a dedicated router:

```python
# routers/paper_reviews.py
router = APIRouter(prefix="/api", tags=["paper-reviews"])

# POST /api/bookmarks/{bookmark_id}/papers/{paper_index}/review
# GET  /api/bookmarks/{bookmark_id}/papers/{paper_index}/review
# DELETE /api/bookmarks/{bookmark_id}/papers/{paper_index}/review
# POST /api/bookmarks/{bookmark_id}/papers/{paper_index}/auto-highlight
```

This router imports `load_bookmarks`, `modify_bookmarks` from `routers.deps` and `generate_highlights` from `routers.highlight_service`.

### 4.4 Review Generation Service

Create `routers/paper_review_service.py` to encapsulate the LLM call:

```python
def generate_paper_review(
    paper: dict,
    client,
    model: str = "gpt-4.1",
) -> dict:
    """
    Generate a structured per-paper review using a single LLM call.

    Args:
        paper: Paper dict with title, authors, year, abstract, full_text (optional)
        client: OpenAI-compatible client
        model: LLM model name

    Returns:
        Structured review dict matching PaperReview schema
    """
```

This service is separate from the multi-paper `run_fast_review` in `reviews.py`. It uses `response_format={"type": "json_object"}` for reliable structured output.

### 4.5 Concurrency & Safety

- The review endpoint acquires `modify_bookmarks()` context manager only for the final write, not during the LLM call (same pattern as existing `auto_highlight_bookmark`).
- LLM cache (`routers/llm_cache.py`) is reused so identical papers produce cached results.
- Rate limiting: `@limiter.limit("10/minute")` on the review endpoint (per-paper reviews are cheaper than deep reviews).

---

## 5. Web Designer: UI/UX Design for PaperViewerPanel

### 5.1 Layout Evolution

**Current PaperViewerPanel layout:**
```
+-------------------+------------------------------------------+
| Paper List (280px)| PDF Viewer (flex)                        |
|                   |                                          |
| [Paper 1]         |  [PDF pages...]                          |
| [Paper 2] *       |                                          |
| [Paper 3]         |                                          |
|                   |  [Toolbar: page nav | zoom | fit]        |
+-------------------+------------------------------------------+
```

**Proposed layout with review panel:**
```
+-------------------+---------------------+--------------------+
| Paper List (260px)| PDF Viewer (flex)   | Review Panel       |
|                   |                     | (380px, collapsible)|
| [Paper 1]         | [PDF pages...]      | [Review Tab]       |
| [Paper 2] *       |                     | [Highlights Tab]   |
|   [Review] btn    |                     |                    |
| [Paper 3]         | [Toolbar]           | [Content...]       |
+-------------------+---------------------+--------------------+
```

The review panel slides in from the right when a paper has a review or when the user triggers a review. It is collapsible to preserve the full-width PDF reading experience.

### 5.2 Paper List Item Enhancement

Each paper item in the list gains contextual indicators:

```
+--------------------------------------------------+
| [PDF icon] Paper Title Line 1...                  |
|            Paper Title Line 2...                  |
|            Author et al. · 2024                   |
|  [Review badge 7/10] [Highlights badge 12]        |
|  [Review button]                                  |
+--------------------------------------------------+
```

- **Review badge**: Shows overall score if review exists (color-coded: green 7+, yellow 5-6, red <5)
- **Highlights badge**: Count of review_highlights
- **Review button**: "Review" if no review, "Re-review" if review exists

### 5.3 Review Panel Design

The review panel uses a tabbed layout:

**Tab 1: Review**
```
+--------------------------------------------+
| Review                          Highlights  |
+--------------------------------------------+
| Overall Score: 7/10  Confidence: 4/5       |
|                                            |
| [Summary]                                  |
| 2-3 sentence summary text...              |
|                                            |
| [Strengths] (3)                     [v]    |
|   + Strong theoretical foundation         |
|   + Comprehensive experimental...         |
|   + Novel architecture design...          |
|                                            |
| [Weaknesses] (2)                    [v]    |
|   - Limited dataset diversity...          |
|   - Missing ablation study...             |
|                                            |
| [Methodology] Rigor: 4 Novel: 5 Repro: 3  |
|   Commentary text...                       |
|                                            |
| [Questions for Authors]             [v]    |
|   1. How does the model scale...          |
|   2. What happens when...                 |
|                                            |
| [Detailed Review]                   [v]    |
|   Full markdown rendered here...          |
|   (with highlight overlay if highlights   |
|    are present)                            |
+--------------------------------------------+
```

**Tab 2: Highlights**
```
+--------------------------------------------+
| Review                          Highlights  |
+--------------------------------------------+
| [Auto Review] [Clear All]        12 total  |
|                                            |
| Filter: [All] [Finding] [Method] [Limit]  |
|                                            |
| [Highlight item 1]                        |
|   mark: "quoted text from review..."      |
|   [finding] [Strength] [C4]              |
|   Comment: reviewer analysis...           |
|                                            |
| [Highlight item 2]                        |
|   mark: "quoted text..."                  |
|   [limitation] [Weakness] [C3]           |
|   Comment: ...                            |
+--------------------------------------------+
```

### 5.4 Review Trigger UX Flow

1. User selects a paper in the list
2. PDF loads in the center panel
3. User clicks "Review" button (in paper list item or in an empty review panel)
4. Loading state: spinner with "Analyzing paper..." message
5. Progress indication: "Extracting text..." -> "Running review..." -> "Generating highlights..."
6. Review panel slides in with results
7. Review is auto-saved to bookmark

**For papers with existing reviews:**
- Review panel shows immediately when paper is selected
- "Re-review" option available (replaces existing review)

### 5.5 New Components

```
web-ui/src/components/mypage/
  PaperViewerPanel.tsx       -- extended with review panel integration
  PaperReviewPanel.tsx       -- NEW: review display + highlight tabs
  PaperReviewButton.tsx      -- NEW: review trigger button with states
```

### 5.6 New Hook

```
web-ui/src/hooks/usePaperReview.tsx  -- NEW
```

State and handlers:
```typescript
interface UsePaperReviewReturn {
  // State
  review: PaperReview | null;
  reviewLoading: boolean;
  reviewError: string | null;
  reviewHighlights: HighlightItem[];
  activeReviewTab: 'review' | 'highlights';
  reviewPanelOpen: boolean;
  highlightFilter: string | null;       // category filter

  // Handlers
  startReview: (paperIndex: number, fullText?: string) => Promise<void>;
  deleteReview: (paperIndex: number) => Promise<void>;
  runAutoHighlight: (paperIndex: number) => Promise<void>;
  clearHighlights: (paperIndex: number) => Promise<void>;
  removeHighlight: (paperIndex: number, highlightId: string) => Promise<void>;
  toggleReviewPanel: () => void;
  setActiveReviewTab: (tab: 'review' | 'highlights') => void;
  setHighlightFilter: (category: string | null) => void;
}
```

### 5.7 Props Flow Update

```
MyPage.tsx
  |-- PaperViewerPanel (extended props)
        |-- paperReview hook results passed down
        |-- onReviewPaper callback
        |-- PaperReviewPanel (new child component)
```

The `PaperViewerPanelProps` interface extends to:
```typescript
export interface PaperViewerPanelProps {
  bookmarkDetail: any;
  loadingDetail: boolean;
  hasSelectedBookmark: boolean;
  autoSelectFirst?: boolean;
  // NEW: bookmark context for review operations
  bookmarkId?: string;
  onBookmarkUpdate?: (updatedDetail: any) => void;
}
```

### 5.8 PDF Text Extraction for Review

When the user triggers a review, the frontend extracts text from the loaded PDF:

```typescript
async function extractPdfText(pdfDoc: PDFDocumentProxy): Promise<string> {
  const pages: string[] = [];
  for (let i = 1; i <= Math.min(pdfDoc.numPages, 30); i++) {
    const page = await pdfDoc.getPage(i);
    const content = await page.getTextContent();
    pages.push(content.items.map(item => item.str).join(' '));
  }
  return pages.join('\n\n');
}
```

This provides much richer input for the review than metadata alone. The extraction happens client-side (pdfjs is already loaded) and is sent in the review request body.

---

## 6. Search Engineer: Highlight Text Matching Design

### 6.1 Problem Statement

Per-paper review highlights are extracted from `detailed_review_markdown` (the LLM-generated review text), not from the PDF. The challenge is displaying these highlights correctly in the review panel's markdown rendering.

### 6.2 Highlight Matching Strategy

**Layer 1: Review text highlights (primary)**

These work identically to the existing bookmark report highlights:
- LLM extracts text snippets from `detailed_review_markdown`
- `_find_verbatim_or_fuzzy()` matches them back to the source text
- `applyUserHighlights()` wraps matched text in `<mark>` elements during ReactMarkdown rendering

This is the same proven pipeline already in `useHighlights.tsx` and `highlight_service.py`. It will be reused with minimal changes -- the highlight source is `paper.review.detailed_review_markdown` instead of `bookmark.report_markdown`.

**Layer 2: PDF text cross-referencing (future, stretch goal)**

A more ambitious feature would highlight matching text in the PDF itself:
- Extract text positions from `pdfjs.getPage().getTextContent()` (includes `transform` matrix with x,y,w,h)
- Match highlight texts against PDF text using fuzzy string matching
- Render overlay divs on top of the PDF text layer

This is architecturally complex (text positions vary by page layout, columns, headers) and is **deferred to a future phase**. The design accommodates it by storing `page_number` and `text_position` fields in the highlight schema for future use.

### 6.3 Highlight Category Filtering

The existing 9-category system (`CATEGORY_CONFIG` in `highlight_service.py`) is reused. The new PaperReviewPanel adds category filter chips:

```
[All] [Finding] [Evidence] [Contribution] [Methodology] [Insight] [Reproducibility] [Limitation] [Gap] [Assumption]
```

Filtering is client-side (simple array filter on `highlight.category`).

### 6.4 Highlight Navigation

When user clicks a highlight in the highlights list:
1. Scroll the review markdown to the corresponding `<mark>` element
2. Flash the highlight with a brief animation

This reuses the existing `data-hl-id` attribute and scroll-into-view pattern from `useHighlights.tsx`.

### 6.5 Auto-Highlight Endpoint Reuse

The new `POST /api/bookmarks/{bookmark_id}/papers/{paper_index}/auto-highlight` endpoint calls the same `generate_highlights()` function from `highlight_service.py`, but with:
- `report` = `paper.review.detailed_review_markdown`
- `query` = paper title
- `title` = paper title

The highlight results are stored in `paper.review_highlights` instead of `bookmark.highlights`.

---

## 7. Data Visualization: Review Score & Highlight Statistics

### 7.1 Per-Paper Score Display

In the paper list item, show a compact score indicator:

```
[7.0]  -- green circle with score
 |
 +-- tooltip: "Overall: 7/10 | Confidence: 4/5 | Methodology: 4/5"
```

Color scale:
- 8-10: `#4ade80` (green)
- 6-7: `#a5b4fc` (indigo/blue, default accent)
- 4-5: `#fbbf24` (amber)
- 1-3: `#f87171` (red)

### 7.2 Review Panel Score Visualization

Inside the review panel, a compact radar/spider chart (using existing Plotly.js dependency) showing:
- Rigor (methodology_assessment.rigor)
- Novelty (methodology_assessment.novelty)
- Reproducibility (methodology_assessment.reproducibility)
- Overall Score (overall_score / 2, scaled to 5)
- Confidence (confidence)

This is a small 180x180px Plotly scatterpolar chart with dark theme matching the app.

### 7.3 Highlight Category Distribution

A horizontal stacked bar showing highlight category distribution:

```
[####|###|##|####|#|##]
 find evid meth lim gap assm

12 highlights total | 5 strengths, 7 weaknesses
```

This is pure CSS (no chart library needed) -- each segment is a colored div with width proportional to count.

### 7.4 ConsensusMeter Reuse

The existing `ConsensusMeter.tsx` component (used in ReportViewer for bookmark-level highlights) is reused in the review panel for per-paper review highlights. It already computes strength/weakness distribution from highlights.

### 7.5 Cross-Paper Review Comparison (Multi-Paper View)

When viewing the paper list with multiple reviewed papers, a summary bar at the top shows:
```
Reviews: 4/8 papers | Avg Score: 7.2 | Range: 5-9
```

This gives a quick overview without needing to click into each paper.

---

## 8. Integration Design: Component Interaction Map

### 8.1 Full Data Flow

```
User clicks "Review" on Paper #2
  |
  v
usePaperReview.startReview(2, extractedPdfText)
  |
  v
POST /api/bookmarks/{bm_id}/papers/2/review
  { full_text: "...", review_mode: "fast" }
  |
  v
paper_review_service.generate_paper_review()
  |-- Enrich paper (arXiv abstract if needed)
  |-- Call GPT-4.1 with per-paper prompt
  |-- Parse structured JSON response
  |
  v
Auto-highlight pipeline (inline, not separate call)
  |-- generate_highlights(review.detailed_review_markdown, ...)
  |-- _find_verbatim_or_fuzzy() for each highlight
  |
  v
modify_bookmarks():
  bookmark.papers[2].review = review_result
  bookmark.papers[2].review_highlights = highlights
  |
  v
Return { success: true, review: {...}, highlights: [...] }
  |
  v
Frontend: usePaperReview updates state
  |-- PaperReviewPanel renders review content
  |-- Highlights applied to review markdown via applyUserHighlights()
  |-- Paper list item shows score badge
```

### 8.2 State Ownership

| State | Owner | Consumers |
|---|---|---|
| `bookmarkDetail` | `useBookmarks` | MyPage, PaperViewerPanel, ReportViewer |
| Per-paper review | `usePaperReview` (new) | PaperViewerPanel, PaperReviewPanel |
| Per-paper highlights | `usePaperReview` (new) | PaperReviewPanel |
| Bookmark-level highlights | `useHighlights` (existing) | ReportViewer |
| PDF document/pages | PaperViewerPanel (local) | MemoPage, PDF text extraction |

### 8.3 Bookmark Detail Refresh

After a review is saved, the frontend needs to update `bookmarkDetail` to reflect the new review data. Two strategies:

**Option A (chosen): Optimistic local update**
- After receiving the review response, merge `review` and `review_highlights` into the local `bookmarkDetail.papers[index]`
- No need to re-fetch the full bookmark detail
- `onBookmarkUpdate` callback notifies the parent (`MyPage.tsx`) to update its `bookmarkDetail` state

**Option B (deferred): Full re-fetch**
- After review completes, call `getBookmarkDetail(bookmarkId)` to refresh all data
- Simpler but adds latency and network overhead

---

## 9. Implementation Phases

### Phase 1: Core Per-Paper Review (MVP)
**Backend:**
- `routers/paper_reviews.py` -- new router with review CRUD endpoints
- `routers/paper_review_service.py` -- LLM call encapsulation
- Register router in `api_server.py`
- Data model: add `review` field to paper objects in bookmark JSON

**Frontend:**
- `usePaperReview.tsx` hook
- `PaperReviewPanel.tsx` component (review tab only)
- Extend `PaperViewerPanel.tsx` with review panel slot and review button
- API client functions: `startPaperReview`, `getPaperReview`, `deletePaperReview`

### Phase 2: Review Highlights
**Backend:**
- Add `review_highlights` field to paper objects
- `POST .../auto-highlight` endpoint reusing `generate_highlights()`
- Inline auto-highlight during review creation (optional auto-run)

**Frontend:**
- Highlights tab in PaperReviewPanel
- Category filter chips
- Highlight navigation (click-to-scroll in review markdown)
- Highlight CRUD (remove individual highlights)
- ConsensusMeter integration

### Phase 3: Enhanced Visualization
**Frontend:**
- Score badge on paper list items
- Methodology radar chart (Plotly)
- Highlight category distribution bar
- Cross-paper review summary bar
- Review panel collapse/expand animation

### Phase 4: PDF Text Integration (Stretch)
**Frontend:**
- PDF text extraction utility
- Send full_text with review request
- (Future) PDF overlay highlights using text positions

---

## 10. File Change Summary

### New Files
| File | Purpose |
|---|---|
| `routers/paper_reviews.py` | Per-paper review API endpoints |
| `routers/paper_review_service.py` | LLM-based review generation service |
| `web-ui/src/hooks/usePaperReview.tsx` | Review state management hook |
| `web-ui/src/components/mypage/PaperReviewPanel.tsx` | Review display component |
| `web-ui/src/components/mypage/PaperReviewPanel.css` | Review panel styles |

### Modified Files
| File | Changes |
|---|---|
| `api_server.py` | Register `paper_reviews` router |
| `routers/__init__.py` | Export new router |
| `web-ui/src/api/client.ts` | Add `startPaperReview`, `getPaperReview`, `deletePaperReview`, `autoHighlightPaperReview` API functions |
| `web-ui/src/components/mypage/PaperViewerPanel.tsx` | Add review panel slot, review button, bookmarkId prop |
| `web-ui/src/components/mypage/PaperViewerPanel.css` | Review panel layout styles |
| `web-ui/src/components/mypage/types.ts` | Add `PaperReview`, `PaperReviewHighlight` interfaces |
| `web-ui/src/components/MyPage.tsx` | Pass bookmarkId and update callback to PaperViewerPanel |

### Unchanged Files (Reused As-Is)
| File | Reused For |
|---|---|
| `routers/highlight_service.py` | `generate_highlights()`, `CATEGORY_CONFIG`, `_find_verbatim_or_fuzzy()` |
| `routers/deps/storage.py` | `load_bookmarks()`, `modify_bookmarks()` |
| `web-ui/src/components/mypage/ConsensusMeter.tsx` | Strength/weakness distribution display |

---

## 11. Risk Assessment & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| LLM returns invalid JSON for structured review | Review creation fails | Use `response_format={"type": "json_object"}`, add fallback parsing with `json.JSONDecoder().raw_decode()`, retry once |
| PDF text extraction produces garbled text | Review quality is poor | Fall back to abstract-only review, display "Limited review (metadata only)" badge |
| Bookmark JSON grows large with many reviews | Slow load/save | Reviews are text-only (no binary data), typical review is ~2-5KB. Even 100 papers with reviews would add ~500KB -- acceptable for JSON file storage |
| Concurrent review writes to same bookmark | Data race | `modify_bookmarks()` context manager already provides file-level locking. LLM call happens outside the lock (same pattern as `auto_highlight_bookmark`) |
| Review panel competes for horizontal space with PDF | Cramped UI on small screens | Review panel is collapsible. On screens < 1200px, it opens as a full overlay instead of a side panel |
| Users expect PDF-level highlights | Confusion about highlight scope | Clear labeling: "Review Highlights" vs "Report Highlights". Phase 4 addresses PDF overlay as stretch goal |

---

## 12. API Specification Detail

### `POST /api/bookmarks/{bookmark_id}/papers/{paper_index}/review`

**Request Body:**
```json
{
  "full_text": "optional extracted PDF text...",
  "abstract": "optional override abstract...",
  "review_mode": "fast"
}
```

**Success Response (200):**
```json
{
  "success": true,
  "review": {
    "summary": "...",
    "strengths": [...],
    "weaknesses": [...],
    "methodology_assessment": { "rigor": 4, "novelty": 5, "reproducibility": 3, "commentary": "..." },
    "key_contributions": ["..."],
    "questions_for_authors": ["..."],
    "overall_score": 7,
    "confidence": 4,
    "detailed_review_markdown": "...",
    "created_at": "2026-03-14T...",
    "model": "gpt-4.1",
    "input_type": "full_text"
  },
  "highlights": [...],
  "highlight_count": 14
}
```

**Error Responses:**
- 400: Paper index out of range, or no reviewable content
- 403: Access denied (wrong user)
- 404: Bookmark not found
- 429: Rate limited
- 502: LLM service error
- 504: LLM timeout

### `GET /api/bookmarks/{bookmark_id}/papers/{paper_index}/review`

**Success Response (200):**
```json
{
  "review": { ... },
  "highlights": [ ... ]
}
```

**Error:** 404 if no review exists.

### `DELETE /api/bookmarks/{bookmark_id}/papers/{paper_index}/review`

**Success Response (200):**
```json
{ "success": true }
```

Removes both `review` and `review_highlights` from the paper object.

### `POST /api/bookmarks/{bookmark_id}/papers/{paper_index}/auto-highlight`

Re-runs auto-highlight on existing review text. Follows same pattern as existing `/api/bookmarks/{bookmark_id}/auto-highlight`.

**Success Response (200):**
```json
{
  "success": true,
  "highlights": [...],
  "added_count": 12,
  "enriched_count": 3
}
```
