"""流程协调器"""

import asyncio
import json
from pathlib import Path
from typing import Callable

from rich.console import Console

from src.models import ProjectInfo, ProjectPaths, shot_plan_from_dict
from src.scraper.github_api import fetch_repo_info, parse_github_url
from src.script.generator import generate_script
from src.browser.recorder import record_browser
from src.browser.desktop_review_recorder import record_desktop_review
from src.animation.mouse import generate_mouse_animations
from src.tts.edge_tts import generate_all_audio, get_audio_duration
from src.composer.bgm import post_process_video
from src.composer.desktop_review import compose_desktop_review_video
from src.composer.video import compose_video
from src.composer.vertical import compose_vertical_video
from src.planner.assets import generate_asset_manifest
from src.planner.brief import generate_creative_brief
from src.planner.capture import capture_assets
from src.planner.desktop_review import (
    generate_desktop_review_plan,
    generate_script_from_desktop_review_plan,
)
from src.planner.script_v2 import generate_script_from_shot_plan
from src.planner.shot_plan import (
    generate_hotlist_shot_plan,
    generate_shot_plan,
    generate_single_review_shot_plan,
)
from src.utils.config import BGM_VOLUME, OUTPUT_DIR, TTS_VOICE, VIDEO_FPS

console = Console()


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _project_info_to_dict(project_info: ProjectInfo) -> dict:
    return {
        "name": project_info.name,
        "owner": project_info.owner,
        "description": project_info.description,
        "stars": project_info.stars,
        "language": project_info.language,
        "topics": project_info.topics,
        "repo_url": project_info.repo_url,
        "homepage": project_info.homepage,
        "default_branch": project_info.default_branch,
    }


def _manifest_from_dict(data: dict):
    from src.models import AssetManifest, VisualAsset

    return AssetManifest(
        assets=[
            VisualAsset(
                id=str(asset.get("id", "")),
                type=str(asset.get("type", "")),
                source=str(asset.get("source", "")),
                path=str(asset.get("path", "")),
                caption=str(asset.get("caption", "")),
                use_case=str(asset.get("use_case", "")),
                quality=str(asset.get("quality", "")),
            )
            for asset in data.get("assets", [])
        ],
    )


def _resolve_plan_dir(from_plan: str) -> Path:
    plan_path = Path(from_plan)
    if plan_path.is_dir():
        return plan_path
    return plan_path.parent


def _manifest_needs_capture(data: dict) -> bool:
    for asset in data.get("assets", []):
        path = str(asset.get("path", ""))
        if path.startswith("http://") or path.startswith("https://"):
            return True
        if path and not Path(path).exists():
            return True
    return False


def _parse_url_list(url: str) -> list[str]:
    raw_parts = url.replace("\n", ",").split(",")
    return [part.strip() for part in raw_parts if part.strip()]


def _prefix_manifest_ids(index: int, manifest):
    from src.models import AssetManifest, VisualAsset

    return AssetManifest(
        assets=[
            VisualAsset(
                id=f"p{index}-{asset.id}",
                type=asset.type,
                source=asset.source,
                path=asset.path,
                caption=asset.caption,
                use_case=asset.use_case,
                quality=asset.quality,
            )
            for asset in manifest.assets
        ]
    )


def _combine_manifests(manifests: list):
    from src.models import AssetManifest

    assets = []
    for manifest in manifests:
        assets.extend(manifest.assets)
    return AssetManifest(assets=assets)


def _stage(stage_callback: Callable[[str, str], None] | None, name: str, message: str) -> None:
    if stage_callback:
        stage_callback(name, message)


async def _generate_audio_task(script, paths: ProjectPaths, voice: str) -> None:
    await generate_all_audio(script, paths.base, voice)


async def _capture_and_tts(
    manifest,
    script,
    paths: ProjectPaths,
    voice: str,
    stage_callback: Callable[[str, str], None] | None,
):
    _stage(stage_callback, "capturing_assets", "开始采集真实素材。")
    console.print("[cyan]🖼️ 正在采集真实素材...[/cyan]")
    _stage(stage_callback, "generating_tts", "开始生成 TTS 语音。")
    console.print("[cyan]🎙️ 正在生成语音...[/cyan]")
    captured_manifest, _audio_files = await asyncio.gather(
        capture_assets(manifest, paths.assets_dir),
        _generate_audio_task(script, paths, voice),
    )
    _write_json(paths.asset_manifest_json, captured_manifest.to_dict())
    return captured_manifest


