"""Fetch GitHub trending repos data for hotlist v2 video."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

CST = timezone(timedelta(hours=8))

GITHUB_SEARCH_API = "https://api.github.com/search/repositories"

LANG_COLORS: dict[str, str] = {
    "TypeScript": "#3b82f6",
    "Python": "#f59e0b",
    "Rust": "#f97316",
    "Go": "#10b981",
    "JavaScript": "#f7df1e",
    "Java": "#b07219",
    "C++": "#f34b7d",
    "C": "#555555",
    "C#": "#178600",
    "Swift": "#F05138",
    "Kotlin": "#A97BFF",
    "Ruby": "#701516",
    "PHP": "#4F5D95",
    "Dart": "#00B4AB",
    "Lua": "#000080",
    "Zig": "#ec915c",
    "Scala": "#c22d40",
    "Elixir": "#6e4a7e",
    "Shell": "#89e051",
    "Vue": "#41b883",
    "Svelte": "#ff3e00",
}

TECH_TAG_KEYWORDS: dict[str, str] = {
    "ai": "AI",
    "agent": "智能体",
    "llm": "大模型",
    "machine-learning": "机器学习",
    "deep-learning": "深度学习",
    "rag": "RAG",
    "mcp": "MCP",
    "github-actions": "GitHub Actions",
    "cli": "CLI 工具",
    "api": "API",
    "sdk": "SDK",
    "framework": "框架",
    "react": "React",
    "vue": "Vue",
    "nextjs": "Next.js",
    "docker": "Docker",
    "kubernetes": "K8s",
    "database": "数据库",
    "editor": "编辑器",
    "terminal": "终端",
    "automation": "自动化",
    "workflow": "工作流",
    "monitoring": "监控",
    "security": "安全",
    "video": "视频",
    "image": "图像",
    "web": "Web",
    "mobile": "移动端",
}


def _created_after(days: int = 7) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.strftime("%Y-%m-%d")


def _star_display(stars: int) -> str:
    if stars >= 10000:
        return f"{stars / 10000:.1f} 万"
    if stars >= 1000:
        return f"{stars / 1000:.1f}k"
    return str(stars)


def _estimate_daily_growth(stars: int, created_at: str) -> str:
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        age_days = max(1, (datetime.now(timezone.utc) - created).days)
    except (ValueError, TypeError):
        age_days = 30
    daily_avg = stars / age_days
    # Use deterministic multiplier based on project age
    # Newer projects (< 30 days) grow faster relative to average
    multiplier = 2.0 if age_days <= 30 else (1.8 if age_days <= 90 else 1.5)
    recent_daily = int(daily_avg * multiplier)
    if recent_daily >= 1000:
        return f"估算日均 star 约 +{recent_daily / 1000:.1f}k"
    return f"估算日均 star 约 +{recent_daily}"


def _simulate_star_history(stars: int) -> list[int]:
    # Deterministic S-curve: base fraction depends on star count
    base = 0.4 if stars < 1000 else (0.5 if stars < 5000 else 0.6)
    history = []
    for i in range(14):
        progress = (i + 1) / 14
        trend = base + (1 - base) * (progress ** 1.5)
        history.append(int(trend * 100))
    history[-1] = 100
    return history


def _extract_tech_tags(topics: list[str], language: str) -> list[str]:
    tags = []
    if language:
        tags.append(language)
    for topic in topics:
        topic_lower = topic.lower()
        for keyword, label in TECH_TAG_KEYWORDS.items():
            if keyword in topic_lower and label not in tags:
                tags.append(label)
                break
    return tags[:4]


def _localized_tagline(description: str, topics: list[str]) -> str:
    text = f"{description} {' '.join(topics)}".lower()
    if any(k in text for k in ("ai", "agent", "llm")):
        return "AI 编程助手"
    if any(k in text for k in ("framework", "库")):
        return "开发框架"
    if any(k in text for k in ("cli", "terminal", "tool")):
        return "命令行工具"
    if any(k in text for k in ("editor", "ide")):
        return "代码编辑器"
    if any(k in text for k in ("database", "sql", "data")):
        return "数据工具"
    if any(k in text for k in ("monitor", "observ")):
        return "监控工具"
    if any(k in text for k in ("security", "auth")):
        return "安全工具"
    if any(k in text for k in ("deploy", "infra", "cloud")):
        return "基础设施"
    return "开源项目"


def _recommendation_reason(item: dict[str, Any]) -> str:
    stars = item.get("stargazers_count", 0)
    desc = item.get("description") or ""
    lang = item.get("language") or "多语言"
    topics = item.get("topics") or []
    text = f"{desc} {' '.join(topics)}".lower()

    if any(k in text for k in ("ai", "agent", "llm", "claude")):
        return f"AI 领域热门项目，{lang} 实现，社区关注度较高"
    if any(k in text for k in ("editor", "ide", "vscode")):
        return f"新一代开发工具，{lang} 编写，开发者体验出色"
    if any(k in text for k in ("framework", "runtime")):
        return f"核心框架类项目，{lang} 生态重要补充"
    if stars > 5000:
        return f"高星标项目，{lang} 实现，估算热度明显上升"
    return f"近期进入候选列表的 {lang} 项目，有实际使用价值"


async def fetch_trending(
    time_window: str = "weekly",
    token: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Fetch trending repos and return structured data for v2 template."""
    days = {"daily": 1, "weekly": 7, "monthly": 30}.get(time_window, 7)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-video-hotlist-v2",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {
        "q": f"created:>={_created_after(days)} stars:>10 archived:false",
        "sort": "stars",
        "order": "desc",
        "per_page": min(limit, 100),
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(GITHUB_SEARCH_API, headers=headers, params=params)
        if response.status_code >= 400:
            raise ValueError(f"GitHub API error: HTTP {response.status_code}")
        data = response.json()

    items = data.get("items", [])[:limit]

    languages_seen: dict[str, str] = {}
    total_new_stars = 0
    projects = []

    for index, item in enumerate(items, start=1):
        owner = (item.get("owner") or {}).get("login", "")
        stars = item.get("stargazers_count", 0)
        language = item.get("language") or ""
        topics = item.get("topics") or []
        created_at = item.get("created_at", "")
        forks = item.get("forks_count", 0)
        issues = item.get("open_issues_count", 0)

        if language and language not in languages_seen:
            languages_seen[language] = LANG_COLORS.get(language, "#8899bb")

        daily_growth = _estimate_daily_growth(stars, created_at)
        growth_num = int(re.sub(r"[^\d]", "", daily_growth) or "0")
        total_new_stars += growth_num

        projects.append({
            "rank": index,
            "name": item.get("name", ""),
            "owner": owner,
            "owner_initial": owner[0].upper() if owner else "?",
            "tagline": _localized_tagline(item.get("description") or "", topics),
            "description": item.get("description") or "",
            "language": language,
            "language_color": LANG_COLORS.get(language, "#8899bb"),
            "stars": stars,
            "stars_display": _star_display(stars),
            "daily_growth": daily_growth,
            "forks": forks,
            "issues": issues,
            "topics": topics,
            "tech_tags": _extract_tech_tags(topics, language),
            "star_history": _simulate_star_history(stars),
            "reason": _recommendation_reason(item),
            "repo_url": item.get("html_url", ""),
        })

    languages_list = [
        {"name": name, "color": color}
        for name, color in list(languages_seen.items())[:6]
    ]

    if total_new_stars >= 1000:
        new_stars_display = f"{total_new_stars / 1000:.0f}K+"
    else:
        new_stars_display = f"{total_new_stars}+"

    now = datetime.now(CST)
    issue_num = now.isocalendar()[1]

    return {
        "date": f"{now.year} 年 {now.month} 月 {now.day} 日",
        "issue": issue_num,
        "total_projects": len(projects),
        "total_languages": len(languages_list),
        "total_new_stars": new_stars_display,
        "languages": languages_list,
        "theme_highlight": _detect_theme(projects),
        "theme_tags": _detect_theme_tags(projects),
        "projects": projects,
    }


def _detect_theme(projects: list[dict[str, Any]]) -> str:
    ai_count = sum(
        1 for p in projects
        if any(k in f"{p['description']} {' '.join(p['topics'])}".lower()
               for k in ("ai", "agent", "llm", "ml"))
    )
    if ai_count >= len(projects) * 0.4:
        return "AI 工具链大爆发"
    tool_count = sum(
        1 for p in projects
        if any(k in f"{p['description']} {' '.join(p['topics'])}".lower()
               for k in ("cli", "tool", "devtool", "editor"))
    )
    if tool_count >= len(projects) * 0.4:
        return "开发者工具新势力"
    return "开源新星闪耀"


def _detect_theme_tags(projects: list[dict[str, Any]]) -> list[str]:
    tag_counts: dict[str, int] = {}
    for p in projects:
        for tag in p.get("tech_tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    sorted_tags = sorted(tag_counts.items(), key=lambda x: -x[1])
    return [tag for tag, _ in sorted_tags[:4]] or ["开源", "GitHub", "热门", "新项目"]
