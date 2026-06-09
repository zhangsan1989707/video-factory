"""Vertical short-video composer."""

from pathlib import Path

from moviepy import AudioClip, AudioFileClip, ImageSequenceClip, concatenate_audioclips
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import numpy as np
from rich.console import Console

from src.models import AssetManifest, ShotPlan, VideoScript
from src.utils.config import VIDEO_FPS, VIDEO_WIDTH_V, VIDEO_HEIGHT_V

console = Console()


def _font(size: int):
    try:
        return ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", size)
    except Exception:
        return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    lines = []
    current = ""
    for char in text:
        test = current + char
        width = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), test, font=font)[2]
        if width > max_width and current:
            lines.append(current)
            current = char
        else:
            current = test
    if current:
        lines.append(current)
    return lines[:4]


def _short_text(text: str, limit: int) -> str:
    text = " ".join(text.replace("\n", " ").split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _asset_map(manifest: AssetManifest) -> dict[str, str]:
    return {asset.id: asset.path for asset in manifest.assets}


def _cover_crop(img: Image.Image, width: int, height: int) -> Image.Image:
    src_w, src_h = img.size
    scale = max(width / src_w, height / src_h)
    new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
    resized = img.resize(new_size, Image.Resampling.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _contain(img: Image.Image, width: int, height: int) -> Image.Image:
    src_w, src_h = img.size
    scale = min(width / src_w, height / src_h)
    new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
    return img.resize(new_size, Image.Resampling.LANCZOS)


def _ease(t: float) -> float:
    return 1 - (1 - t) * (1 - t)


def _cursor() -> Image.Image:
    img = Image.new("RGBA", (70, 70), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    points = [(8, 6), (8, 56), (22, 42), (34, 64), (44, 58), (32, 36), (52, 34)]
    draw.polygon(points, fill=(0, 0, 0, 230))
    inner = [(13, 14), (13, 47), (23, 37), (35, 57), (39, 55), (29, 31), (43, 30)]
    draw.polygon(inner, fill=(255, 255, 255, 255))
    return img


def _target_rect(kind: str, card_x: int, card_y: int, visual_w: int, visual_h: int) -> tuple[int, int, int, int]:
    if "hero" in kind:
        return (card_x + 45, card_y + int(visual_h * 0.44), card_x + int(visual_w * 0.48), card_y + int(visual_h * 0.62))
    if "modes" in kind:
        return (card_x + 45, card_y + int(visual_h * 0.50), card_x + int(visual_w * 0.50), card_y + int(visual_h * 0.58))
    if "detail" in kind:
        return (card_x + int(visual_w * 0.60), card_y + int(visual_h * 0.33), card_x + int(visual_w * 0.94), card_y + int(visual_h * 0.68))
    if "stars" in kind:
        return (card_x + int(visual_w * 0.74), card_y + 70, card_x + int(visual_w * 0.96), card_y + 145)
    if "source" in kind:
        return (card_x + 42, card_y + 72, card_x + int(visual_w * 0.55), card_y + 142)
    return (card_x + int(visual_w * 0.58), card_y + int(visual_h * 0.40), card_x + int(visual_w * 0.92), card_y + int(visual_h * 0.66))


def _hint_text(treatment: str) -> str:
    if "hook" in treatment:
        return "先看结论"
    if "modes" in treatment:
        return "练习模式"
    if "detail" in treatment:
        return "核心价值"
    if "cta" in treatment:
        return "值得推荐"
    if "stars" in treatment:
        return "来源验证"
    if "closing" in treatment:
        return "继续筛工具"
    return "真实页面"


def _project_name(title: str) -> str:
    if "：" in title:
        return title.split("：", 1)[1].strip()
    if ":" in title:
        return title.split(":", 1)[1].strip()
    return title.strip()


def _hotlist_bg(asset_path: str, width: int, height: int) -> Image.Image:
    try:
        asset = Image.open(asset_path).convert("RGB")
        bg = _cover_crop(asset, width, height).filter(ImageFilter.GaussianBlur(radius=34))
        frame = bg.convert("RGBA")
        frame.alpha_composite(Image.new("RGBA", (width, height), (4, 14, 29, 205)))
    except Exception:
        frame = Image.new("RGBA", (width, height), (5, 18, 36, 255))

    draw = ImageDraw.Draw(frame)
    for x in range(0, width, 96):
        draw.line((x, 0, x, height), fill=(38, 93, 135, 16), width=1)
    for y in range(0, height, 96):
        draw.line((0, y, width, y), fill=(38, 93, 135, 14), width=1)

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((160, 170, width - 160, 1040), fill=(0, 190, 180, 22))
    glow_draw.ellipse((-220, 260, 520, 1000), fill=(0, 140, 255, 28))
    glow_draw.ellipse((520, -140, 1260, 620), fill=(0, 220, 180, 22))
    frame.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)))
    return frame


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, y: int, font, fill, width: int) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (bbox[2] - bbox[0])) // 2, y), text, fill=fill, font=font)
    return bbox[3] - bbox[1]


