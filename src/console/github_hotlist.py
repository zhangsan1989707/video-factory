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

from src.scraper.github_trending import fetch_trending_html
from src.utils.config import OUTPUT_DIR

GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
GITHUB_REPO_API = "https://api.github.com/repos"
CACHE_DIR = OUTPUT_DIR / "cache" / "github-hotlist"
CACHE_TTL_SECONDS = {
    "daily": 30 * 60,
    "weekly": 2 * 60 * 60,
    "monthly": 6 * 60 * 60,
}
CACHE_SCHEMA_VERSION = 6
ESTIMATED_GROWTH_NOTE = "热度口径：估算日均 star 由当前总 stars 和仓库创建时间折算，不是真实新增 star。"
TRENDING_SOURCE = "trending"
SEARCH_API_SOURCE = "search_api"


def created_after(time_window: str) -> str:
    days = {"daily": 1, "weekly": 7, "monthly": 30}.get(time_window, 7)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.strftime("%Y-%m-%d")


async def collect_candidates(
    time_window: str,
    token: str = "",
    limit: int = 30,
    force_refresh: bool = True,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """Collect recent repositories using GitHub Trending (with Search API fallback)."""
    return (
        await collect_candidates_with_meta(
            time_window,
            token=token,
            limit=limit,
            force_refresh=force_refresh,
            language=language,
        )
    )["items"]


async def collect_candidates_with_meta(
    time_window: str,
    token: str = "",
    limit: int = 30,
    force_refresh: bool = True,
    enrich_with_llm: bool = True,
    llm_limit: int = 10,
    language: str | None = None,
) -> dict[str, Any]:
    """Collect recent repositories and return GitHub response metadata.

    Flow:
    1. Try to fetch GitHub Trending HTML (primary source for real "stars today")
    2. Optionally enrich each trending repo with full metadata via /repos/{full_name}
    3. If Trending fails, fall back to the GitHub Search API
    4. Apply scoring / filtering / LLM enrichment
    5. Return the final candidates sorted by score
    """
    params = {
        "time_window": time_window,
        "limit": limit,
        "language": (language or "").strip().lower(),
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

    source: str = TRENDING_SOURCE
    degraded = False
    degraded_reason = ""
    fetch_attempt: dict[str, Any] = {}

    try:
        fetch_attempt = await _fetch_via_trending(
            time_window=time_window,
            language=language,
            headers=headers,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 - 降级路径要吃掉所有异常
        degraded = True
        degraded_reason = str(exc)
        try:
            fetch_attempt = await _fetch_via_search_api(
                time_window=time_window,
                headers=headers,
                limit=limit,
            )
            source = SEARCH_API_SOURCE
        except Exception as exc2:  # noqa: BLE001
            # Search API may be rate-limited; if we have a cached payload, serve it
            # as stale so the caller (job) can still proceed.
            if cached and "rate limit" in str(exc2).lower():
                stale = _cache_result(cached, "stale_rate_limit")
                stale["degraded"] = True
                stale["degraded_reason"] = f"trending={exc}; search_api={exc2}"
                stale["data_source"] = SEARCH_API_SOURCE
                return stale
            raise ValueError(
                f"Trending 抓取失败且 Search API 兜底也失败: trending={exc}; search_api={exc2}"
            ) from exc2

    raw_items: list[dict[str, Any]] = fetch_attempt["raw_items"]
    rate_limit: str = fetch_attempt["rate_limit"]
    trending_meta: dict[str, dict[str, Any]] = fetch_attempt.get("trending_meta", {})

    # Step 2: Parallel fetch README for items missing description
    async def _fetch_readme_for_item(
        client: httpx.AsyncClient, item: dict[str, Any]
    ) -> dict[str, Any]:
        description = item.get("description") or ""
        readme = "" if description else await _fetch_readme_excerpt(client, headers, item)
        return {**item, "readme_excerpt": readme}

    async with httpx.AsyncClient(timeout=30.0) as client:
        enriched_items = await asyncio.gather(
            *[_fetch_readme_for_item(client, item) for item in raw_items]
        )

    # Step 3: Compute scores + filter
    scored = []
    for item in enriched_items:
        score = _content_score(item)
        is_ok, status_label = _candidate_status(item)
        scored.append({"item": item, "score": score, "is_ok": is_ok, "status": status_label})

    eligible = [s for s in scored if s["is_ok"]]
    eligible.sort(key=lambda s: s["score"], reverse=True)

    if not eligible:
        fallback = sorted(scored, key=lambda s: s["score"], reverse=True)[:limit]
        eligible = fallback

    # Step 4: Enrich top N projects with LLM (if enabled and available)
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
        full_name = item.get("full_name", "")
        item_language = item.get("language") or ""
        topics = item.get("topics") or []
        homepage = item.get("homepage") or ""

        trending_info = trending_meta.get(full_name, {})
        stars_today = int(trending_info.get("stars_today") or 0)

        # --- LLM enrichment (optional) ---
        description_zh = ""
        enrichment_source = "keyword"
        enriched = False

        if enrich_with_llm and score >= 30:
            try:
                from src.utils.llm_translate import enrich_description
                llm_total += 1
                result = await enrich_description(
                    name=name,
                    description=description,
                    readme_excerpt=readme_excerpt,
                    language=item_language,
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
            "full_name": full_name,
            "name": name,
            "owner": owner.get("login", "") if isinstance(owner, dict) else str(owner),
            "description": description,
            "description_zh": description_zh,
            "description_source": description_source,
            "enrichment_source": enrichment_source,
            "repo_description_missing": not bool(description),
            "readme_excerpt": readme_excerpt,
            "stars": item.get("stargazers_count", 0),
            "stars_today": stars_today,
            "data_source": source,
            "daily_growth": _estimated_daily_growth(item),
            "growth_note": ESTIMATED_GROWTH_NOTE,
            "forks": item.get("forks_count", 0),
            "issues": item.get("open_issues_count", 0),
            "language": item_language,
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
        "data_source": source,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "total_fetched": len(raw_items),
        "total_eligible": len(eligible),
        "llm_called": enrich_with_llm,
        "llm_total": llm_total,
        "llm_success": llm_success,
    }
    _write_cache(cache_key, result)
    return result


async def _fetch_via_trending(
    *,
    time_window: str,
    language: str | None,
    headers: dict[str, str],
    limit: int,
) -> dict[str, Any]:
    """Primary path: scrape GitHub Trending and enrich with /repos/{full_name}."""
    trending_repos = await fetch_trending_html(language=language, since=time_window)
    # Trending returns ~25 repos; cap to limit to keep the API enrichment bounded.
    selected = trending_repos[: max(limit, 25)]
    if not selected:
        raise ValueError("GitHub Trending returned an empty list")

    api_headers = {
        **headers,
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-video-console",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    raw_items: list[dict[str, Any]] = []
    rate_limit = "未检测"
    async with httpx.AsyncClient(timeout=30.0) as client:
        results = await asyncio.gather(
            *[_enrich_trending_repo(client, api_headers, repo) for repo in selected],
            return_exceptions=True,
        )
        for repo, outcome in zip(selected, results):
            if isinstance(outcome, BaseException):
                # If a single repo enrichment fails, still keep the trending data
                raw_items.append(_trending_repo_to_item(repo, None))
                continue
            raw_items.append(_trending_repo_to_item(repo, outcome))
            # Capture rate limit label from the first successful response
            if outcome and isinstance(outcome, dict) and outcome.get("__rate_limit"):
                rate_limit = outcome["__rate_limit"]

    return {
        "raw_items": raw_items,
        "rate_limit": rate_limit,
        "trending_meta": {repo["full_name"]: repo for repo in selected},
    }


async def _fetch_via_search_api(
    *,
    time_window: str,
    headers: dict[str, str],
    limit: int,
) -> dict[str, Any]:
    """Fallback path: GitHub Search API (existing behaviour, recreated for clarity)."""
    fetch_limit = min(max(limit * 2, 20), 100)
    params = {
        "q": f"created:>={created_after(time_window)} stars:>10 archived:false",
        "sort": "stars",
        "order": "desc",
        "per_page": fetch_limit,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(GITHUB_SEARCH_API, headers=headers, params=params)
        if response.status_code >= 400:
            if _is_rate_limited(response):
                raise ValueError(
                    f"GitHub API 限流: HTTP {response.status_code} {_github_error_message(response)}"
                )
            raise ValueError(_github_error_message(response))
        data = response.json()
        rate_limit = _rate_limit_label(response.headers)
        raw_items = data.get("items", [])

    return {
        "raw_items": raw_items,
        "rate_limit": rate_limit,
        "trending_meta": {},
    }


async def _enrich_trending_repo(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    trending_repo: dict[str, Any],
) -> dict[str, Any] | None:
    """Fetch full metadata for a single trending repo via /repos/{full_name}."""
    full_name = trending_repo.get("full_name") or ""
    if not full_name or "/" not in full_name:
        return None
    try:
        response = await client.get(f"{GITHUB_REPO_API}/{full_name}", headers=headers)
    except httpx.HTTPError:
        return None
    if response.status_code >= 400:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    payload["__rate_limit"] = _rate_limit_label(response.headers)
    return payload


def _trending_repo_to_item(
    trending_repo: dict[str, Any],
    enriched: dict[str, Any] | None,
) -> dict[str, Any]:
    """Map a trending repo (+ optional enriched payload) to a Search-API-shaped item."""
    full_name = trending_repo.get("full_name", "")
    owner_login, _, name = full_name.partition("/")
    if enriched:
        # Prefer the API payload; fill missing fields from trending.
        item = dict(enriched)
        item.pop("__rate_limit", None)
        item.setdefault("full_name", full_name)
        item.setdefault("name", name or item.get("name", ""))
        owner = item.get("owner")
        if not isinstance(owner, dict):
            item["owner"] = {"login": owner_login}
        item.setdefault("description", trending_repo.get("description") or "")
        item.setdefault("language", trending_repo.get("language") or "")
        item.setdefault("html_url", trending_repo.get("repo_url") or f"https://github.com/{full_name}")
    else:
        item = {
            "full_name": full_name,
            "name": name,
            "owner": {"login": owner_login},
            "description": trending_repo.get("description") or "",
            "language": trending_repo.get("language") or "",
            "html_url": trending_repo.get("repo_url") or f"https://github.com/{full_name}",
            "stargazers_count": 0,
            "forks_count": 0,
            "open_issues_count": 0,
            "topics": [],
            "homepage": "",
            "created_at": "",
            "updated_at": "",
        }
    return item


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
        "data_source": result.get("data_source") or TRENDING_SOURCE,
        "degraded": bool(result.get("degraded")),
        "degraded_reason": result.get("degraded_reason") or "",
        "total_fetched": result.get("total_fetched") or 0,
        "total_eligible": result.get("total_eligible") or 0,
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
        "data_source": payload.get("data_source") or TRENDING_SOURCE,
        "degraded": bool(payload.get("degraded")),
        "degraded_reason": payload.get("degraded_reason") or "",
        "total_fetched": int(payload.get("total_fetched") or 0),
        "total_eligible": int(payload.get("total_eligible") or 0),
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