async def _record_desktop_and_tts(
    desktop_plan,
    script,
    paths: ProjectPaths,
    voice: str,
    stage_callback: Callable[[str, str], None] | None,
):
    _stage(stage_callback, "generating_tts", "开始生成 TTS 语音。")
    console.print("[cyan]🎙️ 正在生成语音...[/cyan]")
    _stage(stage_callback, "capturing_assets", "开始录制桌面浏览镜头。")
    console.print("[cyan]🎥 正在录制桌面浏览镜头...[/cyan]")
    _audio_files, frames_info = await asyncio.gather(
        _generate_audio_task(script, paths, voice),
        record_desktop_review(desktop_plan, paths.base),
    )
    return frames_info


async def _fetch_hotlist_project(index: int, url: str):
    owner, repo = parse_github_url(url)
    project = await fetch_repo_info(owner, repo)
    manifest = _prefix_manifest_ids(index, generate_asset_manifest(project))
    return index, project, manifest


def _finish_video(
    output_path: Path,
    no_bgm: bool,
    bgm_volume: float,
    bgm_path: str | None,
    stage_callback: Callable[[str, str], None] | None = None,
) -> Path:
    _stage(stage_callback, "post_processing", "开始执行视频后处理。")
    return post_process_video(output_path, no_bgm=no_bgm, bgm_volume=bgm_volume, bgm_path=bgm_path)


# ---------------------------------------------------------------------------
# 各管线路径
# ---------------------------------------------------------------------------

async def _run_from_plan(
    from_plan: str,
    output: str | None,
    voice: str,
    fps: int,
    dry_run: bool,
    no_bgm: bool,
    bgm_volume: float,
    bgm_path: str | None,
    stage_callback: Callable[[str, str], None] | None,
) -> Path:
    """从已有分镜目录恢复执行。"""
    project_dir = _resolve_plan_dir(from_plan)
    paths = ProjectPaths(project_dir)
    output_path = Path(output) if output else paths.final_video
    console.print("[cyan]📋 正在读取已有分镜...[/cyan]")

    # desktop-review 分镜
    if paths.desktop_review_plan_json.exists():
        with open(paths.desktop_review_plan_json, encoding="utf-8") as f:
            from src.models import desktop_review_plan_from_dict
            desktop_plan = desktop_review_plan_from_dict(json.load(f))
        script = generate_script_from_desktop_review_plan(desktop_plan)
        _write_json(paths.script_json, script.to_dict())
        if dry_run:
            console.print(f"\n[green]✅ From-plan dry run 完成。请检查: {paths.base}[/green]\n")
            return paths.base
        frames_info = await _record_desktop_and_tts(desktop_plan, script, paths, voice, stage_callback)
        _stage(stage_callback, "composing_video", "开始合成 desktop-review 视频。")
        console.print("[cyan]🎬 正在合成 desktop-review 视频...[/cyan]")
        output_path = compose_desktop_review_video(
            plan=desktop_plan,
            script=script,
            frames_info=frames_info,
            audio_dir=paths.audio_dir,
            output_path=output_path,
            preview_dir=paths.preview_frames_dir,
            fps=fps,
        )
        return _finish_video(output_path, no_bgm, bgm_volume, bgm_path, stage_callback)

    # 竖屏分镜
    with open(paths.shot_plan_json, encoding="utf-8") as f:
        shot_plan = shot_plan_from_dict(json.load(f))
    with open(paths.asset_manifest_json, encoding="utf-8") as f:
        manifest_data = json.load(f)
    manifest = _manifest_from_dict(manifest_data)
    script = generate_script_from_shot_plan(shot_plan)
    _write_json(paths.script_json, script.to_dict())
    if dry_run:
        console.print(f"\n[green]✅ From-plan dry run 完成。请检查: {paths.base}[/green]\n")
        return paths.base
    if _manifest_needs_capture(manifest_data):
        manifest = await _capture_and_tts(manifest, script, paths, voice, stage_callback)
    else:
        _stage(stage_callback, "generating_tts", "开始生成 TTS 语音。")
        console.print("[cyan]🎙️ 正在生成语音...[/cyan]")
        await generate_all_audio(script, paths.base, voice)
    _stage(stage_callback, "composing_video", "开始合成竖屏视频。")
    console.print("[cyan]🎬 正在合成竖屏视频...[/cyan]")
    output_path = compose_vertical_video(
        script=script,
        shot_plan=shot_plan,
        manifest=manifest,
        audio_dir=paths.audio_dir,
        output_path=output_path,
        preview_dir=paths.preview_frames_dir,
        fps=fps,
    )
    return _finish_video(output_path, no_bgm, bgm_volume, bgm_path, stage_callback)


