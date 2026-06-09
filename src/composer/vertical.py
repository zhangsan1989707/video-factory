"""Vertical short-video composer."""

from pathlib import Path

from moviepy import AudioClip, AudioFileClip, ImageSequenceClip, concatenate_audioclips
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import numpy as np
from rich.console import Console

from src.models import AssetManifest, ShotPlan, VideoScript
from src.utils.config import VIDEO_FPS, VIDEO_WIDTH_V, VIDEO_HEIGHT_V

console = Console()

BG = (2, 20, 38)
GRID = (11, 53, 80)
PANEL = (7, 27, 51)
PANEL_SOFT = (10, 35, 62)
TEXT_MAIN = (245, 248, 255)
TEXT_BODY = (215, 227, 245)
TEXT_MUTED = (127, 163, 200)
STAR_GREEN = (46, 242, 194)
RANK_YELLOW = (255, 216, 77)
LINE_BLUE = (74, 93, 117)


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


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _appear(progress: float, start: float = 0.0, end: float = 0.6) -> float:
    if end <= start:
        return 1.0
    return _ease(_clamp01((progress - start) / (end - start)))


def _fade(fill: tuple[int, int, int], opacity: float) -> tuple[int, int, int, int]:
    return (*fill, int(255 * _clamp01(opacity)))


def _open_asset(asset_path: str) -> Image.Image | None:
    if not asset_path:
        return None
    try:
        return Image.open(asset_path).convert("RGB")
    except Exception:
        return None


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


def _hotlist_bg(asset_path: str, width: int, height: int, progress: float = 0.0) -> Image.Image:
    try:
        asset = Image.open(asset_path).convert("RGB")
        bg = _cover_crop(asset, width, height).filter(ImageFilter.GaussianBlur(radius=34))
        frame = bg.convert("RGBA")
        frame.alpha_composite(Image.new("RGBA", (width, height), (*BG, 224)))
    except Exception:
        frame = Image.new("RGBA", (width, height), (*BG, 255))

    draw = ImageDraw.Draw(frame)
    drift = int(progress * 10)
    for x in range(-96 + drift, width, 96):
        draw.line((x, 0, x, height), fill=(*GRID, 22), width=1)
    for y in range(-96 + drift, height, 96):
        draw.line((0, y, width, y), fill=(*GRID, 18), width=1)

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    pulse = int(8 * np.sin(progress * np.pi))
    glow_draw.ellipse((190, 190, width - 190, 1030), fill=(0, 145, 150, 18 + pulse))
    glow_draw.ellipse((-240, 300, 500, 1030), fill=(0, 80, 180, 18))
    glow_draw.ellipse((570, -160, 1220, 560), fill=(0, 180, 160, 14))
    frame.alpha_composite(glow.filter(ImageFilter.GaussianBlur(96)))
    return frame


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, y: int, font, fill, width: int) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (bbox[2] - bbox[0])) // 2, y), text, fill=fill, font=font)
    return bbox[3] - bbox[1]


def _draw_glow_centered(frame: Image.Image, text: str, y: int, font, fill, width: int, glow_alpha: int = 34) -> int:
    layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    bbox = layer_draw.textbbox((0, 0), text, font=font)
    x = (width - (bbox[2] - bbox[0])) // 2
    alpha = fill[3] if len(fill) > 3 else 255
    layer_draw.text((x, y), text, fill=(*TEXT_MAIN, int(glow_alpha * alpha / 255)), font=font)
    frame.alpha_composite(layer.filter(ImageFilter.GaussianBlur(10)))
    ImageDraw.Draw(frame).text((x, y), text, fill=fill, font=font)
    return bbox[3] - bbox[1]


def _draw_pill(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, font, fill=(20, 153, 255, 80)) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0] + 42
    h = bbox[3] - bbox[1] + 24
    draw.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=fill, outline=(70, 185, 255, 120), width=1)
    draw.text((x + 21, y + 10), text, fill=(235, 247, 255, 245), font=font)
    return w


