from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from src.console import skills_hotlist


class SkillsHotlistTest(unittest.TestCase):
    def test_collect_candidates_merges_sources_and_scores_for_video(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "skillhub.cn":
                return httpx.Response(200, text=SKILLHUB_HTML)
            if request.url.host == "clawhub.ai" and request.url.path == "/api/v1/skills":
                return httpx.Response(200, json=CLAWHUB_PAYLOAD)
            return httpx.Response(404)

        result = asyncio.run(_collect_with_transport(httpx.MockTransport(handler)))

        self.assertEqual(result["cache_status"], "fresh")
        self.assertFalse(result["degraded"])
        self.assertEqual(result["total_fetched"], 4)
        first = result["items"][0]
        self.assertEqual(first["name"], "Browser Research Skill")
        self.assertEqual(first["sources"], ["SkillHub", "ClawHub"])
        self.assertGreaterEqual(first["score"], 80)
        self.assertIn("实用技能推荐", first["recommendation"])
        self.assertIn("浏览器", first["topics"])

    def test_collect_candidates_uses_html_fallback_for_clawhub(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "skillhub.cn":
                return httpx.Response(200, text=SKILLHUB_HTML)
            if request.url.host == "clawhub.ai" and request.url.path == "/api/v1/skills":
                return httpx.Response(503, text="temporarily unavailable")
            if request.url.host == "clawhub.ai":
                return httpx.Response(200, text=CLAWHUB_HTML)
            return httpx.Response(404)

        result = asyncio.run(_collect_with_transport(httpx.MockTransport(handler)))

        self.assertTrue(result["degraded"])
        self.assertIn("clawhub", result["degraded_reason"])
        names = [item["name"] for item in result["items"]]
        self.assertIn("Code Review Skill", names)

    def test_collect_candidates_reuses_cache_when_requested(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if request.url.host == "skillhub.cn":
                return httpx.Response(200, text=SKILLHUB_HTML)
            if request.url.host == "clawhub.ai" and request.url.path == "/api/v1/skills":
                return httpx.Response(200, json=CLAWHUB_PAYLOAD)
            return httpx.Response(404)

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            asyncio.run(_collect_with_transport(httpx.MockTransport(handler), cache_dir=cache_dir))
            result = asyncio.run(_collect_with_transport(
                httpx.MockTransport(handler),
                cache_dir=cache_dir,
                force_refresh=False,
            ))

        self.assertEqual(calls, 2)
        self.assertEqual(result["cache_status"], "hit")
        self.assertEqual(result["items"][0]["name"], "Browser Research Skill")

    def test_collect_candidates_uses_stale_cache_when_all_sources_fail(self) -> None:
        def success(request: httpx.Request) -> httpx.Response:
            if request.url.host == "skillhub.cn":
                return httpx.Response(200, text=SKILLHUB_HTML)
            if request.url.host == "clawhub.ai" and request.url.path == "/api/v1/skills":
                return httpx.Response(200, json=CLAWHUB_PAYLOAD)
            return httpx.Response(404)

        def failure(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="down")

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            asyncio.run(_collect_with_transport(httpx.MockTransport(success), cache_dir=cache_dir))
            result = asyncio.run(_collect_with_transport(
                httpx.MockTransport(failure),
                cache_dir=cache_dir,
                force_refresh=True,
            ))

        self.assertEqual(result["cache_status"], "stale_error")
        self.assertTrue(result["degraded"])
        self.assertEqual(result["items"][0]["name"], "Browser Research Skill")


async def _collect_with_transport(
    transport: httpx.MockTransport,
    cache_dir: Path | None = None,
    force_refresh: bool = True,
) -> dict:
    original_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    stack = [
        patch("src.console.skills_hotlist.httpx.AsyncClient", side_effect=client_factory),
    ]
    if cache_dir is not None:
        stack.append(patch("src.console.skills_hotlist.CACHE_DIR", cache_dir))
    with stack[0]:
        if len(stack) > 1:
            with stack[1]:
                return await skills_hotlist.collect_candidates_with_meta("weekly", limit=5, force_refresh=force_refresh)
        return await skills_hotlist.collect_candidates_with_meta("weekly", limit=5, force_refresh=force_refresh)


SKILLHUB_HTML = """
<html>
  <head><title>SkillHub-专为中国用户优化的Skills社区</title></head>
  <body>
    <script id="__NEXT_DATA__" type="application/json">
      {"props":{"pageProps":{"skills":[
        {"name":"Browser Research Skill","description":"AI browser search and research workflow","slug":"browser-research","tags":["browser","agent"]},
        {"name":"PPT Maker Skill","description":"Create slides and visual scripts for short videos","slug":"ppt-maker","tags":["ppt","video"]}
      ]}}}
    </script>
  </body>
</html>
"""

CLAWHUB_PAYLOAD = {
    "items": [
        {
            "name": "Browser Research Skill",
            "description": "AI browser search and research workflow with citations",
            "slug": "browser-research",
            "tags": ["browser", "research"],
            "downloads": 1200,
        },
        {
            "name": "Code Review Skill",
            "description": "Agent skill for reviewing pull requests and code changes",
            "slug": "code-review",
            "tags": ["coding", "github"],
        },
    ]
}

CLAWHUB_HTML = """
<html><body>
  <a href="/skills/code-review">
    <h2>Code Review Skill</h2>
    <p>Agent skill for reviewing pull requests and code changes</p>
  </a>
</body></html>
"""
