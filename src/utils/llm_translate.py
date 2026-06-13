"""LLM-based project description translation and enrichment.

Uses the configured model provider (via model_router) to:
1. Translate English project descriptions to Chinese
2. Summarize README excerpts into short descriptions
3. Generate brief descriptions from project name (when no other info)

All functions are non-blocking and gracefully degrade:
- If the model is unavailable, return empty string
- Caller decides what fallback to use

Simple in-memory caching prevents duplicate calls for identical text.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
from typing import Any


# === Cache ===

_cache_lock = threading.Lock()
_cache: dict[str, str] = {}


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _cache_get(text: str) -> str:
    with _cache_lock:
        return _cache.get(_cache_key(text), "")


def _cache_set(text: str, value: str) -> None:
    if not value:
        return
    with _cache_lock:
        _cache[_cache_key(text)] = value


# === Helpers ===

def _is_chinese(text: str) -> bool:
    """Heuristic: treat text as Chinese if it contains any CJK characters."""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            return True
    return False


# === Core: synchronous translation (model_router is sync) ===

def _translate_sync(text: str, task: str = "candidate_analysis") -> str:
    """Translate English text to Chinese via configured LLM provider.

    Returns empty string on failure / model unavailable.
    """
    cached = _cache_get(text)
    if cached:
        return cached

    try:
        from src.console.model_router import chat_text
    except Exception:
        return ""

    system = (
        "你是一个简洁的中英翻译助手。"
        "把用户提供的英文 GitHub 项目描述翻译成通顺、地道的中文，"
        "不要加任何解释、引号或前缀，"
        "只输出翻译后的中文句子。"
        "如果原文已经是中文或主要是中文，原样返回即可。"
    )
    prompt = f"请把下面的项目描述翻译成中文（不超过 80 个字）：\n\n{text}"

    try:
        content, _route = chat_text(task, system, prompt, max_tokens=300)
        result = str(content or "").strip().strip("“”\"'")
        if result:
            _cache_set(text, result)
        return result
    except Exception:
        return ""


def _summarize_readme_sync(readme_text: str, project_name: str = "", task: str = "candidate_analysis") -> str:
    """Summarize a README excerpt into a short Chinese description."""
    cache_key = f"readme:{project_name}:{readme_text[:200]}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        from src.console.model_router import chat_text
    except Exception:
        return ""

    system = (
        "你是一个简洁的信息提取助手。"
        "从 GitHub 项目的 README 中提取核心功能描述，"
        "用中文写一句不超过 60 个字的项目简介。"
        "不要加任何标题、项目名称、引号或前缀，"
        "只输出简介内容。"
    )
    snippet = readme_text[:1500] if len(readme_text) > 1500 else readme_text
    prompt = f"项目名：{project_name}\n\n以下是该项目的 README 内容：\n\n{snippet}\n\n请用一句中文（不超过 60 字）介绍这个项目解决了什么问题。"

    try:
        content, _route = chat_text(task, system, prompt, max_tokens=250)
        result = str(content or "").strip().strip("“”\"'")
        if result:
            _cache_set(cache_key, result)
        return result
    except Exception:
        return ""


def _generate_from_name_sync(name: str, language: str = "", topics: list[str] | None = None, task: str = "candidate_analysis") -> str:
    """Generate a conservative Chinese description from project name only.

    Used as a last-resort fallback when no description or README exists.
    """
    topics_str = ", ".join(topics) if topics else "无"
    cache_key = f"name:{name}:{language}:{topics_str}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        from src.console.model_router import chat_text
    except Exception:
        return ""

    system = (
        "你是一个保守的项目描述助手。"
        "当一个 GitHub 项目缺少描述时，"
        "你只能基于项目名称和语言做谨慎的推测，"
        "不要编造具体功能。"
        "用中文写一句不超过 40 个字的描述。"
    )
    prompt = (
        f"项目名称：{name}\n"
        f"主要语言：{language or '未知'}\n"
        f"标签：{topics_str}\n\n"
        "请基于以上信息，用一句中文（不超过 40 字）谨慎描述这个项目可能是什么。"
        "如果不确定，就写一个通用描述（例如'开源项目'），不要编造具体功能。"
    )

    try:
        content, _route = chat_text(task, system, prompt, max_tokens=200)
        result = str(content or "").strip().strip("“”\"'")
        if result:
            _cache_set(cache_key, result)
        return result
    except Exception:
        return ""


# === Async wrappers (for use in async pipelines) ===

async def translate_to_chinese(text: str, task: str = "candidate_analysis") -> str:
    """Async wrapper: translate text to Chinese via LLM."""
    if not text or not text.strip():
        return ""
    # Already Chinese? return as-is (or clean up)
    if _is_chinese(text):
        return text.strip()
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _translate_sync, text, task)
    except Exception:
        return ""


async def summarize_readme(readme_text: str, project_name: str = "", task: str = "candidate_analysis") -> str:
    """Async wrapper: summarize README excerpt into short Chinese description."""
    if not readme_text or not readme_text.strip():
        return ""
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _summarize_readme_sync, readme_text, project_name, task)
    except Exception:
        return ""


async def generate_from_name(
    name: str,
    language: str = "",
    topics: list[str] | None = None,
    task: str = "candidate_analysis",
) -> str:
    """Async wrapper: generate conservative Chinese description from name."""
    if not name:
        return ""
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _generate_from_name_sync, name, language, topics or [], task)
    except Exception:
        return ""


# === High-level: enrich project description via LLM ===

async def enrich_description(
    name: str,
    description: str = "",
    readme_excerpt: str = "",
    language: str = "",
    topics: list[str] | None = None,
    task: str = "candidate_analysis",
) -> dict[str, Any]:
    """Enrich a project with a Chinese description using the configured LLM.

    Priority chain:
    1. Description in Chinese -> use as-is
    2. Description in English -> translate to Chinese
    3. No description, but has README -> summarize README
    4. Nothing -> generate from name (conservative / may be empty)

    Returns a dict with:
      - description_zh: the final Chinese description string (may be empty)
      - source: "description_zh" | "translated" | "readme" | "name" | "missing"
      - enriched: True if LLM was successfully used
    """
    desc = (description or "").strip()
    readme = (readme_excerpt or "").strip()
    topic_list = list(topics or [])

    # Priority 1: description is already Chinese
    if desc and _is_chinese(desc):
        return {"description_zh": desc, "source": "description_zh", "enriched": False}

    # Priority 2: description is English -> translate
    if desc:
        translated = await translate_to_chinese(desc, task=task)
        if translated:
            return {"description_zh": translated, "source": "translated", "enriched": True}

    # Priority 3: no description, has README -> summarize
    if readme:
        summary = await summarize_readme(readme, name, task=task)
        if summary:
            return {"description_zh": summary, "source": "readme", "enriched": True}

    # Priority 4: nothing -> generate from name (conservative)
    generated = await generate_from_name(name, language, topic_list, task=task)
    if generated:
        return {"description_zh": generated, "source": "name", "enriched": True}

    return {"description_zh": "", "source": "missing", "enriched": False}


# === Scoring & Filtering ===

def compute_completeness_score(
    stars: int = 0,
    description: str = "",
    readme_excerpt: str = "",
    language: str = "",
    topics: list[str] | None = None,
    homepage: str = "",
) -> int:
    """Compute a project information completeness score, 0-100.

    - Base: 0 (previously was 40, which inflated low-quality projects)
    - Stars: weighted contribution (higher stars = more established)
    - Description: heavy bonus when present
    - README: bonus when excerpt available
    - Language: moderate bonus
    - Topics: bonus per topic
    - Homepage: bonus (demos / docs indicate quality)

    Intended use:
      - >= 70: high-quality project, good candidate for video
      - 50-69: acceptable, but could be better
      - 30-49: marginal, use with caution
      - < 30: low-quality, should be filtered out
    """
    score = 0

    # Stars: up to 40 points (more established projects are safer bets)
    if stars >= 5000:
        score += 40
    elif stars >= 1000:
        score += 35
    elif stars >= 500:
        score += 25
    elif stars >= 200:
        score += 18
    elif stars >= 100:
        score += 12
    elif stars >= 50:
        score += 6
    else:
        score += 0  # Very new / low-quality: no star bonus

    # Description: heavy bonus - critical for understanding the project
    if description and description.strip():
        score += 25
    elif readme_excerpt and readme_excerpt.strip():
        score += 15  # README is useful but not as concise as a proper description
    # If neither: massive penalty - we can't tell what the project does

    # Language: helps categorization
    if language:
        score += 8

    # Topics: up to 12 points (3 pts per topic, max 4)
    topic_list = list(topics or [])
    if topic_list:
        score += min(12, len(topic_list) * 3)

    # Homepage: indicates project has extra polish
    if homepage:
        score += 8

    return min(score, 100)


def is_eligible_candidate(
    stars: int = 0,
    description: str = "",
    readme_excerpt: str = "",
    language: str = "",
    topics: list[str] | None = None,
    homepage: str = "",
    min_score: int = 30,
) -> tuple[bool, str]:
    """Determine if a project is worth including in the hotlist.

    Returns (is_eligible, reason).

    Hard elimination rules (instant rejection):
    1. stars < 100 AND no description AND no README -> reject
    2. Overall score < min_score (default 30) -> reject
    """
    has_desc = bool(description and description.strip())
    has_readme = bool(readme_excerpt and readme_excerpt.strip())
    topic_list = list(topics or [])

    score = compute_completeness_score(
        stars=stars,
        description=description,
        readme_excerpt=readme_excerpt,
        language=language,
        topics=topic_list,
        homepage=homepage,
    )

    # Hard rule 1: too few stars AND no description AND no README
    if stars < 100 and not has_desc and not has_readme:
        return False, f"信息过少（stars={stars}，无描述）"

    # Hard rule 2: score too low
    if score < min_score:
        return False, f"评分过低（{score}分，低于{min_score}分阈值）"

    return True, f"候选（{score}分）"