async def _run_hotlist(
    url_list: list[str],
    output: str | None,
    voice: str,
    fps: int,
    dry_run: bool,
    no_bgm: bool,
    bgm_volume: float,
    bgm_path: str | None,
    stage_callback: Callable[[str, str], None] | None,
) -> Path:
    """热榜模式：多个仓库合成一个竖屏视频。"""
    if len(url_list) < 2:
        raise ValueError("热榜模式需要至少 2 个 GitHub 仓库地址，用逗号分隔")
    if output:
        output_path = Path(output)
        project_dir = output_path.parent
    else:
        project_dir = OUTPUT_DIR / "github-hotlist"
        output_path = project_dir / "final.mp4"
    project_dir.mkdir(parents=True, exist_ok=True)
    paths = ProjectPaths(project_dir)

    console.print("[cyan]🔍 正在抓取热榜项目信息...[/cyan]")
    results = await asyncio.gather(*[
        _fetch_hotlist_project(index, item)
        for index, item in enumerate(url_list[:10], start=1)
    ])
    projects = []
    manifests = []
    for index, project, manifest in sorted(results, key=lambda item: item[0]):
        projects.append(project)
        manifests.append(manifest)
        console.print(f"   ✓ #{index} {project.full_name} | {project.stars} stars")

    _write_json(paths.info_json, {"projects": [_project_info_to_dict(p) for p in projects]})
    combined_manifest = _combine_manifests(manifests)
    _write_json(paths.asset_manifest_json, combined_manifest.to_dict())
    console.print(f"   ✓ 找到 {len(combined_manifest.assets)} 个候选素材")

    console.print("[cyan]🎞️ 正在生成真实热榜分镜...[/cyan]")
    shot_plan = generate_hotlist_shot_plan(projects, manifests)
    _write_json(paths.shot_plan_json, shot_plan.to_dict())

    script = generate_script_from_shot_plan(shot_plan)
    _write_json(paths.script_json, script.to_dict())

    if dry_run:
        console.print(f"\n[green]✅ Hotlist dry run 完成。请检查: {paths.base}[/green]\n")
        return paths.base

    combined_manifest = await _capture_and_tts(combined_manifest, script, paths, voice, stage_callback)

    _stage(stage_callback, "composing_video", "开始合成热榜竖屏视频。")
    console.print("[cyan]🎬 正在合成热榜竖屏视频...[/cyan]")
    output_path = compose_vertical_video(
        script=script,
        shot_plan=shot_plan,
        manifest=combined_manifest,
        audio_dir=paths.audio_dir,
        output_path=output_path,
        preview_dir=paths.preview_frames_dir,
        fps=fps,
    )
    return _finish_video(output_path, no_bgm, bgm_volume, bgm_path, stage_callback)


