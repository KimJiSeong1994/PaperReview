"""
Style Guide Manager

스타일 가이드 파일을 로딩하고 도메인을 감지하여
적절한 가이드를 반환하는 매니저.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 도메인별 키워드 매핑
DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "nlp_agent": [
        "transformer", "llm", "agent", "prompt", "language model",
        "nlp", "bert", "gpt", "attention", "tokenizer", "embedding",
        "rag", "retrieval", "generation", "fine-tuning", "instruction",
        "chatbot", "dialogue", "multi-agent", "chain-of-thought",
    ],
    "cv": [
        "image", "vision", "detection", "segmentation", "cnn",
        "convolution", "resnet", "yolo", "object detection",
        "classification", "gan", "diffusion", "visual",
        "pixel", "feature map", "bounding box",
    ],
    "theory": [
        "theorem", "proof", "convergence", "bound", "complexity",
        "optimization", "gradient", "loss function", "regret",
        "approximation", "generalization", "sample complexity",
        "pac learning", "vc dimension",
    ],
}


class StyleGuideManager:
    """스타일 가이드 로딩 및 도메인 감지 매니저"""

    def __init__(self, guides_dir: Optional[Path] = None):
        """
        Args:
            guides_dir: 스타일 가이드 디렉토리 경로.
                        None이면 기본 위치 사용.
        """
        self.guides_dir = guides_dir or Path(__file__).parent / "style_guides"
        self._guides: Dict[str, str] = {}
        self._load_guides()

    def _load_guides(self):
        """디렉토리에서 모든 .md 가이드 파일 로딩"""
        if not self.guides_dir.exists():
            logger.warning("[StyleGuideManager] Guides directory not found: %s", self.guides_dir)
            return

        for md_file in self.guides_dir.glob("*.md"):
            key = md_file.stem  # e.g., "academic_poster_general"
            try:
                self._guides[key] = md_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("[StyleGuideManager] Failed to load %s: %s", md_file.name, e)

        logger.info("[StyleGuideManager] Loaded %d style guides", len(self._guides))

    def get_guide(self, domain: str = "general") -> str:
        """
        범용 가이드 + 도메인 가이드 결합 반환.

        Args:
            domain: 도메인 이름 ("general", "nlp_agent", "cv", "theory")

        Returns:
            결합된 스타일 가이드 텍스트
        """
        parts = []

        # 범용 가이드
        general = self._guides.get("academic_poster_general", "")
        if general:
            parts.append(general)

        # 도메인 가이드 (general이 아닌 경우)
        if domain != "general":
            domain_key = f"{domain}_style"
            domain_guide = self._guides.get(domain_key, "")
            if domain_guide:
                parts.append(f"\n---\n\n## Domain-Specific Guide: {domain}\n\n{domain_guide}")

        return "\n".join(parts)

    def detect_domain(self, keywords: List[str]) -> str:
        """
        키워드 기반 도메인 자동 감지.

        Args:
            keywords: 논문/리포트 키워드 리스트

        Returns:
            감지된 도메인 이름 ("general", "nlp_agent", "cv", "theory")
        """
        if not keywords:
            return "general"

        keywords_lower = [kw.lower().strip() for kw in keywords]
        scores: Dict[str, int] = {}

        for domain, domain_kws in DOMAIN_KEYWORDS.items():
            score = 0
            for kw in keywords_lower:
                for dkw in domain_kws:
                    if dkw in kw or kw in dkw:
                        score += 1
            scores[domain] = score

        if not scores:
            return "general"

        best_domain = max(scores, key=scores.get)
        if scores[best_domain] >= 2:
            return best_domain

        return "general"

    def list_guides(self) -> List[str]:
        """사용 가능한 가이드 이름 목록 반환"""
        return list(self._guides.keys())
