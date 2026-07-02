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
    """生成静态预览帧（PIL），支持 MACD 图表渲染"""
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
    green = (34, 197, 94)
    red = (239, 68, 68)
    blue = (96, 165, 250)

    preview_paths: list[Path] = []
    for scene in render_plan.get("scenes", []):
        img = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(img)
        margin = 48
        draw.rounded_rectangle([margin, 200, width - margin, height - 200], radius=24, fill=card)

        template_id = scene.get("template_id", "")
        title = scene.get("title", "")
        sub = scene.get("subtitle", "")
        bullets = scene.get("bullets", [])

        if template_id == "indicator_chart":
            chart_type = scene.get("chart_type", "macd")
            _CHART_DRAWERS = {
                "macd": _draw_macd_chart,
                "kdj": _draw_kdj_chart,
                "ma": _draw_ma_chart,
                "volume": _draw_volume_chart,
                "support_resistance": _draw_sr_chart,
                "stop_loss": _draw_stoploss_chart,
            }
            drawer = _CHART_DRAWERS.get(chart_type, _draw_macd_chart)
            drawer(draw, width, height, title, sub, gold, white, muted, green, red, blue, _font)
        else:
            if title:
                f = _font(64)
                bbox = draw.textbbox((0, 0), title, font=f)
                tw = bbox[2] - bbox[0]
                draw.text(((width - tw) // 2, 440), title, fill=gold, font=f)
            if sub:
                f = _font(32)
                bbox = draw.textbbox((0, 0), sub, font=f)
                tw = bbox[2] - bbox[0]
                draw.text(((width - tw) // 2, 540), sub, fill=white, font=f)
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
            draw.text(((width - tw) // 2, height - 320), text, fill=red, font=f)

        target = output_dir / f"preview_{scene.get('scene_id', 'unknown')}.png"
        img.save(target)
        preview_paths.append(target)

    return preview_paths


def _draw_macd_chart(draw, width, height, title, sub, gold, white, muted, green, red, blue, _font):
    """用 PIL 绘制 MACD 图表"""
    # Title
    if title:
        f = _font(56)
        bbox = draw.textbbox((0, 0), title, font=f)
        tw = bbox[2] - bbox[0]
        draw.text(((width - tw) // 2, 320), title, fill=gold, font=f)
    if sub:
        f = _font(28)
        bbox = draw.textbbox((0, 0), sub, font=f)
        tw = bbox[2] - bbox[0]
        draw.text(((width - tw) // 2, 400), sub, fill=white, font=f)

    # Chart area
    chart_left = 120
    chart_right = width - 120
    chart_top = 520
    chart_bottom = 1100
    chart_mid = (chart_top + chart_bottom) // 2
    chart_w = chart_right - chart_left

    # Zero axis
    draw.line([(chart_left, chart_mid), (chart_right, chart_mid)], fill=muted, width=1)
    f = _font(18)
    draw.text((chart_right + 8, chart_mid - 10), "零轴", fill=muted, font=f)

    # Histogram bars
    bar_count = 14
    bar_w = chart_w // (bar_count * 2)
    heights = [30, 48, 62, 40, -35, -52, -25, 18, 38, 55, 42, -20, -30, 15]
    for i, h in enumerate(heights):
        x = chart_left + (i * 2 + 1) * bar_w
        bar_h = abs(h) * 2
        if h > 0:
            y0 = chart_mid - bar_h
            y1 = chart_mid
            draw.rounded_rectangle([x, y0, x + bar_w, y1], radius=3, fill=green)
        else:
            y0 = chart_mid
            y1 = chart_mid + bar_h
            draw.rounded_rectangle([x, y0, x + bar_w, y1], radius=3, fill=red)

    # DIF line (gold)
    dif_points = [
        (chart_left + 10, chart_mid + 20),
        (chart_left + chart_w * 0.1, chart_mid - 10),
        (chart_left + chart_w * 0.2, chart_mid - 30),
        (chart_left + chart_w * 0.3, chart_mid - 50),
        (chart_left + chart_w * 0.35, chart_mid - 20),
        (chart_left + chart_w * 0.45, chart_mid + 10),
        (chart_left + chart_w * 0.5, chart_mid + 40),
        (chart_left + chart_w * 0.6, chart_mid + 20),
        (chart_left + chart_w * 0.7, chart_mid - 15),
        (chart_left + chart_w * 0.8, chart_mid - 35),
        (chart_left + chart_w * 0.9, chart_mid - 20),
        (chart_right - 10, chart_mid - 10),
    ]
    for i in range(len(dif_points) - 1):
        draw.line([dif_points[i], dif_points[i + 1]], fill=gold, width=3)

    # DEA line (blue)
    dea_points = [
        (chart_left + 10, chart_mid + 25),
        (chart_left + chart_w * 0.1, chart_mid + 5),
        (chart_left + chart_w * 0.2, chart_mid - 15),
        (chart_left + chart_w * 0.3, chart_mid - 35),
        (chart_left + chart_w * 0.35, chart_mid - 10),
        (chart_left + chart_w * 0.45, chart_mid + 15),
        (chart_left + chart_w * 0.5, chart_mid + 30),
        (chart_left + chart_w * 0.6, chart_mid + 10),
        (chart_left + chart_w * 0.7, chart_mid - 5),
        (chart_left + chart_w * 0.8, chart_mid - 20),
        (chart_left + chart_w * 0.9, chart_mid - 12),
        (chart_right - 10, chart_mid - 5),
    ]
    for i in range(len(dea_points) - 1):
        draw.line([dea_points[i], dea_points[i + 1]], fill=blue, width=3)

    # Golden cross marker
    gc_x = chart_left + int(chart_w * 0.58)
    gc_y = chart_mid - 10
    draw.ellipse([gc_x - 14, gc_y - 14, gc_x + 14, gc_y + 14], outline=gold, width=2)
    f = _font(16)
    draw.text((gc_x - 16, gc_y + 18), "金叉", fill=gold, font=f)

    # Legend
    legend_y = chart_bottom + 40
    legend_items = [
        ("DIF 快线", gold), ("DEA 慢线", blue),
        ("红柱", green), ("绿柱", red),
    ]
    lx = chart_left
    for label, color in legend_items:
        draw.ellipse([lx, legend_y, lx + 12, legend_y + 12], fill=color)
        f = _font(20)
        draw.text((lx + 18, legend_y - 2), label, fill=white, font=f)
        lx += 180


def _draw_kdj_chart(draw, width, height, title, sub, gold, white, muted, green, red, blue, _font):
    """KDJ 指标图"""
    if title:
        f = _font(56)
        bbox = draw.textbbox((0, 0), title, font=f)
        draw.text(((width - bbox[2] + bbox[0]) // 2, 320), title, fill=gold, font=f)
    if sub:
        f = _font(28)
        bbox = draw.textbbox((0, 0), sub, font=f)
        draw.text(((width - bbox[2] + bbox[0]) // 2, 400), sub, fill=white, font=f)

    cl, cr = 120, width - 120
    ct, cb = 520, 1050
    cw = cr - cl
    mid80 = ct + int((cb - ct) * 0.2)
    mid20 = ct + int((cb - ct) * 0.8)

    # 超买超卖区域
    draw.rectangle([cl, ct, cr, mid80], fill=(239, 68, 68, 25))
    draw.rectangle([cl, mid20, cr, cb], fill=(34, 197, 94, 25))
    draw.line([(cl, mid80), (cr, mid80)], fill=red, width=1)
    draw.line([(cl, mid20), (cr, mid20)], fill=green, width=1)
    f = _font(16)
    draw.text((cr + 8, mid80 - 10), "超买 80", fill=red, font=f)
    draw.text((cr + 8, mid20 - 10), "超卖 20", fill=green, font=f)

    # K 线 (gold)
    k_pts = [(cl + i * cw // 13, ct + int((cb - ct) * (0.3 + 0.15 * (1 if i % 3 == 0 else -1) * (i % 5) / 5))) for i in range(14)]
    for i in range(len(k_pts) - 1):
        draw.line([k_pts[i], k_pts[i + 1]], fill=gold, width=3)

    # D 线 (blue) - 更平滑
    d_pts = [(cl + i * cw // 13, ct + int((cb - ct) * (0.35 + 0.1 * (1 if i % 4 == 0 else -1) * (i % 6) / 6))) for i in range(14)]
    for i in range(len(d_pts) - 1):
        draw.line([d_pts[i], d_pts[i + 1]], fill=blue, width=3)

    # J 线 (purple) - 波动最大
    purple = (168, 85, 247)
    j_pts = [(cl + i * cw // 13, ct + int((cb - ct) * (0.25 + 0.25 * (1 if i % 2 == 0 else -1) * (i % 3) / 3))) for i in range(14)]
    for i in range(len(j_pts) - 1):
        draw.line([j_pts[i], j_pts[i + 1]], fill=purple, width=2)

    legend_y = cb + 40
    lx = cl
    for label, color in [("K 线", gold), ("D 线", blue), ("J 线", purple)]:
        draw.ellipse([lx, legend_y, lx + 12, legend_y + 12], fill=color)
        draw.text((lx + 18, legend_y - 2), label, fill=white, font=_font(20))
        lx += 160


def _draw_ma_chart(draw, width, height, title, sub, gold, white, muted, green, red, blue, _font):
    """均线图"""
    if title:
        f = _font(56)
        bbox = draw.textbbox((0, 0), title, font=f)
        draw.text(((width - bbox[2] + bbox[0]) // 2, 320), title, fill=gold, font=f)
    if sub:
        f = _font(28)
        bbox = draw.textbbox((0, 0), sub, font=f)
        draw.text(((width - bbox[2] + bbox[0]) // 2, 400), sub, fill=white, font=f)

    cl, cr = 120, width - 120
    ct, cb = 520, 1050
    cw = cr - cl

    # K 线背景 (灰色)
    k_base = [(cl + i * cw // 19, ct + int((cb - ct) * (0.4 + 0.15 * ((-1) ** i) * (i % 5) / 5))) for i in range(20)]
    for i in range(len(k_base) - 1):
        draw.line([k_base[i], k_base[i + 1]], fill=(100, 116, 139), width=2)

    # MA5 (gold)
    ma5 = [(cl + i * cw // 19, ct + int((cb - ct) * (0.42 + 0.12 * ((-1) ** i) * (i % 4) / 4))) for i in range(20)]
    for i in range(len(ma5) - 1):
        draw.line([ma5[i], ma5[i + 1]], fill=gold, width=3)

    # MA10 (blue)
    ma10 = [(cl + i * cw // 19, ct + int((cb - ct) * (0.45 + 0.08 * ((-1) ** i) * (i % 6) / 6))) for i in range(20)]
    for i in range(len(ma10) - 1):
        draw.line([ma10[i], ma10[i + 1]], fill=blue, width=3)

    # MA20 (green)
    ma20 = [(cl + i * cw // 19, ct + int((cb - ct) * (0.48 + 0.05 * ((-1) ** i) * (i % 8) / 8))) for i in range(20)]
    for i in range(len(ma20) - 1):
        draw.line([ma20[i], ma20[i + 1]], fill=green, width=3)

    legend_y = cb + 40
    lx = cl
    for label, color in [("K 线", (100, 116, 139)), ("MA5", gold), ("MA10", blue), ("MA20", green)]:
        draw.ellipse([lx, legend_y, lx + 12, legend_y + 12], fill=color)
        draw.text((lx + 18, legend_y - 2), label, fill=white, font=_font(20))
        lx += 160


def _draw_volume_chart(draw, width, height, title, sub, gold, white, muted, green, red, blue, _font):
    """成交量图"""
    if title:
        f = _font(56)
        bbox = draw.textbbox((0, 0), title, font=f)
        draw.text(((width - bbox[2] + bbox[0]) // 2, 320), title, fill=gold, font=f)
    if sub:
        f = _font(28)
        bbox = draw.textbbox((0, 0), sub, font=f)
        draw.text(((width - bbox[2] + bbox[0]) // 2, 400), sub, fill=white, font=f)

    cl, cr = 120, width - 120
    ct, cb = 520, 1000
    cw = cr - cl
    bar_count = 16
    bar_w = cw // (bar_count * 2)
    volumes = [30, 45, 55, 40, 65, 80, 60, 35, 50, 70, 90, 75, 45, 55, 40, 60]
    max_vol = max(volumes)

    for i, v in enumerate(volumes):
        x = cl + (i * 2 + 1) * bar_w
        bar_h = int((v / max_vol) * (cb - ct - 40))
        y0 = cb - bar_h
        color = green if i % 3 != 0 else red
        draw.rounded_rectangle([x, y0, x + bar_w, cb], radius=3, fill=color)

    # 放量标注
    peak_idx = volumes.index(max(volumes))
    peak_x = cl + (peak_idx * 2 + 1) * bar_w + bar_w // 2
    peak_y = cb - int((max_vol / max_vol) * (cb - ct - 40)) - 20
    draw.text((peak_x - 20, peak_y), "放量", fill=gold, font=_font(20))

    legend_y = cb + 40
    lx = cl
    for label, color in [("上涨量", green), ("下跌量", red), ("放量", gold)]:
        draw.ellipse([lx, legend_y, lx + 12, legend_y + 12], fill=color)
        draw.text((lx + 18, legend_y - 2), label, fill=white, font=_font(20))
        lx += 160


def _draw_sr_chart(draw, width, height, title, sub, gold, white, muted, green, red, blue, _font):
    """支撑压力图"""
    if title:
        f = _font(56)
        bbox = draw.textbbox((0, 0), title, font=f)
        draw.text(((width - bbox[2] + bbox[0]) // 2, 320), title, fill=gold, font=f)
    if sub:
        f = _font(28)
        bbox = draw.textbbox((0, 0), sub, font=f)
        draw.text(((width - bbox[2] + bbox[0]) // 2, 400), sub, fill=white, font=f)

    cl, cr = 120, width - 120
    ct, cb = 520, 1050
    cw = cr - cl
    support_y = cb - 120
    resist_y = ct + 120

    # 支撑线 (green)
    draw.line([(cl, support_y), (cr, support_y)], fill=green, width=2)
    f = _font(20)
    draw.text((cr + 8, support_y - 10), "支撑位", fill=green, font=f)

    # 压力线 (red)
    draw.line([(cl, resist_y), (cr, resist_y)], fill=red, width=2)
    draw.text((cr + 8, resist_y - 10), "压力位", fill=red, font=f)

    # 价格走势
    price_pts = [
        (cl + 10, ct + 200),
        (cl + cw * 0.15, ct + 180),
        (cl + cw * 0.25, support_y + 20),
        (cl + cw * 0.35, ct + 250),
        (cl + cw * 0.45, resist_y - 20),
        (cl + cw * 0.55, ct + 200),
        (cl + cw * 0.65, support_y + 30),
        (cl + cw * 0.75, ct + 280),
        (cl + cw * 0.85, resist_y - 10),
        (cr - 10, ct + 220),
    ]
    for i in range(len(price_pts) - 1):
        draw.line([price_pts[i], price_pts[i + 1]], fill=white, width=2)

    # 触碰标记
    for px, py in [price_pts[2], price_pts[6]]:
        draw.ellipse([px - 8, py - 8, px + 8, py + 8], fill=green)
    for px, py in [price_pts[4], price_pts[8]]:
        draw.ellipse([px - 8, py - 8, px + 8, py + 8], fill=red)

    legend_y = cb + 40
    lx = cl
    for label, color in [("价格", white), ("支撑", green), ("压力", red)]:
        draw.ellipse([lx, legend_y, lx + 12, legend_y + 12], fill=color)
        draw.text((lx + 18, legend_y - 2), label, fill=white, font=_font(20))
        lx += 140


def _draw_stoploss_chart(draw, width, height, title, sub, gold, white, muted, green, red, blue, _font):
    """止损路径图"""
    if title:
        f = _font(56)
        bbox = draw.textbbox((0, 0), title, font=f)
        draw.text(((width - bbox[2] + bbox[0]) // 2, 320), title, fill=gold, font=f)
    if sub:
        f = _font(28)
        bbox = draw.textbbox((0, 0), sub, font=f)
        draw.text(((width - bbox[2] + bbox[0]) // 2, 400), sub, fill=white, font=f)

    cl, cr = 120, width - 120
    ct, cb = 520, 1050
    cw = cr - cl
    sl_y = ct + 300

    # 止损线 (red dashed)
    for x in range(cl, cr, 12):
        draw.line([(x, sl_y), (min(x + 6, cr), sl_y)], fill=red, width=2)
    f = _font(20)
    draw.text((cr + 8, sl_y - 10), "止损线", fill=red, font=f)

    # 买入点
    buy_x = cl + int(cw * 0.2)
    buy_y = sl_y - 80
    draw.ellipse([buy_x - 10, buy_y - 10, buy_x + 10, buy_y + 10], fill=green)
    draw.text((buy_x - 16, buy_y + 16), "买入", fill=green, font=f)

    # 价格路径：先涨后跌破
    price_pts = [
        (cl + 10, buy_y),
        (cl + cw * 0.15, buy_y - 40),
        (cl + cw * 0.25, buy_y - 20),
        (cl + cw * 0.35, buy_y + 30),
        (cl + cw * 0.45, sl_y - 10),
        (cl + cw * 0.55, sl_y + 15),
        (cl + cw * 0.65, sl_y + 60),
        (cl + cw * 0.75, sl_y + 100),
        (cr - 10, sl_y + 140),
    ]
    for i in range(len(price_pts) - 1):
        draw.line([price_pts[i], price_pts[i + 1]], fill=white, width=2)

    # 跌破标记
    break_x = cl + int(cw * 0.52)
    draw.ellipse([break_x - 12, sl_y - 12, break_x + 12, sl_y + 12], fill=red)
    draw.text((break_x - 20, sl_y + 18), "跌破止损", fill=red, font=f)

    legend_y = cb + 40
    lx = cl
    for label, color in [("价格", white), ("买入点", green), ("止损线", red)]:
        draw.ellipse([lx, legend_y, lx + 12, legend_y + 12], fill=color)
        draw.text((lx + 18, legend_y - 2), label, fill=white, font=_font(20))
        lx += 160
