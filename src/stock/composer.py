"""股票科普视频合成模块"""

from pathlib import Path
from typing import Any

from src.stock.hyperframes_render import render_stock_education_video


async def compose_stock_video(
    theme: str,
    segments: list[dict[str, Any]],
    output_dir: Path,
    voice: str,
    rate: str,
    fps: int = 30,
) -> Path:
    """合成股票科普视频

    作为 render_stock_education_video 的薄封装，使用 HyperFrames
    将脚本片段、TTS 音频与动画合成为最终视频。

    Args:
        theme: 视频主题
        segments: 脚本片段（含 narration / subtitle / timestamp / duration）
        output_dir: 输出目录
        voice: TTS 声音
        rate: TTS 语速
        fps: 帧率

    Returns:
        最终视频路径
    """
    return await render_stock_education_video(
        theme=theme,
        segments=segments,
        output_dir=output_dir,
        voice=voice,
        rate=rate,
        fps=fps,
    )
