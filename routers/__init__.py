"""
FastAPI Router modules for Paper Review Agent API.

Each module groups related endpoints into an APIRouter.
"""

from .search import router as search_router
from .papers import router as papers_router
from .reviews import router as reviews_router
from .bookmarks import router as bookmarks_router
from .chat import router as chat_router
from .lightrag import router as lightrag_router

__all__ = [
    "search_router",
    "papers_router",
    "reviews_router",
    "bookmarks_router",
    "chat_router",
    "lightrag_router",
]
