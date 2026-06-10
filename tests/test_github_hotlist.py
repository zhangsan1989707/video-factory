from __future__ import annotations

import asyncio
import unittest

import httpx

from src.console import github_hotlist


class GithubHotlistTest(unittest.TestCase):
    def test_collect_candidates_without_token(self) -> None:
        seen_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.update(request.headers)
            return _github_response()

        result = asyncio.run(_collect_with_transport("", httpx.MockTransport(handler)))

        self.assertNotIn("authorization", seen_headers)
        self.assertRegex(result["rate_limit"], r"^59/60，重置 \d{2}:\d{2}$")
        self.assertEqual(result["items"][0]["full_name"], "demo/alpha")
        self.assertEqual(result["items"][0]["forks"], 17)
        self.assertEqual(result["items"][0]["issues"], 3)
        self.assertRegex(result["items"][0]["daily_growth"], r"^约 \+\d+/天$")

    def test_collect_candidates_with_token(self) -> None:
        seen_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.update(request.headers)
            return _github_response()

        result = asyncio.run(_collect_with_transport("ghp_test", httpx.MockTransport(handler)))

        self.assertEqual(seen_headers.get("authorization"), "Bearer ghp_test")
        self.assertEqual(result["items"][0]["selected"], True)

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
            asyncio.run(_collect_with_transport("", httpx.MockTransport(handler)))

        self.assertIn("GitHub API 额度 0/60，重置", str(raised.exception))

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

async def _collect_with_transport(token: str, transport: httpx.MockTransport):
    original = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    httpx.AsyncClient = client_factory
    try:
        return await github_hotlist.collect_candidates_with_meta("weekly", token=token, limit=1)
    finally:
        httpx.AsyncClient = original


def _github_response() -> httpx.Response:
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
                    "description": "AI agent workflow",
                    "stargazers_count": 120,
                    "forks_count": 17,
                    "open_issues_count": 3,
                    "language": "Python",
                    "topics": ["ai"],
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
