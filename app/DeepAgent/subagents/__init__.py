"""
Deep Agent SubAgents
"""
from .researcher_agent import create_researcher_subagent
from .advisor_agent import create_advisor_subagent

__all__ = [
    'create_researcher_subagent',
    'create_advisor_subagent',
]

