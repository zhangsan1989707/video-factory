"""File-backed storage for the local console."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.config import OUTPUT_DIR, ROOT_DIR


CONFIG_DIR = ROOT_DIR / ".config" / "video-console"
JOBS_DIR = OUTPUT_DIR / "jobs"


DEFAULT_PROVIDERS = {
    "providers": [
        {
            "id": "openai",
            "name": "OpenAI",
            "type": "openai",
            "api_key": "",
            "base_url": "",
            "default_model": "gpt-4.1-mini",
            "enabled": False,
            "last_test": "未测试",
        },
        {
            "id": "anthropic",
            "name": "Anthropic",
            "type": "anthropic",
            "api_key": "",
            "base_url": "",
            "default_model": "claude-sonnet-4-5",
            "enabled": False,
            "last_test": "未测试",
        },
        {
            "id": "deepseek",
            "name": "DeepSeek",
            "type": "openai-compatible",
            "api_key": "",
            "base_url": "https://api.deepseek.com",
            "default_model": "deepseek-chat",
            "enabled": False,
            "last_test": "未测试",
        },
        {
            "id": "xiaomi",
            "name": "小米",
            "type": "openai-compatible",
            "api_key": "",
            "base_url": "",
            "default_model": "",
            "enabled": False,
            "last_test": "未测试",
        },
    ]
}

DEFAULT_MODEL_ROUTING = {
    "candidate_analysis": {"provider": "deepseek", "model": "deepseek-chat"},
    "hotlist_ranking": {"provider": "deepseek", "model": "deepseek-chat"},
    "hook_generation": {"provider": "openai", "model": "gpt-4.1-mini"},
    "feature_extraction": {"provider": "deepseek", "model": "deepseek-chat"},
    "narration_generation": {"provider": "openai", "model": "gpt-4.1-mini"},
    "script_polishing": {"provider": "deepseek", "model": "deepseek-chat"},
    "fact_check": {"provider": "deepseek", "model": "deepseek-chat"},
}

DEFAULT_GITHUB = {"token": "", "last_rate_limit": "未检测"}

DEFAULT_SCHEDULER = {
    "enabled": False,
    "frequency": "daily",
    "time": "09:00",
    "time_window": "daily",
    "project_count": 10,
    "template_params": {},
    "last_run_date": "",
}

DEFAULT_TEMPLATES = {
    "active_template": "github_hotlist_vertical_v1",
    "github_hotlist_vertical_v1": {
        "project_count": 10,
        "style": "tech_hotspot",
        "render_engine": "hyperframes",
        "subtitle_mode": "large_hook",
        "bgm": "default",
        "narration_tone": "professional_review",
        "orientation": "vertical",
    },
}

CONFIG_FILES = {
    "providers": "providers.json",
    "model-routing": "model-routing.json",
    "github": "github.json",
    "templates": "templates.json",
    "scheduler": "scheduler.json",
}
JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def ensure_storage() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_json("providers.json", DEFAULT_PROVIDERS)
    _ensure_json("model-routing.json", DEFAULT_MODEL_ROUTING)
    _ensure_json("github.json", DEFAULT_GITHUB)
    _ensure_json("templates.json", DEFAULT_TEMPLATES)
    _ensure_json("scheduler.json", DEFAULT_SCHEDULER)


def _ensure_json(name: str, default: dict[str, Any]) -> None:
    path = CONFIG_DIR / name
    if not path.exists():
        write_json(path, default)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return _default_copy(default)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _default_copy(default)
    if isinstance(default, dict) and not isinstance(data, dict):
        return _default_copy(default)
    if isinstance(default, list) and not isinstance(data, list):
        return _default_copy(default)
    return data


def _default_copy(default: Any) -> Any:
    if isinstance(default, (dict, list)):
        return json.loads(json.dumps(default, ensure_ascii=False))
    return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def config_snapshot() -> dict[str, Any]:
    ensure_storage()
    return {
        "providers": _redacted_providers(),
        "model_routing": read_json(CONFIG_DIR / "model-routing.json", DEFAULT_MODEL_ROUTING),
        "github": _redacted_github(),
        "templates": _normalize_templates(read_json(CONFIG_DIR / "templates.json", DEFAULT_TEMPLATES)),
        "scheduler": _normalize_scheduler(read_json(CONFIG_DIR / "scheduler.json", DEFAULT_SCHEDULER)),
        "config_dir": str(CONFIG_DIR),
        "jobs_dir": str(JOBS_DIR),
    }


def read_github_token() -> str:
    ensure_storage()
    data = read_json(CONFIG_DIR / "github.json", DEFAULT_GITHUB)
    return str(data.get("token") or "")


def update_github_rate_limit(last_rate_limit: str) -> None:
    ensure_storage()
    data = read_json(CONFIG_DIR / "github.json", DEFAULT_GITHUB)
    data["last_rate_limit"] = last_rate_limit or "未检测"
    write_json(CONFIG_DIR / "github.json", data)


def update_scheduler_last_run(last_run_date: str) -> dict[str, Any]:
    ensure_storage()
    data = _normalize_scheduler(read_json(CONFIG_DIR / "scheduler.json", DEFAULT_SCHEDULER), preserve_last_run=False)
    data["last_run_date"] = str(last_run_date or "")
    write_json(CONFIG_DIR / "scheduler.json", data)
    return config_snapshot()


def update_config(name: str, data: dict[str, Any]) -> dict[str, Any]:
    ensure_storage()
    filename, normalized = _normalized_config_update(name, data)
    write_json(CONFIG_DIR / filename, normalized)
    return config_snapshot()


def update_configs(items: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for name, data in items.items():
        _validate_config_update_shape(name, data)
    ensure_storage()
    normalized: list[tuple[str, dict[str, Any]]] = []
    for name, data in items.items():
        filename, item = _normalized_config_update(name, data)
        normalized.append((filename, item))
    backups = {filename: _file_backup(CONFIG_DIR / filename) for filename, _item in normalized}
    try:
        for filename, item in normalized:
            write_json(CONFIG_DIR / filename, item)
    except Exception:
        for filename, backup in backups.items():
            _restore_file_backup(CONFIG_DIR / filename, backup)
        raise
    return config_snapshot()


def normalize_model_name(provider_id: str, model: str) -> str:
    value = str(model or "").strip()
    if provider_id != "xiaomi":
        return value
    aliases = {
        "MiMo-V2.5-Pro": "mimo-v2.5-pro",
        "mimo-v2-pro": "mimo-v2.5-pro",
    }
    return aliases.get(value, value)


def _normalized_config_update(name: str, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    _validate_config_update_shape(name, data)
    if name == "providers":
        data = _merge_provider_secrets(data)
    if name == "model-routing":
        data = _normalize_model_routing(data)
    if name == "github":
        data = _merge_github_secret(data)
    if name == "scheduler":
        data = _normalize_scheduler(data)
    if name == "templates":
        data = _normalize_templates(data)
    return CONFIG_FILES[name], data


def _validate_config_update_shape(name: str, data: Any) -> None:
    if name not in CONFIG_FILES:
        raise ValueError(f"未知配置: {name}")
    if not isinstance(data, dict):
        raise ValueError(f"配置必须是对象: {name}")


def _file_backup(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.exists() and path.is_file() else None
    except OSError:
        return None


def _restore_file_backup(path: Path, backup: bytes | None) -> None:
    try:
        if backup is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(backup)
    except OSError:
        pass


def update_provider_test_result(provider_id: str, message: str) -> dict[str, Any]:
    ensure_storage()
    data = read_json(CONFIG_DIR / "providers.json", DEFAULT_PROVIDERS)
    found = False
    for provider in _provider_items(data):
        if provider.get("id") == provider_id:
            provider["last_test"] = message
            found = True
            break
    if not found:
        raise ValueError(f"未知供应商: {provider_id}")
    write_json(CONFIG_DIR / "providers.json", data)
    return config_snapshot()


def provider_connection_matches_saved(provider_id: str, provider_config: dict[str, Any] | None) -> bool:
    if not provider_config:
        return True
    data = read_json(CONFIG_DIR / "providers.json", DEFAULT_PROVIDERS)
    saved = next((provider for provider in _provider_items(data) if provider.get("id") == provider_id), None)
    if not saved:
        return False
    candidate = dict(saved)
    candidate.update(provider_config)
    if not provider_config.get("api_key"):
        candidate["api_key"] = saved.get("api_key", "")
    return not _provider_connection_changed(saved, candidate)


def next_job_id(prefix: str = "GH-HOTLIST") -> str:
    ensure_storage()
    today = datetime.now().strftime("%Y%m%d")
    existing = sorted(JOBS_DIR.glob(f"{prefix}-{today}-*"))
    numbers = []
    for path in existing:
        parts = path.name.split("-")
        if len(parts) >= 4 and parts[2] == today:
            try:
                numbers.append(int(parts[3]))
            except ValueError:
                pass
    return f"{prefix}-{today}-{(max(numbers) + 1 if numbers else 1):03d}"


def create_job(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _validate_job_id(job_id)
    job_dir = JOBS_DIR / job_id
    if job_dir.exists():
        raise ValueError(f"任务目录已存在: {job_id}")
    job_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    template = _normalize_job_template(str(payload.get("template") or "github_hotlist_vertical_v1"), payload.get("template_params") or {})
    job = {
        "id": job_id,
        "type": "github_hotlist",
        "status": "draft_pending",
        "stage": "draft_pending",
        "created_at": now,
        "updated_at": now,
        "title": payload.get("title") or "GitHub 热榜视频",
        "time_window": normalize_time_window(payload.get("time_window"), "weekly"),
        "template": template["name"],
        "template_params": template["params"],
        "project_count": normalize_project_count(payload.get("project_count")),
        "job_dir": str(job_dir),
        "official_video": "",
        "error": "",
        "failed_stage": "",
        "plan_validation": {"status": "not_run", "error": ""},
        "model_calls": [],
        "stage_history": [
            {"stage": "draft_pending", "status": "draft_pending", "at": now}
        ],
    }
    write_json(job_dir / "task.json", job)
    append_log(job_id, "任务已创建，等待生成候选草稿。")
    return job


def _normalize_job_template(template_name: str, params: Any) -> dict[str, Any]:
    active = template_name if template_name in _template_names(DEFAULT_TEMPLATES) else str(DEFAULT_TEMPLATES["active_template"])
    normalized = _normalize_templates({
        "active_template": active,
        active: params if isinstance(params, dict) else {},
    })
    return {"name": active, "params": normalized[active]}


def read_job(job_id: str) -> dict[str, Any]:
    if not _valid_job_id(job_id):
        return {}
    path = JOBS_DIR / job_id / "task.json"
    if path.is_symlink():
        return {}
    return read_json(path, {})


def update_job(job_id: str, **changes: Any) -> dict[str, Any]:
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    previous_stage = job.get("stage")
    previous_status = job.get("status")
    job.update(changes)
    now = datetime.now().isoformat(timespec="seconds")
    job["updated_at"] = now
    if "stage" in changes or "status" in changes:
        if job.get("stage") != previous_stage or job.get("status") != previous_status:
            history = job.get("stage_history") or []
            history.append({
                "stage": job.get("stage", ""),
                "status": job.get("status", ""),
                "at": now,
            })
            job["stage_history"] = history[-80:]
    write_json(JOBS_DIR / job_id / "task.json", job)
    return job


def append_model_call(job_id: str, call: dict[str, Any]) -> dict[str, Any]:
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    route = call.get("route") or {}
    entry = {
        "task": str(call.get("task") or ""),
        "provider": str(route.get("provider_name") or route.get("provider") or call.get("provider") or ""),
        "model": str(route.get("model") or call.get("model") or ""),
        "status": str(call.get("status") or ""),
        "error": str(call.get("error") or ""),
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    calls = job.get("model_calls") or []
    calls.append(entry)
    job["model_calls"] = calls[-80:]
    job["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(JOBS_DIR / job_id / "task.json", job)
    return job


def list_jobs() -> list[dict[str, Any]]:
    ensure_storage()
    jobs = []
    for task_path in JOBS_DIR.glob("*/task.json"):
        if task_path.is_symlink():
            continue
        job = read_json(task_path, {})
        if str(job.get("id") or "") != task_path.parent.name:
            continue
        jobs.append(job)
    return sorted(jobs, key=lambda job: (str(job.get("updated_at") or ""), str(job.get("id") or "")), reverse=True)


def delete_job(job_id: str) -> dict[str, Any]:
    _validate_job_id(job_id)
    job = read_job(job_id)
    if not job or str(job.get("id") or "") != job_id:
        raise ValueError(f"任务不存在: {job_id}")
    job_dir = JOBS_DIR / job_id
    jobs_root = JOBS_DIR.resolve()
    if job_dir.is_symlink():
        raise ValueError(f"任务目录不是普通目录: {job_id}")
    resolved = job_dir.resolve()
    if jobs_root not in resolved.parents or not resolved.is_dir():
        raise ValueError(f"任务目录不存在: {job_id}")
    shutil.rmtree(resolved)
    return {"ok": True, "job_id": job_id}


def append_log(job_id: str, message: str) -> None:
    _validate_job_id(job_id)
    log_path = JOBS_DIR / job_id / "logs.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.is_symlink():
        raise ValueError(f"日志文件不是普通文件: {job_id}")
    stamp = datetime.now().strftime("%H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")


def read_log(job_id: str) -> str:
    if not _valid_job_id(job_id):
        return ""
    path = JOBS_DIR / job_id / "logs.txt"
    if not path.exists() or path.is_symlink():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def read_log_tail(job_id: str, line_count: int = 20) -> str:
    lines = read_log(job_id).splitlines()
    if not lines:
        return ""
    return "\n".join(lines[-line_count:])


def job_artifacts(job_id: str) -> dict[str, Any]:
    if not _valid_job_id(job_id):
        return {"job_id": job_id, "job_dir": str(JOBS_DIR / "_invalid_job_id_"), "files": []}
    job_dir = JOBS_DIR / job_id
    files = []
    if job_dir.exists():
        for path in sorted(job_dir.rglob("*")):
            try:
                is_file = path.is_file()
                is_symlink = path.is_symlink()
                stat = path.stat() if is_file and not is_symlink else None
                size = stat.st_size if stat else 0
                mtime = int(stat.st_mtime) if stat else 0
            except OSError:
                continue
            if is_file and not is_symlink:
                name = str(path.relative_to(job_dir))
                if not _is_hidden_artifact(name):
                    files.append({"name": name, "path": str(path), "size": size, "mtime": mtime})
    return {"job_id": job_id, "job_dir": str(job_dir), "files": files}


def _is_hidden_artifact(name: str) -> bool:
    return any(part.startswith(".") for part in Path(name).parts)


def _valid_job_id(job_id: str) -> bool:
    value = str(job_id or "")
    return bool(JOB_ID_RE.fullmatch(value)) and not any(part in {"", ".", ".."} or part.startswith(".") for part in Path(value).parts)


def _validate_job_id(job_id: str) -> None:
    if not _valid_job_id(job_id):
        raise ValueError(f"非法任务编号: {job_id}")


def _redacted_github() -> dict[str, Any]:
    data = read_json(CONFIG_DIR / "github.json", DEFAULT_GITHUB)
    token = str(data.get("token") or "")
    return {
        "configured": bool(token),
        "token_preview": f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else "",
        "last_rate_limit": data.get("last_rate_limit", "未检测"),
    }


def _redacted_providers() -> dict[str, Any]:
    data = read_json(CONFIG_DIR / "providers.json", DEFAULT_PROVIDERS)
    providers = []
    for provider in _provider_items(data):
        item = dict(provider)
        api_key = str(item.get("api_key") or "")
        item["configured"] = bool(api_key)
        item["enabled"] = bool_value(item.get("enabled"))
        item["available"] = bool(item["enabled"] and api_key and str(item.get("last_test") or "").startswith("连接成功"))
        item["api_key"] = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) >= 8 else ""
        providers.append(item)
    return {"providers": providers}


def _merge_provider_secrets(data: dict[str, Any]) -> dict[str, Any]:
    current = read_json(CONFIG_DIR / "providers.json", DEFAULT_PROVIDERS)
    current_by_id = {item.get("id"): item for item in _provider_items(current)}
    incoming_by_id = {item.get("id"): item for item in _provider_items(data)}
    providers = []
    for default_provider in DEFAULT_PROVIDERS["providers"]:
        provider_id = default_provider.get("id")
        previous = current_by_id.get(provider_id, {})
        incoming = incoming_by_id.get(provider_id, {})
        incoming_key = incoming.get("api_key", previous.get("api_key", default_provider.get("api_key", "")))
        if _is_redacted_secret(str(incoming_key or ""), str(previous.get("api_key") or "")):
            incoming_key = previous.get("api_key", "")
        item = {
            **default_provider,
            "api_key": incoming_key,
            "base_url": incoming.get("base_url", previous.get("base_url", default_provider.get("base_url", ""))),
            "default_model": normalize_model_name(
                str(provider_id or ""),
                incoming.get("default_model", previous.get("default_model", default_provider.get("default_model", ""))),
            ),
            "enabled": bool_value(incoming.get("enabled", previous.get("enabled", default_provider.get("enabled", False)))),
            "last_test": incoming.get("last_test", previous.get("last_test", default_provider.get("last_test", "未测试"))),
        }
        if not item.get("api_key"):
            item["api_key"] = previous.get("api_key", "")
        if _provider_connection_changed(previous, item):
            item["last_test"] = "未测试"
        providers.append(item)
    return {"providers": providers}


def _is_redacted_secret(candidate: str, secret: str) -> bool:
    return bool(secret and len(secret) >= 8 and candidate == f"{secret[:4]}...{secret[-4:]}")


def _provider_connection_changed(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if not previous:
        return False
    for key in ("api_key", "base_url", "default_model", "enabled"):
        if key == "enabled":
            if bool_value(previous.get(key)) != bool_value(current.get(key)):
                return True
            continue
        if previous.get(key) != current.get(key):
            return True
    return False


def bool_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _merge_github_secret(data: dict[str, Any]) -> dict[str, Any]:
    current = read_json(CONFIG_DIR / "github.json", DEFAULT_GITHUB)
    token = str(data.get("token") or "")
    if not token or _is_redacted_secret(token, str(current.get("token") or "")):
        data["token"] = current.get("token", "")
    data["last_rate_limit"] = current.get("last_rate_limit", "未检测")
    return data


def _normalize_scheduler(data: dict[str, Any], preserve_last_run: bool = True) -> dict[str, Any]:
    current = read_json(CONFIG_DIR / "scheduler.json", DEFAULT_SCHEDULER) if preserve_last_run else {}
    item = dict(data)
    item["enabled"] = bool_value(item.get("enabled"))
    if item.get("frequency") not in {"daily", "weekly"}:
        item["frequency"] = DEFAULT_SCHEDULER["frequency"]
    item["time_window"] = normalize_time_window(item.get("time_window"), DEFAULT_SCHEDULER["time_window"])
    if not _valid_hhmm(str(item.get("time") or "")):
        item["time"] = DEFAULT_SCHEDULER["time"]
    item["project_count"] = normalize_project_count(item.get("project_count"))
    if not isinstance(item.get("template_params"), dict):
        item["template_params"] = {}
    item["last_run_date"] = str((current if preserve_last_run else item).get("last_run_date") or "")
    return item


def _normalize_templates(data: dict[str, Any]) -> dict[str, Any]:
    default_name = str(DEFAULT_TEMPLATES["active_template"])
    active = str(data.get("active_template") or default_name)
    if active not in _template_names(DEFAULT_TEMPLATES):
        active = default_name
    item = dict(DEFAULT_TEMPLATES)
    template = data.get(active) if isinstance(data.get(active), dict) else {}
    if "style" not in template and template.get("visual_style"):
        template = {**template, "style": template.get("visual_style")}
    if template.get("style") == "tech_dark" and not template.get("render_engine"):
        template = {**template, "style": "tech_hotspot"}
    has_render_engine = "render_engine" in template
    merged = dict(DEFAULT_TEMPLATES[active])
    for key in ("project_count", "style", "render_engine", "subtitle_mode", "bgm", "narration_tone", "orientation", "bgm_path"):
        if key in template:
            merged[key] = template[key]
    merged["project_count"] = normalize_project_count(merged.get("project_count"))
    if merged.get("style") not in {"tech_hotspot", "tech_dark", "minimal_white", "black_gold"}:
        merged["style"] = DEFAULT_TEMPLATES[active]["style"]
    if not has_render_engine:
        merged["render_engine"] = "hyperframes" if merged.get("style") == "tech_hotspot" else "pil"
    elif merged.get("render_engine") not in {"hyperframes", "pil"}:
        merged["render_engine"] = "hyperframes" if merged.get("style") == "tech_hotspot" else "pil"
    if merged.get("subtitle_mode") not in {"large_hook", "standard"}:
        merged["subtitle_mode"] = DEFAULT_TEMPLATES[active]["subtitle_mode"]
    if merged.get("bgm") not in {"default", "none", "custom"}:
        merged["bgm"] = DEFAULT_TEMPLATES[active]["bgm"]
    if merged.get("narration_tone") not in {"professional_review", "short_video_hook", "calm_analysis"}:
        merged["narration_tone"] = DEFAULT_TEMPLATES[active]["narration_tone"]
    merged["orientation"] = "vertical"
    merged["bgm_path"] = str(merged.get("bgm_path") or "")
    item["active_template"] = active
    item[active] = merged
    return item


def _template_names(templates: dict[str, Any]) -> set[str]:
    return {name for name, value in templates.items() if name != "active_template" and isinstance(value, dict)}


def _valid_hhmm(value: str) -> bool:
    try:
        hour, minute = [int(part) for part in value.split(":", 1)]
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _normalize_model_routing(data: dict[str, Any]) -> dict[str, dict[str, str]]:
    providers = _provider_items(read_json(CONFIG_DIR / "providers.json", DEFAULT_PROVIDERS))
    provider_ids = {str(provider.get("id") or "") for provider in providers}
    routing: dict[str, dict[str, str]] = {}
    for task, default_route in DEFAULT_MODEL_ROUTING.items():
        candidate = data.get(task) if isinstance(data, dict) else {}
        provider_id = str((candidate or {}).get("provider") or "")
        model = normalize_model_name(provider_id, str((candidate or {}).get("model") or ""))
        if provider_id in provider_ids and model:
            routing[task] = {"provider": provider_id, "model": model}
        else:
            routing[task] = dict(default_route)
    return routing


def _provider_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    providers = data.get("providers", [])
    if not isinstance(providers, list):
        return []
    return [item for item in providers if isinstance(item, dict) and item.get("id")]


def normalize_project_count(value: Any) -> int:
    try:
        count = int(value or 10)
    except (TypeError, ValueError):
        return 10
    return 5 if count <= 5 else 10


def normalize_time_window(value: Any, default: str = "daily") -> str:
    candidate = str(value or default)
    return candidate if candidate in {"daily", "weekly", "monthly"} else default