def _draw_rank_tag(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, body: str, width: int, opacity: float = 1.0) -> None:
    accent_font = _font(34)
    body_font = _font(40)
    accent_bbox = draw.textbbox((0, 0), text, font=accent_font)
    body_lines = _wrap_text(body, body_font, width - x - 190)[:1]
    body_text = body_lines[0] if body_lines else body
    dot_r = 8
    draw.ellipse((x, y + 28, x + dot_r * 2, y + 28 + dot_r * 2), fill=(*LINE_BLUE, int(220 * opacity)))
    draw.text((x + 36, y), text, fill=(*TEXT_MUTED, int(220 * opacity)), font=accent_font)
    draw.text((x + 36 + accent_bbox[2] - accent_bbox[0] + 20, y - 4), body_text, fill=(*TEXT_BODY, int(245 * opacity)), font=body_font)


def _treatment_parts(treatment: str) -> list[str]:
    return treatment.split(":")


def _draw_voice_subtitle(frame: Image.Image, subtitle: str, width: int, height: int) -> None:
    draw = ImageDraw.Draw(frame)
    subtitle_font = _font(42)
    box_w = int(width * 0.84)
    box_x = (width - box_w) // 2
    lines = _wrap_text(subtitle, subtitle_font, box_w - 72)
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = _short_text(lines[-1], 18)
    box_h = 36 + len(lines) * 58
    box_y = height - 292
    draw.rounded_rectangle(
        (box_x, box_y, box_x + box_w, box_y + box_h),
        radius=18,
        fill=(0, 0, 0, 150),
        outline=(*LINE_BLUE, 80),
        width=1,
    )
    y = box_y + 20
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=subtitle_font)
        draw.text(((width - (bbox[2] - bbox[0])) // 2, y), line, fill=(*TEXT_BODY, 248), font=subtitle_font)
        y += 58


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


def _hotlist_rows(treatment: str) -> list[str]:
    parts = _treatment_parts(treatment)
    return parts[1].split(";") if len(parts) > 1 and parts[1] else []


def _draw_micro_footer(draw: ImageDraw.ImageDraw, text: str, width: int, height: int) -> None:
    font = _font(28)
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (bbox[2] - bbox[0])) // 2, height - 106), text, fill=(*TEXT_MUTED, 118), font=font)


def _draw_centered_in_rect(draw: ImageDraw.ImageDraw, text: str, rect: tuple[int, int, int, int], font, fill) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    x = rect[0] + ((rect[2] - rect[0]) - (bbox[2] - bbox[0])) // 2
    y = rect[1] + ((rect[3] - rect[1]) - (bbox[3] - bbox[1])) // 2
    draw.text((x, y), text, fill=fill, font=font)
    return bbox[3] - bbox[1]


def _row_name(row: str) -> str:
    text = row.split(" ", 1)[1] if row.startswith("#") and " " in row else row
    if " Star" in text:
        return text.rsplit(" ", 2)[0]
    return text


def _draw_screenshot_panel(
    frame: Image.Image,
    asset_path: str,
    x: int,
    y: int,
    w: int,
    h: int,
    progress: float,
) -> bool:
    asset = _open_asset(asset_path)
    if asset is None:
        return False

    appear = _appear(progress, 0.28, 0.68)
    if appear <= 0:
        return True

    draw = ImageDraw.Draw(frame)
    top = y + int((1 - appear) * 28)
    alpha = int(255 * appear)
    shadow = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((20, 20, w + 20, h + 20), radius=24, fill=(0, 0, 0, int(115 * appear)))
    frame.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)), (x - 20, top - 20))

    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel)
    panel_draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=22, fill=(*PANEL_SOFT, int(238 * appear)), outline=(*LINE_BLUE, int(120 * appear)), width=2)
    chrome_h = 42
    panel_draw.rounded_rectangle((0, 0, w - 1, chrome_h), radius=22, fill=(13, 41, 70, int(245 * appear)))
    panel_draw.rectangle((0, chrome_h - 18, w - 1, chrome_h), fill=(13, 41, 70, int(245 * appear)))
    for i, color in enumerate(((255, 95, 87), (255, 189, 46), (40, 201, 64))):
        panel_draw.ellipse((24 + i * 30, 14, 40 + i * 30, 30), fill=(*color, int(180 * appear)))

    visual = _contain(asset, w - 34, h - chrome_h - 30)
    zoom = 1.0 + 0.018 * _ease(progress)
    visual = visual.resize((int(visual.width * zoom), int(visual.height * zoom)), Image.Resampling.LANCZOS).convert("RGBA")
    visual.putalpha(alpha)
    vx = (w - visual.width) // 2
    vy = chrome_h + 14 + (h - chrome_h - 30 - visual.height) // 2
    panel.alpha_composite(visual, (vx, vy))
    frame.alpha_composite(panel, (x, top))
    draw.rounded_rectangle((x, top, x + w, top + h), radius=22, outline=(*TEXT_MAIN, int(28 * appear)), width=1)
    return True