async def _run_desktop_review(
    project_info: ProjectInfo,
    paths: ProjectPaths,
    output_path: Path,
    voice: str,
    fps: int,
    dry_run: bool,
    no_bgm: bool,
    bgm_volume: float,
    bgm_path: str | None,
    stage_callback: Callable[[str, str], None] | None,
) -> Path:
    """桌面浏览风格：录制浏览器操作 + 合成。"""
    console.print("[cyan]🖥️ 正在生成 desktop-review 分镜...[/cyan]")
    desktop_plan = generate_desktop_review_plan(project_info)
    _write_json(paths.desktop_review_plan_json, desktop_plan.to_dict())

    script = generate_script_from_desktop_review_plan(desktop_plan)
    _write_json(paths.script_json, script.to_dict())

    if dry_run:
        console.print(f"\n[green]✅ Desktop dry run 完成。请检查: {paths.base}[/green]\n")
        return paths.base

    frames_info = await _record_desktop_and_tts(desktop_plan, script, paths, voice, stage_callback)

    _stage(stage_callback, "composing_video", "开始合成 desktop-review 视频。")
    console.print("[cyan]🎬 正在合成 desktop-review 视频...[/cyan]")
    output_path = compose_desktop_review_video(
        plan=desktop_plan,
        script=script,
        frames_info=frames_info,
        audio_dir=paths.audio_dir,
        output_path=output_path,
        preview_dir=paths.preview_frames_dir,
        fps=fps,
    )
    return _finish_video(output_path, no_bgm, bgm_volume, bgm_path, stage_callback)


async def _run_vertical(
    project_info: ProjectInfo,
    paths: ProjectPaths,
    output_path: Path,
    voice: str,
    fps: int,
    style: str,
    dry_run: bool,
    no_bgm: bool,
    bgm_volume: float,
    bgm_path: str | None,
    stage_callback: Callable[[str, str], None] | None,
) -> Path:
    """竖屏风格：生成 brief + 素材 + 分镜 + 合成。"""
    console.print("[cyan]🧭 正在生成选题 brief...[/cyan]")
    brief = generate_creative_brief(project_info)
    _write_json(paths.creative_brief_json, brief.to_dict())
    console.print(f"   ✓ {brief.recommendation}: {brief.reason}")

    console.print("[cyan]🖼️ 正在整理素材清单...[/cyan]")
    manifest = generate_asset_manifest(project_info)
    _write_json(paths.asset_manifest_json, manifest.to_dict())
    console.print(f"   ✓ 找到 {len(manifest.assets)} 个候选素材")

    console.print("[cyan]🎞️ 正在生成竖屏分镜...[/cyan]")
    if style == "single-review" or style == "default":
        shot_plan = generate_single_review_shot_plan(project_info, brief, manifest)
    else:
        shot_plan = generate_shot_plan(project_info, brief, manifest)
    _write_json(paths.shot_plan_json, shot_plan.to_dict())

    script = generate_script_from_shot_plan(shot_plan)
    _write_json(paths.script_json, script.to_dict())

    if dry_run:
        console.print(f"\n[green]✅ Dry run 完成。请检查: {paths.base}[/green]\n")
        return paths.base

    if brief.recommendation == "skip":
        console.print("[yellow]⚠ brief 建议跳过，但仍继续生成竖屏草稿。[/yellow]")

    manifest = await _capture_and_tts(manifest, script, paths, voice, stage_callback)

    _stage(stage_callback, "composing_video", "开始合成竖屏视频。")
    console.print("[cyan]🎬 正在合成竖屏视频...[/cyan]")
    output_path = compose_vertical_video(
        script=script,
        shot_plan=shot_plan,
        manifest=manifest,
        audio_dir=paths.audio_dir,
        output_path=output_path,
        preview_dir=paths.preview_frames_dir,
        fps=fps,
    )
    return _finish_video(output_path, no_bgm, bgm_volume, bgm_path, stage_callback)


