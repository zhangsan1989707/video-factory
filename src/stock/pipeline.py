"""股票科普视频流水线"""

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.stock.script import generate_stock_script, generate_subtitle_file
from src.stock.scraper import fetch_finance_content, search_finance_topics
from src.stock.spec.renderer import StockRenderer
from src.stock.spec.shots import DefinitionShot, SummaryShot, TitleShot
from src.tts.edge_tts import (
    generate_all_audio,
    reset_tts_rate_override,
    set_tts_rate_override,
)


class _ScriptAdapter:
    """将股票科普脚本片段适配为 generate_all_audio 所需的 VideoScript 形状。"""

    def __init__(self, segments: list[dict[str, Any]]) -> None:
        self.segments = [
            type(
                "_Segment",
                (),
                {
                    "timestamp": float(seg.get("timestamp", 0)),
                    "duration": float(seg.get("duration", 5)),
                    "narration": str(seg.get("narration", "")),
                },
            )()
            for seg in segments
        ]


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
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: 获取内容
    content_source = str(content_source).strip().lower()
    if content_source == "finance_site":
        content = await fetch_finance_content(source_input, theme)
    elif content_source == "llm":
        topics = await search_finance_topics(source_input or theme)
        first = topics[0] if topics else {}
        content = {
            "topic": theme,
            "content": first.get("content") or first.get("summary") or first.get("title") or "",
            "source": first.get("source") or "llm",
        }
    else:
        content = {"topic": theme, "content": source_input, "source": "manual"}

    # Step 2: 生成脚本
    script_data = await generate_stock_script(
        theme=theme,
        source_content=str(content.get("content", "")),
    )

    script_path = output_dir / "script.json"
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script_data, f, ensure_ascii=False, indent=2)

    # Step 3: 生成 TTS 音频
    rate_token = set_tts_rate_override(rate)
    try:
        audio_files = await generate_all_audio(
            _ScriptAdapter(script_data["segments"]),
            output_dir,
            voice,
        )
    finally:
        reset_tts_rate_override(rate_token)

    audio_path = _combine_audio_files(audio_files, output_dir / "audio" / "combined.mp3")

    # Step 4: 生成字幕
    subtitle_path = generate_subtitle_file(
        script_data["segments"],
        str(output_dir / "subtitle.srt"),
    )

    # Step 5: 生成分镜规范
    shot_spec = _generate_shot_spec(theme, script_data["segments"], fps=fps)
    shot_spec_path = output_dir / "shot_spec.json"
    with open(shot_spec_path, "w", encoding="utf-8") as f:
        json.dump(shot_spec, f, ensure_ascii=False, indent=2)

    # Step 6: 渲染帧序列
    renderer = StockRenderer()
    frames = renderer.render_shots(shot_spec, output_dir / "frames")

    # Step 7: 合成最终视频
    output_path = output_dir / "final.mp4"

    if frames and audio_path and audio_path.exists():
        renderer.render_video_from_frames(
            frames=frames,
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            output_path=output_path,
            fps=fps,
        )
    else:
        # Fallback: 至少保留脚本、字幕与音频，生成空壳视频占位
        output_path.touch()

    return output_path


def _combine_audio_files(audio_files: list[Path], output_path: Path) -> Path | None:
    """将多段 TTS 音频合并为一个音频文件；单段时直接复用。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    valid_files = [Path(p) for p in audio_files if Path(p).exists()]
    if not valid_files:
        return None
    if len(valid_files) == 1:
        return valid_files[0]

    # 使用 ffmpeg concat demuxer 顺序拼接
    concat_lines = "\n".join(f"file '{path.resolve()}'" for path in valid_files)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as list_file:
        list_file.write(concat_lines)
        list_path = Path(list_file.name)

    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(output_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"音频拼接失败: {result.stderr}")
        return output_path
    finally:
        list_path.unlink(missing_ok=True)


def _generate_shot_spec(theme: str, segments: list[dict], fps: int = 30) -> dict:
    """根据脚本生成分镜规范。"""
    shots = []
    shot_id = 1

    # 封面标题
    shots.append(
        TitleShot(
            id=shot_id,
            start=0,
            end=5,
            main_title="60秒带你看懂",
            sub_title=theme,
        ).to_dict()
    )
    shot_id += 1

    # 中间分镜（根据脚本段落，最多 8 个）
    for seg in segments[:8]:
        shots.append(
            DefinitionShot(
                id=shot_id,
                start=seg["timestamp"],
                end=seg["timestamp"] + seg["duration"],
                term=theme,
                definition=seg["narration"],
                translation="",
            ).to_dict()
        )
        shot_id += 1

    # 总结
    shots.append(
        SummaryShot(
            id=shot_id,
            start=55,
            end=60,
            points=["今天学了", theme],
            closing_text="关注我，持续更新投资干货",
        ).to_dict()
    )

    return {
        "version": "1.0",
        "resolution": [1080, 1920],
        "duration": 60,
        "fps": fps,
        "font_family": "Noto Sans SC",
        "theme": {
            "primary": "#1A1A2E",
            "accent": "#E8B04B",
            "text": "#FFFFFF",
            "background": "#0F0F1A",
        },
        "shots": shots,
    }
