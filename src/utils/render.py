"""公共渲染工具函数

提取自 vertical.py、desktop_review.py、effects.py、mouse.py 等模块的重复代码。
"""

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from src.utils.config import CJK_FONT_PATH


@lru_cache(maxsize=32)
def get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """获取缓存的中文字体对象，避免重复加载字体文件"""
    if CJK_FONT_PATH:
        try:
            return ImageFont.truetype(CJK_FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()


def ease_out(t: float) -> float:
    """缓动函数：ease-out（减速停止）"""
    return 1 - (1 - t) * (1 - t)


def ease_in_out(t: float) -> float:
    """缓动函数：平滑的加速-减速"""
    if t < 0.5:
        return 2 * t * t
    return 1 - (-2 * t + 2) ** 2 / 2


def clamp01(value: float) -> float:
    """将值限制在 [0.0, 1.0] 范围内"""
    return max(0.0, min(1.0, value))


def short_text(text: str, limit: int) -> str:
    """截断过长文本"""
    text = " ".join(text.replace("\n", " ").split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def create_cursor(size: int = 70) -> Image.Image:
    """创建鼠标指针图像

    Args:
        size: 指针画布尺寸，默认 70px
    """
    scale = size / 70
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 外框（黑色阴影）
    outline = [
        (int(8 * scale), int(6 * scale)),
        (int(8 * scale), int(56 * scale)),
        (int(22 * scale), int(42 * scale)),
        (int(34 * scale), int(64 * scale)),
        (int(44 * scale), int(58 * scale)),
        (int(32 * scale), int(36 * scale)),
        (int(52 * scale), int(34 * scale)),
    ]
    draw.polygon(outline, fill=(0, 0, 0, 230))
    # 内部（白色填充）
    inner = [
        (int(13 * scale), int(14 * scale)),
        (int(13 * scale), int(47 * scale)),
        (int(23 * scale), int(37 * scale)),
        (int(35 * scale), int(57 * scale)),
        (int(39 * scale), int(55 * scale)),
        (int(29 * scale), int(31 * scale)),
        (int(43 * scale), int(30 * scale)),
    ]
    draw.polygon(inner, fill=(255, 255, 255, 255))
    return img


def wrap_text(text: str, font, max_width: int) -> list[str]:
    """自动换行文本"""
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


def cover_crop(img: Image.Image, width: int, height: int) -> Image.Image:
    """裁剪图片以覆盖目标尺寸（居中裁剪）"""
    src_w, src_h = img.size
    scale = max(width / src_w, height / src_h)
    new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
    resized = img.resize(new_size, Image.Resampling.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def contain(img: Image.Image, width: int, height: int) -> Image.Image:
    """缩放图片以适应目标尺寸（保持比例，留白）"""
    src_w, src_h = img.size
    scale = min(width / src_w, height / src_h)
    new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
    return img.resize(new_size, Image.Resampling.LANCZOS)
