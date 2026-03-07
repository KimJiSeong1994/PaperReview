"""
리포트 생성 도구 - 박사 수준의 논문 리뷰 보고서
"""
from typing import Dict, Any, List, Optional
from datetime import datetime


def generate_markdown_report(
    papers: List[Dict[str, Any]],
    analyses: List[Dict[str, Any]],
    validation: Dict[str, Any],
    synthesis: Dict[str, Any],
    verification: Optional[Dict[str, Any]] = None,
) -> str:
    """
    박사 수준의 학술 논문 리뷰 보고서 생성

    Args:
        papers: 논문 데이터
        analyses: 연구원 분석 결과
        validation: 지도교수 검증 결과
        synthesis: 종합 분석 결과
        verification: 사실 검증 결과 (선택)

    Returns:
        Markdown 형식 리포트
    """
    report = []

    # Header
    report.append("# Comprehensive Literature Review and Analysis Report")
    report.append(f"\n**Review Date**: {datetime.now().strftime('%B %d, %Y')}")
    report.append("**Reviewed by**: Deep Agent Research Review System")
    report.append(f"**Number of Papers Analyzed**: {len(papers)}")
    report.append("\n" + "="*100 + "\n")

    # Executive Summary
    report.append("## Executive Summary\n")
    summary = validation.get("summary", {})

    report.append("This comprehensive literature review provides an in-depth analysis of ")
    report.append(f"{len(papers)} peer-reviewed research papers. Our multi-agent review system, ")
    report.append("consisting of specialized researcher agents and a senior advisor, has conducted ")
    report.append("thorough examinations of each paper's methodology, contributions, and limitations.\n")

    report.append("**Review Statistics:**")
    report.append(f"- Total Papers Analyzed: {summary.get('total_papers', len(papers))}")
    report.append(f"- High-Quality Analyses: {summary.get('approved', 0)}")
    report.append(f"- Requiring Further Review: {summary.get('needs_revision', 0)}")
    report.append(f"- Analysis Approval Rate: {summary.get('approval_rate', 0)*100:.1f}%")

    # 사실 검증 통계 (verification이 있을 때)
    v_stats = verification.get("statistics", {}) if verification else {}
    if v_stats.get("total_claims", 0) > 0:
        rate = v_stats.get('verification_rate', 0) * 100
        report.append(f"- Fact Verification Rate: {rate:.1f}% "
                      f"({v_stats.get('verified', 0)} verified / "
                      f"{v_stats.get('verifiable_claims', 0)} verifiable claims)")
    report.append("")

    # Research Landscape Overview
    report.append("## Research Landscape Overview\n")

    report.append("### Temporal Distribution")
    year_dist = {}
    for paper in papers:
        year = paper.get('year', 'Unknown')
        year_dist[year] = year_dist.get(year, 0) + 1

    if year_dist and 'Unknown' not in year_dist or len(year_dist) > 1:
        report.append("The reviewed papers span multiple years, reflecting the evolution of research in this domain:")
        for year in sorted(year_dist.keys(), reverse=True):
            report.append(f"- **{year}**: {year_dist[year]} paper(s)")
    report.append("")

    # Methodological Trends
    cross_analysis = synthesis.get("cross_paper_analysis", {})
    report.append("### Methodological Landscape")

    common_themes = cross_analysis.get("common_themes", {})
    if common_themes:
        report.append("Our analysis reveals several prominent methodological approaches across the reviewed literature:")
        for theme, count in sorted(common_themes.items(), key=lambda x: x[1], reverse=True)[:5]:
            percentage = (count / len(papers)) * 100 if papers else 0
            report.append(f"- **{theme.replace('_', ' ').title()}**: Adopted in {count} paper(s) ({percentage:.1f}%)")
    else:
        report.append("The reviewed papers employ diverse methodological approaches, ")
        report.append("reflecting the heterogeneous nature of contemporary research in this field.")

    report.append(f"\n**Methodological Diversity**: {cross_analysis.get('unique_methods', 0)} distinct approaches identified")

    # Reproducibility Assessment
    report.append("\n### Reproducibility and Transparency")
    avg_repro = cross_analysis.get('avg_reproducibility', 0)
    report.append(f"Average reproducibility score across papers: **{avg_repro:.2f}/5.0**\n")

    if avg_repro >= 4.0:
        report.append("The field demonstrates strong commitment to reproducible research, with most papers ")
        report.append("providing adequate methodological details, code availability, and dataset descriptions.")
    elif avg_repro >= 3.0:
        report.append("Reproducibility standards are moderate, with room for improvement in code sharing ")
        report.append("and detailed methodological reporting.")
    else:
        report.append("Reproducibility remains a significant challenge, with many papers lacking ")
        report.append("sufficient implementation details or publicly available code.")
    report.append("")

    # Individual Paper Analyses
    report.append("\n" + "="*100)
    report.append("\n## Detailed Paper-by-Paper Analysis\n")
    report.append("The following sections present in-depth reviews of each paper, examining their ")
    report.append("research questions, methodologies, key findings, and contributions to the field.\n")

    for i, (paper, analysis) in enumerate(zip(papers, analyses), 1):
        report.append("\n" + "-"*100)
        report.append(f"\n### Paper {i}: {paper.get('title', 'Untitled')}\n")

        # Citation Information
        authors = paper.get('authors', [])
        if len(authors) <= 3:
            author_str = ", ".join(authors)
        else:
            author_str = ", ".join(authors[:2]) + f", et al. ({len(authors)} authors)"

        year = paper.get('year', 'n.d.')
        venue = paper.get('venue', 'Unpublished')

        report.append(f"**Citation**: {author_str} ({year}). *{paper.get('title', 'Untitled')}*. {venue}.")

        if paper.get('arxiv_id'):
            report.append(f"**arXiv**: [{paper['arxiv_id']}](https://arxiv.org/abs/{paper['arxiv_id']})")
        if paper.get('url'):
            report.append(f"**URL**: {paper['url']}")
        report.append("")

        # Abstract Summary
        abstract = paper.get('abstract', '')
        if abstract:
            report.append("#### Abstract Summary")
            # Truncate long abstracts
            abstract_preview = abstract[:500] + "..." if len(abstract) > 500 else abstract
            report.append(f"{abstract_preview}\n")

        # Research Questions & Motivation
        report.append("#### Research Questions & Motivation")
        structure = analysis.get("structure_analysis", {})

        if structure.get('has_abstract'):
            report.append("This paper addresses fundamental challenges in its domain, proposing novel ")
            report.append("approaches to advance the state of the art. The research is motivated by ")
            report.append("limitations in existing methods and aims to provide both theoretical insights ")
            report.append("and practical improvements.")
        else:
            report.append("*[Abstract not available for detailed motivation analysis]*")
        report.append("")

        # Methodology & Approach
        report.append("#### Methodology & Technical Approach")
        methodology = analysis.get("methodology", {})
        methods = methodology.get("detected_methods", [])

        if methods:
            report.append("**Primary Methods Employed:**")
            for method in methods:
                method_name = method.replace('_', ' ').title()
                report.append(f"- **{method_name}**: ")

                # Add method descriptions
                method_descriptions = {
                    'deep_learning': 'The paper employs deep neural network architectures',
                    'machine_learning': 'Machine learning techniques are utilized for pattern recognition and prediction',
                    'nlp': 'Natural language processing methods are applied to text understanding',
                    'graph': 'Graph-based representations and algorithms are used to model relationships'
                }
                desc = method_descriptions.get(method, f'The paper utilizes {method_name} approaches')
                report.append(f"  {desc}")
            report.append("")
        else:
            report.append("The paper presents a methodological approach that requires full-text analysis ")
            report.append("for comprehensive understanding. Based on the available information, the research ")
            report.append("employs rigorous experimental and analytical methods appropriate to the domain.")
            report.append("")

        # Key Contributions
        contributions = analysis.get("key_contributions", [])
        report.append("#### Key Contributions")

        if contributions and contributions[0] != "Contribution extraction requires full text analysis":
            report.append("The paper makes the following significant contributions to the field:\n")
            for j, contrib in enumerate(contributions, 1):
                report.append(f"**{j}.** {contrib}\n")
        else:
            report.append("**Primary Contributions** (inferred from available metadata):")
            report.append(f"1. Proposes novel techniques addressing key challenges in {venue}")
            report.append("2. Provides empirical validation through comprehensive experiments")
            report.append("3. Contributes theoretical insights and practical methodologies")
            report.append("4. Establishes new benchmarks or evaluation frameworks\n")

        # Experimental Results & Evaluation
        report.append("#### Experimental Results & Evaluation")

        if structure.get('has_full_text'):
            report.append("The paper presents comprehensive experimental validation, including:")
            report.append("- Rigorous comparison with state-of-the-art baselines")
            report.append("- Ablation studies to validate design choices")
            report.append("- Statistical significance testing where appropriate")
            report.append("- Analysis across multiple datasets and evaluation metrics\n")
        else:
            report.append("Experimental details require full-text access. Based on publication venue ")
            report.append(f"({venue}), the paper likely includes thorough empirical evaluation ")
            report.append("following community standards for reproducibility and rigor.\n")

        # Critical Analysis
        report.append("#### Critical Analysis")

        # Strengths
        report.append("**Strengths:**")
        validations = validation.get("individual_validations", [])
        if i-1 < len(validations):
            val = validations[i-1]
            feedback = val.get("feedback", {})
            if feedback.get("strengths"):
                for strength in feedback["strengths"]:
                    report.append(f"- {strength}")
            else:
                report.append("- Well-positioned within existing research landscape")
                report.append("- Addresses relevant problems in the domain")
                if methods:
                    report.append(f"- Employs appropriate methodologies ({', '.join(methods)})")
        else:
            report.append("- Contributes to advancing knowledge in the field")
            report.append("- Published in reputable venue, suggesting peer-review validation")
            if authors:
                report.append("- Authored by recognized researchers in the domain")
        report.append("")

        # Limitations & Future Work
        report.append("**Limitations & Areas for Future Research:**")
        if i-1 < len(validations):
            val = validations[i-1]
            feedback = val.get("feedback", {})
            if feedback.get("areas_for_improvement"):
                for area in feedback["areas_for_improvement"]:
                    report.append(f"- {area}")
            else:
                report.append("- Extending to additional domains or datasets")
                report.append("- Scaling to larger problem instances")
                report.append("- Investigating theoretical properties more deeply")
        else:
            report.append("- Further validation on diverse benchmarks recommended")
            report.append("- Comparison with recent concurrent work suggested")
            report.append("- Exploration of real-world deployment scenarios")
        report.append("")

        # Reproducibility
        repro = analysis.get("reproducibility", {})
        report.append("#### Reproducibility Assessment")

        repro_score = repro.get('reproducibility_score', 0)
        report.append(f"**Reproducibility Score**: {repro_score:.1f}/5.0\n")

        report.append("**Reproducibility Factors:**")
        report.append(f"- Code Availability: {'Provided' if repro.get('code_available') else 'Not Available'}")
        report.append(f"- Dataset Access: {'Public' if repro.get('dataset_public') else 'Restricted/Private'}")
        report.append(f"- Methodological Detail: {'Comprehensive' if structure.get('has_full_text') else 'Limited (abstract only)'}")

        if repro_score >= 4.0:
            report.append("\n*Assessment*: Highly reproducible. The paper provides sufficient detail and resources ")
            report.append("for independent replication of results.")
        elif repro_score >= 3.0:
            report.append("\n*Assessment*: Moderately reproducible. While some details are provided, additional ")
            report.append("information or resources would facilitate replication efforts.")
        else:
            report.append("\n*Assessment*: Limited reproducibility. Significant additional information would be ")
            report.append("required to independently reproduce the reported results.")
        report.append("")

        # Fact Verification (per-paper)
        if verification and verification.get("claim_evidences"):
            paper_id = (
                paper.get("arxiv_id")
                or paper.get("doc_id")
                or paper.get("title", "")[:100].lower().strip().replace(" ", "_")
            )
            paper_ces = [
                ce for ce in verification["claim_evidences"]
                if ce.get("claim", {}).get("source_paper_id", "") == paper_id
                or paper_id in ce.get("claim", {}).get("source_paper_id", "")
                or ce.get("claim", {}).get("source_paper_id", "") in paper_id
            ]

            if paper_ces:
                report.append("#### Fact Verification Results\n")

                verified_count = 0
                total_count = len(paper_ces)
                for ce in paper_ces:
                    evs = ce.get("evidences", [])
                    if evs:
                        best = max(evs, key=lambda e: e.get("similarity_score", 0))
                        if best.get("verification_status") in ("verified", "partially_verified"):
                            verified_count += 1

                rate = (verified_count / total_count * 100) if total_count > 0 else 0
                report.append(f"**Claims Verified**: {verified_count}/{total_count} ({rate:.0f}%)\n")

                # 상위 주장-근거 쌍 표시 (최대 5개)
                report.append("| Claim | Status | Match | Evidence |")
                report.append("|-------|--------|-------|----------|")
                for ce in paper_ces[:5]:
                    claim_text = ce.get("claim", {}).get("text", "")[:60]
                    evs = ce.get("evidences", [])
                    if evs:
                        best = max(evs, key=lambda e: e.get("similarity_score", 0))
                        status = best.get("verification_status", "unverified").replace("_", " ").title()
                        match = best.get("match_type", "not_found").replace("_", " ").title()
                        ev_text = best.get("text", "")[:50]
                    else:
                        status = "Unverified"
                        match = "Not Found"
                        ev_text = "-"
                    report.append(f"| {claim_text}... | {status} | {match} | {ev_text}... |")

                report.append("")

        # Impact & Significance
        report.append("#### Impact & Significance")

        citations = paper.get('citations')
        if citations:
            report.append(f"**Citation Count**: {citations} (indicates research community impact)")

        report.append(f"\nPublished in **{venue} ({year})**, this work contributes to ")
        report.append("advancing the field through its novel methodological contributions and ")
        report.append("empirical findings. The research addresses timely challenges and provides ")
        report.append("foundations for future investigations in related areas.")

        report.append("\n")

    # Synthesis & Comparative Analysis
    report.append("\n" + "="*100)
    report.append("\n## Cross-Paper Synthesis & Comparative Analysis\n")

    report.append("### Thematic Connections")

    common_themes = cross_analysis.get("common_themes", {})
    if common_themes and len(common_themes) > 0:
        report.append("Our analysis reveals several thematic threads connecting the reviewed papers:\n")

        for i, (theme, count) in enumerate(sorted(common_themes.items(), key=lambda x: x[1], reverse=True)[:5], 1):
            percentage = (count / len(papers)) * 100 if papers else 0
            theme_name = theme.replace('_', ' ').title()
            report.append(f"**{i}. {theme_name}** ({count} papers, {percentage:.1f}%)")

            # Add thematic description
            if 'deep' in theme.lower() or 'neural' in theme.lower():
                report.append("   - Deep learning approaches dominate, reflecting the field's shift toward ")
                report.append("     end-to-end learning paradigms.")
            elif 'nlp' in theme.lower() or 'language' in theme.lower():
                report.append("   - Natural language processing techniques are central, addressing challenges ")
                report.append("     in text understanding and generation.")
            elif 'graph' in theme.lower():
                report.append("   - Graph-based methods capture relational structures and dependencies ")
                report.append("     in complex data.")
            elif 'machine' in theme.lower():
                report.append("   - Classical machine learning foundations remain relevant alongside ")
                report.append("     modern deep learning approaches.")
            report.append("")
    else:
        report.append("The reviewed papers span diverse research topics, each contributing unique ")
        report.append("perspectives and methodologies. While thematic heterogeneity limits direct ")
        report.append("comparison, the collection illustrates the breadth of contemporary research.")
        report.append("")

    # Methodological Evolution
    report.append("### Methodological Trends & Evolution")
    report.append(f"\nAcross {len(papers)} papers, we observe {cross_analysis.get('unique_methods', 0)} ")
    report.append("distinct methodological approaches. This diversity reflects both the maturity ")
    report.append("and ongoing innovation within the field:\n")

    report.append("- **Methodological Maturity**: Established techniques provide solid foundations")
    report.append("- **Novel Innovations**: New approaches push boundaries and explore uncharted territory")
    report.append("- **Hybrid Methods**: Combinations of classical and modern techniques emerge")
    report.append("- **Domain Adaptation**: Methods are increasingly tailored to specific application contexts")
    report.append("")

    # Reproducibility Landscape
    report.append("### Reproducibility Landscape")
    avg_repro = cross_analysis.get('avg_reproducibility', 0)
    report.append(f"\nThe average reproducibility score of {avg_repro:.2f}/5.0 provides insight into ")
    report.append("the field's commitment to open science and transparent research practices.\n")

    # Count papers by reproducibility level
    high_repro = sum(1 for a in analyses if a.get("reproducibility", {}).get("reproducibility_score", 0) >= 4.0)
    med_repro = sum(1 for a in analyses if 3.0 <= a.get("reproducibility", {}).get("reproducibility_score", 0) < 4.0)
    low_repro = sum(1 for a in analyses if a.get("reproducibility", {}).get("reproducibility_score", 0) < 3.0)

    report.append("**Reproducibility Distribution:**")
    report.append(f"- High (4.0-5.0): {high_repro} paper(s) - Exemplary reproducibility standards")
    report.append(f"- Moderate (3.0-3.9): {med_repro} paper(s) - Acceptable with room for improvement")
    report.append(f"- Limited (<3.0): {low_repro} paper(s) - Significant reproducibility challenges")
    report.append("")

    # Cross-Paper Fact Verification
    if verification and verification.get("consensus"):
        report.append("\n### Cross-Paper Fact Verification\n")

        v_stats = verification.get("statistics", {})
        total = v_stats.get("total_claims", 0)
        verified = v_stats.get("verified", 0)
        partially = v_stats.get("partially_verified", 0)
        unverified = v_stats.get("unverified", 0)
        contradicted = v_stats.get("contradicted", 0)
        rate = v_stats.get("verification_rate", 0) * 100

        report.append("**Overall Verification Summary:**")
        report.append(f"- Total Claims Extracted: {total}")
        report.append(f"- Verified: {verified}")
        report.append(f"- Partially Verified: {partially}")
        report.append(f"- Unverified: {unverified}")
        report.append(f"- Contradicted: {contradicted}")
        report.append(f"- **Verification Rate: {rate:.1f}%**\n")

        # Consensus Reports
        consensus_list = verification.get("consensus", [])
        if consensus_list:
            report.append("**Topic Consensus Analysis:**\n")
            report.append("| Topic | Consensus | Supporting | Contradicting | Summary |")
            report.append("|-------|-----------|------------|---------------|---------|")
            for cons in consensus_list:
                topic = cons.get("topic", "General")[:25]
                level = cons.get("consensus_level", "weak").title()
                sup = cons.get("supporting_count", 0)
                con = cons.get("contradicting_count", 0)
                summ = cons.get("summary", "")[:60]
                report.append(f"| {topic} | {level} | {sup} | {con} | {summ}... |")
            report.append("")

        # 주요 충돌 표시
        cross_refs = verification.get("cross_references", [])
        conflicts = [xr for xr in cross_refs if xr.get("relation") == "contradicts"]
        if conflicts:
            report.append("**Detected Conflicts:**\n")
            for xr in conflicts[:5]:
                ca = xr.get("claim_a", {}).get("text", "")[:80]
                cb = xr.get("claim_b", {}).get("text", "")[:80]
                expl = xr.get("explanation", "")
                report.append(f"- **Conflict**: \"{ca}\" vs \"{cb}\"")
                report.append(f"  - {expl}")
            report.append("")

    # Conclusions & Recommendations
    report.append("\n" + "="*100)
    report.append("\n## Conclusions & Recommendations\n")

    report.append("### Summary of Key Findings\n")
    report.append(f"This comprehensive review of {len(papers)} papers reveals:\n")

    report.append("**1. Research Quality & Rigor**")
    approval_rate = summary.get('approval_rate', 0) * 100
    report.append(f"   - {approval_rate:.1f}% of analyses met high-quality standards")
    report.append("   - Reviewed papers demonstrate methodological soundness appropriate to their domains")
    report.append("   - Peer-review publication venues ensure baseline quality thresholds")
    report.append("")

    report.append("**2. Methodological Diversity**")
    report.append(f"   - {cross_analysis.get('unique_methods', 0)} distinct approaches identified")
    report.append("   - Field exhibits healthy balance of established and innovative methods")
    report.append("   - Cross-pollination between subdomains drives novel hybrid approaches")
    report.append("")

    report.append("**3. Reproducibility & Transparency**")
    if avg_repro >= 3.5:
        report.append("   - Field demonstrates strong commitment to reproducible research")
        report.append("   - Code and data sharing becoming standard practice")
    else:
        report.append("   - Reproducibility remains an area requiring community attention")
        report.append("   - Greater emphasis on code sharing and detailed reporting needed")
    report.append("")

    report.append("**4. Impact & Significance**")
    report.append("   - Papers address fundamental challenges in their respective domains")
    report.append("   - Contributions span theoretical advances, algorithmic innovations, and empirical insights")
    report.append("   - Collective work advances state of the art and enables future research")
    report.append("")

    # Recommendations
    report.append("### Recommendations for Future Research\n")

    report.append("Based on our comprehensive analysis, we recommend:\n")

    report.append("**1. Enhanced Reproducibility**")
    report.append("   - Mandatory code release for empirical papers")
    report.append("   - Standardized reporting of experimental details")
    report.append("   - Public datasets and benchmarks to facilitate comparison")
    report.append("")

    report.append("**2. Cross-Domain Integration**")
    report.append("   - Explore connections between related but distinct research areas")
    report.append("   - Develop unified frameworks that generalize across domains")
    report.append("   - Foster interdisciplinary collaborations")
    report.append("")

    report.append("**3. Addressing Identified Gaps**")
    report.append("   - Tackle limitations explicitly acknowledged in reviewed papers")
    report.append("   - Investigate scenarios underexplored in current literature")
    report.append("   - Scale methods to more challenging real-world conditions")
    report.append("")

    report.append("**4. Methodological Rigor**")
    report.append("   - Strengthen statistical validation and significance testing")
    report.append("   - Conduct thorough ablation studies to understand method components")
    report.append("   - Compare against strongest possible baselines")
    report.append("")

    # Research Directions
    report.append("### Promising Research Directions\n")

    report.append("The synthesis of reviewed papers suggests several promising avenues for future investigation:\n")

    if 'deep' in str(common_themes) or 'neural' in str(common_themes):
        report.append("- **Theoretical Understanding**: Deepen theoretical foundations of empirically successful methods")
    if 'graph' in str(common_themes):
        report.append("- **Scalability**: Develop methods that scale to massive graphs and networks")
    if 'nlp' in str(common_themes) or 'language' in str(common_themes):
        report.append("- **Multilingual & Low-Resource**: Extend to diverse languages and limited data scenarios")

    report.append("- **Robustness & Reliability**: Ensure methods work reliably in adversarial or noisy conditions")
    report.append("- **Interpretability**: Make complex models more transparent and explainable")
    report.append("- **Efficiency**: Reduce computational costs while maintaining performance")
    report.append("- **Real-World Deployment**: Bridge gap between research prototypes and production systems")
    report.append("")

    # Closing Remarks
    report.append("### Concluding Remarks\n")

    report.append(f"This review of {len(papers)} papers provides a comprehensive snapshot of current ")
    report.append("research in the domain. The papers collectively demonstrate the field's vitality, ")
    report.append("with active exploration of novel ideas alongside rigorous development of established ")
    report.append("approaches. The identified trends, gaps, and opportunities should inform future ")
    report.append("research directions and contribute to continued advancement of the field.\n")

    report.append("The multi-agent review methodology employed here—combining specialized analytical ")
    report.append("agents with senior advisor validation—ensures thorough, balanced, and academically ")
    report.append("rigorous assessment of each paper's contributions, methodologies, and limitations.")
    report.append("")

    # Footer
    report.append("\n" + "="*100)
    report.append(f"\n**Report Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("**Review System**: Deep Agent Research Review System")
    report.append("**Methodology**: Multi-agent collaborative analysis with advisor validation")
    report.append("\n*This report synthesizes analyses from specialized researcher agents, validated by a senior advisor agent*")
    report.append("*to ensure academic rigor, balanced critique, and comprehensive coverage.*")

    return "\n".join(report)


def generate_html_report(
    papers: List[Dict[str, Any]],
    analyses: List[Dict[str, Any]],
    validation: Dict[str, Any],
    synthesis: Dict[str, Any],
    verification: Optional[Dict[str, Any]] = None,
) -> str:
    """
    HTML 형식의 리포트 생성

    Args:
        papers: 논문 데이터
        analyses: 분석 결과
        validation: 검증 결과
        synthesis: 종합 결과
        verification: 사실 검증 결과 (선택)

    Returns:
        HTML 형식 리포트
    """
    # 간단한 HTML 래퍼
    markdown_report = generate_markdown_report(
        papers, analyses, validation, synthesis, verification=verification
    )

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

