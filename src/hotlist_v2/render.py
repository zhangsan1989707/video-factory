"""End-to-end render pipeline for hotlist v2 video."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from html import escape
from difflib import SequenceMatcher
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from rich.console import Console

CST = timezone(timedelta(hours=8))

from src.hotlist_v2.fetch import fetch_trending, LANG_COLORS
from src.hotlist_v2.template import DEFAULT_STYLE, render_composition
from src.tts.edge_tts import generate_all_audio, get_audio_duration
from src.models import VideoScript, ScriptSegment

console = Console()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "hotlist-v2"

VALID_SCENE_COMPONENTS = {
    "broll-hero.big-type",
    "broll-charts.h-bar",
    "broll-hero.big-number",
    "aroll.concept-card",
    "broll-abstract.placeholder",
}

HYPERFRAMES_PRESETS = {
    "Swiss Pulse",
    "Velvet Standard",
    "Deconstructed",
    "Maximalist Type",
    "Data Drift",
    "Soft Signal",
    "Folk Frequency",
    "Shadow Cut",
}


async def render_hotlist_v2(
    output_path: Path | None = None,
    time_window: str = "weekly",
    token: str = "",
    limit: int = 10,
    durations: dict[str, int] | None = None,
    style: str = DEFAULT_STYLE,
    issue_number: int | None = None,
) -> Path:
    """Full pipeline: fetch → template → HyperFrames → TTS → final video.

    Args:
        output_path: Final video output path
        time_window: GitHub trending time window (daily/weekly/monthly)
        token: GitHub API token
        limit: Number of projects to include
        durations: Optional screen duration overrides
        issue_number: Optional issue number override (default: current ISO week)

    Returns:
        Path to final video
    """
    console.print("[bold cyan]Step 1/5:[/] Fetching GitHub trending data...")
    data = await fetch_trending(time_window, token=token, limit=limit)
    if issue_number is not None:
        data["issue"] = _resolve_issue_number(issue_number)
    return await render_hotlist_v2_from_data(data, output_path=output_path, durations=durations, style=style, limit=limit)


async def render_hotlist_v2_from_projects(
    projects: list[dict],
    output_path: Path | None = None,
    durations: dict[str, int] | None = None,
    style: str = DEFAULT_STYLE,
    narration_segments: list[dict] | None = None,
    stage_callback: Callable[[str, str], None] | None = None,
    limit: int = 10,
    issue_number: int | None = None,
) -> Path:
    """Render a hotlist v2 video from already selected console project data."""
    data = _data_from_projects(projects, issue_number=issue_number)
    return await render_hotlist_v2_from_data(
        data,
        output_path=output_path,
        durations=durations,
        style=style,
        narration_segments=narration_segments,
        stage_callback=stage_callback,
        limit=limit,
    )


def render_hotlist_v2_previews_from_projects(
    projects: list[dict],
    output_dir: Path,
    durations: dict[str, int] | None = None,
    style: str = DEFAULT_STYLE,
    limit: int = 10,
    issue_number: int | None = None,
) -> list[Path]:
    """Render static preview frames from the HyperFrames HTML template."""
    output_dir.mkdir(parents=True, exist_ok=True)
    data = _data_from_projects(projects, issue_number=issue_number)
    timeline = _timeline_context(data, durations, limit=limit)
    render_data = {**data, **timeline}
    html_dir = output_dir.parent / "hyperframes_preview_html"
    html_dir.mkdir(parents=True, exist_ok=True)

    previews = []
    base_html = html_dir / "composition.html"
    render_composition(render_data, base_html, durations, style=style)
    targets = [
        ("screen-intro", output_dir / "shot-01.png"),
        ("screen-list", output_dir / "shot-02.png"),
    ]
    for index, detail in enumerate(render_data.get("detail_screens") or [], start=1):
        targets.append((detail["screen_id"], output_dir / f"shot-{index + 2:02d}.png"))
    targets.append(("screen-hook", output_dir / f"shot-{len(targets) + 1:02d}.png"))
    previews.extend(_capture_html_screens(base_html, targets))
    return previews


async def render_hotlist_v2_from_data(
    data: dict,
    output_path: Path | None = None,
    durations: dict[str, int] | None = None,
    style: str = DEFAULT_STYLE,
    narration_segments: list[dict] | None = None,
    stage_callback: Callable[[str, str], None] | None = None,
    limit: int = 10,
) -> Path:
    """Render a hotlist v2 video from normalized template data."""
    out = output_path or OUTPUT_DIR / "final.mp4"
    work_dir = out.parent
    work_dir.mkdir(parents=True, exist_ok=True)
    timeline = _timeline_context(data, durations, narration_segments, limit=limit)
    console.print(f"  ✓ Found {data['total_projects']} projects, {data['total_languages']} languages")

    # Step 2: Generate TTS narration first so the visual timeline can follow real speech length.
    _emit_stage(stage_callback, "generating_tts", "开始生成 TTS 语音。")
    console.print("[bold cyan]Step 2/5:[/] Generating TTS narration...")
    script = _build_script_from_timeline(timeline)
    script_path = work_dir / "script.json"
    shutil.rmtree(work_dir / "audio", ignore_errors=True)
    await generate_all_audio(script, work_dir)
    audio_dir = work_dir / "audio"
    segment_durations = _audio_segment_durations(script, audio_dir)
    timeline = _timeline_context(data, durations, narration_segments, segment_durations=segment_durations, limit=limit)
    video_spec = _build_video_spec(data, timeline, style=style, work_dir=work_dir)
    _validate_video_spec(video_spec)
    spec_path = work_dir / "video-spec.json"
    spec_path.write_text(json.dumps(video_spec, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"  ✓ Video spec audit: {spec_path}")
    script = _build_script_from_spec(video_spec)
    script_path.write_text(json.dumps(script.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"  ✓ TTS audio: {audio_dir}")

    # Step 3: Render HTML composition
    _emit_stage(stage_callback, "composing_html", "开始生成 HTML 画面。")
    console.print("[bold cyan]Step 3/5:[/] Rendering HTML composition...")
    render_data = _render_data_from_spec(data, video_spec)
    data_path = work_dir / "trending-data.json"
    data_path.write_text(json.dumps(render_data, indent=2, ensure_ascii=False), encoding="utf-8")
    html_path = work_dir / "composition.html"
    render_composition(render_data, html_path, durations, style=style)
    console.print(f"  ✓ HTML composition: {html_path}")

    # Step 4: Render video with HyperFrames
    _emit_stage(stage_callback, "rendering_hyperframes", "开始使用 HyperFrames 渲染动画视频。")
    console.print("[bold cyan]Step 4/5:[/] Rendering video with HyperFrames...")
    raw_video = work_dir / "raw.mp4"
    _render_hyperframes(html_path, raw_video)
    console.print(f"  ✓ Raw video: {raw_video}")

    # Step 5: Mix TTS audio into video
    _emit_stage(stage_callback, "mixing_audio", "开始混合 TTS 音频。")
    console.print("[bold cyan]Step 5/5:[/] Mixing TTS audio...")
    _mix_audio(raw_video, script, audio_dir, out)
    console.print(f"  ✓ [bold green]Final video:[/] {out}")

    return out


def _emit_stage(stage_callback: Callable[[str, str], None] | None, stage: str, message: str) -> None:
    if stage_callback:
        stage_callback(stage, message)


def _resolve_issue_number(explicit: int | None = None) -> int:
    """Resolve the issue number: explicit > auto-increment from history > ISO week."""
    if explicit is not None and explicit > 0:
        return int(explicit)
    # Auto-increment: scan previous jobs for the highest issue number used
    last_issue = _last_issue_from_history()
    if last_issue is not None:
        return last_issue + 1
    # Fallback: current ISO week number
    return datetime.now(CST).isocalendar()[1]


def _last_issue_from_history() -> int | None:
    """Scan existing job records to find the highest issue number previously used."""
    try:
        from src.console.store import JOBS_DIR, read_json
        max_issue = None
        for task_path in JOBS_DIR.glob("*/task.json"):
            try:
                job = read_json(task_path, {})
                params = job.get("template_params") or {}
                issue = params.get("issue_number")
                if issue is not None and isinstance(issue, (int, float)) and int(issue) > 0:
                    candidate = int(issue)
                    if max_issue is None or candidate > max_issue:
                        max_issue = candidate
                # Also check the rendered data snapshot
                data_path = task_path.parent / "trending-data.json"
                if data_path.exists():
                    data = read_json(data_path, {})
                    issue_in_data = data.get("issue")
                    if issue_in_data is not None and isinstance(issue_in_data, (int, float)) and int(issue_in_data) > 0:
                        candidate = int(issue_in_data)
                        if max_issue is None or candidate > max_issue:
                            max_issue = candidate
            except Exception:
                continue
        return max_issue
    except Exception:
        return None


def _data_from_projects(projects: list[dict], issue_number: int | None = None) -> dict:
    """Normalize console selected projects to the hotlist v2 template shape."""
    normalized = []
    languages_seen: dict[str, str] = {}
    total_daily_growth = 0
    for index, item in enumerate(projects, start=1):
        stars = int(item.get("stars") or item.get("stargazers_count") or 0)
        language = str(item.get("language") or "")
        language_color = str(item.get("language_color") or _language_color(language))
        if language and language not in languages_seen:
            languages_seen[language] = language_color
        full_name = str(item.get("full_name") or item.get("name") or "")
        owner, name = _split_full_name(full_name)
        name = str(item.get("name") or name or full_name)
        topics = [str(topic) for topic in (item.get("topics") or [])[:8]]
        description = _project_description(item)
        purpose = _project_purpose(item, description)
        outcome = _project_outcome(item, description)
        hook = _project_hook(item, name)
        growth_num = _growth_number(str(item.get("daily_growth") or item.get("stars_delta") or ""))
        total_daily_growth += growth_num
        fact_card = _project_fact_card(item, name, description, purpose, outcome, hook, stars, growth_num)
        normalized.append({
            "rank": index,
            "name": name,
            "owner": owner,
            "owner_initial": owner[:1].upper() if owner else "?",
            "license": str(item.get("license") or item.get("license_name") or "开源协议待确认"),
            "tagline": str(item.get("tagline") or item.get("audience") or "开源热点"),
            "hook": fact_card["one_line_hook"],
            "description": description,
            "purpose": fact_card["core_action"],
            "outcome": fact_card["viewer_benefit"],
            "core_problem": fact_card["core_problem"],
            "core_action": fact_card["core_action"],
            "proof_point": fact_card["proof_point"],
            "viewer_benefit": fact_card["viewer_benefit"],
            "risk_note": fact_card["risk_note"],
            "visual_asset_label": fact_card["visual_asset_label"],
            "visual_asset_source": fact_card["visual_asset_source"],
            "language": language,
            "language_color": language_color,
            "stars": stars,
            "stars_display": _star_display(stars),
            "daily_growth": str(item.get("daily_growth") or item.get("stars_delta") or "热度上升"),
            "trend_label": _trend_label(item),
            "trend_icon": _trend_icon(growth_num),
            "trend_heat": _trend_heat(growth_num),
            "forks": _fork_display(item),
            "issues": int(item.get("issues") or item.get("open_issues_count") or 0),
            "topics": topics,
            "tech_tags": _tech_tags(topics, language),
            "audience_tags": _audience_tags(item, topics),
            "display_tags": _display_tags(item, topics, language),
            "preview_url": str(item.get("homepage") or ""),
            "star_history": _star_history(stars, index),
            "reason": fact_card["detail_reason"],
            "repo_url": str(item.get("repo_url") or item.get("html_url") or ""),
        })
    _dedupe_project_copy(normalized)

    now = datetime.now(CST)
    resolved_issue = _resolve_issue_number(issue_number)
    languages = [{"name": name, "color": color} for name, color in list(languages_seen.items())[:6]]
    return {
        "date": f"{now.year} 年 {now.month} 月 {now.day} 日",
        "issue": resolved_issue,
        "total_projects": len(normalized),
        "total_languages": len(languages),
        "total_new_stars": _star_display(total_daily_growth) if total_daily_growth else "待确认",
        "languages": languages,
        "theme_highlight": _theme_highlight(normalized),
        "theme_tags": _theme_tags(normalized),
        "projects": normalized,
    }


def _split_full_name(full_name: str) -> tuple[str, str]:
    if "/" not in full_name:
        return "", full_name
    owner, name = full_name.split("/", 1)
    return owner, name


def _star_display(stars: int) -> str:
    if stars >= 10000:
        return f"{stars / 10000:.1f} 万"
    if stars >= 1000:
        return f"{stars / 1000:.1f}k"
    return str(stars)


def _fork_display(item: dict) -> str:
    for key in ("forks", "forks_count"):
        if key in item and item.get(key) is not None:
            try:
                return f"{int(item.get(key) or 0):,}"
            except (TypeError, ValueError):
                return str(item.get(key))
    return "未知"


def _project_description(item: dict) -> str:
    raw_description_zh = " ".join(str(item.get("description_zh") or "").split()).strip()
    description_zh = _clean_viewer_text(raw_description_zh)
    description = _clean_viewer_text(str(item.get("description") or ""))
    # Clean up legacy prefix from older pipelines
    if not description_zh and raw_description_zh.startswith("README 显示："):
        description_zh = raw_description_zh.removeprefix("README 显示：").strip(" 。")
    if not description_zh and raw_description_zh.startswith("项目说明："):
        description_zh = raw_description_zh.removeprefix("项目说明：").strip(" 。")
    readme_intro = _readme_intro(str(item.get("readme") or item.get("readme_excerpt") or ""))
    if not description_zh and not description and readme_intro:
        return _ensure_sentence(readme_intro)
    return description_zh or description or "简介待补充"


def _project_purpose(item: dict, description: str) -> str:
    feature = item.get("feature_extract") if isinstance(item.get("feature_extract"), dict) else {}
    if feature.get("core_action"):
        return _ensure_sentence(str(feature.get("core_action")))
    for key in ("project_highlight", "viewer_benefit"):
        text = _clean_viewer_text(str(item.get(key) or ""))
        if text:
            return text
    return description


def _project_outcome(item: dict, description: str) -> str:
    feature = item.get("feature_extract") if isinstance(item.get("feature_extract"), dict) else {}
    if feature.get("quantified_benefit"):
        return _ensure_sentence(str(feature.get("quantified_benefit")))
    for key in ("project_outcome", "implementation_effect", "outcome"):
        text = _clean_viewer_text(str(item.get(key) or ""))
        if text:
            return _ensure_sentence(text)

    text = _project_text(item)
    if _has_keyword(text, ("ppt", "powerpoint", "presentation", "slide", "slides")):
        return "把需求整理成 PPT 大纲、页面结构和备注文案，少从空白页开始。"
    if _has_keyword(text, ("figma", "design", "designer", "ui", "interface", "prototype")):
        return "把界面想法转成可编辑的设计或前端结构，减少反复描述和手工搭页面。"
    if _has_keyword(text, ("claude", "agent-skill", "agent-skills", "skill")):
        return "把常用任务封装成 Claude 能调用的技能，少写重复提示词和流程说明。"
    if _has_keyword(text, ("code", "coding", "developer", "devtool", "github")):
        return "把开发中的检索、生成或协作步骤变短，适合直接嵌进工程流程。"
    if _has_keyword(text, ("ai", "agent", "llm", "model", "rag")):
        return _specific_ai_outcome(item, description)
    if _has_keyword(text, ("video", "image", "audio", "visual", "3d")):
        return "减少内容生成、处理或可视化时的来回切换。"
    if _has_keyword(text, ("react", "vue", "frontend", "ui", "css")):
        return "更快做出可见界面，降低样式和交互试错成本。"
    if _has_keyword(text, ("data", "database", "analytics", "sql")):
        return "把数据整理、查询或分析流程变得更直接。"
    if _has_keyword(text, ("cli", "terminal", "shell", "developer")):
        return "把重复命令和工程操作收拢成更短路径。"
    return _ensure_sentence(description)


def _project_hook(item: dict, name: str) -> str:
    feature = item.get("feature_extract") if isinstance(item.get("feature_extract"), dict) else {}
    if feature.get("core_problem"):
        return _short_text(str(feature.get("core_problem")), 15)
    for key in ("hook", "project_hook", "headline"):
        text = _clean_viewer_text(str(item.get(key) or ""))
        if text:
            return _short_text(text, 15)

    text = _project_text(item)
    name_text = name.lower()
    combined = f"{name_text} {text}"
    if _has_keyword(combined, ("ppt", "powerpoint", "presentation", "slide", "slides")):
        return "一句话生成 PPT"
    if _has_keyword(combined, ("figma", "design", "designer", "ui", "interface", "prototype")):
        return "自然语言做设计"
    if _has_keyword(combined, ("claude", "agent-skill", "agent-skills", "skill")):
        return "把任务变成技能"
    if _has_keyword(combined, ("cli", "terminal", "shell")):
        return "命令行少走弯路"
    if _has_keyword(combined, ("video", "image", "audio", "visual", "3d")):
        return "更快生成内容"
    if _has_keyword(combined, ("data", "database", "analytics", "sql")):
        return "数据处理更直接"
    if _has_keyword(combined, ("ai", "agent", "llm", "model", "rag")):
        return "AI 工作流提速"
    return "值得关注的新项目"


def _specific_ai_outcome(item: dict, description: str) -> str:
    text = description.strip("。") or str(item.get("name") or "这个项目")
    if len(text) > 34:
        text = text[:34].rstrip()
    return f"围绕“{text}”做具体自动化，避免只停留在聊天式试用。"


def _project_fact_card(
    item: dict,
    name: str,
    description: str,
    purpose: str,
    outcome: str,
    hook: str,
    stars: int,
    growth_num: int,
) -> dict[str, str]:
    feature = item.get("feature_extract") if isinstance(item.get("feature_extract"), dict) else {}
    core_problem = _first_clean(
        str(feature.get("core_problem") or ""),
        str(item.get("core_problem") or ""),
        str(item.get("viewer_pain") or ""),
    ) or _infer_core_problem(item)
    core_action = _first_clean(
        str(feature.get("core_action") or ""),
        str(item.get("project_highlight") or ""),
        purpose,
        description,
    ) or _fallback_core_action(item, name)
    viewer_benefit = _first_clean(
        str(feature.get("quantified_benefit") or ""),
        str(item.get("viewer_benefit") or ""),
        outcome,
    ) or _fallback_viewer_benefit(item)
    proof_point = _proof_point(item, stars, growth_num)
    risk_note = _first_clean(str(item.get("risk") or ""))
    if not risk_note and item.get("repo_description_missing"):
        if item.get("readme") or item.get("readme_excerpt"):
            risk_note = "简介未填写，用途来自项目说明，建议先确认用途"
        else:
            risk_note = "简介未填写，建议先确认用途"
    risk_note = risk_note or "效果建议实测后再判断"
    one_line_hook = _first_clean(hook, core_problem) or _short_text(name, 15)
    visual_label, visual_source = _visual_asset(item)
    detail_reason = _detail_reason(core_action, viewer_benefit, proof_point)
    return {
        "core_problem": _short_text(core_problem, 24),
        "core_action": _ensure_sentence(_short_text(core_action, 86)),
        "viewer_benefit": _ensure_sentence(_short_text(viewer_benefit, 72)),
        "proof_point": _ensure_sentence(_short_text(proof_point, 86)),
        "risk_note": _ensure_sentence(_short_text(risk_note, 70)),
        "one_line_hook": _short_text(one_line_hook, 15),
        "visual_asset_label": visual_label,
        "visual_asset_source": visual_source,
        "detail_reason": detail_reason,
    }


def _first_clean(*values: str) -> str:
    for value in values:
        text = _clean_viewer_text(value)
        if text and not _is_weak_copy(text):
            return text
    return ""


def _is_weak_copy(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    weak_phrases = (
        "近期热度上升",
        "值得关注",
        "值得试",
        "重点看",
        "具体用途",
        "实现效果",
        "上手成本",
        "开源热点",
        "开源项目",
        "项目描述较少",
        "需要打开仓库确认",
        "需要补充README",
        "需要补充一个真实使用场景",
        "缺少项目描述",
        "建议跳过",
        "人工确认后再入榜",
    )
    return any(phrase in text or phrase.replace(" ", "") in compact for phrase in weak_phrases)


def _infer_core_problem(item: dict) -> str:
    text = _project_text(item)
    if _has_keyword(text, ("ppt", "powerpoint", "presentation", "slide", "slides")):
        return "PPT 从空白页开始"
    if _has_keyword(text, ("figma", "design", "designer", "ui", "interface", "prototype")):
        return "设计稿来回描述"
    if _has_keyword(text, ("claude", "agent-skill", "agent-skills", "skill")):
        return "重复提示词太多"
    if _has_keyword(text, ("cli", "terminal", "shell")):
        return "终端流程太碎"
    if _has_keyword(text, ("data", "database", "analytics", "sql")):
        return "数据整理太慢"
    if _has_keyword(text, ("video", "image", "audio", "visual", "3d")):
        return "内容处理步骤多"
    if _has_keyword(text, ("ai", "agent", "llm", "model", "rag")):
        return "AI 落地任务不清"
    return "功能证据待补齐"


def _fallback_core_action(item: dict, name: str) -> str:
    description = _clean_viewer_text(str(item.get("description") or ""))
    if description:
        return f"{name} 的仓库描述指向：{description}"
    return f"{name} 需要补充项目说明"


def _fallback_viewer_benefit(item: dict) -> str:
    audience = _clean_viewer_text(str(item.get("audience") or ""))
    if audience:
        return f"适合{audience}先判断是否值得试用"
    return "适合先收藏，等补足功能证据后再决定是否实测"


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


def _proof_point(item: dict, stars: int, growth_num: int) -> str:
    proof = _first_clean(str(item.get("proof_point") or ""), str(item.get("recommendation") or ""))
    if proof:
        return proof
    topics = [str(topic) for topic in item.get("topics") or [] if str(topic).strip()]
    parts = []
    if stars:
        parts.append(f"当前 {_star_display(stars)} stars")
    if growth_num:
        parts.append(f"估算日均 star 约 +{_compact_number(growth_num)}")
    if topics:
        parts.append("标签：" + " / ".join(topics[:3]))
    if item.get("homepage"):
        parts.append("有官网或演示页可核对")
    return "；".join(parts) or "信息待补充"


def _visual_asset(item: dict) -> tuple[str, str]:
    homepage = str(item.get("homepage") or "").strip()
    if homepage:
        return "官网 / 演示页", homepage
    for key in ("readme_image_url", "image_url", "screenshot_url"):
        source = str(item.get(key) or "").strip()
        if source:
            return "项目截图", source
    repo_url = str(item.get("repo_url") or item.get("html_url") or "").strip()
    if repo_url:
        return "项目主页", repo_url
    return "截图待补充", ""


def _detail_reason(core_action: str, viewer_benefit: str, proof_point: str) -> str:
    action = _ensure_sentence(core_action).rstrip("。")
    benefit = _ensure_sentence(viewer_benefit).rstrip("。")
    proof = _ensure_sentence(proof_point).rstrip("。")
    return f"{action}；{benefit}。证据：{proof}。"


def _project_reason(item: dict, purpose: str, outcome: str, stars: int) -> str:
    ranking = _clean_viewer_text(str(item.get("ranking_reason") or ""))
    benefit = _clean_viewer_text(str(item.get("viewer_benefit") or ""))
    highlight = _clean_viewer_text(str(item.get("project_highlight") or ""))
    parts = []
    if highlight and highlight != purpose:
        parts.append(f"功能上，{highlight.rstrip('。')}。")
    else:
        parts.append(f"功能上，{purpose.rstrip('。')}。")
    parts.append(f"效果上，{outcome.rstrip('。')}。")
    if benefit and benefit not in " ".join(parts):
        parts.append(f"价值上，{benefit.rstrip('。')}。")
    if ranking:
        parts.append(ranking.rstrip("。") + "。")
    elif stars:
        parts.append(f"{_star_display(stars)} 个 Star 说明它已经获得开发者关注。")
    return "".join(parts)


def _clean_viewer_text(text: str) -> str:
    text = " ".join(text.split()).strip()
    if not text:
        return ""
    blocked = (
        "适合做成中文短视频",
        "短视频切入点",
        "适合讲清楚",
        "画面表达空间",
        "场景感讲清楚",
        "项目用途、适合人群和实际价值",
        "README",
        "仓库页做信息卡片",
        "近期热度上升",
        "值得关注",
        "值得试",
        "重点看",
        "具体用途",
        "实现效果",
        "上手成本",
        "项目描述较少",
    )
    compact = text.replace(" ", "")
    if any(phrase in text or phrase.replace(" ", "") in compact for phrase in blocked):
        return ""
    return text


def _project_text(item: dict) -> str:
    return " ".join([
        str(item.get("name") or ""),
        str(item.get("full_name") or ""),
        str(item.get("description") or ""),
        str(item.get("description_zh") or ""),
        str(item.get("readme") or item.get("readme_excerpt") or "")[:1200],
        " ".join(str(topic) for topic in item.get("topics") or []),
        str(item.get("language") or ""),
    ]).lower()


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(
        keyword in lowered if len(keyword) >= 3 else re.search(rf"(^|[^a-z0-9]){re.escape(keyword)}([^a-z0-9]|$)", lowered)
        for keyword in keywords
    )


def _ensure_sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return "项目描述较少，需要打开仓库确认具体用途。"
    return text if text.endswith(("。", "！", "？", ".", "!", "?")) else text + "。"


def _short_text(text: str, limit: int) -> str:
    text = " ".join(text.split()).strip("。")
    return text if len(text) <= limit else text[:limit].rstrip()


def _trend_label(item: dict) -> str:
    explicit = _clean_viewer_text(str(item.get("trend_label") or ""))
    if explicit:
        return explicit

    growth_text = str(item.get("daily_growth") or item.get("stars_delta") or "").strip()
    growth_num = _growth_number(growth_text)
    history = [int(v) for v in item.get("star_history") or [] if isinstance(v, int | float)]
    if len(history) >= 28:
        recent = sum(history[-14:]) / 14
        previous = sum(history[-28:-14]) / 14
        ratio = recent / previous if previous else 1
    else:
        ratio = 1.25 if growth_num >= 100 else 1.0

    if growth_num > 300 or ratio >= 1.6:
        word = "爆发"
        icon = "🔥🔥" if growth_num > 300 else "🔥"
    elif growth_num >= 150:
        word = "加速"
        icon = "🔥"
    elif growth_num > 0 or ratio >= 0.9:
        word = "稳步上升"
        icon = "📈"
    else:
        word = "降温"
        icon = "📉"

    if growth_num:
        return f"{icon} 估算 +{_compact_number(growth_num)}/天 {word}"
    if growth_text:
        return f"{icon} {growth_text} {word}"
    return f"{icon} 热度{word}"


def _trend_icon(growth_num: int) -> str:
    if growth_num > 300:
        return "🔥🔥"
    if growth_num >= 150:
        return "🔥"
    return "📈"


def _trend_heat(growth_num: int) -> str:
    if growth_num > 300:
        return "hot"
    if growth_num >= 150:
        return "warm"
    return "steady"


def _growth_number(text: str) -> int:
    match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*([kK千万]?)", text.replace(",", ""))
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit in {"k", "千"}:
        value *= 1000
    elif unit == "万":
        value *= 10000
    return max(0, int(value))


def _compact_number(value: int) -> str:
    if value >= 10000:
        return f"{value / 10000:.1f}万"
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)


def _audience_tags(item: dict, topics: list[str]) -> list[str]:
    text = _project_text(item)
    tags: list[str] = []
    rules = [
        (("ppt", "powerpoint", "presentation", "slide", "slides"), "#PPT自动化"),
        (("figma", "design", "designer", "ui", "interface", "prototype"), "#AI设计"),
        (("claude", "agent-skill", "agent-skills"), "#Claude插件"),
        (("agent", "workflow", "automation"), "#AI工作流"),
        (("frontend", "react", "vue", "css"), "#前端辅助"),
        (("cli", "terminal", "shell"), "#开发工具"),
        (("data", "database", "analytics", "sql"), "#数据处理"),
        (("video", "image", "audio", "visual"), "#内容创作"),
    ]
    for keywords, tag in rules:
        if len(tags) >= 3:
            break
        if tag not in tags and _has_keyword(text, keywords):
            tags.append(tag)
    for topic in topics:
        if len(tags) >= 3:
            break
        topic_text = topic.strip()
        if topic_text and len(topic_text) <= 16:
            tag = _topic_audience_tag(topic_text)
            if tag not in tags:
                tags.append(tag)
    return tags[:3] or ["#开源项目", "#效率工具"]


def _topic_audience_tag(topic: str) -> str:
    mapping = {
        "ai": "#AI工具",
        "llm": "#大模型",
        "ppt": "#PPT自动化",
        "workflow": "#工作流",
        "design": "#AI设计",
        "claude": "#Claude插件",
        "frontend": "#前端辅助",
    }
    return mapping.get(topic.lower(), f"#{topic}")


def _dedupe_project_copy(projects: list[dict]) -> None:
    seen_outcomes: list[str] = []
    for project in projects:
        outcome = str(project.get("outcome") or "")
        if any(_copy_similarity(outcome, seen) > 0.8 for seen in seen_outcomes):
            hook = str(project.get("hook") or project.get("name") or "这个项目")
            description = str(project.get("description") or "").rstrip("。")
            if len(description) > 30:
                description = description[:30].rstrip()
            project["outcome"] = _ensure_sentence(f"更具体地说，{hook}：{description or '把项目主题做成可直接使用的流程'}")
            project["reason"] = _project_reason(project, str(project.get("purpose") or ""), str(project.get("outcome") or ""), int(project.get("stars") or 0))
        seen_outcomes.append(str(project.get("outcome") or ""))


def _copy_similarity(left: str, right: str) -> float:
    left = re.sub(r"\s+", "", left)
    right = re.sub(r"\s+", "", right)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _language_color(language: str) -> str:
    return LANG_COLORS.get(language, "#8899bb")


def _tech_tags(topics: list[str], language: str) -> list[str]:
    tags = [language] if language else []
    for topic in topics:
        if topic and topic not in tags:
            tags.append(topic)
    return tags[:4]


def _display_tags(item: dict, topics: list[str], language: str) -> list[str]:
    tags = []
    feature = item.get("feature_extract") if isinstance(item.get("feature_extract"), dict) else {}
    problem = str(feature.get("core_problem") or "").strip()
    if problem:
        tags.append(problem)
    for tag in _audience_tags(item, topics):
        clean = tag.lstrip("#")
        if clean and clean not in tags:
            tags.append(clean)
    if language and language not in tags:
        tags.append(language)
    for topic in topics:
        clean = str(topic).strip()
        if clean and len(clean) <= 16 and clean not in tags:
            tags.append(clean)
        if len(tags) >= 3:
            break
    return tags[:3] or ["开源", "效率工具"]


def _star_history(stars: int, index: int) -> list[int]:
    base = max(24, 70 - index * 4)
    return [min(100, base + step * 5 + (stars % 7)) for step in range(14)]


def _theme_highlight(projects: list[dict]) -> str:
    text = " ".join(f"{p.get('description', '')} {' '.join(p.get('topics') or [])}".lower() for p in projects)
    if any(key in text for key in ("ai", "agent", "llm", "claude")):
        return "AI 开源工具"
    if any(key in text for key in ("framework", "runtime")):
        return "开发框架"
    return "技术热点"


def _theme_tags(projects: list[dict]) -> list[str]:
    tags = []
    for project in projects:
        for tag in project.get("tech_tags") or []:
            if tag and tag not in tags:
                tags.append(tag)
    return tags[:4] or ["GitHub", "开源", "热点"]


def _capture_html_screen(html_path: Path, screen_id: str, output_path: Path) -> Path:
    return _capture_html_screens(html_path, [(screen_id, output_path)])[0]


def _capture_html_screens(html_path: Path, targets: list[tuple[str, Path]]) -> list[Path]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
            page.goto(html_path.resolve().as_uri(), wait_until="domcontentloaded")
            outputs = []
            for screen_id, output_path in targets:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                page.wait_for_selector(f"#{screen_id}", state="attached", timeout=5000)
                page.evaluate(
                    """(screenId) => {
                        document.querySelectorAll('.screen').forEach((el) => {
                            el.style.visibility = 'hidden';
                            el.style.opacity = '0';
                        });
                        const target = document.getElementById(screenId);
                        target.style.visibility = 'visible';
                        target.style.opacity = '1';
                    }""",
                    screen_id,
                )
                page.screenshot(path=str(output_path), clip={"x": 0, "y": 0, "width": 1080, "height": 1920})
                outputs.append(output_path)
        finally:
            browser.close()
    return outputs


def _timeline_context(
    data: dict,
    durations: dict[str, int] | None = None,
    narration_segments: list[dict] | None = None,
    segment_durations: dict[str, float] | None = None,
    limit: int = 10,
) -> dict:
    """Build one shared timeline for the HTML composition and TTS script."""
    projects = data.get("projects") or []
    narration = _narration_by_id(narration_segments or [])
    duration_overrides = durations or {}
    audio_durations = segment_durations or {}

    intro_text = _narration_text(
        narration,
        "intro",
        f"这期 GitHub 热榜，我挑了 {data.get('total_projects', len(projects))} 个真实项目，{data.get('theme_highlight', '开源新星')}。",
    )
    list_text = _list_narration(projects)
    hook_text = _narration_text(
        narration,
        "outro",
        "这期都是真实开源项目。你想先看哪个？评论区告诉我。",
    )

    intro_duration = _screen_duration("intro", _duration_override(duration_overrides, "intro_duration") or _spoken_duration(intro_text, 5.0, 7.0), audio_durations)
    list_duration = _screen_duration("list", _duration_override(duration_overrides, "list_duration") or _spoken_duration(list_text, 6.0, 8.0), audio_durations)
    detail_base = _duration_override(duration_overrides, "detail_duration")
    hook_duration = _screen_duration("hook", _duration_override(duration_overrides, "hook_duration") or _spoken_duration(hook_text, 5.5, 8.0), audio_durations)

    cursor = 0.0
    intro_screen = {
        "screen_id": "screen-intro",
        "start": cursor,
        "duration": intro_duration,
        "narration": intro_text,
        "target": "intro",
        "subtitle_html": _subtitle_html(intro_text, ["GitHub", "热榜", "真实项目"]),
    }
    cursor += intro_duration
    list_screen = {
        "screen_id": "screen-list",
        "start": cursor,
        "duration": list_duration,
        "narration": list_text,
        "target": "list",
        "subtitle_html": _subtitle_html(list_text, [str(project.get("name") or "") for project in projects[:3]]),
    }
    cursor += list_duration

    detail_screens = []
    for index, project in enumerate(projects, start=1):
        project_text = _narration_text(narration, f"project-{index}", _project_narration(project))
        target = f"project-{index}"
        rank_text, proof_text = _split_project_narration(project_text, project)
        duration = _detail_duration(
            target,
            detail_base or _spoken_duration(project_text, 5.4, 8.5),
            audio_durations,
        )
        rank_duration, proof_duration = _split_detail_duration(duration, audio_durations.get(target), audio_durations.get(f"{target}-proof"))
        detail_screens.append({
            "screen_id": f"screen-detail-{index:02d}",
            "start": cursor,
            "duration": rank_duration,
            "narration": rank_text,
            "target": target,
            "detail_kind": "rank-punch",
            "paired_target": f"{target}-proof",
            "project": project,
            "subtitle_html": _subtitle_html(rank_text, [str(project.get("name") or ""), str(project.get("hook") or "")]),
        })
        cursor += rank_duration
        detail_screens.append({
            "screen_id": f"screen-detail-{index:02d}-proof",
            "start": cursor,
            "duration": proof_duration,
            "narration": proof_text,
            "target": f"{target}-proof",
            "detail_kind": "value-proof",
            "paired_target": target,
            "project": project,
            "subtitle_html": _subtitle_html(proof_text, [str(project.get("core_action") or ""), str(project.get("viewer_benefit") or "")]),
        })
        cursor += proof_duration

    hook_screen = {
        "screen_id": "screen-hook",
        "start": cursor,
        "duration": hook_duration,
        "narration": hook_text,
        "target": "hook",
        "subtitle_html": _subtitle_html(hook_text, ["评论区", "项目", "实操"]),
    }
    cursor += hook_duration

    return {
        "intro_screen": intro_screen,
        "list_screen": list_screen,
        "detail_screens": detail_screens,
        "hook_screen": hook_screen,
        "total_duration": round(cursor, 1),
        "top_projects": projects[: min(limit, len(projects))],
        "intro_duration": intro_duration,
        "list_duration": list_duration,
        "detail_duration": detail_base or 0,
        "hook_duration": hook_duration,
    }


def _build_script_from_timeline(timeline: dict) -> VideoScript:
    """Build VideoScript from the same timeline used by the HTML template."""
    items = [timeline["intro_screen"], timeline["list_screen"], *timeline["detail_screens"], timeline["hook_screen"]]
    return VideoScript(
        title="GitHub 热榜速报",
        segments=[
            ScriptSegment(
                timestamp=float(item["start"]),
                duration=float(item["duration"]),
                narration=str(item["narration"]),
                action="show",
                target=str(item["target"]),
            )
            for item in items
        ],
        total_duration=float(timeline["total_duration"]),
    )


def _build_script_from_spec(spec: dict[str, Any]) -> VideoScript:
    scenes = spec.get("scenes") if isinstance(spec.get("scenes"), list) else []
    return VideoScript(
        title="GitHub 热榜速报",
        segments=[
            ScriptSegment(
                timestamp=float(scene["start"]),
                duration=float(scene["duration"]),
                narration=str(scene["voiceover"]),
                action="show",
                target=str(scene["target"]),
            )
            for scene in scenes
        ],
        total_duration=float((spec.get("video_basics") or {}).get("total_duration") or 0),
    )


def _build_video_spec(data: dict, timeline: dict, style: str = DEFAULT_STYLE, work_dir: Path | None = None) -> dict[str, Any]:
    """Build an auditable director spec from the current HyperFrames timeline."""
    scenes = _build_scene_model(data, timeline)
    visual = _visual_spec(style, work_dir)
    return {
        "schema_version": "hotlist-video-spec.v1",
        "video_basics": {
            "purpose": "GitHub 热榜短视频",
            "audience": "关注开源工具、AI 工具和开发效率的中文开发者",
            "platform": "竖屏短视频",
            "aspect_ratio": "9:16",
            "fps": 30,
            "total_duration": float(timeline["total_duration"]),
            "core_message": f"本期 GitHub TOP {data.get('total_projects', len(data.get('projects') or []))}",
            "information_density": "hook",
            "tone_of_voice": "克制的中文开源项目观察",
            "viewer_familiarity": "理解 GitHub、Star、开源项目；不默认理解每个项目具体用途",
        },
        "narrative_structure": {
            "beats": [
                {"name": "hook", "start": 0.0, "end": float(timeline["intro_screen"]["duration"])},
                {
                    "name": "ranking",
                    "start": float(timeline["list_screen"]["start"]),
                    "end": _scene_end(timeline["list_screen"]),
                },
                {
                    "name": "details",
                    "start": float(timeline["detail_screens"][0]["start"]) if timeline["detail_screens"] else _scene_end(timeline["list_screen"]),
                    "end": float(timeline["hook_screen"]["start"]),
                },
                {"name": "cta", "start": float(timeline["hook_screen"]["start"]), "end": _scene_end(timeline["hook_screen"])},
            ],
            "emotional_curve": ["开场给出榜单价值", "中段逐项核对用途与证据", "收尾提示互动选择"],
            "audio_visual_relationship": "旁白解释项目价值，画面用榜单、事实卡和收尾清单承载可扫读信息。",
        },
        "expression": {
            "scene_types": ["大字开场", "榜单总览", "排名冲击", "价值证明", "收尾清单"],
            "subtitle_mode": "rendered_keyword_overlay",
            "motion_language": "卡片进入、榜单级联、指标强调、硬切转场",
            "pacing": {"average_scene_duration": _average_scene_duration(scenes), "unit": "seconds"},
        },
        "visual": visual,
        "assets": _spec_assets(data),
        "scenes": scenes,
        "audio_timeline": [
            {
                "target": scene["target"],
                "start": scene["start"],
                "duration": scene["duration"],
                "voiceover": scene["voiceover"],
                "subtitle_mode": scene["subtitle_mode"],
            }
            for scene in scenes
        ],
    }


def _render_data_from_spec(data: dict, spec: dict[str, Any]) -> dict[str, Any]:
    scenes = spec.get("scenes") if isinstance(spec.get("scenes"), list) else []
    detail_screens = [_detail_render_from_spec_scene(scene) for scene in scenes if str(scene.get("target") or "").startswith("project-")]
    top_projects = data.get("projects") or []
    return {
        **data,
        "intro_screen": _screen_from_spec_scene(_scene_for_target(scenes, "intro")),
        "list_screen": _screen_from_spec_scene(_scene_for_target(scenes, "list")),
        "detail_screens": detail_screens,
        "hook_screen": _screen_from_spec_scene(_scene_for_target(scenes, "hook")),
        "total_duration": float((spec.get("video_basics") or {}).get("total_duration") or 0),
        "top_projects": top_projects[: min(len(top_projects), max(1, len(detail_screens) // 2) if detail_screens else len(top_projects))],
        "intro_duration": float((_scene_for_target(scenes, "intro") or {}).get("duration") or 0),
        "list_duration": float((_scene_for_target(scenes, "list") or {}).get("duration") or 0),
        "detail_duration": 0,
        "hook_duration": float((_scene_for_target(scenes, "hook") or {}).get("duration") or 0),
    }


def _build_scene_model(data: dict, timeline: dict) -> list[dict[str, Any]]:
    projects = data.get("projects") or []
    scenes = [
        _scene_from_screen(
            timeline["intro_screen"],
            scene_id="scene-01-intro",
            component_id="broll-hero.big-type",
            display_text=f"TOP {data.get('total_projects', len(projects))} 热榜速报",
            visual_description="9:16 竖屏开场，大标题、项目数量、语言数量和估算日均 star 作为首屏信息锚点。",
            motion="SLAMS title, CASCADES metrics",
            asset_dependencies=[],
            subtitle_keywords=["GitHub", "热榜", "真实项目"],
            project={},
        ),
        _scene_from_screen(
            timeline["list_screen"],
            scene_id="scene-02-ranking",
            component_id="broll-charts.h-bar",
            display_text=f"GitHub TOP {len(projects)} 榜单",
            visual_description="榜单纵向排列，项目名、作者、语言、stars 和估算热度同屏展示，适合快速扫读。",
            motion="CASCADES rank rows",
            asset_dependencies=[],
            subtitle_keywords=[str(project.get("name") or "") for project in projects[:3] if project.get("name")],
            project={},
        ),
    ]

    for detail in timeline["detail_screens"]:
        project = detail.get("project") or {}
        scenes.append(_scene_from_screen(
            detail,
            scene_id=f"scene-{len(scenes) + 1:02d}-{detail.get('detail_kind', 'project')}-{int(project.get('rank') or len(scenes) - 1):02d}",
            component_id="broll-hero.big-number" if detail.get("detail_kind") == "rank-punch" else "aroll.concept-card",
            display_text=f"#{project.get('rank') or '?'} {project.get('name') or 'GitHub 项目'}",
            visual_description=_detail_visual_description(detail),
            motion="SLAMS rank, EMPHASIZES metric" if detail.get("detail_kind") == "rank-punch" else "FLOATS proof card, HIGHLIGHTS keywords",
            asset_dependencies=_project_asset_dependencies(project),
            subtitle_keywords=[
                str(project.get("name") or ""),
                str(project.get("hook") or ""),
                str(project.get("language") or ""),
            ],
            project=project,
        ))

    scenes.append(_scene_from_screen(
        timeline["hook_screen"],
        scene_id=f"scene-{len(scenes) + 1:02d}-cta",
        component_id="broll-hero.big-type",
        display_text=f"TOP {data.get('total_projects', len(projects))} 速览收尾",
        visual_description="收尾清单回看全部项目，用排名卡片提示观众评论选择想看的实操拆解。",
        motion="STACKS cards, HOLDS CTA",
        asset_dependencies=[],
        subtitle_keywords=["评论区", "项目", "实操"],
        out_transition="fade-out",
        project={},
    ))
    return scenes


def _detail_visual_description(detail: dict) -> str:
    if detail.get("detail_kind") == "rank-punch":
        return "排名冲击镜头，突出项目排名、名称、stars、语言和一句痛点钩子，先让观众记住它是谁。"
    return "价值证明镜头，突出具体用途、用户收益、证据来源和风险提示，承接上一镜的排名冲击。"


def _scene_for_target(scenes: list[dict[str, Any]], target: str) -> dict[str, Any]:
    for scene in scenes:
        if str(scene.get("target") or "") == target:
            return scene
    return {}


def _screen_from_spec_scene(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "screen_id": str(scene.get("screen_id") or ""),
        "start": float(scene.get("start") or 0),
        "duration": float(scene.get("duration") or 0),
        "narration": str(scene.get("voiceover") or ""),
        "target": str(scene.get("target") or ""),
        "subtitle_html": _subtitle_html(str(scene.get("voiceover") or ""), list(scene.get("subtitle_keywords") or [])),
    }


def _detail_render_from_spec_scene(scene: dict[str, Any]) -> dict[str, Any]:
    target = str(scene.get("target") or "")
    project = scene.get("project") or {}
    return {
        **_screen_from_spec_scene(scene),
        "detail_kind": "rank-punch" if target.endswith("-proof") is False else "value-proof",
        "paired_target": f"{target}-proof" if target.endswith("-proof") is False else target.rsplit("-proof", 1)[0],
        "project": project,
    }


def _scene_from_screen(
    screen: dict,
    scene_id: str,
    component_id: str,
    display_text: str,
    visual_description: str,
    motion: str,
    asset_dependencies: list[dict[str, str]],
    subtitle_keywords: list[str],
    out_transition: str = "hard cut",
    project: dict[str, Any] | None = None,
) -> dict[str, Any]:
    narration = str(screen.get("narration") or "").strip()
    start = round(float(screen.get("start") or 0), 1)
    duration = round(float(screen.get("duration") or 0), 1)
    keywords = [keyword for keyword in subtitle_keywords if keyword][:4]
    return {
        "id": scene_id,
        "target": str(screen.get("target") or ""),
        "screen_id": str(screen.get("screen_id") or ""),
        "start": start,
        "duration": duration,
        "end": round(start + duration, 1),
        "type": "B-roll",
        "component_id": component_id,
        "voiceover": narration,
        "display_text": display_text,
        "expected_content": display_text,
        "expected_effect": "观众能在一屏内理解这一段的排序、用途或行动提示。",
        "visual_description": visual_description,
        "motion": motion,
        "sound_effect": "无",
        "transition": {"in": "hard cut", "out": out_transition},
        "asset_dependencies": asset_dependencies,
        "subtitle_mode": "keyword_highlight",
        "subtitle_keywords": keywords,
        "project": project or {},
    }


def _scene_end(screen: dict) -> float:
    return round(float(screen.get("start") or 0) + float(screen.get("duration") or 0), 1)


def _average_scene_duration(scenes: list[dict[str, Any]]) -> float:
    if not scenes:
        return 0.0
    return round(sum(float(scene["duration"]) for scene in scenes) / len(scenes), 1)


def _spec_assets(data: dict) -> list[dict[str, str]]:
    assets = []
    for project in data.get("projects") or []:
        for asset in _project_asset_dependencies(project):
            assets.append(asset)
    return assets


def _project_asset_dependencies(project: dict) -> list[dict[str, str]]:
    source = str(project.get("visual_asset_source") or project.get("repo_url") or "").strip()
    if not source:
        return []
    return [{
        "id": f"project-{project.get('rank') or 'x'}-source",
        "type": str(project.get("visual_asset_label") or "项目来源"),
        "source": source,
        "usage": str(project.get("name") or "项目事实卡"),
    }]


def _visual_spec(style: str, work_dir: Path | None = None) -> dict[str, str]:
    design_path = _find_design_md(work_dir)
    if design_path:
        return {
            "theme_source": "design.md",
            "theme": "custom_design",
            "design_md": str(design_path),
            "preset": "",
            "legacy_style": style,
            "accent_color": "default",
            "decor_density": "design_default",
        }
    if style in HYPERFRAMES_PRESETS:
        return {
            "theme_source": "hyperframes_preset",
            "theme": style,
            "design_md": "",
            "preset": style,
            "legacy_style": "",
            "accent_color": "default",
            "decor_density": "preset_default",
        }
    return {
        "theme_source": "legacy_style_profile",
        "theme": style,
        "design_md": "",
        "preset": "",
        "legacy_style": style,
        "accent_color": "default",
        "decor_density": "style_default",
    }


def _find_design_md(work_dir: Path | None = None) -> Path | None:
    candidates = []
    if work_dir:
        candidates.append(work_dir / "design.md")
        candidates.append(work_dir / "DESIGN.md")
    candidates.append(PROJECT_ROOT / "design.md")
    candidates.append(PROJECT_ROOT / "DESIGN.md")
    for path in candidates:
        if path.exists():
            return path
    return None


def _validate_video_spec(spec: dict[str, Any]) -> None:
    scenes = spec.get("scenes") if isinstance(spec.get("scenes"), list) else []
    if not scenes:
        raise ValueError("video-spec scenes 不能为空")
    hook_scenes = [scene for scene in scenes if "intro" in str(scene.get("id") or "") or "hook" in str(scene.get("target") or "")]
    if not hook_scenes or min(float(scene.get("start") or 0) for scene in hook_scenes) > 3.0:
        raise ValueError("video-spec 缺少前 3 秒 hook scene")
    total_duration = float((spec.get("video_basics") or {}).get("total_duration") or 0)
    scene_total = round(sum(float(scene.get("duration") or 0) for scene in scenes), 1)
    if abs(scene_total - total_duration) > 0.5:
        raise ValueError(f"video-spec 总时长不一致: scenes={scene_total}, total={total_duration}")

    for scene in scenes:
        scene_id = str(scene.get("id") or "unknown")
        if str(scene.get("component_id") or "") not in VALID_SCENE_COMPONENTS:
            raise ValueError(f"{scene_id} 使用了未登记组件: {scene.get('component_id')}")
        if float(scene.get("duration") or 0) <= 0:
            raise ValueError(f"{scene_id} 时长必须大于 0")
        for key in ("voiceover", "display_text", "visual_description", "motion", "sound_effect"):
            if not str(scene.get(key) or "").strip():
                raise ValueError(f"{scene_id} 缺少 {key}")
        transition = scene.get("transition") or {}
        if not str(transition.get("in") or "").strip() or not str(transition.get("out") or "").strip():
            raise ValueError(f"{scene_id} 缺少转场")
        if "asset_dependencies" not in scene:
            raise ValueError(f"{scene_id} 缺少素材依赖字段")


def _narration_by_id(segments: list[dict]) -> dict[str, str]:
    return {
        str(segment.get("id") or ""): str(segment.get("text") or "").strip()
        for segment in segments
        if isinstance(segment, dict) and str(segment.get("id") or "")
    }


def _narration_text(segments: dict[str, str], segment_id: str, fallback: str) -> str:
    return segments.get(segment_id) or fallback


def _duration_override(durations: dict[str, int], key: str) -> float | None:
    if key not in durations:
        return None
    try:
        return max(1.0, float(durations[key]))
    except (TypeError, ValueError):
        return None


def _split_project_narration(text: str, project: dict) -> tuple[str, str]:
    text = " ".join(text.split()).strip()
    rank = project.get("rank") or 1
    name = project.get("name") or "GitHub 项目"
    hook = str(project.get("hook") or project.get("core_problem") or "先看它解决什么问题").strip()
    punch = f"第 {rank} 个，{name}。{hook}。"
    proof = text
    if proof.startswith(punch):
        proof = proof[len(punch):].strip()
    if not proof or proof == punch:
        proof = str(project.get("reason") or project.get("viewer_benefit") or project.get("description") or "具体价值还需要结合项目说明继续核对。")
    return punch, proof


def _detail_duration(target: str, visual_duration: float, audio_durations: dict[str, float]) -> float:
    rank_audio = audio_durations.get(target)
    proof_audio = audio_durations.get(f"{target}-proof")
    if rank_audio or proof_audio:
        audio_duration = (rank_audio or 0) + (proof_audio or 0) + 0.7
        return math.ceil(max(visual_duration, audio_duration) * 10) / 10
    return round(visual_duration, 1)


def _split_detail_duration(duration: float, rank_audio: float | None = None, proof_audio: float | None = None) -> tuple[float, float]:
    if rank_audio or proof_audio:
        rank_duration = math.ceil(max(1.2, min(2.4, (rank_audio or 0) + 0.35)) * 10) / 10
    else:
        rank_duration = round(max(1.2, min(2.2, duration * 0.32)), 1)
    if proof_audio:
        proof_duration = math.ceil(max(1.0, duration - rank_duration, proof_audio + 0.35) * 10) / 10
    else:
        proof_duration = round(max(1.0, duration - rank_duration), 1)
    return rank_duration, proof_duration


def _subtitle_html(text: str, keywords: list[str]) -> str:
    text = " ".join(str(text or "").split()).strip()
    if not text:
        return ""
    escaped = escape(text)
    for keyword in sorted({kw.strip() for kw in keywords if kw and len(kw.strip()) >= 2}, key=len, reverse=True)[:4]:
        escaped_keyword = escape(keyword)
        escaped = escaped.replace(
            escaped_keyword,
            f'<span class="subtitle-keyword">{escaped_keyword}</span>',
            1,
        )
    return escaped


def _spoken_duration(text: str, minimum: float, maximum: float) -> float:
    cjk_chars = len(re.findall(r"[\u3400-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9]+", text))
    estimate = 1.2 + (cjk_chars + latin_words * 2.2) / 11.5
    return round(max(minimum, min(maximum, estimate)), 1)


def _screen_duration(target: str, visual_duration: float, audio_durations: dict[str, float]) -> float:
    audio_duration = audio_durations.get(target)
    if not audio_duration:
        return round(visual_duration, 1)
    return math.ceil(max(visual_duration, audio_duration + 0.35) * 10) / 10


def _audio_segment_durations(script: VideoScript, audio_dir: Path) -> dict[str, float]:
    durations = {}
    for index, segment in enumerate(script.segments):
        audio_path = audio_dir / f"segment-{index:03d}.mp3"
        if audio_path.exists():
            durations[segment.target] = get_audio_duration(audio_path)
    return durations


def _list_narration(projects: list[dict]) -> str:
    if not projects:
        return "先看完整榜单，本期 GitHub 热门项目都在这里。"
    names = "、".join(str(project.get("name") or "") for project in projects[:3] if project.get("name"))
    return f"先看完整 TOP {len(projects)} 榜单：{names} 领跑，本期还有更多值得收藏的开源项目。"


def _project_narration(project: dict) -> str:
    rank = project.get("rank") or 1
    name = project.get("name") or "GitHub 项目"
    reason = project.get("reason") or project.get("description") or project.get("tagline") or "近期进入热榜候选，建议结合 README 和 stars 走势复核。"
    return f"第 {rank} 个，{name}。{reason}"


def _render_hyperframes(html_path: Path, output_path: Path) -> None:
    """Render HTML composition to MP4 using HyperFrames CLI.

    HyperFrames expects a project directory with index.html.
    We use the rendered composition directly as index.html.
    """
    project_dir = html_path.parent / "_hf_project"
    project_dir.mkdir(parents=True, exist_ok=True)

    # Copy composition as index.html (HyperFrames entry point)
    index_html = project_dir / "index.html"
    shutil.copy2(html_path, index_html)

    cmd = [
        "npx", "hyperframes", "render", str(project_dir),
        "-o", str(output_path),
        "--resolution", "portrait",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=600,
    )
    if result.returncode != 0:
        console.print(f"  [yellow]HyperFrames stderr:[/] {result.stderr[:500]}")
        raise RuntimeError(f"HyperFrames render failed: {result.stderr[:200]}")
    _verify_rendered_video(output_path)
    console.print(f"  HyperFrames output: {result.stdout[-300:]}")


def _verify_rendered_video(video_path: Path) -> None:
    if not video_path.exists() or video_path.stat().st_size <= 0:
        raise RuntimeError(f"HyperFrames render did not produce a usable video: {video_path}")
    try:
        from moviepy import VideoFileClip

        clip = VideoFileClip(str(video_path))
        try:
            if not clip.duration or clip.duration <= 0:
                raise RuntimeError(f"HyperFrames output has invalid duration: {video_path}")
            frame = clip.get_frame(min(0.1, max(0.0, clip.duration / 2)))
            if getattr(frame, "size", 0) <= 0:
                raise RuntimeError(f"HyperFrames output has an empty frame: {video_path}")
        finally:
            clip.close()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"HyperFrames output verification failed: {exc}") from exc


def _mix_audio(
    video_path: Path,
    script: VideoScript,
    audio_dir: Path,
    output_path: Path,
) -> None:
    """Mix TTS audio segments into the rendered video using FFmpeg."""
    from moviepy import AudioFileClip, CompositeAudioClip, VideoFileClip

    video = VideoFileClip(str(video_path))
    audio_clips = []
    try:
        for i, segment in enumerate(script.segments):
            audio_path = audio_dir / f"segment-{i:03d}.mp3"
            if audio_path.exists():
                clip = AudioFileClip(str(audio_path)).with_start(float(segment.timestamp))
                audio_clips.append(clip)

        if audio_clips:
            final_audio = CompositeAudioClip(audio_clips).with_duration(video.duration)
            if final_audio.duration > video.duration:
                final_audio = final_audio.subclipped(0, video.duration)
            video = video.with_audio(final_audio)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        video.write_videofile(
            str(output_path),
            fps=30,
            codec="libx264",
            audio_codec="aac",
            bitrate="8000k",
            preset="medium",
            logger=None,
        )
    finally:
        video.close()
        for clip in audio_clips:
            clip.close()
