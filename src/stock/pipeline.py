"""股票科普视频流水线"""

import asyncio
from pathlib import Path
from typing import Any

from src.stock.script import generate_stock_script, generate_subtitle_file
from src.stock.scraper import fetch_finance_content
from src.stock.spec.renderer import StockRenderer
from src.tts.edge_tts import generate_all_audio


async def run_stock_pipeline(
    theme: str,
    content_source: str,  # "finance_site" | "llm" | "manual"
    source_input: str,     # URL / 关键词 / 文本
    output_dir: Path,
    voice: str,
    rate: str,
    fps: int = 30,
) -> Path:
    """运行股票科普视频完整流水线

    Steps:
    1. 获取内容（抓取/LLM生成/手动输入）
    2. 生成脚本
    3. 生成 TTS 音频
    4. 生成分镜规范
    5. 渲染帧序列
    6. 合成最终视频

    Args:
        theme: 视频主题
        content_source: 内容来源
        source_input: 来源输入
        output_dir: 输出目录
        voice: TTS 声音
        rate: TTS 语速
        fps: 帧率

    Returns:
        最终视频路径
    """
    # TODO: 实现完整流水线
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / "final.mp4"
