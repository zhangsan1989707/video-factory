"""股票科普脚本生成模块"""

import json
from typing import Any

from src.console.model_router import chat_json_detail


async def generate_stock_script(
    theme: str,
    source_content: str = "",
    topic: str = "",
) -> dict[str, Any]:
    """生成60秒股票科普视频脚本

    Args:
        theme: 视频主题，如 "MACD指标"
        source_content: 原始内容（可选）
        topic: 主题关键词（用于搜索）

    Returns:
        {
            "title": "60秒带你看懂XXX",
            "segments": [
                {"timestamp": 0, "duration": 5, "narration": "...", "subtitle": "..."},
                ...
            ]
        }
    """
    # TODO: 实现脚本生成
    # 1. 如果有 source_content，用 LLM 提炼要点
    # 2. 生成 60 秒口播脚本
    # 3. 返回带时间戳的 segments

    return {
        "title": f"60秒带你看懂{theme}",
        "segments": [],
    }


def generate_subtitle_file(
    segments: list[dict[str, Any]],
    output_path: str,
) -> None:
    """从脚本片段生成 SRT 字幕文件

    Args:
        segments: 脚本片段列表
        output_path: 输出 SRT 文件路径
    """
    with open(output_path, "w", encoding="utf-8") as f:
        for i, segment in enumerate(segments, start=1):
            start_ts = _format_srt_time(segment["timestamp"])
            end_ts = _format_srt_time(segment["timestamp"] + segment["duration"])
            subtitle = segment.get("subtitle", segment.get("narration", ""))

            f.write(f"{i}\n")
            f.write(f"{start_ts} --> {end_ts}\n")
            f.write(f"{subtitle}\n")
            f.write("\n")


def _format_srt_time(seconds: float) -> str:
    """将秒数转换为 SRT 时间格式 (HH:MM:SS,mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
