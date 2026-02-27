"""
Deep Review Agent
실제 deepagents 패키지를 사용한 Master Agent 구현
"""
import os
import sys
import json
import logging
import threading
from typing import List, Dict, Any, Optional
from pathlib import Path

# 경로 추가
sys.path.append(str(Path(__file__).parent.parent.parent))

from deepagents import create_deep_agent, SubAgent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.DeepAgent.workspace_manager import WorkspaceManager
from app.DeepAgent.system_prompts import (
    MASTER_AGENT_PROMPT,
    RESEARCHER_AGENT_PROMPT,
    ADVISOR_AGENT_PROMPT
)

logger = logging.getLogger(__name__)


# ==================== Custom Tools ====================

@tool
def load_papers_tool(paper_ids: str) -> str:
    """
    Load papers from IDs (comma-separated string or JSON list)
    
    Args:
        paper_ids: Comma-separated paper IDs (e.g., "id1,id2,id3") or JSON list
        
    Returns:
        JSON string with paper data
    """
    from app.DeepAgent.tools.paper_loader import load_papers_from_ids
    
    # Parse IDs - handle multiple formats
    try:
        # Try to parse as JSON list first
        if paper_ids.strip().startswith('['):
            ids = json.loads(paper_ids)
        else:
            # Parse as comma-separated string
            ids = [pid.strip() for pid in paper_ids.split(',')]
    except Exception as e:
        print(f"[WARNING] Error parsing paper_ids: {e}")
        # Fallback: treat as single ID
        ids = [paper_ids.strip()]
    
    # Ensure all IDs are strings
    ids = [str(pid) for pid in ids if pid]
    
    print(f"[INFO] Loading {len(ids)} papers: {ids}")
    
    # Load papers
    papers = load_papers_from_ids(ids)
    
    return json.dumps({
        "success": True,
        "count": len(papers),
        "papers": papers
    }, ensure_ascii=False)


@tool
def save_analysis_result(researcher_id: str, paper_id: str, analysis: str) -> str:
    """
    Save researcher's analysis result to workspace
    
    Args:
        researcher_id: Researcher identifier
        paper_id: Paper ID
        analysis: Analysis result (JSON string)
        
    Returns:
        Confirmation message
    """
    # Get workspace from context (will be set by DeepReviewAgent)
    workspace = getattr(save_analysis_result, '_workspace', None)
    if not workspace:
        return "Error: Workspace not available"
    
    try:
        analysis_data = json.loads(analysis) if isinstance(analysis, str) else analysis
        
        path = workspace.save_researcher_analysis(
            researcher_id=researcher_id,
            paper_id=paper_id,
            analysis=analysis_data
        )
        
        return f"[v] Analysis saved to {path}"
    except Exception as e:
        return f"Error saving analysis: {e}"


@tool
def get_all_analyses() -> str:
    """
    Get all researcher analyses from workspace
    
    Returns:
        JSON string with all analyses
    """
    workspace = getattr(get_all_analyses, '_workspace', None)
    if not workspace:
        return json.dumps({"error": "Workspace not available"})
    
    analyses = workspace.load_all_analyses()
    
    return json.dumps({
        "count": len(analyses),
        "analyses": analyses
    }, ensure_ascii=False)


@tool
def save_validation_result(validation: str) -> str:
    """
    Save advisor's validation result
    
    Args:
        validation: Validation result (JSON string)
        
    Returns:
        Confirmation message
    """
    workspace = getattr(save_validation_result, '_workspace', None)
    if not workspace:
        return "Error: Workspace not available"
    
    try:
        validation_data = json.loads(validation) if isinstance(validation, str) else validation
        
        path = workspace.save_advisor_validation(validation_data)
        
        return f"[v] Validation saved to {path}"
    except Exception as e:
        return f"Error saving validation: {e}"


