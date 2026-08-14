"""
Agent instances: SearchAgent, QueryAnalyzer.
"""

import logging
from typing import Optional

from .config import api_key

logger = logging.getLogger(__name__)

# ── Agent instances ────────────────────────────────────────────────────
from app.SearchAgent.search_agent import SearchAgent
from app.QueryAgent.query_analyzer import QueryAnalyzer

search_agent = SearchAgent(openai_api_key=api_key)

query_analyzer: Optional[QueryAnalyzer] = None

if api_key:
    try:
        query_analyzer = QueryAnalyzer(api_key=api_key)
        logger.info("Query analyzer initialized")
    except Exception as e:
        logger.warning("Could not initialize query analyzer: %s", e)
        query_analyzer = None
else:
    logger.warning("No OpenAI API key - query analysis disabled")