def _draw_pill(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, font, fill=(20, 153, 255, 80)) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0] + 42
    h = bbox[3] - bbox[1] + 24
    draw.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=fill, outline=(70, 185, 255, 120), width=1)
    draw.text((x + 21, y + 10), text, fill=(235, 247, 255, 245), font=font)
    return w


def _draw_rank_tag(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, body: str, width: int) -> None:
    accent_font = _font(34)
    body_font = _font(40)
    accent_bbox = draw.textbbox((0, 0), text, font=accent_font)
    body_lines = _wrap_text(body, body_font, width - x - 190)[:1]
    body_text = body_lines[0] if body_lines else body
    dot_r = 8
    draw.ellipse((x, y + 28, x + dot_r * 2, y + 28 + dot_r * 2), fill=(29, 235, 160, 220))
    draw.text((x + 36, y), text, fill=(120, 185, 245, 220), font=accent_font)
    draw.text((x + 36 + accent_bbox[2] - accent_bbox[0] + 20, y - 4), body_text, fill=(238, 247, 255, 245), font=body_font)


def _treatment_parts(treatment: str) -> list[str]:
    return treatment.split(":")


def _draw_voice_subtitle(frame: Image.Image, subtitle: str, width: int, height: int) -> None:
    draw = ImageDraw.Draw(frame)
    subtitle_font = _font(46)
    box_w = int(width * 0.86)
    box_x = (width - box_w) // 2
    lines = _wrap_text(subtitle, subtitle_font, box_w - 72)
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = _short_text(lines[-1], 18)
    box_h = 38 + len(lines) * 62
    box_y = height - 320
    draw.rounded_rectangle((box_x, box_y, box_x + box_w, box_y + box_h), radius=24, fill=(0, 0, 0, 132))
    y = box_y + 22
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=subtitle_font)
        draw.text(((width - (bbox[2] - bbox[0])) // 2, y), line, fill=(255, 255, 255, 248), font=subtitle_font)
        y += 62


def _split_points(text: str) -> list[str]:
    for prefix in ("我会先看三件事：", "我会先看三件事:"):
        text = text.replace(prefix, "")
    parts = []
    current = ""
    for char in text:
        if char in "；;。":
            if current.strip():
                parts.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current.strip())
    return parts[:3] or [text]


def _render_opening_frame(shot_title: str, subtitle: str, asset_path: str, progress: float, width: int, height: int) -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height)
    draw = ImageDraw.Draw(frame)
    name = _project_name(shot_title)
    small_font = _font(40)
    title_font = _font(116)
    date_font = _font(44)

    alpha = int(80 + 175 * min(1.0, progress * 2.2))
    _draw_centered(draw, "GitHub 热榜", 250, small_font, (210, 225, 240, alpha), width)
    _draw_centered(draw, "热榜观察", 470, title_font, (255, 255, 255, alpha), width)
    _draw_centered(draw, name, 620, title_font, (28, 170, 255, alpha), width)
    draw.line((230, 780, width - 230, 780), fill=(25, 165, 255, 180), width=3)
    _draw_centered(draw, "第 1 名 Star 数是第 10 名的 10 倍", 840, date_font, (255, 220, 44, alpha), width)
    _draw_voice_subtitle(frame, subtitle, width, height)
    draw.text((width // 2 - 82, height - 104), "关注我 · 看热榜", fill=(180, 200, 220, 110), font=_font(30))
    return frame.convert("RGB")


def _render_single_hook_frame(subtitle: str, treatment: str, asset_path: str, progress: float, width: int, height: int) -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height)
    draw = ImageDraw.Draw(frame)
    parts = _treatment_parts(treatment)
    name = parts[1] if len(parts) > 1 else "GitHub 项目"
    stars = parts[2] if len(parts) > 2 else "Star"
    _draw_centered(draw, stars, 310, _font(122), (255, 220, 44, 250), width)
    _draw_centered(draw, name, 500, _font(92), (255, 255, 255, 250), width)
    _draw_centered(draw, "它能解决什么问题？", 640, _font(48), (28, 170, 255, 240), width)
    _draw_voice_subtitle(frame, subtitle, width, height)
    return frame.convert("RGB")


def _render_single_judgment_frame(subtitle: str, treatment: str, asset_path: str, progress: float, width: int, height: int) -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height)
    draw = ImageDraw.Draw(frame)
    parts = _treatment_parts(treatment)
    name = parts[1] if len(parts) > 1 else "这个项目"
    _draw_centered(draw, "我的判断", 280, _font(54), (190, 215, 235, 190), width)
    _draw_centered(draw, name, 410, _font(92), (255, 255, 255, 250), width)
    draw.rounded_rectangle((126, 640, width - 126, 980), radius=30, fill=(8, 31, 58, 175), outline=(45, 160, 255, 130), width=2)
    _draw_centered(draw, "不是普通工具介绍", 710, _font(56), (255, 255, 255, 245), width)
    _draw_centered(draw, "而是一个能带来启发的产品样本", 810, _font(50), (28, 170, 255, 240), width)
    _draw_voice_subtitle(frame, subtitle, width, height)
    return frame.convert("RGB")


