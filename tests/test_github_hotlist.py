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

    def test_collect_candidates_reuses_fresh_cache(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return _github_response()

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            first = asyncio.run(_collect_with_transport("", httpx.MockTransport(handler), force_refresh=True, cache_dir=cache_dir))
            second = asyncio.run(_collect_with_transport("", httpx.MockTransport(handler), cache_dir=cache_dir))

        self.assertEqual(calls, 1)
        self.assertEqual(first["cache_status"], "fresh")
        self.assertEqual(second["cache_status"], "hit")
        self.assertEqual(second["items"][0]["full_name"], "demo/alpha")

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


async def _collect_with_transport(
    token: str,
    transport: httpx.MockTransport,
    force_refresh: bool = False,
    cache_dir: Path | None = None,
    enrich_with_llm: bool = True,
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
            return await github_hotlist.collect_candidates_with_meta("weekly", token=token, limit=1, force_refresh=force_refresh, enrich_with_llm=enrich_with_llm)
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