def _draw_fallback_signal(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, progress: float) -> None:
    appear = _appear(progress, 0.28, 0.68)
    top = y + int((1 - appear) * 28)
    draw.rounded_rectangle((x, top, x + w, top + h), radius=22, fill=(*PANEL, int(164 * appear)), outline=(*LINE_BLUE, int(105 * appear)), width=2)
    label_font = _font(36)
    value_font = _font(58)
    _draw_centered_in_rect(draw, "项目信号", (x, top + 46, x + w, top + 104), label_font, _fade(TEXT_MUTED, appear))
    items = ("README", "GitHub", "开源趋势")
    iy = top + 164
    for i, item in enumerate(items):
        item_appear = _appear(progress, 0.38 + i * 0.08, 0.78 + i * 0.08)
        draw.ellipse((x + 86, iy + 18, x + 104, iy + 36), fill=_fade(LINE_BLUE, item_appear))
        draw.text((x + 132, iy), item, fill=_fade(TEXT_BODY, item_appear), font=value_font if i == 0 else _font(44))
        iy += 92


def _render_opening_frame(shot_title: str, subtitle: str, asset_path: str, progress: float, width: int, height: int) -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height, progress)
    draw = ImageDraw.Draw(frame)
    name = _project_name(shot_title)
    subtitle_line = "Top 10 开源项目速览" if "热榜" in name else name
    small_font = _font(38)
    title_font = _font(112)
    date_font = _font(42)

    a1 = _appear(progress, 0.0, 0.35)
    a2 = _appear(progress, 0.12, 0.52)
    a3 = _appear(progress, 0.32, 0.72)
    _draw_centered(draw, "GitHub 热榜", 268 - int((1 - a1) * 24), small_font, _fade(TEXT_MUTED, a1 * 0.9), width)
    _draw_glow_centered(frame, "本期热榜", 448 - int((1 - a2) * 32), title_font, _fade(TEXT_MAIN, a2), width)
    _draw_centered(draw, subtitle_line, 622, _font(58), _fade(TEXT_BODY, a2 * 0.96), width)
    line_w = int((width - 420) * a3)
    draw.line((width // 2 - line_w // 2, 780, width // 2 + line_w // 2, 780), fill=_fade(LINE_BLUE, a3 * 0.86), width=3)
    _draw_centered(draw, "1 秒看懂是什么，3 秒判断值不值得看", 840, date_font, _fade(TEXT_MUTED, a3), width)
    _draw_voice_subtitle(frame, subtitle, width, height)
    _draw_micro_footer(draw, "关注我 · 看热榜", width, height)
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
    frame = _hotlist_bg(asset_path, width, height, progress)
    draw = ImageDraw.Draw(frame)
    rows = _hotlist_rows(treatment)
    max_rows = min(10, len(rows))
    row_spacing = min(96, (height - 660) // max(max_rows, 1))
    title_a = _appear(progress, 0.0, 0.38)
    _draw_centered(draw, "GitHub 本期热榜", 176 - int((1 - title_a) * 24), _font(78), _fade(TEXT_MAIN, title_a), width)
    _draw_centered(draw, "Top 10 开源项目速览", 276, _font(36), _fade(TEXT_MUTED, title_a), width)
    y = 384
    for i, row in enumerate(rows[:max_rows], start=1):
        appear = _appear(progress, 0.12 + (i - 1) * 0.045, 0.48 + (i - 1) * 0.045)
        x = 84 + int((1 - appear) * 44)
        row_h = 72
        fill = (*PANEL, int(112 + 54 * appear))
        outline = (*LINE_BLUE, int(36 + 58 * appear))
        draw.rounded_rectangle((x, y, width - 84, y + row_h), radius=15, fill=fill, outline=outline, width=1)
        rank_fill = RANK_YELLOW if i == 1 else TEXT_MUTED
        draw.text((x + 26, y + 17), f"#{i}", fill=_fade(rank_fill, appear), font=_font(32))
        row_text = row.split(" ", 1)[1] if row.startswith("#") and " " in row else row
        if " Star" in row_text:
            name_part, stars_part = row_text.rsplit(" ", 2)[0], " ".join(row_text.rsplit(" ", 2)[1:])
            draw.text((x + 102, y + 17), _short_text(name_part, 18), fill=_fade(TEXT_BODY, appear), font=_font(32))
            stars_bbox = draw.textbbox((0, 0), stars_part, font=_font(30))
            draw.text((width - 112 - (stars_bbox[2] - stars_bbox[0]), y + 19), stars_part, fill=_fade(STAR_GREEN, appear), font=_font(30))
        else:
            draw.text((x + 102, y + 17), _short_text(row_text, 28), fill=_fade(TEXT_BODY, appear), font=_font(32))
        y += row_spacing
    _draw_voice_subtitle(frame, subtitle, width, height)
    return frame.convert("RGB")


def _render_hotlist_rank_card_frame(subtitle: str, treatment: str, asset_path: str, progress: float, width: int, height: int) -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height, progress)
    draw = ImageDraw.Draw(frame)
    parts = _treatment_parts(treatment)
    rank = parts[1] if len(parts) > 1 else "1"
    name = parts[2] if len(parts) > 2 else "GitHub 项目"
    stars_text = parts[3] if len(parts) > 3 else "Star"
    hook = parts[4] if len(parts) > 4 else ""
    detail_raw = parts[5] if len(parts) > 5 else ""
    details = detail_raw.split("|") if detail_raw else []

    hook_appear = _appear(progress, 0.0, 0.34)
    if hook:
        hook_font = _font(34)
        hook_text = _short_text(hook, 22)
        bbox = draw.textbbox((0, 0), hook_text, font=hook_font)
        pill_w = min(width - 160, bbox[2] - bbox[0] + 56)
        pill_x = (width - pill_w) // 2
        pill_y = 144 - int((1 - hook_appear) * 18)
        draw.rounded_rectangle((pill_x, pill_y, pill_x + pill_w, pill_y + 62), radius=20, fill=_fade(PANEL, hook_appear * 0.72), outline=_fade(LINE_BLUE, hook_appear * 0.45), width=1)
        _draw_centered(draw, hook_text, pill_y + 13, hook_font, _fade(TEXT_MUTED, hook_appear), width)

    title_font = _font(112)
    title_lines = _wrap_text(name, title_font, width - 180)[:2]
    title_y = 264
    title_appear = _appear(progress, 0.08, 0.48)
    for line in title_lines:
        _draw_glow_centered(frame, line, title_y - int((1 - title_appear) * 30), title_font, _fade(TEXT_MAIN, title_appear), width)
        title_y += 126

    meta_y = title_y + 2
    meta_appear = _appear(progress, 0.2, 0.58)
    stars_font = _font(58)
    stars_bbox = draw.textbbox((0, 0), stars_text, font=stars_font)
    stars_w = stars_bbox[2] - stars_bbox[0]
    stars_x = (width - stars_w) // 2
    draw.text((stars_x, meta_y), stars_text, fill=_fade(STAR_GREEN, meta_appear * 0.96), font=stars_font)
    badge_x = stars_x - 116
    badge_y = meta_y + 6
    if badge_x < 80:
        badge_x = width - 190
    badge_pop = 1 + int(8 * (1 - abs(meta_appear - 0.72)) * meta_appear)
    draw.rounded_rectangle((badge_x - badge_pop, badge_y - badge_pop, badge_x + 84 + badge_pop, badge_y + 54 + badge_pop), radius=18, fill=_fade(RANK_YELLOW, meta_appear * 0.94))
    draw.text((badge_x + 14, badge_y + 7), f"#{rank}", fill=_fade(BG, meta_appear), font=_font(34))

    bar_y = meta_y + 88
    bar_w = int(width * 0.44)
    bar_x = (width - bar_w) // 2
    fill_ratio = _appear(progress, 0.28, 0.72)
    fill_w = int(bar_w * fill_ratio)
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + 14), radius=7, fill=(*LINE_BLUE, 118))
    if fill_w > 0:
        draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + 14), radius=7, fill=(*LINE_BLUE, 205))

    visual_y = bar_y + 62
    has_asset_panel = _draw_screenshot_panel(frame, asset_path, 108, visual_y, width - 216, 430, progress)
    if not has_asset_panel:
        _draw_fallback_signal(draw, 108, visual_y, width - 216, 430, progress)

    if len(details) >= 3:
        tag_y = visual_y + 488
        labels = ["解决", "亮点", "适合"]
        for idx, (label, text) in enumerate(zip(labels, details)):
            row_appear = _appear(progress, 0.36 + idx * 0.06, 0.64 + idx * 0.06)
            iy = tag_y + idx * 94 + int((1 - row_appear) * 22)
            if row_appear <= 0:
                continue
            _draw_rank_tag(draw, label, 112, iy, str(text), width, row_appear)

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


