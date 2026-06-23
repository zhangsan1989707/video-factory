"""Local HTTP server for the video factory console."""

from __future__ import annotations
import json
import mimetypes
import re
import subprocess
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from src.console.background import is_active, request_cancel, start_async_job
from src.console.model_router import test_provider
from src.console.preflight import preflight_snapshot, run_real_smoke_check
from src.console.scheduler import run_due_scheduled_draft, start_scheduler_loop
from src.console.jobs import (
    create_desktop_review_job,
    create_from_plan_render_job,
    create_hotlist_job,
    create_single_project_vertical_job,
    finalize_numbered_output,
    generate_candidates,
    job_detail,
    prepare_plan,
    regenerate_candidates,
    regenerate_script,
    render_video,
    reset_video_for_regeneration,
    save_script,
    save_selection,
    validate_plan,
)
from src.console.store import (
    JOBS_DIR,
    append_log,
    batch_delete_jobs,
    config_snapshot,
    delete_job,
    delete_preset,
    ensure_storage,
    job_artifacts,
    list_jobs,
    list_presets,
    provider_connection_matches_saved,
    read_job,
    read_log,
    recover_hanging_jobs,
    save_preset,
    update_config,
    update_configs,
    update_job,
    update_provider_test_result,
    summarize_jobs_model_usage,
)


MAX_REQUEST_BODY_BYTES = 256 * 1024  # 256 KB

STATIC_DIR = Path(__file__).parent / "static"


def _safe_path(base_dir: Path, user_path: str) -> Path | None:
    """验证路径安全，防止目录遍历攻击"""
    resolved = (base_dir / user_path).resolve()
    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError:
        return None
    if resolved.is_symlink():
        return None
    if not resolved.exists():
        return None
    return resolved


def run_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    ensure_storage()
    recover_hanging_jobs()
    start_scheduler_loop()
    server = ThreadingHTTPServer((host, port), ConsoleHandler)
    url = f"http://{host}:{port}"
    print(f"Video Factory Console running at {url}")
    if open_browser:
        webbrowser.open(url)
    server.serve_forever()


