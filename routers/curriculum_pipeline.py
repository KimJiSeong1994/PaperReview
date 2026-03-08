"""
3-step Curriculum Generation Pipeline

Step 1: LLM generates curriculum structure (modules/topics + search keywords)
        referencing real university courses (MIT, Stanford, Oxford, CMU, etc.)
Step 2: OpenAlex API searches and verifies real papers per topic
Step 3: LLM assembles final curriculum with verified papers + Korean context
"""

import json
import logging
import asyncio
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)


class CurriculumPipeline:
    """Multi-step curriculum generation with SSE progress reporting."""

    def __init__(self, openai_client):
        self.client = openai_client

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
            async for event in self._step2_search_papers(structure, total_topics):
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
               "message": "Curriculum complete!"}

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
- Reference ACTUAL university courses that cover this topic or closely related topics.
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
      "url": ""
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

        # Scale max_tokens based on number of modules
        # ~300 tokens per module (id, title, description, inspired_by, 2-3 topics with keywords)
        structure_tokens = max(4000, num_modules * 500 + 1500)

        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=structure_tokens,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)

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

                    # Sort by citation count, take top papers
                    candidates.sort(key=lambda p: p.get("citations", 0), reverse=True)
                    topic_item["verified_papers"] = candidates[:6]
        finally:
            searcher.close()

        # Final yield: the updated structure (not a dict with 'step')
        yield structure

    # ── Step 3: Final Assembly ────────────────────────────────────────

    async def _step3_assemble(self, structure: dict, topic: str, difficulty: str) -> dict:
        """Assemble final curriculum. For large curricula (>5 modules), process in batches."""
        modules = structure.get("modules", [])
        ref_courses = structure.get("reference_courses", [])

        # For <=5 modules, single call. For >5, batch to avoid token truncation.
        batch_size = 5
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
                "module_description": module.get("description", ""),
                "topics": [],
            }
            for t in module.get("topics", []):
                topic_info = {
                    "topic_title": t["title"],
                    "verified_papers": [
                        {
                            "title": p["title"],
                            "authors": p.get("authors", [])[:5],
                            "year": p.get("year", ""),
                            "doi": p.get("doi", ""),
                            "citations": p.get("citations", 0),
                            "venue": p.get("venue", ""),
                        }
                        for p in t.get("verified_papers", [])
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

        # ~800 tokens per module (title, description, 2 topics × 3 papers with Korean context)
        assembly_tokens = max(4000, len(modules) * 1200)

        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=assembly_tokens,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
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
