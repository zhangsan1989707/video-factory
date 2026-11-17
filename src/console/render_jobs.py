"""Plan validation, video rendering, progress tracking, numbering/finalization, and version listing for console jobs."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from src.console import jobs as _jobs
from src.console.background import JobCancelled, raise_if_cancelled
from src.hotlist_v2.template import normalize_style, render_engine_for_style
from src.utils.config import BGM_VOLUME, TTS_RATE, TTS_VOICE

# Render pipeline stage order, used to compute overall render progress percentage.
# Stages that share the same step (e.g. capturing_assets + generating_tts running
# concurrently) are listed in the order they typically finish. ``post_processing``
# is intentionally excluded — it is short and finalize-driven, so the bar jumps
# to 100% only when ``finalize_numbered_output`` runs. Unknown stages (e.g.
# ``preparing_plan`` / ``post_processing``) preserve the previous percent.
RENDER_STAGE_ORDER = (
    "capturing_assets",
    "generating_tts",
    "composing_html",
    "rendering_hyperframes",
    "mixing_audio",
    "composing_video",
)

# 标点/控制字符 → "-"，覆盖 ASCII 与常见全角标点
_FILENAME_SANITIZE_RE = re.compile(
    r"[\\/:*?\"<>|\s\u3000-\u303f\uff00-\uffef\u3001\u3002\uff0c\uff1a\uff1b\uff1f\uff01]+"
)


def reset_video_for_regeneration(job_id: str) -> dict[str, Any]:
    _jobs._require_regenerable_job(job_id)
    job = _jobs.read_job(job_id)
    if _jobs._job_type(job) == "single_project_vertical":
        _jobs._clear_current_video_output(job_id)
        _jobs.append_log(job_id, "已请求重新生成单项目最终视频；保留计划文件和历史正式版本。")
        return _jobs.update_job(
            job_id,
            status="ready_to_render",
            stage="preparing_plan",
            failed_stage="",
            error="",
            official_video="",
            render_progress={
                "stage": "preparing_plan",
                "stage_index": 0,
                "stage_total": len(_jobs.RENDER_STAGE_ORDER),
                "step_current": 1,
                "step_total": 1,
                "percent": 0,
                "message": "等待重新渲染",
            },
        )
    selected = _jobs.read_json(_jobs.JOBS_DIR / job_id / "selected_projects.json", {}).get("items") or []
    segments = _jobs.read_json(_jobs.JOBS_DIR / job_id / "narration.json", {}).get("segments") or []
    if not selected:
        raise ValueError("请先确认项目列表，再重新生成最终视频")
    if not segments:
        raise ValueError("请先确认口播脚本，再重新生成最终视频")
    _jobs._clear_current_video_output(job_id)
    _jobs.append_log(job_id, "已请求重新生成最终视频；保留当前项目和口播脚本。")
    return _jobs.update_job(
        job_id,
        status="ready_to_render",
        stage="preparing_plan",
        failed_stage="",
        error="",
        official_video="",
        render_progress={
            "stage": "preparing_plan",
            "stage_index": 0,
            "stage_total": len(_jobs.RENDER_STAGE_ORDER),
            "step_current": 1,
            "step_total": 1,
            "percent": 0,
            "message": "等待重新渲染",
        },
    )


async def _validate_single_project_plan(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    _jobs._require_stage(job, {"preparing_plan"}, "当前阶段不能校验计划文件")
    job_dir = _jobs.JOBS_DIR / job_id
    if not _jobs._has_pipeline_plan(job_dir):
        import asyncio

        if _jobs._job_type(job) == "from_plan_render":
            await asyncio.to_thread(_jobs._prepare_from_plan_render, job_id, job)
        else:
            await asyncio.to_thread(_jobs._prepare_single_project_plan, job_id, job)
    _jobs.append_log(job_id, f"开始校验{_jobs._job_type_label(job)} --from-plan dry run。")
    _jobs.update_job(
        job_id,
        status="running",
        stage="preparing_plan",
        failed_stage="",
        error="",
        plan_validation={"status": "running", "error": ""},
    )
    try:
        await _jobs.run_pipeline(
            url="",
            output=str(job_dir / "final.mp4"),
            orientation="vertical",
            from_plan=str(job_dir),
            style=_jobs._pipeline_style_for_job(job),
            dry_run=True,
            voice=_jobs._tts_voice(job),
            rate=_jobs._tts_rate(job),
        )
        details = _jobs._plan_validation_details(job_dir)
        _jobs.append_log(job_id, f"{_jobs._job_type_label(job)}计划文件校验通过，可进入最终渲染。")
        validation = {"status": "passed", "error": "", "details": details}
        _jobs.update_job(job_id, status="ready_to_render", stage="preparing_plan", plan_validation=validation)
        return {"job": _jobs.read_job(job_id), "plan_validation": validation, "artifacts": _jobs.job_artifacts(job_id)}
    except Exception as exc:
        _jobs.append_log(job_id, f"{_jobs._job_type_label(job)}计划文件校验失败: {exc}")
        validation = {"status": "failed", "error": str(exc)}
        _jobs.update_job(
            job_id,
            status="failed",
            stage="preparing_plan",
            failed_stage="preparing_plan",
            error=str(exc),
            plan_validation=validation,
        )
        raise


async def validate_plan(job_id: str) -> dict[str, Any]:
    job = _jobs.read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    if _jobs._job_type(job) in {"single_project_vertical", "desktop_review", "from_plan_render"}:
        return await _jobs._validate_single_project_plan(job_id, job)
    _jobs._require_stage(job, {"preparing_plan"}, "当前阶段不能校验计划文件")

    job_dir = _jobs.JOBS_DIR / job_id
    if not (job_dir / "shot_plan.json").exists():
        _jobs.prepare_plan(job_id)
    _jobs._ensure_quality_gate(job_id)

    _jobs.append_log(job_id, "开始校验 --from-plan dry run。")
    _jobs.update_job(
        job_id,
        status="running",
        stage="preparing_plan",
        failed_stage="",
        error="",
        plan_validation={"status": "running", "error": ""},
    )
    try:
        await _jobs.run_pipeline(
            url="",
            output=str(job_dir / "final.mp4"),
            orientation="vertical",
            from_plan=str(job_dir),
            style="hotlist",
            dry_run=True,
            voice=_jobs._tts_voice(job),
            rate=_jobs._tts_rate(job),
        )
        details = _jobs._plan_validation_details(job_dir)
        _jobs.append_log(job_id, "计划文件校验通过，可进入最终渲染。")
        validation = {"status": "passed", "error": "", "details": details}
        _jobs.update_job(job_id, status="ready_to_render", stage="preparing_plan", plan_validation=validation)
        return {"job": _jobs.read_job(job_id), "plan_validation": validation, "artifacts": _jobs.job_artifacts(job_id)}
    except Exception as exc:
        _jobs.append_log(job_id, f"计划文件校验失败: {exc}")
        validation = {"status": "failed", "error": str(exc)}
        _jobs.update_job(
            job_id,
            status="failed",
            stage="preparing_plan",
            failed_stage="preparing_plan",
            error=str(exc),
            plan_validation=validation,
        )
        raise


async def render_video(job_id: str) -> dict[str, Any]:
    job = _jobs.read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    if _jobs._job_type(job) in {"single_project_vertical", "desktop_review", "from_plan_render"}:
        return await _jobs._render_single_project_video(job_id, job)
    _jobs._require_stage(
        job,
        {
            "preparing_plan",
            "capturing_assets",
            "generating_tts",
            "composing_video",
            "composing_html",
            "rendering_hyperframes",
            "mixing_audio",
            "post_processing",
        },
        "当前阶段不能生成最终视频",
    )

    job_dir = _jobs.JOBS_DIR / job_id
    try:
        raise_if_cancelled(job_id)
        if not (job_dir / "shot_plan.json").exists():
            _jobs.prepare_plan(job_id)
        job = _jobs.read_job(job_id)
        _jobs._ensure_quality_gate(job_id)
        raise_if_cancelled(job_id)
        if (job.get("plan_validation") or {}).get("status") != "passed":
            await _jobs.validate_plan(job_id)
            job = _jobs.read_job(job_id)
        raise_if_cancelled(job_id)

        # 提前校验 BGM 路径，避免渲染完成后才发现文件不存在导致视频被删
        _ = _jobs._bgm_path(job)

        _jobs.append_log(job_id, "开始生成最终视频。这个阶段会生成语音并合成 mp4。")
        _jobs.update_job(
            job_id,
            status="running",
            failed_stage="",
            error="",
            cancel_requested=False,
            render_progress={
                "stage": "preparing_plan",
                "stage_index": 0,
                "stage_total": len(_jobs.RENDER_STAGE_ORDER),
                "step_current": 1,
                "step_total": 1,
                "percent": 0,
                "message": "开始渲染",
            },
        )

        def on_pipeline_stage(stage: str, message: str) -> None:
            raise_if_cancelled(job_id)
            _jobs.update_job(job_id, status="running", stage=stage)
            _jobs.append_log(job_id, message)
            _jobs._set_render_progress(job_id, stage=stage, step=1, total=1, message=message)

        def on_pipeline_progress(stage: str, step: int, total: int) -> None:
            raise_if_cancelled(job_id)
            _jobs._set_render_progress(job_id, stage=stage, step=step, total=total)

        selected = _jobs.read_json(job_dir / "selected_projects.json", {}).get("items") or []
        output_path = job_dir / "final.mp4"
        visual_style = _jobs._visual_style(job)
        if _jobs._render_engine(job) == "hyperframes":
            raise_if_cancelled(job_id)
            _jobs.append_log(job_id, f"使用 HyperFrames 模板渲染：{visual_style}。")
            narration_segments = _jobs.read_json(job_dir / "narration.json", {}).get("segments") or []
            await _jobs.render_hotlist_v2_from_projects(
                selected,
                output_path=output_path,
                style=visual_style,
                narration_segments=narration_segments,
                stage_callback=on_pipeline_stage,
                issue_number=_jobs._issue_number(job),
                voice=_jobs._tts_voice(job),
                rate=_jobs._tts_rate(job),
                progress_callback=on_pipeline_progress,
            )
            _jobs._write_video_spec_report(job_id)
            raise_if_cancelled(job_id)
            _jobs.update_job(job_id, status="running", stage="post_processing")
            _jobs._set_render_progress(job_id, stage="post_processing", step=1, total=1, message="开始执行视频后处理。")
            _jobs.append_log(job_id, "开始执行视频后处理。")
            _jobs.post_process_video(
                output_path,
                no_bgm=_jobs._no_bgm(job),
                bgm_volume=_jobs._bgm_volume(job),
                bgm_path=_jobs._bgm_path(job),
            )
        else:
            await _jobs.run_pipeline(
                url="",
                output=str(output_path),
                orientation="vertical",
                from_plan=str(job_dir),
                style="hotlist",
                no_bgm=_jobs._no_bgm(job),
                bgm_volume=_jobs._bgm_volume(job),
                bgm_path=_jobs._bgm_path(job),
                stage_callback=on_pipeline_stage,
                voice=_jobs._tts_voice(job),
                rate=_jobs._tts_rate(job),
                progress_callback=on_pipeline_progress,
            )
        raise_if_cancelled(job_id)
        _jobs.update_job(job_id, status="running", stage="post_processing")
        _jobs._set_render_progress(job_id, stage="post_processing", step=1, total=1, message=f"视频合成完成: {output_path}")
        _jobs.append_log(job_id, f"视频合成完成: {output_path}")
        return _jobs.finalize_numbered_output(job_id, str(job.get("title") or "GitHub热榜视频"))
    except JobCancelled as exc:
        failed_stage = str(_jobs.read_job(job_id).get("stage") or "composing_video")
        _jobs.append_log(job_id, str(exc))
        _jobs._clear_current_video_output(job_id)
        if _jobs._video_versions(job_id):
            _jobs.append_log(job_id, "已保留历史正式视频版本；仅清理本次未完成输出。")
        _jobs.update_job(
            job_id,
            status="failed",
            stage=failed_stage,
            failed_stage=failed_stage,
            error=str(exc),
            cancel_requested=False,
            render_progress={
                "stage": failed_stage,
                "stage_index": 0,
                "stage_total": len(_jobs.RENDER_STAGE_ORDER),
                "step_current": 1,
                "step_total": 1,
                "percent": 0,
                "message": "已取消",
            },
        )
        raise
    except Exception as exc:
        failed_stage = str(_jobs.read_job(job_id).get("stage") or "composing_video")
        _jobs.append_log(job_id, f"视频生成失败: {exc}")
        # 若失败发生在 post_processing（finalize 阶段，如复制到正式目录失败），
        # final.mp4 已渲染成功，不能删除，否则用户被迫重新渲染整段视频。
        if failed_stage != "post_processing":
            _jobs._clear_current_video_output(job_id)
            if _jobs._video_versions(job_id):
                _jobs.append_log(job_id, "历史正式视频版本仍保留；仅清理本次失败输出。")
        else:
            _jobs.append_log(job_id, "渲染已完成但输出到正式目录失败，final.mp4 已保留，可手动重试 finalize。")
        _jobs.update_job(
            job_id,
            status="failed",
            stage=failed_stage,
            failed_stage=failed_stage,
            error=str(exc),
            cancel_requested=False,
            render_progress={
                "stage": failed_stage,
                "stage_index": 0,
                "stage_total": len(_jobs.RENDER_STAGE_ORDER),
                "step_current": 1,
                "step_total": 1,
                "percent": 0,
                "message": "渲染失败",
            },
        )
        raise


async def _render_single_project_video(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    _jobs._require_stage(
        job,
        {
            "preparing_plan",
            "capturing_assets",
            "generating_tts",
            "composing_video",
            "post_processing",
        },
        "当前阶段不能生成最终视频",
    )
    job_dir = _jobs.JOBS_DIR / job_id
    try:
        raise_if_cancelled(job_id)
        if not _jobs._has_pipeline_plan(job_dir):
            import asyncio

            if _jobs._job_type(job) == "from_plan_render":
                await asyncio.to_thread(_jobs._prepare_from_plan_render, job_id, job)
            else:
                await asyncio.to_thread(_jobs._prepare_single_project_plan, job_id, job)
            job = _jobs.read_job(job_id)
        raise_if_cancelled(job_id)
        if (job.get("plan_validation") or {}).get("status") != "passed":
            await _jobs._validate_single_project_plan(job_id, job)
            job = _jobs.read_job(job_id)
        raise_if_cancelled(job_id)

        _jobs.append_log(job_id, f"开始生成{_jobs._job_type_label(job)}最终视频。这个阶段会采集素材、生成语音并合成 mp4。")
        _jobs.update_job(
            job_id,
            status="running",
            failed_stage="",
            error="",
            cancel_requested=False,
            render_progress={
                "stage": "preparing_plan",
                "stage_index": 0,
                "stage_total": len(_jobs.RENDER_STAGE_ORDER),
                "step_current": 1,
                "step_total": 1,
                "percent": 0,
                "message": "开始渲染",
            },
        )

        def on_pipeline_stage(stage: str, message: str) -> None:
            raise_if_cancelled(job_id)
            _jobs.update_job(job_id, status="running", stage=stage)
            _jobs.append_log(job_id, message)
            _jobs._set_render_progress(job_id, stage=stage, step=1, total=1, message=message)

        def on_pipeline_progress(stage: str, step: int, total: int) -> None:
            raise_if_cancelled(job_id)
            _jobs._set_render_progress(job_id, stage=stage, step=step, total=total)

        await _jobs.run_pipeline(
            url="",
            output=str(job_dir / "final.mp4"),
            orientation="vertical",
            from_plan=str(job_dir),
            style=_jobs._pipeline_style_for_job(job),
            no_bgm=_jobs._no_bgm(job),
            bgm_volume=_jobs._bgm_volume(job),
            bgm_path=_jobs._bgm_path(job),
            stage_callback=on_pipeline_stage,
            voice=_jobs._tts_voice(job),
            rate=_jobs._tts_rate(job),
            progress_callback=on_pipeline_progress,
        )
        raise_if_cancelled(job_id)
        _jobs.update_job(job_id, status="running", stage="post_processing")
        _jobs._set_render_progress(
            job_id,
            stage="post_processing",
            step=1,
            total=1,
            message=f"{_jobs._job_type_label(job)}视频合成完成: {job_dir / 'final.mp4'}",
        )
        _jobs.append_log(job_id, f"{_jobs._job_type_label(job)}视频合成完成: {job_dir / 'final.mp4'}")
        return _jobs.finalize_numbered_output(job_id, str(job.get("title") or _jobs._job_type_label(job)))
    except JobCancelled as exc:
        failed_stage = str(_jobs.read_job(job_id).get("stage") or "composing_video")
        _jobs.append_log(job_id, str(exc))
        _jobs._clear_current_video_output(job_id)
        if _jobs._video_versions(job_id):
            _jobs.append_log(job_id, "已保留历史正式视频版本；仅清理本次未完成输出。")
        _jobs.update_job(
            job_id,
            status="failed",
            stage=failed_stage,
            failed_stage=failed_stage,
            error=str(exc),
            cancel_requested=False,
            render_progress={
                "stage": failed_stage,
                "stage_index": 0,
                "stage_total": len(_jobs.RENDER_STAGE_ORDER),
                "step_current": 1,
                "step_total": 1,
                "percent": 0,
                "message": "已取消",
            },
        )
        raise
    except Exception as exc:
        failed_stage = str(_jobs.read_job(job_id).get("stage") or "composing_video")
        _jobs.append_log(job_id, f"{_jobs._job_type_label(job)}视频生成失败: {exc}")
        # 与 render_video 保持一致：post_processing 阶段失败时不删 final.mp4；
        # 其它阶段失败只删 final.mp4，保留 official_video 引用（避免历史正式版本丢失）。
        if failed_stage != "post_processing":
            _jobs._clear_current_video_output(job_id)
            if _jobs._video_versions(job_id):
                _jobs.append_log(job_id, "历史正式视频版本仍保留；仅清理本次失败输出。")
        else:
            _jobs.append_log(job_id, "渲染已完成但输出到正式目录失败，final.mp4 已保留，可手动重试 finalize。")
        _jobs.update_job(
            job_id,
            status="failed",
            stage=failed_stage,
            failed_stage=failed_stage,
            error=str(exc),
            cancel_requested=False,
            render_progress={
                "stage": failed_stage,
                "stage_index": 0,
                "stage_total": len(_jobs.RENDER_STAGE_ORDER),
                "step_current": 1,
                "step_total": 1,
                "percent": 0,
                "message": "渲染失败",
            },
        )
        raise


def finalize_numbered_output(job_id: str, title: str = "") -> dict[str, Any]:
    job = _jobs.read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    stage = str(job.get("stage") or "")
    status = str(job.get("status") or "")
    if stage not in {"post_processing", "completed"} and status != "completed":
        raise ValueError(f"当前阶段不能生成带编号正式文件: {stage or 'unknown'}")
    job_dir = _jobs.JOBS_DIR / job_id
    source = job_dir / "final.mp4"
    if not source.exists():
        raise ValueError("final.mp4 不存在，无法生成带编号正式文件")
    safe_title = _jobs._safe_filename(title or str(job.get("title") or "GitHub热榜视频"))
    base_name = _jobs._official_video_base_name(job, job_id, safe_title)
    target = _jobs._write_to_official_output_dir(job, source, base_name)
    _jobs.append_log(job_id, f"正式视频文件已输出到指定目录: {target}")
    params = dict(job.get("template_params") or {})
    params["official_output_dir"] = str(target.parent)
    _jobs.update_job(
        job_id,
        status="completed",
        stage="completed",
        official_video=str(target),
        template_params=params,
        render_progress={
            "stage": "completed",
            "stage_index": len(_jobs.RENDER_STAGE_ORDER),
            "stage_total": len(_jobs.RENDER_STAGE_ORDER),
            "step_current": 1,
            "step_total": 1,
            "percent": 100,
            "message": "渲染完成",
        },
    )
    _jobs._mark_published_in_lark(job_id)
    return {"job": _jobs.read_job(job_id), "artifacts": _jobs.job_artifacts(job_id)}


def _official_video_base_name(job: dict[str, Any], job_id: str, safe_title: str) -> str:
    return f"{_jobs._job_date_prefix(job_id)}-第{_jobs._official_issue_number(job, job_id):03d}期-{safe_title}"


def _job_date_prefix(job_id: str) -> str:
    parts = job_id.split("-")
    if len(parts) >= 3 and re.fullmatch(r"\d{8}", parts[2] or ""):
        return "-".join(parts[:3])
    return job_id


def _official_issue_number(job: dict[str, Any], job_id: str) -> int:
    issue = _jobs._issue_number(job)
    if issue is not None:
        return issue
    parts = job_id.split("-")
    if len(parts) >= 4:
        try:
            return int(parts[3])
        except ValueError:
            pass
    return 1


def _copy_with_retry(source: Path, target: Path, attempts: int = 3) -> None:
    """带退避的复制，规避 macOS 上偶发的 EPERM（如 TCC 提示/Spotlight/Time Machine）。"""
    delay = 0.4
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            _jobs.shutil.copy2(source, target)
            return
        except (PermissionError, OSError) as exc:
            last_exc = exc
            if attempt == attempts:
                break
            # EPERM 在 macOS 上多为瞬时（沙箱/索引器争抢文件锁），重试常常即可恢复
            _jobs.time.sleep(delay)
            delay *= 2
    assert last_exc is not None
    raise last_exc


def _write_to_official_output_dir(job: dict[str, Any], source: Path, base_name: str) -> Path:
    params = job.get("template_params") or {}
    output_dir_text = str(params.get("official_output_dir") or _jobs.DEFAULT_OFFICIAL_OUTPUT_DIR).strip()
    output_dir = Path(output_dir_text).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = _jobs._available_video_path(output_dir, base_name)
    try:
        _jobs._copy_with_retry(source, target)
    except Exception as exc:
        raise RuntimeError(
            f"无法将视频复制到正式输出目录: {target}（{exc}）。"
            "请检查目标目录权限、磁盘空间，以及 macOS 是否在弹出"
            "「允许访问文件夹」的系统对话框。"
        ) from exc
    return target


def _video_versions(job_id: str) -> list[dict[str, Any]]:
    job = _jobs.read_job(job_id) or {}
    official_name = Path(str(job.get("official_video") or "")).name
    official_text = str(job.get("official_video") or "").strip()
    official_path = Path(official_text) if official_text else None
    job_dir = _jobs.JOBS_DIR / job_id
    if not job_dir.exists():
        return []
    versions = []
    if official_path and official_path.exists() and not _jobs._is_relative_to(official_path, job_dir):
        try:
            stat = official_path.stat()
            versions.append({
                "name": official_path.name,
                "path": str(official_path),
                "size": stat.st_size,
                "updated_at": int(stat.st_mtime),
                "duration_seconds": _jobs._probe_video_duration(official_path),
                "is_official": True,
                "external": True,
            })
        except OSError:
            pass
    for path in sorted({*job_dir.glob(f"{job_id}-*.mp4"), *job_dir.glob(f"{_jobs._job_date_prefix(job_id)}-*.mp4")}):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        versions.append({
            "name": path.name,
            "path": str(path),
            "size": stat.st_size,
            "updated_at": int(stat.st_mtime),
            "duration_seconds": _jobs._probe_video_duration(path),
            "is_official": bool(official_name and path.name == official_name),
        })
    return sorted(versions, key=lambda item: (item["updated_at"], _jobs._version_index(str(item["name"]))))


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _probe_video_duration(path: Path) -> float | None:
    try:
        result = _jobs.subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
        value = float((result.stdout or "").strip())
        return round(value, 1) if value >= 0 else None
    except Exception:
        return None


def _clear_video_outputs(job_id: str) -> None:
    _jobs._clear_current_video_output(job_id)
    _jobs.update_job(job_id, official_video="")


def _clear_current_video_output(job_id: str) -> None:
    final = _jobs.JOBS_DIR / job_id / "final.mp4"
    if final.exists() and final.is_file():
        final.unlink()


def _version_index(name: str) -> int:
    match = re.search(r"-v(\d+)\.mp4$", name)
    return int(match.group(1)) if match else 1


def _no_bgm(job: dict[str, Any]) -> bool:
    params = job.get("template_params") or {}
    return params.get("bgm") == "none"


def _bgm_path(job: dict[str, Any]) -> str | None:
    params = job.get("template_params") or {}
    if params.get("bgm") != "custom":
        return None
    bgm_path_str = str(params.get("bgm_path") or "").strip()
    if not bgm_path_str:
        raise ValueError("已选择自定义 BGM 但未提供文件路径")
    path = Path(bgm_path_str).expanduser()
    if not path.exists() or not path.is_file():
        raise ValueError(f"自定义 BGM 文件不存在: {path}")
    if path.suffix.lower() not in {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac"}:
        raise ValueError(f"不支持的 BGM 文件格式: {path.suffix}")
    return str(path)


def _bgm_volume(job: dict[str, Any]) -> float:
    params = job.get("template_params") or {}
    raw = params.get("bgm_volume", BGM_VOLUME)
    if isinstance(raw, bool):
        return BGM_VOLUME
    try:
        volume = float(raw)
    except (TypeError, ValueError):
        return BGM_VOLUME
    return min(1.0, max(0.0, volume))


def _tts_voice(job: dict[str, Any]) -> str:
    """从任务模板参数中读取 TTS 声音；未配置时回落到全局默认值。"""
    params = job.get("template_params") or {}
    voice = str(params.get("tts_voice") or "").strip()
    return voice or TTS_VOICE


def _tts_rate(job: dict[str, Any]) -> str:
    """从任务模板参数中读取 TTS 语速；未配置时回落到全局默认值。"""
    params = job.get("template_params") or {}
    rate = str(params.get("tts_rate") or "").strip()
    return rate or TTS_RATE


def _visual_style(job: dict[str, Any]) -> str:
    params = job.get("template_params") or {}
    return normalize_style(str(params.get("style") or params.get("visual_style") or "tech_hotspot"))


def _render_engine(job: dict[str, Any]) -> str:
    params = job.get("template_params") or {}
    engine = str(params.get("render_engine") or "").strip()
    if engine in {"hyperframes", "pil"}:
        return engine
    return render_engine_for_style(_jobs._visual_style(job))


def _issue_number(job: dict[str, Any]) -> int | None:
    params = job.get("template_params") or {}
    val = params.get("issue_number")
    if val is not None:
        try:
            n = int(val)
            return n if n > 0 else None
        except (TypeError, ValueError):
            return None
    return None


def _pipeline_style_for_job(job: dict[str, Any]) -> str:
    job_type = _jobs._job_type(job)
    if job_type == "desktop_review":
        return "desktop-review"
    if job_type == "from_plan_render":
        return "default"
    return "single-review"


def _job_type_label(job: dict[str, Any]) -> str:
    return {
        "single_project_vertical": "单项目竖屏",
        "desktop_review": "桌面审阅",
        "from_plan_render": "计划文件",
    }.get(_jobs._job_type(job), "任务")


def _render_command_for_job(job: dict[str, Any], job_dir: Path) -> str:
    job_type = _jobs._job_type(job)
    repo_url = str(job.get("repo_url") or "")
    if job_type == "desktop_review":
        return f".venv/bin/python -m src.cli {repo_url} -o {job_dir / 'final.mp4'} --style desktop-review"
    if job_type == "from_plan_render":
        return f".venv/bin/python -m src.cli --from-plan {job_dir} -o {job_dir / 'final.mp4'}"
    return f".venv/bin/python -m src.cli {repo_url} -o {job_dir / 'final.mp4'} --vertical --style single-review"


def _set_render_progress(
    job_id: str,
    *,
    stage: str,
    step: int,
    total: int,
    message: str | None = None,
) -> None:
    """Persist a fine-grained render progress snapshot to the job for UI display.

    Stores ``render_progress`` on the job dict with ``stage``, ``step_current``,
    ``step_total``, ``stage_index``, ``stage_total``, ``percent``, ``message``.
    The ``percent`` is clamped to ``[0, 100]`` and is monotonically non-decreasing
    within a single render attempt so the UI bar never moves backwards.
    """
    step_total = max(1, int(total))
    step_current = max(1, min(int(step), step_total))
    stage_total = len(_jobs.RENDER_STAGE_ORDER)
    job = _jobs.read_job(job_id)
    if not job:
        return
    previous = job.get("render_progress") or {}
    previous_percent = int(previous.get("percent") or 0)
    try:
        stage_index = _jobs.RENDER_STAGE_ORDER.index(stage) + 1
    except ValueError:
        # Unknown stage (e.g. preparing_plan / post_processing): keep previous
        # percent, just refresh stage label + message so the UI shows real status.
        payload = {
            "stage": stage,
            "stage_index": int(previous.get("stage_index") or 0),
            "stage_total": stage_total,
            "step_current": step_current,
            "step_total": step_total,
            "percent": previous_percent,
        }
        if message:
            payload["message"] = str(message)[:200]
        _jobs.update_job(job_id, render_progress=payload)
        return
    stage_factor = (stage_index - 1) + (step_current / step_total)
    percent = int(round((stage_factor / stage_total) * 100))
    percent = max(0, min(100, percent))
    if percent < previous_percent:
        # Don't let the bar move backwards within a render attempt.
        percent = previous_percent
    payload = {
        "stage": stage,
        "stage_index": stage_index,
        "stage_total": stage_total,
        "step_current": step_current,
        "step_total": step_total,
        "percent": percent,
    }
    if message:
        payload["message"] = str(message)[:200]
    _jobs.update_job(job_id, render_progress=payload)


def _safe_filename(text: str) -> str:
    """生成稳定可移植的视频文件名片段。

    规则：
    - 把 ASCII 与全角标点统一替换为 ``-``，避免 macOS 路径解析/HFS+ 边界问题。
    - 折叠连续 ``-``，去掉首尾的 ``-``、``.`` 和空白。
    - 截断到 40 字符，必要时省略号收尾，且不再追加 ``...``，避免和 ``.mp4`` 拼出
      ``....mp4`` 这种容易被某些工具误读的尾巴。
    """
    if not text:
        return "GitHub热榜视频"
    cleaned = _FILENAME_SANITIZE_RE.sub("-", text)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-").strip().rstrip(".")
    if not cleaned:
        return "GitHub热榜视频"
    if len(cleaned) > 40:
        cleaned = cleaned[:40].rstrip("-").rstrip(".") or cleaned[:40]
    return cleaned or "GitHub热榜视频"


def _available_video_path(directory: Path, stem: str) -> Path:
    target = directory / f"{stem}.mp4"
    if not target.exists():
        return target
    index = 2
    while True:
        candidate = directory / f"{stem}-v{index}.mp4"
        if not candidate.exists():
            return candidate
        index += 1