class ConsoleHandler(BaseHTTPRequestHandler):
    server_version = "VideoFactoryConsole/0.1"

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; script-src 'self' https://cdn.jsdelivr.net")
        super().end_headers()

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/jobs/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 5 and parts[3] == "artifacts":
                path = self._job_artifact_path(parts[2], "/".join(parts[4:]))
                if path and path.exists() and path.is_file():
                    self.send_response(200)
                    self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                    self.send_header("Content-Length", str(path.stat().st_size))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return
        path = self._static_path(parsed.path)
        if path:
            if path.exists() and path.is_file():
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(path.stat().st_size))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_file(STATIC_DIR / "index.html")
            return
        static_path = self._static_path(parsed.path)
        if static_path:
            self._send_file(static_path)
            return
        if parsed.path == "/api/health":
            self._json({"ok": True, "service": "video-factory-console"})
            return
        if parsed.path == "/api/preflight":
            self._json(preflight_snapshot())
            return
        if parsed.path == "/api/config":
            self._json(config_snapshot())
            return
        if parsed.path == "/api/presets":
            self._json({"presets": list_presets()})
            return
        if parsed.path == "/api/jobs":
            jobs = reconcile_running_jobs(list_jobs())
            self._json({"jobs": jobs, "model_usage": summarize_jobs_model_usage(jobs)})
            return
        if parsed.path.startswith("/api/jobs/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 3:
                job_id = parts[2]
                if len(parts) == 3:
                    if not self._job_exists(job_id):
                        self._not_found()
                        return
                    reconcile_running_job(job_id)
                    self._json(job_detail(job_id))
                    return
                if len(parts) == 4 and parts[3] == "logs":
                    if not self._job_exists(job_id):
                        self._not_found()
                        return
                    self._json({"job_id": job_id, "logs": read_log(job_id)})
                    return
                if len(parts) == 4 and parts[3] == "artifacts":
                    if not self._job_exists(job_id):
                        self._not_found()
                        return
                    self._json(job_artifacts(job_id))
                    return
                if len(parts) >= 5 and parts[3] == "artifacts":
                    self._send_job_artifact(job_id, "/".join(parts[4:]))
                    return
        self._not_found()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/config":
                name = parse_qs(parsed.query).get("name", [""])[0]
                self._json(update_config(name, payload) if name else update_configs(payload))
                return
            if parsed.path == "/api/preflight/smoke":
                self._json(run_real_smoke_check())
                return
            if parsed.path == "/api/jobs":
                job_type = str(payload.get("type") or "github_hotlist")
                creators = {
                    "github_hotlist": create_hotlist_job,
                    "single_project_vertical": create_single_project_vertical_job,
                    "desktop_review": create_desktop_review_job,
                    "from_plan_render": create_from_plan_render_job,
                }
                creator = creators.get(job_type)
                if creator is None:
                    raise ValueError(f"未知任务类型: {job_type}")
                self._json({"job": creator(payload)})
                return
            if parsed.path == "/api/jobs/batch-delete":
                self._json(batch_delete_jobs(payload.get("job_ids") or []))
                return
            if parsed.path == "/api/scheduler/run-due":
                self._json(run_due_scheduled_draft(force=bool(payload.get("force"))))
                return
            if parsed.path == "/api/presets":
                self._json(save_preset(str(payload.get("name") or ""), payload.get("params") or {}))
                return
            if parsed.path.startswith("/api/presets/"):
                parts = parsed.path.strip("/").split("/")
                if len(parts) == 4 and parts[3] == "apply":
                    preset_id = parts[2]
                    presets = list_presets()
                    preset = next((p for p in presets if p.get("id") == preset_id), None)
                    if not preset:
                        self._not_found()
                        return
                    self._json({"preset": preset, "ok": True})
                    return
            if parsed.path.startswith("/api/providers/"):
                parts = parsed.path.strip("/").split("/")
                if len(parts) == 4 and parts[3] == "test":
                    provider = payload.get("provider") or None
                    ok, message = test_provider(parts[2], str(payload.get("model") or ""), provider)
                    status_text = f"{'连接成功' if ok else '连接失败'}: {_short_message(message)}"
                    saved = provider_connection_matches_saved(parts[2], provider)
                    config = update_provider_test_result(parts[2], status_text) if saved else config_snapshot()
                    self._json({
                        "ok": ok,
                        "message": status_text,
                        "saved": saved,
                        "config": config,
                    })
                    return
            if parsed.path.startswith("/api/jobs/"):
                parts = parsed.path.strip("/").split("/")
                if len(parts) == 4:
                    job_id = parts[2]
                    action = parts[3]
                    if action == "candidates":
                        self._json(start_candidates_job(job_id))
                        return
                    if action == "refresh-candidates":
                        self._json(start_refresh_candidates_job(job_id))
                        return
                    if action == "regenerate-candidates":
                        self._json(start_regenerate_candidates_job(job_id))
                        return
                    if action == "selection":
                        self._json(start_selection_job(job_id, payload))
                        return
                    if action == "regenerate-script":
                        self._json(start_regenerate_script_job(job_id))
                        return
                    if action == "script":
                        self._json(start_save_script_job(job_id, payload))
                        return
                    if action == "prepare-plan":
                        self._json(start_prepare_plan_job(job_id))
                        return
                    if action == "validate-plan":
                        self._json(start_validate_plan_job(job_id))
                        return
                    if action == "render-video":
                        self._json(start_render_job(job_id))
                        return
                    if action == "regenerate-video":
                        self._json(start_regenerate_render_job(job_id))
                        return
                    if action == "cancel":
                        self._json(cancel_active_job(job_id))
                        return
                    if action == "open-folder":
                        self._json(open_job_folder(job_id))
                        return
                    if action == "finalize":
                        self._json(finalize_numbered_output(job_id, str(payload.get("title") or "")))
                        return
            self._not_found()
        except (json.JSONDecodeError, ValueError) as exc:
            self._json({"error": str(exc)}, status=_error_status(exc))
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/presets/"):
                parts = parsed.path.strip("/").split("/")
                if len(parts) == 3:
                    self._json(delete_preset(parts[2]))
                    return
            if parsed.path.startswith("/api/jobs/"):
                parts = parsed.path.strip("/").split("/")
                if len(parts) == 3:
                    job_id = parts[2]
                    if not self._job_exists(job_id):
                        self._not_found()
                        return
                    if is_active(job_id):
                        raise ValueError("任务正在运行，不能删除")
                    self._json(delete_job(job_id))
                    return
            self._not_found()
        except ValueError as exc:
            self._json({"error": str(exc)}, status=_error_status(exc))
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        print(f"{self.address_string()} - {format % args}")

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            raise ValueError("Content-Length must be a non-negative integer")
        if length < 0:
            raise ValueError("Content-Length must be a non-negative integer")
        if length > MAX_REQUEST_BODY_BYTES:
            raise ValueError(f"请求体过大，最大允许 {MAX_REQUEST_BODY_BYTES // 1024} KB")
        if not length:
            return {}
        try:
            raw = self.rfile.read(length).decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("JSON body must be UTF-8 encoded") from None
        payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._not_found()
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_job_artifact(self, job_id: str, encoded_name: str) -> None:
        path = self._job_artifact_path(job_id, encoded_name)
        if not path:
            self._not_found()
            return
        self._send_file(path)

    def _job_artifact_path(self, job_id: str, encoded_name: str) -> Path | None:
        if not self._job_exists(job_id):
            return None
        name = unquote(encoded_name)
        if "\\" in name or any(part.startswith(".") for part in Path(name).parts):
            return None
        job_dir = (JOBS_DIR / job_id).resolve()
        path = _safe_path(job_dir, name)
        if path is None or not path.is_file():
            return None
        return path

    def _not_found(self) -> None:
        self._json({"error": "not found"}, status=404)

    def _job_exists(self, job_id: str) -> bool:
        job = read_job(job_id)
        return str(job.get("id") or "") == job_id

    def _static_path(self, request_path: str) -> Path | None:
        if request_path == "/":
            return STATIC_DIR / "index.html"
        if request_path.startswith("/static/"):
            return self._safe_static_file(request_path.removeprefix("/static/"))
        if request_path in ("/styles.css", "/app.js"):
            return self._safe_static_file(request_path.removeprefix("/"))
        return None

    def _safe_static_file(self, name: str) -> Path | None:
        decoded = unquote(name)
        if "\\" in decoded:
            return None
        return _safe_path(STATIC_DIR, decoded)


def _short_message(message: str, limit: int = 160) -> str:
    text = _redact_message_secrets(" ".join(str(message).split()))
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _redact_message_secrets(message: str) -> str:
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[redacted]", message)
    return re.sub(r"(api key:\s*)\*+[A-Za-z0-9_-]+", r"\1[redacted]", text, flags=re.IGNORECASE)


def _error_status(exc: Exception) -> int:
    message = str(exc)
    return 404 if message.startswith(("任务不存在:", "任务目录不存在:")) else 400


def start_render_job(job_id: str) -> dict:
    job = job_detail(job_id)["job"]
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    if str(job.get("stage") or "") not in {
        "preparing_plan",
        "capturing_assets",
        "generating_tts",
        "composing_video",
        "composing_html",
        "rendering_hyperframes",
        "mixing_audio",
        "post_processing",
    }:
        raise ValueError(f"当前阶段不能生成最终视频: {job.get('stage') or 'unknown'}")
    started = start_async_job(job_id, render_video, on_error=record_render_background_failure)
    if not started:
        raise ValueError("已有渲染任务正在运行")
    job = job_detail(job_id)["job"]
    return {"started": started, "active": is_active(job_id), "job": job}


def start_candidates_job(job_id: str) -> dict:
    job = _ensure_job_exists(job_id)
    if str(job.get("stage") or "") not in {"draft_pending", "collecting_candidates", "analyzing_candidates", "awaiting_project_confirmation"}:
        raise ValueError(f"当前阶段不能生成候选项目: {job.get('stage') or 'unknown'}")

    async def worker(_job_id: str) -> None:
        await generate_candidates(_job_id)

    return _start_background_action(job_id, worker, "后台候选任务失败")


def start_refresh_candidates_job(job_id: str) -> dict:
    job = _ensure_job_exists(job_id)
    if str(job.get("stage") or "") not in {"draft_pending", "collecting_candidates", "analyzing_candidates", "awaiting_project_confirmation"}:
        raise ValueError(f"当前阶段不能刷新候选: {job.get('stage') or 'unknown'}")
    if str(job.get("status") or "") == "running":
        raise ValueError("任务运行中，不能刷新")

    async def worker(_job_id: str) -> None:
        await generate_candidates(_job_id, force_refresh=True)

    return _start_background_action(job_id, worker, "后台刷新候选任务失败")


def start_regenerate_candidates_job(job_id: str) -> dict:
    job = _ensure_job_exists(job_id)
    if str(job.get("status") or "") == "running":
        raise ValueError("任务运行中，不能重新生成")

    async def worker(_job_id: str) -> None:
        await regenerate_candidates(_job_id)

    return _start_background_action(job_id, worker, "后台候选重生成任务失败")


def start_selection_job(job_id: str, payload: dict) -> dict:
    job = _ensure_job_exists(job_id)
    if str(job.get("stage") or "") not in {"awaiting_project_confirmation", "generating_script"}:
        raise ValueError(f"当前阶段不能确认项目: {job.get('stage') or 'unknown'}")
    items = payload.get("items") or []
    if not items:
        raise ValueError("至少需要选择 1 个项目")

    async def worker(_job_id: str) -> None:
        save_selection(_job_id, payload)

    return _start_background_action(job_id, worker, "后台项目确认任务失败")


def start_regenerate_script_job(job_id: str) -> dict:
    job = _ensure_job_exists(job_id)
    if str(job.get("status") or "") == "running":
        raise ValueError("任务运行中，不能重新生成")

    async def worker(_job_id: str) -> None:
        regenerate_script(_job_id)

    return _start_background_action(job_id, worker, "后台口播重生成任务失败")


def start_save_script_job(job_id: str, payload: dict) -> dict:
    job = _ensure_job_exists(job_id)
    if str(job.get("stage") or "") not in {"awaiting_script_confirmation", "preparing_plan"}:
        raise ValueError(f"当前阶段不能确认口播: {job.get('stage') or 'unknown'}")
    segments = payload.get("segments") or []
    if not segments:
        raise ValueError("口播脚本不能为空")

    async def worker(_job_id: str) -> None:
        save_script(_job_id, payload)

    return _start_background_action(job_id, worker, "后台口播确认任务失败")


def start_prepare_plan_job(job_id: str) -> dict:
    job = _ensure_job_exists(job_id)
    if str(job.get("stage") or "") != "preparing_plan":
        raise ValueError(f"当前阶段不能生成计划文件: {job.get('stage') or 'unknown'}")
    if str(job.get("status") or "") not in {"awaiting_render", "awaiting_validation", "ready_to_render", "failed"}:
        raise ValueError(f"当前状态不能生成计划文件: {job.get('status') or 'unknown'}")

    async def worker(_job_id: str) -> None:
        import asyncio

        await asyncio.to_thread(prepare_plan, _job_id)

    return _start_background_action(job_id, worker, "后台计划生成任务失败")


def start_validate_plan_job(job_id: str) -> dict:
    job = _ensure_job_exists(job_id)
    if str(job.get("stage") or "") != "preparing_plan":
        raise ValueError(f"当前阶段不能校验计划文件: {job.get('stage') or 'unknown'}")

    async def worker(_job_id: str) -> None:
        await validate_plan(_job_id)

    return _start_background_action(job_id, worker, "后台计划校验任务失败")


def start_regenerate_render_job(job_id: str) -> dict:
    reset_video_for_regeneration(job_id)
    return start_render_job(job_id)


def record_render_background_failure(job_id: str, exc: Exception) -> None:
    job = read_job(job_id)
    if not job or str(job.get("status") or "") == "failed":
        return
    failed_stage = str(job.get("stage") or "preparing_plan")
    message = f"后台渲染任务失败: {exc}"
    append_log(job_id, message)
    update_job(job_id, status="failed", failed_stage=failed_stage, error=str(exc))


def _start_background_action(
    job_id: str,
    worker,
    failure_prefix: str,
) -> dict:
    started = start_async_job(job_id, worker, on_error=lambda failed_id, exc: record_background_failure(failed_id, exc, failure_prefix))
    if not started:
        raise ValueError("已有后台任务正在运行")
    return {"started": started, "active": is_active(job_id), "job": job_detail(job_id)["job"]}


def record_background_failure(job_id: str, exc: Exception, prefix: str) -> None:
    job = read_job(job_id)
    if not job or str(job.get("status") or "") == "failed":
        return
    failed_stage = str(job.get("stage") or "unknown")
    message = f"{prefix}: {exc}"
    append_log(job_id, message)
    update_job(job_id, status="failed", failed_stage=failed_stage, error=str(exc))


def _ensure_job_exists(job_id: str) -> dict:
    job = job_detail(job_id)["job"]
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    return job


def cancel_active_job(job_id: str) -> dict:
    job = read_job(job_id)
    if not job:
        raise ValueError(f"任务不存在: {job_id}")
    if not request_cancel(job_id):
        raise ValueError("当前没有正在运行的任务")
    append_log(job_id, "已请求取消当前任务；会在下一个安全检查点停止。")
    job = update_job(job_id, cancel_requested=True, error="已请求取消当前任务；会在下一个安全检查点停止。")
    return {"cancel_requested": True, "active": is_active(job_id), "job": job}


def reconcile_running_jobs(jobs: list[dict]) -> list[dict]:
    return [reconcile_running_job(str(job.get("id") or "")) for job in jobs if job.get("id")]


def reconcile_running_job(job_id: str) -> dict:
    job = read_job(job_id)
    if not job or job.get("status") != "running" or is_active(job_id):
        return job
    failed_stage = str(job.get("stage") or "unknown")
    message = "控制台重启或后台任务已停止，运行中的任务已标记为失败，可从当前阶段重试。"
    append_log(job_id, message)
    return update_job(job_id, status="failed", failed_stage=failed_stage, error=message)


def open_job_folder(job_id: str) -> dict:
    job_dir = (JOBS_DIR / job_id).resolve()
    jobs_root = JOBS_DIR.resolve()
    if jobs_root not in job_dir.parents or not job_dir.exists() or not job_dir.is_dir():
        raise ValueError(f"任务目录不存在: {job_id}")
    if subprocess.run(["open", str(job_dir)], check=False).returncode != 0:
        raise ValueError(f"无法打开任务目录: {job_dir}")
    return {"ok": True, "job_id": job_id, "path": str(job_dir)}