def _render_plain_closing_frame(subtitle: str, asset_path: str, progress: float, width: int, height: int, treatment: str = "") -> Image.Image:
    frame = _hotlist_bg(asset_path, width, height, progress)
    draw = ImageDraw.Draw(frame)
    title_a = _appear(progress, 0.0, 0.42)
    tag_a = _appear(progress, 0.22, 0.68)
    cta_a = _appear(progress, 0.48, 0.88)
    _draw_centered(draw, "下期拆哪个方向？", 360 - int((1 - title_a) * 30), _font(70), _fade(TEXT_MAIN, title_a), width)
    rows = _hotlist_rows(treatment)
    tags = []
    if rows:
        tags = [_short_text(_row_name(row), 10) for row in rows[:4]]
    if not tags:
        tags = ["AI", "运维", "独立开发", "工具站"]

    tag_font = _font(42)
    rows_to_draw = [tags[:2], tags[2:4]]
    for row_idx, tag_row in enumerate(rows_to_draw):
        if not tag_row:
            continue
        widths = []
        for tag in tag_row:
            bbox = draw.textbbox((0, 0), tag, font=tag_font)
            widths.append(min(300, bbox[2] - bbox[0] + 44))
        total_w = sum(widths) + (len(tag_row) - 1) * 18
        x = max(70, (width - total_w) // 2)
        for col_idx, tag in enumerate(tag_row):
            i = row_idx * 2 + col_idx
            item_a = _appear(progress, 0.2 + i * 0.06, 0.66 + i * 0.06) * tag_a
            y = 534 + row_idx * 86 + int((1 - item_a) * 18)
            draw.rounded_rectangle((x, y, x + widths[col_idx], y + 68), radius=18, fill=_fade(PANEL, item_a * 0.76), outline=_fade(LINE_BLUE, item_a * 0.52), width=1)
            _draw_centered_in_rect(draw, tag, (x, y, x + widths[col_idx], y + 68), tag_font, _fade(TEXT_BODY, item_a))
            x += widths[col_idx] + 18

    draw.line((250, 772, width - 250, 772), fill=_fade(LINE_BLUE, cta_a * 0.84), width=3)
    _draw_centered(draw, "评论区告诉我", 834, _font(56), _fade(TEXT_BODY, cta_a), width)
    _draw_voice_subtitle(frame, subtitle, width, height)
    _draw_micro_footer(draw, "关注我 · 下期见", width, height)
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
        return _render_plain_closing_frame(subtitle, asset_path, progress, width, height, treatment)
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
