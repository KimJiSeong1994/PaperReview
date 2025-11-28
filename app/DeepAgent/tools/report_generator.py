"""
리포트 생성 도구
"""
from typing import Dict, Any, List
from datetime import datetime


def generate_markdown_report(
    papers: List[Dict[str, Any]],
    analyses: List[Dict[str, Any]],
    validation: Dict[str, Any],
    synthesis: Dict[str, Any]
) -> str:
    """
    Markdown 형식의 최종 리뷰 리포트 생성
    
    Args:
        papers: 논문 데이터
        analyses: 연구원 분석 결과
        validation: 지도교수 검증 결과
        synthesis: 종합 분석 결과
        
    Returns:
        Markdown 형식 리포트
    """
    report = []
    
    # Header
    report.append("# Paper Review Report")
    report.append(f"\n**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"\n**Total Papers**: {len(papers)}")
    report.append("\n" + "="*80 + "\n")
    
    # Executive Summary
    report.append("## Executive Summary\n")
    summary = validation.get("summary", {})
    report.append(f"- **Papers Reviewed**: {summary.get('total_papers', 0)}")
    report.append(f"- **Approved Analyses**: {summary.get('approved', 0)}")
    report.append(f"- **Needs Revision**: {summary.get('needs_revision', 0)}")
    report.append(f"- **Approval Rate**: {summary.get('approval_rate', 0)*100:.1f}%")
    
    # Cross-Paper Synthesis
    report.append("\n## Cross-Paper Synthesis\n")
    cross_analysis = synthesis.get("cross_paper_analysis", {})
    
    report.append("### Common Themes")
    common_themes = cross_analysis.get("common_themes", {})
    if common_themes:
        for theme, count in sorted(common_themes.items(), key=lambda x: x[1], reverse=True):
            report.append(f"- **{theme.replace('_', ' ').title()}**: {count} papers")
    else:
        report.append("- No common themes identified across papers")
    
    report.append(f"\n### Research Trends")
    report.append(f"- **Unique Methods**: {cross_analysis.get('unique_methods', 0)}")
    report.append(f"- **Average Reproducibility**: {cross_analysis.get('avg_reproducibility', 0):.2f}")
    report.append(f"- **Reproducibility Trend**: {cross_analysis.get('reproducibility_trend', 'unknown').upper()}")
    
    # Individual Paper Analyses
    report.append("\n" + "="*80)
    report.append("\n## Individual Paper Analyses\n")
    
    for i, (paper, analysis) in enumerate(zip(papers, analyses), 1):
        report.append(f"### Paper {i}: {paper.get('title', 'Untitled')}\n")
        
        # Basic Info
        report.append("**Metadata:**")
        authors = paper.get('authors', [])
        author_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
        report.append(f"- Authors: {author_str}")
        report.append(f"- Year: {paper.get('year', 'N/A')}")
        report.append(f"- Venue: {paper.get('venue', 'N/A')}")
        if paper.get('arxiv_id'):
            report.append(f"- arXiv ID: {paper['arxiv_id']}")
        report.append("")
        
        # Structure Analysis
        structure = analysis.get("structure_analysis", {})
        report.append("**Structure:**")
        report.append(f"- Abstract Available: {'✅' if structure.get('has_abstract') else '❌'}")
        report.append(f"- Full Text Available: {'✅' if structure.get('has_full_text') else '❌'}")
        report.append("")
        
        # Key Contributions
        contributions = analysis.get("key_contributions", [])
        report.append("**Key Contributions:**")
        if contributions and contributions[0] != "Contribution extraction requires full text analysis":
            for j, contrib in enumerate(contributions, 1):
                report.append(f"{j}. {contrib}")
        else:
            report.append("- Requires full text analysis for detailed contributions")
        report.append("")
        
        # Methodology
        methodology = analysis.get("methodology", {})
        methods = methodology.get("detected_methods", [])
        report.append("**Methodology:**")
        if methods:
            report.append(f"- Detected Methods: {', '.join(m.replace('_', ' ').title() for m in methods)}")
        else:
            report.append("- Requires deeper analysis to identify specific methods")
        report.append("")
        
        # Reproducibility
        repro = analysis.get("reproducibility", {})
        report.append("**Reproducibility Assessment:**")
        report.append(f"- Score: {repro.get('reproducibility_score', 0):.2f}")
        report.append(f"- Assessment: {repro.get('assessment', 'unknown').upper()}")
        report.append(f"- Code Available: {'✅' if repro.get('code_available') else '❌'}")
        report.append(f"- Public Dataset: {'✅' if repro.get('dataset_public') else '❌'}")
        report.append("")
        
        # Validation Status
        validations = validation.get("individual_validations", [])
        if i-1 < len(validations):
            val = validations[i-1]
            feedback = val.get("feedback", {})
            report.append("**Validation Status:**")
            status = val.get("overall_status", "UNKNOWN")
            status_icon = "✅" if status == "APPROVED" else "⚠️" if status == "NEEDS_REVISION" else "❓"
            report.append(f"- Status: {status_icon} {status}")
            
            if feedback.get("strengths"):
                report.append("- Strengths:")
                for strength in feedback["strengths"]:
                    report.append(f"  - {strength}")
            
            if feedback.get("areas_for_improvement"):
                report.append("- Areas for Improvement:")
                for area in feedback["areas_for_improvement"]:
                    report.append(f"  - {area}")
        
        report.append("\n" + "-"*80 + "\n")
    
    # Conclusions
    report.append("## Conclusions\n")
    report.append("### Key Findings")
    report.append("1. Research quality and reproducibility vary across papers")
    report.append("2. Common methodological themes identified")
    report.append("3. Validation process ensures academic rigor")
    
    report.append("\n### Recommendations")
    report.append("1. Address identified limitations in future work")
    report.append("2. Improve reproducibility standards")
    report.append("3. Increase cross-paper collaboration opportunities")
    
    # Footer
    report.append("\n" + "="*80)
    report.append("\n*Report generated by Deep Agent Research Review System*")
    
    return "\n".join(report)


def generate_html_report(
    papers: List[Dict[str, Any]],
    analyses: List[Dict[str, Any]],
    validation: Dict[str, Any],
    synthesis: Dict[str, Any]
) -> str:
    """
    HTML 형식의 리포트 생성
    
    Args:
        papers: 논문 데이터
        analyses: 분석 결과
        validation: 검증 결과
        synthesis: 종합 결과
        
    Returns:
        HTML 형식 리포트
    """
    # 간단한 HTML 래퍼
    markdown_report = generate_markdown_report(papers, analyses, validation, synthesis)
    
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Paper Review Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        pre {{
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            white-space: pre-wrap;
            word-wrap: break-word;
        }}
    </style>
</head>
<body>
    <pre>{markdown_report}</pre>
</body>
</html>
    """
    
    return html

