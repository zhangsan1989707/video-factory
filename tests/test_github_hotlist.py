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