@tool
def generate_final_report(title: str) -> str:
    """
    Generate and save final review report
    
    Args:
        title: Report title
        
    Returns:
        Report file path
    """
    workspace = getattr(generate_final_report, '_workspace', None)
    if not workspace:
        return "Error: Workspace not available"
    
    try:
        from app.DeepAgent.tools.report_generator import generate_markdown_report
        
        # Load data
        papers = workspace.load_selected_papers()
        analyses = workspace.load_all_analyses()
        validation = workspace.load_latest_validation()
        
        if not validation:
            return "Error: No validation found"
        
        # Extract analysis data
        analysis_list = [a.get('analysis', {}) for a in analyses]
        
        # Generate report
        report = generate_markdown_report(
            papers=papers,
            analyses=analysis_list,
            validation=validation.get('validation', {}),
            synthesis=validation.get('validation', {}).get('cross_paper_synthesis', {})
        )
        
        # Save
        path = workspace.save_final_report(report, format="markdown")
        
        return f"[v] Report saved to {path}"
    except Exception as e:
        return f"Error generating report: {e}"


# ==================== LLM-based Deep Research Tools ====================

# Global LLM instance for tools (thread-safe)
_llm_lock = threading.Lock()
_llm_instance = None

def get_llm():
    """Get or create LLM instance for tools (thread-safe)"""
    global _llm_instance
    with _llm_lock:
        if _llm_instance is None:
            _llm_instance = ChatOpenAI(
                model="gpt-4o-mini",
                temperature=0.3,
                request_timeout=30,
            )
        return _llm_instance


def _parse_paper_json(paper_json: str) -> dict:
    """Safely parse paper JSON"""
    try:
        return json.loads(paper_json)
    except json.JSONDecodeError:
        try:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(paper_json)
            return data
        except Exception:
            return {}


def _format_authors(authors: list, max_count: int = 5) -> str:
    """Safely format authors list to string, handling various formats"""
    if not authors:
        return "Unknown"
    
    formatted = []
    for author in authors[:max_count]:
        if isinstance(author, str):
            formatted.append(author)
        elif isinstance(author, dict):
            # Try common author dict formats
            name = author.get('name') or author.get('full_name') or author.get('author') or str(author)
            formatted.append(name)
        else:
            formatted.append(str(author))
    
    result = ', '.join(formatted)
    if len(authors) > max_count:
        result += f' et al. (+{len(authors) - max_count} more)'
    
    return result


@tool
def analyze_paper_deep(paper_json: str) -> str:
    """
    Perform deep analysis of a paper using LLM
    
    This tool conducts comprehensive analysis including:
    - Research problem and motivation
    - Methodology and technical approach
    - Key contributions and innovations
    - Experimental results and findings
    - Strengths and limitations
    
    Args:
        paper_json: Paper data as JSON string containing title, abstract, authors, etc.
        
    Returns:
        Comprehensive analysis result as JSON string
    """
    paper_data = _parse_paper_json(paper_json)
    if not paper_data:
        return json.dumps({"error": "Invalid paper data"})
    
    title = paper_data.get("title", "Unknown Title")
    abstract = paper_data.get("abstract", "")
    authors = paper_data.get("authors", [])
    year = paper_data.get("year", "")
    full_text = paper_data.get("full_text", "")
    
    # Use abstract if no full text available
    content = full_text if full_text else abstract
    if not content:
        return json.dumps({
            "error": "No content available for analysis",
            "title": title
        })
    
    # Truncate content if too long (for API limits)
    max_content_length = 8000
    if len(content) > max_content_length:
        content = content[:max_content_length] + "\n\n[Content truncated for analysis...]"
    
    llm = get_llm()
    
    # Format authors safely
    authors_str = _format_authors(authors, max_count=5)
    
    analysis_prompt = f"""You are a PhD-level research analyst. Conduct a comprehensive deep analysis of this academic paper.

**Paper Information:**
- Title: {title}
- Authors: {authors_str}
- Year: {year}

**Paper Content:**
{content}

**Provide a detailed analysis in the following structure:**

## 1. Research Problem & Motivation
- What problem does this paper address?
- Why is this problem important?
- What gaps in existing research does it fill?

## 2. Methodology & Technical Approach
- What methods/algorithms are proposed?
- How does the approach work technically?
- What are the key innovations compared to prior work?

## 3. Key Contributions
- List the main contributions (3-5 items)
- What is novel and significant about each?

## 4. Experimental Results
- What experiments were conducted?
- What were the main findings?
- How does it compare to baselines?

## 5. Strengths
- What are the paper's strongest aspects?
- What does it do exceptionally well?

## 6. Limitations & Future Work
- What are the weaknesses or limitations?
- What questions remain unanswered?
- What future research directions are suggested?

## 7. Impact Assessment
- What is the potential impact of this work?
- How might it influence future research?

Be specific, evidence-based, and cite paper content where relevant."""

    try:
        print(f"[Step] Deep analyzing: {title[:50]}...")
        response = llm.invoke(analysis_prompt)
        analysis_text = response.content
        
        return json.dumps({
            "success": True,
            "title": title,
            "analysis_type": "deep_research",
            "analysis": analysis_text,
            "metadata": {
                "authors": authors,
                "year": year,
                "has_full_text": bool(full_text),
                "content_length": len(content)
            }
        }, ensure_ascii=False)
        
    except Exception as e:
        print(f"[ERROR] Error in deep analysis: {e}")
        return json.dumps({
            "error": str(e),
            "title": title
        })


