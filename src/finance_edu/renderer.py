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

        template_id = scene.get("template_id", "")
        title = scene.get("title", "")
        sub = scene.get("subtitle", "")
        bullets = scene.get("bullets", [])

        _TEMPLATE_RENDERERS = {
            "hook_title": _render_hook,
            "myth_vs_truth": _render_myth,
            "concept_card": _render_concept,
            "indicator_chart": _render_chart,
            "three_points": _render_three,
            "risk_warning": _render_risk,
            "summary_quote": _render_summary,
        }
        renderer = _TEMPLATE_RENDERERS.get(template_id, _render_generic)
        renderer(draw, width, height, title, sub, bullets, scene, gold, white, muted, card, green, red, blue, _font)

        risk = scene.get("risk_note", "")
        if risk and template_id != "risk_warning":
            f = _font(22)
            text = f"⚠ {risk}"
            bbox = draw.textbbox((0, 0), text, font=f)
            tw = bbox[2] - bbox[0]
            draw.text(((width - tw) // 2, height - 280), text, fill=red, font=f)

        target = output_dir / f"preview_{scene.get('scene_id', 'unknown')}.png"
        img.save(target)
        preview_paths.append(target)

    return preview_paths


def _render_hook(draw, w, h, title, sub, bullets, scene, gold, white, muted, card, green, red, blue, _font):
    """Hook 开场：大标题 + 徽章"""
    # 徽章
    badge_text = "• 科普小课堂"
    bf = _font(24)
    bb = draw.textbbox((0, 0), badge_text, font=bf)
    bw = bb[2] - bb[0] + 48
    bx = (w - bw) // 2
    by = 480
    draw.rounded_rectangle([bx, by, bx + bw, by + 44], radius=22, fill=None, outline=gold, width=1)
    draw.text((bx + 24, by + 8), badge_text, fill=gold, font=bf)

    # 标题
    if title:
        f = _font(80)
        bbox = draw.textbbox((0, 0), title, font=f)
        tw = bbox[2] - bbox[0]
        draw.text(((w - tw) // 2, 580), title, fill=gold, font=f)

    # 副标题
    if sub:
        f = _font(34)
        bbox = draw.textbbox((0, 0), sub, font=f)
        tw = bbox[2] - bbox[0]
        draw.text(((w - tw) // 2, 700), sub, fill=white, font=f)


def _render_myth(draw, w, h, title, sub, bullets, scene, gold, white, muted, card, green, red, blue, _font):
    """误区对比：标题 + 左右两栏"""
    if title:
        f = _font(60)
        bbox = draw.textbbox((0, 0), title, font=f)
        draw.text(((w - bbox[2] + bbox[0]) // 2, 300), title, fill=gold, font=f)
    if sub:
        f = _font(28)
        bbox = draw.textbbox((0, 0), sub, font=f)
        draw.text(((w - bbox[2] + bbox[0]) // 2, 390), sub, fill=white, font=f)

    # 左栏：误区
    lx, rx = 100, w // 2 + 30
    lw, rw = w // 2 - 130, w // 2 - 130
    card_top = 480
    card_h = 500

    draw.rounded_rectangle([lx, card_top, lx + lw, card_top + card_h], radius=20, fill=card, outline=red, width=1)
    draw.rounded_rectangle([rx, card_top, rx + rw, card_top + card_h], radius=20, fill=card, outline=green, width=1)

    # 左栏标签
    draw.text((lx + 24, card_top + 20), "✗ 常见误区", fill=red, font=_font(24))
    # 左栏内容
    y = card_top + 70
    for b in bullets[:3]:
        draw.text((lx + 24, y), f"•  {b}", fill=muted, font=_font(26))
        y += 52

    # 右栏标签
    draw.text((rx + 24, card_top + 20), "✓ 正确理解", fill=green, font=_font(24))
    # 右栏内容
    right_items = ["只是观察工具", "需要结合其他信号", "不能单独使用"]
    y = card_top + 70
    for item in right_items:
        draw.text((rx + 24, y), f"•  {item}", fill=white, font=_font(26))
        y += 52


def _render_concept(draw, w, h, title, sub, bullets, scene, gold, white, muted, card, green, red, blue, _font):
    """概念卡片：带装饰的卡片"""
    margin = 80
    card_top = 380
    card_bottom = 1050
    draw.rounded_rectangle([margin, card_top, w - margin, card_bottom], radius=24, fill=card, outline=(242, 201, 76, 60), width=1)

    # 眼眉标签
    draw.text((margin + 40, card_top + 30), "概念", fill=gold, font=_font(22))

    # 标题
    if title:
        f = _font(60)
        draw.text((margin + 40, card_top + 70), title, fill=white, font=f)

    # 分割线
    draw.line([(margin + 40, card_top + 155), (margin + 140, card_top + 155)], fill=gold, width=4)

    # 副标题
    if sub:
        draw.text((margin + 40, card_top + 175), sub, fill=muted, font=_font(30))

    # 要点标签
    y = card_top + 240
    for b in bullets[:3]:
        bb = draw.textbbox((0, 0), b, font=_font(26))
        bw = bb[2] - bb[0] + 40
        draw.rounded_rectangle([margin + 40, y, margin + 40 + bw, y + 48], radius=12, fill=(242, 201, 76, 30), outline=(242, 201, 76, 80), width=1)
        draw.text((margin + 60, y + 10), b, fill=white, font=_font(26))
        y += 68


def _render_chart(draw, w, h, title, sub, bullets, scene, gold, white, muted, card, green, red, blue, _font):
    """图表场景：委托给专业图表绘制器"""
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
    drawer(draw, w, h, title, sub, gold, white, muted, green, red, blue, _font)


def _render_three(draw, w, h, title, sub, bullets, scene, gold, white, muted, card, green, red, blue, _font):
    """三点卡片：编号卡片"""
    if title:
        f = _font(60)
        bbox = draw.textbbox((0, 0), title, font=f)
        draw.text(((w - bbox[2] + bbox[0]) // 2, 320), title, fill=gold, font=f)
    if sub:
        f = _font(28)
        bbox = draw.textbbox((0, 0), sub, font=f)
        draw.text(((w - bbox[2] + bbox[0]) // 2, 410), sub, fill=white, font=f)

    card_top = 500
    card_h = 150
    card_gap = 24
    margin = 100
    for i, b in enumerate(bullets[:3]):
        y = card_top + i * (card_h + card_gap)
        draw.rounded_rectangle([margin, y, w - margin, y + card_h], radius=18, fill=card)

        # 编号圆圈
        cx = margin + 50
        cy = y + card_h // 2
        draw.ellipse([cx - 24, cy - 24, cx + 24, cy + 24], fill=(242, 201, 76, 40), outline=gold, width=2)
        nf = _font(28)
        nb = draw.textbbox((0, 0), str(i + 1), font=nf)
        draw.text((cx - (nb[2] - nb[0]) // 2, cy - (nb[3] - nb[1]) // 2), str(i + 1), fill=gold, font=nf)

        # 文字
        draw.text((margin + 100, y + card_h // 2 - 16), b, fill=white, font=_font(30))


def _render_risk(draw, w, h, title, sub, bullets, scene, gold, white, muted, card, green, red, blue, _font):
    """风险提醒：红色边框 + 警告图标"""
    margin = 80
    card_top = 380
    card_bottom = 1100
    draw.rounded_rectangle([margin, card_top, w - margin, card_bottom], radius=24, fill=card, outline=red, width=2)

    # 警告图标
    icon_x = margin + 40
    icon_y = card_top + 30
    draw.polygon([(icon_x + 20, icon_y), (icon_x, icon_y + 36), (icon_x + 40, icon_y + 36)], outline=white, width=2)
    draw.text((icon_x + 14, icon_y + 8), "!", fill=white, font=_font(20))

    # 标题
    if title:
        draw.text((margin + 40, card_top + 60), title, fill=red, font=_font(56))

    # 副标题
    if sub:
        draw.text((margin + 40, card_top + 140), sub, fill=white, font=_font(28))

    # 要点
    y = card_top + 200
    for b in bullets[:3]:
        # 感叹号圆圈
        bx = margin + 50
        draw.ellipse([bx, y + 2, bx + 28, y + 30], fill=(239, 68, 68, 40), outline=red, width=1)
        draw.text((bx + 8, y + 4), "!", fill=red, font=_font(18))
        draw.text((margin + 90, y), b, fill=white, font=_font(28))
        y += 56

    # 风险提示底栏
    risk_note = scene.get("risk_note", "")
    if risk_note:
        note_y = card_bottom - 70
        draw.rounded_rectangle([margin + 20, note_y, w - margin - 20, note_y + 50], radius=10, fill=(239, 68, 68, 20))
        draw.text(((w - draw.textbbox((0, 0), risk_note, font=_font(22))[2] + draw.textbbox((0, 0), risk_note, font=_font(22))[0]) // 2, note_y + 12), risk_note, fill=red, font=_font(22))


def _render_summary(draw, w, h, title, sub, bullets, scene, gold, white, muted, card, green, red, blue, _font):
    """总结金句：引用风格"""
    margin = 80
    card_top = 400
    card_bottom = 1050
    draw.rounded_rectangle([margin, card_top, w - margin, card_bottom], radius=24, fill=card)

    # 眼眉
    draw.text(((w - draw.textbbox((0, 0), "总结", font=_font(22))[2] + draw.textbbox((0, 0), "总结", font=_font(22))[0]) // 2, card_top + 30), "总结", fill=gold, font=_font(22))

    # 标题
    if title:
        f = _font(52)
        bbox = draw.textbbox((0, 0), title, font=f)
        draw.text(((w - bbox[2] + bbox[0]) // 2, card_top + 70), title, fill=white, font=f)

    # 分割线
    draw.line([(w // 2 - 30, card_top + 145), (w // 2 + 30, card_top + 145)], fill=gold, width=3)

    # 引用内容
    if sub:
        f = _font(34)
        bbox = draw.textbbox((0, 0), sub, font=f)
        draw.text(((w - bbox[2] + bbox[0]) // 2, card_top + 170), sub, fill=muted, font=f)

    # 风险提示
    disclaimer = "以上内容仅作知识科普，不构成投资建议"
    df = _font(20)
    db = draw.textbbox((0, 0), disclaimer, font=df)
    draw.rounded_rectangle([(w - db[2] + db[0]) // 2 - 16, card_bottom - 80, (w + db[2] - db[0]) // 2 + 16, card_bottom - 40], radius=8, fill=(242, 201, 76, 15))
    draw.text(((w - db[2] + db[0]) // 2, card_bottom - 75), disclaimer, fill=muted, font=df)


def _render_generic(draw, w, h, title, sub, bullets, scene, gold, white, muted, card, green, red, blue, _font):
    """通用回退"""
    margin = 48
    draw.rounded_rectangle([margin, 200, w - margin, h - 200], radius=24, fill=card)
    if title:
        f = _font(64)
        bbox = draw.textbbox((0, 0), title, font=f)
        draw.text(((w - bbox[2] + bbox[0]) // 2, 440), title, fill=gold, font=f)
    if sub:
        f = _font(32)
        bbox = draw.textbbox((0, 0), sub, font=f)
        draw.text(((w - bbox[2] + bbox[0]) // 2, 540), sub, fill=white, font=f)
    if bullets:
        f = _font(28)
        y = 660
        for b in bullets[:3]:
            text = f"•  {b}"
            bbox = draw.textbbox((0, 0), text, font=f)
            draw.text(((w - bbox[2] + bbox[0]) // 2, y), text, fill=muted, font=f)
            y += 60


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
