"""
Entity Extractor - LLM 기반 논문 엔티티/관계 추출

논문 텍스트에서 학술 엔티티(Concept, Method, Dataset 등)와
엔티티 간 관계를 LLM으로 추출한다.
"""
import os
import json
import asyncio
import re
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

load_dotenv()

try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class EntityExtractor:
    """LLM 기반 논문 엔티티 및 관계 추출"""

    ENTITY_TYPES = ["Concept", "Method", "Dataset", "Task", "Metric", "Tool"]

    EXTRACTION_PROMPT = """You are an expert academic knowledge extractor. Given the following academic paper text, extract all key entities and their relationships.

## Entity Types
- **Concept**: Core theoretical concepts (e.g., "attention mechanism", "graph neural network")
- **Method**: Specific algorithms or models (e.g., "BERT", "ResNet", "Adam optimizer")
- **Dataset**: Datasets used (e.g., "ImageNet", "SQuAD", "COCO")
- **Task**: Research tasks (e.g., "object detection", "machine translation")
- **Metric**: Evaluation metrics (e.g., "F1-score", "BLEU", "accuracy")
- **Tool**: Frameworks or tools (e.g., "PyTorch", "TensorFlow", "Hugging Face")

## Rules
1. Use canonical, lowercase names for entities (e.g., "bert" not "BERT model")
2. Extract at most 20 entities and 15 relationships per paper
3. Each relationship must describe HOW the source and target are related
4. Include high-level theme keywords for each relationship

## Paper Text
{text}

## Output (JSON only, no markdown)
{{
  "entities": [
    {{"name": "entity name", "type": "Concept|Method|Dataset|Task|Metric|Tool", "description": "1-2 sentence description"}}
  ],
  "relationships": [
    {{"source": "source entity", "target": "target entity", "relationship": "how they relate", "keywords": ["theme1", "theme2"]}}
  ]
}}"""

    def __init__(self, model: str = "gpt-4o-mini", api_key: Optional[str] = None):
        if not OPENAI_AVAILABLE:
            raise ImportError("openai package is required for EntityExtractor")

        import ssl
        try:
            ssl._create_default_https_context = ssl._create_unverified_context
        except AttributeError:
            pass

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key is required")

        self.client = AsyncOpenAI(api_key=self.api_key)
        self.model = model

    def _prepare_paper_text(self, paper: Dict[str, Any], max_chars: int = 4000) -> str:
        """논문 텍스트 준비 (title + abstract + full_text 앞부분)"""
        parts = []
        title = paper.get("title", "")
        if title:
            parts.append(f"Title: {title}")

        abstract = paper.get("abstract", "")
        if abstract:
            parts.append(f"Abstract: {abstract}")

        full_text = paper.get("full_text", "")
        if full_text:
            remaining = max_chars - sum(len(p) for p in parts)
            if remaining > 200:
                parts.append(f"Content: {full_text[:remaining]}")

        return "\n\n".join(parts)

    def _get_paper_id(self, paper: Dict[str, Any]) -> str:
        """논문 ID 생성"""
        title = paper.get("title", "unknown")
        return title[:100].lower().strip().replace(" ", "_")

    async def extract_from_paper(self, paper: Dict[str, Any]) -> Dict[str, Any]:
        """단일 논문에서 엔티티/관계 추출"""
        text = self._prepare_paper_text(paper)
        paper_id = self._get_paper_id(paper)

        prompt = self.EXTRACTION_PROMPT.format(text=text)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You extract structured knowledge from academic papers. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=2000,
            )

            content = response.choices[0].message.content.strip()
            result = self._parse_json_response(content)

            # 출처 논문 ID 태깅
            for entity in result.get("entities", []):
                entity["source_paper_id"] = paper_id
            for rel in result.get("relationships", []):
                rel["source_paper_id"] = paper_id

            return {
                "paper_id": paper_id,
                "paper_title": paper.get("title", ""),
                "entities": result.get("entities", []),
                "relationships": result.get("relationships", []),
            }

        except Exception as e:
            print(f"  Entity extraction failed for '{paper.get('title', '')[:50]}': {e}")
            return {
                "paper_id": paper_id,
                "paper_title": paper.get("title", ""),
                "entities": [],
                "relationships": [],
            }

    async def extract_batch(
        self, papers: List[Dict[str, Any]], max_concurrent: int = 4
    ) -> List[Dict[str, Any]]:
        """배치 엔티티 추출 (동시성 제어)"""
        semaphore = asyncio.Semaphore(max_concurrent)
        results = []

        async def _extract_with_semaphore(paper, idx):
            async with semaphore:
                title = paper.get("title", "")[:50]
                print(f"  [{idx+1}/{len(papers)}] Extracting: {title}...")
                return await self.extract_from_paper(paper)

        tasks = [
            _extract_with_semaphore(paper, i)
            for i, paper in enumerate(papers)
        ]
        results = await asyncio.gather(*tasks)
        return list(results)

    def extract_batch_sync(
        self, papers: List[Dict[str, Any]], max_concurrent: int = 4
    ) -> List[Dict[str, Any]]:
        """동기 배치 추출 (asyncio.run wrapper)"""
        return asyncio.run(self.extract_batch(papers, max_concurrent))

    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        """LLM 응답에서 JSON 파싱 (코드 블록 처리 포함)"""
        # markdown 코드 블록 제거
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)
        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # JSON 부분만 추출 시도
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {"entities": [], "relationships": []}

    # ─── Chunking ───

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 100) -> List[str]:
        """텍스트를 청크로 분할"""
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            # 문장 경계에서 자르기
            if end < len(text):
                boundary = text.rfind(".", start, end)
                if boundary > start + chunk_size // 2:
                    end = boundary + 1

            chunks.append(text[start:end].strip())
            start = end - overlap

        return [c for c in chunks if c]
