"""AI skills hotlist candidate collection for the console."""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import httpx

from src.utils.config import OUTPUT_DIR

SKILLHUB_URL = "https://skillhub.cn/"
CLAWHUB_API_URL = "https://clawhub.ai/api/v1/skills"
CLAWHUB_SKILLS_URL = "https://clawhub.ai/skills"
CACHE_DIR = OUTPUT_DIR / "cache" / "skills-hotlist"
CACHE_TTL_SECONDS = {
    "daily": 30 * 60,
    "weekly": 2 * 60 * 60,
    "monthly": 6 * 60 * 60,
}
CACHE_SCHEMA_VERSION = 1
SOURCE_LABELS = {
    "skillhub": "SkillHub",
    "clawhub": "ClawHub",
}


async def collect_candidates(
    time_window: str,
    limit: int = 30,
    force_refresh: bool = True,
) -> list[dict[str, Any]]:
    return (
        await collect_candidates_with_meta(
            time_window=time_window,
            limit=limit,
            force_refresh=force_refresh,
        )
    )["items"]


async def collect_candidates_with_meta(
    time_window: str,
    limit: int = 30,
    force_refresh: bool = True,
) -> dict[str, Any]:
    params = {"time_window": time_window, "limit": limit}
    cache_key = _cache_key(time_window, limit, params)
    cached = _read_cache(cache_key)
    if cached and not force_refresh and not _cache_expired(cached, time_window):
        return _cache_result(cached, "hit")

    source_results: list[dict[str, Any]] = []
    errors: list[str] = []
    headers = {"User-Agent": "github-video-skills-hotlist"}

    async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
        for source_name, fetcher in (
            ("skillhub", _fetch_skillhub),
            ("clawhub", _fetch_clawhub),
        ):
            try:
                items = await fetcher(client)
                for item in items:
                    source_error = item.pop("_source_error", "")
                    if source_error:
                        errors.append(f"{source_name}: {source_error}")
                source_results.extend(items)
            except Exception as exc:  # noqa: BLE001 - partial source failure should degrade, not fail the whole list
                errors.append(f"{source_name}: {exc}")

    if not source_results:
        if cached:
            stale = _cache_result(cached, "stale_error")
            stale["degraded"] = True
            stale["degraded_reason"] = "; ".join(errors) or "all sources failed"
            return stale
        raise ValueError(f"Skills 热榜数据源全部失败: {'; '.join(errors) or '无可用数据'}")

    merged = _merge_and_rank(source_results, limit=limit)
    result = {
        "items": merged,
        "cache_status": "fresh",
        "data_source": "skills_hotlist",
        "degraded": bool(errors),
        "degraded_reason": "; ".join(errors),
        "total_fetched": len(source_results),
        "total_eligible": len(merged),
        "rate_limit": "不适用",
    }
    _write_cache(cache_key, result)
    return result