@tool
def extract_key_contributions(paper_json: str) -> str:
    """
    Extract and analyze the key contributions of a paper using LLM
    
    Args:
        paper_json: Paper data as JSON string
        
    Returns:
        Key contributions analysis as JSON string
    """
    paper_data = _parse_paper_json(paper_json)
    if not paper_data:
        return json.dumps({"error": "Invalid paper data"})
    
    title = paper_data.get("title", "")
    abstract = paper_data.get("abstract", "")
    content = paper_data.get("full_text", "") or abstract
    
    if not content:
        return json.dumps({"error": "No content available", "title": title})
    
    llm = get_llm()
    
    prompt = f"""Analyze this academic paper and extract the key contributions:

**Title:** {title}

**Content:**
{content[:5000]}

**Task:** Identify and explain the main contributions of this paper.

For each contribution, provide:
1. A clear, concise statement of the contribution
2. Why it is significant
3. How it advances the field

Format your response as a numbered list with detailed explanations."""

    try:
        print(f"[INFO] Extracting contributions: {title[:50]}...")
        response = llm.invoke(prompt)
        
        return json.dumps({
            "success": True,
            "title": title,
            "contributions": response.content
        }, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({"error": str(e), "title": title})


@tool
def analyze_methodology(paper_json: str) -> str:
    """
    Perform deep methodology analysis using LLM
    
    Analyzes the research methodology, technical approach, and implementation details.
    
    Args:
        paper_json: Paper data as JSON string
        
    Returns:
        Methodology analysis as JSON string
    """
    paper_data = _parse_paper_json(paper_json)
    if not paper_data:
        return json.dumps({"error": "Invalid paper data"})
    
    title = paper_data.get("title", "")
    abstract = paper_data.get("abstract", "")
    content = paper_data.get("full_text", "") or abstract
    
    if not content:
        return json.dumps({"error": "No content available", "title": title})
    
    llm = get_llm()
    
    prompt = f"""Analyze the methodology of this academic paper:

**Title:** {title}

**Content:**
{content[:6000]}

**Provide detailed analysis of:**

## 1. Research Design
- What type of research is this? (empirical, theoretical, experimental, etc.)
- What is the overall research framework?

## 2. Technical Approach
- What algorithms or methods are used?
- How do they work technically?
- What are the key equations or formulations?

## 3. Data & Experiments
- What datasets are used?
- How are experiments designed?
- What metrics are used for evaluation?

## 4. Implementation Details
- What tools/frameworks are mentioned?
- What hyperparameters or configurations are used?
- How reproducible is the approach?

## 5. Methodological Innovations
- What is novel about this methodology?
- How does it differ from existing approaches?

## 6. Methodological Limitations
- What are the assumptions made?
- What are the potential weaknesses?"""

    try:
        print(f"[INFO] Analyzing methodology: {title[:50]}...")
        response = llm.invoke(prompt)
        
        # Detect method categories
        content_lower = content.lower()
        detected_methods = []
        method_keywords = {
            "deep_learning": ["deep learning", "neural network", "cnn", "rnn", "transformer", "attention"],
            "machine_learning": ["machine learning", "classification", "regression", "clustering", "svm"],
            "nlp": ["natural language", "nlp", "language model", "text", "embedding", "bert", "gpt"],
            "graph_neural": ["graph neural", "gcn", "gnn", "node", "graph convolution"],
            "reinforcement_learning": ["reinforcement learning", "rl", "reward", "policy"],
            "computer_vision": ["image", "vision", "object detection", "segmentation"]
        }
        
        for method, keywords in method_keywords.items():
            if any(kw in content_lower for kw in keywords):
                detected_methods.append(method)
        
        return json.dumps({
            "success": True,
            "title": title,
            "methodology_analysis": response.content,
            "detected_methods": detected_methods
        }, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({"error": str(e), "title": title})


@tool
def critical_analysis(paper_json: str) -> str:
    """
    Perform critical analysis of a paper - evaluating strengths, weaknesses, and impact
    
    Args:
        paper_json: Paper data as JSON string
        
    Returns:
        Critical analysis as JSON string
    """
    paper_data = _parse_paper_json(paper_json)
    if not paper_data:
        return json.dumps({"error": "Invalid paper data"})
    
    title = paper_data.get("title", "")
    abstract = paper_data.get("abstract", "")
    content = paper_data.get("full_text", "") or abstract
    
    if not content:
        return json.dumps({"error": "No content available", "title": title})
    
    llm = get_llm()
    
    prompt = f"""Conduct a critical academic analysis of this paper:

**Title:** {title}

**Content:**
{content[:6000]}

**Provide a balanced critical analysis:**

## Strengths
1. **Technical Innovation**: What technical contributions are noteworthy?
2. **Experimental Rigor**: How thorough and valid are the experiments?
3. **Presentation Quality**: How well is the work presented?
4. **Practical Impact**: What practical applications are enabled?

## Weaknesses
1. **Methodological Limitations**: What are the approach's limitations?
2. **Experimental Gaps**: What experiments are missing or insufficient?
3. **Assumptions**: What assumptions might not hold in practice?
4. **Scalability Concerns**: Are there scalability or efficiency issues?

## Reproducibility Assessment
- Is the method clearly described enough to reproduce?
- Is code/data available?
- Are hyperparameters and configurations specified?

## Impact Potential
- How significant is this work for the field?
- What future research does it enable?
- What are the broader implications?

Be constructive but rigorous in your critique."""

    try:
        print(f"[INFO] Critical analysis: {title[:50]}...")
        response = llm.invoke(prompt)
        
        return json.dumps({
            "success": True,
            "title": title,
            "critical_analysis": response.content
        }, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({"error": str(e), "title": title})


# ==================== SubAgent Definitions ====================

def create_researcher_subagent_for_deepagent(researcher_id: int) -> SubAgent:
    """
    Create a Researcher SubAgent for deepagents with LLM-powered deep research tools
    
    Args:
        researcher_id: Researcher number
        
    Returns:
        SubAgent specification (dict)
    """
    researcher = SubAgent(
        name=f"researcher_{researcher_id}",
        description=f"Expert PhD-level researcher who conducts deep analysis of academic papers using LLM-powered tools, focusing on methodology, contributions, and critical evaluation",
        system_prompt=f"""
{RESEARCHER_AGENT_PROMPT}

You are Researcher #{researcher_id}, a PhD-level research analyst. Your mission is to conduct DEEP RESEARCH on assigned papers.

## Your Deep Research Process:

### Step 1: Comprehensive Analysis
Use `analyze_paper_deep` tool to perform thorough analysis covering:
- Research problem and motivation
- Methodology and technical approach
- Key contributions and innovations
- Experimental results
- Strengths and limitations
- Impact assessment

### Step 2: Contribution Extraction
Use `extract_key_contributions` tool to identify:
- Main contributions (3-5 items)
- Significance of each contribution
- How it advances the field

### Step 3: Methodology Deep-Dive
Use `analyze_methodology` tool to examine:
- Research design and framework
- Technical approach and algorithms
- Data, experiments, and metrics
- Implementation details
- Methodological innovations and limitations

### Step 4: Critical Evaluation
Use `critical_analysis` tool to provide:
- Balanced strengths and weaknesses
- Reproducibility assessment
- Impact potential evaluation

### Step 5: Save Results
Use `save_analysis_result` tool to save your complete analysis.

## Guidelines:
- Be OBJECTIVE and EVIDENCE-BASED
- Quote or reference specific paper content
- Provide constructive but rigorous critique
- Consider both theoretical and practical implications
- Think about how this paper fits in the broader research landscape

Your analysis should be PhD thesis quality - thorough, rigorous, and insightful.
        """.strip(),
        tools=[
            analyze_paper_deep,
            extract_key_contributions,
            analyze_methodology,
            critical_analysis,
            save_analysis_result,
        ],
    )
    
    return researcher


# ==================== Advisor Tools (Global) ====================

@tool
def validate_and_improve_analysis(analysis_json: str) -> str:
    """
    Validate researcher's analysis and provide improvement feedback using LLM
    
    Args:
        analysis_json: Researcher's analysis as JSON string
        
    Returns:
        Validation result with feedback
    """
    analysis_data = _parse_paper_json(analysis_json)
    if not analysis_data:
        return json.dumps({"error": "Invalid analysis data", "validation": "ERROR"})
    
    llm = get_llm()
    
    analysis_content = analysis_data.get("analysis", "")
    title = analysis_data.get("title", "Unknown")
    
    prompt = f"""You are a Senior Professor reviewing a PhD researcher's paper analysis.

**Paper Title:** {title}

**Researcher's Analysis:**
{analysis_content[:6000] if isinstance(analysis_content, str) else json.dumps(analysis_content)[:6000]}

**Evaluate the analysis on these criteria:**

## 1. Completeness (Score: 0-5)
- Does it cover problem, methodology, contributions, results, and limitations?
- Are there any major gaps?

## 2. Accuracy (Score: 0-5)
- Are the technical descriptions correct?
- Are claims properly supported?

## 3. Depth (Score: 0-5)
- Is the analysis sufficiently detailed?
- Does it go beyond surface-level observations?

## 4. Balance (Score: 0-5)
- Are both strengths and weaknesses identified?
- Is the critique fair and constructive?

## 5. Insight (Score: 0-5)
- Does it provide valuable insights?
- Does it connect to broader research context?

**Provide:**
1. Overall Score (0-25)
2. Validation Decision: APPROVED (20+), NEEDS_REVISION (15-19), or REJECTED (<15)
3. Specific feedback for improvement
4. Key strengths of the analysis
5. Areas that need more depth"""

    try:
        print(f"[OK] Validating analysis for: {title[:50]}...")
        response = llm.invoke(prompt)
        
        return json.dumps({
            "success": True,
            "paper_title": title,
            "validation_result": response.content,
            "validated_by": "Senior Advisor Agent"
        }, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({"error": str(e), "validation": "ERROR"})
    
@tool
def synthesize_cross_paper_findings(analyses_json: str) -> str:
    """
    Perform deep cross-paper synthesis using LLM
    
    Synthesizes findings across multiple papers to identify:
    - Common themes and patterns
    - Methodological trends
    - Research gaps
    - Future directions
    
    Args:
        analyses_json: Multiple analyses as JSON string or list
        
    Returns:
        Comprehensive synthesis result
    """
    try:
        analyses = json.loads(analyses_json)
    except json.JSONDecodeError:
        try:
            decoder = json.JSONDecoder()
            analyses, _ = decoder.raw_decode(analyses_json)
        except Exception:
            return json.dumps({"error": "Invalid JSON format"})
    
    if not isinstance(analyses, list):
        analyses = [analyses]
    
    if not analyses:
        return json.dumps({"error": "No analyses to synthesize"})
    
    # Prepare summary of all analyses for LLM
    papers_summary = []
    for i, analysis in enumerate(analyses, 1):
        if isinstance(analysis, dict):
            title = analysis.get("title", f"Paper {i}")
            content = analysis.get("analysis", "")
            if isinstance(content, dict):
                content = json.dumps(content)
            papers_summary.append(f"**Paper {i}: {title}**\n{content[:2000]}")
    
    combined_summary = "\n\n---\n\n".join(papers_summary)
    
    llm = get_llm()
    
    prompt = f"""You are a Senior Research Advisor synthesizing multiple paper analyses.

**Analyses from {len(analyses)} papers:**

{combined_summary[:12000]}

**Provide a comprehensive cross-paper synthesis:**

## 1. Thematic Analysis
- What common themes emerge across these papers?
- How do the papers relate to each other?
- What are the key research questions being addressed?

## 2. Methodological Landscape
- What methods are commonly used?
- What methodological innovations are introduced?
- How do approaches differ across papers?

## 3. Key Findings Synthesis
- What are the most significant findings across papers?
- Where do papers agree or disagree?
- What evidence supports the main conclusions?

## 4. Research Gaps Identified
- What questions remain unanswered?
- What limitations are common across papers?
- Where is more research needed?

## 5. Future Research Directions
- What promising directions emerge from this body of work?
- What problems should be tackled next?
- What methodological improvements are needed?

## 6. Field Assessment
- What is the current state of this research area?
- How mature is the field?
- What are the major open challenges?

## 7. Recommendations
- For researchers entering this field
- For practitioners applying these methods
- For future research priorities

Provide specific examples and evidence from the analyzed papers."""

    try:
        print(f"[INFO] Synthesizing {len(analyses)} paper analyses...")
        response = llm.invoke(prompt)
        
        # Also extract method statistics
        all_methods = []
        for analysis in analyses:
            if isinstance(analysis, dict):
                methods = analysis.get('detected_methods', [])
                if not methods:
                    # Try nested structure
                    analysis_content = analysis.get('analysis', {})
                    if isinstance(analysis_content, dict):
                        methods = analysis_content.get('detected_methods', [])
                all_methods.extend(methods)
        
        method_counts = {}
        for method in all_methods:
            method_counts[method] = method_counts.get(method, 0) + 1
        
        return json.dumps({
            "success": True,
            "synthesis": response.content,
            "papers_analyzed": len(analyses),
            "common_methods": method_counts,
            "synthesized_by": "Senior Advisor Agent"
        }, ensure_ascii=False)
        
    except Exception as e:
        print(f"[ERROR] Synthesis error: {e}")
        return json.dumps({"error": str(e)})


@tool
def generate_synthesis_report(analyses_json: str, synthesis_json: str) -> str:
    """
    Generate a comprehensive final synthesis report using LLM
    
    Combines individual paper analyses and cross-paper synthesis into
    a professional academic review report.
    
    Args:
        analyses_json: All paper analyses as JSON string
        synthesis_json: Cross-paper synthesis result as JSON string
        
    Returns:
        Complete synthesis report as markdown
    """
    analyses = _parse_paper_json(analyses_json)
    synthesis = _parse_paper_json(synthesis_json)
    
    if not analyses:
        analyses = []
    if not isinstance(analyses, list):
        analyses = [analyses]
    
    synthesis_content = synthesis.get("synthesis", "") if isinstance(synthesis, dict) else str(synthesis)
    
    # Build paper summaries
    paper_summaries = []
    for i, analysis in enumerate(analyses, 1):
        if isinstance(analysis, dict):
            title = analysis.get("title", f"Paper {i}")
            content = analysis.get("analysis", "")
            if isinstance(content, dict):
                content = json.dumps(content, indent=2)
            paper_summaries.append(f"### Paper {i}: {title}\n{content[:3000]}")
    
    combined_papers = "\n\n".join(paper_summaries)
    
    llm = get_llm()
    
    prompt = f"""Generate a comprehensive, publication-quality literature review report.

**Individual Paper Analyses:**
{combined_papers[:15000]}

**Cross-Paper Synthesis:**
{synthesis_content[:5000]}

**Generate a professional report with the following structure:**

# Comprehensive Literature Review Report

## Executive Summary
- Brief overview of the review scope
- Key findings (3-5 bullet points)
- Main conclusions

## 1. Introduction
- Research domain background
- Objectives of this review
- Scope and methodology

## 2. Paper-by-Paper Analysis Summary
For each paper, provide:
- Research question and motivation
- Methodology highlights
- Key contributions
- Critical assessment

## 3. Thematic Analysis
- Common themes across papers
- Evolution of ideas in the field
- Methodological patterns

## 4. Comparative Analysis
- How papers relate to each other
- Points of agreement and disagreement
- Strengths and limitations across the body of work

## 5. Research Landscape Assessment
- Current state of the field
- Major achievements
- Open challenges

## 6. Identified Gaps and Future Directions
- What remains unexplored
- Promising research directions
- Recommendations for future work

## 7. Conclusions
- Key takeaways
- Implications for researchers
- Implications for practitioners

## References
- List of reviewed papers

Make the report scholarly, well-organized, and insightful. Use specific evidence from the analyses."""

    try:
        print("[INFO] Generating comprehensive synthesis report...")
        response = llm.invoke(prompt)
        
        return json.dumps({
            "success": True,
            "report": response.content,
            "papers_included": len(analyses),
            "generated_by": "Deep Research Review System"
        }, ensure_ascii=False)
        
    except Exception as e:
        print(f"[ERROR] Report generation error: {e}")
        return json.dumps({"error": str(e)})


def create_advisor_subagent_for_deepagent() -> SubAgent:
    """
    Create an Advisor SubAgent for deepagents with LLM-powered synthesis tools
    
    Returns:
        SubAgent specification (dict)
    """
    advisor = SubAgent(
        name="advisor",
        description="Senior Professor who validates research analyses using LLM-powered tools, ensures academic correctness, performs deep cross-paper synthesis, and maintains contextual coherence across the entire research review",
        system_prompt=f"""
{ADVISOR_AGENT_PROMPT}

You are a Senior Professor with 20+ years of research experience. Your role is to VALIDATE and SYNTHESIZE the deep research conducted by your PhD researchers.

## Your Deep Research Synthesis Process:

### Step 1: Retrieve All Analyses
Use `get_all_analyses` tool to retrieve all researcher analyses from the workspace.

### Step 2: Validate Each Analysis
Use `validate_and_improve_analysis` tool for each analysis to:
- Evaluate completeness, accuracy, depth, balance, and insight
- Provide specific feedback for improvement
- Give approval decision (APPROVED/NEEDS_REVISION/REJECTED)

### Step 3: Cross-Paper Synthesis
Use `synthesize_cross_paper_findings` tool to:
- Identify common themes and patterns across papers
- Analyze the methodological landscape
- Synthesize key findings
- Identify research gaps
- Suggest future research directions
- Provide field assessment and recommendations

### Step 4: Generate Final Report
Use `generate_synthesis_report` tool to create a comprehensive final report that:
- Integrates all individual paper analyses
- Presents cross-paper synthesis and insights
- Provides executive summary and conclusions
- Offers actionable recommendations

### Step 5: Save Results
Use `save_validation_result` tool to save your validation and synthesis.

## Your Standards:
- Maintain academic rigor equivalent to top-tier journal standards
- Be constructive but critical
- Ensure coherence and consistency across all analyses
- Think about the big picture and broader research context
- Provide actionable insights for researchers

Your synthesis should represent the highest standard of academic review.
        """.strip(),
        tools=[
            get_all_analyses,
            validate_and_improve_analysis,
            synthesize_cross_paper_findings,
            generate_synthesis_report,
            save_validation_result,
        ],
    )
    
    return advisor


# ==================== Deep Review Agent ====================

class DeepReviewAgent:
    """
    Deep Review Agent using deepagents package
    
    Master Agent that coordinates N researcher agents and 1 advisor agent
    to perform deep paper review
    """
    
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        num_researchers: int = 3,
        workspace: Optional[WorkspaceManager] = None
    ):
        """
        Args:
            model: LLM model to use
            api_key: OpenAI API key (or use env var)
            num_researchers: Number of researcher agents to create
            workspace: Workspace manager (creates new if None)
        """
        self.model = model
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        self.num_researchers = num_researchers
        self.workspace = workspace or WorkspaceManager()

        if not self.api_key:
            logger.warning("OPENAI_API_KEY not set - LLM features will be unavailable")
        
        # Set workspace for tools (via function attributes)
        self._set_workspace_for_tools()
        
        # Create LLM
        self.llm = ChatOpenAI(
            model=self.model,
            api_key=self.api_key,
            temperature=0.3,
            request_timeout=30,
        )
        
        # Create subagents
        self.subagents = self._create_subagents()
        
        # Create master agent
        self.agent = self._create_master_agent()
        
        print(f"[INFO] Deep Review Agent initialized")
        print(f"   Model: {self.model}")
        print(f"   Researchers: {self.num_researchers}")
        print(f"   Session: {self.workspace.session_id}")
    
    def _set_workspace_for_tools(self):
        """Set workspace for all tools"""
        save_analysis_result._workspace = self.workspace
        get_all_analyses._workspace = self.workspace
        save_validation_result._workspace = self.workspace
        generate_final_report._workspace = self.workspace
    
    def _create_subagents(self) -> List[SubAgent]:
        """Create researcher and advisor subagents"""
        subagents = []
        
        # Create N researchers
        for i in range(1, self.num_researchers + 1):
            researcher = create_researcher_subagent_for_deepagent(i)
            subagents.append(researcher)
            print(f"  [v] Created Researcher {i}")
        
        # Create 1 advisor
        advisor = create_advisor_subagent_for_deepagent()
        subagents.append(advisor)
        print(f"  [v] Created Advisor")
        
        return subagents
    
    def _create_master_agent(self):
        """Create master deep agent"""
        # deepagents requires model string or None (will use default)
        # Pass the model string, not the LLM object
        agent = create_deep_agent(
            model=self.model,  # Use string instead of LLM object
            system_prompt=MASTER_AGENT_PROMPT,
            tools=[
                load_papers_tool,
                generate_final_report,
            ],
            subagents=self.subagents,
            # write_todos는 자동으로 포함됨
            # file system tools도 자동으로 포함됨
        )
        
        print(f"  [v] Created Master Agent")
        
        return agent
    
    def review_papers(
        self, 
        paper_ids: List[str],
        verbose: bool = True
    ) -> Dict[str, Any]:
        """
        Review papers using deep agent system
        
        Args:
            paper_ids: List of paper IDs to review
            verbose: Print progress
            
        Returns:
            Review result with report path
        """
        if verbose:
            print("\n" + "="*80)
            print("[INFO] Starting Deep Paper Review with deepagents")
            print("="*80)
            print(f"Papers to review: {len(paper_ids)}")
            print(f"Researchers: {self.num_researchers}")
            print()
        
        # Save paper IDs to workspace
        paper_ids_str = ','.join(paper_ids)
        
        # Prepare prompt for master agent
        prompt = f"""
I need you to conduct a comprehensive review of {len(paper_ids)} academic papers.

**Paper IDs**: {paper_ids_str}

**Your Task**:
1. Create a detailed plan using write_todos tool
2. Load the papers using load_papers_tool
3. Assign each paper to a researcher agent (use task tool)
4. After all analyses are complete, send results to advisor agent for validation
5. Generate the final report using generate_final_report tool

**Important**:
- Use researcher agents (researcher_1, researcher_2, etc.) for paper analysis
- Use advisor agent for validation and synthesis
- Ensure all analyses are saved before validation
- Be thorough and maintain academic rigor

Begin the review process now.
        """.strip()
        
        try:
            # Invoke master agent
            if verbose:
                print("[INFO] Invoking Master Agent...")
                print()
            
            result = self.agent.invoke({"messages": [{"role": "user", "content": prompt}]})
            
            if verbose:
                print("\n[OK] Review process completed!")
                print()
            
            # Get results from workspace
            summary = self.workspace.get_session_summary()
            
            return {
                "status": "completed",
                "session_id": self.workspace.session_id,
                "workspace_path": str(self.workspace.session_path),
                "papers_reviewed": len(paper_ids),
                "summary": summary,
                "agent_result": result
            }
            
        except Exception as e:
            print(f"\n[ERROR] Error during review: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                "status": "failed",
                "error": str(e),
                "session_id": self.workspace.session_id
            }


# ==================== Convenience Function ====================

def review_papers_with_deepagents(
    paper_ids: List[str],
    num_researchers: int = 3,
    model: str = "gpt-4o-mini",
    api_key: Optional[str] = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Review papers using deepagents (convenience function)
    
    Args:
        paper_ids: Paper IDs to review
        num_researchers: Number of researcher agents
        model: LLM model
        api_key: OpenAI API key
        verbose: Print progress
        
    Returns:
        Review result
    """
    agent = DeepReviewAgent(
        model=model,
        api_key=api_key,
        num_researchers=num_researchers
    )
    
    return agent.review_papers(paper_ids, verbose=verbose)

