"""股票科普脚本生成模块"""

from pathlib import Path
from typing import Any

from src.console.model_router import chat_json_detail
from src.stock.prompts import SCRIPT_GENERATION_PROMPT


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
    prompt = SCRIPT_GENERATION_PROMPT.format(
        theme=theme,
        original_content=source_content or f"主题：{topic or theme}",
    )
    system = "你是一个专业的中文短视频脚本创作助手，只输出合法 JSON，不输出额外解释。"

    result = chat_json_detail(
        task="narration_generation",
        system=system,
        prompt=prompt,
        max_tokens=2000,
    )

    data = result.get("data")
    if data and isinstance(data.get("segments"), list) and len(data["segments"]) > 0:
        return _normalize_script(theme, data)

    # 当模型不可用时，返回一个可用的兜底脚本，保证流水线能继续运行
    return _fallback_script(theme)


def _normalize_script(theme: str, data: dict[str, Any]) -> dict[str, Any]:
    """规范化脚本格式，确保必要字段存在。"""
    segments: list[dict[str, Any]] = []
    for seg in data.get("segments", []):
        narration = str(seg.get("narration") or seg.get("subtitle") or "").strip()
        subtitle = str(seg.get("subtitle") or narration).strip()
        if not narration:
            continue
        segments.append({
            "timestamp": float(seg.get("timestamp", 0)),
            "duration": float(seg.get("duration", 5)),
            "narration": narration,
            "subtitle": subtitle,
        })

    return {
        "title": str(data.get("title") or f"60秒带你看懂{theme}"),
        "segments": segments,
    }


def _fallback_script(theme: str) -> dict[str, Any]:
    """LLM 不可用时使用的兜底脚本。"""
    return {
        "title": f"60秒带你看懂{theme}",
        "segments": [
            {
                "timestamp": 0,
                "duration": 5,
                "narration": f"今天讲一个散户必须懂的概念：{theme}。",
                "subtitle": f"今天讲一个散户必须懂的概念：{theme}",
            },
            {
                "timestamp": 5,
                "duration": 15,
                "narration": f"{theme}是投资中非常实用的知识点，搞懂它能帮你少踩很多坑。",
                "subtitle": f"{theme}是投资中非常实用的知识点。",
            },
            {
                "timestamp": 20,
                "duration": 20,
                "narration": "它的核心逻辑很简单：先看趋势，再看信号，最后结合成交量确认。",
                "subtitle": "核心逻辑：趋势、信号、成交量。",
            },
            {
                "timestamp": 40,
                "duration": 15,
                "narration": "实际用起来，不要迷信单一指标，多维度验证才能提高胜率。",
                "subtitle": "不要迷信单一指标，多维度验证。",
            },
            {
                "timestamp": 55,
                "duration": 5,
                "narration": "关注我，每天60秒，带你搞懂一个投资知识点。",
                "subtitle": "关注我，每天60秒。",
            },
        ],
    }


def generate_subtitle_file(
    segments: list[dict[str, Any]],
    output_path: str,
) -> Path:
    """从脚本片段生成 SRT 字幕文件

    Args:
        segments: 脚本片段列表
        output_path: 输出 SRT 文件路径

    Returns:
        输出文件路径
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        for i, segment in enumerate(segments, start=1):
            start_ts = _format_srt_time(segment["timestamp"])
            end_ts = _format_srt_time(segment["timestamp"] + segment["duration"])
            subtitle = segment.get("subtitle", segment.get("narration", ""))

            f.write(f"{i}\n")
            f.write(f"{start_ts} --> {end_ts}\n")
            f.write(f"{subtitle}\n")
            f.write("\n")

    return output_path


def _format_srt_time(seconds: float) -> str:
    """将秒数转换为 SRT 时间格式 (HH:MM:SS,mmm)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
