"""HyperFrames 渲染封装 - 股票科普视频"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.tts.edge_tts import generate_all_audio


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_DIR = PROJECT_ROOT / "assets" / "templates"


class ScriptAdapter:
    """适配 generate_all_audio 需要的 VideoScript 形状"""

    def __init__(self, segments: list[dict[str, Any]]) -> None:
        self.segments = [
            type(
                "_Segment",
                (),
                {
                    "timestamp": float(seg.get("timestamp", 0)),
                    "duration": float(seg.get("duration", 5)),
                    "narration": str(seg.get("narration", "")),
                },
            )()
            for seg in segments
        ]


async def render_stock_education_video(
    theme: str,
    segments: list[dict[str, Any]],
    output_dir: Path,
    voice: str,
    rate: str,
    fps: int = 30,
) -> Path:
    """用 HyperFrames 渲染股票科普视频

    Args:
        theme: 主题
        segments: 脚本片段（已按实际音频时长校准）
        output_dir: 输出目录
        voice: TTS 声音
        rate: TTS 语速
        fps: 帧率

    Returns:
        最终视频路径
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 生成 TTS
    audio_files = await generate_all_audio(
        ScriptAdapter(segments), output_dir, voice=voice, rate=rate
    )

    # 2. 根据实际音频时长再次校准 segments
    calibrated = calibrate_segments_by_audio(segments, audio_files)

    # 3. 渲染 HTML composition
    html_path = output_dir / "composition.html"
    render_html_composition(theme, calibrated, html_path)

    # 4. HyperFrames 渲染 raw video
    raw_video = output_dir / "raw.mp4"
    render_hyperframes(html_path, raw_video)

    # 5. 混合音频
    final_video = output_dir / "final.mp4"
    mix_audio(raw_video, calibrated, audio_files, final_video)

    return final_video


def render_html_composition(
    theme: str, segments: list[dict[str, Any]], output_path: Path
) -> None:
    """渲染 HTML composition"""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("stock-education.html")

    screens = build_screens(theme, segments)
    total_duration = sum(float(s.get("duration", 0)) for s in screens)

    context = {
        "theme": theme,
        "screens": screens,
        "total_duration": total_duration,
        "style_profile": MAGAZINE_STYLE,
    }

    html = template.render(**context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def build_screens(theme: str, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 segments 映射为 screens"""
    screens: list[dict[str, Any]] = []
    screen_types = ["intro", "concept", "concept", "chart", "comparison", "concept", "summary"]

    for i, seg in enumerate(segments):
        if i == len(segments) - 1 and i >= len(screen_types) - 1:
            screen_type = "summary"
        else:
            screen_type = screen_types[i % len(screen_types)]
        screens.append(
            {
                "id": f"screen-{i + 1:02d}-{screen_type}",
                "type": screen_type,
                "start": float(seg.get("timestamp", 0)),
                "duration": float(seg.get("duration", 5)),
                "narration": str(seg.get("narration", "")),
                "subtitle": str(seg.get("subtitle", seg.get("narration", ""))),
                "term": theme,
            }
        )

    return screens


MAGAZINE_STYLE = {
    "canvas_bg": "#0F0F1A",
    "bg_card": "rgba(26, 26, 46, 0.85)",
    "accent_gold": "#E8B04B",
    "accent_gold_rgb": "232, 176, 75",
    "text_primary": "#FFFFFF",
    "text_secondary": "rgba(255, 255, 255, 0.72)",
    "text_dim": "rgba(255, 255, 255, 0.48)",
    "font_display": "'Noto Serif SC', 'STSong', serif",
    "font_body": "'Noto Sans SC', -apple-system, sans-serif",
    "card_radius": "24px",
}


def calibrate_segments_by_audio(
    segments: list[dict[str, Any]], audio_files: list[Any]
) -> list[dict[str, Any]]:
    """根据实际 TTS 音频时长校准 segments"""
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    durations: list[float] = []

    for i, seg in enumerate(segments):
        audio_file = audio_files[i] if i < len(audio_files) else None
        duration = float(seg.get("duration", 5))
        if audio_file and Path(audio_file).exists():
            try:
                result = subprocess.run(
                    [
                        ffprobe,
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        str(audio_file),
                    ],
                    capture_output=True,
                    text=True,
                )
                duration = float(result.stdout.strip() or duration)
            except Exception:
                pass
        durations.append(duration)

    total = sum(durations)
    target_total = min(total, 60.0)
    scale = target_total / total if total > 0 else 1.0

    calibrated: list[dict[str, Any]] = []
    current_ts = 0.0
    for seg, dur in zip(segments, durations):
        scaled_dur = round(dur * scale, 3)
        calibrated.append(
            {
                **seg,
                "timestamp": round(current_ts, 3),
                "duration": scaled_dur,
            }
        )
        current_ts += scaled_dur

    return calibrated


def render_hyperframes(html_path: Path, output_path: Path) -> None:
    """调用 HyperFrames CLI 渲染视频"""
    project_dir = html_path.parent / "_hf_project"
    project_dir.mkdir(parents=True, exist_ok=True)
    index_html = project_dir / "index.html"
    shutil.copy2(html_path, index_html)

    cmd = [
        "npx",
        "hyperframes",
        "render",
        str(project_dir),
        "-o",
        str(output_path),
        "--resolution",
        "portrait",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"HyperFrames render failed: {result.stderr[:500]}")


def mix_audio(
    video_path: Path,
    segments: list[dict[str, Any]],
    audio_files: list[Any],
    output_path: Path,
) -> None:
    """用 moviepy 把 TTS 音频混合到视频中"""
    from moviepy import AudioFileClip, CompositeAudioClip, VideoFileClip

    video = VideoFileClip(str(video_path))
    audio_clips: list[Any] = []
    try:
        for i, segment in enumerate(segments):
            audio_path = audio_files[i] if i < len(audio_files) else None
            if audio_path and Path(audio_path).exists():
                clip = AudioFileClip(str(audio_path)).with_start(
                    float(segment["timestamp"])
                )
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
