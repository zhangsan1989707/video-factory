"""Candidate collection, analysis, ranking, and Lark candidate sync for console jobs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from src.console import jobs as _jobs


async def generate_candidates(job_id: str, force_refresh: bool = True) -> dict[str, Any]:
    job = _jobs.read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    _jobs._require_job_type(job, {"github_hotlist", "skills_hotlist"}, "当前任务类型不支持候选生成")
    _jobs._require_stage(
        job,
        {"draft_pending", "collecting_candidates", "analyzing_candidates", "awaiting_project_confirmation"},
        "当前阶段不能生成候选项目",
    )
    return await _jobs._generate_candidates_snapshot(job_id, job, force_refresh=force_refresh)


async def regenerate_candidates(job_id: str) -> dict[str, Any]:
    job = _jobs._require_regenerable_job(job_id)
    _jobs.append_log(job_id, "已请求重新生成候选项目；将清除已选项目、口播、计划文件和视频产物。")
    return await _jobs._generate_candidates_snapshot(job_id, job, force_refresh=True)


async def _generate_candidates_snapshot(job_id: str, job: dict[str, Any], force_refresh: bool = True) -> dict[str, Any]:
    is_refresh = force_refresh and str(job.get("stage") or "") == "awaiting_project_confirmation"
    if is_refresh:
        _jobs._clear_candidates_only(job_id)
        _jobs.append_log(job_id, "已请求跳过缓存，仅刷新候选数据，保留已选项目和口播。")
    else:
        _jobs._clear_candidate_artifacts(job_id)
    _jobs.update_job(job_id, status="running", stage="collecting_candidates", failed_stage="", error="")
    is_skills_job = _jobs._job_type(job) == "skills_hotlist"
    item_label = "Skills" if is_skills_job else "项目"
    _jobs._set_progress_hint(job_id, kind="pending", text=f"正在拉取 {job.get('time_window', 'weekly')} 候选{item_label}…")
    _jobs.append_log(
        job_id,
        f"开始拉取 {job.get('time_window', 'weekly')} 候选{item_label}。" + ("（跳过缓存）" if force_refresh else ""),
    )
    try:
        if is_skills_job:
            result = await _jobs.collect_skills_candidates_with_meta(
                time_window=str(job.get("time_window") or "weekly"),
                limit=30,
                force_refresh=force_refresh,
            )
        else:
            result = await _jobs.collect_candidates_with_meta(
                time_window=str(job.get("time_window") or "weekly"),
                token=_jobs.read_github_token(),
                limit=30,
                force_refresh=force_refresh,
            )
        candidates = result["items"]
        if not is_skills_job:
            _jobs.update_github_rate_limit(str(result.get("rate_limit") or "未检测"))
        if result.get("cache_status") == "hit" and is_skills_job:
            _jobs.append_log(job_id, "使用缓存！Skills 热榜候选缓存命中，未请求数据源。")
        elif result.get("cache_status") == "hit":
            _jobs.append_log(job_id, "使用缓存！GitHub 候选缓存命中，未请求 API。")
            _jobs.append_log(job_id, f"GitHub 缓存记录额度: {result.get('rate_limit') or '未检测'}。")
        elif str(result.get("cache_status") or "").startswith("stale") and is_skills_job:
            _jobs.append_log(job_id, f"使用缓存！Skills 热榜数据源异常，已使用最近缓存候选: {result.get('degraded_reason') or '未知原因'}。")
        elif result.get("cache_status") == "stale_rate_limit":
            _jobs.append_log(job_id, "使用缓存！GitHub 额度受限，已使用最近缓存候选。")
            _jobs.append_log(job_id, f"GitHub 缓存记录额度: {result.get('rate_limit') or '未检测'}。")
        elif is_skills_job:
            _jobs.append_log(job_id, f"Skills 热榜数据源: {result.get('data_source') or 'skills_hotlist'}。")
        else:
            _jobs.append_log(job_id, f"GitHub API 额度: {result.get('rate_limit') or '未检测'}。")
        if not is_skills_job:
            _jobs.append_log(job_id, _jobs.ESTIMATED_GROWTH_NOTE)
        quota_hint = _jobs._quota_waiting_hint(str(result.get("rate_limit") or ""))
        if quota_hint and result.get("cache_status") != "hit" and not is_skills_job:
            _jobs._set_progress_hint(job_id, kind="waiting_quota", text="等待 GitHub 配额刷新…", reset_at=quota_hint)
        _jobs.update_job(job_id, status="running", stage="analyzing_candidates")
        _jobs._set_progress_hint(job_id, kind="analyzing", text="候选分析 / 排序进行中…")
        _jobs._update_candidate_source(job_id, {
            "cache_status": str(result.get("cache_status") or "fresh"),
            "cache_label": _jobs._candidate_cache_label(str(result.get("cache_status") or "fresh")),
            "analysis_status": "pending",
            "analysis_label": "候选分析进行中",
            "ranking_status": "pending",
            "ranking_label": "排序进行中",
        })
        candidates = _jobs._analyze_candidates(job_id, candidates)
        _jobs._set_progress_hint(job_id, kind="ranking", text="候选排序中…")
        candidates = _jobs._rank_candidates(job_id, candidates)
        # 标注已发布状态，供前端展示
        _jobs._annotate_already_published(candidates)
        _jobs.write_json(_jobs.JOBS_DIR / job_id / "candidates.json", {"items": candidates})
        _jobs.append_log(job_id, f"候选{item_label}拉取完成，共 {len(candidates)} 个。")
        # 任务级统一时间戳，供飞书同步和后续已选/发布标记使用
        fetch_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        job["fetch_time"] = fetch_time
        _jobs.update_job(job_id, fetch_time=fetch_time)
        result_meta = {
            "cache_status": str(result.get("cache_status") or "fresh"),
            "data_source": str(result.get("data_source") or "trending"),
            "time_window": str(job.get("time_window") or "daily"),
        }
        _jobs._sync_all_candidates_to_lark(job_id, job, candidates, result_meta, fetch_time)
        _jobs.update_job(job_id, status="awaiting_input", stage="awaiting_project_confirmation")
        _jobs._set_progress_hint(job_id, kind="done", text="候选已就绪，请确认项目。")
        return {"job": _jobs.read_job(job_id), "candidates": candidates}
    except Exception as exc:
        _jobs.append_log(job_id, f"候选项目拉取失败: {exc}")
        failed_stage = str(_jobs.read_job(job_id).get("stage") or "collecting_candidates")
        _jobs.update_job(job_id, status="failed", stage=failed_stage, failed_stage=failed_stage, error=str(exc))
        _jobs._set_progress_hint(job_id, kind="failed", text=f"失败：{_jobs._short_text(str(exc), 120)}")
        raise


def _write_lark_sync_status(job_id: str, segment: str, payload: dict[str, Any]) -> None:
    """写入 job.lark_sync.{segment} 状态"""
    job = _jobs.read_job(job_id)
    lark_sync = dict(job.get("lark_sync") or {})
    lark_sync[segment] = {**payload, "at": datetime.now(timezone.utc).isoformat()}
    _jobs.update_job(job_id, lark_sync=lark_sync)


def _sync_selection_to_lark(job_id: str, selected: list[dict[str, Any]]) -> None:
    """已选项目同步到飞书已选表。手动与调度任务均同步。"""
    job = _jobs.read_job(job_id)
    try:
        result = _jobs.sync_selected_projects(job, selected)
    except Exception as exc:
        _jobs.append_log(job_id, f"飞书多维表格同步失败，已继续生成口播: {exc}")
        _jobs._write_lark_sync_status(job_id, "selected", {"status": "failed", "error": str(exc)})
        return
    if result.get("status") == "synced":
        _jobs.append_log(job_id, f"飞书多维表格已同步 {result.get('count') or 0} 个选中项目。")
        _jobs._write_lark_sync_status(job_id, "selected", result)
    elif result.get("status") == "partial":
        err_count = len(result.get("errors") or [])
        _jobs.append_log(job_id, f"飞书多维表格部分同步: 成功 {result.get('count') or 0} 个，{err_count} 个失败或超时，已继续生成口播。")
        _jobs._write_lark_sync_status(job_id, "selected", result)
    elif result.get("status") == "skipped":
        _jobs.append_log(job_id, f"飞书多维表格同步跳过，已继续生成口播: {result.get('error') or '配置不完整'}")
        _jobs._write_lark_sync_status(job_id, "selected", result)
    elif result.get("status") == "disabled":
        _jobs._write_lark_sync_status(job_id, "selected", result)


def resync_lark(job_id: str, segment: str = "all") -> dict[str, Any]:
    """手动重试飞书同步。支持 segment="selected"/"all_data"/"all"。

    从磁盘文件中读取已有的候选/已选，重新执行对应的同步逻辑。
    同步执行——每个 segment 依次执行并写入状态。
    """
    from .lark_sync import read_lark_config

    job = _jobs.read_job(job_id)
    if not job:
        return {"ok": False, "error": "任务不存在"}
    if not read_lark_config().get("enabled"):
        return {"ok": False, "error": "飞书同步未启用"}

    segments_to_retry = ["selected", "all_data"] if segment == "all" else [segment]
    results: dict[str, str] = {}

    for seg in segments_to_retry:
        if seg == "selected":
            selected = _jobs.read_json(_jobs.JOBS_DIR / job_id / "selected_projects.json", {}).get("items") or []
            if not selected:
                results[seg] = "no_selection"
                continue
            _jobs._sync_selection_to_lark(job_id, selected)
            results[seg] = "triggered"
        elif seg == "all_data":
            candidates = _jobs.read_json(_jobs.JOBS_DIR / job_id / "candidates.json", {}).get("items") or []
            result_meta = {
                "cache_status": str(job.get("cache_status") or "fresh"),
                "data_source": str(job.get("data_source") or "trending"),
                "time_window": str(job.get("time_window") or "daily"),
            }
            fetch_time = str(job.get("fetch_time") or "")
            if not candidates:
                results[seg] = "no_candidates"
                continue
            _jobs._sync_all_candidates_to_lark(job_id, job, candidates, result_meta, fetch_time)
            results[seg] = "triggered"

    return {"ok": True, "segments": results}


def _sync_all_candidates_to_lark(
    job_id: str,
    job: dict[str, Any],
    candidates: list[dict[str, Any]],
    result_meta: dict[str, Any],
    fetch_time: str,
) -> None:
    """全量候选同步到飞书"""
    from .lark_sync import read_lark_config, sync_all_candidates

    cfg = read_lark_config()
    if not cfg.get("enabled") or not cfg.get("sync_all_data") or not cfg.get("all_data_table_id"):
        _jobs._write_lark_sync_status(job_id, "all_data", {"status": "disabled"})
        return
    try:
        result = sync_all_candidates(
            job=job,
            candidates=candidates,
            result_meta=result_meta,
            fetch_time=fetch_time,
            base_token=cfg["base_token"],
            table_id=cfg["all_data_table_id"],
        )
        _jobs._write_lark_sync_status(job_id, "all_data", result)
    except Exception as e:
        _jobs.append_log(job_id, f"全量同步失败: {e}")
        _jobs._write_lark_sync_status(job_id, "all_data", {"status": "failed", "error": str(e)})


def _mark_published_in_lark(job_id: str) -> None:
    """标记已选项目为已发布"""
    from .lark_sync import mark_published_in_lark, read_lark_config

    cfg = read_lark_config()
    if not cfg.get("enabled") or not cfg.get("sync_selected_data") or not cfg.get("selected_data_table_id"):
        _jobs._write_lark_sync_status(job_id, "publish_mark", {"status": "disabled"})
        return
    job = _jobs.read_job(job_id)
    sel_path = _jobs.JOBS_DIR / job_id / "selected_projects.json"
    if not sel_path.exists():
        _jobs._write_lark_sync_status(job_id, "publish_mark", {"status": "skipped", "reason": "no selection"})
        return
    sel = _jobs.read_json(sel_path, {})
    published_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        result = mark_published_in_lark(
            job=job,
            selected=sel.get("items", []),
            published_at=published_at,
            base_token=cfg["base_token"],
            table_id=cfg["selected_data_table_id"],
        )
        _jobs._write_lark_sync_status(job_id, "publish_mark", result)
    except Exception as e:
        _jobs.append_log(job_id, f"标记已发布失败: {e}")
        _jobs._write_lark_sync_status(job_id, "publish_mark", {"status": "failed", "error": str(e)})


def _candidate_key(item: dict[str, Any]) -> str:
    return str(item.get("full_name") or item.get("repo_url") or "").strip()


def _annotate_already_published(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为候选列表标注 _already_published 标志，供前端展示"""
    published = _jobs.scan_published_full_names()
    for c in candidates:
        c["_already_published"] = c.get("full_name") in published
    return candidates


