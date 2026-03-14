"""
FastAPI Router modules for Paper Review Agent API.

Each module groups related endpoints into an APIRouter.
"""

from .auth import router as auth_router
from .search import router as search_router
from .papers import router as papers_router
from .reviews import router as reviews_router
from .bookmarks import router as bookmarks_router
from .paper_reviews import router as paper_reviews_router
from .chat import router as chat_router
from .lightrag import router as lightrag_router
from .admin import router as admin_router
from .exploration import router as exploration_router
from .share import router as share_router
from .curriculum import router as curriculum_router
from .pdf_proxy import router as pdf_proxy_router

__all__ = [
    "auth_router",
    "search_router",
    "papers_router",
    "reviews_router",
    "bookmarks_router",
    "paper_reviews_router",
    "chat_router",
    "lightrag_router",
    "admin_router",
    "exploration_router",
    "share_router",
    "curriculum_router",
    "pdf_proxy_router",
]
