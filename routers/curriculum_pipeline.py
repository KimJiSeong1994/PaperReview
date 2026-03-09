"""
4-step Curriculum Generation Pipeline

Step 1: LLM generates curriculum structure (modules/topics + search keywords)
        referencing real university courses (MIT, Stanford, Oxford, CMU, etc.)
Step 2: OpenAlex API searches and verifies real papers per topic
Step 3: LLM assembles final curriculum with verified papers + Korean context
Step 4: LLM auto-reviews for quality issues → searches replacements → refines
"""

import json
import logging
import asyncio
import datetime
import os
import time
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)


def _compute_paper_score(paper: dict, paper_preference: str | None = None) -> float:
    """Composite score: citations/year + recency bonus + preference weighting."""
    citations = paper.get("citations", 0)
    try:
        year = int(paper.get("year", 0))
    except (ValueError, TypeError):
        year = 0
    current_year = datetime.datetime.now().year

    if year > 0:
        age = max(current_year - year, 1)
        citations_per_year = citations / age
    else:
        citations_per_year = citations

    # Recency bonus: recent papers (≤3 years) get extra score
    recency_bonus = 0
    if year >= current_year - 1:
        recency_bonus = 50
    elif year >= current_year - 3:
        recency_bonus = 20

    score = citations_per_year + recency_bonus

    # paper_preference weighting
    if paper_preference == "cutting_edge" and year >= current_year - 3:
        score *= 2.0
    elif paper_preference == "survey_heavy" and citations > 500:
        score *= 1.5

    return score


