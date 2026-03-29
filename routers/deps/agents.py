"""
Agent instances: SearchAgent, QueryAnalyzer, RelevanceFilter.
"""

import logging
from typing import Optional

from .config import api_key

logger = logging.getLogger(__name__)

# ── Agent instances ────────────────────────────────────────────────────
from app.SearchAgent.search_agent import SearchAgent
from app.QueryAgent.query_analyzer import QueryAnalyzer
from app.QueryAgent.relevance_filter import RelevanceFilter

search_agent = SearchAgent(openai_api_key=api_key)

query_analyzer: Optional[QueryAnalyzer] = None
relevance_filter: Optional[RelevanceFilter] = None

if api_key:
    try:
        try:
            query_analyzer = QueryAnalyzer(api_key=api_key)
            logger.info("Query analyzer initialized")
        except Exception as e:
            logger.warning("Could not initialize query analyzer: %s", e)
            query_analyzer = None

        try:
            relevance_filter = RelevanceFilter(api_key=api_key)
            logger.info("Relevance filter initialized")
        except Exception as e:
            logger.warning("Could not initialize relevance filter: %s", e)
            relevance_filter = None
    except Exception as e:
        logger.warning("Could not initialize query analyzer/filter: %s", e)
else:
    logger.warning("No OpenAI API key - query analysis and relevance filtering disabled")
