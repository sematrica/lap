"""Replaceable discovery backend. It never retrieves the pages in its results."""

import json
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from .errors import AgentError

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
MAX_PROVIDER_BYTES = 256 * 1024
RESULT_LIMIT = 5


class SearchProvider(Protocol):
    def search(self, query: str) -> list[dict[str, str]]:
        """Return title/url/snippet dictionaries, or a sanitized AgentError."""
        ...


@dataclass
class BraveSearchProvider:
    api_key: str = field(default="", repr=False)
    timeout: float = 10
    transport: object = field(default=None, repr=False)

    def search(self, query):
        if not self.api_key or len(self.api_key) > 1024 or any(
                ord(c) < 33 or ord(c) > 126 for c in self.api_key):
            raise AgentError("search_configuration_error", "Set BRAVE_SEARCH_API_KEY in .env to enable web search.")
        try:
            # The model controls only q. No URL, credentials, headers, or provider
            # options come from a tool call. A fresh client never reuses cookies.
            with httpx.Client(timeout=self.timeout, trust_env=False, follow_redirects=False,
                              transport=self.transport) as client:
                deadline = time.monotonic() + self.timeout
                with client.stream("GET", ENDPOINT,
                        params={"q": query, "count": RESULT_LIMIT, "result_filter": "web",
                                "text_decorations": "false", "extra_snippets": "false"},
                        headers={"X-Subscription-Token": self.api_key,
                                 "Accept": "application/json", "Accept-Encoding": "identity"}) as response:
                    if response.status_code in (401, 403, 422):
                        # Brave returns 422 SUBSCRIPTION_TOKEN_INVALID for a bad/unsubscribed key,
                        # not a malformed request: every other request parameter here is fixed.
                        raise AgentError("search_authentication_error", "Search provider rejected the API key or its plan permissions.")
                    if response.status_code == 429:
                        raise AgentError("search_rate_limited", "Search provider rate limit reached. Try again later.")
                    if response.status_code != 200:
                        raise AgentError("search_provider_error", "Search provider is unavailable or rejected the request.")
                    if (response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
                            or response.headers.get("content-encoding", "identity").lower() != "identity"):
                        raise AgentError("search_response_error", "Search provider returned an unsupported response format.")
                    length = response.headers.get("content-length")
                    if length is not None and (int(length) < 0 or int(length) > MAX_PROVIDER_BYTES):
                        raise AgentError("search_response_too_large", "Search provider response exceeded the size limit.")
                    body = bytearray()
                    for chunk in response.iter_raw():
                        if time.monotonic() > deadline:
                            raise AgentError("search_timeout", "Search provider timed out.")
                        if len(body) + len(chunk) > MAX_PROVIDER_BYTES:
                            raise AgentError("search_response_too_large", "Search provider response exceeded the size limit.")
                        body.extend(chunk)
                    data = json.loads(body)
            if not isinstance(data, dict) or data.get("type") != "search" or "error" in data:
                raise ValueError
            web = data.get("web")
            if web is None:  # Documented optional web section on an empty search.
                return []
            if not isinstance(web, dict) or not isinstance(web.get("results"), list):
                raise ValueError
            results = []
            for item in web["results"][:RESULT_LIMIT]:
                if not isinstance(item, dict):
                    raise ValueError
                result = {"title": item.get("title"), "url": item.get("url"),
                          "snippet": item.get("description", "")}
                if any(not isinstance(value, str) or self.api_key in value for value in result.values()):
                    raise ValueError
                results.append(result)
            return results
        except AgentError:
            raise
        except httpx.TimeoutException:
            raise AgentError("search_timeout", "Search provider timed out.") from None
        except httpx.RequestError:
            raise AgentError("search_provider_error", "Could not securely connect to the search provider.") from None
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise AgentError("search_response_error", "Search provider returned an invalid response.") from None


def build_search_provider(settings):
    if settings.provider != "brave":
        raise AgentError("search_configuration_error", "SEARCH_PROVIDER must be brave.")
    return BraveSearchProvider(settings.api_key, settings.timeout)
