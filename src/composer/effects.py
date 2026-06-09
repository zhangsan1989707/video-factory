"""视觉特效模块"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np
from pathlib import Path


def create_gradient_background(width: int, height: int, color1: tuple, color2: tuple) -> Image.Image:
    """创建渐变背景"""
    img = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(img)

    for y in range(height):
        # 计算渐变颜色
        r = int(color1[0] + (color2[0] - color1[0]) * y / height)
        g = int(color1[1] + (color2[1] - color1[1]) * y / height)
        b = int(color1[2] + (color2[2] - color1[2]) * y / height)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    return img


def create_title_card(
    title: str,
    subtitle: str,
    width: int = 1920,
    height: int = 1080,
    duration_frames: int = 90,
) -> list[Image.Image]:
    """创建开场标题卡片（带动画）"""
    frames = []

    # 渐变背景
    bg = create_gradient_background(width, height, (15, 23, 42), (30, 58, 138))

    for i in range(duration_frames):
        frame = bg.copy()
        draw = ImageDraw.Draw(frame)
        progress = i / duration_frames

        # 标题淡入动画
        alpha = min(255, int(255 * progress * 2))
        title_y = height // 2 - 50 + int(30 * (1 - progress))

        # 标题文字
        try:
            font_large = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 72)
            font_small = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 36)
        except:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # 绘制标题（居中）
        title_bbox = draw.textbbox((0, 0), title, font=font_large)
        title_x = (width - title_bbox[2]) // 2
        draw.text((title_x, title_y), title, fill=(255, 255, 255, alpha), font=font_large)

        # 副标题延迟淡入
        if progress > 0.3:
            sub_alpha = min(255, int(255 * (progress - 0.3) * 2))
            sub_bbox = draw.textbbox((0, 0), subtitle, font=font_small)
            sub_x = (width - sub_bbox[2]) // 2
            draw.text((sub_x, title_y + 100), subtitle, fill=(148, 163, 184, sub_alpha), font=font_small)

        # 装饰线条
        if progress > 0.5:
            line_alpha = min(100, int(100 * (progress - 0.5) * 2))
            line_width = int(200 * (progress - 0.5) * 2)
            line_x = (width - line_width) // 2
            draw.line(
                [(line_x, title_y + 80), (line_x + line_width, title_y + 80)],
                fill=(96, 165, 250, line_alpha),
                width=2,
            )

        frames.append(frame)

    return frames


def create_info_card(
    icon: str,
    title: str,
    value: str,
    width: int = 400,
    height: int = 200,
    bg_color: tuple = (30, 41, 59),
) -> Image.Image:
    """创建信息卡片"""
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆角矩形背景
    draw.rounded_rectangle(
        [(0, 0), (width, height)],
        radius=16,
        fill=bg_color,
        outline=(51, 65, 85),
        width=1,
    )

    try:
        font_icon = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 48)
        font_title = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 20)
        font_value = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 36)
    except:
        font_icon = ImageFont.load_default()
        font_title = ImageFont.load_default()
        font_value = ImageFont.load_default()

    # 图标
    draw.text((30, 30), icon, fill=(96, 165, 250), font=font_icon)

    # 数值
    draw.text((30, 90), value, fill=(255, 255, 255), font=font_value)

    # 标题
    draw.text((30, 140), title, fill=(148, 163, 184), font=font_title)

    return img


def create_feature_card(
    title: str,
    description: str,
    number: str,
    width: int = 500,
    height: int = 160,
) -> Image.Image:
    """创建功能特性卡片"""
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 背景
    draw.rounded_rectangle(
        [(0, 0), (width, height)],
        radius=12,
        fill=(30, 41, 59),
        outline=(51, 65, 85),
        width=1,
    )

    # 左侧数字标识
    draw.rounded_rectangle(
        [(15, 15), (55, 55)],
        radius=8,
        fill=(59, 130, 246),
    )

    try:
        font_num = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 24)
        font_title = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 28)
        font_desc = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 18)
    except:
        font_num = ImageFont.load_default()
        font_title = ImageFont.load_default()
        font_desc = ImageFont.load_default()

    # 数字
    draw.text((25, 20), number, fill=(255, 255, 255), font=font_num)

    # 标题
    draw.text((75, 20), title, fill=(255, 255, 255), font=font_title)

    # 描述
    draw.text((75, 60), description, fill=(148, 163, 184), font=font_desc)

    return img


def create_cta_card(
    text: str = "⭐ Star 收藏",
    width: int = 400,
    height: int = 80,
) -> Image.Image:
    """创建行动号召卡片"""
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 渐变按钮
    for x in range(width):
        r = int(59 + (37, 99, 235)[0] * x / width)
        g = int(130 + (37, 99, 235)[1] * x / width)
        b = int(246 + (37, 99, 235)[2] * x / width)
        draw.line([(x, 0), (x, height)], fill=(r, g, b))

    # 圆角遮罩
    mask = Image.new('L', (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([(0, 0), (width, height)], radius=40, fill=255)

    try:
        font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 32)
    except:
        font = ImageFont.load_default()

    # 文字
    bbox = draw.textbbox((0, 0), text, font=font)
    text_x = (width - bbox[2]) // 2
    text_y = (height - bbox[3]) // 2
    draw.text((text_x, text_y), text, fill=(255, 255, 255), font=font)

    return img


def create_highlight_overlay(
    frame: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    progress: float,
) -> Image.Image:
    """创建高亮覆盖层"""
    overlay = frame.copy()
    draw = ImageDraw.Draw(overlay)

    # 高亮光晕效果
    for i in range(3):
        offset = int(5 * progress)
        alpha = int(60 * (1 - progress))
        draw.rectangle(
            [x - offset - i * 3, y - offset - i * 3, x + w + offset + i * 3, y + h + offset + i * 3],
            outline=(96, 165, 250, alpha),
            width=2,
        )

    return overlay


def create_transition_frames(
    frame1: Image.Image,
    frame2: Image.Image,
    num_frames: int = 15,
    transition_type: str = "fade",
) -> list[Image.Image]:
    """创建转场帧"""
    frames = []

    for i in range(num_frames):
        progress = i / num_frames

        if transition_type == "fade":
            # 淡入淡出
            alpha = int(255 * progress)
            blended = Image.blend(frame1, frame2, progress)
            frames.append(blended)

        elif transition_type == "slide":
            # 滑动转场
            offset = int(frame1.width * progress)
            new_frame = Image.new('RGB', frame1.size)
            new_frame.paste(frame1, (-offset, 0))
            new_frame.paste(frame2, (frame1.width - offset, 0))
            frames.append(new_frame)

    return frames


def add_particles(
    frame: Image.Image,
    num_particles: int = 20,
) -> Image.Image:
    """添加粒子效果"""
    overlay = frame.copy()
    draw = ImageDraw.Draw(overlay)

    for _ in range(num_particles):
        x = np.random.randint(0, frame.width)
        y = np.random.randint(0, frame.height)
        size = np.random.randint(2, 6)
        alpha = np.random.randint(50, 150)

        draw.ellipse(
            [x, y, x + size, y + size],
            fill=(96, 165, 250, alpha),
        )

    return overlay