class CurriculumPipeline:
    """Multi-step curriculum generation with SSE progress reporting."""

    def __init__(self, openai_client):
        self.client = openai_client

    @staticmethod
    def _extract_json_from_text(text: str) -> str:
        """Extract JSON object from text that may contain markdown fences or prose."""
        import re
        # Try ```json ... ``` fence first
        m = re.search(r"```(?:json)?\s*(\{.*)", text, re.DOTALL)
        if m:
            block = m.group(1)
            # Try to find closing fence
            end = block.find("```")
            if end > 0:
                return block[:end].strip()
            return block.strip()
        # Try to find first { ... last }
        start = text.find("{")
        if start >= 0:
            return text[start:].strip()
        return text.strip()

    @staticmethod
    def _parse_llm_json(response, step_label: str) -> dict:
        """Safely parse JSON from LLM response with detailed error logging."""
        choice = response.choices[0] if response.choices else None
        if not choice:
            raise ValueError(f"[{step_label}] API returned no choices")

        content = choice.message.content
        finish_reason = choice.finish_reason
        usage = response.usage

        logger.info(
            "[%s] LLM response — finish_reason=%s, prompt_tokens=%s, "
            "completion_tokens=%s, content_len=%s",
            step_label, finish_reason,
            usage.prompt_tokens if usage else "?",
            usage.completion_tokens if usage else "?",
            len(content) if content else 0,
        )

        if finish_reason == "content_filter":
            raise ValueError(f"[{step_label}] Response blocked by content filter")

        if not content or not content.strip():
            raise ValueError(
                f"[{step_label}] LLM returned empty response "
                f"(finish_reason={finish_reason}). "
                "The prompt may be too large or the model unavailable."
            )

        # Extract JSON from possible markdown/prose wrapper
        json_text = CurriculumPipeline._extract_json_from_text(content)

        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            pass

        # If truncated, try to repair
        if finish_reason == "length":
            logger.warning(
                "[%s] Truncated output (%d chars), attempting JSON repair...",
                step_label, len(json_text),
            )
            repaired = CurriculumPipeline._repair_truncated_json(json_text)
            if repaired is not None:
                logger.info("[%s] JSON repair succeeded", step_label)
                return repaired

        logger.error(
            "[%s] JSON parse failed — content[:500]=%s",
            step_label, content[:500],
        )
        raise ValueError(
            f"[{step_label}] Invalid JSON from LLM (finish_reason={finish_reason})."
        )

    @staticmethod
    def _repair_truncated_json(content: str) -> dict | None:
        """Attempt to repair truncated JSON by closing open brackets/braces."""
        # Strategy: progressively strip trailing chars and close brackets
        s = content.rstrip()
        # Try to find a valid JSON by closing open structures
        for _ in range(200):
            # Count open/close brackets
            open_braces = s.count("{") - s.count("}")
            open_brackets = s.count("[") - s.count("]")

            if open_braces == 0 and open_brackets == 0:
                try:
                    return json.loads(s)
                except json.JSONDecodeError:
                    pass

            # Strip trailing comma or incomplete key/value
            s = s.rstrip(", \t\n\r")
            # Strip incomplete string (ends with unclosed quote)
            if s and s[-1] == '"':
                # Check if this quote is an unclosed string
                s = s[:-1]
                # Find matching opening quote
                last_quote = s.rfind('"')
                if last_quote > 0:
                    # Remove the entire key-value pair back to last comma or brace
                    s = s[:last_quote].rstrip(", \t\n\r:")
                continue
            # Strip trailing colon (incomplete key-value)
            if s and s[-1] == ':':
                s = s[:-1].rstrip(", \t\n\r")
                # Remove the key too
                if s and s[-1] == '"':
                    last_quote = s[:-1].rfind('"')
                    if last_quote >= 0:
                        s = s[:last_quote].rstrip(", \t\n\r")
                continue

            # Close innermost open structure
            if open_brackets > 0:
                s += "]"
            elif open_braces > 0:
                s += "}"
            else:
                break

        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None

    async def generate(
        self,
        topic: str,
        difficulty: str,
        num_modules: int,
        learning_goals: Optional[str] = None,
        paper_preference: Optional[str] = None,
    ) -> AsyncGenerator[dict, None]:
        """Yields SSE event dicts through the 3-step pipeline."""

        # ── Step 1: Structure Generation ──
        yield {"step": 1, "step_name": "structure", "progress": 0,
               "message": "Designing curriculum based on top university courses..."}

        try:
            structure = await self._step1_structure(
                topic, difficulty, num_modules, learning_goals, paper_preference
            )
        except Exception as e:
            logger.error("Step 1 failed: %s", e)
            yield {"error": f"Structure generation failed: {e}", "step": 1}
            return

        module_names = [m["title"] for m in structure.get("modules", [])]
        total_topics = sum(len(m.get("topics", [])) for m in structure.get("modules", []))
        ref_courses = structure.get("reference_courses", [])

        yield {"step": 1, "step_name": "structure", "progress": 100,
               "message": f"Structure ready: {len(module_names)} modules, {total_topics} topics",
               "detail": {"modules": module_names, "reference_courses": ref_courses}}

        # ── Step 2: Paper Search & Verification ──
        yield {"step": 2, "step_name": "search", "progress": 0,
               "message": f"Searching verified papers for {total_topics} topics..."}

        try:
            async for event in self._step2_search_papers(structure, total_topics, paper_preference):
                if "step" in event:
                    yield event  # progress update
                else:
                    structure = event  # final result (the updated structure)
        except Exception as e:
            logger.error("Step 2 failed: %s", e)
            yield {"error": f"Paper search failed: {e}", "step": 2}
            return

        total_papers = sum(
            len(t.get("verified_papers", []))
            for m in structure.get("modules", [])
            for t in m.get("topics", [])
        )

        yield {"step": 2, "step_name": "search", "progress": 100,
               "message": f"Found {total_papers} verified papers across {total_topics} topics"}

        # ── Step 3: Final Assembly ──
        yield {"step": 3, "step_name": "assembly", "progress": 0,
               "message": "Selecting papers and writing annotations..."}

        try:
            curriculum = await self._step3_assemble(structure, topic, difficulty)
        except Exception as e:
            logger.error("Step 3 failed: %s", e)
            yield {"error": f"Assembly failed: {e}", "step": 3}
            return

        yield {"step": 3, "step_name": "assembly", "progress": 100,
               "message": "Assembly complete, starting quality review..."}

        # ── Step 4: Auto-Review & Refine ──
        yield {"step": 4, "step_name": "review", "progress": 0,
               "message": "Reviewing curriculum quality..."}

        try:
            async for event in self._step4_review_and_refine(
                curriculum, structure, topic, difficulty, paper_preference,
            ):
                if event.get("done"):
                    curriculum = event["curriculum"]
                elif "step" in event:
                    yield event
        except Exception as e:
            logger.warning("Step 4 (review) failed, using unrefined curriculum: %s", e)

        yield {"step": 4, "step_name": "review", "progress": 100,
               "message": "Quality review complete!"}

        yield {"done": True, "curriculum": curriculum}

    # ── Step 1: Structure Generation ──────────────────────────────────

    async def _step1_structure(
        self, topic: str, difficulty: str, num_modules: int,
        learning_goals: Optional[str], paper_preference: Optional[str],
    ) -> dict:
        optional_parts = []
        if learning_goals:
            optional_parts.append(f"- Learning goals: {learning_goals}")
        if paper_preference:
            pref_map = {
                "survey_heavy": "Prioritize survey papers, tutorials, and foundational works",
                "cutting_edge": "Prioritize recent cutting-edge research (2022+)",
                "balanced": "Balance classic foundational papers with recent advances",
            }
            optional_parts.append(f"- Paper preference: {pref_map.get(paper_preference, paper_preference)}")
        optional_text = "\n".join(optional_parts) if optional_parts else ""

        prompt = f"""You are an expert academic curriculum designer who has studied syllabi from
the world's top universities: MIT, Stanford, CMU, Oxford, NYU, Berkeley,
ETH Zurich, University of Toronto, Tsinghua University, KAIST, and others.

Design a structured learning curriculum OUTLINE for: "{topic}"

Requirements:
- Difficulty level: {difficulty}
- Number of modules: {num_modules}
- Reference ONLY real, currently-offered or well-documented university courses.
  Provide the official course URL if available. If you are not confident a course exists,
  do NOT fabricate it — instead use "General {topic} Curriculum" as inspired_by.
  For each module, note which real course inspired it.
- Each module should have 1-3 focused topics
- Do NOT include specific paper references yet
- For each topic, provide 2-3 search keywords that would find the most
  important/foundational papers on OpenAlex/Google Scholar
{optional_text}

Return ONLY valid JSON matching this schema:
{{
  "name": "Descriptive curriculum name",
  "description": "2-3 sentence course description",
  "prerequisites": ["prerequisite1", "prerequisite2"],
  "reference_courses": [
    {{
      "university": "MIT",
      "course_code": "6.S898",
      "course_name": "Deep Learning",
      "url": "https://... (official course URL, empty string if unknown)"
    }}
  ],
  "modules": [
    {{
      "id": "mod-01",
      "week": 1,
      "title": "Module Title",
      "description": "What this module covers and why",
      "inspired_by": "MIT 6.S898 Week 1-2",
      "topics": [
        {{
          "id": "topic-01-01",
          "title": "Topic Title",
          "search_keywords": ["keyword1", "keyword2", "keyword3"]
        }}
      ]
    }}
  ]
}}"""

        # Scale max_completion_tokens based on number of modules
        # ~300 tokens per module (id, title, description, inspired_by, 2-3 topics with keywords)
        structure_tokens = max(4000, num_modules * 500 + 1500)

        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model="gpt-5.4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_completion_tokens=structure_tokens,

        )

        result = self._parse_llm_json(response, "Step1-Structure")

        # Verify module count — warn if truncated
        actual_modules = len(result.get("modules", []))
        if actual_modules < num_modules:
            logger.warning(
                "Step 1: Requested %d modules but LLM returned %d (finish_reason=%s, tokens=%d/%d)",
                num_modules, actual_modules,
                response.choices[0].finish_reason,
                response.usage.completion_tokens if response.usage else 0,
                structure_tokens,
            )

        return result

    # ── Step 2: Paper Search & Verification ──────────────────────────

    async def _step2_search_papers(
        self, structure: dict, total_topics: int,
        paper_preference: Optional[str] = None,
    ):
        """Async generator: yields progress dicts, then yields the final structure."""
        from src.collector.paper.openalex_searcher import OpenAlexSearcher
        searcher = OpenAlexSearcher()

        topic_idx = 0
        try:
            for module in structure.get("modules", []):
                for topic_item in module.get("topics", []):
                    topic_idx += 1
                    pct = int((topic_idx / max(total_topics, 1)) * 100)
                    topic_title = topic_item.get("title", "")
                    logger.info("Step 2: Searching topic %d/%d: %s", topic_idx, total_topics, topic_title)

                    yield {"step": 2, "step_name": "search", "progress": pct,
                           "message": f"Searching: {topic_title} ({topic_idx}/{total_topics})"}

                    keywords = topic_item.get("search_keywords", [])
                    candidates = []
                    seen_titles = set()

                    for kw in keywords:
                        try:
                            results = await asyncio.to_thread(searcher.search, kw, 8)
                            for paper in results:
                                title_lower = (paper.get("title") or "").strip().lower()
                                if title_lower and title_lower not in seen_titles:
                                    seen_titles.add(title_lower)
                                    candidates.append(paper)
                        except Exception as e:
                            logger.warning("OpenAlex search failed for '%s': %s", kw, e)

                    # Semantic Scholar fallback when OpenAlex results are insufficient
                    if len(candidates) < 3:
                        s2_results = await asyncio.to_thread(
                            self._search_semantic_scholar, keywords, seen_titles,
                        )
                        candidates.extend(s2_results)

                    # Composite scoring: citations/year + recency bonus + preference
                    candidates.sort(
                        key=lambda p: _compute_paper_score(p, paper_preference),
                        reverse=True,
                    )
                    topic_item["verified_papers"] = candidates[:6]
        finally:
            searcher.close()

        # Final yield: the updated structure (not a dict with 'step')
        yield structure

    def _search_semantic_scholar(self, keywords: list, seen_titles: set, max_per_keyword: int = 5) -> list:
        """Semantic Scholar API로 보충 검색."""
        import requests as _requests

        results = []
        s2_api = "https://api.semanticscholar.org/graph/v1/paper/search"
        headers = {}
        s2_key = os.environ.get("S2_API_KEY")
        if s2_key:
            headers["x-api-key"] = s2_key

        for kw in keywords:
            try:
                resp = _requests.get(s2_api, params={
                    "query": kw,
                    "limit": max_per_keyword,
                    "fields": "title,authors,year,citationCount,venue,externalIds",
                }, headers=headers, timeout=10)
                if resp.status_code != 200:
                    continue
                for paper in resp.json().get("data", []):
                    title = paper.get("title", "")
                    title_lower = title.strip().lower()
                    if title_lower and title_lower not in seen_titles:
                        seen_titles.add(title_lower)
                        ext_ids = paper.get("externalIds") or {}
                        results.append({
                            "title": title,
                            "authors": [a.get("name", "") for a in paper.get("authors", [])][:10],
                            "year": str(paper.get("year", "")),
                            "citations": paper.get("citationCount", 0),
                            "doi": ext_ids.get("DOI", ""),
                            "arxiv_id": ext_ids.get("ArXiv", ""),
                            "venue": paper.get("venue", ""),
                            "url": f"https://api.semanticscholar.org/CorpusID:{paper.get('corpusId', '')}",
                            "source": "SemanticScholar",
                        })
            except Exception as e:
                logger.warning("S2 search failed for '%s': %s", kw, e)
            time.sleep(0.5)  # Rate limit
        return results

    # ── Step 3: Final Assembly ────────────────────────────────────────

    async def _step3_assemble(self, structure: dict, topic: str, difficulty: str) -> dict:
        """Assemble final curriculum. For large curricula (>5 modules), process in batches."""
        modules = structure.get("modules", [])
        ref_courses = structure.get("reference_courses", [])

        # Process in batches of 3 to keep prompt small and leave room for output
        batch_size = 3
        if len(modules) <= batch_size:
            assembled_modules = await self._assemble_batch(
                modules, topic, difficulty, ref_courses, structure,
            )
        else:
            assembled_modules = []
            for i in range(0, len(modules), batch_size):
                batch = modules[i:i + batch_size]
                batch_result = await self._assemble_batch(
                    batch, topic, difficulty, ref_courses, structure,
                    module_offset=i,
                )
                assembled_modules.extend(batch_result)

        curriculum = {
            "name": structure.get("name", topic),
            "university": "Multi-University Reference",
            "instructor": "AI Curated",
            "difficulty": difficulty,
            "description": structure.get("description", ""),
            "prerequisites": structure.get("prerequisites", []),
            "reference_courses": ref_courses,
            "url": "",
            "modules": assembled_modules,
        }
        return curriculum

    async def _assemble_batch(
        self, modules: list, topic: str, difficulty: str,
        ref_courses: list, structure: dict, module_offset: int = 0,
    ) -> list:
        """Assemble a batch of modules into final format."""
        difficulty_guide = {
            "beginner": "Prioritize survey papers, tutorials, and foundational works. Context should explain concepts clearly for newcomers.",
            "intermediate": "Mix foundational papers with key methodological advances. Context should assume basic understanding.",
            "advanced": "Focus on cutting-edge research and theoretical depth. Context should analyze contributions and limitations from a researcher's perspective.",
        }

        structure_for_prompt = []
        for module in modules:
            mod_info = {
                "module_title": module["title"],
                "topics": [],
            }
            for t in module.get("topics", []):
                # Limit to top 4 papers, 3 authors each to reduce prompt tokens
                topic_info = {
                    "topic_title": t["title"],
                    "verified_papers": [
                        {
                            "title": p["title"],
                            "authors": p.get("authors", [])[:3],
                            "year": p.get("year", ""),
                            "doi": p.get("doi", ""),
                            "citations": p.get("citations", 0),
                        }
                        for p in t.get("verified_papers", [])[:4]
                    ],
                }
                mod_info["topics"].append(topic_info)
            structure_for_prompt.append(mod_info)

        ref_text = ""
        if ref_courses:
            ref_text = "Referenced university courses:\n" + "\n".join(
                f"- {c.get('university', '')} {c.get('course_code', '')}: {c.get('course_name', '')}"
                for c in ref_courses
            )

        batch_note = ""
        if module_offset > 0:
            batch_note = f"\nNote: These are modules {module_offset + 1}-{module_offset + len(modules)} of a larger curriculum. Continue numbering from mod-{module_offset + 1:02d} and week {module_offset + 1}.\n"

        prompt = f"""You are assembling a university-level curriculum on "{topic}".
Below is the curriculum structure with VERIFIED real papers (confirmed from OpenAlex).

{ref_text}

Difficulty: {difficulty}
{difficulty_guide.get(difficulty, '')}
{batch_note}
For each topic, select 2-4 of the BEST papers from the verified list and:
1. Use EXACT titles and metadata from the verified papers (do not modify them)
2. Assign category: "required" (essential), "optional" (deeper understanding), or "supplementary" (reference)
3. Write a Korean context sentence explaining why this paper matters for the topic

IMPORTANT: You MUST output ALL {len(modules)} modules listed below. Do not skip or truncate any module.

Structure with verified papers:
{json.dumps(structure_for_prompt, ensure_ascii=False, indent=2)}

Return ONLY valid JSON with this schema:
{{
  "modules": [
    {{
      "id": "mod-{module_offset + 1:02d}",
      "week": {module_offset + 1},
      "title": "Module Title",
      "description": "Module description",
      "topics": [
        {{
          "id": "topic-{module_offset + 1:02d}-01",
          "title": "Topic Title",
          "papers": [
            {{
              "id": "paper-001",
              "title": "EXACT title from verified list",
              "authors": ["Author1", "Author2"],
              "year": 2020,
              "venue": "Conference/Journal",
              "arxiv_id": null,
              "doi": "10.xxxx/yyyy",
              "category": "required",
              "context": "이 논문이 중요한 이유를 한국어로 설명"
            }}
          ]
        }}
      ]
    }}
  ]
}}"""

        # ~3000 tokens per module (title, description, 2-3 topics × 2-3 papers with Korean context)
        assembly_tokens = max(8000, len(modules) * 3000)

        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model="gpt-5.4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_completion_tokens=assembly_tokens,

        )

        result = self._parse_llm_json(response, f"Step3-Assembly(offset={module_offset})")
        assembled = result.get("modules", [])

        if len(assembled) < len(modules):
            logger.warning(
                "Step 3: Batch expected %d modules but got %d (finish_reason=%s, tokens=%d/%d)",
                len(modules), len(assembled),
                response.choices[0].finish_reason,
                response.usage.completion_tokens if response.usage else 0,
                assembly_tokens,
            )

        return assembled

    # ── Step 4: Auto-Review & Refine ──────────────────────────────────

    async def _step4_review_and_refine(
        self,
        curriculum: dict,
        structure: dict,
        topic: str,
        difficulty: str,
        paper_preference: Optional[str] = None,
    ):
        """Auto-review assembled curriculum, search replacements, and refine.

        Yields progress events, then yields {"done": True, "curriculum": refined}.
        """
        # 4a: LLM reviews the curriculum
        review = await self._review_curriculum(curriculum, topic, difficulty)

        issues = review.get("issues", [])
        if not issues:
            logger.info("Step 4: No quality issues found, skipping refine")
            yield {"step": 4, "step_name": "review", "progress": 50,
                   "message": "Quality check passed — no issues found"}
            yield {"done": True, "curriculum": curriculum}
            return

        logger.info("Step 4: Found %d issues, refining...", len(issues))
        yield {"step": 4, "step_name": "review", "progress": 30,
               "message": f"Found {len(issues)} issues, searching better papers..."}

        # 4b: Search replacement papers for flagged entries
        papers_to_replace = [
            i for i in issues if i.get("action") == "replace"
        ]
        replacement_candidates = {}
        if papers_to_replace:
            replacement_candidates = await self._search_replacement_papers(
                papers_to_replace, structure, paper_preference,
            )

        yield {"step": 4, "step_name": "review", "progress": 60,
               "message": "Applying improvements..."}

        # 4c: LLM refines with review feedback + replacement candidates
        refined = await self._apply_refinements(
            curriculum, review, replacement_candidates, topic, difficulty,
        )

        yield {"step": 4, "step_name": "review", "progress": 90,
               "message": f"Refined: {len(papers_to_replace)} papers replaced, "
                         f"{len(issues) - len(papers_to_replace)} issues fixed"}
        yield {"done": True, "curriculum": refined}

    async def _review_curriculum(self, curriculum: dict, topic: str, difficulty: str) -> dict:
        """LLM reviews the assembled curriculum for quality issues."""
        # Build compact representation for review
        compact_modules = []
        for module in curriculum.get("modules", []):
            compact_topics = []
            for t in module.get("topics", []):
                compact_papers = [
                    {
                        "id": p.get("id", ""),
                        "title": p.get("title", ""),
                        "year": p.get("year"),
                        "category": p.get("category", ""),
                        "venue": p.get("venue", ""),
                    }
                    for p in t.get("papers", [])
                ]
                compact_topics.append({
                    "title": t.get("title", ""),
                    "papers": compact_papers,
                })
            compact_modules.append({
                "title": module.get("title", ""),
                "topics": compact_topics,
            })

        prompt = f"""You are a senior academic reviewer evaluating a generated curriculum on "{topic}" (difficulty: {difficulty}).

Review the curriculum below and identify quality issues. Check for:
1. **Relevance**: Papers not directly relevant to their assigned topic
2. **Coverage gaps**: Important sub-areas of a topic that have no papers
3. **Difficulty mismatch**: Papers too advanced for beginners, or too basic for advanced
4. **Duplication**: Same paper or near-duplicate across different topics
5. **Category errors**: Papers miscategorized (e.g., a niche paper marked "required")
6. **Outdated selections**: Key topics relying only on very old papers (pre-2015) when newer, better alternatives exist

Curriculum:
{json.dumps(compact_modules, ensure_ascii=False, indent=2)}

Return ONLY valid JSON:
{{
  "overall_quality": "good" | "needs_improvement" | "poor",
  "issues": [
    {{
      "paper_id": "paper-001 (or empty if structural issue)",
      "module_title": "affected module",
      "topic_title": "affected topic",
      "issue_type": "relevance|coverage_gap|difficulty|duplication|category|outdated",
      "description": "brief explanation of the issue",
      "action": "replace|recategorize|note",
      "search_keywords": ["keyword1", "keyword2"] // only if action=replace
    }}
  ]
}}

If the curriculum is good and has no significant issues, return {{"overall_quality": "good", "issues": []}}.
Be selective — only flag genuine issues, not minor nitpicks."""

        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model="gpt-5.4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_completion_tokens=3000,

        )
        return self._parse_llm_json(response, "Step4-Review")

    async def _search_replacement_papers(
        self,
        papers_to_replace: list[dict],
        structure: dict,
        paper_preference: Optional[str],
    ) -> dict:
        """Search replacement candidates for flagged papers via OpenAlex + S2."""
        from src.collector.paper.openalex_searcher import OpenAlexSearcher

        # Collect existing paper titles from the structure to avoid duplicates
        existing_titles = set()
        for m in structure.get("modules", []):
            for t in m.get("topics", []):
                for p in t.get("verified_papers", []):
                    title_lower = (p.get("title") or "").strip().lower()
                    if title_lower:
                        existing_titles.add(title_lower)

        replacement_candidates = {}  # paper_id -> [candidate papers]
        searcher = OpenAlexSearcher()
        try:
            for issue in papers_to_replace:
                paper_id = issue.get("paper_id", "")
                keywords = issue.get("search_keywords", [])
                if not keywords:
                    continue

                candidates = []
                seen = set(existing_titles)

                for kw in keywords:
                    try:
                        results = await asyncio.to_thread(searcher.search, kw, 5)
                        for paper in results:
                            title_lower = (paper.get("title") or "").strip().lower()
                            if title_lower and title_lower not in seen:
                                seen.add(title_lower)
                                candidates.append(paper)
                    except Exception as e:
                        logger.warning("Replacement search failed for '%s': %s", kw, e)

                # S2 fallback if needed
                if len(candidates) < 2:
                    s2_results = await asyncio.to_thread(
                        self._search_semantic_scholar, keywords, seen, 3,
                    )
                    candidates.extend(s2_results)

                candidates.sort(
                    key=lambda p: _compute_paper_score(p, paper_preference),
                    reverse=True,
                )
                replacement_candidates[paper_id] = [
                    {
                        "title": c["title"],
                        "authors": c.get("authors", [])[:5],
                        "year": c.get("year", ""),
                        "doi": c.get("doi", ""),
                        "venue": c.get("venue", ""),
                        "citations": c.get("citations", 0),
                    }
                    for c in candidates[:4]
                ]
        finally:
            searcher.close()

        return replacement_candidates

    async def _apply_refinements(
        self,
        curriculum: dict,
        review: dict,
        replacement_candidates: dict,
        topic: str,
        difficulty: str,
    ) -> dict:
        """LLM applies review feedback to produce a refined curriculum."""
        issues = review.get("issues", [])

        # Build issue summary for the prompt
        issues_text = json.dumps(issues, ensure_ascii=False, indent=2)
        replacements_text = json.dumps(replacement_candidates, ensure_ascii=False, indent=2)

        # Current curriculum (compact: only modules for token efficiency)
        current_modules = json.dumps(curriculum.get("modules", []), ensure_ascii=False, indent=2)

        num_modules = len(curriculum.get("modules", []))
        prompt = f"""You are refining a curriculum on "{topic}" (difficulty: {difficulty}) based on an expert review.

CURRENT CURRICULUM MODULES:
{current_modules}

REVIEW ISSUES:
{issues_text}

REPLACEMENT PAPER CANDIDATES (verified from academic databases):
{replacements_text}

Instructions:
1. For issues with action="replace": swap the flagged paper with the BEST candidate from the replacement list. Use EXACT title and metadata from the candidate.
2. For issues with action="recategorize": change the paper's category as appropriate.
3. For issues with action="note" (coverage gaps, structural): adjust topic descriptions or add clarifying context, but do NOT invent unverified papers.
4. Keep ALL papers that were NOT flagged — do not remove or modify them.
5. Preserve all module/topic IDs, structure, and Korean context sentences for unchanged papers.
6. Write new Korean context sentences for any newly added replacement papers.

IMPORTANT: Output ALL {num_modules} modules. Do not skip any.

Return ONLY valid JSON:
{{
  "modules": [ ... same schema as input ... ]
}}"""

        refine_tokens = max(4000, num_modules * 1200)

        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model="gpt-5.4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_completion_tokens=refine_tokens,

        )

        result = self._parse_llm_json(response, "Step4-Refine")
        refined_modules = result.get("modules", [])

        if len(refined_modules) < num_modules:
            logger.warning(
                "Step 4: Refine expected %d modules but got %d, keeping original for missing",
                num_modules, len(refined_modules),
            )

        # Build refined curriculum preserving top-level metadata
        refined = {**curriculum, "modules": refined_modules}
        return refined
