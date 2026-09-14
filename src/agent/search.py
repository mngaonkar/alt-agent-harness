"""Tavily web search client.

Tavily is used rather than a raw HTTP fetch because it returns short extracted
snippets instead of full pages.
"""

import json
import urllib.error
import urllib.request


_ENDPOINT = "https://api.tavily.com/search"


class SearchError(Exception):
    pass


class TavilyClient:
    def __init__(self, cfg):
        self.api_key = cfg.get("tavily_api_key", "") or ""
        self.endpoint = cfg.get("tavily_endpoint", _ENDPOINT)
        self.default_results = int(cfg.get("tavily_max_results", 5))
        self.depth = cfg.get("tavily_search_depth", "basic")
        self.timeout = int(cfg.get("request_timeout", 45))

    @property
    def enabled(self):
        return bool(self.api_key)

    def search(self, query, max_results=None, topic="general", days=None,
               include_answer=True, include_domains=None):
        if not self.api_key:
            raise SearchError(
                "no tavily_api_key configured; set it in config.json")
        if not query:
            raise SearchError("query is empty")

        payload = {
            "query": query,
            "max_results": max(1, min(int(max_results or self.default_results), 10)),
            "search_depth": self.depth,
            "include_answer": include_answer,
            "include_raw_content": False,
            "include_images": False,
            "topic": topic,
        }
        if topic == "news" and days:
            payload["days"] = int(days)
        if include_domains:
            payload["include_domains"] = include_domains

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = resp.status
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
            if status == 401:
                raise SearchError("Tavily rejected the API key (HTTP 401)")
            if status in (429, 432):
                raise SearchError("Tavily quota or rate limit reached (HTTP %d)"
                                  % status)
            snippet = raw[:200].decode("utf-8", "replace")
            raise SearchError("Tavily returned HTTP %d: %s" % (status, snippet))
        except OSError as exc:
            raise SearchError("network error reaching Tavily: %s" % exc)

        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise SearchError("could not parse Tavily response: %s" % exc)


def format_results(data, snippet_chars=400):
    """Render Tavily JSON as compact text for the model."""
    lines = []
    answer = data.get("answer")
    if answer:
        lines.append("Answer: %s" % answer.strip())
        lines.append("")

    results = data.get("results") or []
    if not results:
        lines.append("No results.")
        return "\n".join(lines)

    lines.append("Sources:")
    for i, item in enumerate(results, 1):
        title = (item.get("title") or "untitled").strip()
        url = (item.get("url") or "").strip()
        content = (item.get("content") or "").strip()
        if len(content) > snippet_chars:
            content = content[:snippet_chars].rstrip() + "..."
        lines.append("[%d] %s" % (i, title))
        lines.append("    %s" % url)
        if content:
            lines.append("    %s" % content)
    return "\n".join(lines)
