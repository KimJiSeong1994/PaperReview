"""
Deep Agent System for Paper Review
실제 deepagents 패키지를 활용한 논문 리뷰 시스템
"""

from .workspace_manager import WorkspaceManager
from .deep_review_agent import DeepReviewAgent, review_papers_with_deepagents

# Legacy support (직접 구현 버전)
from .review_orchestrator import ReviewOrchestrator, review_selected_papers
from .subagents import create_researcher_subagent, create_advisor_subagent

__all__ = [
    # New: deepagents 패키지 사용
    'DeepReviewAgent',
    'review_papers_with_deepagents',
    
    # Core
    'WorkspaceManager',
    
    # Legacy: 직접 구현 버전 (LLM 없이 작동)
    'ReviewOrchestrator',
    'review_selected_papers',
    'create_researcher_subagent',
    'create_advisor_subagent',
]

__version__ = '0.2.0'