async def _run_horizontal(
    project_info: ProjectInfo,
    script,
    paths: ProjectPaths,
    output_path: Path,
    voice: str,
    fps: int,
    orientation: str,
    min_duration: int,
    max_duration: int,
    no_bgm: bool,
    bgm_volume: float,
    bgm_path: str | None,
    stage_callback: Callable[[str, str], None] | None,
) -> Path:
    """横屏模式（旧版）：脚本 → TTS → 浏览器录制 → 鼠标动效 → 合成。"""
    _write_json(paths.script_json, script.to_dict())

    _stage(stage_callback, "generating_tts", "开始生成 TTS 语音。")
    console.print("[cyan]🎙️ 正在生成语音...[/cyan]")
    audio_files = await generate_all_audio(script, paths.base, voice)

    total_audio_duration = sum(get_audio_duration(f) for f in audio_files)
    console.print(f"   ✓ 使用语音: {voice}")
    console.print(f"   ✓ 音频总时长: {total_audio_duration:.1f} 秒")

    _stage(stage_callback, "capturing_assets", "开始录制浏览器素材。")
    console.print("[cyan]🖥️ 正在录制浏览器...[/cyan]")
    frames_info = await record_browser(script, paths.base, fps, total_audio_duration)

    console.print("[cyan]🖱️ 正在生成鼠标动效...[/cyan]")
    generate_mouse_animations(script, frames_info, paths.base, fps)

    _stage(stage_callback, "composing_video", "开始合成横屏视频。")
    console.print("[cyan]🎬 正在合成视频...[/cyan]")
    final_path = compose_video(
        script=script,
        mouse_frames_dir=paths.mouse_dir,
        audio_dir=paths.audio_dir,
        output_path=output_path,
        fps=fps,
        orientation=orientation,
        total_audio_duration=total_audio_duration,
    )

    final_path = _finish_video(final_path, no_bgm, bgm_volume, bgm_path, stage_callback)
    console.print(f"\n[green]✅ 完成！视频已保存到: {final_path}[/green]\n")
    return final_path


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def run_pipeline(
    url: str,
    output: str | None = None,
    orientation: str = "horizontal",
    voice: str = TTS_VOICE,
    min_duration: int = 30,
    max_duration: int = 60,
    fps: int = VIDEO_FPS,
    dry_run: bool = False,
    from_plan: str | None = None,
    style: str = "default",
    no_bgm: bool = False,
    bgm_volume: float = BGM_VOLUME,
    bgm_path: str | None = None,
    stage_callback: Callable[[str, str], None] | None = None,
) -> Path:
    """执行完整的视频生成流程。"""
    console.print(f"\n[bold]🎬 GitHub Video Maker[/bold]\n")

    if from_plan:
        return await _run_from_plan(
            from_plan, output, voice, fps, dry_run,
            no_bgm, bgm_volume, bgm_path, stage_callback,
        )

    if not url:
        raise ValueError("请提供 GitHub 仓库地址，或使用 --from-plan 指向已有分镜目录")

    url_list = _parse_url_list(url)
    is_hotlist = orientation == "vertical" and (style == "hotlist" or len(url_list) > 1)

    if is_hotlist:
        return await _run_hotlist(
            url_list, output, voice, fps, dry_run,
            no_bgm, bgm_volume, bgm_path, stage_callback,
        )

    # 单仓库路径
    owner, repo = parse_github_url(url)
    if output:
        output_path = Path(output)
        project_dir = output_path.parent
    else:
        project_dir = OUTPUT_DIR / f"{owner}-{repo}"
        output_path = project_dir / "final.mp4"
    project_dir.mkdir(parents=True, exist_ok=True)
    paths = ProjectPaths(project_dir)

    console.print("[cyan]🔍 正在抓取项目信息...[/cyan]")
    project_info = await fetch_repo_info(owner, repo)
    console.print(f"   ✓ {project_info.full_name} - {project_info.description[:40]}")
    console.print(f"   ⭐ {project_info.stars} stars | {project_info.language}")
    _write_json(paths.info_json, _project_info_to_dict(project_info))

    if style == "desktop-review":
        return await _run_desktop_review(
            project_info, paths, output_path, voice, fps, dry_run,
            no_bgm, bgm_volume, bgm_path, stage_callback,
        )

    if orientation == "vertical" or dry_run:
        return await _run_vertical(
            project_info, paths, output_path, voice, fps, style, dry_run,
            no_bgm, bgm_volume, bgm_path, stage_callback,
        )

    # 旧版横屏路径
    console.print("[cyan]📝 正在生成视频脚本...[/cyan]")
    script = generate_script(project_info, min_duration, max_duration)
    console.print(f"   ✓ 生成 {len(script.segments)} 个片段，总时长 {script.total_duration:.0f} 秒")

    return await _run_horizontal(
        project_info, script, paths, output_path, voice, fps,
        orientation, min_duration, max_duration,
        no_bgm, bgm_volume, bgm_path, stage_callback,
    )
