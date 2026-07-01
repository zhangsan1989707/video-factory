"""HyperFrames 股票科普渲染测试"""

import subprocess
import tempfile
from pathlib import Path

import pytest

from src.stock.hyperframes_render import (
    build_screens,
    calibrate_segments_by_audio,
    render_html_composition,
)


def test_build_screens():
    segments = [
        {"timestamp": 0, "duration": 5, "narration": "开场", "subtitle": "开场"},
        {"timestamp": 5, "duration": 10, "narration": "概念解释", "subtitle": "概念"},
    ]
    screens = build_screens("MACD", segments)
    assert len(screens) == 2
    assert screens[0]["type"] == "intro"
    assert screens[0]["start"] == 0
    assert screens[1]["type"] == "concept"


def test_calibrate_segments_by_audio():
    segments = [
        {"timestamp": 0, "duration": 5, "narration": "a"},
        {"timestamp": 5, "duration": 5, "narration": "b"},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = Path(tmpdir) / "segment-000.m4a"
        result = subprocess.run(
            [
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
                "2.5",
                "-c:a",
                "aac",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip("ffmpeg not available")

        calibrated = calibrate_segments_by_audio(segments, [audio_path, None])
        assert calibrated[0]["duration"] == pytest.approx(2.5, 0.1)
        assert calibrated[1]["duration"] == 5.0


def test_render_html_composition():
    segments = [
        {"timestamp": 0, "duration": 5, "narration": "开场", "subtitle": "开场"},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "composition.html"
        render_html_composition("MACD", segments, output_path)
        assert output_path.exists()
        html = output_path.read_text(encoding="utf-8")
        assert "screen-01-intro" in html
        assert "MACD" in html
