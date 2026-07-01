"""股票科普视频流水线端到端测试"""

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.stock.pipeline import _generate_shot_spec, run_stock_pipeline
from src.stock.script import generate_stock_script, generate_subtitle_file


def _run(coro):
    """在同步测试函数中运行异步协程。"""
    return asyncio.run(coro)


def _make_llm_response(theme: str) -> dict:
    """构造一个模拟的 LLM 脚本生成响应。"""
    return {
        "data": {
            "title": f"60秒带你看懂{theme}",
            "segments": [
                {
                    "timestamp": 0,
                    "duration": 5,
                    "narration": f"今天讲一个散户必须懂的概念：{theme}。",
                    "subtitle": f"今天讲一个散户必须懂的概念：{theme}。",
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
    }


def _generate_silent_audio(audio_path: Path, duration: float = 1.0) -> None:
    """使用 ffmpeg 生成一段静音 AAC 音频，用于流水线测试。"""
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=24000:cl=mono",
        "-t",
        str(duration),
        "-c:a",
        "aac",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"无法生成测试音频，ffmpeg 不可用: {result.stderr}")


def test_stock_pipeline_llm_source():
    """测试 LLM 生成内容的流水线（已 mock 外部网络调用）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        audio_path = output_dir / "audio" / "segment-000.m4a"
        _generate_silent_audio(audio_path, duration=1.0)

        with (
            patch(
                "src.stock.pipeline.search_finance_topics",
                new=AsyncMock(
                    return_value=[
                        {
                            "title": "MACD",
                            "content": "MACD称为指数平滑异同移动平均线",
                            "source": "llm",
                        }
                    ]
                ),
            ) as mock_search,
            patch(
                "src.stock.script.chat_json_detail",
                return_value=_make_llm_response("MACD指标"),
            ) as mock_chat,
            patch(
                "src.stock.pipeline.generate_all_audio",
                new=AsyncMock(return_value=[audio_path]),
            ) as mock_tts,
        ):
            final_path = _run(
                run_stock_pipeline(
                    theme="MACD指标",
                    content_source="llm",
                    source_input="MACD",
                    output_dir=output_dir,
                    voice="zh-CN-XiaoxiaoNeural",
                    rate="+20%",
                    fps=5,
                )
            )

        assert final_path.exists()
        assert (output_dir / "script.json").exists()
        assert (output_dir / "subtitle.srt").exists()
        assert (output_dir / "shot_spec.json").exists()
        mock_search.assert_awaited_once_with("MACD")
        mock_chat.assert_called_once()
        mock_tts.assert_awaited_once()


def test_stock_pipeline_manual_source():
    """测试手动输入内容的流水线（已 mock 外部网络调用）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        audio_path = output_dir / "audio" / "segment-000.m4a"
        _generate_silent_audio(audio_path, duration=1.0)

        content = """
        MACD称为指数平滑异同移动平均线
        由快的指数平均线减去慢的指数平均线得到
        主要用于判断买卖信号
        """

        with (
            patch(
                "src.stock.script.chat_json_detail",
                return_value=_make_llm_response("MACD指标"),
            ) as mock_chat,
            patch(
                "src.stock.pipeline.generate_all_audio",
                new=AsyncMock(return_value=[audio_path]),
            ) as mock_tts,
        ):
            final_path = _run(
                run_stock_pipeline(
                    theme="MACD指标",
                    content_source="manual",
                    source_input=content,
                    output_dir=output_dir,
                    voice="zh-CN-XiaoxiaoNeural",
                    rate="+20%",
                    fps=5,
                )
            )

        script_path = output_dir / "script.json"
        assert script_path.exists()
        with open(script_path, encoding="utf-8") as f:
            script = json.load(f)
        assert "title" in script
        assert "segments" in script
        assert len(script["segments"]) > 0

        assert final_path.exists()
        assert (output_dir / "subtitle.srt").exists()
        assert (output_dir / "shot_spec.json").exists()
        mock_chat.assert_called_once()
        mock_tts.assert_awaited_once()


def test_script_generation_output_format():
    """验证脚本生成的输出格式符合预期。"""
    with patch(
        "src.stock.script.chat_json_detail",
        return_value=_make_llm_response("市盈率"),
    ) as mock_chat:
        script = _run(generate_stock_script("市盈率"))

    assert isinstance(script, dict)
    assert "title" in script
    assert "segments" in script
    assert isinstance(script["segments"], list)
    assert len(script["segments"]) > 0

    for seg in script["segments"]:
        assert "timestamp" in seg
        assert "duration" in seg
        assert "narration" in seg
        assert "subtitle" in seg
        assert isinstance(seg["timestamp"], (int, float))
        assert isinstance(seg["duration"], (int, float))
        assert isinstance(seg["narration"], str)
        assert isinstance(seg["subtitle"], str)
        assert seg["narration"]
        assert seg["subtitle"]

    mock_chat.assert_called_once()


def test_subtitle_file_generation():
    """验证 SRT 字幕文件生成格式正确。"""
    segments = [
        {
            "timestamp": 0,
            "duration": 5,
            "narration": "第一句台词",
            "subtitle": "第一句字幕",
        },
        {
            "timestamp": 5,
            "duration": 5,
            "narration": "第二句台词",
            "subtitle": "第二句字幕",
        },
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        srt_path = Path(tmpdir) / "subtitle.srt"
        result_path = generate_subtitle_file(segments, str(srt_path))

        assert result_path == srt_path
        assert srt_path.exists()

        text = srt_path.read_text(encoding="utf-8")
        assert "1\n00:00:00,000 --> 00:00:05,000\n第一句字幕" in text
        assert "2\n00:00:05,000 --> 00:00:10,000\n第二句字幕" in text


def test_shot_spec_generation():
    """验证根据脚本生成分镜规范的结构。"""
    segments = [
        {
            "timestamp": 0,
            "duration": 5,
            "narration": "开场钩子",
            "subtitle": "开场钩子",
        },
        {
            "timestamp": 5,
            "duration": 15,
            "narration": "核心概念",
            "subtitle": "核心概念",
        },
    ]

    spec = _generate_shot_spec("MACD指标", segments, fps=30)

    assert spec["version"] == "1.0"
    assert spec["resolution"] == [1080, 1920]
    assert spec["duration"] == 20
    assert spec["fps"] == 30
    assert "font_family" in spec
    assert "theme" in spec
    assert "shots" in spec

    shots = spec["shots"]
    assert len(shots) == 1 + len(segments) + 1
    assert shots[0]["type"] == "title"
    assert shots[0]["content"]["sub"] == "MACD指标"
    assert shots[-1]["type"] == "summary"
    assert shots[-1]["content"]["closing"] == "关注我，持续更新投资干货"

    for shot in shots:
        assert "id" in shot
        assert "start" in shot
        assert "end" in shot
        assert "type" in shot
        assert "content" in shot
