"""Local scheduled draft runner for the console."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime
from typing import Any

from src.console.background import active_job, raise_if_cancelled
from src.console.jobs import create_hotlist_job, generate_candidates, prepare_plan, render_video, save_script, save_selection, validate_plan
from src.console.store import CONFIG_DIR, DEFAULT_SCHEDULER, DEFAULT_TEMPLATES, bool_value, config_snapshot, normalize_project_count, normalize_time_window, read_json, update_job, update_scheduler_last_run
from src.hotlist_v2.template import normalize_style


_STARTED = False
_LOCK = threading.Lock()
_RUNNING_KEYS: set[str] = set()


def run_due_scheduled_draft(now: datetime | None = None, force: bool = False) -> dict[str, Any]:
    now = now or datetime.now()
    schedule = _normalized_schedule(read_json(CONFIG_DIR / "scheduler.json", DEFAULT_SCHEDULER))
    if not force and not _is_due(schedule, now):
        return {"started": False, "reason": "not_due", "job": None}
    run_key = _run_key(schedule, now)
    with _LOCK:
        if run_key in _RUNNING_KEYS:
            return {"started": False, "reason": "already_running", "job": None}
        _RUNNING_KEYS.add(run_key)

    try:
        payload = {
            "title": "GitHub 定时热榜视频" if schedule.get("mode") == "auto_video" else "GitHub 定时热榜草稿",
            "scheduled": True,
            "schedule_mode": schedule.get("mode") or "candidates_only",
            "auto_confirm": bool(schedule.get("auto_confirm")),
            "time_window": schedule.get("time_window") or "daily",
            "project_count": normalize_project_count(schedule.get("project_count")),
            "template": _active_template_name(),
            "template_params": _scheduled_template_params(schedule),
        }
        job = create_hotlist_job(payload)
        with active_job(job["id"]):
            # 单一事件循环包整条 pipeline：避免 Playwright/httpx 等长生命周期资源
            # 在 asyncio.run 边界被强制销毁，并保证取消信号能穿透到各阶段。
            result = asyncio.run(
                _run_scheduled_pipeline(
                    job["id"],
                    schedule,
                    normalize_project_count(schedule.get("project_count")),
                )
            )
        _mark_schedule_run(run_key)
        merged_job = {**job, **(result.get("job") or {})}
        merged_job["scheduled"] = True
        merged_job["schedule_mode"] = schedule.get("mode") or "candidates_only"
        merged_job["auto_confirm"] = bool(schedule.get("auto_confirm"))
        update_job(job["id"], scheduled=True, schedule_mode=merged_job["schedule_mode"], auto_confirm=merged_job["auto_confirm"])
        return {"started": True, "reason": "due", "job": merged_job}
    finally:
        with _LOCK:
            _RUNNING_KEYS.discard(run_key)


async def _run_scheduled_pipeline(
    job_id: str,
    schedule: dict[str, Any],
    project_count: int,
) -> dict[str, Any]:
    """在单一事件循环里串行跑完候选→脚本→计划→渲染。"""
    raise_if_cancelled(job_id)
    result = await generate_candidates(job_id)
    auto_confirm = bool(schedule.get("auto_confirm"))
    mode = schedule.get("mode") or "candidates_only"
    if auto_confirm or mode in {"auto_script", "auto_video"}:
        # auto_confirm=true 时强制把"待确认项目"也消化掉；否则按 mode 跳过。
        raise_if_cancelled(job_id)
        result = _generate_scheduled_script(job_id, result, project_count)
    if auto_confirm or mode == "auto_video":
        result = await _generate_scheduled_video_async(job_id, result, auto_confirm=auto_confirm)
    return result


def start_scheduler_loop(interval_seconds: int = 60) -> bool:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return False
        _STARTED = True

    def loop() -> None:
        while True:
            try:
                run_due_scheduled_draft()
            except Exception as exc:
                print(f"Scheduled console draft failed: {exc}")
            time.sleep(interval_seconds)

    thread = threading.Thread(target=loop, name="console-scheduler", daemon=True)
    thread.start()
    return True


def _is_due(schedule: dict[str, Any], now: datetime) -> bool:
    if not bool_value(schedule.get("enabled")):
        return False
    if str(schedule.get("last_run_date") or "") == _run_key(schedule, now):
        return False
    try:
        hour, minute = [int(part) for part in str(schedule.get("time") or "09:00").split(":", 1)]
    except ValueError:
        hour, minute = 9, 0
    if schedule.get("frequency") == "weekly":
        # weekly 模式只允许周一/周二触发。周一整天已过预定时间即可；周二不限制时间
        # （周一已过，预定时间一定过），用于 catch-up 周一全天宕机的情况。
        if now.weekday() == 0 and (now.hour, now.minute) < (hour, minute):
            return False
        if now.weekday() not in {0, 1}:
            return False
        return True
    if (now.hour, now.minute) < (hour, minute):
        return False
    return True


def _run_key(schedule: dict[str, Any], now: datetime) -> str:
    if schedule.get("frequency") == "weekly":
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"
    return now.strftime("%Y-%m-%d")


def _normalized_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    data = dict(schedule)
    data["enabled"] = bool_value(data.get("enabled"))
    if data.get("mode") not in {"candidates_only", "auto_script", "auto_video"}:
        data["mode"] = DEFAULT_SCHEDULER["mode"]
    if data.get("frequency") not in {"daily", "weekly"}:
        data["frequency"] = DEFAULT_SCHEDULER["frequency"]
    data["time_window"] = normalize_time_window(data.get("time_window"), DEFAULT_SCHEDULER["time_window"])
    if not isinstance(data.get("template_params"), dict):
        data["template_params"] = {}
    else:
        params = dict(data["template_params"])
        if "style" not in params and params.get("visual_style"):
            params["style"] = params.get("visual_style")
        params.pop("visual_style", None)
        if params.get("style"):
            params["style"] = normalize_style(str(params.get("style") or ""))
        data["template_params"] = params
    return data


def _generate_scheduled_script(job_id: str, result: dict[str, Any], project_count: int) -> dict[str, Any]:
    candidates = result.get("candidates") or []
    selected = candidates[:project_count]
    if not selected:
        raise RuntimeError("定时脚本模式没有可用候选项目")
    return save_selection(job_id, {"items": selected})


async def _generate_scheduled_video_async(job_id: str, result: dict[str, Any], auto_confirm: bool = False) -> dict[str, Any]:
    segments = result.get("segments") or []
    if not segments:
        raise RuntimeError("定时出片模式没有可用口播脚本")
    raise_if_cancelled(job_id)
    # auto_confirm=true 时把脚本质检视为可忽略项，确保出片不被阻断。
    scripted = save_script(job_id, {"segments": segments, "ignore_quality_risk": auto_confirm})
    if (scripted.get("job") or {}).get("stage") == "awaiting_script_confirmation":
        raise RuntimeError((scripted.get("job") or {}).get("error") or "定时出片模式被脚本质检阻断")
    raise_if_cancelled(job_id)
    prepare_plan(job_id)
    raise_if_cancelled(job_id)
    await validate_plan(job_id)
    raise_if_cancelled(job_id)
    return await render_video(job_id)


def _mark_schedule_run(run_key: str) -> None:
    update_scheduler_last_run(run_key)


def _active_template_name() -> str:
    templates = config_snapshot()["templates"]
    active = str(templates.get("active_template") or DEFAULT_TEMPLATES["active_template"])
    return active if isinstance(templates.get(active), dict) else str(DEFAULT_TEMPLATES["active_template"])


def _scheduled_template_params(schedule: dict[str, Any]) -> dict[str, Any]:
    templates = config_snapshot()["templates"]
    active = _active_template_name()
    base = templates.get(active) if isinstance(templates.get(active), dict) else {}
    params = dict(base)
    params.update(schedule.get("template_params") or {})
    if params.get("visual_style"):
        params["style"] = params.get("style") or params.get("visual_style")
    params.pop("visual_style", None)
    if params.get("style"):
        params["style"] = normalize_style(str(params.get("style") or ""))
    return params
