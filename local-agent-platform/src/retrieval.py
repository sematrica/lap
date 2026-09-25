"""Ephemeral URL provenance for one task, never a browsing session or memory."""

import re

from .errors import AgentError
from .tools.search_tool import navigation_only
from .tools.web_tool import normalize_url

MAX_SEARCH_CALLS = 3


class RetrievalState:
    def __init__(self):
        self.search_calls = 0
        self.searched = False
        self.search_urls = set()
        self.search_results = []
        self.sources = {}
        self.read_sources = {}

    def before_search(self):
        if self.search_calls >= MAX_SEARCH_CALLS:
            raise AgentError("search_limit", "At most three search attempts are allowed per task. Stopped further searches.")
        self.search_calls += 1

    def record(self, name, result):
        if name == "search_web" and result.get("status") == "searched":
            self.searched = True
            for item in result["results"]:
                url = item["url"]
                normalized = normalize_url(url)
                self.search_urls.add(normalized)
                self.sources[normalized] = url
                self.search_results.append(item)
        elif name in {"read_webpage", "nasa_neo_feed"} and result.get("status") == "read":
            url = result.get("source_url")
            if url:
                normalized = normalize_url(url)
                self.sources[normalized] = url
                if name == "read_webpage":
                    self.read_sources[normalized] = url

    def needs_page(self, task, enabled):
        return (bool(self.search_urls) and "read_webpage" in enabled
                and not navigation_only(task) and not self.read_sources)

    def finish(self, answer, task, enabled):
        if self.searched and not self.search_urls and not self.read_sources:
            return "Search returned no usable results. I could not verify the requested information."
        if self.searched and "read_webpage" not in enabled and not navigation_only(task):
            # Snippets alone cannot justify a detailed factual answer when this
            # agent lacks the page-reading capability. Return discovery only.
            links = list(dict.fromkeys(item["url"] for item in self.search_results))
            return ("Search discovery only: read_webpage is disabled, so I could not verify page contents.\n"
                    + "\n".join(links))
        if not self.searched and not self.read_sources:
            return answer
        # Only actual top-level result URLs (or final read URLs) can be citations.
        # URLs inside snippets/page text do not become sources or fetch permission.
        found = set()
        for candidate in re.findall(r"(?:[A-Za-z][A-Za-z0-9+.-]*://|www\.)[^\s<>\"']+", answer):
            candidate = candidate.rstrip(".,;!?)`]*")
            try:
                url = normalize_url(candidate)
            except AgentError:
                raise AgentError("unverified_source_url", "The model supplied an unverified source URL. No sourced answer was returned.") from None
            if url not in self.sources:
                raise AgentError("unverified_source_url", "The model supplied a URL absent from retrieved sources. No sourced answer was returned.")
            found.add(url)
        # Relative Markdown links cannot serve as verified source URLs either.
        targets = re.findall(r"\]\(([^\s)]+)", answer)
        targets += re.findall(r"(?m)^\s*\[[^\]]+\]:\s*(\S+)", answer)
        for target in targets:
            if not target.startswith(("https://", "http://")):
                raise AgentError("unverified_source_url", "Citations must use full URLs from retrieved sources.")
        preferred = self.read_sources or self.sources
        if preferred and not found.intersection(preferred):
            answer += "\n\nSources:\n" + "\n".join(list(preferred.values())[:3])
        return answer
