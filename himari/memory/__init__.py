"""Long-term local memory: categories, dedupe, bounded retrieval, summaries."""

from .extraction import extract_candidate
from .manager import MemoryManager, normalize
from .models import CATEGORIES, Memory
from .retrieval import retrieve
from .summarizer import summarize_session

__all__ = [
    "CATEGORIES",
    "Memory",
    "MemoryManager",
    "normalize",
    "extract_candidate",
    "retrieve",
    "summarize_session",
]