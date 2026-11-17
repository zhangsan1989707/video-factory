"""Plan preparation, asset manifest, shot plan, preview rendering, and readiness reports for console jobs."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from src.console import jobs as _jobs
from src.models import AssetManifest, ScriptSegment, Shot, ShotPlan, VideoScript, VisualAsset

README_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _clear_plan_artifacts(job_id: str) -> None:
    job_dir = _jobs.JOBS_DIR / job_id
    for name in (
        "asset_manifest.json",
        "shot_plan.json",
        "script.json",
        "info.json",
        "cover_frame.png",
        "cover_frame.json",
        "preview_visual_report.json",
        "video_spec_report.json",
        "readiness_report.json",
        "final.mp4",
    ):
        path = job_dir / name
        if path.exists() and path.is_file():
            path.unlink()
    preview_dir = job_dir / "preview_frames"
    if preview_dir.exists() and preview_dir.is_dir():
        shutil.rmtree(preview_dir)
    _jobs.update_job(job_id, official_video="")


def _clear_desktop_plan_artifacts(job_id: str) -> None:
    job_dir = _jobs.JOBS_DIR / job_id
    for name in ("desktop_review_plan.json",):
        path = job_dir / name
        if path.exists() and path.is_file():
            path.unlink()


def prepare_plan(job_id: str) -> dict[str, Any]:
    """Prepare current pipeline files without starting expensive rendering."""
    job = _jobs.read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    if _jobs._job_type(job) in {"single_project_vertical", "desktop_review"}:
        return _jobs._prepare_single_project_plan(job_id, job)
    if _jobs._job_type(job) == "from_plan_render":
        return _jobs._prepare_from_plan_render(job_id, job)
    _jobs._require_stage(job, {"preparing_plan"}, "当前阶段不能生成计划文件")
    if str(job.get("status") or "") not in {"awaiting_render", "awaiting_validation", "ready_to_render", "failed"}:
        raise ValueError(f"当前状态不能生成计划文件: {job.get('status') or 'unknown'}")
    selected = _jobs.read_json(_jobs.JOBS_DIR / job_id / "selected_projects.json", {}).get("items") or []
    segments = _jobs.read_json(_jobs.JOBS_DIR / job_id / "narration.json", {}).get("segments") or []
    if not selected:
        raise ValueError("请先确认项目列表")
    if not segments:
        raise ValueError("请先确认口播脚本")
    _jobs._ensure_quality_gate(job_id)

    _jobs.update_job(job_id, status="running", stage="preparing_plan", failed_stage="", error="")
    _jobs.append_log(job_id, "开始生成流水线计划文件。")

    job_dir = _jobs.JOBS_DIR / job_id
    try:
        manifest = _jobs._manifest(selected)
        shot_plan = _jobs._shot_plan(job, selected, segments)
        script = _jobs.generate_script_from_shot_plan(shot_plan)

        _jobs.write_json(job_dir / "asset_manifest.json", manifest.to_dict())
        _jobs.write_json(job_dir / "shot_plan.json", shot_plan.to_dict())
        _jobs.write_json(job_dir / "script.json", script.to_dict())
        _jobs.write_json(job_dir / "info.json", {"projects": selected})
        visual_style = _jobs._visual_style(job)
        if _jobs._render_engine(job) == "hyperframes":
            previews = _jobs.render_hotlist_v2_previews_from_projects(
                selected,
                job_dir / "preview_frames",
                style=visual_style,
                issue_number=_jobs._issue_number(job),
            )
        else:
            previews = _jobs.render_vertical_previews(script, shot_plan, manifest, job_dir / "preview_frames")
        visual_report = _jobs._write_preview_visual_report(job_id, previews)
        cover = _jobs._write_cover_frame(job_id, previews)
        readiness = _jobs._write_readiness_report(
            job_id,
            selected,
            segments,
            len(previews),
            bool(cover.get("path")),
            visual_report.get("status") == "passed",
        )
        _jobs.append_log(
            job_id,
            f"计划文件已生成，并输出 {len(previews)} 张静态预览帧；预览帧来自当前渲染模板，入场、扫光和数字动效会在正式 MP4 渲染时体现。",
        )
        _jobs.update_job(
            job_id,
            status="awaiting_validation",
            stage="preparing_plan",
            plan_validation={"status": "not_run", "error": ""},
        )
        return {
            "job": _jobs.read_job(job_id),
            "artifacts": _jobs.job_artifacts(job_id),
            "plan_validation": {"status": "not_run", "error": ""},
            "cover_frame": cover,
            "preview_visual_report": visual_report,
            "readiness_report": readiness,
            "render_command": f".venv/bin/python -m src.cli --from-plan {job_dir} -o {job_dir / 'final.mp4'} --vertical",
        }
    except Exception as exc:
        _jobs.append_log(job_id, f"计划文件生成失败: {exc}")
        _jobs._clear_plan_artifacts(job_id)
        _jobs.update_job(job_id, status="failed", stage="preparing_plan", failed_stage="preparing_plan", error=str(exc))
        raise


def _prepare_single_project_plan(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    _jobs._require_stage(job, {"preparing_plan"}, "当前阶段不能生成计划文件")
    if str(job.get("status") or "") not in {"awaiting_render", "awaiting_validation", "ready_to_render", "failed"}:
        raise ValueError(f"当前状态不能生成计划文件: {job.get('status') or 'unknown'}")
    repo_url = str(job.get("repo_url") or "").strip()
    if not repo_url:
        raise ValueError("单项目任务缺少 GitHub 仓库地址")
    pipeline_style = _jobs._pipeline_style_for_job(job)
    is_desktop = _jobs._job_type(job) == "desktop_review"

    _jobs._clear_plan_artifacts(job_id)
    if is_desktop:
        _jobs._clear_desktop_plan_artifacts(job_id)
    _jobs.update_job(job_id, status="running", stage="preparing_plan", failed_stage="", error="")
    _jobs.append_log(job_id, f"开始生成{_jobs._job_type_label(job)}计划文件: {repo_url}。")

    job_dir = _jobs.JOBS_DIR / job_id
    try:
        import asyncio

        asyncio.run(_jobs.run_pipeline(
            url=repo_url,
            output=str(job_dir / "final.mp4"),
            orientation="vertical" if not is_desktop else "horizontal",
            style=pipeline_style,
            dry_run=True,
            voice=_jobs._tts_voice(_jobs.read_job(job_id)),
            rate=_jobs._tts_rate(_jobs.read_job(job_id)),
        ))
        previews = _jobs._preview_existing_plan(job_dir)
        cover = _jobs._write_cover_frame(job_id, previews)
        console_segments = _jobs._console_segments_from_script(job_dir)
        _jobs.write_json(job_dir / "narration.json", {"segments": console_segments})
        readiness = _jobs._write_pipeline_job_readiness_report(job_id, repo_url, len(previews), bool(cover.get("path")))
        _jobs.append_log(job_id, f"{_jobs._job_type_label(job)}计划文件已生成，并输出 {len(previews)} 张静态预览帧。")
        _jobs.update_job(
            job_id,
            status="awaiting_input",
            stage="awaiting_script_confirmation",
            plan_validation={"status": "not_run", "error": ""},
        )
        return {
            "job": _jobs.read_job(job_id),
            "artifacts": _jobs.job_artifacts(job_id),
            "plan_validation": {"status": "not_run", "error": ""},
            "cover_frame": cover,
            "readiness_report": readiness,
            "segments": console_segments,
            "render_command": _jobs._render_command_for_job(job, job_dir),
        }
    except Exception as exc:
        _jobs.append_log(job_id, f"{_jobs._job_type_label(job)}计划文件生成失败: {exc}")
        _jobs._clear_plan_artifacts(job_id)
        _jobs.update_job(job_id, status="failed", stage="preparing_plan", failed_stage="preparing_plan", error=str(exc))
        raise


def _prepare_from_plan_render(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    _jobs._require_stage(job, {"preparing_plan"}, "当前阶段不能生成计划文件")
    if str(job.get("status") or "") not in {"awaiting_render", "awaiting_validation", "ready_to_render", "failed"}:
        raise ValueError(f"当前状态不能生成计划文件: {job.get('status') or 'unknown'}")
    plan_path = Path(str(job.get("plan_path") or "")).expanduser()
    if not plan_path.exists():
        raise ValueError(f"计划文件目录不存在: {plan_path}")
    source_dir = plan_path if plan_path.is_dir() else plan_path.parent
    if not (source_dir / "shot_plan.json").exists() and not (source_dir / "desktop_review_plan.json").exists():
        raise ValueError("计划文件目录需要包含 shot_plan.json 或 desktop_review_plan.json")

    _jobs._clear_plan_artifacts(job_id)
    _jobs._clear_desktop_plan_artifacts(job_id)
    _jobs.update_job(job_id, status="running", stage="preparing_plan", failed_stage="", error="")
    _jobs.append_log(job_id, f"开始导入计划文件目录: {source_dir}。")

    job_dir = _jobs.JOBS_DIR / job_id
    try:
        _jobs._copy_plan_snapshot(source_dir, job_dir)
        previews = _jobs._preview_existing_plan(job_dir)
        cover = _jobs._write_cover_frame(job_id, previews)
        console_segments = _jobs._console_segments_from_script(job_dir)
        _jobs.write_json(job_dir / "narration.json", {"segments": console_segments})
        readiness = _jobs._write_pipeline_job_readiness_report(job_id, str(source_dir), len(previews), bool(cover.get("path")))
        _jobs.append_log(job_id, f"计划文件已导入，并输出 {len(previews)} 张静态预览帧。")
        _jobs.update_job(
            job_id,
            status="awaiting_input",
            stage="awaiting_script_confirmation",
            plan_validation={"status": "not_run", "error": ""},
        )
        return {
            "job": _jobs.read_job(job_id),
            "artifacts": _jobs.job_artifacts(job_id),
            "plan_validation": {"status": "not_run", "error": ""},
            "cover_frame": cover,
            "readiness_report": readiness,
            "segments": console_segments,
            "render_command": f".venv/bin/python -m src.cli --from-plan {job_dir} -o {job_dir / 'final.mp4'}",
        }
    except Exception as exc:
        _jobs.append_log(job_id, f"计划文件导入失败: {exc}")
        _jobs._clear_plan_artifacts(job_id)
        _jobs._clear_desktop_plan_artifacts(job_id)
        _jobs.update_job(job_id, status="failed", stage="preparing_plan", failed_stage="preparing_plan", error=str(exc))
        raise


def _has_pipeline_plan(job_dir: Path) -> bool:
    return (job_dir / "shot_plan.json").exists() or (job_dir / "desktop_review_plan.json").exists()


def _copy_plan_snapshot(source_dir: Path, target_dir: Path) -> None:
    allowed_files = {
        "asset_manifest.json",
        "shot_plan.json",
        "desktop_review_plan.json",
        "script.json",
        "info.json",
    }
    copied = False
    for name in allowed_files:
        source = source_dir / name
        if source.exists() and source.is_file() and not source.is_symlink():
            shutil.copy2(source, target_dir / name)
            copied = True
    for dirname in ("assets", "audio", "desktop_frames"):
        source = source_dir / dirname
        target = target_dir / dirname
        if source.exists() and source.is_dir() and not source.is_symlink():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target, symlinks=False)
    if not copied or not _jobs._has_pipeline_plan(target_dir):
        raise ValueError("计划文件目录需要包含可用计划文件")


def _preview_existing_plan(job_dir: Path) -> list[Path]:
    if (job_dir / "desktop_review_plan.json").exists():
        return _jobs._desktop_preview_placeholders(job_dir)
    manifest = _jobs._asset_manifest_from_dict(_jobs.read_json(job_dir / "asset_manifest.json", {}))
    shot_plan = _jobs.shot_plan_from_dict(_jobs.read_json(job_dir / "shot_plan.json", {}))
    script = _jobs._video_script_from_dict(_jobs.read_json(job_dir / "script.json", {}))
    return _jobs.render_vertical_previews(script, shot_plan, manifest, job_dir / "preview_frames")


def _desktop_preview_placeholders(job_dir: Path) -> list[Path]:
    from PIL import Image, ImageDraw

    preview_dir = job_dir / "preview_frames"
    preview_dir.mkdir(parents=True, exist_ok=True)
    target = preview_dir / "desktop-review-plan.png"
    image = Image.new("RGB", (960, 540), (21, 24, 31))
    draw = ImageDraw.Draw(image)
    draw.rectangle((72, 72, 888, 468), outline=(100, 116, 139), width=3)
    draw.rectangle((72, 72, 888, 116), fill=(34, 40, 49))
    draw.text((108, 86), "desktop-review plan", fill=(235, 238, 243))
    draw.text((108, 170), "Preview frames are captured during final render.", fill=(180, 190, 205))
    image.save(target)
    return [target]


def _write_cover_frame(job_id: str, previews: list[Any]) -> dict[str, Any]:
    job_dir = _jobs.JOBS_DIR / job_id
    source = Path(previews[0]) if previews else Path()
    if not source.exists() or not source.is_file():
        cover = {"status": "missing", "path": "", "source": "", "note": "没有可用预览帧。"}
        _jobs.write_json(job_dir / "cover_frame.json", cover)
        _jobs.append_log(job_id, "封面帧生成跳过：没有可用预览帧。")
        return cover
    target = job_dir / "cover_frame.png"
    shutil.copy2(source, target)
    cover = {
        "status": "ready",
        "path": str(target),
        "source": str(source),
        "note": "第一版封面帧复用首张静态预览。",
    }
    _jobs.write_json(job_dir / "cover_frame.json", cover)
    _jobs.append_log(job_id, "封面帧已生成。")
    return cover


def _write_preview_visual_report(job_id: str, previews: list[Any]) -> dict[str, Any]:
    job_dir = _jobs.JOBS_DIR / job_id
    checked = []
    failures = []
    for preview in previews[: min(5, len(previews))]:
        path = Path(preview)
        try:
            _jobs._verify_preview_frame_image(path)
            checked.append(str(path))
        except Exception as exc:
            failures.append({"path": str(path), "error": str(exc)})
    report = {
        "status": "passed" if checked and not failures else "failed",
        "checked_count": len(checked),
        "checked": checked,
        "failures": failures,
        "summary": f"已通过 {len(checked)} 张预览帧视觉 smoke。" if checked and not failures else "预览帧视觉 smoke 未通过。",
    }
    _jobs.write_json(job_dir / "preview_visual_report.json", report)
    if report["status"] == "passed":
        _jobs.append_log(job_id, report["summary"])
    else:
        _jobs.append_log(job_id, f"{report['summary']} {failures[0]['error'] if failures else '没有可检查预览帧。'}")
    return report


def _write_video_spec_report(job_id: str) -> dict[str, Any]:
    job_dir = _jobs.JOBS_DIR / job_id
    spec_path = job_dir / "video-spec.json"
    if not spec_path.exists():
        report = {
            "status": "missing",
            "path": str(spec_path),
            "summary": "未找到 video-spec.json 审计产物。",
        }
        _jobs.write_json(job_dir / "video_spec_report.json", report)
        _jobs.append_log(job_id, report["summary"])
        return report

    spec = _jobs.read_json(spec_path, {})
    scenes = spec.get("scenes") if isinstance(spec.get("scenes"), list) else []
    visual = spec.get("visual") if isinstance(spec.get("visual"), dict) else {}
    video_basics = spec.get("video_basics") if isinstance(spec.get("video_basics"), dict) else {}
    total_duration = float(video_basics.get("total_duration") or 0)
    report = {
        "status": "ready" if scenes else "review",
        "path": str(spec_path),
        "schema_version": str(spec.get("schema_version") or ""),
        "scene_count": len(scenes),
        "total_duration": total_duration,
        "theme_source": str(visual.get("theme_source") or ""),
        "theme": str(visual.get("theme") or ""),
        "summary": f"video-spec 审计已生成：{len(scenes)} 个 scene，主题来源 {visual.get('theme_source') or '-'}。",
    }
    _jobs.write_json(job_dir / "video_spec_report.json", report)
    _jobs.append_log(job_id, report["summary"])
    return report


def _write_readiness_report(
    job_id: str,
    projects: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    preview_count: int,
    has_cover: bool,
    visual_smoke_passed: bool = False,
) -> dict[str, Any]:
    quality = _jobs.read_json(_jobs.JOBS_DIR / job_id / "quality_report.json", {})
    publish_pack = _jobs.read_json(_jobs.JOBS_DIR / job_id / "publish_pack.json", {})
    checks = [
        _jobs._readiness_check("projects", bool(projects), "已确认项目", "缺少已确认项目"),
        _jobs._readiness_check("script", bool(segments), "已确认口播脚本", "缺少口播脚本"),
        _jobs._readiness_check("preview_frames", preview_count >= max(1, len(projects) + 3), f"已生成 {preview_count} 张预览帧", "预览帧数量不足"),
        _jobs._readiness_check("preview_visual_smoke", visual_smoke_passed, "预览帧视觉 smoke 已通过", "预览帧视觉 smoke 未通过"),
        _jobs._readiness_check("cover_frame", has_cover, "已生成封面帧", "缺少封面帧"),
        _jobs._readiness_check("publish_pack", bool(publish_pack.get("title") and publish_pack.get("description")), "已生成发布辅助包", "缺少发布辅助包"),
        _jobs._readiness_check("data_semantics", bool(publish_pack.get("data_note")), publish_pack.get("data_note") or _jobs.ESTIMATED_GROWTH_NOTE, "缺少热度口径说明"),
    ]
    if quality:
        fact_passed = _jobs._quality_verified(quality)
        checks.append(_jobs._readiness_check(
            "fact_check",
            fact_passed,
            f"质检状态: {quality.get('status')}",
            f"质检未验证或需要复核: {quality.get('status')}",
        ))
    score = int(sum(item["score"] for item in checks) / max(1, len(checks)))
    status = "ready" if score >= 85 and all(item["passed"] for item in checks) else "review"
    report = {
        "status": status,
        "score": score,
        "checks": checks,
        "summary": "可以进入最终渲染。" if status == "ready" else "进入最终渲染前建议复核未通过项。",
    }
    _jobs.write_json(_jobs.JOBS_DIR / job_id / "readiness_report.json", report)
    _jobs.append_log(job_id, f"发布准备度评分: {score} / 100，状态 {status}。")
    return report


def _write_pipeline_job_readiness_report(
    job_id: str,
    source_label: str,
    preview_count: int,
    has_cover: bool,
) -> dict[str, Any]:
    job_dir = _jobs.JOBS_DIR / job_id
    script = _jobs.read_json(job_dir / "script.json", {})
    segments = script.get("segments", []) if isinstance(script.get("segments"), list) else []
    has_desktop_plan = (job_dir / "desktop_review_plan.json").exists()
    checks = [
        _jobs._readiness_check("source", bool(source_label), f"已设置来源: {source_label}", "缺少任务来源"),
        _jobs._readiness_check("plan", _jobs._has_pipeline_plan(job_dir), "已生成分镜计划", "缺少分镜计划"),
        _jobs._readiness_check("script", bool(segments), "已生成口播脚本", "缺少口播脚本"),
        _jobs._readiness_check("preview_frames", preview_count > 0, f"已生成 {preview_count} 张预览帧", "缺少预览帧"),
        _jobs._readiness_check("cover_frame", has_cover, "已生成封面帧", "缺少封面帧"),
    ]
    if not has_desktop_plan:
        checks.insert(2, _jobs._readiness_check("asset_manifest", (job_dir / "asset_manifest.json").exists(), "已生成素材清单", "缺少素材清单"))
    score = int(sum(item["score"] for item in checks) / max(1, len(checks)))
    status = "ready" if all(item["passed"] for item in checks) else "review"
    report = {
        "status": status,
        "score": score,
        "checks": checks,
        "summary": "计划可进入最终渲染。" if status == "ready" else "进入最终渲染前建议复核未通过项。",
    }
    _jobs.write_json(job_dir / "readiness_report.json", report)
    _jobs.append_log(job_id, f"发布准备度评分: {score} / 100，状态 {status}。")
    return report


def _write_single_project_readiness_report(
    job_id: str,
    repo_url: str,
    preview_count: int,
    has_cover: bool,
) -> dict[str, Any]:
    return _jobs._write_pipeline_job_readiness_report(job_id, repo_url, preview_count, has_cover)


def _readiness_check(check_id: str, passed: bool, ok: str, fail: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": passed,
        "score": 100 if passed else 0,
        "message": ok if passed else fail,
    }


def _plan_validation_details(job_dir: Path) -> dict[str, Any]:
    manifest = _jobs.read_json(job_dir / "asset_manifest.json", {})
    shot_plan = _jobs.read_json(job_dir / "shot_plan.json", {})
    script = _jobs.read_json(job_dir / "script.json", {})
    asset_ids = {str(asset.get("id") or "") for asset in manifest.get("assets", []) if isinstance(asset, dict)}
    shot_assets = [
        str(shot.get("visual_asset") or "")
        for shot in shot_plan.get("shots", [])
        if isinstance(shot, dict) and str(shot.get("visual_asset") or "")
    ]
    durations = [
        float(segment.get("duration") or 0)
        for segment in script.get("segments", [])
        if isinstance(segment, dict)
    ]
    subtitles = [
        str(shot.get("subtitle") or "")
        for shot in shot_plan.get("shots", [])
        if isinstance(shot, dict)
    ]
    return {
        "asset_existence": {asset_id: asset_id in asset_ids for asset_id in shot_assets},
        "duration_sum": round(sum(durations), 1),
        "subtitle_length_check": "all_under_35_chars" if all(len(text) <= 35 for text in subtitles) else "has_long_subtitle",
    }


def _asset_manifest_from_dict(data: dict[str, Any]) -> AssetManifest:
    return AssetManifest(assets=[
        VisualAsset(
            id=str(asset.get("id") or ""),
            type=str(asset.get("type") or ""),
            source=str(asset.get("source") or ""),
            path=str(asset.get("path") or ""),
            caption=str(asset.get("caption") or ""),
            use_case=str(asset.get("use_case") or ""),
            quality=str(asset.get("quality") or ""),
        )
        for asset in data.get("assets", [])
        if isinstance(asset, dict)
    ])


def _video_script_from_dict(data: dict[str, Any]) -> VideoScript:
    return VideoScript(
        title=str(data.get("title") or "GitHub 项目推荐"),
        total_duration=float(data.get("total_duration") or 0),
        segments=[
            ScriptSegment(
                timestamp=float(segment.get("timestamp") or 0),
                duration=float(segment.get("duration") or 4),
                narration=str(segment.get("narration") or ""),
                action=str(segment.get("action") or ""),
                target=str(segment.get("target") or ""),
                focus_area=str(segment.get("focus_area") or ""),
            )
            for segment in data.get("segments", [])
            if isinstance(segment, dict)
        ],
    )


def _manifest(projects: list[dict[str, Any]]) -> AssetManifest:
    assets = []
    for index, project in enumerate(projects, start=1):
        assets.extend(_jobs._project_visual_assets(index, project))
    return AssetManifest(assets=assets)


def _project_visual_assets(index: int, project: dict[str, Any]) -> list[VisualAsset]:
    full_name = str(project.get("full_name") or "")
    repo_url = str(project.get("repo_url") or "")
    description = str(project.get("description") or project.get("description_zh") or "")[:60]
    candidates: list[tuple[str, str, str, str, str]] = []

    homepage = str(project.get("homepage") or "").strip()
    if homepage:
        candidates.append(("webpage", homepage, "项目官网或在线演示", "项目真实界面截图", "high"))
    for source in _jobs._readme_image_sources(project)[:2]:
        candidates.append(("image", source, "README 产品截图", "展示项目实际长相", "high"))
    if repo_url:
        candidates.append(("github_repo", repo_url, f"{full_name} - {description}", "GitHub 仓库来源页", "medium"))
    elif full_name:
        source = f"https://github.com/{full_name}"
        candidates.append(("github_repo", source, f"{full_name} - {description}", "GitHub 仓库来源页", "low"))

    assets = []
    seen = set()
    for asset_index, (type_, source, caption, use_case, quality) in enumerate(candidates, start=1):
        if not source or source in seen:
            continue
        seen.add(source)
        assets.append(VisualAsset(
            id=f"p{index}-asset-{asset_index:03d}",
            type=type_,
            source=source,
            path=source,
            caption=caption,
            use_case=use_case,
            quality=quality,
        ))
    return assets


def _readme_image_sources(project: dict[str, Any]) -> list[str]:
    readme = str(project.get("readme") or "")
    if not readme:
        screenshots = project.get("screenshots") or []
        if isinstance(screenshots, list):
            return [
                source
                for source in (str(item).strip() for item in screenshots)
                if source.startswith(("http://", "https://"))
            ]
        return []
    owner, repo = _jobs._project_owner_repo(project)
    branch = str(project.get("default_branch") or "main")
    base = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/" if owner and repo else ""
    sources = []
    for match in README_IMAGE_RE.finditer(readme):
        source = match.group(1).strip().split()[0].strip("<>")
        if not source:
            continue
        if source.startswith(("http://", "https://")):
            sources.append(source)
        elif base:
            sources.append(urljoin(base, source.removeprefix("./")))
    return sources


def _project_owner_repo(project: dict[str, Any]) -> tuple[str, str]:
    full_name = str(project.get("full_name") or "")
    if "/" in full_name:
        owner, repo = full_name.split("/", 1)
        return owner, repo
    path = urlparse(str(project.get("repo_url") or "")).path.strip("/")
    if "/" in path:
        owner, repo = path.split("/", 1)
        return owner, repo.removesuffix(".git")
    return "", ""


def _shot_plan(
    job: dict[str, Any],
    projects: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> ShotPlan:
    rows = [
        f"#{index} {project.get('name') or project.get('full_name')} {_jobs._star_label(int(project.get('stars') or 0))}"
        for index, project in enumerate(projects, start=1)
    ]
    row_payload = ";".join(rows)
    by_id = {segment.get("id"): segment.get("text", "") for segment in segments}
    shots = [
        Shot(
            start=0,
            duration=5.0,
            visual_asset="",
            visual_treatment="hotlist_opening",
            narration_intent="多项目热榜开场",
            subtitle=str(by_id.get("intro") or ""),
        ),
        Shot(
            start=5.0,
            duration=5.0,
            visual_asset="",
            visual_treatment=f"hotlist_ranking:{row_payload}",
            narration_intent="真实榜单总览",
            subtitle=_jobs._ranking_overview_line(projects),
        ),
    ]
    start = 10.0
    for index, project in enumerate(projects, start=1):
        hook = str(project.get("description_zh") or project.get("name") or "GitHub 项目")[:28]
        detail = "|".join([
            _jobs._short_text(_jobs._viewer_pain(project), 24),
            _jobs._short_text(_jobs._viewer_highlight(project), 24),
            _jobs._short_text(_jobs._viewer_audience(project), 18),
        ])
        safe_detail = "|".join(_jobs._safe_part(part) for part in detail.split("|"))
        shots.append(Shot(
            start=start,
            duration=5.0,
            visual_asset=f"p{index}-asset-001",
            visual_treatment=(
                f"hotlist_rank_card:{index}:{_jobs._safe_part(str(project.get('name') or 'GitHub 项目'))}:"
                f"{_jobs._star_label(int(project.get('stars') or 0))}:{_jobs._safe_part(hook)}:{safe_detail}"
            ),
            narration_intent=f"热榜项目 {index}",
            subtitle=str(by_id.get(f"project-{index}") or ""),
        ))
        start += 5.0
    shots.append(Shot(
        start=start,
        duration=5.0,
        visual_asset="",
        visual_treatment=f"hotlist_closing:{row_payload}",
        narration_intent="多项目趋势总结",
        subtitle=str(by_id.get("outro") or ""),
    ))
    return ShotPlan(title=str(job.get("title") or "GitHub 本期热榜"), shots=shots)


def _star_label(stars: int) -> str:
    if stars >= 1000:
        return f"{stars / 1000:.1f}K Star"
    return f"{stars:,} Star" if stars else "GitHub 项目"


def _safe_part(text: str) -> str:
    return text.replace(":", " ").replace("|", " ").replace(";", " ").strip()
