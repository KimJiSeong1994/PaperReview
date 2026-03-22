"""
Deep Agent Tools
"""
from .paper_loader import load_papers_from_ids, get_paper_content
from .report_generator import generate_markdown_report, generate_html_report

__all__ = [
    'load_papers_from_ids',
    'get_paper_content',
    'generate_markdown_report',
    'generate_html_report',
]

# fact_verification은 dotenv 의존성이 있어 선택적 임포트
try:
    from .fact_verification import (
        ClaimExtractor,
        EvidenceLinker,
        CrossRefValidator,
        Claim,
        Evidence,
        ClaimEvidence,
        ClaimType,
        MatchType,
        VerificationStatus,
        VerificationResult,
        ClaimRelation,
        ConsensusLevel,
        CrossReference,
        ConsensusReport,
    )
    __all__ += [
        'ClaimExtractor', 'EvidenceLinker', 'CrossRefValidator',
        'Claim', 'Evidence', 'ClaimEvidence', 'ClaimType', 'MatchType',
        'VerificationStatus', 'VerificationResult', 'ClaimRelation',
        'ConsensusLevel', 'CrossReference', 'ConsensusReport',
    ]
except ImportError:
    pass

