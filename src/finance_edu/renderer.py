"""炒股科普视频渲染器 - Playwright 截图 + ffmpeg 合成"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.finance_edu.constants import (
    BLACK_GOLD_THEME,
    SAFE_AREA,
    VIDEO_FPS,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
    WHITE_CARD_THEME,
)
from src.finance_edu.models import FinanceEduScene, FinanceEduStoryboard, FinanceEduTopic
from src.finance_edu.storage import write_json

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_DIR = PROJECT_ROOT / "assets" / "templates" / "finance_edu"


def build_finance_render_plan(
    topic: FinanceEduTopic,
    storyboard: FinanceEduStoryboard,
    paths,
) -> dict[str, Any]:
    """构建渲染计划 JSON"""
    render_plan = {
        "width": VIDEO_WIDTH,
        "height": VIDEO_HEIGHT,
        "fps": VIDEO_FPS,
        "duration": topic.duration,
        "style": topic.visual_style,
        "title": storyboard.title,
        "scenes": [],
    }
    for scene in storyboard.scenes:
        render_plan["scenes"].append(_scene_to_render(scene))
    return render_plan


def _scene_to_render(scene: FinanceEduScene) -> dict[str, Any]:
    return {
        "scene_id": scene.scene_id,
        "template_id": scene.template_id,
        "start": scene.start,
        "duration": scene.duration,
        "title": scene.title,
        "subtitle": scene.subtitle,
        "bullets": scene.bullets,
        "narration": scene.narration,
        "chart_type": scene.chart_type,
        "chart_hint": scene.chart_hint,
        "risk_note": scene.risk_note,
        "visual_style": scene.visual_style,
    }


def save_render_plan(render_plan: dict[str, Any], path: Path) -> None:
    write_json(path, render_plan)


def render_finance_html(
    visual_style: str,
    title: str,
    scenes: list[dict[str, Any]],
    total_duration: float,
    output_path: Path,
) -> None:
    """用 Jinja2 渲染 finance_edu HTML composition"""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("finance_edu.html")
    html = template.render(
        visual_style=visual_style,
        title=title,
        scenes=scenes,
        total_duration=total_duration,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def render_playwright_video(
    html_path: Path,
    scenes: list[dict[str, Any]],
    output_path: Path,
    fps: int = VIDEO_FPS,
) -> None:
    """用 Playwright 打开 HTML，逐场景截图，ffmpeg 合成视频"""
    from playwright.sync_api import sync_playwright

    frames_dir = html_path.parent / "_playwright_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": VIDEO_WIDTH, "height": VIDEO_HEIGHT})
        page.goto(f"file://{html_path.resolve()}")
        page.wait_for_timeout(1000)

        for i, scene in enumerate(scenes):
            start = float(scene.get("start", 0))
            advance_to = start + 0.3
            page.evaluate(f"window.__timelines.main.seek({advance_to}).pause()")
            page.wait_for_timeout(200)
            page.screenshot(path=str(frames_dir / f"frame_{i:04d}.png"))
            print(f"  📸 场景 {i + 1}/{len(scenes)} @ {advance_to:.1f}s")

        browser.close()

    _frames_to_video(frames_dir, scenes, output_path, fps)


def _frames_to_video(
    frames_dir: Path,
    scenes: list[dict[str, Any]],
    output_path: Path,
    fps: int,
) -> None:
    """用 ffmpeg 把截图序列 + 时长合成为视频"""
    concat_file = frames_dir / "concat.txt"
    with open(concat_file, "w", encoding="utf-8") as f:
        for i, scene in enumerate(scenes):
            frame = frames_dir / f"frame_{i:04d}.png"
            dur = float(scene.get("duration", 5))
            f.write(f"file '{frame.resolve()}'\n")
            f.write(f"duration {dur}\n")
        if scenes:
            last_frame = frames_dir / f"frame_{len(scenes) - 1:04d}.png"
            f.write(f"file '{last_frame.resolve()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-vf", f"fps={fps}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 合成失败: {result.stderr[-500:]}")


def mix_audio(
    video_path: Path,
    scenes: list[dict[str, Any]],
    audio_files: list[Path],
    output_path: Path,
) -> None:
    """把 TTS 音频按时间戳混合到视频中"""
    from moviepy import AudioFileClip, CompositeAudioClip, VideoFileClip

    video = VideoFileClip(str(video_path))
    audio_clips: list[Any] = []
    try:
        for i, scene in enumerate(scenes):
            audio_path = audio_files[i] if i < len(audio_files) else None
            if audio_path and Path(audio_path).exists():
                clip = AudioFileClip(str(audio_path)).with_start(float(scene.get("start", 0)))
                audio_clips.append(clip)
        if audio_clips:
            final_audio = CompositeAudioClip(audio_clips).with_duration(video.duration)
            if final_audio.duration > video.duration:
                final_audio = final_audio.subclipped(0, video.duration)
            video = video.with_audio(final_audio)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        video.write_videofile(
            str(output_path), fps=30, codec="libx264", audio_codec="aac",
            bitrate="8000k", preset="medium", logger=None,
        )
    finally:
        video.close()
        for clip in audio_clips:
            clip.close()


def render_finance_preview_frames(
    render_plan: dict[str, Any],
    output_dir: Path,
) -> list[Path]:
    """生成静态预览帧（PIL）"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    width = render_plan.get("width", VIDEO_WIDTH)
    height = render_plan.get("height", VIDEO_HEIGHT)
    style = render_plan.get("style", "black_gold")
    is_dark = style == "black_gold"

    font_path = None
    try:
        from src.utils.config import CJK_FONT_PATH
        font_path = CJK_FONT_PATH
    except Exception:
        pass

    def _font(size):
        try:
            if font_path:
                return ImageFont.truetype(font_path, size)
        except Exception:
            pass
        return ImageFont.load_default()

    bg = (7, 10, 15) if is_dark else (247, 243, 234)
    card = (16, 23, 34) if is_dark else (255, 255, 255)
    gold = (242, 201, 76) if is_dark else (217, 164, 65)
    white = (248, 250, 252) if is_dark else (17, 24, 39)
    muted = (148, 163, 184) if is_dark else (107, 114, 128)

    preview_paths: list[Path] = []
    for scene in render_plan.get("scenes", []):
        img = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(img)
        margin = 48
        draw.rounded_rectangle([margin, 200, width - margin, height - 200], radius=24, fill=card)

        title = scene.get("title", "")
        if title:
            f = _font(64)
            bbox = draw.textbbox((0, 0), title, font=f)
            tw = bbox[2] - bbox[0]
            draw.text(((width - tw) // 2, 440), title, fill=gold, font=f)

        sub = scene.get("subtitle", "")
        if sub:
            f = _font(32)
            bbox = draw.textbbox((0, 0), sub, font=f)
            tw = bbox[2] - bbox[0]
            draw.text(((width - tw) // 2, 540), sub, fill=white, font=f)

        bullets = scene.get("bullets", [])
        if bullets:
            f = _font(28)
            y = 660
            for b in bullets[:3]:
                text = f"•  {b}"
                bbox = draw.textbbox((0, 0), text, font=f)
                tw = bbox[2] - bbox[0]
                draw.text(((width - tw) // 2, y), text, fill=muted, font=f)
                y += 60

        risk = scene.get("risk_note", "")
        if risk:
            f = _font(22)
            text = f"⚠ {risk}"
            bbox = draw.textbbox((0, 0), text, font=f)
            tw = bbox[2] - bbox[0]
            draw.text(((width - tw) // 2, height - 320), text, fill=(239, 68, 68), font=f)

        target = output_dir / f"preview_{scene.get('scene_id', 'unknown')}.png"
        img.save(target)
        preview_paths.append(target)

    return preview_paths
