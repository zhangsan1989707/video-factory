from __future__ import annotations

import json
import tempfile
import threading
import unittest
import http.client
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from src.console.background import active_job
from src.console.server import ConsoleHandler, _short_message
from src.console.store import create_job, read_json, update_job, write_json


class ConsoleServerSmokeTest(unittest.TestCase):
    def test_health_response_matches_documented_shape(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            health = _get(base_url, "/api/health")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        self.assertEqual(health, {"ok": True, "service": "video-factory-console"})

    def test_create_job_rejects_unknown_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    status = _post_status(base_url, "/api/jobs", {"type": "desktop-but-typo"})
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

        self.assertEqual(status, 400)

    def test_static_endpoint_rejects_symlinked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            static_dir = Path(tmp) / "static"
            static_dir.mkdir()
            (static_dir / "app.js").write_text("console.log('ok')", encoding="utf-8")
            outside = Path(tmp) / "outside.js"
            outside.write_text("secret", encoding="utf-8")
            (static_dir / "linked.js").symlink_to(outside)

            with patch("src.console.server.STATIC_DIR", static_dir):
                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    ok = _get_status(f"{base_url}/app.js")
                    linked = _get_status(f"{base_url}/static/linked.js")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

        self.assertEqual(ok, 200)
        self.assertEqual(linked, 404)

    def test_http_workflow_reaches_render_start_and_artifacts(self) -> None:
        async def fake_candidates(job_id: str) -> dict:
            write_json(jobs_dir / job_id / "candidates.json", {"items": _sample_projects()})
            job = update_job(job_id, status="awaiting_input", stage="awaiting_project_confirmation")
            return {"job": job, "candidates": _sample_projects()}

        async def fake_render(job_id: str) -> dict:
            job_dir = jobs_dir / job_id
            (job_dir / "final.mp4").write_bytes(b"video")
            job = update_job(job_id, status="completed", stage="completed")
            return {"job": job}

        def fake_previews(projects, output_dir, **kwargs):
            output_dir.mkdir(parents=True, exist_ok=True)
            previews = []
            for index in range(1, len(projects) + 4):
                path = output_dir / f"shot-{index:02d}.png"
                path.write_bytes(b"preview")
                previews.append(path)
            return previews

        async def fake_pipeline(**kwargs):
            return Path(kwargs["from_plan"])

        def immediate_start(job_id: str, worker, on_error=None) -> bool:
            try:
                import asyncio
                asyncio.run(worker(job_id))
            except Exception as exc:
                if on_error:
                    on_error(job_id, exc)
            return True

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
                patch("src.console.server.generate_candidates", side_effect=fake_candidates),
                patch("src.console.jobs.route_snapshot", return_value={
                    "provider": "",
                    "provider_name": "",
                    "model": "",
                    "enabled": "",
                    "configured": "",
                }),
                patch("src.console.model_router.route_snapshot", return_value={
                    "provider": "",
                    "provider_name": "",
                    "model": "",
                    "enabled": "",
                    "configured": "",
                }),
                patch("src.console.jobs.render_hotlist_v2_previews_from_projects", side_effect=fake_previews),
                patch("src.console.jobs.run_pipeline", side_effect=fake_pipeline),
                patch("src.console.server.render_video", side_effect=fake_render),
                patch("src.console.server.start_async_job", side_effect=immediate_start),
                patch("src.console.server.is_active", return_value=False),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    created = _post(base_url, "/api/jobs", {
                        "title": "HTTP smoke",
                        "project_count": 2,
                        "template_params": {"bgm": "none"},
                    })
                    job_id = created["job"]["id"]
                    draft = _post(base_url, f"/api/jobs/{job_id}/candidates", {})
                    selection = _post(base_url, f"/api/jobs/{job_id}/selection", {"items": _sample_projects()})
                    selection_detail = _get(base_url, f"/api/jobs/{job_id}")
                    script = _post(base_url, f"/api/jobs/{job_id}/script", {"segments": selection_detail["segments"]})
                    prepared = _post(base_url, f"/api/jobs/{job_id}/prepare-plan", {})
                    validated = _post(base_url, f"/api/jobs/{job_id}/validate-plan", {})
                    render = _post(base_url, f"/api/jobs/{job_id}/render-video", {})
                    detail = _get(base_url, f"/api/jobs/{job_id}")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

        self.assertTrue(draft["started"])
        self.assertTrue(selection["started"])
        self.assertTrue(script["started"])
        self.assertTrue(prepared["started"])
        self.assertTrue(validated["started"])
        self.assertEqual(script["job"]["status"], "awaiting_render")
        self.assertEqual(draft["job"]["stage"], "awaiting_project_confirmation")
        self.assertEqual(detail["quality_report"]["status"], "unverified")
        self.assertEqual(prepared["job"]["status"], "awaiting_validation")
        self.assertEqual(validated["job"]["status"], "ready_to_render")
        self.assertTrue(render["started"])
        self.assertFalse(render["active"])
        names = [item["name"] for item in detail["artifacts"]["files"]]
        self.assertIn("hook.json", names)
        self.assertIn("cover_frame.json", names)
        self.assertIn("cover_frame.png", names)
        self.assertIn("publish_pack.json", names)
        self.assertIn("quality_report.json", names)
        self.assertIn("readiness_report.json", names)
        self.assertIn("shot_plan.json", names)
        self.assertIn("asset_manifest.json", names)
        self.assertIn("script.json", names)
        self.assertIn("preview_frames/shot-01.png", names)

    def test_artifact_endpoint_serves_only_files_inside_job_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            job_dir = jobs_dir / "GH-HOTLIST-20990101-SEC"
            preview_dir = job_dir / "preview_frames"
            preview_dir.mkdir(parents=True)
            (job_dir / "task.json").write_text(json.dumps({"id": job_dir.name}), encoding="utf-8")
            (preview_dir / "shot-01.png").write_bytes(b"ok")
            (job_dir / ".env").write_text("SECRET=1", encoding="utf-8")
            outside = jobs_dir / "outside.txt"
            outside.parent.mkdir(parents=True, exist_ok=True)
            outside.write_text("secret", encoding="utf-8")
            (job_dir / "outside-link.txt").symlink_to(outside)

            with (
                patch("src.console.server.JOBS_DIR", jobs_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    with urllib.request.urlopen(f"{base_url}/api/jobs/{job_dir.name}/artifacts/preview_frames/shot-01.png", timeout=10) as response:
                        body = response.read()
                    escaped_status = _get_status(f"{base_url}/api/jobs/{job_dir.name}/artifacts/../outside.txt")
                    encoded_status = _get_status(f"{base_url}/api/jobs/{job_dir.name}/artifacts/%2E%2E/outside.txt")
                    hidden_status = _get_status(f"{base_url}/api/jobs/{job_dir.name}/artifacts/.env")
                    symlink_status = _get_status(f"{base_url}/api/jobs/{job_dir.name}/artifacts/outside-link.txt")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

        self.assertEqual(body, b"ok")
        self.assertEqual(escaped_status, 404)
        self.assertEqual(encoded_status, 404)
        self.assertEqual(hidden_status, 404)
        self.assertEqual(symlink_status, 404)

    def test_missing_job_read_endpoints_return_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.server.JOBS_DIR", jobs_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    detail = _get_status(f"{base_url}/api/jobs/GH-HOTLIST-20990101-MISSING")
                    logs = _get_status(f"{base_url}/api/jobs/GH-HOTLIST-20990101-MISSING/logs")
                    artifacts = _get_status(f"{base_url}/api/jobs/GH-HOTLIST-20990101-MISSING/artifacts")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

        self.assertEqual(detail, 404)
        self.assertEqual(logs, 404)
        self.assertEqual(artifacts, 404)

    def test_corrupt_job_snapshot_read_endpoints_return_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            job_dir = jobs_dir / "GH-HOTLIST-20990101-CORRUPT"
            job_dir.mkdir(parents=True)
            (job_dir / "task.json").write_text("{bad", encoding="utf-8")
            (job_dir / "logs.txt").write_text("should not leak", encoding="utf-8")
            (job_dir / "preview.png").write_bytes(b"image")

            with (
                patch("src.console.server.JOBS_DIR", jobs_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    detail = _get_status(f"{base_url}/api/jobs/{job_dir.name}")
                    logs = _get_status(f"{base_url}/api/jobs/{job_dir.name}/logs")
                    artifacts = _get_status(f"{base_url}/api/jobs/{job_dir.name}/artifacts")
                    artifact_file = _get_status(f"{base_url}/api/jobs/{job_dir.name}/artifacts/preview.png")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

        self.assertEqual(detail, 404)
        self.assertEqual(logs, 404)
        self.assertEqual(artifacts, 404)
        self.assertEqual(artifact_file, 404)

    def test_stale_running_job_is_marked_failed_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
                patch("src.console.server.is_active", return_value=False),
            ):
                job = create_job("GH-HOTLIST-20990101-STALE-RUN", {"project_count": 2})
                update_job(job["id"], status="running", stage="generating_tts")

                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    jobs = _get(base_url, "/api/jobs")
                    detail = _get(base_url, f"/api/jobs/{job['id']}")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

            saved = read_json(jobs_dir / job["id"] / "task.json", {})
            logs = (jobs_dir / job["id"] / "logs.txt").read_text(encoding="utf-8")

        listed = next(item for item in jobs["jobs"] if item["id"] == job["id"])
        self.assertEqual(listed["status"], "failed")
        self.assertEqual(detail["job"]["status"], "failed")
        self.assertEqual(detail["failed_stage"], "generating_tts")
        self.assertEqual(saved["failed_stage"], "generating_tts")
        self.assertIn("后台任务已停止", logs)

    def test_list_jobs_does_not_fail_active_background_request(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        async def slow_candidates(job_id: str) -> dict:
            job = update_job(job_id, status="running", stage="collecting_candidates")
            entered.set()
            self.assertTrue(release.wait(timeout=5))
            job = update_job(job_id, status="awaiting_input", stage="awaiting_project_confirmation")
            return {"job": job, "candidates": []}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
                patch("src.console.server.generate_candidates", side_effect=slow_candidates),
            ):
                job = create_job("GH-HOTLIST-20990101-SYNC-RUN", {})
                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                request_thread = threading.Thread(
                    target=lambda: _post(f"http://127.0.0.1:{server.server_port}", f"/api/jobs/{job['id']}/candidates", {}),
                    daemon=True,
                )
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    request_thread.start()
                    self.assertTrue(entered.wait(timeout=5))
                    jobs = _get(base_url, "/api/jobs")
                    detail = _get(base_url, f"/api/jobs/{job['id']}")
                    release.set()
                    request_thread.join(timeout=5)
                finally:
                    release.set()
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)
                saved = read_json(jobs_dir / job["id"] / "task.json", {})

        listed = next(item for item in jobs["jobs"] if item["id"] == job["id"])
        self.assertEqual(listed["status"], "running")
        self.assertEqual(detail["job"]["status"], "running")
        self.assertEqual(detail["job"]["stage"], "collecting_candidates")
        self.assertEqual(saved["status"], "awaiting_input")

    def test_delete_job_endpoint_removes_history_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
            ):
                job = create_job("GH-HOTLIST-20990101-DELETE", {})
                (jobs_dir / job["id"] / "preview.png").write_bytes(b"image")

                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    result = _delete(base_url, f"/api/jobs/{job['id']}")
                    jobs = _get(base_url, "/api/jobs")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

                job_dir_exists = (jobs_dir / job["id"]).exists()

        self.assertTrue(result["ok"])
        self.assertEqual(result["job_id"], "GH-HOTLIST-20990101-DELETE")
        self.assertEqual(jobs["jobs"], [])
        self.assertFalse(job_dir_exists)

    def test_delete_job_endpoint_rejects_active_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
                patch("src.console.server.is_active", return_value=True),
            ):
                job = create_job("GH-HOTLIST-20990101-ACTIVE", {})

                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    status = _delete_status(base_url, f"/api/jobs/{job['id']}")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

                job_dir_exists = (jobs_dir / job["id"]).exists()

        self.assertEqual(status, 400)
        self.assertTrue(job_dir_exists)

    def test_job_detail_reports_active_flag_while_background_context_is_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
            ):
                job = create_job("GH-HOTLIST-20990101-ACTIVE-DETAIL", {})
                update_job(job["id"], status="awaiting_input", stage="awaiting_project_confirmation")

                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    with active_job(job["id"]):
                        detail = _get(base_url, f"/api/jobs/{job['id']}")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

        self.assertTrue(detail["job"]["active"])
        self.assertEqual(detail["job"]["status"], "awaiting_input")
        self.assertEqual(detail["job"]["stage"], "awaiting_project_confirmation")

    def test_cancel_job_endpoint_marks_active_job_cancel_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
            ):
                job = create_job("GH-HOTLIST-20990101-CANCEL", {})
                update_job(job["id"], status="running", stage="composing_video")

                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    with active_job(job["id"]):
                        result = _post(base_url, f"/api/jobs/{job['id']}/cancel", {})
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                logs = (jobs_dir / job["id"] / "logs.txt").read_text(encoding="utf-8")

        self.assertTrue(result["cancel_requested"])
        self.assertTrue(saved["cancel_requested"])
        self.assertIn("已请求取消当前任务", logs)

    def test_create_job_endpoint_allows_new_job_while_another_job_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
                patch("src.console.server.is_active", return_value=True),
            ):
                create_job("GH-HOTLIST-20990101-ACTIVE", {})

                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    created = _post(base_url, "/api/jobs", {"project_count": 2})
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

        self.assertTrue(created["job"]["id"].startswith("GH-HOTLIST-"))
        self.assertNotEqual(created["job"]["id"], "GH-HOTLIST-20990101-ACTIVE")

    def test_provider_test_endpoint_uses_inline_provider_config(self) -> None:
        seen = {}

        def fake_test(provider_id: str, model: str, provider: dict | None = None):
            seen["provider_id"] = provider_id
            seen["model"] = model
            seen["provider"] = provider
            return True, "ok"

        with (
            patch("src.console.server.test_provider", side_effect=fake_test),
            patch("src.console.server.provider_connection_matches_saved", return_value=False),
            patch("src.console.server.config_snapshot", return_value={"providers": {"providers": []}}),
            patch("src.console.server.update_provider_test_result") as update_result,
        ):
            server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                result = _post(base_url, "/api/providers/openai/test", {
                    "model": "draft-model",
                    "provider": {
                        "api_key": "sk-draft",
                        "base_url": "https://draft.example/v1",
                        "default_model": "draft-default",
                        "enabled": True,
                    },
                })
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=1)

        self.assertTrue(result["ok"])
        self.assertFalse(result["saved"])
        self.assertEqual(seen["provider_id"], "openai")
        self.assertEqual(seen["model"], "draft-model")
        self.assertEqual(seen["provider"]["api_key"], "sk-draft")
        self.assertEqual(seen["provider"]["base_url"], "https://draft.example/v1")
        update_result.assert_not_called()

    def test_provider_test_endpoint_writes_result_for_saved_provider_config(self) -> None:
        with (
            patch("src.console.server.test_provider", return_value=(True, "ok")),
            patch("src.console.server.provider_connection_matches_saved", return_value=True),
            patch("src.console.server.update_provider_test_result", return_value={"providers": {"providers": []}}) as update_result,
        ):
            server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                result = _post(base_url, "/api/providers/openai/test", {"model": "saved-model"})
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=1)

        self.assertTrue(result["ok"])
        self.assertTrue(result["saved"])
        update_result.assert_called_once_with("openai", "连接成功: ok")

    def test_provider_test_message_redacts_api_key_fragments(self) -> None:
        message = _short_message("Authentication Fails, Your api key: ****b4da is invalid for sk-secretvalue")

        self.assertIn("api key: [redacted]", message)
        self.assertNotIn("b4da", message)
        self.assertNotIn("sk-secretvalue", message)

    def test_config_endpoint_saves_settings_in_one_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    result = _post(base_url, "/api/config", {
                        "github": {"token": "ghp_batch", "last_rate_limit": "ok"},
                        "lark": {"enabled": True, "base_token": "base_batch", "table_id": "tbl_batch"},
                        "providers": {
                            "providers": [
                                {
                                    "id": "openai",
                                    "api_key": "sk-openai",
                                    "base_url": "",
                                    "default_model": "gpt-4.1-mini",
                                    "enabled": True,
                                }
                            ]
                        },
                        "model-routing": {
                            "candidate_analysis": {"provider": "openai", "model": "gpt-4.1-mini"},
                        },
                        "scheduler": {
                            "enabled": "false",
                            "frequency": "daily",
                            "time": "09:00",
                            "time_window": "weekly",
                            "project_count": 5,
                            "template_params": {},
                            "last_run_date": "",
                        },
                        "templates": {
                            "active_template": "github_hotlist_vertical_v1",
                            "github_hotlist_vertical_v1": {
                                "project_count": 5,
                                "style": "sspai_editorial",
                                "subtitle_mode": "standard",
                                "bgm": "none",
                                "narration_tone": "short_video_hook",
                                "orientation": "vertical",
                            },
                        },
                    })
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

            github = read_json(config_dir / "github.json", {})
            lark = read_json(config_dir / "lark.json", {})
            providers = read_json(config_dir / "providers.json", {})["providers"]
            scheduler = read_json(config_dir / "scheduler.json", {})
            templates = read_json(config_dir / "templates.json", {})

        self.assertTrue(result["github"]["configured"])
        self.assertTrue(result["lark"]["configured"])
        self.assertEqual(github["token"], "ghp_batch")
        self.assertEqual(lark["table_id"], "tbl_batch")
        self.assertEqual(providers[0]["api_key"], "sk-openai")
        self.assertIs(scheduler["enabled"], False)
        self.assertEqual(templates["github_hotlist_vertical_v1"]["style"], "sspai_editorial")

    def test_post_value_errors_return_bad_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    created = _post(base_url, "/api/jobs", {"project_count": 2})
                    status = _post_status(base_url, f"/api/jobs/{created['job']['id']}/selection", {"items": _sample_projects()})
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

        self.assertEqual(status, 400)

    def test_post_missing_job_returns_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    status = _post_status(base_url, "/api/jobs/GH-HOTLIST-20990101-MISSING/prepare-plan", {})
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

        self.assertEqual(status, 404)

    def test_all_missing_job_write_endpoints_return_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            missing_id = "GH-HOTLIST-20990101-MISSING"
            endpoints = (
                "candidates",
                "regenerate-candidates",
                "selection",
                "regenerate-script",
                "script",
                "prepare-plan",
                "validate-plan",
                "render-video",
                "regenerate-video",
                "finalize",
            )
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    statuses = {
                        endpoint: _post_status(base_url, f"/api/jobs/{missing_id}/{endpoint}", {})
                        for endpoint in endpoints
                    }
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

        self.assertEqual(statuses, {endpoint: 404 for endpoint in endpoints})
        self.assertFalse((jobs_dir / missing_id).exists())

    def test_open_missing_job_folder_returns_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base_url = f"http://127.0.0.1:{server.server_port}"
                try:
                    status = _post_status(base_url, "/api/jobs/GH-HOTLIST-20990101-MISSING/open-folder", {})
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=1)

        self.assertEqual(status, 404)

    def test_invalid_json_returns_bad_request(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            request = urllib.request.Request(
                base_url + "/api/jobs",
                data=b"{bad",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(request, timeout=10)
                status = 200
            except urllib.error.HTTPError as exc:
                status = exc.code
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        self.assertEqual(status, 400)

    def test_non_utf8_json_returns_bad_request(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            request = urllib.request.Request(
                base_url + "/api/jobs",
                data=b"\xff",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(request, timeout=10)
                status = 200
            except urllib.error.HTTPError as exc:
                status = exc.code
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        self.assertEqual(status, 400)

    def test_non_object_json_returns_bad_request(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            request = urllib.request.Request(
                base_url + "/api/providers/openai/test",
                data=b"[]",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(request, timeout=10)
                status = 200
            except urllib.error.HTTPError as exc:
                status = exc.code
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        self.assertEqual(status, 400)

    def test_invalid_content_length_returns_bad_request(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), ConsoleHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status = _raw_post_status(server.server_port, "/api/jobs", b"{}", "bad")
            negative_status = _raw_post_status(server.server_port, "/api/jobs", b"", "-1")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        self.assertEqual(status, 400)
        self.assertEqual(negative_status, 400)


def _post(base_url: str, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base_url + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_status(base_url: str, path: str, payload: dict) -> int:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base_url + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _get(base_url: str, path: str) -> dict:
    with urllib.request.urlopen(base_url + path, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _delete(base_url: str, path: str) -> dict:
    request = urllib.request.Request(base_url + path, method="DELETE")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _delete_status(base_url: str, path: str) -> int:
    request = urllib.request.Request(base_url + path, method="DELETE")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _get_status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _raw_post_status(port: int, path: str, body: bytes, content_length: str) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.putrequest("POST", path)
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", content_length)
        connection.endheaders()
        if body:
            connection.send(body)
        return connection.getresponse().status
    finally:
        connection.close()


def _sample_projects() -> list[dict[str, object]]:
    return [
        {
            "name": "alpha",
            "full_name": "demo/alpha",
            "repo_url": "https://github.com/demo/alpha",
            "stars": 1520,
            "description": "AI agent workflow",
            "description_zh": "AI 工作流工具",
            "recommendation": "解决重复操作",
            "visual_potential": "README 可展示",
            "audience": "AI 开发者",
        },
        {
            "name": "beta",
            "full_name": "demo/beta",
            "repo_url": "https://github.com/demo/beta",
            "stars": 88,
            "description": "CLI helper",
            "description_zh": "命令行助手",
            "recommendation": "减少切工具",
            "visual_potential": "终端截图可展示",
            "audience": "开发者",
        },
    ]


if __name__ == "__main__":
    unittest.main()
