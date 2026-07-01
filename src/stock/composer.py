"""股票科普视频合成模块"""

from pathlib import Path
from typing import Any


def compose_stock_video(
    frames_dir: Path,
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
    fps: int = 30,
) -> Path:
    """合成股票科普视频

    Args:
        frames_dir: 帧序列目录
        audio_path: TTS音频文件
        subtitle_path: SRT字幕文件
        output_path: 输出视频路径
        fps: 帧率

    Returns:
        输出视频路径
    """
    # TODO: 实现视频合成
    # 1. 读取帧序列
    # 2. 使用 ffmpeg 合成视频 + 音频 + 字幕
    return output_path
