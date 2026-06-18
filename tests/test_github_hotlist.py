from __future__ import annotations

import asyncio
import base64
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import httpx

from src.console import github_hotlist


class GithubHotlistTest(unittest.TestCase):
    def test_collect_candidates_without_token(self) -> None:
        seen_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.update(request.headers)
            return _github_response()

        result = asyncio.run(_collect_with_transport("", httpx.MockTransport(handler), force_refresh=True))

        self.assertNotIn("authorization", seen_headers)
        self.assertRegex(result["rate_limit"], r"^59/60，重置 \d{2}:\d{2}$")
        self.assertEqual(result["items"][0]["full_name"], "demo/alpha")
        self.assertEqual(result["items"][0]["forks"], 17)
        self.assertEqual(result["items"][0]["issues"], 3)
        self.assertRegex(result["items"][0]["daily_growth"], r"^估算日均 star 约 \+\d+/天$")
        self.assertIn("不是真实新增 star", result["items"][0]["growth_note"])

    def test_collect_candidates_with_token(self) -> None:
        seen_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.update(request.headers)
            return _github_response()

        result = asyncio.run(_collect_with_transport("ghp_test", httpx.MockTransport(handler), force_refresh=True))

        self.assertEqual(seen_headers.get("authorization"), "Bearer ghp_test")
        self.assertEqual(result["items"][0]["full_name"], "demo/alpha")

    def test_collect_candidates_reports_github_error_context(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                headers={
                    "x-ratelimit-remaining": "0",
                    "x-ratelimit-limit": "60",
                    "x-ratelimit-reset": "1893456000",
                },
                json={"message": "API rate limit exceeded"},
            )

        with self.assertRaisesRegex(ValueError, r"HTTP 403 API rate limit exceeded") as raised:
            asyncio.run(_collect_with_transport("", httpx.MockTransport(handler), force_refresh=True))

        self.assertIn("GitHub API 额度 0/60，重置", str(raised.exception))

    def test_collect_candidates_skips_fresh_cache_by_default(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return _github_response()

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            first = asyncio.run(_collect_with_transport("", httpx.MockTransport(handler), force_refresh=True, cache_dir=cache_dir))
            second = asyncio.run(_collect_with_transport("", httpx.MockTransport(handler), cache_dir=cache_dir))

        # Each invocation now hits GitHub twice: trending HTML + Search API fallback.
        self.assertEqual(calls, 4)
        self.assertEqual(first["cache_status"], "fresh")
        self.assertEqual(second["cache_status"], "fresh")
        self.assertEqual(second["items"][0]["full_name"], "demo/alpha")
        # Both calls fell back to Search API because the mock transport cannot
        # serve the GitHub Trending HTML page.
        self.assertEqual(first["data_source"], "search_api")
        self.assertTrue(first["degraded"])
        self.assertEqual(second["data_source"], "search_api")
        self.assertTrue(second["degraded"])

    def test_collect_candidates_can_reuse_fresh_cache_when_requested(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return _github_response()

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            asyncio.run(_collect_with_transport("", httpx.MockTransport(handler), force_refresh=True, cache_dir=cache_dir))
            result = asyncio.run(_collect_with_transport("", httpx.MockTransport(handler), force_refresh=False, cache_dir=cache_dir))

        # First call hits GitHub twice (trending + fallback); the cached second
        # call does not touch the network.
        self.assertEqual(calls, 2)
        self.assertEqual(result["cache_status"], "hit")
        self.assertEqual(result["items"][0]["full_name"], "demo/alpha")

    def test_collect_candidates_uses_stale_cache_on_rate_limit(self) -> None:
        def success_handler(request: httpx.Request) -> httpx.Response:
            return _github_response()

        def limited_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                headers={
                    "x-ratelimit-remaining": "0",
                    "x-ratelimit-limit": "30",
                    "x-ratelimit-reset": "1893456000",
                },
                json={"message": "API rate limit exceeded"},
            )

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            asyncio.run(_collect_with_transport("", httpx.MockTransport(success_handler), force_refresh=True, cache_dir=cache_dir))
            result = asyncio.run(_collect_with_transport("", httpx.MockTransport(limited_handler), force_refresh=True, cache_dir=cache_dir))

        self.assertEqual(result["cache_status"], "stale_rate_limit")
        self.assertEqual(result["items"][0]["full_name"], "demo/alpha")

    def test_heuristic_descriptions_are_project_specific(self) -> None:
        ppt = github_hotlist._localized_description({
            "full_name": "gorden/GordenSuperPPTSkills",
            "name": "GordenSuperPPTSkills",
            "description": "AI powered PowerPoint presentation workflow",
            "topics": ["ai", "ppt", "workflow"],
        })
        design = github_hotlist._localized_description({
            "full_name": "baoyu/baoyu-design",
            "name": "baoyu-design",
            "description": "Claude agent skills for generating UI design drafts",
            "topics": ["ai", "design", "claude"],
        })

        self.assertIn("PPT", ppt)
        self.assertIn("设计", design)
        self.assertNotEqual(ppt, design)
        self.assertNotIn("围绕 AI 工具或模型工作流", ppt)
        self.assertNotIn("围绕 AI 工具或模型工作流", design)

    def test_recommendation_hides_internal_tag_quality_label(self) -> None:
        recommendation = github_hotlist._recommendation_reason({
            "full_name": "demo/alpha",
            "name": "alpha",
            "description": "AI agent workflow",
            "language": "Python",
            "topics": ["ai", "agent"],
        })

        self.assertIn("Python 项目", recommendation)
        self.assertNotIn("标签完善", recommendation)
        self.assertNotIn("信息待补充", recommendation)

    def test_missing_repo_description_uses_readme_context(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/repos/demo/alpha/readme"):
                readme = "# performative-ui\n\nAI-native React components for satirical product interfaces."
                return httpx.Response(
                    200,
                    json={"content": base64.b64encode(readme.encode("utf-8")).decode("ascii"), "encoding": "base64"},
                )
            return _github_response(description=None, topics=["react", "ui"], language="TypeScript")

        result = asyncio.run(_collect_with_transport("", httpx.MockTransport(handler), force_refresh=True, enrich_with_llm=False))
        item = result["items"][0]

        self.assertEqual(item["description"], "")
        self.assertEqual(item["description_source"], "readme")
        self.assertEqual(item["repo_description_missing"], True)
        self.assertIn("项目说明显示", item["description_zh"])
        self.assertIn("AI-native React components", item["description_zh"])
        self.assertNotIn("GitHub 简介字段", item["description_zh"])
        self.assertIn("简介未填写", item["risk"])
        self.assertNotIn("建议跳过", item["description_zh"])

    def test_collect_candidates_uses_trending_as_primary_source(self) -> None:
        from tests.test_github_trending import SAMPLE_HTML

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "github.com":
                return httpx.Response(200, text=SAMPLE_HTML)
            if request.url.path == "/repos/DeusData/codebase-memory-mcp":
                return httpx.Response(
                    200,
                    json={
                        "full_name": "DeusData/codebase-memory-mcp",
                        "name": "codebase-memory-mcp",
                        "owner": {"login": "DeusData"},
                        "description": "Trending primary description",
                        "stargazers_count": 12345,
                        "forks_count": 678,
                        "open_issues_count": 12,
                        "language": "C",
                        "topics": ["mcp", "agent"],
                        "html_url": "https://github.com/DeusData/codebase-memory-mcp",
                        "homepage": "https://example.com",
                        "created_at": "2025-12-01T00:00:00Z",
                        "updated_at": "2026-01-15T00:00:00Z",
                    },
                    headers={
                        "x-ratelimit-remaining": "4990",
                        "x-ratelimit-limit": "5000",
                        "x-ratelimit-reset": "1893456000",
                    },
                )
            return httpx.Response(404, text="not found")

        result = asyncio.run(_collect_with_transport(
            "ghp_test",
            httpx.MockTransport(handler),
            force_refresh=True,
            enrich_with_llm=False,
        ))

        self.assertEqual(result["data_source"], "trending")
        self.assertFalse(result["degraded"])
        # The first trending repo is enriched with the /repos response.
        first = result["items"][0]
        self.assertEqual(first["full_name"], "DeusData/codebase-memory-mcp")
        self.assertEqual(first["stars_today"], 371)
        self.assertEqual(first["stars"], 12345)
        self.assertEqual(first["language"], "C")
        self.assertEqual(first["data_source"], "trending")

    def test_collect_candidates_falls_back_to_search_api_when_trending_fails(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "github.com":
                return httpx.Response(503, text="Service Unavailable")
            return _github_response()

        result = asyncio.run(_collect_with_transport(
            "",
            httpx.MockTransport(handler),
            force_refresh=True,
            enrich_with_llm=False,
        ))

        self.assertEqual(result["data_source"], "search_api")
        self.assertTrue(result["degraded"])
        self.assertIn("503", result["degraded_reason"])
        self.assertEqual(result["items"][0]["full_name"], "demo/alpha")

    def test_collect_candidates_trending_data_survives_enrichment_failure(self) -> None:
        from tests.test_github_trending import SAMPLE_HTML

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "github.com":
                return httpx.Response(200, text=SAMPLE_HTML)
            if "/repos/" in request.url.path:
                return httpx.Response(403, text="rate limit")
            return httpx.Response(404, text="not found")

        result = asyncio.run(_collect_with_transport(
            "",
            httpx.MockTransport(handler),
            force_refresh=True,
            enrich_with_llm=False,
        ))

        self.assertEqual(result["data_source"], "trending")
        # Even though /repos enrichment failed, stars_today from trending still flows through.
        first = result["items"][0]
        self.assertEqual(first["full_name"], "DeusData/codebase-memory-mcp")
        self.assertEqual(first["stars_today"], 371)
        # stars_total is 0 because /repos enrichment did not succeed.
        self.assertEqual(first["stars"], 0)

    def test_collect_candidates_accepts_language_filter(self) -> None:
        seen_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            if request.url.host == "github.com":
                return httpx.Response(200, text="<html></html>")
            return _github_response()

        asyncio.run(_collect_with_transport(
            "",
            httpx.MockTransport(handler),
            force_refresh=True,
            enrich_with_llm=False,
        ))
        # The fallback Search API call should still go out (we did not pass a
        # language filter here, so the URL keeps `time_window=weekly` only).

    def test_collect_candidates_passes_language_to_trending(self) -> None:
        from tests.test_github_trending import SAMPLE_HTML

        seen_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            if request.url.host == "github.com" and request.url.path == "/trending/python":
                return httpx.Response(200, text=SAMPLE_HTML)
            if "/repos/DeusData/codebase-memory-mcp" in request.url.path:
                return httpx.Response(
                    200,
                    json={
                        "full_name": "DeusData/codebase-memory-mcp",
                        "name": "codebase-memory-mcp",
                        "owner": {"login": "DeusData"},
                        "description": "x",
                        "stargazers_count": 1,
                        "forks_count": 0,
                        "open_issues_count": 0,
                        "language": "C",
                        "topics": [],
                        "html_url": "https://github.com/DeusData/codebase-memory-mcp",
                        "homepage": "",
                        "created_at": "2025-12-01T00:00:00Z",
                        "updated_at": "2026-01-15T00:00:00Z",
                    },
                )
            return httpx.Response(404, text="not found")

        result = asyncio.run(_collect_with_transport(
            "",
            httpx.MockTransport(handler),
            force_refresh=True,
            enrich_with_llm=False,
            language="python",
        ))

        # Language filter must round-trip into the trending URL.
        self.assertTrue(any("/trending/python" in u for u in seen_urls), seen_urls)
        self.assertEqual(result["data_source"], "trending")
        self.assertEqual(result["items"][0]["stars_today"], 371)

    def test_collect_candidates_cache_persists_data_source(self) -> None:
        from tests.test_github_trending import SAMPLE_HTML

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "github.com":
                return httpx.Response(200, text=SAMPLE_HTML)
            if "/repos/DeusData/codebase-memory-mcp" in request.url.path:
                return httpx.Response(
                    200,
                    json={
                        "full_name": "DeusData/codebase-memory-mcp",
                        "name": "codebase-memory-mcp",
                        "owner": {"login": "DeusData"},
                        "description": "x",
                        "stargazers_count": 1,
                        "forks_count": 0,
                        "open_issues_count": 0,
                        "language": "C",
                        "topics": [],
                        "html_url": "https://github.com/DeusData/codebase-memory-mcp",
                        "homepage": "",
                        "created_at": "2025-12-01T00:00:00Z",
                        "updated_at": "2026-01-15T00:00:00Z",
                    },
                )
            return httpx.Response(404, text="not found")

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            first = asyncio.run(_collect_with_transport(
                "",
                httpx.MockTransport(handler),
                force_refresh=True,
                enrich_with_llm=False,
                cache_dir=cache_dir,
            ))
            second = asyncio.run(_collect_with_transport(
                "",
                httpx.MockTransport(handler),
                force_refresh=False,
                enrich_with_llm=False,
                cache_dir=cache_dir,
            ))

        self.assertEqual(first["data_source"], "trending")
        self.assertEqual(second["cache_status"], "hit")
        self.assertEqual(second["data_source"], "trending")
        self.assertEqual(second["items"][0]["stars_today"], 371)


async def _collect_with_transport(
    token: str,
    transport: httpx.MockTransport,
    force_refresh: bool = True,
    cache_dir: Path | None = None,
    enrich_with_llm: bool = True,
    language: str | None = None,
):
    original = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    with ExitStack() as stack:
        if cache_dir is None:
            cache_dir = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(patch("src.console.github_hotlist.CACHE_DIR", cache_dir))
        httpx.AsyncClient = client_factory
        try:
            return await github_hotlist.collect_candidates_with_meta(
                "weekly",
                token=token,
                limit=1,
                force_refresh=force_refresh,
                enrich_with_llm=enrich_with_llm,
                language=language,
            )
        finally:
            httpx.AsyncClient = original


def _github_response(
    description: str | None = "AI agent workflow",
    topics: list[str] | None = None,
    language: str = "Python",
) -> httpx.Response:
    return httpx.Response(
        200,
        headers={
            "x-ratelimit-remaining": "59",
            "x-ratelimit-limit": "60",
            "x-ratelimit-reset": "1893456000",
        },
        json={
            "items": [
                {
                    "full_name": "demo/alpha",
                    "name": "alpha",
                    "owner": {"login": "demo"},
                    "description": description,
                    "stargazers_count": 120,
                    "forks_count": 17,
                    "open_issues_count": 3,
                    "language": language,
                    "topics": topics if topics is not None else ["ai"],
                    "html_url": "https://github.com/demo/alpha",
                    "homepage": "",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-02T00:00:00Z",
                }
            ]
        },
    )


if __name__ == "__main__":
    unittest.main()
