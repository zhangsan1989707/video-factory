"""edge-tts 集成"""

import asyncio
import subprocess
from pathlib import Path

import edge_tts
from rich.console import Console

from src.models import VideoScript
from src.utils.config import TTS_VOICE, TTS_RATE

console = Console()

MAX_RETRIES = 3


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
    rate: str = TTS_RATE,
) -> Path:
    """生成单段语音（带重试）"""
    for attempt in range(MAX_RETRIES):
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
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
) -> list[Path]:
    """为脚本的所有片段生成语音"""
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    audio_files = []

    for i, segment in enumerate(script.segments):
        output_path = audio_dir / f"segment-{i:03d}.mp3"
        if _is_valid_audio(output_path):
            console.print(f"  复用语音 {i + 1}: {segment.narration[:20]}...")
            audio_files.append(output_path)
            continue
        console.print(f"  生成语音 {i + 1}: {segment.narration[:20]}...")

        await generate_audio_segment(
            segment.narration,
            output_path,
            voice=voice,
        )
        audio_files.append(output_path)

    console.print(f"  ✓ 生成 {len(audio_files)} 段语音")
    return audio_files


def get_audio_duration(audio_path: Path) -> float:
    """获取音频文件时长（秒）"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio_path)],
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return 5.0  # 默认 5 秒
