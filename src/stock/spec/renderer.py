"""video-spec-builder 封装 - 渲染股票科普视频分镜"""

import json
import subprocess
from pathlib import Path
from typing import Any

# TODO: 集成 video-spec-builder
# 预期接口：
# - render_shot_spec(spec_json: dict, output_dir: Path) -> list[Path] (渲染后的帧序列)
# - get_renderer_version() -> str


class StockRenderer:
    """股票科普视频渲染器"""

    def __init__(self, video_spec_builder_path: str | None = None):
        self.video_spec_builder_path = video_spec_builder_path

    def render_shots(self, shots: list[dict[str, Any]], output_dir: Path) -> list[Path]:
        """渲染分镜序列为帧图片"""
        output_dir.mkdir(parents=True, exist_ok=True)
        # TODO: 调用 video-spec-builder 渲染
        # 暂时返回空列表占位
        return []

    def render_video_from_frames(
        self,
        frames: list[Path],
        audio_path: Path,
        subtitle_path: Path,
        output_path: Path,
        fps: int = 30,
    ) -> Path:
        """将帧序列、TTS音频、字幕合成为最终视频"""
        # TODO: 使用 ffmpeg 合成
        return output_path


def get_renderer_version() -> str:
    """获取渲染器版本"""
    return "0.1.0-stub"
