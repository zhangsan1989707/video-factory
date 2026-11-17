"""股票科普视频渲染器测试"""

import subprocess
import tempfile
from pathlib import Path

import pytest

from src.stock.spec.renderer import StockRenderer, get_renderer_version


def _make_minimal_spec() -> dict:
    """构造一个最简分镜规范，用于测试 fallback 渲染。"""
    return {
        "version": "1.0",
        "resolution": [1080, 1920],
        "duration": 2,
        "fps": 2,
        "theme": {
            "primary": "#1A1A2E",
            "accent": "#E8B04B",
            "text": "#FFFFFF",
            "background": "#0F0F1A",
        },
        "shots": [
            {
                "id": 1,
                "start": 0,
                "end": 1,
                "type": "title",
                "content": {
                    "main": "60秒带你看懂",
                    "sub": "MACD指标",
                    "style": "magazine_cover",
                },
            },
            {
                "id": 2,
                "start": 1,
                "end": 2,
                "type": "definition",
                "content": {
                    "term": "MACD",
                    "definition": "指数平滑异同移动平均线",
                    "translation": "",
                },
            },
        ],
    }


def _generate_silent_audio(audio_path: Path, duration: float = 1.0) -> None:
    """使用 ffmpeg 生成一段静音 AAC 音频，用于视频合成测试。"""
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


def test_renderer_can_be_instantiated():
    """渲染器可以被实例化，并指向默认 video-spec-builder 路径。"""
    renderer = StockRenderer()
    assert renderer.video_spec_builder_path.name == "video-spec-builder"
    assert renderer.video_spec_builder_path.parent.name == "third_party"

    custom_path = "/tmp/fake-vsb"
    renderer_custom = StockRenderer(custom_path)
    assert str(renderer_custom.video_spec_builder_path) == custom_path


def test_get_renderer_version():
    """版本号应为语义化字符串。"""
    version = get_renderer_version()
    assert isinstance(version, str)
    assert len(version.split(".")) >= 2


def test_render_shots_fallback_when_vsb_not_available():
    """当 video-spec-builder 不可用时，render_shots 应降级生成帧。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        renderer = StockRenderer(video_spec_builder_path=output_dir / "nonexistent-vsb")

        spec = _make_minimal_spec()
        frames = renderer.render_shots(spec, output_dir)

        assert len(frames) > 0
        assert all(f.exists() for f in frames)
        assert (output_dir / "shot_spec.json").exists()
        # 帧按文件名连续编号
        assert frames[0].name == "frame_0001.png"


def test_render_video_from_frames():
    """使用 ffmpeg 将帧序列、音频、字幕合成为 MP4。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        renderer = StockRenderer(video_spec_builder_path=output_dir / "nonexistent-vsb")

        spec = _make_minimal_spec()
        frames = renderer.render_shots(spec, output_dir / "frames")
        assert len(frames) > 0

        audio_path = output_dir / "audio.m4a"
        _generate_silent_audio(audio_path, duration=1.0)

        subtitle_path = output_dir / "subtitle.srt"
        subtitle_path.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\n测试字幕\n\n", encoding="utf-8"
        )

        output_path = output_dir / "final.mp4"
        result_path = renderer.render_video_from_frames(
            frames=frames,
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            output_path=output_path,
            fps=2,
        )

        assert result_path == output_path
        assert output_path.exists()
        assert output_path.stat().st_size > 0


def test_render_video_from_frames_without_subtitles():
    """字幕文件不存在时仍应正常合成视频。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        renderer = StockRenderer(video_spec_builder_path=output_dir / "nonexistent-vsb")

        spec = _make_minimal_spec()
        frames = renderer.render_shots(spec, output_dir / "frames")

        audio_path = output_dir / "audio.m4a"
        _generate_silent_audio(audio_path, duration=1.0)

        output_path = output_dir / "final.mp4"
        renderer.render_video_from_frames(
            frames=frames,
            audio_path=audio_path,
            subtitle_path=output_dir / "missing.srt",
            output_path=output_path,
            fps=2,
        )

        assert output_path.exists()
        assert output_path.stat().st_size > 0


def test_render_video_from_frames_no_frames_raises():
    """空帧列表应抛出 ValueError。"""
    renderer = StockRenderer()
    with pytest.raises(ValueError, match="No frames to render"):
        renderer.render_video_from_frames(
            frames=[],
            audio_path=Path("audio.mp3"),
            subtitle_path=Path("sub.srt"),
            output_path=Path("out.mp4"),
        )
