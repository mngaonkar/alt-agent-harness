---
name: websearch
description: Look things up on the live internet with Tavily - current events, news, weather, prices, product specs, library documentation, or any fact that may have changed since training. Use whenever the user asks about something recent, something external to this host, or anything you are not confident is still accurate.
version: 1.0.0
---

# Web search

## When to search

Search when the answer depends on the outside world or on anything that may
have changed: news, weather, prices, releases, versions, datasheets, API
documentation. Also search when you are simply unsure.

Do **not** search for things this host already knows about itself. OS, disk,
RSS, uptime and the workspace come from the `sysinfo` skill. Searching for
those returns worse information than `host_status`.

If `web_search` is not in the tool list, Tavily is not configured. Say so and
offer `http_get` only when the user already has a URL.

## Running a search

`web_search` takes a `query` and optionally `max_results` (1-10, default 5),
`topic`, and `days`.

Write queries as keywords, not as the user's sentence. "grok-4.6 context window"
beats "can you tell me how big grok 4.6's context is?".

For recent events pass `topic: "news"`, optionally with `days` to bound the
window:

    web_search(query="xAI grok model release", topic="news", days=30)

Prefer one well-chosen query over several narrow ones, and raise `max_results`
rather than searching again with a slightly different phrasing.

## Reading the results

The response has an `Answer:` line — Tavily's own synthesis — followed by
numbered sources with URLs and snippets.

Treat the `Answer` as a starting point, not as verified truth. When the
snippets disagree with it, trust the snippets and say so. When sources
disagree with each other, report the disagreement rather than silently
choosing one.

Snippets are truncated. If a snippet is clearly cut off mid-fact and the
detail matters, fetch that one URL with `http_get` to read more.

## Reporting

Answer the question first in your own words, then cite which source it came
from — the site name is enough, with the URL only if the user would need it.
Do not paste the raw result block back to the user.

If the search returns nothing useful, say so plainly and say what you tried.
Do not fall back to guessing from memory while implying it came from the web.
