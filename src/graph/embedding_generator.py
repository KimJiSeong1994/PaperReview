"""
논문 임베딩 생성 모듈
"""
import os
import json
import numpy as np
from typing import Dict, List, Any, Optional
import sys
from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.join(os.path.dirname(__file__), '../../'))
from utils.logger import log_data_processing

try:
    from collector.paper.deduplicator import PaperDeduplicator
    _normalize_title = PaperDeduplicator.normalize_title
    _normalize_doi = PaperDeduplicator.normalize_doi
except ImportError:
    def _normalize_title(t):
        return t.lower().strip() if t else ""

    def _normalize_doi(d):
        return ""

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OpenAI = None  # type: ignore
    OPENAI_AVAILABLE = False

class EmbeddingGenerator:
    """논문 임베딩 생성 클래스"""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        use_openai: bool = True,
        fallback_dim: int = 384
    ):
        self.embedding_cache = {}
        self.use_openai = use_openai and OPENAI_AVAILABLE
        self.fallback_dim = fallback_dim

        if self.use_openai:
            self.api_key = api_key or os.getenv('OPENAI_API_KEY')
            if not self.api_key:
                raise ValueError("OpenAI API key is required.")
            self.client = OpenAI(api_key=self.api_key)
            self.model = model
        else:
            self.api_key = None
            self.client = None
            self.model = model
            if use_openai and not OPENAI_AVAILABLE:
                print("Warning: OpenAI package not available. Using deterministic fallback embeddings.")

    def _get_paper_text(self, paper: Dict[str, Any]) -> str:
        """논문에서 임베딩 생성용 텍스트 추출"""
        parts = [f"Title: {paper['title']}" if paper.get('title') else None,
                 f"Abstract: {paper['abstract']}" if paper.get('abstract') else None,
                 f"Content: {(paper['full_text'][:2000] + '...' if len(paper.get('full_text', '')) > 2000 else paper.get('full_text', ''))}" if paper.get('full_text') else None]
        return "\n\n".join([p for p in parts if p]) if any(parts) else ""

    def _tokenize(self, text: str) -> List[str]:
        """간단한 토크나이저 (알파벳/숫자 기반)"""
        import re

        text = text.lower()
        tokens = re.findall(r"[a-z0-9]+", text)
        return [t for t in tokens if len(t) > 1]

    def _generate_fallback_embedding(self, text: str) -> Optional[np.ndarray]:
        """OpenAI 미사용 시 Hashing 기반 문맥 임베딩 생성"""
        if not text:
            return None

        import hashlib

        vector = np.zeros(self.fallback_dim, dtype='float32')
        tokens = self._tokenize(text)
        if not tokens:
            return None

        for token in tokens:
            token_hash = hashlib.md5(token.encode('utf-8')).digest()
            idx = int.from_bytes(token_hash[:4], 'little') % self.fallback_dim
            vector[idx] += 1.0

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm
        return vector

    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """텍스트를 embedding으로 변환"""
        if not text or not text.strip():
            return None

        text_hash = hash(text)
        if text_hash in self.embedding_cache:
            return self.embedding_cache[text_hash]

        try:
            if self.use_openai and self.client:
                response = self.client.embeddings.create(model=self.model, input=text[:8000])
                embedding = np.array(response.data[0].embedding).astype('float32')
            else:
                embedding = self._generate_fallback_embedding(text)
                if embedding is None:
                    return None

            self.embedding_cache[text_hash] = embedding
            return embedding
        except Exception as e:
            print(f"Error generating embedding: {e}")
            return None

    @log_data_processing("Embedding Generation")
    def generate_embedding(self, paper: Dict[str, Any]) -> Optional[np.ndarray]:
        """단일 논문의 임베딩 생성"""
        text = self._get_paper_text(paper)
        return self._get_embedding(text)

    def generate_batch_embeddings(self, papers: List[Dict[str, Any]], batch_size: int = 100) -> Dict[str, np.ndarray]:
        """여러 논문의 임베딩 배치 생성"""
        embeddings = {}

        for i, paper in enumerate(papers):
            if i % 10 == 0:
                print(f"  [{i+1}/{len(papers)}] 임베딩 생성 중...")

            paper_id = self._generate_paper_id(paper)
            embedding = self.generate_embedding(paper)

            if embedding is not None:
                embeddings[paper_id] = embedding

        return embeddings

    def _generate_paper_id(self, paper: Dict[str, Any]) -> str:
        """논문 고유 ID 생성 (DOI 우선, 없으면 정규화 제목)"""
        doi = _normalize_doi(paper.get('doi', ''))
        if doi:
            return f"doi:{doi}"
        title = _normalize_title(paper.get('title', ''))
        return title[:100] if title else str(hash(str(paper)))

    def save_embeddings(self, embeddings: Dict[str, np.ndarray], output_dir: str = "data/embeddings"):
        """임베딩을 파일로 저장"""
        os.makedirs(output_dir, exist_ok=True)

        # FAISS 인덱스 생성
        try:
            import faiss

            if not embeddings:
                print("저장할 임베딩이 없습니다.")
                return

            embedding_list = list(embeddings.values())
            paper_ids = list(embeddings.keys())

            embeddings_array = np.array(embedding_list).astype('float32')
            dimension = embeddings_array.shape[1]

            # Cosine similarity를 위한 정규화
            faiss.normalize_L2(embeddings_array)

            # FAISS 인덱스 생성
            index = faiss.IndexFlatIP(dimension)  # Inner Product = Cosine Similarity (정규화 후)
            index.add(embeddings_array)

            # 저장
            index_path = os.path.join(output_dir, 'paper_embeddings.index')
            faiss.write_index(index, index_path)
            print(f"✓ FAISS 인덱스 저장: {index_path}")

            # ID 매핑 저장
            mapping_path = os.path.join(output_dir, 'paper_id_mapping.json')
            with open(mapping_path, 'w', encoding='utf-8') as f:
                json.dump(paper_ids, f, ensure_ascii=False, indent=2)
            print(f"✓ ID 매핑 저장: {mapping_path}")

        except ImportError:
            print("Warning: FAISS not installed. Saving as JSON instead.")
            # JSON으로 저장 (대안)
            json_path = os.path.join(output_dir, 'embeddings.json')
            embeddings_dict = {k: v.tolist() for k, v in embeddings.items()}
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(embeddings_dict, f, ensure_ascii=False, indent=2)
            print(f"✓ 임베딩 저장: {json_path}")