def _render_single_project_card_frame(subtitle: str, treatment: str, asset_path: str, progress: float, width: int, height: int) -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height)
    draw = ImageDraw.Draw(frame)
    parts = _treatment_parts(treatment)
    name = parts[1] if len(parts) > 1 else "GitHub 项目"
    language = parts[2] if len(parts) > 2 else "开源"
    _draw_centered(draw, name, 270, _font(92), (255, 255, 255, 250), width)
    _draw_centered(draw, "项目观察卡", 400, _font(46), (190, 215, 235, 190), width)
    x = 170
    for tag in ("能做什么", "带来什么", "为什么推荐", language):
        x += _draw_pill(draw, tag, x, 560, _font(36)) + 16
        if x > width - 260:
            x = 170
    draw.rounded_rectangle((110, 760, width - 110, 1120), radius=28, fill=(10, 30, 54, 170), outline=(55, 170, 255, 130), width=2)
    for i, point in enumerate(("真实页面", "README 证据", "源码来源"), start=1):
        y = 810 + (i - 1) * 88
        draw.text((170, y), f"0{i}", fill=(30, 180, 255, 235), font=_font(38))
        draw.text((260, y), point, fill=(245, 250, 255, 240), font=_font(42))
    _draw_voice_subtitle(frame, subtitle, width, height)
    return frame.convert("RGB")


def _render_ranking_frame(shot_title: str, subtitle: str, asset_path: str, progress: float, width: int, height: int) -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height)
    draw = ImageDraw.Draw(frame)
    name = _project_name(shot_title)
    title_font = _font(96)
    row_font = _font(42)
    meta_font = _font(36)

    _draw_centered(draw, "本期观察", 170, meta_font, (190, 215, 235, 180), width)
    _draw_centered(draw, "GitHub 热榜雷达", 250, title_font, (255, 255, 255, 245), width)

    rows = [name, "真实页面", "README 证据", "适合人群", "收藏再试"]
    y = 500
    for i, row in enumerate(rows, start=1):
        appear = min(1.0, max(0.0, progress * 4 - (i - 1) * 0.35))
        x = 78 + int((1 - _ease(appear)) * 60)
        fill = (12, 32, 58, int(120 + 80 * appear))
        outline = (25, 150, 255, int(70 + 90 * appear))
        draw.rounded_rectangle((x, y, width - 78, y + 82), radius=18, fill=fill, outline=outline, width=2)
        rank_color = (255, 218, 40, 240) if i == 1 else (110, 170, 220, 210)
        draw.text((x + 28, y + 20), f"#{i}", fill=rank_color, font=row_font)
        draw.text((x + 132, y + 20), row, fill=(246, 250, 255, 238), font=row_font)
        if i == 1:
            draw.text((width - 250, y + 23), "HOT", fill=(29, 235, 160, 230), font=meta_font)
        y += 105

    _draw_voice_subtitle(frame, subtitle, width, height)
    return frame.convert("RGB")


