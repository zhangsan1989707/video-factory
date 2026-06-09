"""鼠标动效引擎"""

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from rich.console import Console

from src.models import VideoScript, ScriptSegment

console = Console()

# 鼠标指针大小（放大版，参考真实系统光标）
CURSOR_SIZE = 48


def create_cursor_image() -> Image.Image:
    """创建大号鼠标指针图像（白色填充 + 黑色描边）"""
    img = Image.new("RGBA", (CURSOR_SIZE, CURSOR_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 箭头形状鼠标指针，在 48px 画布上绘制
    points = [
        (4, 4),       # 左上尖角
        (4, 36),      # 左下
        (12, 28),     # 左侧凹点
        (20, 38),     # 下凸点
        (26, 33),     # 右下凸点
        (18, 22),     # 右侧凹点
        (28, 10),     # 右上
    ]
    # 黑色描边（先画粗描边再画填充）
    draw.polygon(points, fill="black", outline="black", width=3)
    # 白色填充（略小的内层多边形）
    inner_points = [
        (6, 6),
        (6, 34),
        (13, 27),
        (20, 36),
        (25, 32),
        (17, 21),
        (26, 12),
    ]
    draw.polygon(inner_points, fill="white")

    return img


def create_click_effect(size: int = 60) -> Image.Image:
    """创建点击效果（红色光圈）"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    center = size // 2
    radius = size // 2 - 2
    draw.ellipse(
        [center - radius, center - radius, center + radius, center + radius],
        outline=(255, 80, 60, 200),
        width=3,
    )
    return img


def create_selection_effect(
    width: int, height: int, progress: float = 0.0
) -> Image.Image:
    """创建红色选中框特效（带脉冲发光）

    Args:
        width: 选中区域宽度
        height: 选中区域高度
        progress: 0.0-1.0，控制脉冲动画的相位
    """
    padding = 20
    img_w = width + padding * 2
    img_h = height + padding * 2
    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))

    # 脉冲效果：发光范围随 progress 周期性变化
    pulse = 0.5 + 0.5 * math.sin(progress * math.pi * 2)
    glow_expand = int(4 + 6 * pulse)
    glow_alpha = int(80 + 80 * pulse)

    # 外层发光（多层红色半透明矩形）
    for i in range(glow_expand, 0, -1):
        alpha = int(glow_alpha * (1 - i / (glow_expand + 1)))
        draw = ImageDraw.Draw(img)
        draw.rectangle(
            [
                padding - i,
                padding - i,
                padding + width + i,
                padding + height + i,
            ],
            outline=(255, 60, 40, alpha),
            width=2,
        )

    # 内层实线红色边框
    draw = ImageDraw.Draw(img)
    draw.rectangle(
        [padding, padding, padding + width, padding + height],
        outline=(255, 80, 50, 220),
        width=2,
    )

    return img


def calculate_mouse_path(
    start: tuple[int, int],
    end: tuple[int, int],
    num_frames: int,
) -> list[tuple[int, int]]:
    """计算鼠标移动路径（贝塞尔曲线）"""
    if num_frames <= 1:
        return [end]

    points = []
    for i in range(num_frames):
        t = i / (num_frames - 1)

        # 三次贝塞尔曲线，加入轻微随机偏移模拟真人手感
        x = start[0] + (end[0] - start[0]) * t
        y = start[1] + (end[1] - start[1]) * t

        # 添加微小随机抖动（模拟人手）
        if 0 < t < 1:
            x += random.uniform(-2, 2)
            y += random.uniform(-2, 2)

        points.append((int(x), int(y)))

    return points


def get_target_position(
    bounds: dict | None,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int]:
    """获取目标位置"""
    if bounds:
        # 移动到元素中心
        return (
            int(bounds["x"] + bounds["width"] / 2),
            int(bounds["y"] + bounds["height"] / 2),
        )
    # 默认移动到屏幕中央偏右
    return (frame_width * 3 // 4, frame_height // 2)


def render_mouse_on_frame(
    frame: Image.Image,
    mouse_pos: tuple[int, int],
    action: str,
    bounds: dict | None,
    progress: float,
) -> Image.Image:
    """在帧上渲染鼠标和效果

    Args:
        frame: 已加载的 RGBA 帧图像（可能已经过镜头缩放处理）
        mouse_pos: 鼠标在帧上的位置
        action: 动作类型
        bounds: 目标元素边界
        progress: 片段内进度 0.0-1.0
    """
    draw = ImageDraw.Draw(frame)

    # 根据动作类型添加效果
    if action == "highlight" and bounds:
        # 红色选中框（带脉冲）
        x, y = int(bounds["x"]), int(bounds["y"])
        w, h = int(bounds["width"]), int(bounds["height"])
        selection = create_selection_effect(w, h, progress)
        paste_x = x - 10  # padding offset
        paste_y = y - 10
        frame.paste(selection, (paste_x, paste_y), selection)

    elif action == "click" and bounds:
        # 红色选中框 + 点击光圈
        x, y = int(bounds["x"]), int(bounds["y"])
        w, h = int(bounds["width"]), int(bounds["height"])
        selection = create_selection_effect(w, h, progress)
        paste_x = x - 10
        paste_y = y - 10
        frame.paste(selection, (paste_x, paste_y), selection)

        # 点击时光圈扩散
        if progress > 0.6:
            cx, cy = mouse_pos
            radius = int(25 * (progress - 0.6) / 0.4)
            if radius > 0:
                draw = ImageDraw.Draw(frame)
                draw.ellipse(
                    [cx - radius, cy - radius, cx + radius, cy + radius],
                    outline=(255, 80, 50, 180),
                    width=3,
                )

    elif action == "zoom" and bounds:
        # 放大镜效果 + 红色选中框
        x, y = int(bounds["x"]), int(bounds["y"])
        w, h = int(bounds["width"]), int(bounds["height"])
        selection = create_selection_effect(w, h, progress)
        paste_x = x - 10
        paste_y = y - 10
        frame.paste(selection, (paste_x, paste_y), selection)

    # 绘制鼠标指针
    cursor = create_cursor_image()
    # 确保鼠标不超出帧边界
    cx, cy = mouse_pos
    cx = max(0, min(cx, frame.width - CURSOR_SIZE))
    cy = max(0, min(cy, frame.height - CURSOR_SIZE))
    frame.paste(cursor, (cx, cy), cursor)

    return frame.convert("RGB")


def generate_mouse_animations(
    script: VideoScript,
    frames_info: list[dict],
    output_dir: Path,
    fps: int = 30,
) -> list[Path]:
    """为所有帧生成鼠标动效（含镜头缩放）"""
    from src.animation.camera import (
        calculate_camera_states,
        apply_camera_zoom,
        transform_mouse_pos,
    )

    mouse_dir = output_dir / "mouse"
    mouse_dir.mkdir(parents=True, exist_ok=True)

    cursor = create_cursor_image()
    current_pos = (960, 540)  # 初始位置
    mouse_frames = []

    # 预计算所有帧的镜头状态
    camera_states = calculate_camera_states(script, frames_info)

    for i, frame_info in enumerate(frames_info):
        seg_idx = frame_info["segment_index"]
        segment = script.segments[seg_idx]
        bounds = frame_info.get("bounds")

        # 计算目标位置
        target_pos = get_target_position(bounds, 1920, 1080)

        # 计算该片段内的进度
        seg_start = segment.timestamp
        frame_time = frame_info["timestamp"]
        progress = (frame_time - seg_start) / segment.duration if segment.duration > 0 else 0
        progress = max(0, min(1, progress))

        # 计算鼠标位置（平滑移动）
        if progress < 0.3:
            move_progress = progress / 0.3
            mouse_pos = (
                int(current_pos[0] + (target_pos[0] - current_pos[0]) * move_progress),
                int(current_pos[1] + (target_pos[1] - current_pos[1]) * move_progress),
            )
        else:
            mouse_pos = target_pos

        # 应用镜头缩放
        camera = camera_states[i] if i < len(camera_states) else None
        frame = Image.open(frame_info["path"]).convert("RGBA")
        render_bounds = bounds

        if camera and camera.zoom_level > 1.0:
            frame = apply_camera_zoom(frame, camera)
            mouse_pos = transform_mouse_pos(mouse_pos, camera, 1920, 1080)
            # 转换 bounds 坐标到缩放后的坐标空间
            if render_bounds:
                zx, zy = transform_mouse_pos(
                    (int(render_bounds["x"]), int(render_bounds["y"])),
                    camera, 1920, 1080,
                )
                zoom = camera.zoom_level
                render_bounds = {
                    "x": zx,
                    "y": zy,
                    "width": render_bounds["width"] * zoom,
                    "height": render_bounds["height"] * zoom,
                }

        # 渲染鼠标效果到帧（传入已加载的帧图像）
        result = render_mouse_on_frame(
            frame,
            mouse_pos,
            segment.action,
            render_bounds,
            progress,
        )

        # 保存带鼠标的帧
        mouse_path = mouse_dir / f"mouse-{frame_info['path'].stem.split('-')[1]}.png"
        result.save(mouse_path)
        mouse_frames.append(mouse_path)

        # 更新当前位置
        if progress >= 0.3:
            current_pos = target_pos

    console.print(f"  ✓ 生成 {len(mouse_frames)} 帧鼠标动效（含镜头缩放）")
    return mouse_frames
