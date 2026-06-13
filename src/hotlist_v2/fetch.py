"""Fetch GitHub trending repos data for hotlist v2 video."""

from __future__ import annotations

import asyncio
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
    lang = item.get("language") or "其他"
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
    return f"近期候选项目，{lang} 实现，有实际使用价值"


async def _fetch_readme_excerpt(
    client: httpx.AsyncClient, headers: dict[str, str], item: dict[str, Any]
) -> str:
    """Fetch a short README excerpt for projects missing a description."""
    full_name = str(item.get("full_name") or "")
    if "/" not in full_name:
        return ""
    try:
        response = await client.get(f"https://api.github.com/repos/{full_name}/readme", headers=headers)
    except httpx.HTTPError:
        return ""
    if response.status_code >= 400:
        return ""
    try:
        payload = response.json()
    except ValueError:
        return ""
    import base64
    content = str(payload.get("content") or "")
    if not content:
        return ""
    try:
        readme = base64.b64decode(content).decode("utf-8", errors="replace")
    except ValueError:
        return ""
    # Extract the first meaningful paragraph
    in_code = False
    for raw_line in readme.splitlines()[:50]:
        line = raw_line.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not line or line.startswith(("!", "<", "|", "---", "#")):
            continue
        cleaned = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", line)
        cleaned = re.sub(r"[*_`>#]", "", cleaned).strip()
        if len(cleaned) >= 18:
            return cleaned[:900]
    return ""


def _score_project(item: dict[str, Any], readme: str = "") -> int:
    """Compute a project completeness score (0-100, base 0)."""
    try:
        from src.utils.llm_translate import compute_completeness_score
        return compute_completeness_score(
            stars=int(item.get("stargazers_count") or 0),
            description=item.get("description") or "",
            readme_excerpt=readme,
            language=item.get("language") or "",
            topics=item.get("topics") or [],
            homepage=item.get("homepage") or "",
        )
    except Exception:
        # Fallback: basic scoring (base 0, not 40)
        score = 0
        stars = int(item.get("stargazers_count") or 0)
        if stars >= 1000:
            score += 35
        elif stars >= 500:
            score += 25
        elif stars >= 200:
            score += 18
        elif stars >= 100:
            score += 12
        if item.get("description"):
            score += 25
        if item.get("language"):
            score += 8
        topics = item.get("topics") or []
        if topics:
            score += min(12, len(topics) * 3)
        if item.get("homepage"):
            score += 8
        return min(score, 100)


def _is_eligible(item: dict[str, Any], score: int, readme: str = "") -> tuple[bool, str]:
    """Hard elimination: very few stars AND no textual info.
    Returns (is_eligible, reason)."""
    stars = int(item.get("stargazers_count") or 0)
    has_text = bool(item.get("description") or readme)
    if stars < 100 and not has_text:
        return False, f"信息过少（stars={stars}，无描述）"
    if score < 30:
        return False, f"评分过低（{score}分，低于30分阈值）"
    return True, f"候选（{score}分）"


async def _enrich_project(
    name: str,
    description: str,
    readme_excerpt: str,
    language: str,
    topics: list[str],
    score: int,
    enable_llm: bool = True,
) -> dict[str, Any]:
    """Get a chinese description for this project.

    Priority: LLM translation (if configured) -> readme snippet -> keyword fallback.
    """
    # Try LLM enrichment if enabled and project passes quality bar
    if enable_llm and score >= 30:
        try:
            from src.utils.llm_translate import enrich_description
            result = await enrich_description(
                name=name,
                description=description,
                readme_excerpt=readme_excerpt,
                language=language,
                topics=topics,
                task="candidate_analysis",
            )
            if result.get("description_zh"):
                return {
                    "description_zh": result["description_zh"],
                    "source": result.get("source", "llm"),
                    "enriched": bool(result.get("enriched")),
                }
        except Exception:
            pass

    # Fallback: simple description from readme or keyword-based tagline
    desc = description.strip()
    if desc:
        return {"description_zh": desc, "source": "english_description", "enriched": False}
    if readme_excerpt.strip():
        snippet = readme_excerpt.strip()[:60]
        return {"description_zh": f"项目说明：{snippet}", "source": "readme_snippet", "enriched": False}
    return {"description_zh": "", "source": "missing", "enriched": False}


