"""Console job orchestration."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from src.console.background import JobCancelled, is_active, raise_if_cancelled
from src.console.github_hotlist import ESTIMATED_GROWTH_NOTE, collect_candidates_with_meta
from src.console.model_router import chat_json_detail, route_snapshot
from src.console.store import (
    JOBS_DIR,
    append_model_call,
    append_log,
    create_job,
    job_artifacts,
    next_job_id,
    read_github_token,
    read_job,
    read_json,
    read_log,
    read_log_tail,
    summarize_model_usage,
    update_github_rate_limit,
    update_job,
    write_json,
)
from src.models import AssetManifest, ScriptSegment, Shot, ShotPlan, VideoScript, VisualAsset, shot_plan_from_dict
from src.pipeline import run_pipeline
from src.composer.bgm import post_process_video
from src.composer.vertical import render_vertical_previews
from src.hotlist_v2.render import _resolve_issue_number, render_hotlist_v2_from_projects, render_hotlist_v2_previews_from_projects
from src.hotlist_v2.template import normalize_style, render_engine_for_style
from src.planner.script_v2 import generate_script_from_shot_plan
from src.console.quality import (
    _apply_quality_override,
    _ensure_quality_gate,
    _quality_allows_render,
    _quality_blocks_render,
    _quality_check_script,
    _quality_verified,
)
from src.console.shared import (
    _apply_feature_to_project_copy,
    _clip_multiline,
    _contains_forbidden_narration,
    _contains_producer_visual_jargon,
    _fallback_feature_extract,
    _has_keyword,
    _project_text,
    _quantified_benefit,
    _readme_excerpt,
    _record_model_call,
    _route_available,
    _route_skip_reason,
    _sanitize_feature_extract,
    _short_text,
    _viewer_audience,
    _viewer_highlight,
    _viewer_outcome,
    _viewer_pain,
    _viewer_safe_value,
    _write_ai_raw_response,
)
from src.utils.config import BGM_VOLUME

README_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

def create_hotlist_job(payload: dict[str, Any]) -> dict[str, Any]:
    return _create_job_with_retry("GH-HOTLIST", _with_auto_issue_number(payload))

def create_single_project_vertical_job(payload: dict[str, Any]) -> dict[str, Any]:
    return _create_job_with_retry("GH-SINGLE", {**payload, "type": "single_project_vertical"})

def create_desktop_review_job(payload: dict[str, Any]) -> dict[str, Any]:
    return _create_job_with_retry("GH-DESKTOP", {**payload, "type": "desktop_review"})

def create_from_plan_render_job(payload: dict[str, Any]) -> dict[str, Any]:
    return _create_job_with_retry("GH-PLAN", {**payload, "type": "from_plan_render"})

def _create_job_with_retry(prefix: str, payload: dict[str, Any]) -> dict[str, Any]:
    last_error: ValueError | None = None
    for _attempt in range(5):
        job_id = next_job_id(prefix)
        try:
            return create_job(job_id, payload)
        except ValueError as exc:
            if "任务目录已存在" not in str(exc):
                raise
            last_error = exc
    raise last_error or ValueError("无法创建任务")

def _with_auto_issue_number(payload: dict[str, Any]) -> dict[str, Any]:
    params = dict(payload.get("template_params") or {})
    if _issue_number({"template_params": params}) is None:
        params["issue_number"] = _resolve_issue_number()
    return {**payload, "template_params": params}

async def generate_candidates(job_id: str, force_refresh: bool = False) -> dict[str, Any]:
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    _require_job_type(job, "github_hotlist", "当前任务类型不支持候选生成")
    _require_stage(job, {"draft_pending", "collecting_candidates", "analyzing_candidates", "awaiting_project_confirmation"}, "当前阶段不能生成候选项目")
    return await _generate_candidates_snapshot(job_id, job, force_refresh=force_refresh)

async def regenerate_candidates(job_id: str) -> dict[str, Any]:
    job = _require_regenerable_job(job_id)
    append_log(job_id, "已请求重新生成候选项目；将清除已选项目、口播、计划文件和视频产物。")
    return await _generate_candidates_snapshot(job_id, job, force_refresh=True)

async def _generate_candidates_snapshot(job_id: str, job: dict[str, Any], force_refresh: bool = False) -> dict[str, Any]:
    is_refresh = force_refresh and str(job.get("stage") or "") == "awaiting_project_confirmation"
    if is_refresh:
        _clear_candidates_only(job_id)
        append_log(job_id, "已请求跳过缓存，仅刷新候选数据，保留已选项目和口播。")
    else:
        _clear_candidate_artifacts(job_id)
    update_job(job_id, status="running", stage="collecting_candidates", failed_stage="", error="")
    append_log(job_id, f"开始拉取 {job.get('time_window', 'weekly')} 候选项目。"
               + ("（跳过缓存）" if force_refresh else ""))
    try:
        result = await collect_candidates_with_meta(
            time_window=str(job.get("time_window") or "weekly"),
            token=read_github_token(),
            limit=30,
            force_refresh=force_refresh,
        )
        candidates = result["items"]
        update_github_rate_limit(str(result.get("rate_limit") or "未检测"))
        if result.get("cache_status") == "hit":
            append_log(job_id, "GitHub 候选缓存命中，未请求 API。")
            append_log(job_id, f"GitHub 缓存记录额度: {result.get('rate_limit') or '未检测'}。")
        elif result.get("cache_status") == "stale_rate_limit":
            append_log(job_id, "GitHub 额度受限，已使用最近缓存候选。")
            append_log(job_id, f"GitHub 缓存记录额度: {result.get('rate_limit') or '未检测'}。")
        else:
            append_log(job_id, f"GitHub API 额度: {result.get('rate_limit') or '未检测'}。")
        append_log(job_id, ESTIMATED_GROWTH_NOTE)
        update_job(job_id, status="running", stage="analyzing_candidates")
        _update_candidate_source(job_id, {
            "cache_status": str(result.get("cache_status") or "fresh"),
            "cache_label": _candidate_cache_label(str(result.get("cache_status") or "fresh")),
            "analysis_status": "pending",
            "analysis_label": "候选分析进行中",
            "ranking_status": "pending",
            "ranking_label": "排序进行中",
        })
        candidates = _analyze_candidates(job_id, candidates)
        candidates = _rank_candidates(job_id, candidates)
        write_json(JOBS_DIR / job_id / "candidates.json", {"items": candidates})
        append_log(job_id, f"候选项目拉取完成，共 {len(candidates)} 个。")
        update_job(job_id, status="awaiting_input", stage="awaiting_project_confirmation")
        return {"job": read_job(job_id), "candidates": candidates}
    except Exception as exc:
        append_log(job_id, f"候选项目拉取失败: {exc}")
        failed_stage = str(read_job(job_id).get("stage") or "collecting_candidates")
        update_job(job_id, status="failed", stage=failed_stage, failed_stage=failed_stage, error=str(exc))
        raise

def save_selection(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    _require_stage(job, {"awaiting_project_confirmation", "generating_script"}, "当前阶段不能确认项目")
    items = payload.get("items") or []
    if not items:
        raise ValueError("至少需要选择 1 个项目")

    project_count = int(job.get("project_count") or 5)
    if len(items) > project_count:
        raise ValueError(f"最多只能选择 {project_count} 个项目，当前选择 {len(items)} 个")
    selected = _selected_from_candidate_snapshot(job_id, items)
    selected = _ensure_feature_extracts(job_id, selected)
    _clear_plan_artifacts(job_id)
    _clear_script_metadata(job_id)
    write_json(JOBS_DIR / job_id / "selected_projects.json", {"items": selected})
    append_log(job_id, f"已确认 {len(selected)} 个入选项目。")
    return _generate_script_for_selection(job_id, selected)

def regenerate_script(job_id: str) -> dict[str, Any]:
    _require_regenerable_job(job_id)
    selected = read_json(JOBS_DIR / job_id / "selected_projects.json", {}).get("items") or []
    if not selected:
        raise ValueError("请先确认项目列表，再重新生成口播脚本")
    append_log(job_id, "已请求重新生成口播脚本；将清除已确认口播后的计划文件和视频产物。")
    _clear_plan_artifacts(job_id)
    _clear_script_metadata(job_id)
    return _generate_script_for_selection(job_id, selected)

def _generate_script_for_selection(job_id: str, selected: list[dict[str, Any]]) -> dict[str, Any]:
    update_job(job_id, status="running", stage="generating_script", error="")
    selected = _ensure_feature_extracts(job_id, selected)
    write_json(JOBS_DIR / job_id / "selected_projects.json", {"items": selected})

    hook = _generate_hook(job_id, selected)
    narrations = _model_narrations(job_id, selected)
    if narrations is None:
        narrations = _default_narrations(selected)
    narrations = _polish_narrations(job_id, selected, narrations)
    write_json(JOBS_DIR / job_id / "narration.json", {"segments": narrations})
    append_log(job_id, "已生成初版口播脚本，等待人工确认。")
    update_job(job_id, status="awaiting_input", stage="awaiting_script_confirmation", plan_validation={"status": "not_run", "error": ""})
    return {"job": read_job(job_id), "segments": narrations, "hook": hook}

def reset_video_for_regeneration(job_id: str) -> dict[str, Any]:
    _require_regenerable_job(job_id)
    job = read_job(job_id)
    if _job_type(job) == "single_project_vertical":
        _clear_current_video_output(job_id)
        append_log(job_id, "已请求重新生成单项目最终视频；保留计划文件和历史正式版本。")
        return update_job(job_id, status="ready_to_render", stage="preparing_plan", failed_stage="", error="", official_video="")
    selected = read_json(JOBS_DIR / job_id / "selected_projects.json", {}).get("items") or []
    segments = read_json(JOBS_DIR / job_id / "narration.json", {}).get("segments") or []
    if not selected:
        raise ValueError("请先确认项目列表，再重新生成最终视频")
    if not segments:
        raise ValueError("请先确认口播脚本，再重新生成最终视频")
    _clear_current_video_output(job_id)
    append_log(job_id, "已请求重新生成最终视频；保留当前项目和口播脚本。")
    return update_job(job_id, status="ready_to_render", stage="preparing_plan", failed_stage="", error="", official_video="")

def _require_regenerable_job(job_id: str) -> dict[str, Any]:
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    if str(job.get("status") or "") == "running":
        raise ValueError("任务运行中，不能重新生成")
    return job

def save_script(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    if _job_type(job) in {"single_project_vertical", "desktop_review", "from_plan_render"}:
        return _save_pipeline_job_script(job_id, job, payload)
    _require_stage(job, {"awaiting_script_confirmation", "preparing_plan"}, "当前阶段不能确认口播")
    selected = read_json(JOBS_DIR / job_id / "selected_projects.json", {}).get("items") or []
    if not selected:
        raise ValueError("请先确认项目列表")
    segments = payload.get("segments") or []
    if not segments:
        raise ValueError("口播脚本不能为空")
    _validate_script_segments(selected, segments)
    update_job(job_id, status="running", stage="awaiting_script_confirmation", error="")
    _clear_plan_artifacts(job_id)
    write_json(JOBS_DIR / job_id / "narration.json", {"segments": segments})
    append_log(job_id, "口播脚本已确认。")
    _quality_check_script(job_id, segments, selected)
    quality = read_json(JOBS_DIR / job_id / "quality_report.json", {})
    ignored = bool(payload.get("ignore_quality_risk"))
    if _quality_blocks_render(quality) and not ignored:
        publish_pack = _write_publish_pack(job_id, selected, segments)
        update_job(
            job_id,
            status="awaiting_input",
            stage="awaiting_script_confirmation",
            error="脚本质检未通过，请复核风险项或手动忽略后继续。",
            plan_validation={"status": "not_run", "error": ""},
        )
        return {
            "job": read_job(job_id),
            "segments": segments,
            "quality_report": quality,
            "publish_pack": publish_pack,
        }
    if ignored and _quality_blocks_render(quality):
        quality = _apply_quality_override(job_id, quality)
    publish_pack = _write_publish_pack(job_id, selected, segments)
    update_job(job_id, status="awaiting_render", stage="preparing_plan", error="", plan_validation={"status": "not_run", "error": ""})
    return {
        "job": read_job(job_id),
        "segments": segments,
        "quality_report": read_json(JOBS_DIR / job_id / "quality_report.json", {}),
        "publish_pack": publish_pack,
    }

def _save_pipeline_job_script(job_id: str, job: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    _require_stage(job, {"awaiting_script_confirmation", "preparing_plan"}, "当前阶段不能确认口播")
    segments = payload.get("segments") or []
    if not segments:
        raise ValueError("口播脚本不能为空")
    projects = _pipeline_job_projects(job_id, job)
    _validate_pipeline_script_segments(segments)
    update_job(job_id, status="running", stage="awaiting_script_confirmation", error="")
    write_json(JOBS_DIR / job_id / "narration.json", {"segments": segments})
    _write_script_from_console_segments(job_id, segments)
    append_log(job_id, "口播脚本已确认。")
    _quality_check_script(job_id, segments, projects)
    quality = read_json(JOBS_DIR / job_id / "quality_report.json", {})
    ignored = bool(payload.get("ignore_quality_risk"))
    if _quality_blocks_render(quality) and not ignored:
        publish_pack = _write_pipeline_publish_pack(job_id, job, projects, segments)
        update_job(
            job_id,
            status="awaiting_input",
            stage="awaiting_script_confirmation",
            error="脚本质检未通过，请复核风险项或手动忽略后继续。",
            plan_validation={"status": "not_run", "error": ""},
        )
        return {
            "job": read_job(job_id),
            "segments": segments,
            "quality_report": quality,
            "publish_pack": publish_pack,
        }
    if ignored and _quality_blocks_render(quality):
        quality = _apply_quality_override(job_id, quality)
    publish_pack = _write_pipeline_publish_pack(job_id, job, projects, segments)
    update_job(job_id, status="awaiting_validation", stage="preparing_plan", error="", plan_validation={"status": "not_run", "error": ""})
    return {
        "job": read_job(job_id),
        "segments": segments,
        "quality_report": read_json(JOBS_DIR / job_id / "quality_report.json", {}),
        "publish_pack": publish_pack,
    }

def _require_stage(job: dict[str, Any], allowed: set[str], message: str) -> None:
    if str(job.get("stage") or "") not in allowed:
        raise ValueError(f"{message}: {job.get('stage') or 'unknown'}")

def _validate_script_segments(projects: list[dict[str, Any]], segments: list[dict[str, Any]]) -> None:
    expected = ["intro", *[f"project-{index}" for index in range(1, len(projects) + 1)], "outro"]
    by_id = {str(segment.get("id") or ""): segment for segment in segments if isinstance(segment, dict)}
    missing = [segment_id for segment_id in expected if not str((by_id.get(segment_id) or {}).get("text") or "").strip()]
    if missing:
        raise ValueError(f"口播脚本缺少段落: {', '.join(missing)}")

def _validate_pipeline_script_segments(segments: list[dict[str, Any]]) -> None:
    missing = [
        str(segment.get("id") or f"segment-{index}")
        for index, segment in enumerate(segments, start=1)
        if not str((segment or {}).get("text") or "").strip()
    ]
    if missing:
        raise ValueError(f"口播脚本缺少段落: {', '.join(missing)}")

def _console_segments_from_script(job_dir: Path) -> list[dict[str, str]]:
    script = read_json(job_dir / "script.json", {})
    raw_segments = script.get("segments", []) if isinstance(script.get("segments"), list) else []
    segments = []
    total = len(raw_segments)
    for index, segment in enumerate(raw_segments, start=1):
        if not isinstance(segment, dict):
            continue
        if index == 1:
            segment_id = "intro"
            label = "开场"
        elif index == total:
            segment_id = "outro"
            label = "结尾"
        else:
            segment_id = f"project-{index - 1}"
            label = f"段落 {index - 1}"
        segments.append({
            "id": segment_id,
            "label": label,
            "text": str(segment.get("narration") or ""),
        })
    return segments

def _write_script_from_console_segments(job_id: str, console_segments: list[dict[str, Any]]) -> None:
    script_path = JOBS_DIR / job_id / "script.json"
    script = read_json(script_path, {})
    raw_segments = script.get("segments", []) if isinstance(script.get("segments"), list) else []
    by_id = {str(segment.get("id") or ""): str(segment.get("text") or "") for segment in console_segments if isinstance(segment, dict)}
    patched = []
    total = len(raw_segments)
    for index, segment in enumerate(raw_segments, start=1):
        if not isinstance(segment, dict):
            continue
        if index == 1:
            segment_id = "intro"
        elif index == total:
            segment_id = "outro"
        else:
            segment_id = f"project-{index - 1}"
        item = dict(segment)
        if segment_id in by_id:
            item["narration"] = by_id[segment_id]
        patched.append(item)
    script["segments"] = patched
    write_json(script_path, script)

def _selected_from_candidate_snapshot(job_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = read_json(JOBS_DIR / job_id / "candidates.json", {}).get("items") or []
    by_key = {}
    for candidate in candidates:
        key = _candidate_key(candidate)
        if key:
            by_key[key] = candidate
    if not by_key:
        raise ValueError("候选快照不存在，请先生成候选项目")
    selected = []
    seen = set()
    for item in items:
        key = _candidate_key(item)
        if not key or key not in by_key:
            raise ValueError(f"候选快照中不存在: {item.get('full_name') or item.get('name') or 'unknown'}")
        if key in seen:
            raise ValueError(f"不能重复选择同一个项目: {item.get('full_name') or item.get('name') or key}")
        seen.add(key)
        selected.append(dict(by_key[key]))
    return selected

def _candidate_key(item: dict[str, Any]) -> str:
    return str(item.get("full_name") or item.get("repo_url") or "").strip()

def _clear_candidate_artifacts(job_id: str) -> None:
    job_dir = JOBS_DIR / job_id
    for name in ("candidates.json", "selected_projects.json", "narration.json", "hook.json"):
        path = job_dir / name
        if path.exists() and path.is_file():
            path.unlink()
    _clear_script_metadata(job_id)
    _clear_plan_artifacts(job_id)

def _clear_candidates_only(job_id: str) -> None:
    """Only clear candidates.json, preserving selected projects and narration."""
    path = JOBS_DIR / job_id / "candidates.json"
    if path.exists() and path.is_file():
        path.unlink()

def _clear_plan_artifacts(job_id: str) -> None:
    job_dir = JOBS_DIR / job_id
    for name in (
        "asset_manifest.json",
        "shot_plan.json",
        "script.json",
        "info.json",
        "cover_frame.png",
        "cover_frame.json",
        "readiness_report.json",
        "final.mp4",
    ):
        path = job_dir / name
        if path.exists() and path.is_file():
            path.unlink()
    preview_dir = job_dir / "preview_frames"
    if preview_dir.exists() and preview_dir.is_dir():
        shutil.rmtree(preview_dir)
    update_job(job_id, official_video="")

def _clear_desktop_plan_artifacts(job_id: str) -> None:
    job_dir = JOBS_DIR / job_id
    for name in ("desktop_review_plan.json",):
        path = job_dir / name
        if path.exists() and path.is_file():
            path.unlink()

def _clear_script_metadata(job_id: str) -> None:
    job_dir = JOBS_DIR / job_id
    for name in ("quality_report.json", "publish_pack.json", "narration_source.json"):
        path = job_dir / name
        if path.exists() and path.is_file():
            path.unlink()

def _job_type(job: dict[str, Any]) -> str:
    return str(job.get("type") or "github_hotlist")

def _require_job_type(job: dict[str, Any], expected: str, message: str) -> None:
    if _job_type(job) != expected:
        raise ValueError(f"{message}: {_job_type(job)}")

def prepare_plan(job_id: str) -> dict[str, Any]:
    """Prepare current pipeline files without starting expensive rendering."""
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    if _job_type(job) in {"single_project_vertical", "desktop_review"}:
        return _prepare_single_project_plan(job_id, job)
    if _job_type(job) == "from_plan_render":
        return _prepare_from_plan_render(job_id, job)
    _require_stage(job, {"preparing_plan"}, "当前阶段不能生成计划文件")
    if str(job.get("status") or "") not in {"awaiting_render", "awaiting_validation", "ready_to_render", "failed"}:
        raise ValueError(f"当前状态不能生成计划文件: {job.get('status') or 'unknown'}")
    selected = read_json(JOBS_DIR / job_id / "selected_projects.json", {}).get("items") or []
    segments = read_json(JOBS_DIR / job_id / "narration.json", {}).get("segments") or []
    if not selected:
        raise ValueError("请先确认项目列表")
    if not segments:
        raise ValueError("请先确认口播脚本")
    _ensure_quality_gate(job_id)

    update_job(job_id, status="running", stage="preparing_plan", failed_stage="", error="")
    append_log(job_id, "开始生成流水线计划文件。")

    job_dir = JOBS_DIR / job_id
    try:
        manifest = _manifest(selected)
        shot_plan = _shot_plan(job, selected, segments)
        script = generate_script_from_shot_plan(shot_plan)

        write_json(job_dir / "asset_manifest.json", manifest.to_dict())
        write_json(job_dir / "shot_plan.json", shot_plan.to_dict())
        write_json(job_dir / "script.json", script.to_dict())
        write_json(job_dir / "info.json", {"projects": selected})
        visual_style = _visual_style(job)
        if _render_engine(job) == "hyperframes":
            previews = render_hotlist_v2_previews_from_projects(selected, job_dir / "preview_frames", style=visual_style, issue_number=_issue_number(job))
        else:
            previews = render_vertical_previews(script, shot_plan, manifest, job_dir / "preview_frames")
        cover = _write_cover_frame(job_id, previews)
        readiness = _write_readiness_report(job_id, selected, segments, len(previews), bool(cover.get("path")))
        append_log(job_id, f"计划文件已生成，并输出 {len(previews)} 张静态预览帧；预览帧来自当前渲染模板，入场、扫光和数字动效会在正式 MP4 渲染时体现。")
        update_job(
            job_id,
            status="awaiting_validation",
            stage="preparing_plan",
            plan_validation={"status": "not_run", "error": ""},
        )
        return {
            "job": read_job(job_id),
            "artifacts": job_artifacts(job_id),
            "plan_validation": {"status": "not_run", "error": ""},
            "cover_frame": cover,
            "readiness_report": readiness,
            "render_command": f".venv/bin/python -m src.cli --from-plan {job_dir} -o {job_dir / 'final.mp4'} --vertical",
        }
    except Exception as exc:
        append_log(job_id, f"计划文件生成失败: {exc}")
        _clear_plan_artifacts(job_id)
        update_job(job_id, status="failed", stage="preparing_plan", failed_stage="preparing_plan", error=str(exc))
        raise

def _prepare_single_project_plan(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    _require_stage(job, {"preparing_plan"}, "当前阶段不能生成计划文件")
    if str(job.get("status") or "") not in {"awaiting_render", "awaiting_validation", "ready_to_render", "failed"}:
        raise ValueError(f"当前状态不能生成计划文件: {job.get('status') or 'unknown'}")
    repo_url = str(job.get("repo_url") or "").strip()
    if not repo_url:
        raise ValueError("单项目任务缺少 GitHub 仓库地址")
    pipeline_style = _pipeline_style_for_job(job)
    is_desktop = _job_type(job) == "desktop_review"

    _clear_plan_artifacts(job_id)
    if is_desktop:
        _clear_desktop_plan_artifacts(job_id)
    update_job(job_id, status="running", stage="preparing_plan", failed_stage="", error="")
    append_log(job_id, f"开始生成{_job_type_label(job)}计划文件: {repo_url}。")

    job_dir = JOBS_DIR / job_id
    try:
        import asyncio

        asyncio.run(run_pipeline(
            url=repo_url,
            output=str(job_dir / "final.mp4"),
            orientation="vertical" if not is_desktop else "horizontal",
            style=pipeline_style,
            dry_run=True,
        ))
        previews = _preview_existing_plan(job_dir)
        cover = _write_cover_frame(job_id, previews)
        console_segments = _console_segments_from_script(job_dir)
        write_json(job_dir / "narration.json", {"segments": console_segments})
        readiness = _write_pipeline_job_readiness_report(job_id, repo_url, len(previews), bool(cover.get("path")))
        append_log(job_id, f"{_job_type_label(job)}计划文件已生成，并输出 {len(previews)} 张静态预览帧。")
        update_job(
            job_id,
            status="awaiting_input",
            stage="awaiting_script_confirmation",
            plan_validation={"status": "not_run", "error": ""},
        )
        return {
            "job": read_job(job_id),
            "artifacts": job_artifacts(job_id),
            "plan_validation": {"status": "not_run", "error": ""},
            "cover_frame": cover,
            "readiness_report": readiness,
            "segments": console_segments,
            "render_command": _render_command_for_job(job, job_dir),
        }
    except Exception as exc:
        append_log(job_id, f"{_job_type_label(job)}计划文件生成失败: {exc}")
        _clear_plan_artifacts(job_id)
        update_job(job_id, status="failed", stage="preparing_plan", failed_stage="preparing_plan", error=str(exc))
        raise

def _prepare_from_plan_render(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    _require_stage(job, {"preparing_plan"}, "当前阶段不能生成计划文件")
    if str(job.get("status") or "") not in {"awaiting_render", "awaiting_validation", "ready_to_render", "failed"}:
        raise ValueError(f"当前状态不能生成计划文件: {job.get('status') or 'unknown'}")
    plan_path = Path(str(job.get("plan_path") or "")).expanduser()
    if not plan_path.exists():
        raise ValueError(f"计划文件目录不存在: {plan_path}")
    source_dir = plan_path if plan_path.is_dir() else plan_path.parent
    if not (source_dir / "shot_plan.json").exists() and not (source_dir / "desktop_review_plan.json").exists():
        raise ValueError("计划文件目录需要包含 shot_plan.json 或 desktop_review_plan.json")

    _clear_plan_artifacts(job_id)
    _clear_desktop_plan_artifacts(job_id)
    update_job(job_id, status="running", stage="preparing_plan", failed_stage="", error="")
    append_log(job_id, f"开始导入计划文件目录: {source_dir}。")

    job_dir = JOBS_DIR / job_id
    try:
        _copy_plan_snapshot(source_dir, job_dir)
        previews = _preview_existing_plan(job_dir)
        cover = _write_cover_frame(job_id, previews)
        console_segments = _console_segments_from_script(job_dir)
        write_json(job_dir / "narration.json", {"segments": console_segments})
        readiness = _write_pipeline_job_readiness_report(job_id, str(source_dir), len(previews), bool(cover.get("path")))
        append_log(job_id, f"计划文件已导入，并输出 {len(previews)} 张静态预览帧。")
        update_job(
            job_id,
            status="awaiting_input",
            stage="awaiting_script_confirmation",
            plan_validation={"status": "not_run", "error": ""},
        )
        return {
            "job": read_job(job_id),
            "artifacts": job_artifacts(job_id),
            "plan_validation": {"status": "not_run", "error": ""},
            "cover_frame": cover,
            "readiness_report": readiness,
            "segments": console_segments,
            "render_command": f".venv/bin/python -m src.cli --from-plan {job_dir} -o {job_dir / 'final.mp4'}",
        }
    except Exception as exc:
        append_log(job_id, f"计划文件导入失败: {exc}")
        _clear_plan_artifacts(job_id)
        _clear_desktop_plan_artifacts(job_id)
        update_job(job_id, status="failed", stage="preparing_plan", failed_stage="preparing_plan", error=str(exc))
        raise

async def _validate_single_project_plan(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    _require_stage(job, {"preparing_plan"}, "当前阶段不能校验计划文件")
    job_dir = JOBS_DIR / job_id
    if not _has_pipeline_plan(job_dir):
        import asyncio

        if _job_type(job) == "from_plan_render":
            await asyncio.to_thread(_prepare_from_plan_render, job_id, job)
        else:
            await asyncio.to_thread(_prepare_single_project_plan, job_id, job)
    append_log(job_id, f"开始校验{_job_type_label(job)} --from-plan dry run。")
    update_job(
        job_id,
        status="running",
        stage="preparing_plan",
        failed_stage="",
        error="",
        plan_validation={"status": "running", "error": ""},
    )
    try:
        await run_pipeline(
            url="",
            output=str(job_dir / "final.mp4"),
            orientation="vertical",
            from_plan=str(job_dir),
            style=_pipeline_style_for_job(job),
            dry_run=True,
        )
        details = _plan_validation_details(job_dir)
        append_log(job_id, f"{_job_type_label(job)}计划文件校验通过，可进入最终渲染。")
        validation = {"status": "passed", "error": "", "details": details}
        update_job(job_id, status="ready_to_render", stage="preparing_plan", plan_validation=validation)
        return {"job": read_job(job_id), "plan_validation": validation, "artifacts": job_artifacts(job_id)}
    except Exception as exc:
        append_log(job_id, f"{_job_type_label(job)}计划文件校验失败: {exc}")
        validation = {"status": "failed", "error": str(exc)}
        update_job(
            job_id,
            status="failed",
            stage="preparing_plan",
            failed_stage="preparing_plan",
            error=str(exc),
            plan_validation=validation,
        )
        raise

async def validate_plan(job_id: str) -> dict[str, Any]:
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    if _job_type(job) in {"single_project_vertical", "desktop_review", "from_plan_render"}:
        return await _validate_single_project_plan(job_id, job)
    _require_stage(job, {"preparing_plan"}, "当前阶段不能校验计划文件")

    job_dir = JOBS_DIR / job_id
    if not (job_dir / "shot_plan.json").exists():
        prepare_plan(job_id)
    _ensure_quality_gate(job_id)

    append_log(job_id, "开始校验 --from-plan dry run。")
    update_job(
        job_id,
        status="running",
        stage="preparing_plan",
        failed_stage="",
        error="",
        plan_validation={"status": "running", "error": ""},
    )
    try:
        await run_pipeline(
            url="",
            output=str(job_dir / "final.mp4"),
            orientation="vertical",
            from_plan=str(job_dir),
            style="hotlist",
            dry_run=True,
        )
        details = _plan_validation_details(job_dir)
        append_log(job_id, "计划文件校验通过，可进入最终渲染。")
        validation = {"status": "passed", "error": "", "details": details}
        update_job(job_id, status="ready_to_render", stage="preparing_plan", plan_validation=validation)
        return {"job": read_job(job_id), "plan_validation": validation, "artifacts": job_artifacts(job_id)}
    except Exception as exc:
        append_log(job_id, f"计划文件校验失败: {exc}")
        validation = {"status": "failed", "error": str(exc)}
        update_job(
            job_id,
            status="failed",
            stage="preparing_plan",
            failed_stage="preparing_plan",
            error=str(exc),
            plan_validation=validation,
        )
        raise

async def render_video(job_id: str) -> dict[str, Any]:
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    if _job_type(job) in {"single_project_vertical", "desktop_review", "from_plan_render"}:
        return await _render_single_project_video(job_id, job)
    _require_stage(
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

    job_dir = JOBS_DIR / job_id
    try:
        raise_if_cancelled(job_id)
        if not (job_dir / "shot_plan.json").exists():
            prepare_plan(job_id)
        job = read_job(job_id)
        _ensure_quality_gate(job_id)
        raise_if_cancelled(job_id)
        if (job.get("plan_validation") or {}).get("status") != "passed":
            await validate_plan(job_id)
            job = read_job(job_id)
        raise_if_cancelled(job_id)

        append_log(job_id, "开始生成最终视频。这个阶段会生成语音并合成 mp4。")
        update_job(job_id, status="running", failed_stage="", error="", cancel_requested=False)

        def on_pipeline_stage(stage: str, message: str) -> None:
            raise_if_cancelled(job_id)
            update_job(job_id, status="running", stage=stage)
            append_log(job_id, message)

        selected = read_json(job_dir / "selected_projects.json", {}).get("items") or []
        output_path = job_dir / "final.mp4"
        visual_style = _visual_style(job)
        if _render_engine(job) == "hyperframes":
            raise_if_cancelled(job_id)
            append_log(job_id, f"使用 HyperFrames 模板渲染：{visual_style}。")
            narration_segments = read_json(job_dir / "narration.json", {}).get("segments") or []
            await render_hotlist_v2_from_projects(
                selected,
                output_path=output_path,
                style=visual_style,
                narration_segments=narration_segments,
                stage_callback=on_pipeline_stage,
                issue_number=_issue_number(job),
            )
            raise_if_cancelled(job_id)
            update_job(job_id, status="running", stage="post_processing")
            append_log(job_id, "开始执行视频后处理。")
            post_process_video(output_path, no_bgm=_no_bgm(job), bgm_volume=_bgm_volume(job), bgm_path=_bgm_path(job))
        else:
            await run_pipeline(
                url="",
                output=str(output_path),
                orientation="vertical",
                from_plan=str(job_dir),
                style="hotlist",
                no_bgm=_no_bgm(job),
                bgm_volume=_bgm_volume(job),
                bgm_path=_bgm_path(job),
                stage_callback=on_pipeline_stage,
            )
        raise_if_cancelled(job_id)
        update_job(job_id, status="running", stage="post_processing")
        append_log(job_id, f"视频合成完成: {output_path}")
        return finalize_numbered_output(job_id, str(job.get("title") or "GitHub热榜视频"))
    except JobCancelled as exc:
        failed_stage = str(read_job(job_id).get("stage") or "composing_video")
        append_log(job_id, str(exc))
        _clear_current_video_output(job_id)
        if _video_versions(job_id):
            append_log(job_id, "已保留历史正式视频版本；仅清理本次未完成输出。")
        update_job(job_id, status="failed", stage=failed_stage, failed_stage=failed_stage, error=str(exc), cancel_requested=False)
        raise
    except Exception as exc:
        failed_stage = str(read_job(job_id).get("stage") or "composing_video")
        append_log(job_id, f"视频生成失败: {exc}")
        _clear_video_outputs(job_id)
        if _video_versions(job_id):
            append_log(job_id, "历史正式视频版本仍保留；仅清理本次失败输出。")
        update_job(job_id, status="failed", stage=failed_stage, failed_stage=failed_stage, error=str(exc), cancel_requested=False)
        raise

async def _render_single_project_video(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    _require_stage(
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
    job_dir = JOBS_DIR / job_id
    try:
        raise_if_cancelled(job_id)
        if not _has_pipeline_plan(job_dir):
            import asyncio

            if _job_type(job) == "from_plan_render":
                await asyncio.to_thread(_prepare_from_plan_render, job_id, job)
            else:
                await asyncio.to_thread(_prepare_single_project_plan, job_id, job)
            job = read_job(job_id)
        raise_if_cancelled(job_id)
        if (job.get("plan_validation") or {}).get("status") != "passed":
            await _validate_single_project_plan(job_id, job)
            job = read_job(job_id)
        raise_if_cancelled(job_id)

        append_log(job_id, f"开始生成{_job_type_label(job)}最终视频。这个阶段会采集素材、生成语音并合成 mp4。")
        update_job(job_id, status="running", failed_stage="", error="", cancel_requested=False)

        def on_pipeline_stage(stage: str, message: str) -> None:
            raise_if_cancelled(job_id)
            update_job(job_id, status="running", stage=stage)
            append_log(job_id, message)

        await run_pipeline(
            url="",
            output=str(job_dir / "final.mp4"),
            orientation="vertical",
            from_plan=str(job_dir),
            style=_pipeline_style_for_job(job),
            no_bgm=_no_bgm(job),
            bgm_volume=_bgm_volume(job),
            bgm_path=_bgm_path(job),
            stage_callback=on_pipeline_stage,
        )
        raise_if_cancelled(job_id)
        update_job(job_id, status="running", stage="post_processing")
        append_log(job_id, f"{_job_type_label(job)}视频合成完成: {job_dir / 'final.mp4'}")
        return finalize_numbered_output(job_id, str(job.get("title") or _job_type_label(job)))
    except JobCancelled as exc:
        failed_stage = str(read_job(job_id).get("stage") or "composing_video")
        append_log(job_id, str(exc))
        _clear_current_video_output(job_id)
        if _video_versions(job_id):
            append_log(job_id, "已保留历史正式视频版本；仅清理本次未完成输出。")
        update_job(job_id, status="failed", stage=failed_stage, failed_stage=failed_stage, error=str(exc), cancel_requested=False)
        raise
    except Exception as exc:
        failed_stage = str(read_job(job_id).get("stage") or "composing_video")
        append_log(job_id, f"{_job_type_label(job)}视频生成失败: {exc}")
        _clear_video_outputs(job_id)
        if _video_versions(job_id):
            append_log(job_id, "历史正式视频版本仍保留；仅清理本次失败输出。")
        update_job(job_id, status="failed", stage=failed_stage, failed_stage=failed_stage, error=str(exc), cancel_requested=False)
        raise

def finalize_numbered_output(job_id: str, title: str = "") -> dict[str, Any]:
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    stage = str(job.get("stage") or "")
    status = str(job.get("status") or "")
    if stage not in {"post_processing", "completed"} and status != "completed":
        raise ValueError(f"当前阶段不能生成带编号正式文件: {stage or 'unknown'}")
    job_dir = JOBS_DIR / job_id
    source = job_dir / "final.mp4"
    if not source.exists():
        raise ValueError("final.mp4 不存在，无法生成带编号正式文件")
    safe_title = _safe_filename(title or str(job.get("title") or "GitHub热榜视频"))
    base_name = _official_video_base_name(job, job_id, safe_title)
    target = _available_video_path(job_dir, base_name)
    shutil.copy2(source, target)
    append_log(job_id, f"正式视频文件已生成: {target.name}")
    publish_target = _copy_to_official_output_dir(job_id, job, source, base_name)
    if publish_target:
        append_log(job_id, f"正式视频文件已复制到指定目录: {publish_target}")
    update_job(job_id, status="completed", stage="completed", official_video=str(target))
    return {"job": read_job(job_id), "artifacts": job_artifacts(job_id)}

def _official_video_base_name(job: dict[str, Any], job_id: str, safe_title: str) -> str:
    return f"{_job_date_prefix(job_id)}-第{_official_issue_number(job, job_id):03d}期-{safe_title}"

def _job_date_prefix(job_id: str) -> str:
    parts = job_id.split("-")
    if len(parts) >= 3 and re.fullmatch(r"\d{8}", parts[2] or ""):
        return "-".join(parts[:3])
    return job_id

def _official_issue_number(job: dict[str, Any], job_id: str) -> int:
    issue = _issue_number(job)
    if issue is not None:
        return issue
    parts = job_id.split("-")
    if len(parts) >= 4:
        try:
            return int(parts[3])
        except ValueError:
            pass
    return 1

def _copy_to_official_output_dir(job_id: str, job: dict[str, Any], source: Path, base_name: str) -> Path | None:
    params = job.get("template_params") or {}
    output_dir_text = str(params.get("official_output_dir") or "").strip()
    if not output_dir_text:
        return None
    output_dir = Path(output_dir_text).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = _available_video_path(output_dir, base_name)
    shutil.copy2(source, target)
    return target

def _video_versions(job_id: str) -> list[dict[str, Any]]:
    job = read_job(job_id) or {}
    official_name = Path(str(job.get("official_video") or "")).name
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        return []
    versions = []
    for path in sorted({*job_dir.glob(f"{job_id}-*.mp4"), *job_dir.glob(f"{_job_date_prefix(job_id)}-*.mp4")}):
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
            "duration_seconds": _probe_video_duration(path),
            "is_official": bool(official_name and path.name == official_name),
        })
    return sorted(versions, key=lambda item: (item["updated_at"], _version_index(str(item["name"]))))

def _probe_video_duration(path: Path) -> float | None:
    try:
        result = subprocess.run(
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
    _clear_current_video_output(job_id)
    update_job(job_id, official_video="")

def _clear_current_video_output(job_id: str) -> None:
    final = JOBS_DIR / job_id / "final.mp4"
    if final.exists() and final.is_file():
        final.unlink()

def _version_index(name: str) -> int:
    match = re.search(r"-v(\d+)\.mp4$", name)
    return int(match.group(1)) if match else 1

def job_detail(job_id: str) -> dict[str, Any]:
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    job = {**job, "active": is_active(job_id)}
    model_calls = job.get("model_calls") or []
    return {
        "job": job,
        "candidates": read_json(JOBS_DIR / job_id / "candidates.json", {}).get("items", []),
        "selected": read_json(JOBS_DIR / job_id / "selected_projects.json", {}).get("items", []),
        "segments": read_json(JOBS_DIR / job_id / "narration.json", {}).get("segments", []),
        "hook": read_json(JOBS_DIR / job_id / "hook.json", {}),
        "publish_pack": read_json(JOBS_DIR / job_id / "publish_pack.json", {}),
        "cover_frame": read_json(JOBS_DIR / job_id / "cover_frame.json", {}),
        "logs": read_log(job_id),
        "log_tail": read_log_tail(job_id),
        "failed_stage": job.get("failed_stage") or (job.get("stage") if job.get("status") == "failed" else ""),
        "plan_validation": job.get("plan_validation") or {"status": "not_run", "error": ""},
        "quality_report": read_json(JOBS_DIR / job_id / "quality_report.json", {}),
        "video_versions": _video_versions(job_id),
        "readiness_report": read_json(JOBS_DIR / job_id / "readiness_report.json", {}),
        "stage_history": job.get("stage_history") or [],
        "artifacts": job_artifacts(job_id),
        "latest_model_call": model_calls[-1] if model_calls else {},
        "model_usage": summarize_model_usage(model_calls),
        "narration_source": job.get("narration_source") or {},
        "candidate_source": job.get("candidate_source") or {},
    }

def _analyze_candidates(job_id: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    route = route_snapshot("candidate_analysis")
    if not _route_available(route):
        append_log(job_id, f"候选分析使用启发式评分：{_route_skip_reason(route)}。")
        _update_candidate_source(job_id, {
            "analysis_status": "heuristic",
            "analysis_label": f"启发式评分（{_route_skip_reason(route)}）",
        })
        return candidates
    prompt = {
        "instruction": (
            "为中文 GitHub 热榜短视频分析候选项目。只根据输入字段判断，不要夸大。"
            "区分观众听得懂的项目价值和制作侧画面建议。"
            "每个项目的 description_zh、project_highlight、viewer_benefit 必须写出具体功能或使用场景，"
            "禁止使用同一句模板，禁止使用“围绕……重点是……”这类万能句。"
        ),
        "items": [
            {
                "index": index,
                "full_name": item.get("full_name"),
                "description": item.get("description"),
                "stars": item.get("stars"),
                "language": item.get("language"),
                "topics": item.get("topics"),
                "homepage": item.get("homepage"),
            }
            for index, item in enumerate(candidates[:30])
        ],
        "schema": {
            "items": [
                {
                    "index": 1,
                    "description_zh": "一句中文用途解释",
                    "recommendation": "为什么值得入榜",
                    "project_highlight": "项目最值得讲的真实能力，不写画面素材建议",
                    "viewer_benefit": "观众为什么可能需要它",
                    "risk": "风险提示",
                    "audience": "适合谁",
                    "visual_potential": "仅给视频制作使用的画面潜力，不能作为口播亮点",
                    "score": 80,
                }
            ]
        },
    }
    try:
        detail = chat_json_detail(
            "candidate_analysis",
            "你是克制的中文短视频选题编辑，只输出 JSON。",
            json.dumps(prompt, ensure_ascii=False),
            max_tokens=5000,
        )
        data = detail["data"]
        used_route = detail["route"]
        items = data.get("items", []) if data else []
        by_index = {int(item.get("index") or 0): item for item in items}
        if not by_index:
            _write_ai_raw_response(job_id, "candidate_analysis", detail)
            _record_model_call(job_id, "candidate_analysis", detail, "invalid_json")
            append_log(job_id, f"候选分析模型未返回可用 JSON，保留启发式结果。")
            _update_candidate_source(job_id, {
                "analysis_status": "ai_failed_fallback",
                "analysis_label": f"AI 响应异常后回退启发式（{_short_text(detail.get('error') or '模型未返回可用 JSON', 80)}）",
            })
            return candidates
        for index, candidate in enumerate(candidates, start=1):
            patch = by_index.get(index)
            if patch:
                _merge_candidate_analysis(candidate, patch)
        _record_model_call(job_id, "candidate_analysis", detail, "success")
        append_log(job_id, f"候选分析已使用 {used_route['provider_name']} / {used_route['model']}。")
        _update_candidate_source(job_id, {
            "analysis_status": "ai_success",
            "analysis_label": f"AI 分析：{used_route['provider_name']} / {used_route['model']}",
        })
    except Exception as exc:
        _record_model_call(job_id, "candidate_analysis", {"route": route, "error": str(exc)}, "failed")
        append_log(job_id, f"候选分析模型失败，保留启发式结果: {exc}")
        _update_candidate_source(job_id, {
            "analysis_status": "ai_failed_fallback",
            "analysis_label": f"AI 失败后回退启发式（{_short_text(str(exc), 80)}）",
        })
    return candidates

def _rank_candidates(job_id: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    route = route_snapshot("hotlist_ranking")
    if not _route_available(route):
        append_log(job_id, f"热榜排序使用默认顺序：{_route_skip_reason(route)}。")
        _update_candidate_source(job_id, {
            "ranking_status": "default",
            "ranking_label": f"默认顺序（{_route_skip_reason(route)}）",
        })
        return candidates
    prompt = {
        "instruction": "为中文 GitHub 热榜短视频给候选项目排序。优先考虑观众价值、可解释性、画面潜力和事实稳妥性。",
        "items": [
            {
                "index": index,
                "full_name": item.get("full_name"),
                "description_zh": item.get("description_zh"),
                "recommendation": item.get("recommendation"),
                "risk": item.get("risk"),
                "visual_potential": item.get("visual_potential"),
                "stars": item.get("stars"),
                "score": item.get("score"),
            }
            for index, item in enumerate(candidates[:30])
        ],
        "schema": {
            "items": [
                {"index": 1, "rank": 1, "reason": "为什么排在这个位置"}
            ]
        },
    }
    try:
        detail = chat_json_detail(
            "hotlist_ranking",
            "你是克制的中文选题排序编辑，只输出 JSON。",
            json.dumps(prompt, ensure_ascii=False),
            max_tokens=2600,
        )
        data = detail["data"]
        ranked = _apply_candidate_ranking(candidates, data.get("items", []) if data else [])
        if not ranked:
            _write_ai_raw_response(job_id, "hotlist_ranking", detail)
            _record_model_call(job_id, "hotlist_ranking", detail, "invalid_json")
            append_log(job_id, "热榜排序模型未返回可用 JSON，保留默认顺序。")
            _update_candidate_source(job_id, {
                "ranking_status": "ai_failed_default",
                "ranking_label": f"AI 排序异常后保留默认顺序（{_short_text(detail.get('error') or '模型未返回可用 JSON', 80)}）",
            })
            return candidates
        _record_model_call(job_id, "hotlist_ranking", detail, "success")
        used_route = detail["route"]
        append_log(job_id, f"热榜排序已使用 {used_route['provider_name']} / {used_route['model']}。")
        _update_candidate_source(job_id, {
            "ranking_status": "ai_success",
            "ranking_label": f"AI 排序：{used_route['provider_name']} / {used_route['model']}",
        })
        return ranked
    except Exception as exc:
        _record_model_call(job_id, "hotlist_ranking", {"route": route, "error": str(exc)}, "failed")
        append_log(job_id, f"热榜排序模型失败，保留默认顺序: {exc}")
        _update_candidate_source(job_id, {
            "ranking_status": "ai_failed_default",
            "ranking_label": f"AI 排序失败后保留默认顺序（{_short_text(str(exc), 80)}）",
        })
        return candidates

def _apply_candidate_ranking(candidates: list[dict[str, Any]], items: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    ranks: dict[int, tuple[int, str]] = {}
    for item in items:
        try:
            index = int(item.get("index"))
            rank = int(item.get("rank"))
        except Exception:
            continue
        if index < 1 or index > len(candidates) or rank < 1:
            continue
        ranks[index - 1] = (rank, _short_text(str(item.get("reason") or ""), 140))
    if not ranks:
        return None
    ranked = []
    for index, candidate in enumerate(candidates):
        patched = dict(candidate)
        if index in ranks:
            patched["ai_rank"] = ranks[index][0]
            patched["ranking_reason"] = ranks[index][1]
        ranked.append(patched)
    return sorted(ranked, key=lambda item: (int(item.get("ai_rank") or 9999), -int(item.get("score") or 0)))

def _no_bgm(job: dict[str, Any]) -> bool:
    params = job.get("template_params") or {}
    return params.get("bgm") == "none"

def _bgm_path(job: dict[str, Any]) -> str | None:
    params = job.get("template_params") or {}
    if params.get("bgm") != "custom":
        return None
    path = Path(str(params.get("bgm_path") or "")).expanduser()
    if not path.exists() or not path.is_file():
        raise ValueError(f"自定义 BGM 文件不存在: {path}")
    if path.suffix.lower() not in {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac"}:
        raise ValueError(f"不支持的 BGM 文件格式: {path.suffix}")
    return str(path)

def _bgm_volume(job: dict[str, Any]) -> float:
    params = job.get("template_params") or {}
    try:
        volume = float(params.get("bgm_volume", BGM_VOLUME))
    except (TypeError, ValueError):
        return BGM_VOLUME
    return min(1.0, max(0.0, volume))

def _visual_style(job: dict[str, Any]) -> str:
    params = job.get("template_params") or {}
    return normalize_style(str(params.get("style") or params.get("visual_style") or "tech_hotspot"))

def _render_engine(job: dict[str, Any]) -> str:
    params = job.get("template_params") or {}
    engine = str(params.get("render_engine") or "").strip()
    if engine in {"hyperframes", "pil"}:
        return engine
    return render_engine_for_style(_visual_style(job))

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
    job_type = _job_type(job)
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
    }.get(_job_type(job), "任务")

def _render_command_for_job(job: dict[str, Any], job_dir: Path) -> str:
    job_type = _job_type(job)
    repo_url = str(job.get("repo_url") or "")
    if job_type == "desktop_review":
        return f".venv/bin/python -m src.cli {repo_url} -o {job_dir / 'final.mp4'} --style desktop-review"
    if job_type == "from_plan_render":
        return f".venv/bin/python -m src.cli --from-plan {job_dir} -o {job_dir / 'final.mp4'}"
    return f".venv/bin/python -m src.cli {repo_url} -o {job_dir / 'final.mp4'} --vertical --style single-review"

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
    if not copied or not _has_pipeline_plan(target_dir):
        raise ValueError("计划文件目录需要包含可用计划文件")

def _preview_existing_plan(job_dir: Path) -> list[Path]:
    if (job_dir / "desktop_review_plan.json").exists():
        return _desktop_preview_placeholders(job_dir)
    manifest = _asset_manifest_from_dict(read_json(job_dir / "asset_manifest.json", {}))
    shot_plan = shot_plan_from_dict(read_json(job_dir / "shot_plan.json", {}))
    script = _video_script_from_dict(read_json(job_dir / "script.json", {}))
    return render_vertical_previews(script, shot_plan, manifest, job_dir / "preview_frames")

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

def _merge_candidate_analysis(candidate: dict[str, Any], patch: dict[str, Any]) -> None:
    for key in ("description_zh", "recommendation", "project_highlight", "viewer_benefit", "risk", "audience", "visual_potential"):
        if patch.get(key):
            candidate[key] = _short_text(str(patch[key]), 120)
    try:
        score = int(patch.get("score"))
        candidate["score"] = max(0, min(100, score))
    except Exception:
        pass

def _narration_project_context(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for index, project in enumerate(projects, start=1):
        feature = project.get("feature_extract") or {}
        benefit = str(feature.get("quantified_benefit") or "").strip()
        items.append({
            "rank": index,
            "name": project.get("name"),
            "full_name": project.get("full_name"),
            "description_zh": project.get("description_zh"),
            "feature_extract": feature,
            "core_problem": feature.get("core_problem") or _viewer_pain(project),
            "core_action": feature.get("core_action") or _viewer_highlight(project),
            "quantified_benefit": benefit,
            "quantified_benefit_or_tech_point": benefit or _viewer_highlight(project),
            "recommendation": project.get("recommendation"),
            "project_highlight": project.get("project_highlight"),
            "viewer_benefit": project.get("viewer_benefit"),
            "audience": project.get("audience"),
            "visual_potential": project.get("visual_potential"),
            "stars": project.get("stars"),
            "viewer_pain": _viewer_pain(project),
            "viewer_outcome": _viewer_outcome(project),
            "safe_highlight": _viewer_highlight(project),
            "safe_audience": _viewer_audience(project),
            "risk": project.get("risk"),
            "daily_growth": project.get("daily_growth"),
            "growth_note": project.get("growth_note") or ESTIMATED_GROWTH_NOTE,
        })
    return items

def _ensure_feature_extracts(job_id: str, projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated = []
    missing = []
    for index, project in enumerate(projects, start=1):
        patched = dict(project)
        feature = _sanitize_feature_extract(project.get("feature_extract"))
        if not feature:
            missing.append((index, patched))
            feature = _fallback_feature_extract(patched)
        patched["feature_extract"] = feature
        _apply_feature_to_project_copy(patched, feature)
        updated.append(patched)
    if missing:
        _extract_features_with_model(job_id, updated, [index for index, _project in missing])
    return updated

def _extract_features_with_model(job_id: str, projects: list[dict[str, Any]], indexes: list[int]) -> None:
    route = route_snapshot("feature_extraction")
    if not _route_available(route):
        append_log(job_id, f"项目功能摘要使用启发式提取：{_route_skip_reason(route)}。")
        return
    prompt = {
        "instruction": (
            "为 GitHub 热榜入选项目提取事实型功能摘要。只能根据 description、topics、README 摘要判断，"
            "不要写营销话术，不要把视频画面建议当功能。"
        ),
        "items": [
            {
                "index": index,
                "name": project.get("name"),
                "full_name": project.get("full_name"),
                "description": project.get("description"),
                "description_zh": project.get("description_zh"),
                "topics": project.get("topics"),
                "readme_excerpt": _readme_excerpt(project),
            }
            for index, project in enumerate(projects, start=1)
            if index in indexes
        ],
        "schema": {
            "items": [
                {
                    "index": 1,
                    "core_problem": "15字内具体痛点",
                    "core_action": "用户用它做什么，一句话动作",
                    "quantified_benefit": "可量化效果；没有就空字符串",
                }
            ]
        },
    }
    try:
        detail = chat_json_detail(
            "feature_extraction",
            "你是克制的开源项目功能摘要编辑，只输出 JSON。",
            json.dumps(prompt, ensure_ascii=False),
            max_tokens=1800,
        )
        items = (detail.get("data") or {}).get("items", []) if isinstance(detail.get("data"), dict) else []
        by_index = {int(item.get("index") or 0): _sanitize_feature_extract(item) for item in items if isinstance(item, dict)}
        changed = 0
        for index, project in enumerate(projects, start=1):
            feature = by_index.get(index)
            if feature:
                project["feature_extract"] = feature
                _apply_feature_to_project_copy(project, feature)
                changed += 1
        if changed:
            _record_model_call(job_id, "feature_extraction", detail, "success")
            used_route = detail.get("route") or {}
            append_log(job_id, f"已为 {changed} 个项目提取功能摘要：{used_route.get('provider_name') or used_route.get('provider') or ''} / {used_route.get('model') or ''}。")
        else:
            _write_ai_raw_response(job_id, "feature_extraction", detail)
            _record_model_call(job_id, "feature_extraction", detail, "invalid_json")
            append_log(job_id, "功能摘要模型未返回可用 JSON，保留启发式摘要。")
    except Exception as exc:
        _record_model_call(job_id, "feature_extraction", {"route": route, "error": str(exc)}, "failed")
        append_log(job_id, f"功能摘要模型失败，保留启发式摘要: {exc}")

def _ranking_overview_line(projects: list[dict[str, Any]]) -> str:
    if not projects:
        return "先看榜单：这期按真实使用价值来拆。"
    count = len(projects)
    audiences = []
    for project in projects:
        audience = _viewer_audience(project)
        if audience and audience not in audiences:
            audiences.append(audience)
        if len(audiences) == 2:
            break
    audience_text = "、".join(audiences) if audiences else "开发者"
    return f"先看整体趋势：这 {count} 个项目分别在帮{audience_text}缩短上手路径。"

def _generate_hook(job_id: str, projects: list[dict[str, Any]]) -> dict[str, Any]:
    route = route_snapshot("hook_generation")
    hook_path = JOBS_DIR / job_id / "hook.json"
    if not _route_available(route):
        reason = _route_skip_reason(route)
        hook = _default_hook(projects, route, "skipped", reason)
        write_json(hook_path, hook)
        append_log(job_id, f"标题钩子生成跳过：{reason}。")
        return hook
    prompt = {
        "instruction": "为 GitHub 热榜竖屏短视频生成克制标题和开场钩子。不要夸大，不要承诺收益，只基于输入项目。",
        "projects": [
            {
                "rank": index,
                "name": project.get("name"),
                "full_name": project.get("full_name"),
                "description_zh": project.get("description_zh"),
                "feature_extract": project.get("feature_extract") or {},
                "recommendation": project.get("recommendation"),
                "audience": project.get("audience"),
                "stars": project.get("stars"),
            }
            for index, project in enumerate(projects, start=1)
        ],
        "schema": {
            "title": "适合文件名和视频标题的中文标题，12 到 28 字",
            "opening_hook": "开头 1 句话，20 到 45 字",
            "closing_cta": "结尾互动提示，15 到 40 字",
        },
    }
    try:
        detail = chat_json_detail(
            "hook_generation",
            "你是克制的中文短视频标题编辑，只输出 JSON。",
            json.dumps(prompt, ensure_ascii=False),
            max_tokens=1000,
        )
        hook = _sanitize_hook(detail["data"], detail.get("route") or {}, "", "success")
        if not hook:
            _write_ai_raw_response(job_id, "hook_generation", detail)
            _record_model_call(job_id, "hook_generation", detail, "invalid_json")
            hook = _default_hook(projects, detail.get("route") or {}, "invalid_json", detail.get("error") or "模型未返回可用 JSON")
            write_json(hook_path, hook)
            append_log(job_id, "标题钩子模型未返回可用 JSON，保留默认标题。")
            return hook
        write_json(hook_path, hook)
        update_job(job_id, title=hook["title"])
        _record_model_call(job_id, "hook_generation", detail, "success")
        append_log(job_id, f"标题钩子已使用 {hook['provider']} / {hook['model']}。")
        return hook
    except Exception as exc:
        _record_model_call(job_id, "hook_generation", {"route": route, "error": str(exc)}, "failed")
        hook = _default_hook(projects, route, "failed", str(exc))
        write_json(hook_path, hook)
        append_log(job_id, f"标题钩子生成失败，保留默认标题: {exc}")
        return hook

def _sanitize_hook(
    data: dict[str, Any] | None,
    route: dict[str, Any],
    error: str,
    status: str,
) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    title = _short_text(str(data.get("title") or ""), 36)
    opening_hook = _short_text(str(data.get("opening_hook") or ""), 90)
    closing_cta = _short_text(str(data.get("closing_cta") or ""), 80)
    if not title or not opening_hook:
        return None
    return {
        "status": status,
        "title": title,
        "opening_hook": opening_hook,
        "closing_cta": closing_cta,
        "provider": route.get("provider_name") or route.get("provider") or "",
        "model": route.get("model") or "",
        "error": error,
    }

def _default_hook(
    projects: list[dict[str, Any]],
    route: dict[str, Any],
    status: str,
    error: str,
) -> dict[str, Any]:
    title = f"GitHub热榜{len(projects)}个项目" if projects else "GitHub热榜视频"
    names = "、".join(str(project.get("name") or project.get("full_name") or "这个项目") for project in projects[:3])
    return {
        "status": status,
        "title": title,
        "opening_hook": f"这期看 {names or 'GitHub 热榜'}，只挑真正值得停下来的项目。",
        "closing_cta": "想看哪个项目实操拆解，评论区直接留名字。",
        "provider": route.get("provider_name") or route.get("provider") or "",
        "model": route.get("model") or "",
        "error": error,
    }

def _write_publish_pack(
    job_id: str,
    projects: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    hook = read_json(JOBS_DIR / job_id / "hook.json", {})
    title = _short_text(str(hook.get("title") or read_job(job_id).get("title") or "GitHub 热榜视频"), 40)
    opening = _short_text(str(hook.get("opening_hook") or (segments[0].get("text") if segments else "")), 90)
    closing = _short_text(str(hook.get("closing_cta") or _outro_line(projects)), 80)
    project_names = [str(project.get("full_name") or project.get("name") or "") for project in projects if project.get("full_name") or project.get("name")]
    description_lines = [
        opening or title,
        "",
        "本期项目：",
        *[f"{index}. {name}" for index, name in enumerate(project_names, start=1)],
        "",
        "数据说明：",
        ESTIMATED_GROWTH_NOTE,
        "",
        closing,
    ]
    pack = {
        "title": title,
        "description": _clip_multiline("\n".join(description_lines), 900),
        "hashtags": _hashtags(projects),
        "cover_text": _cover_text(title, projects),
        "source_projects": project_names,
        "data_note": ESTIMATED_GROWTH_NOTE,
    }
    write_json(JOBS_DIR / job_id / "publish_pack.json", pack)
    append_log(job_id, "发布辅助包已生成。")
    return pack

def _pipeline_job_projects(job_id: str, job: dict[str, Any]) -> list[dict[str, Any]]:
    info = read_json(JOBS_DIR / job_id / "info.json", {})
    if isinstance(info.get("projects"), list):
        raw = info["projects"]
    else:
        raw = [info]
    projects = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        full_name = str(item.get("full_name") or "").strip()
        if not full_name and item.get("owner") and item.get("name"):
            full_name = f"{item.get('owner')}/{item.get('name')}"
        repo_url = str(item.get("repo_url") or job.get("repo_url") or job.get("plan_path") or "").strip()
        name = str(item.get("name") or full_name or f"project-{index}")
        projects.append({
            **item,
            "name": name,
            "full_name": full_name or name,
            "repo_url": repo_url,
            "description": str(item.get("description") or ""),
            "description_zh": str(item.get("description_zh") or item.get("description") or ""),
            "stars": item.get("stars") or 0,
            "language": item.get("language") or "",
            "daily_growth": item.get("daily_growth") or "",
            "growth_note": item.get("growth_note") or "",
        })
    if projects:
        return projects
    source = str(job.get("repo_url") or job.get("plan_path") or job_id)
    return [{
        "name": Path(source).name or job_id,
        "full_name": Path(source).name or job_id,
        "repo_url": source,
        "description": str(job.get("title") or ""),
        "description_zh": str(job.get("title") or ""),
        "stars": 0,
        "language": "",
    }]

def _write_pipeline_publish_pack(
    job_id: str,
    job: dict[str, Any],
    projects: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    title = _short_text(str(read_job(job_id).get("title") or _job_type_label(job)), 40)
    source_names = [str(project.get("full_name") or project.get("name") or "") for project in projects if project]
    narration = "\n".join(str(segment.get("text") or "") for segment in segments if segment.get("text"))
    description = _clip_multiline("\n".join([
        title,
        "",
        _short_text(narration, 520),
        "",
        "来源：",
        *[f"- {name}" for name in source_names],
    ]), 900)
    pack = {
        "title": title,
        "description": description,
        "hashtags": _hashtags(projects),
        "cover_text": {"headline": title, "subhead": _short_text(source_names[0] if source_names else title, 48)},
        "source_projects": source_names,
        "data_note": "单项目或计划文件任务使用本地计划快照与仓库元数据，不使用热榜增长估算。",
    }
    write_json(JOBS_DIR / job_id / "publish_pack.json", pack)
    append_log(job_id, "发布辅助包已生成。")
    return pack

def _hashtags(projects: list[dict[str, Any]]) -> list[str]:
    tags = ["GitHub", "开源项目", "开发者工具"]
    text = _project_text({"topics": [], "description": " ".join(_project_text(project) for project in projects)})
    if _has_keyword(text, ("ai", "agent", "llm", "rag", "model")):
        tags.append("AI工具")
    if _has_keyword(text, ("cli", "terminal", "shell", "developer")):
        tags.append("效率工具")
    if _has_keyword(text, ("react", "vue", "frontend", "ui", "css")):
        tags.append("前端开发")
    if _has_keyword(text, ("data", "database", "analytics", "sql")):
        tags.append("数据工具")
    seen = set()
    return [tag for tag in tags if not (tag in seen or seen.add(tag))]

def _cover_text(title: str, projects: list[dict[str, Any]]) -> dict[str, str]:
    top_project = _fastest_growth_project(projects)
    top = str((top_project or {}).get("name") or (top_project or {}).get("full_name") or "开源项目") if projects else "开源项目"
    growth = str((top_project or {}).get("daily_growth") or "")
    feature = (top_project or {}).get("feature_extract") or {}
    hook = str(feature.get("core_problem") or (top_project or {}).get("description_zh") or "").strip("。")
    subhead = f"本周黑马：{top}"
    if growth:
        subhead += f" · {growth}"
    if hook:
        subhead += f" · {hook}"
    return {
        "headline": title,
        "subhead": _short_text(subhead, 48),
    }

def _fastest_growth_project(projects: list[dict[str, Any]]) -> dict[str, Any]:
    if not projects:
        return {}
    return max(projects, key=lambda item: _growth_value(str(item.get("daily_growth") or item.get("stars_delta") or "")))

def _growth_value(text: str) -> int:
    match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*([kK千万]?)", text.replace(",", ""))
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit in {"k", "千"}:
        value *= 1000
    elif unit == "万":
        value *= 10000
    return max(0, int(value))

def _write_cover_frame(job_id: str, previews: list[Any]) -> dict[str, Any]:
    job_dir = JOBS_DIR / job_id
    source = Path(previews[0]) if previews else Path()
    if not source.exists() or not source.is_file():
        cover = {"status": "missing", "path": "", "source": "", "note": "没有可用预览帧。"}
        write_json(job_dir / "cover_frame.json", cover)
        append_log(job_id, "封面帧生成跳过：没有可用预览帧。")
        return cover
    target = job_dir / "cover_frame.png"
    shutil.copy2(source, target)
    cover = {
        "status": "ready",
        "path": str(target),
        "source": str(source),
        "note": "第一版封面帧复用首张静态预览。",
    }
    write_json(job_dir / "cover_frame.json", cover)
    append_log(job_id, "封面帧已生成。")
    return cover

def _write_readiness_report(
    job_id: str,
    projects: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    preview_count: int,
    has_cover: bool,
) -> dict[str, Any]:
    quality = read_json(JOBS_DIR / job_id / "quality_report.json", {})
    publish_pack = read_json(JOBS_DIR / job_id / "publish_pack.json", {})
    checks = [
        _readiness_check("projects", bool(projects), "已确认项目", "缺少已确认项目"),
        _readiness_check("script", bool(segments), "已确认口播脚本", "缺少口播脚本"),
        _readiness_check("preview_frames", preview_count >= max(1, len(projects) + 3), f"已生成 {preview_count} 张预览帧", "预览帧数量不足"),
        _readiness_check("cover_frame", has_cover, "已生成封面帧", "缺少封面帧"),
        _readiness_check("publish_pack", bool(publish_pack.get("title") and publish_pack.get("description")), "已生成发布辅助包", "缺少发布辅助包"),
        _readiness_check("data_semantics", bool(publish_pack.get("data_note")), publish_pack.get("data_note") or ESTIMATED_GROWTH_NOTE, "缺少热度口径说明"),
    ]
    if quality:
        fact_passed = _quality_verified(quality)
        checks.append(_readiness_check(
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
    write_json(JOBS_DIR / job_id / "readiness_report.json", report)
    append_log(job_id, f"发布准备度评分: {score} / 100，状态 {status}。")
    return report

def _write_pipeline_job_readiness_report(
    job_id: str,
    source_label: str,
    preview_count: int,
    has_cover: bool,
) -> dict[str, Any]:
    job_dir = JOBS_DIR / job_id
    script = read_json(job_dir / "script.json", {})
    segments = script.get("segments", []) if isinstance(script.get("segments"), list) else []
    has_desktop_plan = (job_dir / "desktop_review_plan.json").exists()
    checks = [
        _readiness_check("source", bool(source_label), f"已设置来源: {source_label}", "缺少任务来源"),
        _readiness_check("plan", _has_pipeline_plan(job_dir), "已生成分镜计划", "缺少分镜计划"),
        _readiness_check("script", bool(segments), "已生成口播脚本", "缺少口播脚本"),
        _readiness_check("preview_frames", preview_count > 0, f"已生成 {preview_count} 张预览帧", "缺少预览帧"),
        _readiness_check("cover_frame", has_cover, "已生成封面帧", "缺少封面帧"),
    ]
    if not has_desktop_plan:
        checks.insert(2, _readiness_check("asset_manifest", (job_dir / "asset_manifest.json").exists(), "已生成素材清单", "缺少素材清单"))
    score = int(sum(item["score"] for item in checks) / max(1, len(checks)))
    status = "ready" if all(item["passed"] for item in checks) else "review"
    report = {
        "status": status,
        "score": score,
        "checks": checks,
        "summary": "计划可进入最终渲染。" if status == "ready" else "进入最终渲染前建议复核未通过项。",
    }
    write_json(job_dir / "readiness_report.json", report)
    append_log(job_id, f"发布准备度评分: {score} / 100，状态 {status}。")
    return report

def _write_single_project_readiness_report(
    job_id: str,
    repo_url: str,
    preview_count: int,
    has_cover: bool,
) -> dict[str, Any]:
    return _write_pipeline_job_readiness_report(job_id, repo_url, preview_count, has_cover)

def _readiness_check(check_id: str, passed: bool, ok: str, fail: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": passed,
        "score": 100 if passed else 0,
        "message": ok if passed else fail,
    }

def _plan_validation_details(job_dir: Path) -> dict[str, Any]:
    manifest = read_json(job_dir / "asset_manifest.json", {})
    shot_plan = read_json(job_dir / "shot_plan.json", {})
    script = read_json(job_dir / "script.json", {})
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

def _model_narrations(job_id: str, projects: list[dict[str, Any]]) -> list[dict[str, str]] | None:
    route = route_snapshot("narration_generation")
    if not _route_available(route):
        reason = _route_skip_reason(route)
        _update_narration_source(job_id, route, "model_skipped", reason)
        append_log(job_id, f"口播生成使用默认模板：{reason}。")
        return None
    project_context = _narration_project_context(projects)
    prompt = {
        "instruction": (
            "你是一个为「GitHub 热榜视频」撰写口播文案的专家。为 GitHub 热榜竖屏短视频生成中文口播。"
            "单个项目口播要吸引人、有场景感、避免套路；克制、具体、面向观众价值，不要喊口号。"
            "开场必须在 3 秒内抓住人，用一个本期判断或反常识观点切入，不要直接复述第一名项目名。"
            "榜单总览只讲整体趋势和选择标准，不展开第 1 名细节；每个项目详情再按痛点、项目怎么解决、适合谁、为什么值得看展开。"
            "结尾要留下讨论空间或下一期期待，不要只说点赞关注。"
            "每个 project-* 段落控制在 60 到 100 个中文字符左右。"
            "每个 project-* 必须使用对应项目 feature_extract 里的 core_problem 和 core_action；"
            "quantified_benefit 非空时必须自然写入，空时不要编造数字。"
            "禁止使用以下开头句式：如果你纠结、如果你觉得、如果你在找、如果你卡在、先看看它、先看它。"
            "禁止空洞评价：很有价值、值得关注、适合开发者、适合开源项目关注者。"
            "每个 project-* 必须包含：一个反常识或场景化开头；一句具体痛点或爽点；一句锁定目标人群，格式可以用「适合：被 X 折磨的人」。"
            "visual_potential 是制作侧画面建议，禁止直接写入口播；不要把 README 可展示、仓库页做信息卡片、"
            "终端截图可展示、截图可展示、画面潜力、信息卡片当成项目亮点。"
            "daily_growth / growth_note 只表示按当前总 stars 和项目年龄折算的估算日均 star，不是真实新增 star。"
            "如果要提热度，只能说“估算日均 star”或“热度估算”，禁止说“今天涨了”“新增了”“真实增长”。"
        ),
        "projects": project_context,
        "content_strategy": {
            "opening": "一句 20 到 45 字的钩子，讲本期判断，不复述第 1 名详情",
            "overview": "榜单总览负责建立选择标准和整体趋势，不能重复 project-1 的项目介绍",
            "per_project": "每个项目按反常识/场景开头 -> 具体痛点或爽点 -> 被什么问题折磨的人组织",
            "closing": "留下讨论钩子，让观众选择想看哪个项目的实操拆解",
        },
        "project_copy_template": (
            "{{core_problem}} 不是靠收藏项目解决的。{{name}} 的核心动作是：{{core_action}}。"
            "{{quantified_benefit_or_tech_point}}。适合：被 {{core_problem}} 折磨的 {{safe_audience}}。"
        ),
        "schema": {
            "segments": [
                {"id": "intro", "label": "开场", "text": "20 到 45 字"},
                {"id": "project-1", "label": "第 1 名", "text": "60 到 100 字，纯文本，不要序号、标题、Markdown"},
                {"id": "outro", "label": "结尾", "text": "20 到 45 字"},
            ]
        },
    }
    try:
        detail = chat_json_detail(
            "narration_generation",
            "你是中文短视频口播编辑，只输出 JSON。",
            json.dumps(prompt, ensure_ascii=False),
            max_tokens=2600,
        )
        data = detail["data"]
        used_route = detail["route"]
        segments = _sanitize_model_segments(projects, data.get("segments", []) if data else [])
        if not segments:
            _write_ai_raw_response(job_id, "narration_generation", detail)
            _record_model_call(job_id, "narration_generation", detail, "invalid_json")
            _update_narration_source(
                job_id,
                detail.get("route") or route,
                "ai_failed_fallback",
                detail.get("error") or "模型未返回可用 JSON",
            )
            append_log(job_id, "口播模型未返回可用 JSON，改用默认模板。")
            return None
        _record_model_call(job_id, "narration_generation", detail, "success")
        _update_narration_source(job_id, used_route, "ai_success", "")
        append_log(job_id, f"口播生成已使用 {used_route['provider_name']} / {used_route['model']}。")
        return segments
    except Exception as exc:
        _record_model_call(job_id, "narration_generation", {"route": route, "error": str(exc)}, "failed")
        _update_narration_source(job_id, route, "ai_failed_fallback", str(exc))
        append_log(job_id, f"口播模型失败，改用默认模板: {exc}")
        return None

def _polish_narrations(
    job_id: str,
    projects: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> list[dict[str, str]]:
    route = route_snapshot("script_polishing")
    if not _route_available(route):
        reason = _route_skip_reason(route)
        _patch_narration_source(job_id, {"polishing_status": "skipped", "polishing_reason": reason})
        append_log(job_id, f"脚本润色跳过：{reason}。")
        return segments
    prompt = {
        "instruction": (
            "润色 GitHub 热榜中文口播，保持 segment id 不变。只改表达，不新增输入里没有的事实。"
            "每个 project-* 段落要有反差或场景感、具体痛点/爽点、明确目标人群。"
            "禁止使用：如果你纠结、如果你觉得、如果你在找、如果你卡在、先看看它、先看它、很有价值、值得关注、适合开发者、适合开源项目关注者。"
            "保留项目真实能力和观众收益，删除制作侧画面话术；禁止出现 README 可展示、仓库页做信息卡片、"
            "终端截图可展示、截图可展示、画面潜力、信息卡片作为亮点。"
            "daily_growth 仅表示估算日均 star，不是真实新增 star；禁止润色成“新增了”“暴涨了”“今天涨了”等事实口吻。"
        ),
        "projects": [
            {
                "rank": index,
                "name": project.get("name"),
                "full_name": project.get("full_name"),
                "description_zh": project.get("description_zh"),
                "recommendation": project.get("recommendation"),
                "project_highlight": project.get("project_highlight"),
                "viewer_benefit": project.get("viewer_benefit"),
                "audience": project.get("audience"),
                "risk": project.get("risk"),
                "visual_potential": project.get("visual_potential"),
                "stars": project.get("stars"),
            }
            for index, project in enumerate(projects, start=1)
        ],
        "segments": [
            {
                "id": segment.get("id"),
                "label": segment.get("label"),
                "text": segment.get("text"),
            }
            for segment in segments
        ],
        "schema": {
            "segments": [
                {"id": "intro", "label": "开场", "text": "保留信息、节奏更顺的中文口播"}
            ]
        },
    }
    try:
        detail = chat_json_detail(
            "script_polishing",
            "你是克制的中文短视频脚本润色编辑，只输出 JSON。",
            json.dumps(prompt, ensure_ascii=False),
            max_tokens=2600,
        )
        data = detail["data"]
        polished = _sanitize_polished_segments(segments, data.get("segments", []) if data else [])
        if not polished:
            _write_ai_raw_response(job_id, "script_polishing", detail)
            _record_model_call(job_id, "script_polishing", detail, "invalid_json")
            _patch_narration_source(job_id, {
                "polishing_status": "invalid_json",
                "polishing_reason": detail.get("error") or "模型未返回可用 JSON",
            })
            append_log(job_id, "脚本润色模型未返回可用 JSON，保留原稿。")
            return segments
        _record_model_call(job_id, "script_polishing", detail, "success")
        used_route = detail["route"]
        _patch_narration_source(job_id, {
            "polishing_status": "success",
            "polishing_provider": used_route.get("provider_name") or used_route.get("provider") or "",
            "polishing_model": used_route.get("model") or "",
            "polishing_reason": "",
        })
        append_log(job_id, f"脚本润色已使用 {used_route['provider_name']} / {used_route['model']}。")
        return polished
    except Exception as exc:
        _record_model_call(job_id, "script_polishing", {"route": route, "error": str(exc)}, "failed")
        _patch_narration_source(job_id, {"polishing_status": "failed", "polishing_reason": str(exc)})
        append_log(job_id, f"脚本润色失败，保留原稿: {exc}")
        return segments

def _sanitize_polished_segments(
    original: list[dict[str, Any]],
    polished: list[dict[str, Any]],
) -> list[dict[str, str]]:
    expected = [str(segment.get("id") or "") for segment in original]
    by_id = {str(segment.get("id")): segment for segment in polished}
    cleaned = []
    for source in original:
        segment_id = str(source.get("id") or "")
        segment = by_id.get(segment_id)
        text = _clean_narration_text(str(segment.get("text") or "")) if segment else ""
        if not segment_id or not text or _contains_producer_visual_jargon(text) or _contains_forbidden_narration(text):
            return []
        cleaned.append({
            "id": segment_id,
            "label": str(segment.get("label") or source.get("label") or _segment_label(segment_id)),
            "text": text,
        })
    return cleaned if [segment["id"] for segment in cleaned] == expected else []

def _sanitize_model_segments(projects: list[dict[str, Any]], segments: list[dict[str, Any]]) -> list[dict[str, str]]:
    expected = ["intro", *[f"project-{index}" for index in range(1, len(projects) + 1)], "outro"]
    by_id = {str(segment.get("id")): segment for segment in segments}
    cleaned = []
    for segment_id in expected:
        segment = by_id.get(segment_id)
        text = _clean_narration_text(str(segment.get("text") or "")) if segment else ""
        if not text or _contains_producer_visual_jargon(text) or _contains_forbidden_narration(text):
            return []
        cleaned.append({
            "id": segment_id,
            "label": str(segment.get("label") or _segment_label(segment_id)),
            "text": text,
        })
    return cleaned

def _clean_narration_text(text: str) -> str:
    return " ".join(text.split()).strip()

def _segment_label(segment_id: str) -> str:
    if segment_id == "intro":
        return "开场"
    if segment_id == "outro":
        return "结尾"
    return f"第 {segment_id.removeprefix('project-')} 名"

def _update_candidate_source(job_id: str, patch: dict[str, Any]) -> None:
    job = read_job(job_id) or {}
    source = dict(job.get("candidate_source") or {})
    source.update(patch)
    source["summary"] = " · ".join([
        value
        for value in (
            source.get("cache_label"),
            source.get("analysis_label"),
            source.get("ranking_label"),
        )
        if value
    ])
    update_job(job_id, candidate_source=source)

def _candidate_cache_label(status: str) -> str:
    labels = {
        "hit": "缓存命中",
        "stale_rate_limit": "额度受限时使用缓存",
        "fresh": "GitHub 实时拉取",
    }
    return labels.get(status, "GitHub 实时拉取")

def _update_narration_source(job_id: str, route: dict[str, Any], status: str, reason: str) -> None:
    source = {
        "status": status,
        "provider": route.get("provider_name") or route.get("provider") or "",
        "model": route.get("model") or "",
        "reason": reason,
    }
    write_json(JOBS_DIR / job_id / "narration_source.json", source)
    update_job(job_id, narration_source=source)

def _patch_narration_source(job_id: str, patch: dict[str, Any]) -> None:
    job = read_job(job_id) or {}
    source = dict(job.get("narration_source") or read_json(JOBS_DIR / job_id / "narration_source.json", {}))
    source.update(patch)
    write_json(JOBS_DIR / job_id / "narration_source.json", source)
    update_job(job_id, narration_source=source)

def _default_narrations(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments = [
        {
            "id": "intro",
            "label": "开场",
            "text": _intro_line(projects),
        }
    ]
    for index, project in enumerate(projects, start=1):
        segments.append({
            "id": f"project-{index}",
            "label": f"第 {index} 名",
            "text": _default_project_narration(project),
        })
    segments.append({
        "id": "outro",
        "label": "结尾",
        "text": _outro_line(projects),
    })
    return segments

def _intro_line(projects: list[dict[str, Any]]) -> str:
    count = len(projects)
    return (
        f"别再只按 Star 收藏项目了。今天这 {count} 个 GitHub 项目，"
        f"我只看它能不能帮你少走一步弯路。"
    )

def _outro_line(projects: list[dict[str, Any]]) -> str:
    names = "、".join(str(project.get("name") or "这个项目") for project in projects[:3])
    return (
        f"这期最值得回看的，不是排名，而是你现在卡在哪一步。"
        f"如果你想让我把 {names} 里面某一个拆成实操教程，评论区直接打项目名；"
        f"我下一期就按真实使用场景拆给你看。"
    )

def _default_project_narration(project: dict[str, Any]) -> str:
    name = project.get("name") or project.get("full_name") or "这个项目"
    feature = _sanitize_feature_extract(project.get("feature_extract")) or _fallback_feature_extract(project)
    pain = feature["core_problem"]
    highlight = feature["core_action"]
    benefit = feature.get("quantified_benefit") or "重点是把一个具体流程缩短"
    audience = _viewer_audience(project)
    return (
        f"{pain} 不是靠多收藏几个项目解决的。"
        f"{name} 的核心动作是：{highlight}。"
        f"{benefit}。"
        f"适合：被「{pain}」折磨的{_audience_phrase(audience)}。"
    )

def _description_phrase(description: str) -> str:
    if re.match(r"^[A-Za-z0-9]", description):
        return f" {description}"
    return description

def _audience_phrase(audience: str) -> str:
    if re.match(r"^[A-Za-z0-9]", audience):
        return f" {audience}"
    return audience

def _manifest(projects: list[dict[str, Any]]) -> AssetManifest:
    assets = []
    for index, project in enumerate(projects, start=1):
        assets.extend(_project_visual_assets(index, project))
    return AssetManifest(assets=assets)

def _project_visual_assets(index: int, project: dict[str, Any]) -> list[VisualAsset]:
    full_name = str(project.get("full_name") or "")
    repo_url = str(project.get("repo_url") or "")
    description = str(project.get("description") or project.get("description_zh") or "")[:60]
    candidates: list[tuple[str, str, str, str, str]] = []

    homepage = str(project.get("homepage") or "").strip()
    if homepage:
        candidates.append(("webpage", homepage, "项目官网或在线演示", "项目真实界面截图", "high"))
    for source in _readme_image_sources(project)[:2]:
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
    owner, repo = _project_owner_repo(project)
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
        f"#{index} {project.get('name') or project.get('full_name')} {_star_label(int(project.get('stars') or 0))}"
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
            subtitle=_ranking_overview_line(projects),
        ),
    ]
    start = 10.0
    for index, project in enumerate(projects, start=1):
        hook = str(project.get("description_zh") or project.get("name") or "GitHub 项目")[:28]
        detail = "|".join([
            _short_text(_viewer_pain(project), 24),
            _short_text(_viewer_highlight(project), 24),
            _short_text(_viewer_audience(project), 18),
        ])
        safe_detail = "|".join(_safe_part(part) for part in detail.split("|"))
        shots.append(Shot(
            start=start,
            duration=5.0,
            visual_asset=f"p{index}-asset-001",
            visual_treatment=(
                f"hotlist_rank_card:{index}:{_safe_part(str(project.get('name') or 'GitHub 项目'))}:"
                f"{_star_label(int(project.get('stars') or 0))}:{_safe_part(hook)}:{safe_detail}"
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

def _safe_filename(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|\s]+", "-", text).strip("-")
    return text[:40] or "GitHub热榜视频"

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
