"""GitHub Trending HTML scraper.

GitHub does not expose a public API for the Trending page
(``https://github.com/trending``), so this module fetches the HTML and parses
the repository cards.

Each card yields:
    {
        "full_name": "owner/name",
        "description": "...",
        "language": "Python",
        "stars_today": 123,
        "stars_period": "today" | "this week" | "this month",
        "repo_url": "https://github.com/owner/name",
        "owner": "owner",
        "name": "name",
    }
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

GITHUB_TRENDING_BASE = "https://github.com/trending"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

VALID_SINCE = {"daily", "weekly", "monthly"}
PERIOD_LABEL = {"daily": "today", "weekly": "this week", "monthly": "this month"}

# Reserved language slugs GitHub does not expose under /trending/{lang}
_BLOCKED_LANGUAGE_SLUGS: set[str] = set()

_ARTICLE_RE = re.compile(
    r'<article[^>]*class="[^"]*Box-row[^"]*"[^>]*>(.*?)</article>',
    re.DOTALL,
)
_HREF_RE = re.compile(r'href="/([^"/?#][^"?#]*/[^"?#]+)"')
_DESCRIPTION_RE = re.compile(
    r'<p class="col-9[^"]*"[^>]*>(.*?)</p>',
    re.DOTALL,
)
_LANG_RE = re.compile(r'itemprop="programmingLanguage">([^<]+)<')
_STARS_RE = re.compile(
    r'([\d,]+)\s+stars?\s+(today|this week|this month)',
    re.IGNORECASE,
)


def _clean_text(raw: str) -> str:
    """Strip HTML tags / entities from a snippet."""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    return re.sub(r"\s+", " ", text).strip()


def _parse_count(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else 0


def _parse_article(raw: str) -> dict[str, Any] | None:
    href_match = _HREF_RE.search(raw)
    if not href_match:
        return None
    full_path = href_match.group(1)
    if "/" not in full_path:
        return None
    owner, name = full_path.split("/", 1)
    if not owner or not name:
        return None

    desc_match = _DESCRIPTION_RE.search(raw)
    description = _clean_text(desc_match.group(1)) if desc_match else ""

    lang_match = _LANG_RE.search(raw)
    language = (lang_match.group(1).strip() if lang_match else "") or ""

    stars_match = _STARS_RE.search(raw)
    stars_today = _parse_count(stars_match.group(1)) if stars_match else 0
    stars_period = (stars_match.group(2).lower() if stars_match else "").strip()

    return {
        "full_name": f"{owner}/{name}",
        "owner": owner,
        "name": name,
        "description": description,
        "language": language,
        "stars_today": stars_today,
        "stars_period": stars_period,
        "repo_url": f"https://github.com/{owner}/{name}",
    }


def parse_trending_html(html: str) -> list[dict[str, Any]]:
    """Parse GitHub Trending HTML and return one entry per repository card.

    Defensive against missing fields: returns an empty list when no articles
    are present so the caller can decide to fall back to a different source.
    """
    repos: list[dict[str, Any]] = []
    for raw in _ARTICLE_RE.findall(html or ""):
        parsed = _parse_article(raw)
        if parsed:
            repos.append(parsed)
    return repos


def build_trending_url(language: str | None, since: str) -> str:
    """Construct a Trending page URL for the given language / time window."""
    if since not in VALID_SINCE:
        raise ValueError(f"Invalid since={since!r}, expected one of {sorted(VALID_SINCE)}")
    if language:
        slug = quote(language.strip().lower(), safe="")
        if not slug or slug in _BLOCKED_LANGUAGE_SLUGS:
            raise ValueError(f"Invalid language slug: {language!r}")
        return f"{GITHUB_TRENDING_BASE}/{slug}?since={since}"
    return f"{GITHUB_TRENDING_BASE}?since={since}"


async def fetch_trending_html(
    language: str | None = None,
    since: str = "daily",
    *,
    client: httpx.AsyncClient | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[dict[str, Any]]:
    """Fetch GitHub Trending page HTML and parse it.

    Returns a list of repository dicts (see module docstring). Raises
    ``ValueError`` on HTTP error or empty result so the caller can decide
    whether to fall back to an alternative source.
    """
    if since not in VALID_SINCE:
        raise ValueError(f"Invalid since={since!r}, expected one of {sorted(VALID_SINCE)}")
    url = build_trending_url(language, since)
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    try:
        try:
            response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise ValueError(f"GitHub Trending request failed: {exc}") from exc
        if response.status_code >= 400:
            raise ValueError(
                f"GitHub Trending HTTP {response.status_code}: {response.reason_phrase or 'request failed'}"
            )
        repos = parse_trending_html(response.text)
    finally:
        if owns_client and client is not None:
            await client.aclose()

    if not repos:
        raise ValueError("GitHub Trending response contained no repository cards")
    return repos
