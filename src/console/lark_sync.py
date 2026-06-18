"""Optional Lark Base sync for confirmed hotlist selections."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from typing import Any

from src.console.store import CONFIG_DIR, DEFAULT_LARK, JOBS_DIR, read_json


def read_lark_config():
    """读取 lark.json 配置并归一化"""
    from .store import CONFIG_DIR, _normalize_lark, read_json

    path = CONFIG_DIR / "lark.json"
    if not path.exists():
        return {
            "enabled": False,
            "base_token": "",
            "all_data_table_id": "",
            "selected_data_table_id": "",
            "sync_all_data": True,
            "sync_selected_data": True,
        }
    raw = read_json(path, DEFAULT_LARK)
    return _normalize_lark(raw)


def sync_selected_projects(job: dict[str, Any], projects: list[dict[str, Any]]) -> dict[str, Any]:
    config = read_json(CONFIG_DIR / "lark.json", DEFAULT_LARK)
    if not config.get("enabled"):
        return {"status": "disabled", "count": 0, "error": ""}

    base_token = str(config.get("base_token") or "").strip()
    table_id = str(config.get("table_id") or "").strip()
    if not base_token or not table_id:
        return {"status": "skipped", "count": 0, "error": "飞书同步未配置 base token 或 table id"}

    created = 0
    for index, project in enumerate(projects, start=1):
        _create_record(base_token, table_id, _record_fields(job, project, index))
        created += 1
    return {"status": "synced", "count": created, "error": ""}


def _create_record(base_token: str, table_id: str, fields: dict[str, Any]) -> None:
    subprocess.run(
        [
            "lark-cli",
            "base",
            "+record-upsert",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--json",
            json.dumps(fields, ensure_ascii=False),
            "--as",
            "user",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _record_fields(job: dict[str, Any], project: dict[str, Any], order: int) -> dict[str, Any]:
    return {
        "确认日期": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "任务 ID": str(job.get("id") or ""),
        "榜单窗口": str(job.get("time_window") or ""),
        "选择顺序": order,
        "项目全名": str(project.get("full_name") or project.get("name") or ""),
        "仓库 URL": str(project.get("repo_url") or ""),
        "项目名称": str(project.get("name") or ""),
        "描述": str(project.get("description_zh") or project.get("description") or ""),
        "Stars": _number_or_none(project.get("stars")),
        "Daily Growth": str(project.get("daily_growth") or ""),
        "语言": str(project.get("language") or ""),
        "推荐理由": str(project.get("recommendation") or ""),
    }


def _number_or_none(value: Any) -> int | float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def upsert_records(
    base_token: str,
    table_id: str,
    records: list[dict[str, Any]],
    key_fields: tuple[str, ...],
    *,
    identity: str = "user",
) -> dict[str, Any]:
    """按 (key_fields) 复合键 upsert records 到指定表。

    对每条 record：先 +record-list 查重，找到则 +record-update，否则 +record-batch-create。
    Returns: {"created": int, "updated": int, "errors": list}
    """
    if not records:
        return {"created": 0, "updated": 0, "errors": []}

    to_create: list[dict[str, Any]] = []
    to_update: list[tuple[str, dict[str, Any]]] = []  # (record_id, fields)
    errors: list[dict[str, Any]] = []

    for record in records:
        try:
            filter_expr = _build_filter(record, key_fields)
            list_cmd = [
                "lark-cli", "base", "+record-list",
                "--base-token", base_token,
                "--table-id", table_id,
                "--filter", filter_expr,
                "--as", identity,
            ]
            proc = subprocess.run(list_cmd, capture_output=True, text=True, check=True, timeout=30)
            data = json.loads(proc.stdout or "{}")
            items = (data.get("data") or {}).get("items") or []
            if items:
                record_id = items[0].get("record_id")
                to_update.append((record_id, record))
            else:
                to_create.append(record)
        except Exception as e:
            errors.append({"record": record, "error": str(e)})

    created = 0
    if to_create:
        for chunk in _chunks(to_create, 200):
            cmd = [
                "lark-cli", "base", "+record-batch-create",
                "--base-token", base_token,
                "--table-id", table_id,
                "--json", json.dumps(chunk, ensure_ascii=False),
                "--as", identity,
            ]
            try:
                subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
                created += len(chunk)
            except Exception as e:
                for r in chunk:
                    errors.append({"record": r, "error": f"batch-create: {e}"})

    updated = 0
    for record_id, fields in to_update:
        cmd = [
            "lark-cli", "base", "+record-update",
            "--base-token", base_token,
            "--table-id", table_id,
            "--record-id", record_id,
            "--json", json.dumps(fields, ensure_ascii=False),
            "--as", identity,
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
            updated += 1
        except Exception as e:
            errors.append({"record": fields, "error": f"update: {e}"})

    return {"created": created, "updated": updated, "errors": errors}


def sync_all_candidates(
    *,
    job: dict[str, Any],
    candidates: list[dict[str, Any]],
    result_meta: dict[str, Any],
    fetch_time: str,
    base_token: str,
    table_id: str,
    identity: str = "user",
) -> dict[str, Any]:
    """把全量候选 upsert 到"每日全量候选"表。

    fetch_time: 任务级统一时间戳字符串。
    """
    if not base_token or not table_id:
        return {"status": "skipped", "reason": "missing config", "created": 0, "updated": 0, "records_count": 0}

    scheduled = bool(job.get("scheduled"))
    time_window = result_meta.get("time_window", "daily")
    data_source = result_meta.get("data_source", "trending")
    cache_status = result_meta.get("cache_status", "fresh")
    fetch_mode = "调度" if scheduled else "手动"

    records = []
    for c in candidates:
        records.append({
            "抓取时间": fetch_time,
            "项目全名": c.get("full_name", ""),
            "时间窗口": time_window,
            "数据源": data_source,
            "排名": c.get("rank", 0),
            "抓取任务ID": job.get("id", ""),
            "仓库URL": c.get("html_url", ""),
            "项目名": c.get("name", ""),
            "描述原文": c.get("description", ""),
            "描述中文": c.get("description_zh", ""),
            "Stars": c.get("stargazers_count", 0),
            "Daily Growth": c.get("growth_text", ""),
            "语言": c.get("language", ""),
            "Topics": ", ".join(c.get("topics", []) or []),
            "推荐理由": c.get("rationale", ""),
            "风险": c.get("risk", ""),
            "受众": c.get("audience", ""),
            "评分": c.get("score", 0),
            "是否有主页": bool(c.get("has_homepage", False)),
            "缓存状态": cache_status,
            "抓取方式": fetch_mode,
        })

    result = upsert_records(
        base_token=base_token,
        table_id=table_id,
        records=records,
        key_fields=("项目全名", "抓取时间"),
        identity=identity,
    )
    return {
        "status": "synced" if not result["errors"] else "partial",
        "created": result["created"],
        "updated": result["updated"],
        "errors": result["errors"],
        "records_count": len(records),
    }


def _build_filter(record: dict[str, Any], key_fields: tuple[str, ...]) -> str:
    """构造飞书 filter 表达式"""
    parts = []
    for f in key_fields:
        val = record.get(f, "")
        parts.append(f'{f}="{val}"')
    return "AND(" + ",".join(parts) + ")"


def _chunks(lst: list, n: int):
    """将列表按 n 大小分块"""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def mark_published_in_lark(
    *,
    job: dict[str, Any],
    selected: list[dict[str, Any]],
    published_at: str,
    base_token: str,
    table_id: str,
    identity: str = "user",
) -> dict[str, Any]:
    """把已选表对应 record 标记为已发布。

    job.fetch_time 必须与 selected 同步时的抓取时间一致。
    """
    if not base_token or not table_id:
        return {"status": "skipped", "reason": "missing config", "updated": 0, "missing": [], "errors": []}

    fetch_time = job.get("fetch_time", "")
    updated = 0
    missing: list[str] = []
    errors: list[dict[str, Any]] = []

    for s in selected:
        full_name = s.get("full_name", "")
        if not full_name:
            continue
        try:
            filter_expr = _build_filter(
                {"项目全名": full_name, "抓取时间": fetch_time},
                ("项目全名", "抓取时间"),
            )
            list_cmd = [
                "lark-cli", "base", "+record-list",
                "--base-token", base_token, "--table-id", table_id,
                "--filter", filter_expr,
                "--as", identity,
            ]
            proc = subprocess.run(list_cmd, capture_output=True, text=True, check=True, timeout=30)
            data = json.loads(proc.stdout or "{}")
            items = (data.get("data") or {}).get("items") or []
            if not items:
                missing.append(full_name)
                continue
            record_id = items[0]["record_id"]
            fields = {
                "已发布": True,
                "发布时间": published_at,
                "视频路径": s.get("official_video", ""),
                "视频标题": s.get("video_title", ""),
            }
            upd_cmd = [
                "lark-cli", "base", "+record-update",
                "--base-token", base_token, "--table-id", table_id,
                "--record-id", record_id,
                "--json", json.dumps(fields, ensure_ascii=False),
                "--as", identity,
            ]
            subprocess.run(upd_cmd, capture_output=True, text=True, check=True, timeout=30)
            updated += 1
        except Exception as e:
            errors.append({"full_name": full_name, "error": str(e)})

    return {
        "status": "synced" if not errors and not missing else ("partial" if updated else "failed"),
        "updated": updated,
        "missing": missing,
        "errors": errors,
    }


def scan_published_full_names() -> set[str]:
    """扫 JOBS_DIR，返回已发布项目的 full_name 集合（status=completed && official_video 非空）"""
    published: set[str] = set()
    if not JOBS_DIR.exists():
        return published
    for task_path in JOBS_DIR.glob("*/task.json"):
        try:
            task = read_json(task_path, {})
        except Exception:
            continue
        if not isinstance(task, dict):
            continue
        if task.get("status") != "completed":
            continue
        if not task.get("official_video"):
            continue
        sel_path = task_path.parent / "selected_projects.json"
        if not sel_path.exists():
            continue
        try:
            sel = read_json(sel_path, {})
        except Exception:
            continue
        if not isinstance(sel, dict):
            continue
        for item in sel.get("items", []):
            if not isinstance(item, dict):
                continue
            full = item.get("full_name")
            if full:
                published.add(full)
    return published
