"""
Deep Review Agent
실제 deepagents 패키지를 사용한 Master Agent 구현
"""
import os
import sys
import json
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
        print(f"⚠️ Error parsing paper_ids: {e}")
        # Fallback: treat as single ID
        ids = [paper_ids.strip()]
    
    # Ensure all IDs are strings
    ids = [str(pid) for pid in ids if pid]
    
    print(f"📥 Loading {len(ids)} papers: {ids}")
    
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
        
        return f"✓ Analysis saved to {path}"
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
        
        return f"✓ Validation saved to {path}"
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
        
        return f"✓ Report saved to {path}"
    except Exception as e:
        return f"Error generating report: {e}"


# ==================== Researcher Tools (Global) ====================

@tool
def analyze_paper_structure_tool(paper_json: str) -> str:
        """
        Analyze paper structure
        
        Args:
            paper_json: Paper data as JSON string
            
        Returns:
            Structure analysis
        """
        try:
            paper_data = json.loads(paper_json)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON parsing failed in analyze_paper_structure: {e}")
            try:
                decoder = json.JSONDecoder()
                paper_data, _ = decoder.raw_decode(paper_json)
                print(f"✓ Extracted partial JSON")
            except Exception as e2:
                print(f"❌ Could not extract valid JSON: {e2}")
                return json.dumps({"error": "Invalid JSON format"})
        
        return json.dumps({
            "has_abstract": "abstract" in paper_data and len(paper_data.get("abstract", "")) > 0,
            "has_full_text": "full_text" in paper_data and len(paper_data.get("full_text", "")) > 0,
            "title": paper_data.get("title", ""),
            "authors": paper_data.get("authors", []),
            "year": paper_data.get("year"),
        })
    
@tool
def identify_methodology_tool(paper_json: str) -> str:
        """
        Identify methodology used in paper
        
        Args:
            paper_json: Paper data as JSON string
            
        Returns:
            Methodology analysis
        """
        try:
            paper_data = json.loads(paper_json)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON parsing failed in identify_methodology: {e}")
            try:
                decoder = json.JSONDecoder()
                paper_data, _ = decoder.raw_decode(paper_json)
                print(f"✓ Extracted partial JSON")
            except Exception as e2:
                print(f"❌ Could not extract valid JSON: {e2}")
                return json.dumps({"detected_methods": [], "error": "Invalid JSON format"})
        
        text = (paper_data.get("abstract", "") + " " + paper_data.get("full_text", "")).lower()
        
        methodologies = {
            "deep_learning": any(kw in text for kw in ["deep learning", "neural network", "cnn", "rnn", "transformer"]),
            "machine_learning": any(kw in text for kw in ["machine learning", "classification", "regression"]),
            "nlp": any(kw in text for kw in ["natural language", "nlp", "language model"]),
            "graph": any(kw in text for kw in ["graph neural", "graph convolution", "node", "edge"]),
        }
        
        detected = [k for k, v in methodologies.items() if v]
        
        return json.dumps({"detected_methods": detected})


# ==================== SubAgent Definitions ====================

def create_researcher_subagent_for_deepagent(researcher_id: int) -> SubAgent:
    """
    Create a Researcher SubAgent for deepagents
    
    Args:
        researcher_id: Researcher number
        
    Returns:
        SubAgent specification (dict)
    """
    researcher = SubAgent(
        name=f"researcher_{researcher_id}",
        description=f"Expert researcher who analyzes academic papers deeply, focusing on structure, methodology, and contributions",
        system_prompt=f"""
{RESEARCHER_AGENT_PROMPT}

You are Researcher #{researcher_id}. Your specific role:
- Analyze ONE paper deeply and thoroughly
- Use analyze_paper_structure_tool and identify_methodology_tool
- Save your analysis using save_analysis_result tool
- Be objective and evidence-based
        """.strip(),
        tools=[
            analyze_paper_structure_tool,
            identify_methodology_tool,
            save_analysis_result,
        ],
    )
    
    return researcher


# ==================== Advisor Tools (Global) ====================