def _render_hotlist_ranking_frame(subtitle: str, treatment: str, asset_path: str, progress: float, width: int, height: int) -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height)
    draw = ImageDraw.Draw(frame)
    parts = _treatment_parts(treatment)
    rows = parts[1].split(";") if len(parts) > 1 and parts[1] else []
    max_rows = min(10, len(rows))
    row_spacing = min(105, (height - 580) // max(max_rows, 1))
    _draw_centered(draw, "GitHub 本期热榜", 180, _font(82), (255, 255, 255, 248), width)
    y = 350
    for i, row in enumerate(rows[:max_rows], start=1):
        appear = min(1.0, max(0.0, progress * 4 - (i - 1) * 0.25))
        draw.rounded_rectangle((78, y, width - 78, y + 82), radius=16, fill=(12, 32, 58, int(125 + 70 * appear)), outline=(25, 150, 255, int(70 + 90 * appear)), width=2)
        color = (255, 218, 40, 245) if i == 1 else (95, 175, 235, 225)
        draw.text((112, y + 20), row, fill=color if i == 1 else (246, 250, 255, 238), font=_font(34))
        y += row_spacing
    _draw_voice_subtitle(frame, subtitle, width, height)
    return frame.convert("RGB")


def _render_hotlist_rank_card_frame(subtitle: str, treatment: str, asset_path: str, progress: float, width: int, height: int) -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height)
    draw = ImageDraw.Draw(frame)
    parts = _treatment_parts(treatment)
    rank = parts[1] if len(parts) > 1 else "1"
    name = parts[2] if len(parts) > 2 else "GitHub 项目"
    stars_text = parts[3] if len(parts) > 3 else "Star"
    hook = parts[4] if len(parts) > 4 else ""
    detail_raw = parts[5] if len(parts) > 5 else ""
    details = detail_raw.split("|") if detail_raw else []

    if hook:
        hook_font = _font(34)
        hook_text = _short_text(hook, 22)
        bbox = draw.textbbox((0, 0), hook_text, font=hook_font)
        pill_w = min(width - 160, bbox[2] - bbox[0] + 56)
        pill_x = (width - pill_w) // 2
        draw.rounded_rectangle((pill_x, 154, pill_x + pill_w, 216), radius=20, fill=(10, 30, 54, 145), outline=(255, 214, 34, 95), width=1)
        _draw_centered(draw, hook_text, 167, hook_font, (255, 220, 60, 235), width)

    title_font = _font(112)
    title_lines = _wrap_text(name, title_font, width - 180)[:2]
    title_y = 270
    for line in title_lines:
        _draw_centered(draw, line, title_y, title_font, (255, 255, 255, 252), width)
        title_y += 126

    meta_y = title_y + 6
    stars_font = _font(58)
    stars_bbox = draw.textbbox((0, 0), stars_text, font=stars_font)
    stars_w = stars_bbox[2] - stars_bbox[0]
    stars_x = (width - stars_w) // 2
    draw.text((stars_x, meta_y), stars_text, fill=(29, 235, 160, 238), font=stars_font)
    badge_x = stars_x - 116
    badge_y = meta_y + 6
    if badge_x < 80:
        badge_x = width - 190
    draw.rounded_rectangle((badge_x, badge_y, badge_x + 84, badge_y + 54), radius=18, fill=(255, 214, 34, 222))
    draw.text((badge_x + 14, badge_y + 7), f"#{rank}", fill=(6, 16, 31, 255), font=_font(34))

    bar_y = meta_y + 88
    bar_w = int(width * 0.44)
    bar_x = (width - bar_w) // 2
    fill_ratio = _ease(min(1.0, progress * 1.8))
    fill_w = int(bar_w * fill_ratio)
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + 14), radius=7, fill=(20, 50, 80, 120))
    if fill_w > 0:
        draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + 14), radius=7, fill=(29, 235, 160, 210))

    if len(details) >= 3:
        tag_y = bar_y + 130
        labels = ["解决", "亮点", "适合"]
        for idx, (label, text) in enumerate(zip(labels, details)):
            iy = tag_y + idx * 104
            _draw_rank_tag(draw, label, 112, iy, str(text), width)

    _draw_voice_subtitle(frame, subtitle, width, height)
    return frame.convert("RGB")


