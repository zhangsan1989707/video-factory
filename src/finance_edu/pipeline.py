"""炒股科普视频完整流水线"""

from __future__ import annotations

import json
import subprocess
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from rich.console import Console

from src.finance_edu.compliance import check_finance_compliance
from src.finance_edu.constants import (
    BLACK_GOLD_THEME,
    SAFE_AREA,
    SCENE_TEMPLATE_MAP,
    VIDEO_FPS,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
    WHITE_CARD_THEME,
)
from src.finance_edu.models import FinanceEduTopic
from src.finance_edu.renderer import (
    build_finance_render_plan,
    render_finance_html,
    render_finance_preview_frames,
    render_playwright_video,
    save_render_plan,
    mix_audio,
)
from src.finance_edu.script_generator import generate_finance_script
from src.finance_edu.storage import (
    create_finance_job_paths,
    read_json,
    write_json,
)
from src.finance_edu.storyboard import generate_finance_storyboard
from src.tts.edge_tts import (
    generate_all_audio,
    get_audio_duration,
    reset_tts_rate_override,
    set_tts_rate_override,
)

console = Console()


class _TimingReport:
    def __init__(self) -> None:
        self.started_at = datetime.now(timezone.utc)
        self._start = time.perf_counter()
        self.stages: list[dict[str, float | str]] = []

    def stage(self, name: str):
        import contextlib

        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages.append({"name": name, "seconds": round(time.perf_counter() - start, 3)})

    async def measure(self, name: str, awaitable):
        start = time.perf_counter()
        try:
            return await awaitable
        finally:
            self.stages.append({"name": name, "seconds": round(time.perf_counter() - start, 3)})

    def to_dict(self) -> dict:
        finished_at = datetime.now(timezone.utc)
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "total_seconds": round(time.perf_counter() - self._start, 3),
            "stages": self.stages,
        }


class _ScriptAdapter:
    """将 finance_edu 脚本适配为 generate_all_audio 所需的形状"""

    def __init__(self, narration: str, segments: list[dict[str, Any]]) -> None:
        self.segments = [
            type("_Seg", (), {
                "timestamp": float(seg.get("start", 0)),
                "duration": float(seg.get("duration", 5)),
                "narration": str(seg.get("narration", "")),
            })()
            for seg in segments
        ]


def _stage(callback: Callable[[str, str], None] | None, name: str, message: str) -> None:
    if callback:
        callback(name, message)


def _calibrate_segments_by_audio(
    segments: list[dict[str, Any]], audio_files: list[Path]
) -> list[dict[str, Any]]:
    """根据每段 TTS 音频的实际时长重新校准 segments 时间戳"""
    durations: list[float] = []
    for i, seg in enumerate(segments):
        audio_file = audio_files[i] if i < len(audio_files) else None
        duration = float(seg.get("duration", 5))
        if audio_file and audio_file.exists():
            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(audio_file)],
                    capture_output=True, text=True, timeout=5,
                )
                duration = float(result.stdout.strip() or str(duration))
            except Exception:
                pass
        durations.append(duration)

    total = sum(durations)
    target_total = min(total, 65.0)
    scale = target_total / total if total > 0 else 1.0

    calibrated: list[dict[str, Any]] = []
    current_ts = 0.0
    for seg, dur in zip(segments, durations):
        scaled_dur = round(dur * scale, 3)
        calibrated.append({**seg, "start": round(current_ts, 3), "duration": scaled_dur})
        current_ts += scaled_dur

    return calibrated


