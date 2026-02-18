"""
Keyword Extractor - 쿼리에서 이중 레벨 키워드 추출

사용자 쿼리에서 LLM을 사용하여
- Low-level keywords: 구체적 엔티티 (methods, datasets, tools)
- High-level keywords: 추상적 주제/테마
를 추출한다.
"""
import os
import json
import re
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class KeywordExtractor:
    """쿼리에서 low-level/high-level 키워드 추출"""

    KEYWORD_PROMPT = """Given the following academic research query, extract keywords at two levels:

1. **Low-level keywords**: Specific, concrete entities mentioned or implied (methods, models, datasets, tools, metrics, specific techniques)
2. **High-level keywords**: Broader themes, research areas, and abstract concepts

## Query
{query}

## Output (JSON only, no markdown)
{{
  "low_level": ["keyword1", "keyword2", "keyword3"],
  "high_level": ["theme1", "theme2"]
}}"""

    def __init__(self, model: str = "gpt-4o-mini", api_key: Optional[str] = None):
        if not OPENAI_AVAILABLE:
            raise ImportError("openai package is required")

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key is required")

        self.client = OpenAI(api_key=self.api_key)
        self.model = model

    def extract_keywords(self, query: str) -> Dict[str, List[str]]:
        """쿼리에서 이중 레벨 키워드 추출"""
        prompt = self.KEYWORD_PROMPT.format(query=query)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Extract academic keywords from queries. Respond with JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=500,
            )

            content = response.choices[0].message.content.strip()
            result = self._parse_json(content)

            low = [k.strip().lower() for k in result.get("low_level", []) if k.strip()]
            high = [k.strip().lower() for k in result.get("high_level", []) if k.strip()]

            return {"low_level": low, "high_level": high}

        except Exception as e:
            print(f"  Keyword extraction failed: {e}")
            # fallback: 쿼리 단어를 그대로 사용
            words = [w.strip().lower() for w in query.split() if len(w) > 2]
            return {"low_level": words, "high_level": words[:3]}

    @staticmethod
    def _parse_json(content: str) -> dict:
        """JSON 파싱 (마크다운 코드 블록 제거 포함)"""
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*", "", content)
        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {"low_level": [], "high_level": []}
