"""镜头缩放动画引擎（Ken Burns 效果）"""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from rich.console import Console

from src.models import VideoScript

console = Console()


@dataclass
class CameraState:
    """镜头状态"""
    zoom_level: float  # 1.0 = 原始大小, 2.5 = 放大 2.5 倍
    center_x: float    # 归一化中心 X (0.0-1.0)
    center_y: float    # 归一化中心 Y (0.0-1.0)


# 各动作类型的目标镜头参数
ACTION_CAMERA_TARGETS = {
    "navigate": {"zoom": 1.0, "center_x": 0.5, "center_y": 0.4},
    "scroll":   {"zoom": 1.1, "center_x": 0.5, "center_y": 0.5},
    "click":    {"zoom": 1.8, "center_x": 0.5, "center_y": 0.5},
    "highlight": {"zoom": 1.6, "center_x": 0.5, "center_y": 0.5},
    "zoom":     {"zoom": 2.2, "center_x": 0.5, "center_y": 0.5},
}

# 默认初始镜头
DEFAULT_CAMERA = CameraState(zoom_level=1.0, center_x=0.5, center_y=0.4)


def ease_in_out(t: float) -> float:
    """缓动函数：平滑的加速-减速"""
    if t < 0.5:
        return 2 * t * t
    return 1 - (-2 * t + 2) ** 2 / 2


def lerp(a: float, b: float, t: float) -> float:
    """线性插值"""
    return a + (b - a) * t


def get_camera_target_for_segment(
    segment,
    bounds: dict | None,
    frame_width: int,
    frame_height: int,
) -> dict:
    """根据片段动作和目标元素计算镜头目标参数"""
    base = ACTION_CAMERA_TARGETS.get(
        segment.action, ACTION_CAMERA_TARGETS["highlight"]
    )

    target = {
        "zoom": base["zoom"],
        "center_x": base["center_x"],
        "center_y": base["center_y"],
    }

    # 如果有目标元素，将镜头中心对准它
    if bounds and frame_width > 0 and frame_height > 0:
        elem_center_x = (bounds["x"] + bounds["width"] / 2) / frame_width
        elem_center_y = (bounds["y"] + bounds["height"] / 2) / frame_height
        # 限制中心范围，避免裁剪出界
        target["center_x"] = max(0.1, min(0.9, elem_center_x))
        target["center_y"] = max(0.1, min(0.9, elem_center_y))

    return target


def calculate_camera_states(
    script: VideoScript,
    frames_info: list[dict],
    frame_width: int = 1920,
    frame_height: int = 1080,
) -> list[CameraState]:
    """为每一帧计算镜头状态

    镜头行为规则：
    - navigate: 全景，缓慢推进
    - scroll: 保持当前 zoom，轻微平移
    - highlight/click: zoom 推进到目标元素
    - zoom: 强力 zoom 到目标元素
    - 相邻帧之间使用缓动插值
    """
    if not frames_info:
        return []

    states = []
    current_camera = CameraState(
        zoom_level=DEFAULT_CAMERA.zoom_level,
        center_x=DEFAULT_CAMERA.center_x,
        center_y=DEFAULT_CAMERA.center_y,
    )

    # 按片段分组帧
    segment_frames: dict[int, list[int]] = {}
    for i, fi in enumerate(frames_info):
        seg_idx = fi["segment_index"]
        if seg_idx not in segment_frames:
            segment_frames[seg_idx] = []
        segment_frames[seg_idx].append(i)

    # 按片段顺序处理
    for seg_idx in sorted(segment_frames.keys()):
        frame_indices = segment_frames[seg_idx]
        segment = script.segments[seg_idx]
        num_frames = len(frame_indices)

        if num_frames == 0:
            continue

        # 获取该片段的镜头目标
        bounds = frames_info[frame_indices[0]].get("bounds")
        target = get_camera_target_for_segment(
            segment, bounds, frame_width, frame_height
        )

        for local_i, global_i in enumerate(frame_indices):
            progress = local_i / max(1, num_frames - 1)

            # 前 40% 时间用于镜头移动，后 60% 保持稳定
            if progress < 0.4:
                move_t = ease_in_out(progress / 0.4)
                zoom_level = lerp(current_camera.zoom_level, target["zoom"], move_t)
                center_x = lerp(current_camera.center_x, target["center_x"], move_t)
                center_y = lerp(current_camera.center_y, target["center_y"], move_t)
            else:
                zoom_level = target["zoom"]
                center_x = target["center_x"]
                center_y = target["center_y"]

            # 限制 zoom 范围
            zoom_level = max(1.0, min(2.5, zoom_level))

            states.append(CameraState(
                zoom_level=zoom_level,
                center_x=center_x,
                center_y=center_y,
            ))

        # 更新当前镜头状态为该片段结束时的状态
        current_camera = CameraState(
            zoom_level=target["zoom"],
            center_x=target["center_x"],
            center_y=target["center_y"],
        )

    return states


def apply_camera_zoom(
    frame: Image.Image,
    camera: CameraState,
) -> Image.Image:
    """对帧应用镜头缩放效果

    根据 zoom_level 和 center 裁剪帧的对应区域，然后放大回原始尺寸。
    """
    if camera.zoom_level <= 1.0:
        return frame

    w, h = frame.size
    zoom = camera.zoom_level

    # 计算裁剪区域大小
    crop_w = int(w / zoom)
    crop_h = int(h / zoom)

    # 计算裁剪区域左上角（基于归一化中心点）
    cx = int(camera.center_x * w)
    cy = int(camera.center_y * h)

    crop_x = max(0, min(cx - crop_w // 2, w - crop_w))
    crop_y = max(0, min(cy - crop_h // 2, h - crop_h))

    # 裁剪并放大回原始尺寸
    cropped = frame.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
    zoomed = cropped.resize((w, h), Image.Resampling.LANCZOS)

    return zoomed


def transform_mouse_pos(
    pos: tuple[int, int],
    camera: CameraState,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int]:
    """将原始鼠标坐标转换为镜头缩放后的屏幕坐标"""
    if camera.zoom_level <= 1.0:
        return pos

    zoom = camera.zoom_level

    # 计算裁剪区域
    crop_w = frame_width / zoom
    crop_h = frame_height / zoom

    cx = camera.center_x * frame_width
    cy = camera.center_y * frame_height

    crop_x = max(0, min(cx - crop_w / 2, frame_width - crop_w))
    crop_y = max(0, min(cy - crop_h / 2, frame_height - crop_h))

    # 坐标变换：原始坐标 -> 裁剪区域内的相对位置 -> 缩放后的屏幕坐标
    new_x = int((pos[0] - crop_x) * zoom)
    new_y = int((pos[1] - crop_y) * zoom)

    return (new_x, new_y)