async def run_finance_edu_video(
    topic: FinanceEduTopic,
    output_dir: Path | None = None,
    voice: str | None = None,
    rate: str | None = None,
    dry_run: bool = False,
    stage_callback: Callable[[str, str], None] | None = None,
) -> Path:
    """生成炒股科普短视频

    Args:
        topic: 主题配置
        output_dir: 输出目录（可选）
        voice: TTS 声音
        rate: TTS 语速
        dry_run: 只生成计划文件，不合成视频
        stage_callback: 阶段回调

    Returns:
        任务目录路径
    """
    paths = create_finance_job_paths(output_dir)
    timing = _TimingReport()

    # 1. 保存主题配置
    _stage(stage_callback, "saving_topic", "保存主题配置。")
    write_json(paths.topic_json, topic.to_dict())

    # 2. 生成脚本
    _stage(stage_callback, "generating_script", "正在生成口播脚本。")
    console.print("[cyan]📝 正在生成口播脚本...[/cyan]")
    script = await timing.measure("script_generation", generate_finance_script(topic))
    write_json(paths.script_json, script.to_dict())
    console.print(f"   ✓ 脚本标题: {script.title}")
    console.print(f"   ✓ 共 {len(script.segments)} 个段落")

    # 3. 合规检查
    _stage(stage_callback, "compliance_check", "执行合规检查。")
    console.print("[cyan]🔍 正在执行合规检查...[/cyan]")
    report = check_finance_compliance(script)
    write_json(paths.compliance_check_json, report.to_dict())
    console.print(f"   ✓ 合规状态: {'通过' if report.passed else '未通过'}")
    console.print(f"   ✓ 最高风险: {report.max_risk_level}")
    if report.issues:
        for issue in report.issues:
            console.print(f"   ⚠ [{issue.level}] {issue.category}: {issue.text}")

    if not report.passed and report.max_risk_level == "high":
        console.print("[red]❌ 脚本包含高风险内容，请修改后再渲染。[/red]")
        raise ValueError("脚本包含高风险荐股或收益承诺内容，请修改后再渲染")

    # 4. 生成分镜
    _stage(stage_callback, "generating_storyboard", "正在生成分镜。")
    console.print("[cyan]🎞️ 正在生成分镜...[/cyan]")
    storyboard = await timing.measure(
        "storyboard_generation",
        generate_finance_storyboard(topic, script),
    )
    write_json(paths.storyboard_json, storyboard.to_dict())
    console.print(f"   ✓ 共 {len(storyboard.scenes)} 个分镜")

    # dry_run 到此结束
    if dry_run:
        console.print(f"\n[green]✅ Dry run 完成。请检查: {paths.base}[/green]\n")
        return paths.base

    # 5. 生成 TTS 音频
    _stage(stage_callback, "generating_tts", "正在生成 TTS 语音。")
    console.print("[cyan]🎙️ 正在生成语音...[/cyan]")
    adapter = _ScriptAdapter(script.narration, [s.to_dict() for s in script.segments])
    effective_voice = voice or "zh-CN-XiaoxiaoNeural"
    effective_rate = rate or "+20%"
    rate_token = set_tts_rate_override(effective_rate)
    try:
        audio_files = await timing.measure(
            "generate_tts",
            generate_all_audio(adapter, paths.base, effective_voice),
        )
    finally:
        reset_tts_rate_override(rate_token)

    total_audio = sum(get_audio_duration(f) for f in audio_files)
    console.print(f"   ✓ 音频总时长: {total_audio:.1f} 秒")

    # 校准时间戳
    calibrated = _calibrate_segments_by_audio(
        [s.to_dict() for s in script.segments], audio_files
    )

    # 6. 构建渲染计划
    _stage(stage_callback, "building_render_plan", "构建渲染计划。")
    render_plan = build_finance_render_plan(topic, storyboard, paths)
    render_plan["audio_files"] = [str(f) for f in audio_files]
    save_render_plan(render_plan, paths.render_plan_json)

    # 7. 生成预览帧
    _stage(stage_callback, "rendering_preview", "生成预览帧。")
    console.print("[cyan]🖼️ 正在生成预览帧...[/cyan]")
    previews = render_finance_preview_frames(render_plan, paths.preview_frames_dir)
    console.print(f"   ✓ 生成 {len(previews)} 张预览帧")

    # 8. 合成视频 (PIL 帧 + ffmpeg)
    _stage(stage_callback, "composing_video", "合成视频。")
    console.print("[cyan]🎬 正在合成视频...[/cyan]")

    # 校准时间戳
    calibrated = _calibrate_segments_by_audio(
        [s.to_dict() for s in script.segments], audio_files
    )

    # 用 ffmpeg 拼接预览帧为视频，再混合音频
    final_video = paths.base / "final.mp4"
    await timing.measure(
        "compose_video",
        _compose_from_frames(previews, calibrated, audio_files, final_video, paths),
    )

    # 渲染 HTML composition
    html_path = paths.base / "composition.html"
    scenes_for_render = [
        {
            "scene_id": s["scene_type"],
            "template_id": SCENE_TEMPLATE_MAP.get(s["scene_type"], "concept_card"),
            "start": s["start"],
            "duration": s["duration"],
            "title": s.get("screen_title", ""),
            "subtitle": s.get("screen_subtitle", ""),
            "bullets": s.get("bullets", []),
            "narration": s.get("narration", ""),
            "risk_note": "指标存在滞后性" if s["scene_type"] == "pitfall" else "",
        }
        for s in calibrated
    ]
    render_finance_html(
        visual_style=topic.visual_style,
        title=script.title,
        scenes=scenes_for_render,
        total_duration=sum(s["duration"] for s in calibrated),
        output_path=html_path,
    )

    # Playwright 截图 + ffmpeg 合成
    raw_video = paths.base / "raw.mp4"
    await timing.measure(
        "playwright_render",
        _run_playwright_render(html_path, scenes_for_render, raw_video),
    )

    # 混合音频
    final_video = paths.base / "final.mp4"
    await timing.measure(
        "mix_audio",
        _run_mix_audio(raw_video, calibrated, audio_files, final_video),
    )

    # 9. 写入时间报告
    write_json(paths.timing_report, timing.to_dict())

    console.print(f"\n[green]✅ 完成！视频已保存到: {final_video}[/green]\n")
    return paths.base