async def fetch_trending(
    time_window: str = "weekly",
    token: str = "",
    limit: int = 9,
    enrich_with_llm: bool = True,
) -> dict[str, Any]:
    """Fetch trending repos, filter for quality, then enrich descriptions.

    Flow:
    1. Fetch 2x limit from GitHub Search API (to have room for filtering)
    2. Parallel fetch README for items missing description
    3. Compute quality score (0-100, base 0)
    4. Filter out low-quality / cold projects
    5. Enrich top N projects with LLM translation (if configured)
    6. Return final list sorted by score
    """
    days = {"daily": 1, "weekly": 7, "monthly": 30}.get(time_window, 7)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-video-hotlist-v2",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    fetch_limit = min(max(limit * 2, 15), 100)
    params = {
        "q": f"created:>={_created_after(days)} stars:>10 archived:false",
        "sort": "stars",
        "order": "desc",
        "per_page": fetch_limit,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(GITHUB_SEARCH_API, headers=headers, params=params)
        if response.status_code >= 400:
            raise ValueError(f"GitHub API error: HTTP {response.status_code}")
        raw_items = response.json().get("items", [])

        # Parallel fetch README for items missing description
        async def _with_readme(item: dict[str, Any]) -> tuple[dict[str, Any], str]:
            description = item.get("description") or ""
            if description:
                return item, ""
            return item, await _fetch_readme_excerpt(client, headers, item)

        items_with_readme = await asyncio.gather(*[_with_readme(item) for item in raw_items])

    # Score + filter
    scored = []
    for item, readme in items_with_readme:
        score = _score_project(item, readme)
        is_ok, _reason = _is_eligible(item, score, readme)
        if is_ok:
            scored.append((item, readme, score))

    # Sort by score descending
    scored.sort(key=lambda x: x[2], reverse=True)

    # Fallback: if everything got filtered, keep top by score
    if not scored:
        scored = [(item, readme, _score_project(item, readme)) for item, readme in items_with_readme[:limit]]
        scored.sort(key=lambda x: x[2], reverse=True)

    # Enrich top N with LLM (sequential to stay within time budget)
    top_candidates = scored[:limit]
    enriched = []
    for item, readme, score in top_candidates:
        result = await _enrich_project(
            name=item.get("name", ""),
            description=item.get("description") or "",
            readme_excerpt=readme,
            language=item.get("language") or "",
            topics=item.get("topics") or [],
            score=score,
            enable_llm=enrich_with_llm,
        )
        enriched.append((item, readme, score, result))

    # Build final project list
    languages_seen: dict[str, str] = {}
    total_new_stars = 0
    projects = []

    for index, (item, readme, score, zh_result) in enumerate(enriched, start=1):
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

        description_en = item.get("description") or ""
        description_zh = zh_result.get("description_zh") or ""
        description_source = zh_result.get("source", "keyword")

        # tagline: short Chinese label for card display
        if description_zh:
            tagline = _localized_tagline(description_zh, topics) if not _has_chinese(description_en) else _localized_tagline(description_en, topics)
        else:
            tagline = _localized_tagline(description_en, topics)

        projects.append({
            "rank": index,
            "name": item.get("name", ""),
            "owner": owner,
            "owner_initial": owner[0].upper() if owner else "?",
            "tagline": tagline,
            "description": description_en,
            "description_zh": description_zh,
            "description_source": description_source,
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
            "score": score,
            "homepage": item.get("homepage") or "",
            "repo_url": item.get("html_url", ""),
            "readme": readme,
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
        "total_fetched": len(raw_items),
        "total_eligible": len(scored),
    }


def _has_chinese(text: str) -> bool:
    """Detect if a string contains Chinese characters."""
    for ch in text or "":
        if "\u4e00" <= ch <= "\u9fff":
            return True
    return False


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
