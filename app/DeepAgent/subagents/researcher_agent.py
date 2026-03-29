"""
Researcher SubAgent
PhD 연구원 에이전트 - 논문 심층 분석 전담
"""
import sys
from typing import Dict, Any, List
from pathlib import Path

# 경로 추가

from deepagents import SubAgent
from langchain_core.tools import tool


# ==================== Researcher Tools ====================

@tool
def analyze_paper_structure(paper_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    논문 구조 분석

    Args:
        paper_data: 논문 데이터 (title, abstract, full_text 등)

    Returns:
        구조 분석 결과
    """
    return {
        "has_abstract": "abstract" in paper_data and len(paper_data.get("abstract", "")) > 0,
        "has_full_text": "full_text" in paper_data and len(paper_data.get("full_text", "")) > 0,
        "title": paper_data.get("title", ""),
        "authors": paper_data.get("authors", []),
        "year": paper_data.get("year"),
        "venue": paper_data.get("venue", ""),
        "sections_available": paper_data.get("sections", []),
    }


@tool
def extract_key_contributions(paper_data: Dict[str, Any]) -> List[str]:
    """
    논문의 주요 기여 추출

    Args:
        paper_data: 논문 데이터

    Returns:
        주요 기여 리스트
    """
    # Abstract에서 contribution 관련 키워드 찾기
    abstract = paper_data.get("abstract", "")

    # 간단한 휴리스틱 (실제로는 LLM을 사용하거나 더 정교한 분석 필요)
    contribution_keywords = [
        "we propose",
        "we introduce",
        "we present",
        "we develop",
        "our contribution",
        "main contribution",
        "key contribution"
    ]

    contributions = []
    for line in abstract.split('.'):
        line_lower = line.lower()
        if any(keyword in line_lower for keyword in contribution_keywords):
            contributions.append(line.strip())

    return contributions if contributions else ["Contribution extraction requires full text analysis"]


@tool
def identify_methodology(paper_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    논문의 방법론 식별

    Args:
        paper_data: 논문 데이터

    Returns:
        방법론 정보
    """
    # 키워드 기반 방법론 분류
    text = (paper_data.get("abstract", "") + " " + paper_data.get("full_text", "")).lower()

    methodologies = {
        "deep_learning": any(kw in text for kw in ["deep learning", "neural network", "cnn", "rnn", "transformer"]),
        "machine_learning": any(kw in text for kw in ["machine learning", "classification", "regression"]),
        "nlp": any(kw in text for kw in ["natural language", "nlp", "language model", "text processing"]),
        "computer_vision": any(kw in text for kw in ["computer vision", "image", "visual", "object detection"]),
        "graph": any(kw in text for kw in ["graph neural", "graph convolution", "node", "edge"]),
        "rag": any(kw in text for kw in ["retrieval augmented", "rag", "retrieval-augmented"]),
    }

    return {
        "detected_methods": [k for k, v in methodologies.items() if v],
        "requires_deep_read": len([v for v in methodologies.values() if v]) == 0
    }


@tool
def assess_reproducibility(paper_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    재현 가능성 평가

    Args:
        paper_data: 논문 데이터

    Returns:
        재현 가능성 평가 결과
    """
    text = (paper_data.get("abstract", "") + " " + paper_data.get("full_text", "")).lower()

    indicators = {
        "code_available": any(kw in text for kw in ["github", "code available", "open source", "repository"]),
        "dataset_public": any(kw in text for kw in ["public dataset", "benchmark", "open dataset"]),
        "hyperparameters_specified": any(kw in text for kw in ["hyperparameter", "learning rate", "batch size"]),
        "implementation_details": "implementation" in text or "experiment" in text,
    }

    score = sum(indicators.values()) / len(indicators)

    return {
        **indicators,
        "reproducibility_score": score,
        "assessment": "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"
    }


# ==================== Researcher SubAgent ====================

def create_researcher_subagent(researcher_id: str = "researcher") -> SubAgent:
    """
    Researcher SubAgent 생성

    Args:
        researcher_id: 연구원 식별자

    Returns:
        SubAgent 인스턴스 (dict)
    """
    from app.DeepAgent.system_prompts import RESEARCHER_AGENT_PROMPT

    researcher = SubAgent(
        name=f"{researcher_id}",
        instructions=RESEARCHER_AGENT_PROMPT,
        tools=[
            analyze_paper_structure,
            extract_key_contributions,
            identify_methodology,
            assess_reproducibility,
        ],
    )

    return researcher


# ==================== Standalone Analysis Function ====================

def analyze_paper_deep(paper_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    논문 심층 분석 (SubAgent 없이 직접 실행)

    Args:
        paper_data: 논문 데이터

    Returns:
        분석 결과
    """
    # 구조 분석
    structure = analyze_paper_structure.invoke({"paper_data": paper_data})

    # 기여 추출
    contributions = extract_key_contributions.invoke({"paper_data": paper_data})

    # 방법론 식별
    methodology = identify_methodology.invoke({"paper_data": paper_data})

    # 재현성 평가
    reproducibility = assess_reproducibility.invoke({"paper_data": paper_data})

    return {
        "paper_id": paper_data.get("id", paper_data.get("arxiv_id", "unknown")),
        "structure_analysis": structure,
        "key_contributions": contributions,
        "methodology": methodology,
        "reproducibility": reproducibility,
        "analysis_status": "completed"
    }

