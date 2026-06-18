"""Optional Lark Base sync for confirmed hotlist selections."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from typing import Any

from src.console.store import CONFIG_DIR, DEFAULT_LARK, read_json


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