def _render_rank_card_frame(shot_title: str, subtitle: str, asset_path: str, progress: float, width: int, height: int) -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height)
    draw = ImageDraw.Draw(frame)
    name = _project_name(shot_title)
    rank_font = _font(118)
    name_font = _font(74)
    meta_font = _font(34)

    cx = width // 2
    cy = 520
    r = int(118 + 10 * np.sin(progress * np.pi * 2))
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 214, 34, 235))
    _draw_centered(draw, "#1", cy - 58, rank_font, (6, 16, 31, 255), width)
    _draw_centered(draw, name, 720, name_font, (255, 255, 255, 248), width)
    _draw_centered(draw, "值得关注的开源项目", 820, meta_font, (180, 210, 235, 220), width)

    x = 190
    for tag in ("趋势", "证据", "适合谁"):
        x += _draw_pill(draw, tag, x, 960, meta_font) + 18

    draw.rounded_rectangle((120, 1120, width - 120, 1332), radius=28, fill=(10, 30, 54, 180), outline=(55, 170, 255, 130), width=2)
    lines = _wrap_text(subtitle, _font(46), width - 300)
    y = 1170
    for line in lines[:2]:
        _draw_centered(draw, line, y, _font(46), (245, 250, 255, 245), width)
        y += 62

    draw.text((width // 2 - 64, height - 104), name, fill=(180, 200, 220, 110), font=_font(30))
    return frame.convert("RGB")


def _render_breakdown_frame(shot_title: str, subtitle: str, asset_path: str, progress: float, width: int, height: int) -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height)
    draw = ImageDraw.Draw(frame)
    title_font = _font(58)
    item_font = _font(38)
    _draw_centered(draw, "为什么值得看", 210, title_font, (255, 255, 255, 246), width)

    y = 430
    for i, point in enumerate(_split_points(subtitle), start=1):
        appear = min(1.0, max(0.0, progress * 4 - (i - 1) * 0.55))
        top = y + int((1 - _ease(appear)) * 36)
        draw.rounded_rectangle((92, top, width - 92, top + 220), radius=24, fill=(8, 31, 58, int(145 + 45 * appear)), outline=(45, 160, 255, int(70 + 80 * appear)), width=2)
        draw.text((126, top + 34), f"0{i}", fill=(30, 180, 255, 230), font=_font(42))
        lines = _wrap_text(point, item_font, width - 300)
        text_y = top + 42
        for line in lines[:2]:
            draw.text((220, text_y), line, fill=(245, 250, 255, 240), font=item_font)
            text_y += 52
        y += 260

    _draw_voice_subtitle(frame, subtitle, width, height)
    return frame.convert("RGB")


def _render_closing_frame(shot_title: str, subtitle: str, asset_path: str, progress: float, width: int, height: int) -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height)
    draw = ImageDraw.Draw(frame)
    name = _project_name(shot_title)
    _draw_centered(draw, "本期项目", 270, _font(48), (190, 215, 235, 190), width)

    project_text = subtitle.split("。")[0]
    for prefix in ("本期项目：", "本期项目:"):
        project_text = project_text.replace(prefix, "")
    project_text = project_text.replace("你想先看哪个方向？", "")
    tags = [_short_text(tag.strip(), 14) for tag in project_text.split("、") if tag.strip()][:4]
    x = 110
    y = 500
    tag_font = _font(44)
    for tag in tags:
        bbox = draw.textbbox((0, 0), tag, font=tag_font)
        estimated_w = bbox[2] - bbox[0] + 42
        if x + estimated_w > width - 110:
            x = 110
            y += 92
        w = _draw_pill(draw, tag, x, y, tag_font, fill=(20, 153, 255, 96))
        x += w + 22

    _draw_centered(draw, f"{name} 值得先收藏再试", 760, _font(58), (255, 255, 255, 246), width)
    _draw_centered(draw, "你还想看哪个 GitHub 方向？", 870, _font(48), (28, 170, 255, 245), width)
    _draw_voice_subtitle(frame, subtitle, width, height)
    draw.text((width // 2 - 98, height - 104), "关注我 · 下周见", fill=(180, 200, 220, 130), font=_font(30))
    return frame.convert("RGB")


def _render_plain_closing_frame(subtitle: str, asset_path: str, progress: float, width: int, height: int) -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height)
    draw = ImageDraw.Draw(frame)
    _draw_centered(draw, "下期拆哪个方向？", 360, _font(70), (255, 255, 255, 248), width)
    x = 130
    for tag in ("AI", "运维", "独立开发", "工具站"):
        x += _draw_pill(draw, tag, x, 560, _font(44), fill=(20, 153, 255, 96)) + 18
    _draw_centered(draw, "评论区告诉我", 760, _font(56), (28, 170, 255, 245), width)
    _draw_voice_subtitle(frame, subtitle, width, height)
    draw.text((width // 2 - 98, height - 104), "关注我 · 下期见", fill=(180, 200, 220, 130), font=_font(30))
    return frame.convert("RGB")


def _render_frame(
    shot_title: str,
    subtitle: str,
    asset_path: str,
    treatment: str,
    progress: float,
    width: int,
    height: int,
) -> Image.Image:
    if treatment == "hotlist_opening":
        return _render_opening_frame("GitHub 本期热榜", subtitle, asset_path, progress, width, height)
    if treatment.startswith("hotlist_ranking"):
        return _render_hotlist_ranking_frame(subtitle, treatment, asset_path, progress, width, height)
    if treatment.startswith("hotlist_rank_card"):
        return _render_hotlist_rank_card_frame(subtitle, treatment, asset_path, progress, width, height)
    if treatment.startswith("hotlist_closing"):
        return _render_plain_closing_frame(subtitle, asset_path, progress, width, height)
    if treatment.startswith("single_hook"):
        return _render_single_hook_frame(subtitle, treatment, asset_path, progress, width, height)
    if treatment.startswith("single_judgment"):
        return _render_single_judgment_frame(subtitle, treatment, asset_path, progress, width, height)
    if treatment.startswith("single_project_card"):
        return _render_single_project_card_frame(subtitle, treatment, asset_path, progress, width, height)
    if treatment == "single_closing":
        return _render_plain_closing_frame(subtitle, asset_path, progress, width, height)
    if treatment == "opening_trend":
        return _render_opening_frame(shot_title, subtitle, asset_path, progress, width, height)
    if treatment == "ranking_overview":
        return _render_ranking_frame(shot_title, subtitle, asset_path, progress, width, height)
    if treatment == "rank_card":
        return _render_rank_card_frame(shot_title, subtitle, asset_path, progress, width, height)
    if treatment == "feature_breakdown":
        return _render_breakdown_frame(shot_title, subtitle, asset_path, progress, width, height)
    if treatment == "keyword_closing":
        return _render_closing_frame(shot_title, subtitle, asset_path, progress, width, height)

    try:
        asset = Image.open(asset_path).convert("RGB")
    except Exception:
        asset = Image.new("RGB", (1280, 900), (246, 248, 250))

    frame = _hotlist_bg(asset_path, width, height)
    draw = ImageDraw.Draw(frame)

    title_font = _font(50)
    subtitle_font = _font(46)
    note_font = _font(26)
    hint_font = _font(30)

    title_lines = _wrap_text(shot_title, title_font, width - 120)
    y = 96
    for line in title_lines[:2]:
        draw.text((60, y), line, fill=(255, 255, 255, 245), font=title_font)
        y += 62

    visual_h = 1040
    visual_y = 360
    visual = _contain(asset, width - 96, visual_h)
    zoom = 1.0 + 0.035 * _ease(progress)
    visual = visual.resize((int(visual.width * zoom), int(visual.height * zoom)), Image.Resampling.LANCZOS)
    card_x = (width - visual.width) // 2
    card_y = visual_y + (visual_h - visual.height) // 2
    shadow = Image.new("RGBA", (visual.width + 24, visual.height + 24), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((12, 12, visual.width + 12, visual.height + 12), radius=24, fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    frame.alpha_composite(shadow, (card_x - 12, card_y - 12))
    frame.paste(visual, (card_x, card_y))
    draw.rounded_rectangle(
        (card_x, card_y, card_x + visual.width, card_y + visual.height),
        radius=22,
        outline=(255, 255, 255, 90),
        width=2,
    )

    if "pointer" in treatment:
        target = _target_rect(treatment, card_x, card_y, visual.width, visual.height)
        start = (width - 150, height - 470)
        end = (target[0] + 26, target[1] + 28)
        move = min(1.0, progress / 0.45)
        cx = int(start[0] + (end[0] - start[0]) * _ease(move))
        cy = int(start[1] + (end[1] - start[1]) * _ease(move))
        cursor = _cursor()
        frame.alpha_composite(cursor, (cx, cy))

    subtitle_lines = _wrap_text(subtitle, subtitle_font, width - 130)
    box_h = 42 + len(subtitle_lines) * 58
    box_y = height - 250 - box_h // 2
    draw.rounded_rectangle((48, box_y, width - 48, box_y + box_h), radius=24, fill=(0, 0, 0, 132))
    text_y = box_y + 24
    for line in subtitle_lines:
        bbox = draw.textbbox((0, 0), line, font=subtitle_font)
        draw.text(((width - (bbox[2] - bbox[0])) // 2, text_y), line, fill=(255, 255, 255, 245), font=subtitle_font)
        text_y += 58

    draw.text((60, height - 96), "GitHub project review", fill=(255, 255, 255, 145), font=note_font)
    return frame.convert("RGB")


def compose_vertical_video(
    script: VideoScript,
    shot_plan: ShotPlan,
    manifest: AssetManifest,
    audio_dir: Path,
    output_path: Path,
    preview_dir: Path,
    fps: int = VIDEO_FPS,
) -> Path:
    """Render a 1080x1920 short-form video from V2 plan artifacts."""
    asset_paths = _asset_map(manifest)
    audio_clips = []
    audio_durations = []
    for i, _segment in enumerate(script.segments):
        audio_path = audio_dir / f"segment-{i:03d}.mp3"
        if audio_path.exists():
            clip = AudioFileClip(str(audio_path))
            audio_clips.append(clip)
            audio_durations.append(clip.duration)
        else:
            audio_durations.append(_segment.duration)

    frames = []
    preview_dir.mkdir(parents=True, exist_ok=True)
    for i, shot in enumerate(shot_plan.shots):
        segment = script.segments[i] if i < len(script.segments) else None
        subtitle = segment.narration if segment else shot.subtitle
        duration = audio_durations[i] if i < len(audio_durations) else shot.duration
        asset_path = asset_paths.get(shot.visual_asset, "")
        num_frames = max(1, int(duration * fps))
        dynamic_frames = min(num_frames, max(8, int(duration * 5)))
        rendered_frames = []
        preview_frame = None
        for frame_i in range(dynamic_frames):
            progress = frame_i / max(1, dynamic_frames - 1)
            frame = _render_frame(
                shot_plan.title,
                subtitle,
                asset_path,
                shot.visual_treatment,
                progress,
                VIDEO_WIDTH_V,
                VIDEO_HEIGHT_V,
            )
            if frame_i == min(dynamic_frames - 1, max(0, int(dynamic_frames * 0.55))):
                preview_frame = frame
            rendered_frames.append(np.array(frame))
        for frame_i in range(num_frames):
            source_i = min(dynamic_frames - 1, int(frame_i * dynamic_frames / num_frames))
            frames.append(rendered_frames[source_i])
        if preview_frame:
            preview_frame.save(preview_dir / f"shot-{i + 1:02d}.png")

    video_clip = ImageSequenceClip(frames, fps=fps)
    if audio_clips:
        final_audio = concatenate_audioclips(audio_clips)
        video_clip = video_clip.with_audio(final_audio)
    else:
        video_clip = video_clip.with_audio(AudioClip(lambda t: 0, duration=len(frames) / fps, fps=44100))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    console.print("  编码竖屏视频...")
    video_clip.write_videofile(
        str(output_path),
        fps=fps,
        codec="libx264",
        audio_codec="aac",
        bitrate="7000k",
        preset="medium",
        logger=None,
    )
    video_clip.close()
    for clip in audio_clips:
        clip.close()
    console.print(f"  ✓ 竖屏视频已保存到: {output_path}")
    return output_path


def render_vertical_previews(
    script: VideoScript,
    shot_plan: ShotPlan,
    manifest: AssetManifest,
    preview_dir: Path,
) -> list[Path]:
    """Render one static preview image per vertical shot."""
    asset_paths = _asset_map(manifest)
    preview_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, shot in enumerate(shot_plan.shots):
        segment = script.segments[i] if i < len(script.segments) else None
        subtitle = segment.narration if segment else shot.subtitle
        frame = _render_frame(
            shot_plan.title,
            subtitle,
            asset_paths.get(shot.visual_asset, ""),
            shot.visual_treatment,
            0.55,
            VIDEO_WIDTH_V,
            VIDEO_HEIGHT_V,
        )
        path = preview_dir / f"shot-{i + 1:02d}.png"
        frame.save(path)
        paths.append(path)
    return paths
