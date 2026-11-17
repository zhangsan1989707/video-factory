"""Console job orchestration facade and core job lifecycle entrypoints."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from src.composer.bgm import post_process_video
from src.composer.vertical import render_vertical_previews
from src.console.background import JobCancelled, is_active, raise_if_cancelled
from src.console.github_hotlist import ESTIMATED_GROWTH_NOTE, collect_candidates_with_meta
from src.console.lark_sync import scan_published_full_names, sync_selected_projects
from src.console.model_router import chat_json_detail, route_snapshot
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
from src.console.skills_hotlist import (
    SKILLS_SOURCE_NOTE,
    collect_candidates_with_meta as collect_skills_candidates_with_meta,
)
from src.console.store import (
    DEFAULT_OFFICIAL_OUTPUT_DIR,
    JOBS_DIR,
    append_log,
    append_model_call,
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
from src.hotlist_v2.render import (
    _resolve_issue_number,
    _verify_preview_frame_image,
    render_hotlist_v2_from_projects,
    render_hotlist_v2_previews_from_projects,
)
from src.hotlist_v2.template import normalize_style, render_engine_for_style
from src.models import AssetManifest, ScriptSegment, Shot, ShotPlan, VideoScript, VisualAsset, shot_plan_from_dict
from src.pipeline import run_pipeline
from src.planner.script_v2 import generate_script_from_shot_plan
from src.utils.config import BGM_VOLUME, TTS_RATE, TTS_VOICE

from src.console.candidate_jobs import (
    _analyze_candidates,
    _annotate_already_published,
    _apply_candidate_ranking,
    _candidate_cache_label,
    _candidate_key,
    _clear_candidate_artifacts,
    _clear_candidates_only,
    _generate_candidates_snapshot,
    _mark_published_in_lark,
    _merge_candidate_analysis,
    _quota_waiting_hint,
    _rank_candidates,
    _sync_all_candidates_to_lark,
    _sync_selection_to_lark,
    _update_candidate_source,
    _write_lark_sync_status,
    generate_candidates,
    regenerate_candidates,
    resync_lark,
)
from src.console.finance_jobs import (
    _run_finance_edu_pipeline,
    finalize_stock_output,
    run_stock_pipeline_job,
)
from src.console.plan_jobs import (
    README_IMAGE_RE,
    _asset_manifest_from_dict,
    _clear_desktop_plan_artifacts,
    _clear_plan_artifacts,
    _copy_plan_snapshot,
    _desktop_preview_placeholders,
    _has_pipeline_plan,
    _manifest,
    _plan_validation_details,
    _prepare_from_plan_render,
    _prepare_single_project_plan,
    _preview_existing_plan,
    _project_owner_repo,
    _project_visual_assets,
    _readiness_check,
    _readme_image_sources,
    _safe_part,
    _shot_plan,
    _star_label,
    _video_script_from_dict,
    _write_cover_frame,
    _write_pipeline_job_readiness_report,
    _write_preview_visual_report,
    _write_readiness_report,
    _write_single_project_readiness_report,
    _write_video_spec_report,
    prepare_plan,
)
from src.console.render_jobs import (
    RENDER_STAGE_ORDER,
    _FILENAME_SANITIZE_RE,
    _available_video_path,
    _bgm_path,
    _bgm_volume,
    _clear_current_video_output,
    _clear_video_outputs,
    _copy_with_retry,
    _is_relative_to,
    _issue_number,
    _job_date_prefix,
    _job_type_label,
    _no_bgm,
    _official_issue_number,
    _official_video_base_name,
    _pipeline_style_for_job,
    _probe_video_duration,
    _render_command_for_job,
    _render_engine,
    _render_single_project_video,
    _safe_filename,
    _set_render_progress,
    _tts_rate,
    _tts_voice,
    _validate_single_project_plan,
    _version_index,
    _video_versions,
    _visual_style,
    _write_to_official_output_dir,
    finalize_numbered_output,
    render_video,
    reset_video_for_regeneration,
    validate_plan,
)
from src.console.script_jobs import (
    _audience_phrase,
    _clean_narration_text,
    _clear_script_metadata,
    _comment_guide,
    _console_segments_from_script,
    _cover_text,
    _default_hook,
    _default_narrations,
    _default_project_narration,
    _description_phrase,
    _ensure_feature_extracts,
    _extract_features_with_model,
    _fastest_growth_project,
    _generate_hook,
    _generate_script_for_selection,
    _growth_value,
    _hashtags,
    _intro_line,
    _is_skill_item,
    _is_skills_hotlist,
    _model_narrations,
    _narration_project_context,
    _outro_line,
    _patch_narration_source,
    _pipeline_job_projects,
    _polish_narrations,
    _ranking_overview_line,
    _sanitize_hook,
    _sanitize_model_segments,
    _sanitize_polished_segments,
    _save_pipeline_job_script,
    _segment_label,
    _selected_from_candidate_snapshot,
    _title_options,
    _update_narration_source,
    _validate_pipeline_script_segments,
    _validate_script_segments,
    _write_pipeline_publish_pack,
    _write_publish_pack,
    _write_script_from_console_segments,
    regenerate_script,
    save_script,
    save_selection,
)


def create_hotlist_job(payload: dict[str, Any]) -> dict[str, Any]:
    return _create_job_with_retry("GH-HOTLIST", _with_auto_issue_number(payload))


def create_stock_job(payload: dict[str, Any]) -> dict[str, Any]:
    """创建股票科普视频任务"""
    return _create_job_with_retry("STOCK", {**payload, "type": "stock_education"})


def create_finance_edu_job(payload: dict[str, Any]) -> dict[str, Any]:
    """创建炒股科普视频任务（finance_edu）"""
    return _create_job_with_retry("FINEDU", {**payload, "type": "finance_edu"})


def create_skills_hotlist_job(payload: dict[str, Any]) -> dict[str, Any]:
    return _create_job_with_retry("SK-HOTLIST", _with_auto_issue_number({**payload, "type": "skills_hotlist"}))


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


def _require_regenerable_job(job_id: str) -> dict[str, Any]:
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    if str(job.get("status") or "") == "running":
        raise ValueError("任务运行中，不能重新生成")
    return job


def _require_stage(job: dict[str, Any], allowed: set[str], message: str) -> None:
    if str(job.get("stage") or "") not in allowed:
        raise ValueError(f"{message}: {job.get('stage') or 'unknown'}")


def _job_type(job: dict[str, Any]) -> str:
    return str(job.get("type") or "github_hotlist")


def _require_job_type(job: dict[str, Any], expected: str | set[str], message: str) -> None:
    expected_types = {expected} if isinstance(expected, str) else expected
    if _job_type(job) not in expected_types:
        raise ValueError(f"{message}: {_job_type(job)}")


def _set_progress_hint(job_id: str, *, kind: str, text: str, reset_at: str | None = None) -> None:
    """在任务上记录一个简短的进度提示，让 UI 即便没有 stage 切换也能让用户看到在做什么。

    ``kind`` 取值：``pending / waiting_quota / analyzing / ranking / done / failed``。
    ``reset_at`` 用于配额等待场景，UI 可直接展示 ``"重置 hh:mm"``。
    """
    hint = {"kind": str(kind or "pending"), "text": str(text or "")}
    if reset_at:
        hint["reset_at"] = str(reset_at)
    update_job(job_id, progress_hint=hint)


def job_detail(job_id: str) -> dict[str, Any]:
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    job = {**job, "active": is_active(job_id)}
    model_calls = job.get("model_calls") or []
    return {
        "job": job,
        "candidates": _annotate_already_published(read_json(JOBS_DIR / job_id / "candidates.json", {}).get("items", [])),
        "selected": read_json(JOBS_DIR / job_id / "selected_projects.json", {}).get("items", []),
        "segments": read_json(JOBS_DIR / job_id / "narration.json", {}).get("segments", []),
        "hook": read_json(JOBS_DIR / job_id / "hook.json", {}),
        "publish_pack": read_json(JOBS_DIR / job_id / "publish_pack.json", {}),
        "cover_frame": read_json(JOBS_DIR / job_id / "cover_frame.json", {}),
        "preview_visual_report": read_json(JOBS_DIR / job_id / "preview_visual_report.json", {}),
        "video_spec_report": read_json(JOBS_DIR / job_id / "video_spec_report.json", {}),
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
