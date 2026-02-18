"""
LLM 클라이언트 모듈
"""
import os
import sys
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

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
        """LLM 응답 생성"""
        prompt = self.PROMPT_TEMPLATE.format(context=context, query=query)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a research assistant expert in academic papers."},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature
            )
            
            return response.choices[0].message.content
        except Exception as e:
            return f"Error generating response: {str(e)}"

