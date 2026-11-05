"""Public web search adapters."""

from life_agent.tools.search.web import (
	WebSearchError,
	normalize_search_results,
	search_web,
)

__all__ = ["WebSearchError", "normalize_search_results", "search_web"]
