"""End-to-end render pipeline for hotlist v2 video."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone

from rich.console import Console

from src.hotlist_v2.fetch import fetch_trending
from src.hotlist_v2.template import DEFAULT_STYLE, render_composition
from src.tts.edge_tts import generate_all_audio
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
) -> Path:
    """Render a hotlist v2 video from already selected console project data."""
    data = _data_from_projects(projects)
    return await render_hotlist_v2_from_data(data, output_path=output_path, durations=durations, style=style)


def render_hotlist_v2_previews_from_projects(
    projects: list[dict],
    output_dir: Path,
    durations: dict[str, int] | None = None,
    style: str = DEFAULT_STYLE,
) -> list[Path]:
    """Render static preview frames from the HyperFrames HTML template."""
    output_dir.mkdir(parents=True, exist_ok=True)
    data = _data_from_projects(projects)
    html_dir = output_dir.parent / "hyperframes_preview_html"
    html_dir.mkdir(parents=True, exist_ok=True)

    previews = []
    base_html = html_dir / "composition.html"
    render_composition(data, base_html, durations, style=style)
    previews.append(_capture_html_screen(base_html, "screen-intro", output_dir / "shot-01.png"))
    previews.append(_capture_html_screen(base_html, "screen-list", output_dir / "shot-02.png"))

    base_projects = data.get("projects") or []
    for index, project in enumerate(base_projects, start=1):
        detail_data = {
            **data,
            "projects": [project, *[item for item in base_projects if item is not project]],
        }
        detail_html = html_dir / f"composition-detail-{index:02d}.html"
        render_composition(detail_data, detail_html, durations, style=style)
        previews.append(_capture_html_screen(detail_html, "screen-detail", output_dir / f"shot-{index + 2:02d}.png"))

    previews.append(_capture_html_screen(base_html, "screen-hook", output_dir / f"shot-{len(previews) + 1:02d}.png"))
    return previews


async def render_hotlist_v2_from_data(
    data: dict,
    output_path: Path | None = None,
    durations: dict[str, int] | None = None,
    style: str = DEFAULT_STYLE,
) -> Path:
    """Render a hotlist v2 video from normalized template data."""
    out = output_path or OUTPUT_DIR / "final.mp4"
    work_dir = out.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    data_path = work_dir / "trending-data.json"
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"  ✓ Found {data['total_projects']} projects, {data['total_languages']} languages")

    # Step 2: Render HTML composition
    console.print("[bold cyan]Step 2/5:[/] Rendering HTML composition...")
    html_path = work_dir / "composition.html"
    render_composition(data, html_path, durations, style=style)
    console.print(f"  ✓ HTML composition: {html_path}")

    # Step 3: Generate TTS narration
    console.print("[bold cyan]Step 3/5:[/] Generating TTS narration...")
    script = _build_script(data, durations)
    script_path = work_dir / "script.json"
    script_path.write_text(json.dumps(script.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    await generate_all_audio(script, work_dir)
    audio_dir = work_dir / "audio"
    console.print(f"  ✓ TTS audio: {audio_dir}")

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
        normalized.append({
            "rank": index,
            "name": name,
            "owner": owner,
            "owner_initial": owner[:1].upper() if owner else "?",
            "tagline": str(item.get("tagline") or item.get("audience") or "开源热点"),
            "description": str(item.get("description_zh") or item.get("description") or ""),
            "language": language,
            "language_color": language_color,
            "stars": stars,
            "stars_display": _star_display(stars),
            "daily_growth": str(item.get("daily_growth") or item.get("stars_delta") or "热度上升"),
            "forks": int(item.get("forks") or item.get("forks_count") or 0),
            "issues": int(item.get("issues") or item.get("open_issues_count") or 0),
            "topics": topics,
            "tech_tags": _tech_tags(topics, language),
            "star_history": _star_history(stars, index),
            "reason": str(item.get("project_highlight") or item.get("viewer_benefit") or item.get("recommendation") or item.get("ranking_reason") or ""),
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
    from playwright.sync_api import sync_playwright

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=1)
        page.goto(html_path.resolve().as_uri(), wait_until="domcontentloaded")
        page.wait_for_selector(f"#{screen_id}", timeout=5000)
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
        box = page.locator('[data-composition-id="main"]').bounding_box()
        page.screenshot(path=str(output_path), clip=box)
        browser.close()
    return output_path


def _build_script(data: dict, durations: dict[str, int] | None = None) -> VideoScript:
    """Build VideoScript from trending data for TTS generation."""
    dur = {**{"intro_duration": 4, "list_duration": 4, "detail_duration": 4, "hook_duration": 4}, **(durations or {})}
    projects = data.get("projects", [])
    top1 = projects[0] if projects else {}

    segments = [
        ScriptSegment(
            timestamp=0,
            duration=dur["intro_duration"],
            narration=f"这期 GitHub 热榜，我挑了 {data.get('total_projects', 10)} 个真实项目，{data.get('theme_highlight', '开源新星')}。",
            action="show",
            target="intro",
        ),
        ScriptSegment(
            timestamp=dur["intro_duration"],
            duration=dur["list_duration"],
            narration=f"先看榜单：{projects[0]['name'] if projects else ''} 暂时排第一，{projects[1]['name'] if len(projects) > 1 else ''} 和 {projects[2]['name'] if len(projects) > 2 else ''} 紧随其后。",
            action="show",
            target="list",
        ),
        ScriptSegment(
            timestamp=dur["intro_duration"] + dur["list_duration"],
            duration=dur["detail_duration"],
            narration=f"第一名 {top1.get('name', '')}，{top1.get('stars_display', '')} 星标。{top1.get('reason', '')}",
            action="show",
            target="detail",
        ),
        ScriptSegment(
            timestamp=dur["intro_duration"] + dur["list_duration"] + dur["detail_duration"],
            duration=dur["hook_duration"],
            narration="这期都是真实开源项目。你想先看哪个？评论区告诉我。",
            action="show",
            target="hook",
        ),
    ]

    total = sum(dur.values())
    return VideoScript(title="GitHub 热榜速报", segments=segments, total_duration=total)


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
    from moviepy import AudioFileClip, VideoFileClip, concatenate_audioclips

    video = VideoFileClip(str(video_path))
    audio_clips = []
    for i, segment in enumerate(script.segments):
        audio_path = audio_dir / f"segment-{i:03d}.mp3"
        if audio_path.exists():
            clip = AudioFileClip(str(audio_path))
            audio_clips.append(clip)

    if audio_clips:
        final_audio = concatenate_audioclips(audio_clips)
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
