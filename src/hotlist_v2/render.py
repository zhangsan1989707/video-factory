"""End-to-end render pipeline for hotlist v2 video."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from rich.console import Console

from src.hotlist_v2.fetch import fetch_trending
from src.hotlist_v2.template import render_composition
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
    out = output_path or OUTPUT_DIR / "final.mp4"
    work_dir = out.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Fetch trending data
    console.print("[bold cyan]Step 1/5:[/] Fetching GitHub trending data...")
    data = await fetch_trending(time_window, token=token, limit=limit)
    data_path = work_dir / "trending-data.json"
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"  ✓ Found {data['total_projects']} projects, {data['total_languages']} languages")

    # Step 2: Render HTML composition
    console.print("[bold cyan]Step 2/5:[/] Rendering HTML composition...")
    html_path = work_dir / "composition.html"
    render_composition(data, html_path, durations)
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
