"""Shared utilities for console jobs — route helpers, viewer heuristics, text utils, fact tokens."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from src.console import store


# ---------------------------------------------------------------------------
# 路由辅助
# ---------------------------------------------------------------------------

def _route_available(route: dict[str, Any]) -> bool:
    if "available" not in route:
        return bool(route.get("provider") and route.get("model") and route.get("enabled") and route.get("configured"))
    return bool(route.get("provider") and route.get("model") and route.get("available"))


def _route_skip_reason(route: dict[str, Any]) -> str:
    if not route.get("provider") or not route.get("model") or not route.get("enabled") or not route.get("configured"):
        return "未配置模型路由"
    last_test = str(route.get("last_test") or "")
    if last_test.startswith("连接失败"):
        return "模型供应商最近连接测试失败"
    return "模型供应商尚未通过连接测试"


# ---------------------------------------------------------------------------
# 项目特征提取
# ---------------------------------------------------------------------------

def _sanitize_feature_extract(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    core_problem = _short_text(str(value.get("core_problem") or ""), 24)
    core_action = _short_text(str(value.get("core_action") or ""), 80)
    quantified_benefit = _short_text(str(value.get("quantified_benefit") or ""), 48)
    if not core_problem or not core_action:
        return {}
    return {
        "core_problem": core_problem,
        "core_action": core_action,
        "quantified_benefit": quantified_benefit,
    }


def _fallback_feature_extract(project: dict[str, Any]) -> dict[str, str]:
    problem = _short_text(_viewer_pain(project), 15)
    action = _viewer_highlight(project)
    if not action:
        action = _viewer_outcome(project).rstrip("。")
    benefit = _quantified_benefit(project)
    return {
        "core_problem": problem or "判断成本太高",
        "core_action": _short_text(action, 80),
        "quantified_benefit": benefit,
    }


def _apply_feature_to_project_copy(project: dict[str, Any], feature: dict[str, str]) -> None:
    if feature.get("core_action") and not project.get("project_highlight"):
        project["project_highlight"] = feature["core_action"]
    if feature.get("core_problem") and not project.get("viewer_benefit"):
        project["viewer_benefit"] = f"解决{feature['core_problem']}"
    if feature.get("quantified_benefit") and not project.get("project_outcome"):
        project["project_outcome"] = feature["quantified_benefit"]


def _readme_excerpt(project: dict[str, Any]) -> str:
    return _short_text(str(project.get("readme") or project.get("readme_excerpt") or ""), 1800)


def _quantified_benefit(project: dict[str, Any]) -> str:
    text = " ".join([
        str(project.get("description") or ""),
        str(project.get("description_zh") or ""),
        str(project.get("readme") or project.get("readme_excerpt") or "")[:1000],
    ])
    match = re.search(r"([0-9]+(?:\.[0-9]+)?\s*(?:x|倍|%|分钟|秒|hours?|days?))", text, re.IGNORECASE)
    return _short_text(match.group(1), 48) if match else ""


# ---------------------------------------------------------------------------
# AI 调用记录
# ---------------------------------------------------------------------------

def _write_ai_raw_response(job_id: str, task: str, detail: dict[str, Any]) -> None:
    raw = str(detail.get("raw") or "")
    if not raw:
        return
    route = detail.get("route") or {}
    payload = {
        "task": task,
        "provider": route.get("provider_name") or route.get("provider") or "",
        "model": route.get("model") or "",
        "error": detail.get("error") or "",
        "raw": raw,
    }
    store.write_json(store.JOBS_DIR / job_id / f"ai-response-{task}.json", payload)


def _record_model_call(job_id: str, task: str, detail: dict[str, Any], status: str) -> None:
    route = detail.get("route") or {}
    store.append_model_call(job_id, {
        "task": task,
        "provider": route.get("provider_name") or route.get("provider") or "",
        "model": route.get("model") or "",
        "route": route,
        "status": status,
        "error": detail.get("error") or "",
        "usage": detail.get("usage") or {},
    })


# ---------------------------------------------------------------------------
# 观众视角启发式
# ---------------------------------------------------------------------------

def _viewer_pain(project: dict[str, Any]) -> str:
    text = _project_text(project)
    if _has_keyword(text, ("aircraft", "flight", "hardware", "raspberry", "sdr")):
        return "开源硬件难快速跑起来"
    if _has_keyword(text, ("ai", "agent", "llm", "model", "rag")):
        return "AI 难接进真实工作流"
    if _has_keyword(text, ("video", "image", "audio", "visual", "3d")):
        return "生成流程要来回切工具"
    if _has_keyword(text, ("react", "vue", "frontend", "ui", "css")):
        return "界面从零搭太慢"
    if _has_keyword(text, ("data", "database", "analytics", "sql")):
        return "数据分析前置流程太重"
    if _has_keyword(text, ("cli", "terminal", "shell", "developer")):
        return "重复命令吃掉效率"
    return "很难判断哪个值得花时间"


def _viewer_outcome(project: dict[str, Any]) -> str:
    text = _project_text(project)
    fallback = str(project.get("description_zh") or "")
    if not fallback or "描述较少" in fallback:
        fallback = "它的热度已经起来了，但真正值不值得用，要看 README 里的真实场景和上手成本。"
    if _has_keyword(text, ("aircraft", "flight", "hardware", "raspberry", "sdr")):
        return "它把技术玩具变成了更容易演示的真实场景。"
    if _has_keyword(text, ("ai", "agent", "llm", "model", "rag")):
        return "它不是再给你一个聊天窗口，而是把 AI 变成具体步骤。"
    if _has_keyword(text, ("video", "image", "audio", "visual", "3d")):
        return "它把多步视觉流程压缩成更容易复用的结果。"
    if _has_keyword(text, ("react", "vue", "frontend", "ui", "css")):
        return "它能更快做出可见效果，少在样式细节里试错。"
    if _has_keyword(text, ("data", "database", "analytics", "sql")):
        return "它把杂乱数据变成可继续分析的结构。"
    if _has_keyword(text, ("cli", "terminal", "shell", "developer")):
        return "它把重复操作收拢成更短路径。"
    return fallback


def _viewer_highlight(project: dict[str, Any]) -> str:
    for key in ("project_highlight", "viewer_benefit", "recommendation"):
        text = _viewer_safe_value(str(project.get(key) or ""))
        if text:
            return _short_text(text, 24).rstrip("。")
    return _viewer_outcome(project).rstrip("。")


def _viewer_safe_value(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    for prefix in ("高：", "中：", "低：", "高:", "中:", "低:"):
        text = text.removeprefix(prefix).strip()
    blocked = (
        "README 可展示",
        "README可展示",
        "仓库页做信息卡片",
        "终端截图可展示",
        "截图可展示",
        "画面潜力",
        "画面表达空间",
        "信息卡片",
        "可用 README、标签和仓库页",
        "适合做成中文短视频",
        "短视频切入点",
        "适合讲清楚",
        "项目用途、适合人群和实际价值",
    )
    compact = text.replace(" ", "")
    for phrase in blocked:
        if phrase in text or phrase.replace(" ", "") in compact:
            return ""
    return text


def _contains_producer_visual_jargon(text: str) -> bool:
    return bool(text.strip()) and not _viewer_safe_value(text)


def _contains_forbidden_narration(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    forbidden = (
        "如果你纠结",
        "如果你觉得",
        "如果你在找",
        "如果你卡在",
        "先看看它",
        "先看它",
        "很有价值",
        "值得关注",
        "适合开发者",
        "适合开源项目关注者",
    )
    return any(phrase.replace(" ", "") in compact for phrase in forbidden)


def _viewer_audience(project: dict[str, Any]) -> str:
    audience = str(project.get("audience") or "").strip()
    if audience:
        return _short_text(audience, 18)
    text = _project_text(project)
    if _has_keyword(text, ("ai", "agent", "llm", "model", "rag")):
        return "AI 开发者或自动化工作流用户"
    if _has_keyword(text, ("react", "vue", "frontend", "ui", "css")):
        return "前端开发者"
    if _has_keyword(text, ("data", "database", "analytics", "sql")):
        return "数据开发和分析用户"
    if _has_keyword(text, ("cli", "terminal", "shell", "developer")):
        return "经常写脚本和命令行的人"
    return "想快速筛开源工具的人"


# ---------------------------------------------------------------------------
# 事实相似度 / 增长夸大检测
# ---------------------------------------------------------------------------

def _normalize_fact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").lower())


def _fact_tokens(text: str) -> set[str]:
    """用中文 bigram + 英文单词做特征；对短中文也做 trigram 补充。"""
    if not text:
        return set()
    stopwords = {
        "github", "readme", "project", "项目", "工具", "用户",
        "一个", "这个", "那个", "它是", "它可以", "它能",
        "我们", "他们", "你是", "你可以", "的是",
    }
    tokens: set[str] = set()
    # 1) 英文单词：>=3 字符的英文/数字串
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9_-]{2,}", text):
        w = m.group(0).lower()
        if w not in stopwords:
            tokens.add(w)
    # 2) 中文 bigram：对连续中文字符做 2-char 滑窗
    for chinese_segment in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        # bigram
        for i in range(len(chinese_segment) - 1):
            bg = chinese_segment[i:i + 2]
            if bg not in stopwords:
                tokens.add(bg)
        # 对短中文（2-4字）把整个词也加进去（有时是有意义的词）
        if 2 <= len(chinese_segment) <= 4:
            if chinese_segment not in stopwords:
                tokens.add(chinese_segment)
    return tokens


def _fact_similarity(left: str, right: str) -> float:
    left_tokens = _fact_tokens(left)
    right_tokens = _fact_tokens(right)
    if left_tokens and right_tokens:
        left_compact = _normalize_fact_text(left)
        right_compact = _normalize_fact_text(right)

        # 1) 英文单词子串匹配：如果 left 里有英文单词，检查它是否作为子串出现在 right 中
        english_words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", left.lower())
        sub_hits = sum(1 for w in english_words if w and w in right_compact)
        english_hits_ratio = sub_hits / max(1, len(english_words)) if english_words else 0.0

        # 2) 覆盖度：left 的 token 有多少在 right 中出现（适合 core_action vs source 的关系）
        intersect = len(left_tokens & right_tokens)
        coverage = intersect / max(1, len(left_tokens))

        # 3) 中文关键词子串匹配：left 中 2-4 字的有意义词是否作为子串出现在 right 中
        #    （作为 bigram 覆盖率的补充，避免因语序差异导致低匹配）
        chinese_words = re.findall(r"[\u4e00-\u9fff]{2,4}", left)
        chinese_hits = sum(1 for w in chinese_words if w and w in right_compact)
        chinese_hits_ratio = chinese_hits / max(1, len(chinese_words)) if chinese_words else 0.0

        return max(coverage * 1.2, english_hits_ratio * 0.8, chinese_hits_ratio * 0.7)
    left_compact = _normalize_fact_text(left)
    right_compact = _normalize_fact_text(right)
    if not left_compact or not right_compact:
        return 0.0
    return SequenceMatcher(None, left_compact, right_compact).ratio()


def _contains_growth_overclaim(text: str) -> bool:
    lowered = re.sub(r"\s+", "", text.lower())
    if not lowered:
        return False
    blocked_phrases = (
        "新增star",
        "新增星标",
        "真实增长",
        "真实新增",
        "今天涨了",
        "今天新增",
        "单日涨了",
        "单日新增",
        "暴涨了",
        "今日上涨",
        "今日新增",
        "每日新增",
        "每日上涨",
    )
    if any(phrase in lowered for phrase in blocked_phrases):
        return "估算日均star" not in lowered and "热度估算" not in lowered
    return False


# ---------------------------------------------------------------------------
# 文本工具
# ---------------------------------------------------------------------------

def _short_text(text: str, limit: int) -> str:
    text = " ".join(text.split()).strip()
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].strip()
    return (clipped or text[:limit]).rstrip("，。,.") + "..."


def _clip_multiline(text: str, limit: int) -> str:
    text = "\n".join(line.rstrip() for line in str(text).splitlines()).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip("，。,. \n") + "..."


def _project_text(project: dict[str, Any]) -> str:
    return " ".join([
        str(project.get("description") or ""),
        str(project.get("description_zh") or ""),
        " ".join(str(topic) for topic in project.get("topics") or []),
        str(project.get("language") or ""),
    ]).lower()


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(re.search(rf"(^|[^a-z0-9]){re.escape(keyword)}([^a-z0-9]|$)", text) for keyword in keywords)