@tool
def validate_completeness_tool(analysis_json: str) -> str:
        """
        Validate analysis completeness
        
        Args:
            analysis_json: Analysis data as JSON string
            
        Returns:
            Validation result
        """
        try:
            analysis = json.loads(analysis_json)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON parsing failed in validate_completeness: {e}")
            # Try to extract the first valid JSON object
            try:
                decoder = json.JSONDecoder()
                analysis, idx = decoder.raw_decode(analysis_json)
                print(f"✓ Extracted partial JSON")
            except Exception as e2:
                print(f"❌ Could not extract valid JSON: {e2}")
                return json.dumps({
                    "error": "Invalid JSON format",
                    "completeness_score": 0,
                    "is_complete": False,
                    "validation": "ERROR"
                })
        
        required = ["structure_analysis", "methodology"]
        completeness = {
            section: section in analysis.get('analysis', {})
            for section in required
        }
        
        score = sum(completeness.values()) / len(completeness) if completeness else 0
        
        return json.dumps({
            "completeness_score": score,
            "is_complete": score >= 0.75,
            "validation": "APPROVED" if score >= 0.75 else "NEEDS_REVISION"
        })
    
@tool
def synthesize_cross_paper_findings_tool(analyses_json: str) -> str:
        """
        Synthesize findings across multiple papers
        
        Args:
            analyses_json: Multiple analyses as JSON string or list
            
        Returns:
            Synthesis result
        """
        try:
            # Try to parse as JSON
            analyses = json.loads(analyses_json)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON parsing failed: {e}")
            # Try to extract the first valid JSON object
            try:
                # Find the first complete JSON object/array
                decoder = json.JSONDecoder()
                analyses, idx = decoder.raw_decode(analyses_json)
                print(f"✓ Extracted partial JSON (used {idx} chars out of {len(analyses_json)})")
            except Exception as e2:
                print(f"❌ Could not extract valid JSON: {e2}")
                return json.dumps({
                    "error": "Invalid JSON format",
                    "details": str(e)
                })
        
        # Ensure analyses is a list
        if not isinstance(analyses, list):
            analyses = [analyses]
        
        # Extract all methods
        all_methods = []
        for analysis in analyses:
            if isinstance(analysis, dict):
                methods = analysis.get('analysis', {}).get('methodology', {}).get('detected_methods', [])
                all_methods.extend(methods)
        
        # Count frequencies
        method_counts = {}
        for method in all_methods:
            method_counts[method] = method_counts.get(method, 0) + 1
        
        common_themes = {m: c for m, c in method_counts.items() if c >= 2}
        
        return json.dumps({
            "total_papers": len(analyses),
            "common_themes": common_themes,
            "unique_methods": len(method_counts)
        })


def create_advisor_subagent_for_deepagent() -> SubAgent:
    """
    Create an Advisor SubAgent for deepagents
    
    Returns:
        SubAgent specification (dict)
    """
    advisor = SubAgent(
        name="advisor",
        description="Senior advisor who validates research analyses, ensures academic correctness, and synthesizes cross-paper findings",
        system_prompt=f"""
{ADVISOR_AGENT_PROMPT}

Your specific responsibilities:
1. Get all analyses using get_all_analyses tool
2. Validate each analysis using validate_completeness_tool
3. Synthesize findings using synthesize_cross_paper_findings_tool
4. Save validation result using save_validation_result
5. Ensure academic rigor and contextual coherence
        """.strip(),
        tools=[
            get_all_analyses,
            validate_completeness_tool,
            synthesize_cross_paper_findings_tool,
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
        
        # Set workspace for tools (via function attributes)
        self._set_workspace_for_tools()
        
        # Create LLM
        self.llm = ChatOpenAI(
            model=self.model,
            api_key=self.api_key,
            temperature=0.3
        )
        
        # Create subagents
        self.subagents = self._create_subagents()
        
        # Create master agent
        self.agent = self._create_master_agent()
        
        print(f"🤖 Deep Review Agent initialized")
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
            print(f"  ✓ Created Researcher {i}")
        
        # Create 1 advisor
        advisor = create_advisor_subagent_for_deepagent()
        subagents.append(advisor)
        print(f"  ✓ Created Advisor")
        
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
        
        print(f"  ✓ Created Master Agent")
        
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
            print("🚀 Starting Deep Paper Review with deepagents")
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
                print("🤖 Invoking Master Agent...")
                print()
            
            result = self.agent.invoke({"messages": [{"role": "user", "content": prompt}]})
            
            if verbose:
                print("\n✅ Review process completed!")
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
            print(f"\n❌ Error during review: {e}")
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

