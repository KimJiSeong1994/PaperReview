"""
Deep Agent System for Paper Review
실제 deepagents 패키지를 활용한 논문 리뷰 시스템

Note: langchain 호환성 문제로 lazy import 사용
"""

# Core - 항상 안전하게 import
from .workspace_manager import WorkspaceManager

# Lazy imports to avoid langchain compatibility issues
def __getattr__(name):
    """Lazy import to avoid langchain_core compatibility issues"""
    if name == 'DeepReviewAgent':
        from .deep_review_agent import DeepReviewAgent
        return DeepReviewAgent
    elif name == 'review_papers_with_deepagents':
        from .deep_review_agent import review_papers_with_deepagents
        return review_papers_with_deepagents
    elif name == 'ReviewOrchestrator':
        from .review_orchestrator import ReviewOrchestrator
        return ReviewOrchestrator
    elif name == 'review_selected_papers':
        from .review_orchestrator import review_selected_papers
        return review_selected_papers
    elif name == 'create_researcher_subagent':
        from .subagents import create_researcher_subagent
        return create_researcher_subagent
    elif name == 'create_advisor_subagent':
        from .subagents import create_advisor_subagent
        return create_advisor_subagent
    raise AttributeError(f"module 'app.DeepAgent' has no attribute '{name}'")

__all__ = [
    # New: deepagents 패키지 사용 (lazy import)
    'DeepReviewAgent',
    'review_papers_with_deepagents',
    
    # Core
    'WorkspaceManager',
    
    # Legacy: 직접 구현 버전 (lazy import)
    'ReviewOrchestrator',
    'review_selected_papers',
    'create_researcher_subagent',
    'create_advisor_subagent',
]

__version__ = '0.2.0'

