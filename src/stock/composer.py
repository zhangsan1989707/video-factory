"""股票科普视频合成模块"""

from pathlib import Path
from typing import Any

from src.stock.spec.renderer import StockRenderer


def compose_stock_video(
    frames_dir: Path,
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
    fps: int = 30,
) -> Path:
    """合成股票科普视频

    读取帧序列目录中的 frame_*.png，调用 StockRenderer 与 ffmpeg
    将帧、TTS 音频、SRT 字幕合成为最终视频。

    Args:
        frames_dir: 帧序列目录
        audio_path: TTS音频文件
        subtitle_path: SRT字幕文件
        output_path: 输出视频路径
        fps: 帧率

    Returns:
        输出视频路径
    """
    frames_dir = Path(frames_dir)
    audio_path = Path(audio_path)
    subtitle_path = Path(subtitle_path)
    output_path = Path(output_path)

    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        raise ValueError(f"未在 {frames_dir} 找到帧序列")

    renderer = StockRenderer()
    return renderer.render_video_from_frames(
        frames=frames,
        audio_path=audio_path,
        subtitle_path=subtitle_path,
        output_path=output_path,
        fps=fps,
    )
