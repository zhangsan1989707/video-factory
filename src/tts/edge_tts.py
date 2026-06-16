"""edge-tts 集成"""

import asyncio
import subprocess
from contextvars import ContextVar
from pathlib import Path

import edge_tts
from rich.console import Console

from src.models import VideoScript
from src.utils.config import TTS_VOICE, TTS_RATE

console = Console()

MAX_RETRIES = 3
MAX_CONCURRENT_SEGMENTS = 3

# ContextVar: 允许在更高层（pipeline / console job）临时覆盖 TTS 语速，
# 而不需要改 generate_all_audio / _generate_audio_task 的全部内部签名。
# 默认值与 src.utils.config.TTS_RATE 保持一致。
_tts_rate_override: ContextVar[str | None] = ContextVar("tts_rate_override", default=None)


def current_tts_rate() -> str:
    """返回当前生效的 TTS 语速：ContextVar override > 全局默认。"""
    return _tts_rate_override.get() or TTS_RATE


def set_tts_rate_override(rate: str | None):
    """设置当前协程上下文中的 TTS 语速 override。返回 token 供 reset。"""
    return _tts_rate_override.set(rate)


def reset_tts_rate_override(token) -> None:
    _tts_rate_override.reset(token)


def _is_valid_audio(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


async def generate_audio_segment(
    text: str,
    output_path: Path,
    voice: str = TTS_VOICE,
    rate: str | None = None,
) -> Path:
    """生成单段语音（带重试）"""
    effective_rate = rate if rate is not None else current_tts_rate()
    for attempt in range(MAX_RETRIES):
        try:
            communicate = edge_tts.Communicate(text, voice, rate=effective_rate)
            await communicate.save(str(output_path))
            return output_path
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                console.print(f"  [yellow]⚠ 语音生成失败，重试 {attempt + 1}/{MAX_RETRIES}...[/yellow]")
                await asyncio.sleep(2)
            else:
                raise


async def generate_all_audio(
    script: VideoScript,
    output_dir: Path,
    voice: str = TTS_VOICE,
    rate: str | None = None,
) -> list[Path]:
    """为脚本的所有片段生成语音"""
    effective_rate = rate if rate is not None else current_tts_rate()
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    audio_files: list[Path | None] = [None] * len(script.segments)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEGMENTS)

    async def _generate_one(index: int) -> None:
        segment = script.segments[index]
        output_path = audio_dir / f"segment-{index:03d}.mp3"
        async with semaphore:
            await generate_audio_segment(
                segment.narration,
                output_path,
                voice=voice,
                rate=effective_rate,
            )
        audio_files[index] = output_path

    for i, segment in enumerate(script.segments):
        output_path = audio_dir / f"segment-{i:03d}.mp3"
        if _is_valid_audio(output_path):
            console.print(f"  复用语音 {i + 1}: {segment.narration[:20]}...")
            audio_files[i] = output_path
            continue
        console.print(f"  生成语音 {i + 1}: {segment.narration[:20]}...")

    tasks = [
        asyncio.create_task(_generate_one(i))
        for i, path in enumerate(audio_files)
        if path is None
    ]
    if tasks:
        await asyncio.gather(*tasks)

    ordered_files = [path for path in audio_files if path is not None]
    console.print(f"  ✓ 生成 {len(ordered_files)} 段语音")
    return ordered_files


def get_audio_duration(audio_path: Path) -> float:
    """获取音频文件时长（秒）"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio_path)],
            capture_output=True,
            text=True,
        )
        duration = float(result.stdout.strip())
        if duration <= 0:
            console.print(f"  [yellow]⚠ 音频时长异常: {audio_path.name} ({duration}s)，使用默认 5.0s[/yellow]")
            return 5.0
        return duration
    except Exception as e:
        console.print(f"  [yellow]⚠ 获取音频时长失败: {audio_path.name} ({e})，使用默认 5.0s[/yellow]")
        return 5.0
