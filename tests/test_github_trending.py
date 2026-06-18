"""Unit tests for the GitHub Trending HTML scraper."""

from __future__ import annotations

import asyncio
import unittest

import httpx

from src.scraper import github_trending


SAMPLE_HTML = """
<html>
<body>
  <div class="Box">
    <article class="Box-row">
      <h2 class="h3 lh-condensed">
        <a href="/DeusData/codebase-memory-mcp">DeusData / codebase-memory-mcp</a>
      </h2>
      <p class="col-9 color-fg-muted my-1 pr-4">
        High-performance code intelligence MCP server.
      </p>
      <div class="f6 color-fg-muted mt-2">
        <span itemprop="programmingLanguage">C</span>
        <a href="/DeusData/codebase-memory-mcp/stargazers">158</a>
        <span class="d-inline-block float-sm-right">371 stars today</span>
      </div>
    </article>
    <article class="Box-row">
      <h2 class="h3 lh-condensed">
        <a href="/n0-computer/iroh">n0-computer / iroh</a>
      </h2>
      <p class="col-9 color-fg-muted my-1 pr-4">
        IP addresses break, dial keys instead.
      </p>
      <div class="f6 color-fg-muted mt-2">
        <a href="/n0-computer/iroh/stargazers">3,402</a>
        <span class="d-inline-block float-sm-right">95 stars this week</span>
      </div>
    </article>
    <article class="Box-row">
      <h2 class="h3 lh-condensed">
        <a href="/foo/bar">foo / bar</a>
      </h2>
      <p class="col-9 color-fg-muted my-1 pr-4"></p>
      <div class="f6 color-fg-muted mt-2">
        <span class="d-inline-block float-sm-right">12 stars this month</span>
      </div>
    </article>
  </div>
</body>
</html>
"""


class ParseTrendingHtmlTest(unittest.TestCase):
    def test_parses_full_name_owner_name(self) -> None:
        repos = github_trending.parse_trending_html(SAMPLE_HTML)
        self.assertEqual(repos[0]["full_name"], "DeusData/codebase-memory-mcp")
        self.assertEqual(repos[0]["owner"], "DeusData")
        self.assertEqual(repos[0]["name"], "codebase-memory-mcp")

    def test_parses_description(self) -> None:
        repos = github_trending.parse_trending_html(SAMPLE_HTML)
        self.assertIn("High-performance code intelligence", repos[0]["description"])
        self.assertIn("IP addresses break", repos[1]["description"])

    def test_parses_language_only_when_present(self) -> None:
        repos = github_trending.parse_trending_html(SAMPLE_HTML)
        self.assertEqual(repos[0]["language"], "C")
        self.assertEqual(repos[1]["language"], "")
        self.assertEqual(repos[2]["language"], "")

    def test_parses_stars_today_and_period(self) -> None:
        repos = github_trending.parse_trending_html(SAMPLE_HTML)
        self.assertEqual(repos[0]["stars_today"], 371)
        self.assertEqual(repos[0]["stars_period"], "today")
        self.assertEqual(repos[1]["stars_today"], 95)
        self.assertEqual(repos[1]["stars_period"], "this week")
        self.assertEqual(repos[2]["stars_today"], 12)
        self.assertEqual(repos[2]["stars_period"], "this month")

    def test_parses_repo_url(self) -> None:
        repos = github_trending.parse_trending_html(SAMPLE_HTML)
        self.assertEqual(repos[0]["repo_url"], "https://github.com/DeusData/codebase-memory-mcp")

    def test_empty_html_returns_empty(self) -> None:
        self.assertEqual(github_trending.parse_trending_html(""), [])
        self.assertEqual(github_trending.parse_trending_html("<html></html>"), [])

    def test_handles_comma_in_count(self) -> None:
        html = """
        <article class="Box-row">
          <h2><a href="/a/b">a / b</a></h2>
          <p class="col-9">x</p>
          <div><span class="float-sm-right">1,234 stars today</span></div>
        </article>
        """
        repos = github_trending.parse_trending_html(html)
        self.assertEqual(repos[0]["stars_today"], 1234)


class BuildTrendingUrlTest(unittest.TestCase):
    def test_url_for_all_languages(self) -> None:
        self.assertEqual(
            github_trending.build_trending_url(None, "daily"),
            "https://github.com/trending?since=daily",
        )
        self.assertEqual(
            github_trending.build_trending_url("", "weekly"),
            "https://github.com/trending?since=weekly",
        )

    def test_url_for_specific_language(self) -> None:
        self.assertEqual(
            github_trending.build_trending_url("python", "daily"),
            "https://github.com/trending/python?since=daily",
        )
        self.assertEqual(
            github_trending.build_trending_url("C++", "weekly"),
            "https://github.com/trending/c%2B%2B?since=weekly",
        )

    def test_invalid_since_rejected(self) -> None:
        with self.assertRaises(ValueError):
            github_trending.build_trending_url(None, "yearly")

    def test_invalid_language_rejected(self) -> None:
        with self.assertRaises(ValueError):
            github_trending.build_trending_url("   ", "daily")


class FetchTrendingHtmlTest(unittest.TestCase):
    def test_returns_repos_on_200(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "github.com" and request.url.path == "/trending":
                return httpx.Response(200, text=SAMPLE_HTML)
            return httpx.Response(404, text="not found")

        repos = asyncio.run(github_trending.fetch_trending_html(since="daily", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
        self.assertEqual(len(repos), 3)
        self.assertEqual(repos[0]["full_name"], "DeusData/codebase-memory-mcp")

    def test_raises_on_http_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="Service Unavailable")

        async def runner() -> None:
            await github_trending.fetch_trending_html(since="daily", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

        with self.assertRaisesRegex(ValueError, r"HTTP 503"):
            asyncio.run(runner())

    def test_raises_on_empty_body(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html><body>oops</body></html>")

        async def runner() -> None:
            await github_trending.fetch_trending_html(since="daily", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

        with self.assertRaisesRegex(ValueError, r"no repository cards"):
            asyncio.run(runner())

    def test_sends_user_agent(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.headers)
            return httpx.Response(200, text=SAMPLE_HTML)

        asyncio.run(
            github_trending.fetch_trending_html(
                since="daily",
                client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            )
        )
        self.assertIn("Mozilla", seen.get("user-agent", ""))
        self.assertTrue(seen.get("accept-language", "").lower().startswith("en"))


if __name__ == "__main__":
    unittest.main()
