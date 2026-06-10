"""End-to-end render pipeline for hotlist v2 video."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone

from rich.console import Console

from src.hotlist_v2.fetch import fetch_trending
from src.hotlist_v2.template import DEFAULT_STYLE, render_composition
from src.tts.edge_tts import generate_all_audio, get_audio_duration
from src.models import VideoScript, ScriptSegment

console = Console()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "hotlist-v2"


async def render_hotlist_v2(
    output_path: Path | None = None,
    time_window: str = "weekly",
    token: str = "",
    limit: int = 10,
    durations: dict[str, int] | None = None,
    style: str = DEFAULT_STYLE,
) -> Path:
    """Full pipeline: fetch → template → HyperFrames → TTS → final video.

    Args:
        output_path: Final video output path
        time_window: GitHub trending time window (daily/weekly/monthly)
        token: GitHub API token
        limit: Number of projects to include
        durations: Optional screen duration overrides

    Returns:
        Path to final video
    """
    console.print("[bold cyan]Step 1/5:[/] Fetching GitHub trending data...")
    data = await fetch_trending(time_window, token=token, limit=limit)
    return await render_hotlist_v2_from_data(data, output_path=output_path, durations=durations, style=style)


async def render_hotlist_v2_from_projects(
    projects: list[dict],
    output_path: Path | None = None,
    durations: dict[str, int] | None = None,
    style: str = DEFAULT_STYLE,
    narration_segments: list[dict] | None = None,
) -> Path:
    """Render a hotlist v2 video from already selected console project data."""
    data = _data_from_projects(projects)
    return await render_hotlist_v2_from_data(
        data,
        output_path=output_path,
        durations=durations,
        style=style,
        narration_segments=narration_segments,
    )


def render_hotlist_v2_previews_from_projects(
    projects: list[dict],
    output_dir: Path,
    durations: dict[str, int] | None = None,
    style: str = DEFAULT_STYLE,
) -> list[Path]:
    """Render static preview frames from the HyperFrames HTML template."""
    output_dir.mkdir(parents=True, exist_ok=True)
    data = _data_from_projects(projects)
    timeline = _timeline_context(data, durations)
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
) -> Path:
    """Render a hotlist v2 video from normalized template data."""
    out = output_path or OUTPUT_DIR / "final.mp4"
    work_dir = out.parent
    work_dir.mkdir(parents=True, exist_ok=True)
    timeline = _timeline_context(data, durations, narration_segments)
    console.print(f"  ✓ Found {data['total_projects']} projects, {data['total_languages']} languages")

    # Step 2: Generate TTS narration first so the visual timeline can follow real speech length.
    console.print("[bold cyan]Step 2/5:[/] Generating TTS narration...")
    script = _build_script_from_timeline(timeline)
    script_path = work_dir / "script.json"
    shutil.rmtree(work_dir / "audio", ignore_errors=True)
    await generate_all_audio(script, work_dir)
    audio_dir = work_dir / "audio"
    segment_durations = _audio_segment_durations(script, audio_dir)
    timeline = _timeline_context(data, durations, narration_segments, segment_durations=segment_durations)
    script = _build_script_from_timeline(timeline)
    script_path.write_text(json.dumps(script.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"  ✓ TTS audio: {audio_dir}")

    # Step 3: Render HTML composition
    console.print("[bold cyan]Step 3/5:[/] Rendering HTML composition...")
    render_data = {**data, **timeline}
    data_path = work_dir / "trending-data.json"
    data_path.write_text(json.dumps(render_data, indent=2, ensure_ascii=False), encoding="utf-8")
    html_path = work_dir / "composition.html"
    render_composition(render_data, html_path, durations, style=style)
    console.print(f"  ✓ HTML composition: {html_path}")

    # Step 4: Render video with HyperFrames
    console.print("[bold cyan]Step 4/5:[/] Rendering video with HyperFrames...")
    raw_video = work_dir / "raw.mp4"
    _render_hyperframes(html_path, raw_video)
    console.print(f"  ✓ Raw video: {raw_video}")

    # Step 5: Mix TTS audio into video
    console.print("[bold cyan]Step 5/5:[/] Mixing TTS audio...")
    _mix_audio(raw_video, script, audio_dir, out)
    console.print(f"  ✓ [bold green]Final video:[/] {out}")

    return out


def _data_from_projects(projects: list[dict]) -> dict:
    """Normalize console selected projects to the hotlist v2 template shape."""
    normalized = []
    languages_seen: dict[str, str] = {}
    total_stars = 0
    for index, item in enumerate(projects, start=1):
        stars = int(item.get("stars") or item.get("stargazers_count") or 0)
        total_stars += stars
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
        normalized.append({
            "rank": index,
            "name": name,
            "owner": owner,
            "owner_initial": owner[:1].upper() if owner else "?",
            "tagline": str(item.get("tagline") or item.get("audience") or "开源热点"),
            "description": description,
            "purpose": purpose,
            "outcome": outcome,
            "language": language,
            "language_color": language_color,
            "stars": stars,
            "stars_display": _star_display(stars),
            "daily_growth": str(item.get("daily_growth") or item.get("stars_delta") or "热度上升"),
            "forks": _fork_display(item),
            "issues": int(item.get("issues") or item.get("open_issues_count") or 0),
            "topics": topics,
            "tech_tags": _tech_tags(topics, language),
            "star_history": _star_history(stars, index),
            "reason": _project_reason(item, purpose, outcome, stars),
            "repo_url": str(item.get("repo_url") or item.get("html_url") or ""),
        })

    now = datetime.now(timezone(timedelta(hours=8)))
    languages = [{"name": name, "color": color} for name, color in list(languages_seen.items())[:6]]
    return {
        "date": f"{now.year} 年 {now.month} 月 {now.day} 日",
        "issue": now.isocalendar()[1],
        "total_projects": len(normalized),
        "total_languages": len(languages),
        "total_new_stars": _star_display(total_stars),
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
    description_zh = _clean_viewer_text(str(item.get("description_zh") or ""))
    description = _clean_viewer_text(str(item.get("description") or ""))
    return description_zh or description or "项目描述较少，需要打开仓库确认具体用途。"


def _project_purpose(item: dict, description: str) -> str:
    for key in ("project_highlight", "viewer_benefit"):
        text = _clean_viewer_text(str(item.get(key) or ""))
        if text:
            return text
    return description


def _project_outcome(item: dict, description: str) -> str:
    text = _project_text(item)
    if _has_keyword(text, ("ai", "agent", "llm", "model", "rag")):
        return "把模型能力落到具体任务和工作流里。"
    if _has_keyword(text, ("video", "image", "audio", "visual", "3d")):
        return "减少内容生成、处理或可视化时的来回切换。"
    if _has_keyword(text, ("react", "vue", "frontend", "ui", "css")):
        return "更快做出可见界面，降低样式和交互试错成本。"
    if _has_keyword(text, ("data", "database", "analytics", "sql")):
        return "把数据整理、查询或分析流程变得更直接。"
    if _has_keyword(text, ("cli", "terminal", "shell", "developer")):
        return "把重复命令和工程操作收拢成更短路径。"
    return description.rstrip("。") + "。"


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
    )
    compact = text.replace(" ", "")
    if any(phrase in text or phrase.replace(" ", "") in compact for phrase in blocked):
        return ""
    return text


def _project_text(item: dict) -> str:
    return " ".join([
        str(item.get("description") or ""),
        str(item.get("description_zh") or ""),
        " ".join(str(topic) for topic in item.get("topics") or []),
        str(item.get("language") or ""),
    ]).lower()


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(re.search(rf"(^|[^a-z0-9]){re.escape(keyword)}([^a-z0-9]|$)", text) for keyword in keywords)


def _language_color(language: str) -> str:
    colors = {
        "TypeScript": "#3b82f6",
        "Python": "#f59e0b",
        "Rust": "#f97316",
        "Go": "#10b981",
        "JavaScript": "#f7df1e",
    }
    return colors.get(language, "#8899bb")


def _tech_tags(topics: list[str], language: str) -> list[str]:
    tags = [language] if language else []
    for topic in topics:
        if topic and topic not in tags:
            tags.append(topic)
    return tags[:4]


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
        browser.close()
    return outputs


def _timeline_context(
    data: dict,
    durations: dict[str, int] | None = None,
    narration_segments: list[dict] | None = None,
    segment_durations: dict[str, float] | None = None,
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
    }
    cursor += intro_duration
    list_screen = {
        "screen_id": "screen-list",
        "start": cursor,
        "duration": list_duration,
        "narration": list_text,
        "target": "list",
    }
    cursor += list_duration

    detail_screens = []
    for index, project in enumerate(projects, start=1):
        project_text = _narration_text(narration, f"project-{index}", _project_narration(project))
        target = f"project-{index}"
        duration = _screen_duration(target, detail_base or _spoken_duration(project_text, 5.4, 8.5), audio_durations)
        detail_screens.append({
            "screen_id": f"screen-detail-{index:02d}",
            "start": cursor,
            "duration": duration,
            "narration": project_text,
            "target": target,
            "project": project,
        })
        cursor += duration

    hook_screen = {
        "screen_id": "screen-hook",
        "start": cursor,
        "duration": hook_duration,
        "narration": hook_text,
        "target": "hook",
    }
    cursor += hook_duration

    return {
        "intro_screen": intro_screen,
        "list_screen": list_screen,
        "detail_screens": detail_screens,
        "hook_screen": hook_screen,
        "total_duration": round(cursor, 1),
        "top_projects": projects[: min(10, len(projects))],
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
    reason = project.get("reason") or project.get("description") or project.get("tagline") or "近期热度上升，值得关注。"
    return f"第 {rank} 个，{name}。{reason}"


def _render_hyperframes(html_path: Path, output_path: Path) -> None:
    """Render HTML composition to MP4 using HyperFrames CLI.

    HyperFrames expects a project directory with index.html.
    We use the rendered composition directly as index.html.
    """
    project_dir = html_path.parent / "_hf_project"
    project_dir.mkdir(parents=True, exist_ok=True)

    # Copy composition as index.html (HyperFrames entry point)
    import shutil
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
        if not output_path.exists():
            raise RuntimeError(f"HyperFrames render failed: {result.stderr[:200]}")
    console.print(f"  HyperFrames output: {result.stdout[-300:]}")


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
    video.close()
    for clip in audio_clips:
        clip.close()
