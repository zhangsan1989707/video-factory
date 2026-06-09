"""CLI 入口"""

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from src.pipeline import run_pipeline
from src.utils.config import TTS_VOICE, VIDEO_FPS, MIN_DURATION, MAX_DURATION, BGM_VOLUME

app = typer.Typer(
    name="github-video",
    help="AI 驱动的 GitHub 项目介绍视频生成工具",
    add_completion=False,
)
console = Console()


@app.command()
def generate(
    url: str = typer.Argument("", help="GitHub 仓库地址"),
    output: str | None = typer.Option(None, "-o", "--output", help="输出文件路径"),
    orientation: str = typer.Option(
        "horizontal",
        "--orientation",
        help="视频方向: horizontal/vertical",
    ),
    vertical: bool = typer.Option(
        False,
        "--vertical",
        help="使用 V2 竖屏短视频流水线",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="只生成 brief、素材清单、分镜和脚本，不合成视频",
    ),
    style: str = typer.Option(
        "default",
        "--style",
        help="视频风格: default/single-review/hotlist/desktop-review",
    ),
    from_plan: str | None = typer.Option(
        None,
        "--from-plan",
        help="从已有 shot_plan.json 所在目录继续生成竖屏视频",
    ),
    voice: str = typer.Option(
        TTS_VOICE,
        "--voice",
        help="微软 TTS 语音名称",
    ),
    min_duration: int = typer.Option(
        MIN_DURATION,
        "--min-duration",
        help="最短时长（秒）",
    ),
    max_duration: int = typer.Option(
        MAX_DURATION,
        "--max-duration",
        help="最长时长（秒）",
    ),
    fps: int = typer.Option(
        VIDEO_FPS,
        "--fps",
        help="录制帧率",
    ),
    no_bgm: bool = typer.Option(
        False,
        "--no-bgm",
        help="不添加背景音乐",
    ),
    bgm_volume: float = typer.Option(
        BGM_VOLUME,
        "--bgm-volume",
        help="背景音乐音量（0.0-1.0）",
    ),
    bgm_path: str | None = typer.Option(
        None,
        "--bgm-path",
        help="自定义本地 BGM 音频路径",
    ),
    verbose: bool = typer.Option(
        False,
        "-v",
        "--verbose",
        help="详细输出",
    ),
):
    """生成 GitHub 项目介绍视频"""
    try:
        asyncio.run(
            run_pipeline(
                url=url,
                output=output,
                orientation="vertical" if vertical else orientation,
                voice=voice,
                min_duration=min_duration,
                max_duration=max_duration,
                fps=fps,
                dry_run=dry_run,
                from_plan=from_plan,
                style=style,
                no_bgm=no_bgm,
                bgm_volume=bgm_volume,
                bgm_path=bgm_path,
            )
        )
    except Exception as e:
        console.print(f"\n[red]❌ 错误: {e}[/red]\n")
        if verbose:
            import traceback
            traceback.print_exc()
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
