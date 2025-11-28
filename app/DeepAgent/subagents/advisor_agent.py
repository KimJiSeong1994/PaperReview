"""
Advisor SubAgent
지도교수 에이전트 - 검증 및 맥락 유지
"""
import sys
from typing import Dict, Any, List
from pathlib import Path

# 경로 추가
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from deepagents import SubAgent
from langchain_core.tools import tool


# ==================== Advisor Tools ====================

@tool
def validate_analysis_completeness(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    분석의 완전성 검증
    
    Args:
        analysis: 연구원의 분석 결과
        
    Returns:
        검증 결과
    """
    required_sections = [
        "structure_analysis",
        "key_contributions",
        "methodology",
        "reproducibility"
    ]
    
    completeness_check = {
        section: section in analysis and analysis[section] is not None
        for section in required_sections
    }
    
    completeness_score = sum(completeness_check.values()) / len(completeness_check)
    
    missing_sections = [
        section for section, present in completeness_check.items() 
        if not present
    ]
    
    return {
        "completeness_score": completeness_score,
        "is_complete": completeness_score == 1.0,
        "missing_sections": missing_sections,
        "validation": "APPROVED" if completeness_score >= 0.75 else "NEEDS_REVISION"
    }


@tool
def check_scientific_accuracy(analysis: Dict[str, Any], paper_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    과학적 정확성 검증
    
    Args:
        analysis: 연구원의 분석 결과
        paper_data: 원본 논문 데이터
        
    Returns:
        정확성 검증 결과
    """
    # 기본 정보 일치 확인
    checks = {
        "title_matches": (
            analysis.get("structure_analysis", {}).get("title", "") 
            == paper_data.get("title", "")
        ),
        "has_methodology_analysis": (
            "methodology" in analysis 
            and len(analysis.get("methodology", {}).get("detected_methods", [])) > 0
        ),
        "has_contributions": (
            "key_contributions" in analysis 
            and len(analysis.get("key_contributions", [])) > 0
        ),
    }
    
    accuracy_score = sum(checks.values()) / len(checks)
    
    return {
        "accuracy_score": accuracy_score,
        "checks": checks,
        "validation": "APPROVED" if accuracy_score >= 0.7 else "NEEDS_REVIEW"
    }


@tool
def identify_cross_paper_themes(analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    여러 논문 간 공통 테마 식별
    
    Args:
        analyses: 여러 논문 분석 결과 리스트
        
    Returns:
        공통 테마 및 패턴
    """
    # 모든 분석에서 methodology 추출
    all_methods = []
    for analysis in analyses:
        methods = analysis.get("methodology", {}).get("detected_methods", [])
        all_methods.extend(methods)
    
    # 빈도 계산
    method_counts = {}
    for method in all_methods:
        method_counts[method] = method_counts.get(method, 0) + 1
    
    # 공통 테마 (2개 이상의 논문에서 등장)
    common_themes = {
        method: count 
        for method, count in method_counts.items() 
        if count >= 2
    }
    
    # 재현성 트렌드
    reproducibility_scores = [
        analysis.get("reproducibility", {}).get("reproducibility_score", 0)
        for analysis in analyses
    ]
    avg_reproducibility = sum(reproducibility_scores) / len(reproducibility_scores) if reproducibility_scores else 0
    
    return {
        "total_papers": len(analyses),
        "common_themes": common_themes,
        "unique_methods": len(method_counts),
        "avg_reproducibility": avg_reproducibility,
        "reproducibility_trend": "high" if avg_reproducibility >= 0.7 else "medium" if avg_reproducibility >= 0.4 else "low"
    }


@tool
def synthesize_findings(analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    여러 분석 결과 종합
    
    Args:
        analyses: 여러 논문 분석 결과
        
    Returns:
        종합 분석
    """
    # 공통 테마
    themes = identify_cross_paper_themes.invoke({"analyses": analyses})
    
    # 각 논문별 핵심 요약
    paper_summaries = []
    for i, analysis in enumerate(analyses, 1):
        paper_summaries.append({
            "paper_number": i,
            "paper_id": analysis.get("paper_id", f"paper_{i}"),
            "methods": analysis.get("methodology", {}).get("detected_methods", []),
            "reproducibility": analysis.get("reproducibility", {}).get("assessment", "unknown"),
            "contribution_count": len(analysis.get("key_contributions", []))
        })
    
    return {
        "cross_paper_analysis": themes,
        "individual_summaries": paper_summaries,
        "synthesis_status": "completed"
    }


@tool
def provide_feedback(
    analysis: Dict[str, Any], 
    validation_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    연구원에게 피드백 제공
    
    Args:
        analysis: 분석 결과
        validation_result: 검증 결과
        
    Returns:
        피드백
    """
    feedback = {
        "paper_id": analysis.get("paper_id", "unknown"),
        "overall_assessment": validation_result.get("validation", "UNKNOWN"),
        "strengths": [],
        "areas_for_improvement": [],
        "specific_comments": []
    }
    
    # 강점 식별
    if validation_result.get("completeness_score", 0) >= 0.8:
        feedback["strengths"].append("Comprehensive analysis coverage")
    
    if analysis.get("reproducibility", {}).get("reproducibility_score", 0) >= 0.7:
        feedback["strengths"].append("Thorough reproducibility assessment")
    
    # 개선 영역
    missing = validation_result.get("missing_sections", [])
    if missing:
        feedback["areas_for_improvement"].append(
            f"Missing sections: {', '.join(missing)}"
        )
    
    if validation_result.get("accuracy_score", 1.0) < 0.8:
        feedback["areas_for_improvement"].append(
            "Some accuracy concerns - review methodology analysis"
        )
    
    # 구체적 코멘트
    if validation_result.get("validation") == "APPROVED":
        feedback["specific_comments"].append(
            "✅ Analysis approved. High quality work."
        )
    elif validation_result.get("validation") == "NEEDS_REVISION":
        feedback["specific_comments"].append(
            "⚠️ Revisions needed. Please address the areas for improvement."
        )
    
    return feedback


# ==================== Advisor SubAgent ====================

def create_advisor_subagent() -> SubAgent:
    """
    Advisor SubAgent 생성
    
    Returns:
        SubAgent 인스턴스 (dict)
    """
    from app.DeepAgent.system_prompts import ADVISOR_AGENT_PROMPT
    
    advisor = SubAgent(
        name="advisor",
        instructions=ADVISOR_AGENT_PROMPT,
        tools=[
            validate_analysis_completeness,
            check_scientific_accuracy,
            identify_cross_paper_themes,
            synthesize_findings,
            provide_feedback,
        ],
    )
    
    return advisor


# ==================== Standalone Validation Function ====================

def validate_and_synthesize(
    analyses: List[Dict[str, Any]], 
    papers: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    분석 결과 검증 및 종합 (SubAgent 없이 직접 실행)
    
    Args:
        analyses: 연구원들의 분석 결과
        papers: 원본 논문 데이터
        
    Returns:
        검증 및 종합 결과
    """
    # 개별 검증
    validations = []
    for analysis, paper in zip(analyses, papers):
        # 완전성 검증
        completeness = validate_analysis_completeness.invoke({"analysis": analysis})
        
        # 정확성 검증
        accuracy = check_scientific_accuracy.invoke({
            "analysis": analysis,
            "paper_data": paper
        })
        
        # 피드백 생성
        feedback = provide_feedback.invoke({
            "analysis": analysis,
            "validation_result": {
                **completeness,
                "accuracy_score": accuracy.get("accuracy_score", 0)
            }
        })
        
        validations.append({
            "paper_id": analysis.get("paper_id"),
            "completeness": completeness,
            "accuracy": accuracy,
            "feedback": feedback,
            "overall_status": completeness.get("validation", "UNKNOWN")
        })
    
    # 종합 분석
    synthesis = synthesize_findings.invoke({"analyses": analyses})
    
    # 전체 평가
    approved_count = sum(
        1 for v in validations 
        if v.get("overall_status") == "APPROVED"
    )
    
    return {
        "individual_validations": validations,
        "cross_paper_synthesis": synthesis,
        "summary": {
            "total_papers": len(analyses),
            "approved": approved_count,
            "needs_revision": len(analyses) - approved_count,
            "approval_rate": approved_count / len(analyses) if analyses else 0
        },
        "validation_status": "completed"
    }

