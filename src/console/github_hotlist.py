"""GitHub hotlist candidate collection for the console."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any

import httpx

GITHUB_SEARCH_API = "https://api.github.com/search/repositories"


def created_after(time_window: str) -> str:
    days = {"daily": 1, "weekly": 7, "monthly": 30}.get(time_window, 7)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.strftime("%Y-%m-%d")


async def collect_candidates(
    time_window: str,
    token: str = "",
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Collect recent repositories using GitHub Search API."""
    return (await collect_candidates_with_meta(time_window, token=token, limit=limit))["items"]


async def collect_candidates_with_meta(
    time_window: str,
    token: str = "",
    limit: int = 30,
) -> dict[str, Any]:
    """Collect recent repositories and return GitHub response metadata."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-video-console",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {
        "q": f"created:>={created_after(time_window)} stars:>10 archived:false",
        "sort": "stars",
        "order": "desc",
        "per_page": min(limit, 100),
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(GITHUB_SEARCH_API, headers=headers, params=params)
        if response.status_code >= 400:
            raise ValueError(_github_error_message(response))
        data = response.json()
        rate_limit = _rate_limit_label(response.headers)

    candidates = []
    for index, item in enumerate(data.get("items", [])[:limit], start=1):
        owner = item.get("owner") or {}
        candidates.append({
            "rank": index,
            "full_name": item.get("full_name", ""),
            "name": item.get("name", ""),
            "owner": owner.get("login", ""),
            "description": item.get("description") or "",
            "description_zh": _localized_description(item),
            "stars": item.get("stargazers_count", 0),
            "daily_growth": _estimated_daily_growth(item),
            "forks": item.get("forks_count", 0),
            "issues": item.get("open_issues_count", 0),
            "language": item.get("language") or "",
            "topics": item.get("topics") or [],
            "repo_url": item.get("html_url", ""),
            "homepage": item.get("homepage") or "",
            "created_at": item.get("created_at", ""),
            "updated_at": item.get("updated_at", ""),
            "score": _content_score(item),
            "recommendation": _recommendation_reason(item),
            "risk": _risk_note(item),
            "audience": _audience(item),
            "visual_potential": _visual_potential(item),
            "selected": index <= 10,
        })
    return {"items": candidates, "rate_limit": rate_limit}


def _estimated_daily_growth(item: dict[str, Any]) -> str:
    stars = int(item.get("stargazers_count") or 0)
    created_at = str(item.get("created_at") or "")
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        age_days = max(1, (datetime.now(timezone.utc) - created).days)
    except ValueError:
        age_days = 30
    return f"约 +{max(1, round(stars / age_days))}/天" if stars else "暂无"


def _rate_limit_label(headers: httpx.Headers) -> str:
    remaining = headers.get("x-ratelimit-remaining")
    limit = headers.get("x-ratelimit-limit")
    reset = headers.get("x-ratelimit-reset")
    if not remaining or not limit:
        return "未检测"
    if reset and reset.isdigit():
        reset_at = datetime.fromtimestamp(int(reset), tz=timezone.utc).astimezone().strftime("%H:%M")
        return f"{remaining}/{limit}，重置 {reset_at}"
    return f"{remaining}/{limit}"


def _github_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    message = str(payload.get("message") or response.reason_phrase or "请求失败")
    rate_limit = _rate_limit_label(response.headers)
    suffix = "" if rate_limit == "未检测" else f"，GitHub API 额度 {rate_limit}"
    return f"GitHub API 请求失败: HTTP {response.status_code} {message}{suffix}"


def _content_score(item: dict[str, Any]) -> int:
    score = 40
    stars = int(item.get("stargazers_count") or 0)
    topics = item.get("topics") or []
    description = item.get("description") or ""
    if stars >= 1000:
        score += 25
    elif stars >= 300:
        score += 18
    elif stars >= 100:
        score += 10
    if item.get("homepage"):
        score += 10
    if item.get("language"):
        score += 8
    if topics:
        score += min(12, len(topics) * 3)
    if _has_any_keyword(f"{description} {' '.join(topics)}", ("ai", "agent", "llm", "video")):
        score += 10
    return min(score, 100)


def _recommendation_reason(item: dict[str, Any]) -> str:
    stars = int(item.get("stargazers_count") or 0)
    language = item.get("language") or "多语言"
    tags = _topic_label(item)
    value = _localized_description(item)
    star_text = f"{stars:,}"
    return f"{language} 项目，近期获得 {star_text} 个星标。{tags}，适合做成中文短视频切入点：{value}"


def _risk_note(item: dict[str, Any]) -> str:
    description = item.get("description") or ""
    if not description:
        return "描述缺失，生成口播前需要人工确认用途。"
    if int(item.get("stargazers_count") or 0) < 50:
        return "热度偏低，建议确认是否真的适合入榜。"
    return "暂无明显风险，仍需避免夸大项目能力。"


def _audience(item: dict[str, Any]) -> str:
    text = f"{item.get('description') or ''} {' '.join(item.get('topics') or [])}"
    if _has_any_keyword(text, ("ai", "agent", "llm", "model")):
        return "AI 工具开发者"
    if _has_any_keyword(text, ("frontend", "react", "vue", "ui")):
        return "前端开发者"
    if _has_any_keyword(text, ("data", "database", "analytics")):
        return "数据开发者"
    return "开源项目关注者"


def _visual_potential(item: dict[str, Any]) -> str:
    if item.get("homepage"):
        return "高：有主页或演示页面可截图。"
    topics = item.get("topics") or []
    if topics:
        return "中：可用 README、标签和仓库页做信息卡片。"
    return "低：目前主要依赖仓库页信息。"


def _has_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = text.lower()
    return any(re.search(rf"(^|[^a-z0-9]){re.escape(keyword)}([^a-z0-9]|$)", normalized) for keyword in keywords)


def _localized_description(item: dict[str, Any]) -> str:
    description = item.get("description") or ""
    text = f"{description} {' '.join(item.get('topics') or [])}"
    if not description:
        return "项目描述较少，需要先打开仓库确认具体用途。"
    if _has_any_keyword(text, ("aircraft", "flight", "projector", "raspberry", "hardware", "sdr")):
        return "偏硬件、实时数据或空间展示，适合用场景感讲清楚它的玩法。"
    if _has_any_keyword(text, ("video", "image", "audio", "visual", "3d")):
        return "和多媒体生成或可视化有关，画面表达空间比较大。"
    if _has_any_keyword(text, ("ai", "agent", "llm", "model", "rag")):
        return "围绕 AI 工具或模型工作流，适合讲清楚它解决的具体问题。"
    if _has_any_keyword(text, ("react", "vue", "frontend", "ui", "css")):
        return "偏前端或界面工具，适合用效果展示和场景对比来讲。"
    if _has_any_keyword(text, ("data", "database", "analytics", "sql")):
        return "偏数据处理或分析工具，适合从使用场景和效率提升切入。"
    if _has_any_keyword(text, ("cli", "terminal", "shell", "developer")):
        return "偏开发者工具，适合用命令行或工作流演示来讲。"
    return "近期热度上升，可以从项目用途、适合人群和实际价值三个角度介绍。"


def _topic_label(item: dict[str, Any]) -> str:
    topics = item.get("topics") or []
    if topics:
        return "标签信息较完整"
    if item.get("homepage"):
        return "有主页或演示页面"
    return "需要结合 README 进一步判断"