async def _compose_from_frames(
    preview_paths: list[Path],
    scenes: list[dict[str, Any]],
    audio_files: list[Path],
    output_path: Path,
    paths,
) -> None:
    """用 PIL 生成每帧画面 + ffmpeg 合成视频 + 混合音频"""
    import asyncio

    # Step 1: 拼接音频
    concat_list = paths.base / "audio_concat.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for af in audio_files:
            f.write(f"file '{af.resolve()}'\n")

    merged_audio = paths.base / "merged_audio.m4a"
    proc = await _run_subprocess([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c:a", "aac", "-b:a", "128k",
        str(merged_audio),
    ])
    if proc.returncode != 0:
        raise RuntimeError(f"音频拼接失败: {proc.stderr[-300:]}")

    # Step 2: 为每个 scene 生成对应时长的帧序列，用 ffmpeg 合成
    # 用一张图片循环播放对应时长
    segments_video = paths.base / "segments.mp4"
    filter_parts = []
    inputs = []
    for i, (scene, preview) in enumerate(zip(scenes, preview_paths)):
        dur = scene.get("duration", 5)
        inputs.extend(["-loop", "1", "-t", str(dur), "-i", str(preview)])
        filter_parts.append(f"[{i}:v]fps=30[v{i}]")

    concat_str = "".join(f"[v{i}]" for i in range(len(scenes)))
    filter_parts.append(f"{concat_str}concat=n={len(scenes)}:v=1:a=0[outv]")
    filter_complex = ";".join(filter_parts)

    proc = await _run_subprocess([
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        str(segments_video),
    ])
    if proc.returncode != 0:
        raise RuntimeError(f"视频合成失败: {proc.stderr[-500:]}")

    # Step 3: 合并视频 + 音频
    proc = await _run_subprocess([
        "ffmpeg", "-y",
        "-i", str(segments_video),
        "-i", str(merged_audio),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        str(output_path),
    ])
    if proc.returncode != 0:
        raise RuntimeError(f"最终合成失败: {proc.stderr[-500:]}")


async def _run_playwright_render(
    html_path: Path,
    scenes: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """异步调用 Playwright 渲染"""
    import asyncio
    await asyncio.to_thread(render_playwright_video, html_path, scenes, output_path)


async def _run_subprocess(cmd: list[str]) -> subprocess.CompletedProcess:
    """异步运行子进程"""
    import asyncio
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return subprocess.CompletedProcess(
        args=cmd,
        returncode=proc.returncode,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
    )