def _clear_candidate_artifacts(job_id: str) -> None:
    job_dir = _jobs.JOBS_DIR / job_id
    for name in ("candidates.json", "selected_projects.json", "narration.json", "hook.json"):
        path = job_dir / name
        if path.exists() and path.is_file():
            path.unlink()
    _jobs._clear_script_metadata(job_id)
    _jobs._clear_plan_artifacts(job_id)


def _clear_candidates_only(job_id: str) -> None:
    """Only clear candidates.json, preserving selected projects and narration."""
    path = _jobs.JOBS_DIR / job_id / "candidates.json"
    if path.exists() and path.is_file():
        path.unlink()


def _analyze_candidates(job_id: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    route = _jobs.route_snapshot("candidate_analysis")
    if not _jobs._route_available(route):
        _jobs.append_log(job_id, f"候选分析使用启发式评分：{_jobs._route_skip_reason(route)}。")
        _jobs._update_candidate_source(job_id, {
            "analysis_status": "heuristic",
            "analysis_label": f"启发式评分（{_jobs._route_skip_reason(route)}）",
        })
        return candidates
    is_skills = _jobs._is_skills_hotlist(candidates)
    topic_label = "AI Skills 热榜" if is_skills else "GitHub 热榜"
    item_label = "技能" if is_skills else "项目"
    prompt = {
        "instruction": (
            f"为中文 {topic_label} 短视频分析候选{item_label}。只根据输入字段判断，不要夸大。"
            f"区分观众听得懂的{item_label}价值和制作侧画面建议。"
            f"每个{item_label}的 description_zh、project_highlight、viewer_benefit 必须写出具体功能或使用场景，"
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
        detail = _jobs.chat_json_detail(
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
            _jobs._write_ai_raw_response(job_id, "candidate_analysis", detail)
            _jobs._record_model_call(job_id, "candidate_analysis", detail, "invalid_json")
            _jobs.append_log(job_id, "候选分析模型未返回可用 JSON，保留启发式结果。")
            _jobs._update_candidate_source(job_id, {
                "analysis_status": "ai_failed_fallback",
                "analysis_label": f"AI 响应异常后回退启发式（{_jobs._short_text(detail.get('error') or '模型未返回可用 JSON', 80)}）",
            })
            return candidates
        for index, candidate in enumerate(candidates, start=1):
            patch = by_index.get(index)
            if patch:
                _jobs._merge_candidate_analysis(candidate, patch)
        _jobs._record_model_call(job_id, "candidate_analysis", detail, "success")
        _jobs.append_log(job_id, f"候选分析已使用 {used_route['provider_name']} / {used_route['model']}。")
        _jobs._update_candidate_source(job_id, {
            "analysis_status": "ai_success",
            "analysis_label": f"AI 分析：{used_route['provider_name']} / {used_route['model']}",
        })
    except Exception as exc:
        _jobs._record_model_call(job_id, "candidate_analysis", {"route": route, "error": str(exc)}, "failed")
        _jobs.append_log(job_id, f"候选分析模型失败，保留启发式结果: {exc}")
        _jobs._update_candidate_source(job_id, {
            "analysis_status": "ai_failed_fallback",
            "analysis_label": f"AI 失败后回退启发式（{_jobs._short_text(str(exc), 80)}）",
        })
    return candidates


def _rank_candidates(job_id: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    route = _jobs.route_snapshot("hotlist_ranking")
    if not _jobs._route_available(route):
        _jobs.append_log(job_id, f"热榜排序使用默认顺序：{_jobs._route_skip_reason(route)}。")
        _jobs._update_candidate_source(job_id, {
            "ranking_status": "default",
            "ranking_label": f"默认顺序（{_jobs._route_skip_reason(route)}）",
        })
        return candidates
    is_skills = _jobs._is_skills_hotlist(candidates)
    topic_label = "AI Skills 热榜" if is_skills else "GitHub 热榜"
    item_label = "技能" if is_skills else "项目"
    prompt = {
        "instruction": f"为中文 {topic_label} 短视频给候选{item_label}排序。优先考虑观众价值、可解释性、画面潜力和事实稳妥性。",
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
        detail = _jobs.chat_json_detail(
            "hotlist_ranking",
            "你是克制的中文选题排序编辑，只输出 JSON。",
            json.dumps(prompt, ensure_ascii=False),
            max_tokens=2600,
        )
        data = detail["data"]
        ranked = _jobs._apply_candidate_ranking(candidates, data.get("items", []) if data else [])
        if not ranked:
            _jobs._write_ai_raw_response(job_id, "hotlist_ranking", detail)
            _jobs._record_model_call(job_id, "hotlist_ranking", detail, "invalid_json")
            _jobs.append_log(job_id, "热榜排序模型未返回可用 JSON，保留默认顺序。")
            _jobs._update_candidate_source(job_id, {
                "ranking_status": "ai_failed_default",
                "ranking_label": f"AI 排序异常后保留默认顺序（{_jobs._short_text(detail.get('error') or '模型未返回可用 JSON', 80)}）",
            })
            return candidates
        _jobs._record_model_call(job_id, "hotlist_ranking", detail, "success")
        used_route = detail["route"]
        _jobs.append_log(job_id, f"热榜排序已使用 {used_route['provider_name']} / {used_route['model']}。")
        _jobs._update_candidate_source(job_id, {
            "ranking_status": "ai_success",
            "ranking_label": f"AI 排序：{used_route['provider_name']} / {used_route['model']}",
        })
        return ranked
    except Exception as exc:
        _jobs._record_model_call(job_id, "hotlist_ranking", {"route": route, "error": str(exc)}, "failed")
        _jobs.append_log(job_id, f"热榜排序模型失败，保留默认顺序: {exc}")
        _jobs._update_candidate_source(job_id, {
            "ranking_status": "ai_failed_default",
            "ranking_label": f"AI 排序失败后保留默认顺序（{_jobs._short_text(str(exc), 80)}）",
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
        ranks[index - 1] = (rank, _jobs._short_text(str(item.get("reason") or ""), 140))
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


def _merge_candidate_analysis(candidate: dict[str, Any], patch: dict[str, Any]) -> None:
    for key in ("description_zh", "recommendation", "project_highlight", "viewer_benefit", "risk", "audience", "visual_potential"):
        if patch.get(key):
            candidate[key] = _jobs._short_text(str(patch[key]), 120)
    try:
        score = int(patch.get("score"))
        candidate["score"] = max(0, min(100, score))
    except Exception:
        pass


def _update_candidate_source(job_id: str, patch: dict[str, Any]) -> None:
    job = _jobs.read_job(job_id) or {}
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
    _jobs.update_job(job_id, candidate_source=source)


def _quota_waiting_hint(rate_limit_label: str) -> str | None:
    """如果 rate_limit 文案里 ``remaining == 0``，返回 ``"hh:mm"`` 重置时间；否则返回 None。"""
    label = str(rate_limit_label or "")
    match = re.match(r"\s*(\d+)\s*/\s*(\d+)\s*[,，]\s*重置\s*(\d{1,2}:\d{2})", label)
    if not match:
        return None
    remaining = int(match.group(1))
    if remaining > 0:
        return None
    return match.group(3)


def _candidate_cache_label(status: str) -> str:
    labels = {
        "hit": "缓存命中",
        "stale_rate_limit": "额度受限时使用缓存",
        "fresh": "GitHub 实时拉取",
    }
    return labels.get(status, "GitHub 实时拉取")
