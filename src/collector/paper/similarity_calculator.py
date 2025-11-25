import os
import numpy as np
from typing import Dict, Any, Optional, List
import sys
from dotenv import load_dotenv

# .env 파일에서 환경 변수 로드
load_dotenv()

sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from utils.logger import log_data_processing

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True

except ImportError:
    OPENAI_AVAILABLE = False
    print("Warning: OpenAI package not installed. Please install with: pip install openai")

class SimilarityCalculator:
    """LLM 기반 논문 유사도 계산 클래스"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "text-embedding-3-small"):
        if not OPENAI_AVAILABLE:
            raise ImportError("OpenAI package is required. Install with: pip install openai")
        
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY environment variable or pass api_key parameter.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.embedding_cache = {}  # 캐시를 위한 딕셔너리
    
    def _get_paper_text(self, paper: Dict[str, Any]) -> str:
        """논문에서 유사도 계산에 사용할 텍스트 추출"""
        parts = [f"Title: {paper['title']}" if paper.get('title') else None,
                 f"Abstract: {paper['abstract']}" if paper.get('abstract') else None,
                 f"Content: {(paper['full_text'][:2000] + '...' if len(paper.get('full_text', '')) > 2000 else paper.get('full_text', ''))}" if paper.get('full_text') else None]
        return "\n\n".join([p for p in parts if p]) if any(parts) else ""
    
    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """텍스트를 embedding으로 변환"""
        if not text or not text.strip():
            return None
        
        # 캐시 확인
        text_hash = hash(text)
        if text_hash in self.embedding_cache:
            return self.embedding_cache[text_hash]
        
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text[:8000]  # 최대 토큰 제한 고려
            )
            embedding = np.array(response.data[0].embedding)
            
            # 캐시에 저장
            self.embedding_cache[text_hash] = embedding
            return embedding
            
        except Exception as e:
            print(f"Error generating embedding: {e}")
            return None
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Cosine similarity 계산"""
        if vec1 is None or vec2 is None: return 0.0
        norm1, norm2 = np.linalg.norm(vec1), np.linalg.norm(vec2)
        return float(np.dot(vec1, vec2) / (norm1 * norm2)) if norm1 > 0 and norm2 > 0 else 0.0
    
    @log_data_processing("Similarity Calculation")
    def calculate_similarity(self, paper1: Dict[str, Any], paper2: Dict[str, Any]) -> float:
        """두 논문 간의 유사도 계산"""
        text1, text2 = self._get_paper_text(paper1), self._get_paper_text(paper2)
        if not text1 or not text2: return 0.0
        embedding1, embedding2 = self._get_embedding(text1), self._get_embedding(text2)
        return max(0.0, min(1.0, self._cosine_similarity(embedding1, embedding2))) if embedding1 is not None and embedding2 is not None else 0.0
    
    def calculate_batch_similarities(self, main_paper: Dict[str, Any], reference_papers: List[Dict[str, Any]]) -> List[float]:
        """메인 논문과 여러 참고문헌 논문 간의 유사도 일괄 계산"""
        main_embedding = self._get_embedding(self._get_paper_text(main_paper))
        if main_embedding is None: return [0.0] * len(reference_papers)
        
        similarities = []
        for ref in reference_papers:
            ref_embedding = self._get_embedding(self._get_paper_text(ref))
            if ref_embedding is not None:
                sim = self._cosine_similarity(main_embedding, ref_embedding)
                similarities.append(max(0.0, min(1.0, sim)))
            else:
                similarities.append(0.0)
        return similarities
    
    def add_similarity_scores(self, main_paper: Dict[str, Any], references: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """참고문헌에 유사도 점수 추가"""
        if not references: return references
        
        similarities = self.calculate_batch_similarities(main_paper, references)
        list(map(lambda x: x[1].update({'similarity_score': round(x[0], 4), 'similarity_percentage': round(x[0] * 100, 2)}), zip(similarities, references)))
        return references