async def _fetch_skillhub(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get(SKILLHUB_URL)
    response.raise_for_status()
    return _extract_skills_from_html(response.text, source="skillhub", base_url=SKILLHUB_URL)


async def _fetch_clawhub(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    api_error = ""
    try:
        payload = await _fetch_json(client, CLAWHUB_API_URL)
        items = _extract_skills_from_payload(payload, source="clawhub", base_url=CLAWHUB_SKILLS_URL)
        if items:
            return items
    except Exception as exc:  # noqa: BLE001 - page fallback keeps the source usable
        api_error = str(exc)

    response = await client.get(CLAWHUB_SKILLS_URL)
    response.raise_for_status()
    items = _extract_skills_from_html(response.text, source="clawhub", base_url=CLAWHUB_SKILLS_URL)
    if api_error:
        for item in items:
            item["_source_error"] = api_error
    return items


async def _fetch_json(client: httpx.AsyncClient, url: str) -> Any:
    response = await client.get(url)
    response.raise_for_status()
    return response.json()


def _extract_skills_from_payload(payload: Any, source: str, base_url: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = []
        for key in ("items", "skills", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                raw_items = value
                break
            if isinstance(value, dict):
                nested = _extract_skills_from_payload(value, source, base_url)
                if nested:
                    return nested
        if not raw_items:
            for value in payload.values():
                nested = _extract_skills_from_payload(value, source, base_url)
                if nested:
                    return nested
    else:
        raw_items = []

    items = []
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            continue
        item = _normalize_raw_skill(raw, source=source, base_url=base_url, source_rank=index)
        if item:
            items.append(item)
    return items


def _extract_skills_from_html(text: str, source: str, base_url: str) -> list[dict[str, Any]]:
    payload_items = []
    for payload in _json_payloads_from_html(text):
        payload_items.extend(_extract_skills_from_payload(payload, source=source, base_url=base_url))
    if payload_items:
        return payload_items

    card_items = _extract_card_like_skills(text, source=source, base_url=base_url)
    if card_items:
        return card_items

    title = _meta_content(text, "og:title") or _title(text)
    description = _meta_content(text, "description") or _meta_content(text, "og:description")
    if not title:
        return []
    return [_skill_item(
        name=_clean_text(title.replace("SkillHub-", "").replace("ClawHub", "").strip(" -")),
        description=_clean_text(description),
        source=source,
        source_url=base_url,
        source_rank=1,
        tags=["AI Skills"],
    )]


def _json_payloads_from_html(text: str) -> list[Any]:
    payloads = []
    for match in re.finditer(
        r'<script[^>]+(?:id="__NEXT_DATA__"|type="application/ld\+json")[^>]*>(.*?)</script>',
        text,
        flags=re.I | re.S,
    ):
        raw = html.unescape(match.group(1)).strip()
        try:
            payloads.append(json.loads(raw))
        except ValueError:
            continue
    return payloads


def _extract_card_like_skills(text: str, source: str, base_url: str) -> list[dict[str, Any]]:
    items = []
    pattern = re.compile(
        r'<a[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<body>.{0,2500}?)</a>',
        flags=re.I | re.S,
    )
    for index, match in enumerate(pattern.finditer(text), start=1):
        body = re.sub(r"<script.*?</script>|<style.*?</style>", "", match.group("body"), flags=re.I | re.S)
        chunks = [_clean_text(part) for part in re.findall(r">(.*?)<", body, flags=re.S)]
        chunks = [part for part in chunks if len(part) >= 2]
        if not chunks:
            continue
        name = chunks[0]
        description = next((part for part in chunks[1:] if len(part) >= 12), "")
        if not _looks_like_skill(name, description):
            continue
        items.append(_skill_item(
            name=name,
            description=description,
            source=source,
            source_url=urljoin(base_url, html.unescape(match.group("href"))),
            source_rank=index,
            tags=_tags_from_text(f"{name} {description}"),
        ))
    return items


def _normalize_raw_skill(raw: dict[str, Any], source: str, base_url: str, source_rank: int) -> dict[str, Any] | None:
    name = _first_text(raw, "name", "title", "displayName", "slug")
    description = _first_text(raw, "description", "summary", "shortDescription", "intro", "tagline")
    if not name:
        return None

    source_url = _first_text(raw, "url", "sourceUrl", "source_url", "homepage", "homepageUrl", "pageUrl")
    if not source_url:
        slug = _first_text(raw, "slug", "id")
        source_url = f"{base_url.rstrip('/')}/{slug}" if slug else base_url

    tags = _list_text(raw.get("tags") or raw.get("categories") or raw.get("keywords"))
    tags.extend(_tags_from_text(f"{name} {description}"))

    return _skill_item(
        name=name,
        description=description,
        source=source,
        source_url=urljoin(base_url, source_url),
        source_rank=source_rank,
        author=_first_text(raw, "author", "creator", "publisher", "owner"),
        tags=tags,
        stars=_first_int(raw, "stars", "starCount", "likes", "downloads", "installCount"),
        updated_at=_first_text(raw, "updatedAt", "updated_at", "createdAt", "created_at"),
    )


def _skill_item(
    name: str,
    description: str,
    source: str,
    source_url: str,
    source_rank: int,
    tags: list[str] | None = None,
    author: str = "",
    stars: int = 0,
    updated_at: str = "",
) -> dict[str, Any]:
    clean_name = _clean_text(name)[:120]
    clean_description = _clean_text(description)[:800]
    clean_tags = _dedupe([_clean_text(tag) for tag in (tags or []) if _clean_text(tag)])[:6]
    return {
        "id": f"{source}:{_slug(clean_name or source_url)}",
        "name": clean_name or "AI Skill",
        "full_name": clean_name or "AI Skill",
        "description": clean_description,
        "description_zh": _localized_description(clean_name, clean_description, clean_tags),
        "source": source,
        "source_label": SOURCE_LABELS.get(source, source),
        "source_url": _normalize_url(source_url),
        "repo_url": _normalize_url(source_url),
        "homepage": _normalize_url(source_url),
        "author": _clean_text(author),
        "topics": clean_tags,
        "language": SOURCE_LABELS.get(source, source),
        "stars": max(0, int(stars or 0)),
        "stars_today": 0,
        "daily_growth": f"来源：{SOURCE_LABELS.get(source, source)}",
        "data_source": "skills_hotlist",
        "updated_at": updated_at,
        "source_rank": source_rank,
    }


def _merge_and_rank(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        key = _dedupe_key(item)
        current = merged.get(key)
        if current is None:
            merged[key] = {**item, "sources": [item["source_label"]], "source_urls": [item["source_url"]]}
            continue
        current["sources"] = _dedupe([*current.get("sources", []), item["source_label"]])
        current["source_urls"] = _dedupe([*current.get("source_urls", []), item["source_url"]])
        if len(item.get("description") or "") > len(current.get("description") or ""):
            for field in ("description", "description_zh", "topics", "repo_url", "homepage", "source_url"):
                current[field] = item.get(field) or current.get(field)
        current["source_rank"] = min(int(current.get("source_rank") or 999), int(item.get("source_rank") or 999))

    ranked = []
    for item in merged.values():
        score, breakdown = _score(item)
        item["score"] = score
        item["score_breakdown"] = breakdown
        item["recommendation"] = _recommendation_reason(item)
        item["visual_potential"] = _visual_potential(item)
        item["risk"] = _risk_note(item)
        item["ranking_reason"] = _ranking_reason(item)
        ranked.append(item)

    ranked.sort(key=lambda item: (int(item.get("score") or 0), -int(item.get("source_rank") or 999)), reverse=True)
    for index, item in enumerate(ranked[:limit], start=1):
        item["rank"] = index
    return ranked[:limit]


def _score(item: dict[str, Any]) -> tuple[int, dict[str, int]]:
    source_rank = int(item.get("source_rank") or 999)
    rank_score = max(10, 45 - min(source_rank - 1, 20))
    multi_source = 20 if len(item.get("sources") or []) > 1 else 0
    metadata = 0
    if item.get("description"):
        metadata += 12
    if item.get("topics"):
        metadata += min(10, len(item.get("topics") or []) * 2)
    if item.get("homepage"):
        metadata += 5
    if item.get("author"):
        metadata += 3
    video = 15 if _has_video_scene(item) else 6
    popularity = min(10, int(item.get("stars") or 0) // 100)
    breakdown = {
        "source_rank": rank_score,
        "multi_source": multi_source,
        "metadata": metadata,
        "video_fit": video,
        "popularity": popularity,
    }
    return min(100, sum(breakdown.values())), breakdown


def _recommendation_reason(item: dict[str, Any]) -> str:
    topics = "、".join(item.get("topics") or []) or "AI 工作流"
    sources = " / ".join(item.get("sources") or [item.get("source_label") or "Skills 社区"])
    return f"{sources} 收录，适合做一期围绕 {topics} 的实用技能推荐。"


def _visual_potential(item: dict[str, Any]) -> str:
    text = _item_text(item)
    if any(word in text for word in ("browser", "web", "网页", "搜索", "crawl")):
        return "适合用浏览器操作画面展示效果。"
    if any(word in text for word in ("code", "coding", "repo", "github", "编程", "代码")):
        return "适合展示代码工作流前后对比。"
    if any(word in text for word in ("ppt", "slide", "image", "video", "design", "图片", "视频", "设计")):
        return "适合用成品画面做短视频看点。"
    return "适合用排行榜卡片和一句话场景说明呈现。"


def _risk_note(item: dict[str, Any]) -> str:
    if not item.get("description"):
        return "描述较少，发布前建议人工打开来源页确认用途。"
    if len(item.get("sources") or []) == 1:
        return "单一来源热度，建议结合人工判断。"
    return "多源出现，信息可信度较高。"


def _ranking_reason(item: dict[str, Any]) -> str:
    parts = item.get("score_breakdown") or {}
    return f"视频适配 {parts.get('video_fit', 0)} 分，多源加成 {parts.get('multi_source', 0)} 分。"


def _localized_description(name: str, description: str, tags: list[str]) -> str:
    text = f"{name} {description} {' '.join(tags)}".lower()
    if any(word in text for word in ("code", "coding", "github", "repo", "编程", "代码")):
        return f"{name} 是偏开发/代码工作流的 AI Skill，适合展示实际提效场景。"
    if any(word in text for word in ("browser", "crawl", "search", "网页", "搜索")):
        return f"{name} 聚焦网页或信息获取流程，适合做成操作演示。"
    if any(word in text for word in ("ppt", "slide", "image", "video", "design", "图片", "视频", "设计")):
        return f"{name} 偏内容创作和视觉生产，短视频展示空间比较大。"
    if description:
        return f"{name}：{description[:90]}"
    return f"{name} 是来自 Skills 社区的 AI 技能候选。"


def _has_video_scene(item: dict[str, Any]) -> bool:
    text = _item_text(item)
    return any(word in text for word in (
        "browser", "web", "crawl", "search", "code", "coding", "github", "ppt", "slide",
        "image", "video", "design", "网页", "搜索", "代码", "图片", "视频", "设计",
    ))


def _item_text(item: dict[str, Any]) -> str:
    return f"{item.get('name') or ''} {item.get('description') or ''} {' '.join(item.get('topics') or [])}".lower()


def _dedupe_key(item: dict[str, Any]) -> str:
    name_key = _slug(str(item.get("name") or ""))
    if name_key:
        return f"name:{name_key}"
    parsed = urlparse(str(item.get("source_url") or ""))
    if parsed.netloc and parsed.path.strip("/"):
        return f"url:{parsed.netloc.lower()}{parsed.path.rstrip('/').lower()}"
    return f"url:{str(item.get('source_url') or '')}"


def _normalize_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    query = parse_qs(parsed.query, keep_blank_values=True)
    clean_query = urlencode(
        [(key, val) for key, values in query.items() for val in values if not key.lower().startswith(("utm_", "spm"))]
    )
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", "", clean_query, ""))


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
        "data_source": result.get("data_source") or "skills_hotlist",
        "degraded": bool(result.get("degraded")),
        "degraded_reason": result.get("degraded_reason") or "",
        "total_fetched": result.get("total_fetched") or 0,
        "total_eligible": result.get("total_eligible") or 0,
        "rate_limit": "不适用",
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
        "cache_status": status,
        "data_source": payload.get("data_source") or "skills_hotlist",
        "degraded": bool(payload.get("degraded")),
        "degraded_reason": payload.get("degraded_reason") or "",
        "total_fetched": int(payload.get("total_fetched") or 0),
        "total_eligible": int(payload.get("total_eligible") or 0),
        "rate_limit": "不适用",
    }


def _meta_content(text: str, name: str) -> str:
    patterns = [
        rf'<meta[^>]+name="{re.escape(name)}"[^>]+content="([^"]*)"',
        rf'<meta[^>]+property="{re.escape(name)}"[^>]+content="([^"]*)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return _clean_text(match.group(1))
    return ""


def _title(text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.I | re.S)
    return _clean_text(match.group(1)) if match else ""


def _first_text(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("title") or value.get("login")
        if value is not None and str(value).strip():
            return _clean_text(str(value))
    return ""


def _first_int(raw: dict[str, Any], *keys: str) -> int:
    for key in keys:
        try:
            return int(raw.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return 0


def _list_text(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean_text(item.get("name") if isinstance(item, dict) else str(item)) for item in value]
    if isinstance(value, str):
        return [_clean_text(part) for part in re.split(r"[,，/ ]+", value) if part.strip()]
    return []


def _tags_from_text(text: str) -> list[str]:
    lowered = text.lower()
    mapping = {
        "coding": "编程",
        "code": "编程",
        "browser": "浏览器",
        "crawl": "网页抓取",
        "search": "搜索",
        "mcp": "MCP",
        "ppt": "PPT",
        "slide": "PPT",
        "image": "图片",
        "video": "视频",
        "design": "设计",
        "workflow": "工作流",
        "agent": "Agent",
    }
    return [label for keyword, label in mapping.items() if keyword in lowered]


def _looks_like_skill(name: str, description: str) -> bool:
    text = f"{name} {description}".lower()
    return len(name) <= 80 and any(word in text for word in ("skill", "agent", "ai", "mcp", "claude", "codex", "技能"))


def _clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _dedupe(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result
