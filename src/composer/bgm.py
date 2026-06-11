"""BGM 混音与音频标准化"""

import subprocess
from pathlib import Path

from rich.console import Console

from src.utils.config import BGM_DIR, BGM_VOLUME, BGM_FADE_IN, BGM_FADE_OUT

console = Console()

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac"}


def find_bgm() -> Path | None:
    """扫描 BGM 目录，返回第一个音频文件"""
    if not BGM_DIR.is_dir():
        return None
    for f in sorted(BGM_DIR.iterdir()):
        if f.suffix.lower() in AUDIO_EXTENSIONS:
            return f
    return None


def _get_duration(video_path: Path) -> float:
    """用 ffprobe 获取视频时长（秒）"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(video_path),
            ],
            capture_output=True, text=True,
        )
        return float(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        return 0.0


def add_bgm(
    video_path: Path,
    bgm_path: Path,
    output_path: Path | None = None,
    volume: float = BGM_VOLUME,
    fade_in: float = BGM_FADE_IN,
    fade_out: float = BGM_FADE_OUT,
) -> Path:
    """给视频添加背景音乐，BGM 以低音量混入，保留人声清晰度。

    Args:
        video_path: 源视频路径
        bgm_path: 背景音乐路径
        output_path: 输出路径，None 则覆盖源文件
        volume: BGM 音量（0.0-1.0），默认 0.25
        fade_in: BGM 淡入秒数
        fade_out: BGM 淡出秒数
    """
    if output_path is None:
        output_path = video_path

    duration = _get_duration(video_path)
    fade_out_start = max(0, duration - fade_out)

    temp_path = output_path.with_suffix(".bgm.mp4")

    filter_complex = (
        f"[0:a]volume=1.0[voice];"
        f"[1:a]volume={volume},"
        f"atrim=0:{duration},"
        f"afade=t=in:st=0:d={fade_in},"
        f"afade=t=out:st={fade_out_start}:d={fade_out}[bgm];"
        f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-stream_loop", "-1", "-i", str(bgm_path),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        str(temp_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and temp_path.exists():
        temp_path.replace(output_path)
        console.print(f"  ✓ BGM 已添加（音量 {volume:.0%}）")
    else:
        if temp_path.exists():
            temp_path.unlink()
        console.print(f"  [yellow]⚠ BGM 添加失败: {result.stderr[:200]}[/yellow]")

    return output_path


def normalize_audio(video_path: Path) -> Path:
    """对视频进行 EBU R128 响度标准化（-17 LUFS）。

    所有风格的视频统一走这个后处理，保证音量一致。
    """
    temp_path = video_path.with_suffix(".loudnorm.mp4")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-af", "loudnorm=I=-17:TP=-1.5:LRA=11",
        "-c:v", "copy",
        str(temp_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and temp_path.exists():
        temp_path.replace(video_path)
    elif temp_path.exists():
        temp_path.unlink()
    return video_path


def post_process_video(
    video_path: Path,
    no_bgm: bool = False,
    bgm_volume: float = BGM_VOLUME,
    bgm_path: str | Path | None = None,
) -> Path:
    """视频后处理：添加 BGM + 响度标准化。

    在所有 composer 输出后统一调用。
    """
    # 1. 添加 BGM
    if not no_bgm:
        bgm_file = Path(bgm_path).expanduser() if bgm_path else find_bgm()
        if bgm_file:
            add_bgm(video_path, bgm_file, video_path, volume=bgm_volume)
        else:
            console.print("  [yellow]⚠ bgm/ 目录无音频文件，跳过 BGM[/yellow]")

    # 2. 响度标准化
    normalize_audio(video_path)

    return video_path
