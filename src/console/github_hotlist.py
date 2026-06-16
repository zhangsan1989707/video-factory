"""GitHub hotlist candidate collection for the console."""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import httpx

from src.utils.config import OUTPUT_DIR

GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
CACHE_DIR = OUTPUT_DIR / "cache" / "github-hotlist"
CACHE_TTL_SECONDS = {
    "daily": 15 * 60,
    "weekly": 2 * 60 * 60,
    "monthly": 12 * 60 * 60,
}
CACHE_SCHEMA_VERSION = 5
ESTIMATED_GROWTH_NOTE = "热度口径：估算日均 star 由当前总 stars 和仓库创建时间折算，不是真实新增 star。"


def created_after(time_window: str) -> str:
    days = {"daily": 1, "weekly": 7, "monthly": 30}.get(time_window, 7)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.strftime("%Y-%m-%d")


async def collect_candidates(
    time_window: str,
    token: str = "",
    limit: int = 30,
    force_refresh: bool = True,
) -> list[dict[str, Any]]:
    """Collect recent repositories using GitHub Search API."""
    return (await collect_candidates_with_meta(time_window, token=token, limit=limit, force_refresh=force_refresh))["items"]


async def collect_candidates_with_meta(
    time_window: str,
    token: str = "",
    limit: int = 30,
    force_refresh: bool = True,
    enrich_with_llm: bool = True,
    llm_limit: int = 10,
) -> dict[str, Any]:
    """Collect recent repositories and return GitHub response metadata.

    Flow:
    1. Fetch up to 2x the requested limit from GitHub Search API
    2. Fetch README for items without description
    3. Compute completeness score for each project (0-100, base 0)
    4. Filter out low-quality / cold projects
    5. Enrich remaining top N with LLM translation (if enabled)
    6. Return the final candidates sorted by score
    """
    # Step 1: Fetch a larger pool from GitHub so we have room to filter
    fetch_limit = min(max(limit * 2, 20), 100)
    params = {
        "q": f"created:>={created_after(time_window)} stars:>10 archived:false",
        "sort": "stars",
        "order": "desc",
        "per_page": fetch_limit,
    }
    cache_key = _cache_key(time_window, limit, params)
    cached = _read_cache(cache_key)
    if cached and not force_refresh and not _cache_expired(cached, time_window):
        return _cache_result(cached, "hit")

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-video-console",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(GITHUB_SEARCH_API, headers=headers, params=params)
        if response.status_code >= 400:
            if cached and _is_rate_limited(response):
                return _cache_result(cached, "stale_rate_limit")
            raise ValueError(_github_error_message(response))
        data = response.json()
        rate_limit = _rate_limit_label(response.headers)

        # Step 2: Parallel fetch README for items missing description
        raw_items = data.get("items", [])

        async def _fetch_one(item: dict[str, Any]) -> dict[str, Any]:
            description = item.get("description") or ""
            readme = "" if description else await _fetch_readme_excerpt(client, headers, item)
            return {**item, "readme_excerpt": readme}

        enriched_items = await asyncio.gather(*[_fetch_one(item) for item in raw_items])

    # Step 3: Compute scores + filter
    scored = []
    for item in enriched_items:
        score = _content_score(item)
        is_ok, status_label = _candidate_status(item)
        scored.append({"item": item, "score": score, "is_ok": is_ok, "status": status_label})

    # Filter: keep only eligible items, then sort by score desc
    eligible = [s for s in scored if s["is_ok"]]
    eligible.sort(key=lambda s: s["score"], reverse=True)

    # If everything got filtered (shouldn't normally happen), fall back to highest-scored items
    if not eligible:
        fallback = sorted(scored, key=lambda s: s["score"], reverse=True)[:limit]
        eligible = fallback

    # Step 5: Enrich top N projects with LLM (if enabled and available)
    top_candidates = eligible[:limit]
    enriched_results = []
    llm_success = 0
    llm_total = 0

    for entry in top_candidates:
        item = entry["item"]
        score = entry["score"]
        owner = item.get("owner") or {}
        description = item.get("description") or ""
        readme_excerpt = item.get("readme_excerpt") or ""
        name = item.get("name", "")
        language = item.get("language") or ""
        topics = item.get("topics") or []
        homepage = item.get("homepage") or ""

        # --- LLM enrichment (optional) ---
        description_zh = ""
        enrichment_source = "keyword"
        enriched = False

        if enrich_with_llm and score >= 30:
            # Only enrich projects that already pass the basic quality bar
            try:
                from src.utils.llm_translate import enrich_description
                llm_total += 1
                result = await enrich_description(
                    name=name,
                    description=description,
                    readme_excerpt=readme_excerpt,
                    language=language,
                    topics=topics,
                    task="candidate_analysis",
                )
                description_zh = result.get("description_zh", "")
                enrichment_source = result.get("source", "keyword")
                if result.get("enriched"):
                    enriched = True
                    llm_success += 1
            except Exception:
                pass

        # Fallback: use keyword-based description (was already sufficient for display)
        if not description_zh:
            description_zh = _localized_description(item)
            enrichment_source = "keyword"

        description_source = (
            "description_zh" if enrichment_source == "description_zh"
            else "llm" if enriched
            else "github_description" if description
            else "readme" if readme_excerpt
            else "missing"
        )

        enriched_results.append({
            "rank": len(enriched_results) + 1,
            "full_name": item.get("full_name", ""),
            "name": name,
            "owner": owner.get("login", ""),
            "description": description,
            "description_zh": description_zh,
            "description_source": description_source,
            "enrichment_source": enrichment_source,
            "repo_description_missing": not bool(description),
            "readme_excerpt": readme_excerpt,
            "stars": item.get("stargazers_count", 0),
            "daily_growth": _estimated_daily_growth(item),
            "growth_note": ESTIMATED_GROWTH_NOTE,
            "forks": item.get("forks_count", 0),
            "issues": item.get("open_issues_count", 0),
            "language": language,
            "topics": topics,
            "homepage": homepage,
            "created_at": item.get("created_at", ""),
            "updated_at": item.get("updated_at", ""),
            "repo_url": item.get("html_url", ""),
            "score": score,
            "recommendation": _recommendation_reason(item),
            "risk": _risk_note(item),
            "audience": _audience(item),
            "visual_potential": _visual_potential(item),
        })

    result = {
        "items": enriched_results,
        "rate_limit": rate_limit,
        "cache_status": "fresh",
        "total_fetched": len(raw_items),
        "total_eligible": len(eligible),
        "llm_called": enrich_with_llm,
        "llm_total": llm_total,
        "llm_success": llm_success,
    }
    _write_cache(cache_key, result)
    return result


