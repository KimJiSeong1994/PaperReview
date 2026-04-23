"""
LLM 클라이언트 모듈
"""
import logging
import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class EmptyLLMResponseError(ValueError):
    """Raised when the LLM returns an empty or whitespace-only content body.

    This is NOT a valid answer and must never be treated as one. Callers
    should either retry or surface a failure to the user — they must not
    render the empty string as a response.
    """


class LLMClient:
    """LLM 클라이언트 클래스"""

    def __init__(self, model: str = "gpt-4", api_key: Optional[str] = None):
        if not OPENAI_AVAILABLE:
            raise ImportError("OpenAI package is required.")

        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OpenAI API key is required.")

        self.client = OpenAI(api_key=self.api_key)
        self.model = model

    PROMPT_TEMPLATE = """
You are an expert research assistant helping users understand academic papers.

Context from relevant papers:
{context}

User Query: {query}

Based on the provided context from academic papers, please provide a comprehensive answer to the user's query. Include:
1. Direct answers to the query
2. Key insights from the relevant papers
3. Relationships between different papers (if applicable)
4. Limitations or gaps in the current research (if relevant)

Answer:
"""

    def generate_response(self, context: str, query: str, temperature: float = 0.7) -> str:
        """LLM 응답 생성.

        F-04 fix: Never return an error string as if it were an answer. Never
        return ``None``. On empty content → raise ``EmptyLLMResponseError``.
        Any underlying exception (rate limit, network, etc.) is re-raised so
        the caller can distinguish "we asked and got nothing usable" from a
        successful answer.
        """
        prompt = self.PROMPT_TEMPLATE.format(context=context, query=query)

        # Note: exceptions from the OpenAI client propagate intentionally.
        # Callers must handle them — do NOT swallow into a return string.
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a research assistant expert in academic papers."},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature
        )

        content = response.choices[0].message.content or ""
        if not content.strip():
            logger.warning("[LLMClient] Empty LLM content for query length=%d", len(query))
            raise EmptyLLMResponseError("LLM returned empty content")

        return content

