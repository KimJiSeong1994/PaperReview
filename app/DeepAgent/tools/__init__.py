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