def _cache_key(time_window: str, limit: int, params: dict[str, Any]) -> str:
    payload = json.dumps(
        {"version": CACHE_SCHEMA_VERSION, "time_window": time_window, "limit": limit, "params": params},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(cache_key: str) -> Path:
    return CACHE_DIR / f"{cache_key}.json"


def _read_cache(cache_key: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(_cache_path(cache_key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) and isinstance(payload.get("items"), list) else None


def _write_cache(cache_key: str, result: dict[str, Any]) -> None:
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "items": result.get("items") or [],
        "rate_limit": result.get("rate_limit") or "未检测",
    }
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(cache_key).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _cache_expired(payload: dict[str, Any], time_window: str) -> bool:
    try:
        created = datetime.fromisoformat(str(payload.get("created_at") or ""))
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    ttl = CACHE_TTL_SECONDS.get(time_window, CACHE_TTL_SECONDS["weekly"])
    return datetime.now(timezone.utc) - created > timedelta(seconds=ttl)


def _cache_result(payload: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "items": payload.get("items") or [],
        "rate_limit": payload.get("rate_limit") or "未检测",
        "cache_status": status,
    }


async def _fetch_readme_excerpt(client: httpx.AsyncClient, headers: dict[str, str], item: dict[str, Any]) -> str:
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
        return _short_text(response.text, 900)
    content = str(payload.get("content") or "")
    if not content:
        return ""
    try:
        readme = base64.b64decode(content).decode("utf-8", errors="replace")
    except (ValueError, OSError):
        return ""
    return _short_text(readme, 900)


def _is_rate_limited(response: httpx.Response) -> bool:
    message = ""
    try:
        message = str((response.json() or {}).get("message") or "")
    except ValueError:
        pass
    return response.status_code in {403, 429} and (
        response.headers.get("x-ratelimit-remaining") == "0" or "rate limit" in message.lower()
    )


def _estimated_daily_growth(item: dict[str, Any]) -> str:
    stars = int(item.get("stargazers_count") or 0)
    created_at = str(item.get("created_at") or "")
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        age_days = max(1, (datetime.now(timezone.utc) - created).days)
    except ValueError:
        age_days = 30
    return f"估算日均 star 约 +{max(1, round(stars / age_days))}/天" if stars else "估算日均 star 暂无"


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
    """Compute project completeness score using shared logic.

    Uses llm_translate.compute_completeness_score (base 0, weighted).
    """
    try:
        from src.utils.llm_translate import compute_completeness_score
    except Exception:
        # Fallback: basic scoring
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
    return compute_completeness_score(
        stars=int(item.get("stargazers_count") or 0),
        description=item.get("description") or "",
        readme_excerpt=item.get("readme_excerpt") or "",
        language=item.get("language") or "",
        topics=item.get("topics") or [],
        homepage=item.get("homepage") or "",
    )


def _candidate_status(item: dict[str, Any]) -> tuple[bool, str]:
    """Check if a project passes the minimum quality bar.

    Hard elimination: very few stars AND no textual info.
    """
    try:
        from src.utils.llm_translate import is_eligible_candidate
    except Exception:
        return True, "候选"
    return is_eligible_candidate(
        stars=int(item.get("stargazers_count") or 0),
        description=item.get("description") or "",
        readme_excerpt=item.get("readme_excerpt") or "",
        language=item.get("language") or "",
        topics=item.get("topics") or [],
        homepage=item.get("homepage") or "",
    )


def _recommendation_reason(item: dict[str, Any]) -> str:
    language = item.get("language") or "其他"
    value = _localized_description(item)
    return f"{language} 项目。{value}"


def _risk_note(item: dict[str, Any]) -> str:
    description = item.get("description") or ""
    if not description:
        if item.get("readme_excerpt"):
            return "简介未填写，用途来自项目说明，建议先确认用途"
        return "简介未填写，建议先确认用途"
    if int(item.get("stargazers_count") or 0) < 50:
        return "热度偏低，建议确认是否真的适合入榜"
    return "暂无明显风险，仍需避免夸大项目能力"


def _audience(item: dict[str, Any]) -> str:
    text = _project_text(item)
    if _has_any_keyword(text, ("ppt", "powerpoint", "presentation", "slide", "slides")):
        return "经常做汇报和课件的人"
    if _has_any_keyword(text, ("figma", "design", "designer", "ui", "interface", "prototype")):
        return "设计师和前端开发者"
    if _has_any_keyword(text, ("claude", "agent-skill", "agent-skills")):
        return "Claude 和 Agent 用户"
    if _has_any_keyword(text, ("ai", "agent", "llm", "model")):
        return "AI 工具开发者"
    if _has_any_keyword(text, ("frontend", "react", "vue", "ui")):
        return "前端开发者"
    if _has_any_keyword(text, ("data", "database", "analytics")):
        return "数据开发者"
    return "开源项目关注者"


def _visual_potential(item: dict[str, Any]) -> str:
    if item.get("homepage"):
        return "高：有主页或演示页面可截图"
    topics = item.get("topics") or []
    if topics:
        return "中：可用仓库页做信息卡片"
    return "低：目前主要依赖仓库页信息"


def _has_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = text.lower()
    return any(
        keyword in normalized
        if len(keyword) >= 3
        else re.search(rf"(^|[^a-z0-9]){re.escape(keyword)}([^a-z0-9]|$)", normalized)
        for keyword in keywords
    )


def _project_text(item: dict[str, Any]) -> str:
    return " ".join([
        str(item.get("name") or ""),
        str(item.get("full_name") or ""),
        str(item.get("description") or ""),
        str(item.get("readme_excerpt") or "")[:1200],
        " ".join(str(topic) for topic in item.get("topics") or []),
        str(item.get("language") or ""),
    ]).lower()


def _localized_description(item: dict[str, Any]) -> str:
    description = item.get("description") or ""
    text = _project_text(item)
    if not description:
        intro = _readme_intro(str(item.get("readme_excerpt") or ""))
        if intro:
            return f"项目说明显示：{_short_text(intro, 54)}"
        return "简介未填写，建议先打开项目说明或官网确认用途"
    if _has_any_keyword(text, ("ppt", "powerpoint", "presentation", "slide", "slides")):
        return "用来生成或整理 PPT，把主题、结构和页面初稿更快搭出来"
    if _has_any_keyword(text, ("figma", "design", "designer", "ui", "interface", "prototype")):
        return "用于界面设计或设计稿生成，将自然语言想法转成可编辑的页面结构"
    if _has_any_keyword(text, ("claude", "agent-skill", "agent-skills")):
        return "给 Claude 或 Agent 扩展技能，把常用任务封装成可复用工作流"
    if _has_any_keyword(text, ("aircraft", "flight", "projector", "raspberry", "hardware", "sdr")):
        return "偏硬件、实时数据或空间展示，将复杂设备或数据流变成可操作场景"
    if _has_any_keyword(text, ("video", "image", "audio", "visual", "3d")):
        return "用于多媒体生成、处理或可视化，将内容产出变成可复用流程"
    if _has_any_keyword(text, ("ai", "agent", "llm", "model", "rag")):
        return "将 AI 能力接入具体任务，减少反复调试提示词的成本"
    if _has_any_keyword(text, ("react", "vue", "frontend", "ui", "css")):
        return "偏前端或界面工具，快速搭建可见界面和交互效果"
    if _has_any_keyword(text, ("data", "database", "analytics", "sql")):
        return "偏数据处理或分析工具，降低数据整理和查询成本"
    if _has_any_keyword(text, ("cli", "terminal", "shell", "developer")):
        return "偏开发者工具，将重复命令和工程流程简化"
    return f"仓库描述为“{_short_text(description, 54)}”，建议补充项目说明或官网证据"


def _readme_intro(readme: str) -> str:
    in_code = False
    for raw_line in readme.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not line or line.startswith(("!", "<", "|", "---")):
            continue
        if re.fullmatch(r"\[!\[[^\]]*]\([^)]+\)]\([^)]+\)", line):
            continue
        cleaned = re.sub(r"^#+\s*", "", line)
        cleaned = re.sub(r"^[-*]\s+", "", cleaned)
        cleaned = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", cleaned)
        cleaned = re.sub(r"[*_`>#]", "", cleaned).strip()
        if len(cleaned) >= 18:
            return cleaned
    return ""


def _short_text(text: str, limit: int) -> str:
    text = " ".join(text.split()).strip()
    return text if len(text) <= limit else text[:limit].rstrip()
