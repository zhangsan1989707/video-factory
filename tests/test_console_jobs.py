from __future__ import annotations

import asyncio
import json
import os
import time
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.console import jobs as console_jobs
from src.console.jobs import create_hotlist_job, finalize_numbered_output, generate_candidates, job_detail, prepare_plan, regenerate_candidates, regenerate_script, render_video, reset_video_for_regeneration, save_script, save_selection, validate_plan
from src.console.server import open_job_folder, start_candidates_job, start_prepare_plan_job, start_render_job, start_save_script_job
from src.console.store import create_job, next_job_id, read_json, update_job, write_json
from src.console.background import JobCancelled, cancel_requested, is_active, raise_if_cancelled, request_cancel, start_async_job


def _fake_hyperframes_previews(projects: list[dict], output_dir: Path, **kwargs) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    previews = []
    for index in range(1, len(projects) + 4):
        path = output_dir / f"shot-{index:02d}.png"
        path.write_bytes(b"preview")
        previews.append(path)
    return previews


def _with_output_dir(tmp: str, params: dict | None = None) -> dict:
    item = dict(params or {})
    item["official_output_dir"] = str(Path(tmp) / "published")
    return item


class ConsoleJobsTest(unittest.TestCase):
    def setUp(self) -> None:
        route_value = {
            "provider": "",
            "provider_name": "",
            "model": "",
            "enabled": "",
            "configured": "",
        }
        self.route_patcher = patch("src.console.jobs.route_snapshot", return_value=route_value)
        self.route_patcher.start()
        self.model_route_patcher = patch("src.console.model_router.route_snapshot", return_value=route_value)
        self.model_route_patcher.start()
        self.preview_patcher = patch("src.console.jobs.render_hotlist_v2_previews_from_projects", side_effect=_fake_hyperframes_previews)
        self.preview_patcher.start()
        self.preview_visual_patcher = patch("src.console.jobs._verify_preview_frame_image", return_value=None)
        self.preview_visual_patcher.start()

    def tearDown(self) -> None:
        self.preview_visual_patcher.stop()
        self.preview_patcher.stop()
        self.route_patcher.stop()
        self.model_route_patcher.stop()

    def test_background_runner_prevents_duplicate_active_job(self) -> None:
        async def slow_worker(job_id: str) -> None:
            started.append(job_id)
            await asyncio.sleep(0.05)

        started = []
        job_id = "GH-HOTLIST-20990101-BG"

        self.assertTrue(start_async_job(job_id, slow_worker))
        self.assertFalse(start_async_job(job_id, slow_worker))
        self.assertTrue(is_active(job_id))

        deadline = time.time() + 1
        while is_active(job_id) and time.time() < deadline:
            time.sleep(0.01)

        self.assertFalse(is_active(job_id))
        self.assertEqual(started, [job_id])

    def test_background_runner_reports_worker_start_failure(self) -> None:
        async def failing_worker(job_id: str) -> None:
            raise RuntimeError(f"worker failed for {job_id}")

        failures = []
        job_id = "GH-HOTLIST-20990101-BG-FAIL"

        self.assertTrue(start_async_job(job_id, failing_worker, on_error=lambda failed_id, exc: failures.append((failed_id, str(exc)))))

        deadline = time.time() + 1
        while is_active(job_id) and time.time() < deadline:
            time.sleep(0.01)

        self.assertFalse(is_active(job_id))
        self.assertEqual(failures, [(job_id, f"worker failed for {job_id}")])

    def test_background_runner_tracks_cancel_request_until_job_finishes(self) -> None:
        async def cancellable_worker(job_id: str) -> None:
            started.append(job_id)
            while not cancel_requested(job_id):
                await asyncio.sleep(0.01)
            raise_if_cancelled(job_id)

        started = []
        failures = []
        job_id = "GH-HOTLIST-20990101-BG-CANCEL"

        self.assertTrue(start_async_job(job_id, cancellable_worker, on_error=lambda failed_id, exc: failures.append((failed_id, type(exc)))))
        deadline = time.time() + 1
        while not started and time.time() < deadline:
            time.sleep(0.01)

        self.assertTrue(request_cancel(job_id))
        self.assertTrue(cancel_requested(job_id))

        deadline = time.time() + 1
        while is_active(job_id) and time.time() < deadline:
            time.sleep(0.01)

        self.assertFalse(is_active(job_id))
        self.assertFalse(cancel_requested(job_id))
        self.assertEqual(failures, [(job_id, JobCancelled)])

    def test_create_hotlist_job_retries_when_next_directory_is_taken(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                today = datetime.now().strftime("%Y%m%d")
                first_id = f"GH-HOTLIST-{today}-001"
                attempts = []
                real_create_job = console_jobs.create_job

                def racing_create_job(job_id: str, payload: dict) -> dict:
                    attempts.append(job_id)
                    if len(attempts) == 1:
                        (jobs_dir / first_id).mkdir(parents=True)
                    return real_create_job(job_id, payload)

                with patch("src.console.jobs.create_job", side_effect=racing_create_job):
                    job = create_hotlist_job({"title": "重试创建"})

            self.assertEqual(attempts, [first_id, f"GH-HOTLIST-{today}-002"])
            self.assertEqual(job["id"], f"GH-HOTLIST-{today}-002")

    def test_create_single_project_vertical_job_records_repo_and_plan_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = console_jobs.create_single_project_vertical_job({
                    "repo_url": "https://github.com/demo/alpha",
                })

            self.assertTrue(job["id"].startswith("GH-SINGLE-"))
            self.assertEqual(job["type"], "single_project_vertical")
            self.assertEqual(job["repo_url"], "https://github.com/demo/alpha")
            self.assertEqual(job["stage"], "preparing_plan")
            self.assertEqual(job["status"], "awaiting_render")

    def test_create_single_project_vertical_job_rejects_bad_repo_without_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                with self.assertRaisesRegex(ValueError, "GitHub 仓库地址格式"):
                    create_job("GH-SINGLE-20990101-BAD", {
                        "type": "single_project_vertical",
                        "repo_url": "https://example.com/demo/alpha",
                    })

            self.assertFalse((jobs_dir / "GH-SINGLE-20990101-BAD").exists())

    def test_create_desktop_review_job_records_repo_and_plan_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = console_jobs.create_desktop_review_job({
                    "repo_url": "https://github.com/demo/alpha",
                })

            self.assertTrue(job["id"].startswith("GH-DESKTOP-"))
            self.assertEqual(job["type"], "desktop_review")
            self.assertEqual(job["repo_url"], "https://github.com/demo/alpha")
            self.assertEqual(job["stage"], "preparing_plan")
            self.assertEqual(job["status"], "awaiting_render")

    def test_create_from_plan_render_job_requires_existing_plan_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            plan_dir = Path(tmp) / "plan"
            plan_dir.mkdir()
            write_json(plan_dir / "shot_plan.json", {"title": "Plan", "shots": []})
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = console_jobs.create_from_plan_render_job({
                    "plan_path": str(plan_dir),
                })
                with self.assertRaisesRegex(ValueError, "计划文件目录不存在"):
                    console_jobs.create_from_plan_render_job({"plan_path": str(Path(tmp) / "missing")})

            self.assertTrue(job["id"].startswith("GH-PLAN-"))
            self.assertEqual(job["type"], "from_plan_render")
            self.assertEqual(job["plan_path"], str(plan_dir.resolve()))

    def test_prepare_single_project_vertical_plan_uses_existing_pipeline(self) -> None:
        async def fake_run_pipeline(**kwargs):
            calls.append(kwargs)
            job_dir = Path(kwargs["output"]).parent
            write_json(job_dir / "asset_manifest.json", {"assets": []})
            write_json(job_dir / "shot_plan.json", {
                "title": "Alpha",
                "shots": [{"start": 0, "duration": 4, "visual_asset": "", "visual_treatment": "single_hook", "narration_intent": "hook", "subtitle": "Alpha"}],
            })
            write_json(job_dir / "script.json", {
                "title": "Alpha",
                "total_duration": 4,
                "segments": [{"timestamp": 0, "duration": 4, "narration": "Alpha", "action": "show", "target": ""}],
            })
            write_json(job_dir / "info.json", {"name": "alpha"})
            return job_dir

        def fake_vertical_previews(_script, _shot_plan, _manifest, preview_dir: Path):
            preview_dir.mkdir(parents=True, exist_ok=True)
            preview = preview_dir / "shot-01.png"
            preview.write_bytes(b"preview")
            return [preview]

        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=fake_run_pipeline),
                patch("src.console.jobs.render_vertical_previews", side_effect=fake_vertical_previews),
            ):
                job = console_jobs.create_single_project_vertical_job({"repo_url": "https://github.com/demo/alpha"})
                result = prepare_plan(job["id"])

            self.assertEqual(calls[0]["url"], "https://github.com/demo/alpha")
            self.assertEqual(calls[0]["orientation"], "vertical")
            self.assertEqual(calls[0]["style"], "single-review")
            self.assertTrue(calls[0]["dry_run"])
            self.assertEqual(result["job"]["status"], "awaiting_input")
            self.assertEqual(result["job"]["stage"], "awaiting_script_confirmation")
            self.assertEqual(result["segments"][0]["id"], "intro")
            self.assertEqual(result["readiness_report"]["status"], "ready")
            self.assertTrue((jobs_dir / job["id"] / "cover_frame.png").exists())

    def test_prepare_desktop_review_plan_uses_desktop_pipeline(self) -> None:
        async def fake_run_pipeline(**kwargs):
            calls.append(kwargs)
            job_dir = Path(kwargs["output"]).parent
            write_json(job_dir / "desktop_review_plan.json", {"title": "Alpha", "shots": []})
            write_json(job_dir / "script.json", {
                "title": "Alpha",
                "total_duration": 4,
                "segments": [{"timestamp": 0, "duration": 4, "narration": "Alpha", "action": "desktop_review", "target": ""}],
            })
            write_json(job_dir / "info.json", {"name": "alpha"})
            return job_dir

        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=fake_run_pipeline),
            ):
                job = console_jobs.create_desktop_review_job({"repo_url": "https://github.com/demo/alpha"})
                result = prepare_plan(job["id"])

            self.assertEqual(calls[0]["url"], "https://github.com/demo/alpha")
            self.assertEqual(calls[0]["style"], "desktop-review")
            self.assertTrue(calls[0]["dry_run"])
            self.assertEqual(result["job"]["status"], "awaiting_input")
            self.assertEqual(result["job"]["stage"], "awaiting_script_confirmation")
            self.assertTrue((jobs_dir / job["id"] / "desktop_review_plan.json").exists())
            self.assertTrue((jobs_dir / job["id"] / "cover_frame.png").exists())

    def test_prepare_from_plan_render_copies_plan_snapshot(self) -> None:
        def fake_vertical_previews(_script, _shot_plan, _manifest, preview_dir: Path):
            preview_dir.mkdir(parents=True, exist_ok=True)
            preview = preview_dir / "shot-01.png"
            preview.write_bytes(b"preview")
            return [preview]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = root / "jobs"
            plan_dir = root / "source-plan"
            plan_dir.mkdir()
            write_json(plan_dir / "asset_manifest.json", {"assets": []})
            write_json(plan_dir / "shot_plan.json", {
                "title": "Plan",
                "shots": [{"start": 0, "duration": 4, "visual_asset": "", "visual_treatment": "single_hook", "narration_intent": "hook", "subtitle": "Plan"}],
            })
            write_json(plan_dir / "script.json", {
                "title": "Plan",
                "total_duration": 4,
                "segments": [{"timestamp": 0, "duration": 4, "narration": "Plan", "action": "show", "target": ""}],
            })
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.render_vertical_previews", side_effect=fake_vertical_previews),
            ):
                job = console_jobs.create_from_plan_render_job({"plan_path": str(plan_dir)})
                result = prepare_plan(job["id"])

            job_dir = jobs_dir / job["id"]
            self.assertEqual(result["job"]["status"], "awaiting_input")
            self.assertEqual(result["job"]["stage"], "awaiting_script_confirmation")
            self.assertTrue((job_dir / "shot_plan.json").exists())
            self.assertTrue((job_dir / "script.json").exists())
            self.assertTrue((job_dir / "cover_frame.png").exists())

    def test_bgm_volume_is_clamped(self) -> None:
        self.assertEqual(console_jobs._bgm_volume({"template_params": {"bgm_volume": 0.42}}), 0.42)
        self.assertEqual(console_jobs._bgm_volume({"template_params": {"bgm_volume": 2}}), 1.0)
        self.assertEqual(console_jobs._bgm_volume({"template_params": {"bgm_volume": -1}}), 0.0)
        self.assertEqual(console_jobs._bgm_volume({"template_params": {"bgm_volume": "loud"}}), 0.065)

    def test_save_single_project_script_runs_quality_and_publish_pack_without_deleting_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.quality.store.JOBS_DIR", jobs_dir),
            ):
                job = console_jobs.create_single_project_vertical_job({
                    "repo_url": "https://github.com/demo/alpha",
                    "title": "Alpha Review",
                })
                job_dir = jobs_dir / job["id"]
                write_json(job_dir / "asset_manifest.json", {"assets": []})
                write_json(job_dir / "shot_plan.json", {"title": "Alpha", "shots": []})
                write_json(job_dir / "script.json", {
                    "title": "Alpha",
                    "total_duration": 8,
                    "segments": [
                        {"timestamp": 0, "duration": 4, "narration": "旧开场", "action": "show", "target": ""},
                        {"timestamp": 4, "duration": 4, "narration": "旧结尾", "action": "show", "target": ""},
                    ],
                })
                write_json(job_dir / "info.json", {"name": "alpha", "owner": "demo", "repo_url": "https://github.com/demo/alpha", "description": "AI workflow"})
                update_job(job["id"], status="awaiting_input", stage="awaiting_script_confirmation")

                result = save_script(job["id"], {
                    "segments": [
                        {"id": "intro", "label": "开场", "text": "新开场"},
                        {"id": "outro", "label": "结尾", "text": "新结尾"},
                    ],
                })

            saved_script = read_json(jobs_dir / job["id"] / "script.json", {})
            self.assertEqual(result["job"]["status"], "awaiting_validation")
            self.assertTrue((jobs_dir / job["id"] / "shot_plan.json").exists())
            self.assertTrue((jobs_dir / job["id"] / "quality_report.json").exists())
            self.assertTrue((jobs_dir / job["id"] / "publish_pack.json").exists())
            self.assertEqual(saved_script["segments"][0]["narration"], "新开场")

    def test_render_single_project_vertical_uses_from_plan_and_finalizes_output(self) -> None:
        async def fake_run_pipeline(**kwargs):
            calls.append(kwargs)
            output = Path(kwargs["output"])
            output.write_bytes(b"video")
            return output

        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=fake_run_pipeline),
            ):
                job = console_jobs.create_single_project_vertical_job({
                    "repo_url": "https://github.com/demo/alpha",
                    "title": "Alpha Review",
                    "template_params": _with_output_dir(tmp, {"bgm_volume": 0.24}),
                })
                job_dir = jobs_dir / job["id"]
                write_json(job_dir / "asset_manifest.json", {"assets": []})
                write_json(job_dir / "shot_plan.json", {"title": "Alpha", "shots": []})
                write_json(job_dir / "script.json", {"title": "Alpha", "segments": []})
                update_job(job["id"], status="ready_to_render", stage="preparing_plan", plan_validation={"status": "passed", "error": ""})

                result = asyncio.run(render_video(job["id"]))

            self.assertEqual(calls[0]["from_plan"], str(jobs_dir / job["id"]))
            self.assertEqual(calls[0]["style"], "single-review")
            self.assertEqual(calls[0]["bgm_volume"], 0.24)
            self.assertEqual(result["job"]["status"], "completed")
            self.assertTrue(Path(result["job"]["official_video"]).exists())

    def test_viewer_highlight_ignores_visual_potential_for_narration(self) -> None:
        self.assertEqual(
            console_jobs._viewer_highlight({
                "project_highlight": "把 AI 流程接进具体开发步骤",
                "visual_potential": "中：可用 README、标签和仓库页做信息卡片。",
            }),
            "把 AI 流程接进具体开发步骤",
        )
        self.assertNotIn(
            "README",
            console_jobs._viewer_highlight({
                "description": "AI agent workflow",
                "visual_potential": "中：可用 README、标签和仓库页做信息卡片。",
            }),
        )

    def test_narration_sanitizers_preserve_long_text_without_ellipsis(self) -> None:
        long_text = (
            "AI 代理写代码最麻烦的地方，不是它不会写，而是它太容易把一个小问题扩成一整套复杂架构。"
            "Ponytail 的核心动作是把约束写进配置，让代理只交付解决当前问题的最少代码。"
            "它讲的不是更聪明的代理，而是更克制的交付边界，让每次改动都能回到真实需求本身。"
            "适合：被过度设计和无效抽象反复拖慢的自动化开发者。"
        )
        raw_segments = [
            {"id": "intro", "label": "开场", "text": "这期看 AI 工具怎么回到真实工作流。"},
            {"id": "project-1", "label": "第 1 名", "text": long_text},
            {"id": "outro", "label": "结尾", "text": "你想看哪个项目实操，评论区打名字。"},
        ]

        model_segments = console_jobs._sanitize_model_segments([_sample_projects()[0]], raw_segments)
        polished_segments = console_jobs._sanitize_polished_segments(raw_segments, raw_segments)

        self.assertEqual(model_segments[1]["text"], long_text)
        self.assertEqual(polished_segments[1]["text"], long_text)
        self.assertFalse(model_segments[1]["text"].endswith("..."))
        self.assertFalse(polished_segments[1]["text"].endswith("..."))

    def test_manifest_prefers_homepage_then_readme_image_then_repo(self) -> None:
        manifest = console_jobs._manifest([{
            "name": "alpha",
            "full_name": "demo/alpha",
            "repo_url": "https://github.com/demo/alpha",
            "homepage": "https://alpha.example.com",
            "default_branch": "main",
            "readme": "![demo](docs/screen.png)",
            "description": "AI agent workflow",
        }]).to_dict()

        assets = manifest["assets"]
        self.assertEqual([asset["type"] for asset in assets], ["webpage", "image", "github_repo"])
        self.assertEqual(assets[0]["source"], "https://alpha.example.com")
        self.assertEqual(assets[1]["source"], "https://raw.githubusercontent.com/demo/alpha/main/docs/screen.png")

    def test_start_render_job_returns_background_status_without_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.start_async_job", return_value=True),
                patch("src.console.server.is_active", return_value=True),
            ):
                job = create_job("GH-HOTLIST-20990101-SRV", {})
                update_job(job["id"], status="ready_to_render", stage="preparing_plan")
                result = start_render_job(job["id"])

        self.assertTrue(result["started"])
        self.assertTrue(result["active"])
        self.assertEqual(result["job"]["id"], "GH-HOTLIST-20990101-SRV")
        self.assertNotIn("artifacts", result)

    def test_start_candidates_job_returns_background_status_without_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
                patch("src.console.server.start_async_job", return_value=True),
                patch("src.console.server.is_active", return_value=True),
            ):
                job = create_job("GH-HOTLIST-20990101-SRV-CANDIDATES", {})
                result = start_candidates_job(job["id"])

        self.assertTrue(result["started"])
        self.assertTrue(result["active"])
        self.assertEqual(result["job"]["id"], "GH-HOTLIST-20990101-SRV-CANDIDATES")
        self.assertNotIn("candidates", result)

    def test_start_save_script_job_preserves_bad_request_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
                patch("src.console.server.start_async_job") as start_job,
            ):
                job = create_job("GH-HOTLIST-20990101-SRV-SCRIPT", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])

                with self.assertRaisesRegex(ValueError, "当前阶段不能确认口播"):
                    start_save_script_job(job["id"], {"segments": [{"id": "intro", "label": "开场", "text": "test"}]})

                start_job.assert_not_called()

    def test_start_prepare_plan_job_preserves_bad_request_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
                patch("src.console.server.start_async_job") as start_job,
            ):
                job = create_job("GH-HOTLIST-20990101-SRV-PLAN", {"project_count": 2})

                with self.assertRaisesRegex(ValueError, "当前阶段不能生成计划文件"):
                    start_prepare_plan_job(job["id"])

                start_job.assert_not_called()

    def test_start_render_job_reports_duplicate_active_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.start_async_job", return_value=False),
            ):
                job = create_job("GH-HOTLIST-20990101-SRV-DUPE", {})
                update_job(job["id"], status="ready_to_render", stage="preparing_plan")

                with self.assertRaises(ValueError):
                    start_render_job(job["id"])

    def test_start_render_job_records_background_start_failure(self) -> None:
        callbacks = []

        def fake_start(job_id: str, worker, on_error=None) -> bool:
            callbacks.append(on_error)
            return True

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.start_async_job", side_effect=fake_start),
                patch("src.console.server.is_active", return_value=False),
            ):
                job = create_job("GH-HOTLIST-20990101-SRV-BG-FAIL", {})
                update_job(job["id"], status="ready_to_render", stage="preparing_plan")
                start_render_job(job["id"])
                callbacks[0](job["id"], RuntimeError("thread bootstrap failed"))
                detail = job_detail(job["id"])
                logs = (jobs_dir / job["id"] / "logs.txt").read_text(encoding="utf-8")

        self.assertEqual(detail["job"]["status"], "failed")
        self.assertEqual(detail["failed_stage"], "preparing_plan")
        self.assertIn("thread bootstrap failed", detail["job"]["error"])
        self.assertIn("后台渲染任务失败", logs)

    def test_open_job_folder_only_opens_existing_job_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
                patch("src.console.server.subprocess.run") as run,
            ):
                run.return_value.returncode = 0
                job = create_job("GH-HOTLIST-20990101-OPEN", {})
                result = open_job_folder(job["id"])

                self.assertTrue(result["ok"])
                run.assert_called_once_with(["open", str((jobs_dir / job["id"]).resolve())], check=False)

                with self.assertRaises(ValueError):
                    open_job_folder("GH-HOTLIST-20990101-MISSING")

    def test_selection_for_missing_job_does_not_create_partial_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                with self.assertRaises(ValueError):
                    save_selection("GH-HOTLIST-20990101-MISSING", {"items": _sample_projects()})

            self.assertFalse((jobs_dir / "GH-HOTLIST-20990101-MISSING").exists())

    def test_script_for_missing_job_does_not_create_partial_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                with self.assertRaises(ValueError):
                    save_script("GH-HOTLIST-20990101-MISSING", {"segments": [{"id": "intro", "label": "开场", "text": "test"}]})

            self.assertFalse((jobs_dir / "GH-HOTLIST-20990101-MISSING").exists())

    def test_selection_rejects_wrong_stage_without_overwriting_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-STAGE", {"project_count": 2})
                with self.assertRaises(ValueError):
                    save_selection(job["id"], {"items": _sample_projects()})

            self.assertFalse((jobs_dir / job["id"] / "selected_projects.json").exists())

    def test_script_rejects_wrong_stage_without_overwriting_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-SCRIPT-STAGE", {"project_count": 2})
                with self.assertRaises(ValueError):
                    save_script(job["id"], {"segments": [{"id": "intro", "label": "开场", "text": "test"}]})

            self.assertFalse((jobs_dir / job["id"] / "narration.json").exists())

    def test_prepare_plan_rejects_unconfirmed_script_without_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-PLAN-STAGE", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                save_selection(job["id"], {"items": _sample_projects()})

                with self.assertRaises(ValueError):
                    prepare_plan(job["id"])

            self.assertFalse((jobs_dir / job["id"] / "shot_plan.json").exists())

    def test_validate_plan_rejects_before_plan_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-VALIDATE-STAGE", {"project_count": 2})

                with self.assertRaises(ValueError):
                    asyncio.run(validate_plan(job["id"]))

            self.assertFalse((jobs_dir / job["id"] / "shot_plan.json").exists())

    def test_render_video_rejects_before_plan_stage_without_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-RENDER-STAGE", {"project_count": 2})

                with self.assertRaises(ValueError):
                    asyncio.run(render_video(job["id"]))

            self.assertFalse((jobs_dir / job["id"] / "shot_plan.json").exists())

    def test_start_render_job_rejects_before_plan_stage_without_background_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.start_async_job") as start_job,
            ):
                job = create_job("GH-HOTLIST-20990101-START-STAGE", {"project_count": 2})

                with self.assertRaises(ValueError):
                    start_render_job(job["id"])

                start_job.assert_not_called()

    def test_start_render_job_rejects_missing_job_without_background_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.start_async_job") as start_job,
            ):
                with self.assertRaisesRegex(ValueError, "任务不存在"):
                    start_render_job("GH-HOTLIST-20990101-MISSING")

                start_job.assert_not_called()

    def test_job_detail_rejects_missing_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                with self.assertRaisesRegex(ValueError, "任务不存在"):
                    job_detail("GH-HOTLIST-20990101-MISSING")

    def test_hotlist_plan_keeps_rank_card_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-001", {
                    "title": "验证热榜",
                    "project_count": 2,
                })
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                self.assertEqual(selection["job"]["stage"], "awaiting_script_confirmation")

                script = save_script(job["id"], {"segments": selection["segments"]})
                self.assertEqual(script["job"]["status"], "awaiting_render")

                result = prepare_plan(job["id"])
                self.assertEqual(result["job"]["status"], "awaiting_validation")
                self.assertEqual(result["readiness_report"]["status"], "review")
                fact_check = next(item for item in result["readiness_report"]["checks"] if item["id"] == "fact_check")
                self.assertFalse(fact_check["passed"])
                self.assertEqual(result["cover_frame"]["status"], "ready")

                shot_plan = read_json(jobs_dir / job["id"] / "shot_plan.json", {})
                self.assertNotIn("alpha", shot_plan["shots"][1]["subtitle"])
                self.assertIn("整体趋势", shot_plan["shots"][1]["subtitle"])
                rank_cards = [
                    shot["visual_treatment"]
                    for shot in shot_plan["shots"]
                    if shot["visual_treatment"].startswith("hotlist_rank_card:")
                ]

                self.assertEqual(len(rank_cards), 2)
                for treatment in rank_cards:
                    parts = treatment.split(":")
                    self.assertEqual(len(parts), 6)
                    self.assertEqual(len(parts[5].split("|")), 3)
                    self.assertIsNone(re.search(r"[;:]", parts[5]))

                manifest = read_json(jobs_dir / job["id"] / "asset_manifest.json", {})
                asset_ids = [asset["id"] for asset in manifest["assets"]]
                self.assertIn("p1-asset-001", asset_ids)
                self.assertIn("p2-asset-001", asset_ids)
                self.assertTrue(any(asset["type"] in {"webpage", "image", "github_repo"} for asset in manifest["assets"]))
                rank_card_shots = [
                    shot for shot in shot_plan["shots"]
                    if shot["visual_treatment"].startswith("hotlist_rank_card:")
                ]
                self.assertEqual([shot["visual_asset"] for shot in rank_card_shots], ["p1-asset-001", "p2-asset-001"])
                previews = sorted((jobs_dir / job["id"] / "preview_frames").glob("*.png"))
                self.assertEqual(len(previews), len(shot_plan["shots"]))
                cover_frame = jobs_dir / job["id"] / "cover_frame.png"
                self.assertTrue(cover_frame.exists())
                self.assertEqual(cover_frame.read_bytes(), previews[0].read_bytes())
                cover_meta = read_json(jobs_dir / job["id"] / "cover_frame.json", {})
                self.assertEqual(cover_meta["source"], str(previews[0]))
                readiness = read_json(jobs_dir / job["id"] / "readiness_report.json", {})
                visual_check = next(item for item in readiness["checks"] if item["id"] == "preview_visual_smoke")
                self.assertTrue(visual_check["passed"])
                self.assertEqual(readiness["score"], 87)
                self.assertEqual(job_detail(job["id"])["readiness_report"]["status"], "review")
                self.assertEqual(job_detail(job["id"])["cover_frame"]["status"], "ready")
                visual_report = job_detail(job["id"])["preview_visual_report"]
                self.assertEqual(visual_report["status"], "passed")
                self.assertEqual(visual_report["checked_count"], 5)

    def test_hotlist_manifest_prefers_homepage_then_readme_image_then_repo(self) -> None:
        projects = [
            {
                "name": "site",
                "full_name": "demo/site",
                "repo_url": "https://github.com/demo/site",
                "homepage": "https://site.example.com",
                "description": "project with homepage",
            },
            {
                "name": "shot",
                "full_name": "demo/shot",
                "repo_url": "https://github.com/demo/shot",
                "default_branch": "main",
                "readme": "![demo](docs/screen.png)",
                "description": "project with readme image",
            },
            {
                "name": "repo",
                "full_name": "demo/repo",
                "repo_url": "https://github.com/demo/repo",
                "description": "repo only",
            },
        ]

        assets = console_jobs._manifest(projects).to_dict()["assets"]
        by_id = {asset["id"]: asset for asset in assets}

        self.assertEqual(by_id["p1-asset-001"]["type"], "webpage")
        self.assertEqual(by_id["p1-asset-001"]["source"], "https://site.example.com")
        self.assertEqual(by_id["p2-asset-001"]["type"], "image")
        self.assertEqual(
            by_id["p2-asset-001"]["source"],
            "https://raw.githubusercontent.com/demo/shot/main/docs/screen.png",
        )
        self.assertEqual(by_id["p3-asset-001"]["type"], "github_repo")
        self.assertEqual(by_id["p3-asset-001"]["source"], "https://github.com/demo/repo")

    def test_selection_preserves_client_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-ORDER", {"project_count": 2})
                projects = list(reversed(_sample_projects()))
                write_json(jobs_dir / job["id"] / "candidates.json", {"items": _sample_projects()})
                _mark_awaiting_project_confirmation(job["id"])
                save_selection(job["id"], {"items": projects})

                selected = read_json(jobs_dir / job["id"] / "selected_projects.json", {})["items"]
                self.assertEqual([item["name"] for item in selected], ["beta", "alpha"])

    def test_selection_uses_candidate_snapshot_instead_of_client_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-SNAPSHOT", {"project_count": 2})
                write_json(jobs_dir / job["id"] / "candidates.json", {"items": _sample_projects()})
                _mark_awaiting_project_confirmation(job["id"])

                selection = save_selection(job["id"], {"items": [
                    {"full_name": "demo/alpha", "name": "tampered", "stars": 999999},
                ]})

                selected = read_json(jobs_dir / job["id"] / "selected_projects.json", {})["items"]
                self.assertEqual(selected[0]["name"], "alpha")
                self.assertEqual(selected[0]["stars"], 1520)
                self.assertEqual(selected[0]["feature_extract"]["core_action"], "把 AI 流程接进具体开发步骤")
                self.assertEqual(selection["segments"][1]["id"], "project-1")

    def test_selection_rejects_items_outside_candidate_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-FORGED", {"project_count": 2})
                write_json(jobs_dir / job["id"] / "candidates.json", {"items": _sample_projects()})
                _mark_awaiting_project_confirmation(job["id"])

                with self.assertRaisesRegex(ValueError, "候选快照中不存在"):
                    save_selection(job["id"], {"items": [{"full_name": "demo/forged", "name": "forged"}]})

                self.assertFalse((jobs_dir / job["id"] / "selected_projects.json").exists())
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["stage"], "awaiting_project_confirmation")

    def test_selection_rejects_duplicate_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-DUPE-SELECTION", {"project_count": 2})
                write_json(jobs_dir / job["id"] / "candidates.json", {"items": _sample_projects()})
                _mark_awaiting_project_confirmation(job["id"])

                with self.assertRaisesRegex(ValueError, "不能重复选择同一个项目"):
                    save_selection(job["id"], {"items": [
                        {"full_name": "demo/alpha"},
                        {"full_name": "demo/alpha"},
                    ]})

                self.assertFalse((jobs_dir / job["id"] / "selected_projects.json").exists())

    def test_selection_rejects_more_than_project_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-TOO-MANY", {"project_count": 5})
                _mark_awaiting_project_confirmation(job["id"])
                projects = [
                    *_sample_projects(),
                    *_extra_projects(4),
                ]

                with self.assertRaisesRegex(ValueError, "最多只能选择 5 个项目，当前选择 6 个"):
                    save_selection(job["id"], {"items": projects})

                self.assertFalse((jobs_dir / job["id"] / "selected_projects.json").exists())
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["stage"], "awaiting_project_confirmation")

    def test_candidates_rejects_after_project_confirmation_without_overwriting_stage(self) -> None:
        async def collect(**kwargs):
            return {"items": _sample_projects(), "rate_limit": "ok"}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.collect_candidates_with_meta", side_effect=collect),
            ):
                job = create_job("GH-HOTLIST-20990101-CANDIDATE-STAGE", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                save_selection(job["id"], {"items": _sample_projects()})

                with self.assertRaises(ValueError):
                    asyncio.run(generate_candidates(job["id"]))

                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["stage"], "awaiting_script_confirmation")
                candidates = read_json(jobs_dir / job["id"] / "candidates.json", {})["items"]
                self.assertEqual([item["full_name"] for item in candidates], ["demo/alpha", "demo/beta"])

    def test_generate_candidates_labels_cached_rate_limit_as_cached(self) -> None:
        async def collect(**kwargs):
            return {"items": _sample_projects(), "rate_limit": "29/30，重置 19:31", "cache_status": "hit"}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.collect_candidates_with_meta", side_effect=collect),
            ):
                job = create_job("GH-HOTLIST-20990101-CACHED-RATE", {"project_count": 2})

                asyncio.run(generate_candidates(job["id"]))

                logs = (jobs_dir / job["id"] / "logs.txt").read_text(encoding="utf-8")
                self.assertIn("GitHub 候选缓存命中，未请求 API。", logs)
                self.assertIn("GitHub 缓存记录额度: 29/30，重置 19:31。", logs)
                self.assertNotIn("GitHub API 额度: 29/30，重置 19:31。", logs)

    def test_regenerate_candidates_clears_downstream_snapshots(self) -> None:
        async def collect(**kwargs):
            return {"items": _extra_projects(2), "rate_limit": "ok"}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.collect_candidates_with_meta", side_effect=collect),
            ):
                job = create_job("GH-HOTLIST-20990101-REGEN-CANDIDATES", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])

                result = asyncio.run(regenerate_candidates(job["id"]))

                job_dir = jobs_dir / job["id"]
                self.assertEqual([item["name"] for item in result["candidates"]], ["extra-1", "extra-2"])
                self.assertFalse((job_dir / "selected_projects.json").exists())
                self.assertFalse((job_dir / "narration.json").exists())
                self.assertFalse((job_dir / "shot_plan.json").exists())
                self.assertEqual(result["job"]["stage"], "awaiting_project_confirmation")

    def test_regenerate_candidates_passes_force_refresh(self) -> None:
        collected_kwargs = []

        async def collect(**kwargs):
            collected_kwargs.append(kwargs)
            return {"items": _extra_projects(2), "rate_limit": "ok"}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.collect_candidates_with_meta", side_effect=collect),
            ):
                job = create_job("GH-HOTLIST-20990101-FORCE-REFRESH", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])

                asyncio.run(regenerate_candidates(job["id"]))

                self.assertTrue(len(collected_kwargs) >= 1)
                self.assertTrue(collected_kwargs[0].get("force_refresh"), "regenerate_candidates should pass force_refresh=True")

    def test_regenerate_script_keeps_selection_and_clears_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-REGEN-SCRIPT", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])

                result = regenerate_script(job["id"])

                job_dir = jobs_dir / job["id"]
                self.assertTrue((job_dir / "selected_projects.json").exists())
                self.assertTrue((job_dir / "narration.json").exists())
                self.assertFalse((job_dir / "shot_plan.json").exists())
                self.assertEqual(result["job"]["stage"], "awaiting_script_confirmation")
                self.assertEqual([segment["id"] for segment in result["segments"]], ["intro", "project-1", "project-2", "outro"])

    def test_reset_video_for_regeneration_keeps_script_and_clears_video_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-REGEN-VIDEO", {"project_count": 2, "title": "重生成视频"})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                job_dir = jobs_dir / job["id"]
                (job_dir / "final.mp4").write_bytes(b"video")
                (job_dir / f"{job['id']}-old.mp4").write_bytes(b"video")
                update_job(job["id"], status="completed", stage="completed", official_video=str(job_dir / f"{job['id']}-old.mp4"))

                reset = reset_video_for_regeneration(job["id"])

                self.assertFalse((job_dir / "final.mp4").exists())
                self.assertTrue((job_dir / f"{job['id']}-old.mp4").exists())
                self.assertTrue((job_dir / "narration.json").exists())
                self.assertEqual(reset["status"], "ready_to_render")
                self.assertEqual(reset["stage"], "preparing_plan")
                self.assertEqual(reset["official_video"], "")

    def test_plan_validation_runs_from_plan_dry_run_before_render(self) -> None:
        async def dry_run_pipeline(**kwargs):
            calls.append(kwargs)
            return Path(kwargs["from_plan"])

        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=dry_run_pipeline),
            ):
                job = create_job("GH-HOTLIST-20990101-008", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])

                result = asyncio.run(validate_plan(job["id"]))

                self.assertEqual(result["job"]["status"], "ready_to_render")
                self.assertEqual(result["plan_validation"]["status"], "passed")
                self.assertIn("details", result["plan_validation"])
                self.assertIn("asset_existence", result["plan_validation"]["details"])
                self.assertGreater(result["plan_validation"]["details"]["duration_sum"], 0)
                self.assertTrue(calls[0]["dry_run"])
                self.assertEqual(calls[0]["from_plan"], str(jobs_dir / job["id"]))

    def test_prepare_plan_uses_hyperframes_previews_for_tech_hotspot(self) -> None:
        calls = []

        def previews(projects, output_dir, **kwargs):
            calls.append({"projects": projects, "output_dir": output_dir, **kwargs})
            return _fake_hyperframes_previews(projects, output_dir, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.render_hotlist_v2_previews_from_projects", side_effect=previews),
            ):
                job = create_job("GH-HOTLIST-20990101-HF-PREVIEWS", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                result = prepare_plan(job["id"])

                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["style"], "tech_hotspot")
                self.assertEqual(result["readiness_report"]["status"], "review")

    def test_prepare_plan_blocks_failed_preview_visual_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs._verify_preview_frame_image", side_effect=ValueError("preview frame is blank")),
            ):
                job = create_job("GH-HOTLIST-20990101-HF-VISUAL-FAIL", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                result = prepare_plan(job["id"])

                report = result["preview_visual_report"]
                self.assertEqual(report["status"], "failed")
                self.assertEqual(len(report["failures"]), 5)
                visual_check = next(item for item in result["readiness_report"]["checks"] if item["id"] == "preview_visual_smoke")
                self.assertFalse(visual_check["passed"])
                self.assertEqual(result["readiness_report"]["status"], "review")

    def test_prepare_plan_uses_selected_hyperframes_style_for_previews(self) -> None:
        calls = []

        def previews(projects, output_dir, **kwargs):
            calls.append({"projects": projects, "output_dir": output_dir, **kwargs})
            return _fake_hyperframes_previews(projects, output_dir, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.render_hotlist_v2_previews_from_projects", side_effect=previews),
            ):
                job = create_job("GH-HOTLIST-20990101-HF-STYLE-PREVIEWS", {
                    "project_count": 2,
                    "template_params": {"style": "sspai_editorial"},
                })
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])

                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["style"], "sspai_editorial")

    def test_prepare_plan_records_failure_stage_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.render_vertical_previews", side_effect=RuntimeError("preview failed")),
            ):
                job = create_job("GH-HOTLIST-20990101-PREPARE-FAIL", {
                    "project_count": 2,
                    "template_params": {"render_engine": "pil"},
                })
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})

                with self.assertRaises(RuntimeError):
                    prepare_plan(job["id"])

                detail = job_detail(job["id"])
                job_dir = jobs_dir / job["id"]

            self.assertEqual(detail["job"]["status"], "failed")
            self.assertEqual(detail["job"]["stage"], "preparing_plan")
            self.assertEqual(detail["failed_stage"], "preparing_plan")
            self.assertIn("preview failed", detail["job"]["error"])
            self.assertIn("计划文件生成失败", detail["log_tail"])
            self.assertFalse((job_dir / "asset_manifest.json").exists())
            self.assertFalse((job_dir / "shot_plan.json").exists())
            self.assertFalse((job_dir / "script.json").exists())
            self.assertFalse((job_dir / "info.json").exists())
            self.assertTrue((job_dir / "selected_projects.json").exists())
            self.assertTrue((job_dir / "narration.json").exists())

    def test_plan_validation_failure_can_retry_same_job(self) -> None:
        async def pipeline(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError("dry run failed")
            return Path(kwargs["from_plan"])

        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=pipeline),
            ):
                job = create_job("GH-HOTLIST-20990101-VALIDATE-RETRY", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])

                with self.assertRaises(RuntimeError):
                    asyncio.run(validate_plan(job["id"]))

                failed = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(failed["status"], "failed")
                self.assertEqual(failed["failed_stage"], "preparing_plan")

                retried_plan = prepare_plan(job["id"])
                result = asyncio.run(validate_plan(job["id"]))

                self.assertEqual(retried_plan["job"]["status"], "awaiting_validation")
                self.assertEqual(result["job"]["status"], "ready_to_render")
                self.assertEqual(result["job"]["failed_stage"], "")
                self.assertEqual(result["plan_validation"]["status"], "passed")
                self.assertEqual(len(calls), 2)

    def test_reselecting_projects_clears_stale_plan_artifacts(self) -> None:
        async def dry_run_pipeline(**kwargs):
            return Path(kwargs["from_plan"])

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=dry_run_pipeline),
            ):
                job = create_job("GH-HOTLIST-20990101-STALE-SELECTION", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])
                asyncio.run(validate_plan(job["id"]))

                job_dir = jobs_dir / job["id"]
                self.assertTrue((job_dir / "shot_plan.json").exists())
                self.assertTrue((job_dir / "preview_frames").exists())
                update_job(job["id"], status="awaiting_input", stage="awaiting_project_confirmation")

                save_selection(job["id"], {"items": list(reversed(_sample_projects()))})

                self.assertFalse((job_dir / "shot_plan.json").exists())
                self.assertFalse((job_dir / "preview_frames").exists())
                self.assertEqual(read_json(job_dir / "task.json", {})["plan_validation"]["status"], "not_run")

    def test_reselecting_projects_clears_stale_script_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-STALE-META", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})

                job_dir = jobs_dir / job["id"]
                self.assertTrue((job_dir / "quality_report.json").exists())
                self.assertTrue((job_dir / "publish_pack.json").exists())
                update_job(job["id"], status="awaiting_input", stage="awaiting_project_confirmation")

                save_selection(job["id"], {"items": list(reversed(_sample_projects()))})

                self.assertFalse((job_dir / "quality_report.json").exists())
                self.assertFalse((job_dir / "publish_pack.json").exists())
                detail = job_detail(job["id"])
                self.assertEqual(detail["quality_report"], {})
                self.assertEqual(detail["publish_pack"], {})

    def test_resaving_script_clears_stale_plan_artifacts(self) -> None:
        async def dry_run_pipeline(**kwargs):
            return Path(kwargs["from_plan"])

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=dry_run_pipeline),
            ):
                job = create_job("GH-HOTLIST-20990101-STALE-SCRIPT", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])
                asyncio.run(validate_plan(job["id"]))

                job_dir = jobs_dir / job["id"]
                (job_dir / "final.mp4").write_bytes(b"stale video")
                official = job_dir / f"{job['id']}-旧正式版.mp4"
                official.write_bytes(b"stale official")
                update_job(job["id"], official_video=str(official))
                update_job(job["id"], status="awaiting_input", stage="awaiting_script_confirmation")

                edited_segments = [
                    {**segment, "text": "新版口播" if segment["id"] == "intro" else segment["text"]}
                    for segment in selection["segments"]
                ]
                save_script(job["id"], {"segments": edited_segments})

                self.assertFalse((job_dir / "shot_plan.json").exists())
                self.assertFalse((job_dir / "cover_frame.png").exists())
                self.assertFalse((job_dir / "final.mp4").exists())
                self.assertTrue((job_dir / f"{job['id']}-旧正式版.mp4").exists())
                saved = read_json(job_dir / "task.json", {})
                self.assertEqual(saved["plan_validation"]["status"], "not_run")
                self.assertEqual(saved["official_video"], "")

    def test_save_script_rejects_incomplete_segments_without_clearing_plan(self) -> None:
        async def dry_run_pipeline(**kwargs):
            return Path(kwargs["from_plan"])

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=dry_run_pipeline),
            ):
                job = create_job("GH-HOTLIST-20990101-INCOMPLETE-SCRIPT", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])

                job_dir = jobs_dir / job["id"]
                self.assertTrue((job_dir / "shot_plan.json").exists())
                update_job(job["id"], status="awaiting_input", stage="awaiting_script_confirmation")

                with self.assertRaisesRegex(ValueError, "口播脚本缺少段落"):
                    save_script(job["id"], {"segments": [{"id": "intro", "label": "开场", "text": "只有开场"}]})

                self.assertTrue((job_dir / "shot_plan.json").exists())
                saved_segments = read_json(job_dir / "narration.json", {})["segments"]
                self.assertEqual([segment["id"] for segment in saved_segments], ["intro", "project-1", "project-2", "outro"])

    def test_render_video_auto_validates_unchecked_plan(self) -> None:
        async def pipeline(**kwargs):
            calls.append(kwargs)
            return Path(kwargs["from_plan"])

        async def hyperframes(projects, output_path=None, **kwargs):
            render_calls.append({"projects": projects, "output_path": output_path, **kwargs})
            stage_callback = kwargs.get("stage_callback")
            if stage_callback:
                stage_callback("generating_tts", "开始生成 TTS 语音。")
                stage_callback("composing_html", "开始生成 HTML 画面。")
                stage_callback("rendering_hyperframes", "开始使用 HyperFrames 渲染动画视频。")
                stage_callback("mixing_audio", "开始混合 TTS 音频。")
            write_json(Path(output_path).parent / "video-spec.json", {
                "schema_version": "hotlist-video-spec.v1",
                "video_basics": {"total_duration": 8.0},
                "visual": {"theme_source": "legacy_style_profile", "theme": "tech_hotspot"},
                "scenes": [{"id": "scene-01-intro"}, {"id": "scene-02-ranking"}],
            })
            Path(output_path).write_bytes(b"video")
            return Path(output_path)

        calls = []
        render_calls = []
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=pipeline),
                patch("src.console.jobs.render_hotlist_v2_from_projects", side_effect=hyperframes),
                patch("src.console.jobs.post_process_video", return_value=None),
            ):
                job = create_job("GH-HOTLIST-20990101-009", {
                    "project_count": 2,
                    "title": "自动校验",
                    "template_params": _with_output_dir(tmp, {"bgm": "none"}),
                })
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])

                result = asyncio.run(render_video(job["id"]))

                self.assertEqual(result["job"]["status"], "completed")
                self.assertEqual(len(calls), 1)
                self.assertTrue(calls[0]["dry_run"])
                self.assertEqual(len(render_calls), 1)
                self.assertEqual(render_calls[0]["style"], "tech_hotspot")
                self.assertEqual([segment["id"] for segment in render_calls[0]["narration_segments"]], ["intro", "project-1", "project-2", "outro"])
                self.assertIn("stage_callback", render_calls[0])
                self.assertEqual(result["job"]["plan_validation"]["status"], "passed")
                spec_report = job_detail(job["id"])["video_spec_report"]
                self.assertEqual(spec_report["status"], "ready")
                self.assertEqual(spec_report["schema_version"], "hotlist-video-spec.v1")
                self.assertEqual(spec_report["scene_count"], 2)
                self.assertEqual(spec_report["theme_source"], "legacy_style_profile")
                relevant = [
                    item["stage"]
                    for item in result["job"]["stage_history"]
                    if item["stage"] in {"generating_tts", "composing_html", "rendering_hyperframes", "mixing_audio", "post_processing"}
                ]
                self.assertEqual(
                    relevant,
                    ["generating_tts", "composing_html", "rendering_hyperframes", "mixing_audio", "post_processing"],
                )

    def test_render_video_records_precise_hyperframes_failed_stage(self) -> None:
        async def pipeline(**kwargs):
            return Path(kwargs["from_plan"])

        async def hyperframes(projects, output_path=None, **kwargs):
            stage_callback = kwargs.get("stage_callback")
            if stage_callback:
                stage_callback("generating_tts", "开始生成 TTS 语音。")
                stage_callback("composing_html", "开始生成 HTML 画面。")
            raise RuntimeError("html composition crashed")

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=pipeline),
                patch("src.console.jobs.render_hotlist_v2_from_projects", side_effect=hyperframes),
            ):
                job = create_job("GH-HOTLIST-20990101-HF-STAGE-FAIL", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])

                with self.assertRaisesRegex(RuntimeError, "html composition crashed"):
                    asyncio.run(render_video(job["id"]))

                detail = job_detail(job["id"])

                self.assertEqual(detail["job"]["status"], "failed")
                self.assertEqual(detail["job"]["stage"], "composing_html")
                self.assertEqual(detail["failed_stage"], "composing_html")
                self.assertIn("开始生成 HTML 画面。", detail["logs"])
                self.assertIn("html composition crashed", detail["log_tail"])

    def test_render_video_uses_selected_hyperframes_style(self) -> None:
        async def pipeline(**kwargs):
            calls.append(kwargs)
            return Path(kwargs["from_plan"])

        async def hyperframes(projects, output_path=None, **kwargs):
            render_calls.append({"projects": projects, "output_path": output_path, **kwargs})
            Path(output_path).write_bytes(b"video")
            return Path(output_path)

        calls = []
        render_calls = []
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=pipeline),
                patch("src.console.jobs.render_hotlist_v2_from_projects", side_effect=hyperframes),
                patch("src.console.jobs.post_process_video", return_value=None),
            ):
                job = create_job("GH-HOTLIST-20990101-HF-STYLE-RENDER", {
                    "project_count": 2,
                    "template_params": _with_output_dir(tmp, {"style": "apple_minimal", "bgm": "none"}),
                })
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])

                asyncio.run(render_video(job["id"]))

                self.assertEqual(len(render_calls), 1)
                self.assertEqual(render_calls[0]["style"], "apple_minimal")

    def test_render_video_passes_custom_bgm_path(self) -> None:
        async def pipeline(**kwargs):
            calls.append(kwargs)
            return Path(kwargs["from_plan"])

        async def hyperframes(projects, output_path=None, **kwargs):
            Path(output_path).write_bytes(b"video")
            return Path(output_path)

        calls = []
        post_calls = []
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            bgm_file = Path(tmp) / "custom.mp3"
            bgm_file.write_bytes(b"audio")
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=pipeline),
                patch("src.console.jobs.render_hotlist_v2_from_projects", side_effect=hyperframes),
                patch("src.console.jobs.post_process_video", side_effect=lambda *args, **kwargs: post_calls.append((args, kwargs)) or Path(args[0])),
            ):
                job = create_job("GH-HOTLIST-20990101-BGM", {
                    "project_count": 2,
                    "template_params": _with_output_dir(tmp, {"bgm": "custom", "bgm_path": str(bgm_file), "bgm_volume": 0.42}),
                })
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])

                result = asyncio.run(render_video(job["id"]))

                self.assertEqual(result["job"]["status"], "completed")
                self.assertEqual(len(calls), 1)
                self.assertEqual(post_calls[0][1]["bgm_path"], str(bgm_file))
                self.assertEqual(post_calls[0][1]["bgm_volume"], 0.42)
                self.assertFalse(post_calls[0][1]["no_bgm"])

    def test_render_video_fails_for_missing_custom_bgm_path(self) -> None:
        async def hyperframes(projects, output_path=None, **kwargs):
            Path(output_path).write_bytes(b"video")
            return Path(output_path)

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            missing = Path(tmp) / "missing.mp3"
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.render_hotlist_v2_from_projects", side_effect=hyperframes),
            ):
                job = create_job("GH-HOTLIST-20990101-BGM-MISSING", {
                    "project_count": 2,
                    "template_params": {"bgm": "custom", "bgm_path": str(missing)},
                })
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])
                asyncio.run(validate_plan(job["id"]))

                with self.assertRaises(ValueError):
                    asyncio.run(render_video(job["id"]))

                detail = job_detail(job["id"])
                self.assertEqual(detail["job"]["status"], "failed")
                self.assertIn("自定义 BGM 文件不存在", detail["job"]["error"])

    def test_render_video_records_preflight_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
            ):
                job = create_job("GH-HOTLIST-20990101-010", {"project_count": 2})
                update_job(job["id"], status="awaiting_render", stage="preparing_plan")

                with self.assertRaises(ValueError):
                    asyncio.run(render_video(job["id"]))

                detail = job_detail(job["id"])
                self.assertEqual(detail["job"]["status"], "failed")
                self.assertEqual(detail["failed_stage"], "preparing_plan")
                self.assertIn("请先确认项目列表", detail["job"]["error"])

    def test_selection_uses_model_narration_when_available(self) -> None:
        captured = {}

        def chat(task: str, system: str, prompt: str, max_tokens: int = 0):
            captured[task] = json.loads(prompt)
            return {
                "data": {
                    "segments": [
                        {"id": "intro", "label": "开场", "text": "今天看两个真正能落地的开源项目。"},
                        {"id": "project-1", "label": "第 1 名", "text": "很多人以为 alpha 只是 AI 工作流工具，但它真正解决的是把模型接进开发步骤。少掉来回补脚本的时间。适合：被 AI 流程落地折磨的工程师。"},
                        {"id": "project-2", "label": "第 2 名", "text": "很多人以为 beta 只是命令行助手，但它爽在把重复命令收成一条短路径。少翻文档，少切窗口。适合：被终端杂活拖慢的人。"},
                        {"id": "outro", "label": "结尾", "text": "想看实操拆解，就从你最卡的项目开始。"},
                    ]
                },
                "route": {"provider_name": "Mock", "model": "mock-model"},
                "raw": "{}",
                "error": "",
            }

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.model_router.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.jobs.chat_json_detail", side_effect=chat),
            ):
                job = create_job("GH-HOTLIST-20990101-002", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                result = save_selection(job["id"], {"items": _sample_projects()})

                self.assertEqual(result["segments"][0]["text"], "今天看两个真正能落地的开源项目。")
                narration_prompt = captured["narration_generation"]
                self.assertIn("project_highlight", narration_prompt["projects"][0])
                self.assertIn("viewer_benefit", narration_prompt["projects"][0])
                self.assertEqual(narration_prompt["projects"][0]["viewer_pain"], "AI 难接进真实工作流")
                self.assertEqual(narration_prompt["projects"][0]["safe_highlight"], "把 AI 流程接进具体开发步骤")
                self.assertIn("content_strategy", narration_prompt)
                self.assertIn("不复述第 1 名详情", narration_prompt["content_strategy"]["opening"])
                self.assertIn("反常识或场景化开头", narration_prompt["instruction"])
                self.assertIn("如果你纠结", narration_prompt["instruction"])
                self.assertIn("project_copy_template", narration_prompt)
                self.assertIn("榜单总览只讲整体趋势", narration_prompt["instruction"])
                self.assertIn("visual_potential 是制作侧画面建议", narration_prompt["instruction"])
                self.assertIn("README 可展示", narration_prompt["instruction"])
                logs = (jobs_dir / job["id"] / "logs.txt").read_text(encoding="utf-8")
                self.assertIn("口播生成已使用 Mock / mock-model", logs)
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                narration_call = next(item for item in saved["model_calls"] if item["task"] == "narration_generation")
                self.assertEqual(narration_call["provider"], "Mock")
                self.assertEqual(narration_call["model"], "mock-model")
                self.assertEqual(narration_call["status"], "success")
                self.assertNotIn("api_key", narration_call)
                self.assertEqual(saved["narration_source"]["status"], "ai_success")
                self.assertEqual(saved["narration_source"]["provider"], "Mock")
                self.assertEqual(saved["narration_source"]["model"], "mock-model")
                source_file = read_json(jobs_dir / job["id"] / "narration_source.json", {})
                self.assertEqual(source_file["status"], "ai_success")
                self.assertEqual(job_detail(job["id"])["latest_model_call"], saved["model_calls"][-1])
                self.assertEqual(job_detail(job["id"])["narration_source"]["status"], "ai_success")

    def test_model_narration_with_producer_visual_jargon_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.model_router.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": {
                        "segments": [
                            {"id": "intro", "label": "开场", "text": "今天看两个项目。"},
                            {"id": "project-1", "label": "第 1 名", "text": "亮点是 README 可展示。"},
                            {"id": "project-2", "label": "第 2 名", "text": "beta 能减少重复命令。"},
                            {"id": "outro", "label": "结尾", "text": "想看哪个，评论区告诉我。"},
                        ]
                    },
                    "route": {"provider_name": "Mock", "model": "mock-model"},
                    "raw": "{}",
                    "error": "",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-NARRATION-JARGON", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                result = save_selection(job["id"], {"items": _sample_projects()})

                project_line = next(segment["text"] for segment in result["segments"] if segment["id"] == "project-1")
                self.assertNotIn("README 可展示", project_line)
                self.assertIn("alpha 的核心动作是", project_line)
                self.assertIn("把 AI 流程接进具体开发步骤", project_line)
                self.assertNotIn("先看它", project_line)
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"][0]["status"], "invalid_json")
                self.assertEqual(saved["narration_source"]["status"], "ai_failed_fallback")

    def test_model_narration_with_forbidden_opening_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.model_router.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": {
                        "segments": [
                            {"id": "intro", "label": "开场", "text": "今天看两个项目。"},
                            {"id": "project-1", "label": "第 1 名", "text": "如果你纠结哪个项目值得花时间，先看看它，很有价值。"},
                            {"id": "project-2", "label": "第 2 名", "text": "很多人以为 beta 只是命令行助手，但它把重复命令收成短路径。适合：被终端杂活拖慢的人。"},
                            {"id": "outro", "label": "结尾", "text": "想看哪个，评论区告诉我。"},
                        ]
                    },
                    "route": {"provider_name": "Mock", "model": "mock-model"},
                    "raw": "{}",
                    "error": "",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-NARRATION-FORBIDDEN", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                result = save_selection(job["id"], {"items": _sample_projects()})

                project_line = next(segment["text"] for segment in result["segments"] if segment["id"] == "project-1")
                self.assertNotIn("如果你纠结", project_line)
                self.assertNotIn("先看看它", project_line)
                self.assertNotIn("很有价值", project_line)
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["narration_source"]["status"], "ai_failed_fallback")

    def test_invalid_model_narration_response_is_saved_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.model_router.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": None,
                    "route": {"provider_name": "Mock", "model": "mock-model"},
                    "raw": "不是 JSON",
                    "error": "Expecting value",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-005", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                result = save_selection(job["id"], {"items": _sample_projects()})

                self.assertIn("别再只按 Star 收藏项目了", result["segments"][0]["text"])
                raw = read_json(jobs_dir / job["id"] / "ai-response-narration_generation.json", {})
                self.assertEqual(raw["raw"], "不是 JSON")
                self.assertEqual(raw["model"], "mock-model")
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"][0]["status"], "invalid_json")
                self.assertEqual(saved["narration_source"]["status"], "ai_failed_fallback")
                self.assertEqual(saved["narration_source"]["provider"], "Mock")
                self.assertEqual(saved["narration_source"]["model"], "mock-model")
                self.assertEqual(job_detail(job["id"])["narration_source"]["status"], "ai_failed_fallback")

    def test_candidate_analysis_invalid_response_is_saved_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            candidates = _sample_projects()
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.model_router.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": None,
                    "route": {"provider_name": "Mock", "model": "mock-model"},
                    "raw": "<html>bad</html>",
                    "error": "Expecting value",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-006", {"project_count": 2})
                from src.console.jobs import _analyze_candidates

                result = _analyze_candidates(job["id"], candidates)

                self.assertEqual(result, candidates)
                raw = read_json(jobs_dir / job["id"] / "ai-response-candidate_analysis.json", {})
                self.assertEqual(raw["raw"], "<html>bad</html>")
                self.assertEqual(raw["provider"], "Mock")
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"][0]["task"], "candidate_analysis")
                self.assertEqual(saved["model_calls"][0]["status"], "invalid_json")
                self.assertEqual(saved["candidate_source"]["analysis_status"], "ai_failed_fallback")
                self.assertIn("回退启发式", saved["candidate_source"]["analysis_label"])

    def test_candidate_analysis_sends_up_to_30_candidates_to_model(self) -> None:
        captured = {}

        def chat(task: str, system: str, prompt: str, max_tokens: int = 0):
            captured["task"] = task
            captured["prompt"] = json.loads(prompt)
            captured["max_tokens"] = max_tokens
            return {
                "data": {
                    "items": [
                        {
                            "index": 30,
                            "description_zh": "第 30 个项目也经过模型分析",
                            "recommendation": "补足 20-30 个候选的分析覆盖",
                            "project_highlight": "自动整理开发流程",
                            "viewer_benefit": "减少重复判断成本",
                            "risk": "仍需人工确认",
                            "audience": "开发者",
                            "visual_potential": "README 可展示",
                            "score": 77,
                        }
                    ]
                },
                "route": {"provider_name": "Mock", "model": "analysis-model"},
                "raw": "{}",
                "error": "",
            }

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            candidates = [
                {
                    "name": f"repo-{index}",
                    "full_name": f"demo/repo-{index}",
                    "description": f"project {index}",
                    "stars": 100 + index,
                    "language": "Python",
                    "topics": ["tool"],
                    "homepage": "",
                    "score": 50,
                }
                for index in range(1, 32)
            ]
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "analysis-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.jobs.chat_json_detail", side_effect=chat),
            ):
                job = create_job("GH-HOTLIST-20990101-ANALYSIS-30", {"project_count": 10})
                from src.console.jobs import _analyze_candidates

                result = _analyze_candidates(job["id"], candidates)
                saved = read_json(jobs_dir / job["id"] / "task.json", {})

        self.assertEqual(captured["task"], "candidate_analysis")
        self.assertEqual(captured["max_tokens"], 5000)
        self.assertEqual(len(captured["prompt"]["items"]), 30)
        self.assertIn("禁止使用同一句模板", captured["prompt"]["instruction"])
        self.assertIn("围绕……重点是", captured["prompt"]["instruction"])
        self.assertEqual(captured["prompt"]["items"][-1]["full_name"], "demo/repo-30")
        self.assertIn("project_highlight", captured["prompt"]["schema"]["items"][0])
        self.assertIn("viewer_benefit", captured["prompt"]["schema"]["items"][0])
        self.assertEqual(result[29]["description_zh"], "第 30 个项目也经过模型分析")
        self.assertEqual(result[29]["project_highlight"], "自动整理开发流程")
        self.assertEqual(result[29]["viewer_benefit"], "减少重复判断成本")
        self.assertEqual(result[30]["description"], "project 31")
        self.assertEqual(saved["candidate_source"]["analysis_status"], "ai_success")
        self.assertIn("AI 分析：Mock / analysis-model", saved["candidate_source"]["analysis_label"])

    def test_generate_candidates_uses_hotlist_ranking_when_available(self) -> None:
        async def collect(**kwargs):
            return {"items": _sample_projects(), "rate_limit": "ok"}

        def route(task: str) -> dict[str, str]:
            if task == "hotlist_ranking":
                return {
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "rank-model",
                    "enabled": "1",
                    "configured": "1",
                }
            return {"provider": "", "provider_name": "", "model": "", "enabled": "", "configured": ""}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.collect_candidates_with_meta", side_effect=collect),
                patch("src.console.jobs.route_snapshot", side_effect=route),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": {
                        "items": [
                            {"index": 2, "rank": 1, "reason": "CLI 工具更容易演示。"},
                            {"index": 1, "rank": 2, "reason": "AI 工作流适合放在第二个讲。"},
                        ]
                    },
                    "route": {"provider_name": "Mock", "model": "rank-model"},
                    "raw": "{}",
                    "error": "",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-RANK", {"project_count": 2})
                result = asyncio.run(generate_candidates(job["id"]))

                self.assertEqual([item["name"] for item in result["candidates"]], ["beta", "alpha"])
                self.assertEqual(result["candidates"][0]["ai_rank"], 1)
                self.assertEqual(result["candidates"][0]["ranking_reason"], "CLI 工具更容易演示。")
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"][0]["task"], "hotlist_ranking")
                self.assertEqual(saved["model_calls"][0]["status"], "success")
                self.assertEqual(saved["candidate_source"]["ranking_status"], "ai_success")
                self.assertIn("analyzing_candidates", [item["stage"] for item in saved["stage_history"]])

    def test_generate_candidates_records_analysis_failure_stage(self) -> None:
        async def collect(**kwargs):
            return {"items": _sample_projects(), "rate_limit": "ok"}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.collect_candidates_with_meta", side_effect=collect),
                patch("src.console.jobs._analyze_candidates", side_effect=RuntimeError("analysis failed")),
            ):
                job = create_job("GH-HOTLIST-20990101-ANALYSIS-FAIL", {"project_count": 2})

                with self.assertRaises(RuntimeError):
                    asyncio.run(generate_candidates(job["id"]))

                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["status"], "failed")
                self.assertEqual(saved["failed_stage"], "analyzing_candidates")

    def test_generate_candidates_clears_stale_candidate_snapshot_on_retry_failure(self) -> None:
        async def collect(**kwargs):
            return {"items": _sample_projects(), "rate_limit": "ok"}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.collect_candidates_with_meta", side_effect=collect),
            ):
                job = create_job("GH-HOTLIST-20990101-CANDIDATE-STALE", {"project_count": 2})
                asyncio.run(generate_candidates(job["id"]))
                self.assertTrue((jobs_dir / job["id"] / "candidates.json").exists())
                update_job(job["id"], status="failed", stage="analyzing_candidates")

                with patch("src.console.jobs._analyze_candidates", side_effect=RuntimeError("analysis failed")):
                    with self.assertRaises(RuntimeError):
                        asyncio.run(generate_candidates(job["id"]))

                detail = job_detail(job["id"])
                self.assertFalse((jobs_dir / job["id"] / "candidates.json").exists())
                self.assertEqual(detail["candidates"], [])
                self.assertEqual(detail["job"]["failed_stage"], "analyzing_candidates")

    def test_generate_candidates_retries_after_analysis_failure(self) -> None:
        async def collect(**kwargs):
            return {"items": _sample_projects(), "rate_limit": "ok"}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.collect_candidates_with_meta", side_effect=collect),
            ):
                job = create_job("GH-HOTLIST-20990101-ANALYSIS-RETRY", {"project_count": 2})
                with patch("src.console.jobs._analyze_candidates", side_effect=RuntimeError("analysis failed")):
                    with self.assertRaises(RuntimeError):
                        asyncio.run(generate_candidates(job["id"]))

                with patch("src.console.jobs._analyze_candidates", side_effect=lambda _job_id, candidates: candidates):
                    result = asyncio.run(generate_candidates(job["id"]))

                self.assertEqual(result["job"]["status"], "awaiting_input")
                self.assertEqual(result["job"]["stage"], "awaiting_project_confirmation")
                self.assertEqual([item["name"] for item in result["candidates"]], ["alpha", "beta"])
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["failed_stage"], "")

    def test_generate_candidates_keeps_default_order_when_ranking_is_invalid(self) -> None:
        async def collect(**kwargs):
            return {"items": _sample_projects(), "rate_limit": "ok"}

        def route(task: str) -> dict[str, str]:
            if task == "hotlist_ranking":
                return {
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "rank-model",
                    "enabled": "1",
                    "configured": "1",
                }
            return {"provider": "", "provider_name": "", "model": "", "enabled": "", "configured": ""}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.collect_candidates_with_meta", side_effect=collect),
                patch("src.console.jobs.route_snapshot", side_effect=route),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": {"items": []},
                    "route": {"provider_name": "Mock", "model": "rank-model"},
                    "raw": "{\"items\":[]}",
                    "error": "",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-RANK-BAD", {"project_count": 2})
                result = asyncio.run(generate_candidates(job["id"]))

                self.assertEqual([item["name"] for item in result["candidates"]], ["alpha", "beta"])
                raw = read_json(jobs_dir / job["id"] / "ai-response-hotlist_ranking.json", {})
                self.assertEqual(raw["model"], "rank-model")
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"][0]["task"], "hotlist_ranking")
                self.assertEqual(saved["model_calls"][0]["status"], "invalid_json")
                self.assertEqual(saved["candidate_source"]["ranking_status"], "ai_failed_default")

    def test_generate_candidates_records_cache_and_fallback_source_summary(self) -> None:
        async def collect(**kwargs):
            return {"items": _sample_projects(), "rate_limit": "cached", "cache_status": "hit"}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.collect_candidates_with_meta", side_effect=collect),
            ):
                job = create_job("GH-HOTLIST-20990101-CANDIDATE-SOURCE", {"project_count": 2})
                result = asyncio.run(generate_candidates(job["id"]))

                detail = job_detail(job["id"])
                self.assertEqual(result["job"]["candidate_source"]["cache_status"], "hit")
                self.assertEqual(result["job"]["candidate_source"]["analysis_status"], "heuristic")
                self.assertEqual(result["job"]["candidate_source"]["ranking_status"], "default")
                self.assertIn("缓存命中", result["job"]["candidate_source"]["summary"])
                self.assertIn("启发式评分", detail["candidate_source"]["summary"])

    def test_selection_falls_back_when_model_is_unconfigured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "",
                    "configured": "",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-003", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                result = save_selection(job["id"], {"items": _sample_projects()})

                self.assertIn("别再只按 Star 收藏项目了", result["segments"][0]["text"])
                logs = (jobs_dir / job["id"] / "logs.txt").read_text(encoding="utf-8")
                self.assertIn("口播生成使用默认模板", logs)
                detail = job_detail(job["id"])
                self.assertEqual(detail["narration_source"]["status"], "model_skipped")
                self.assertEqual(detail["narration_source"]["reason"], "未配置模型路由")

    def test_default_project_narration_uses_problem_signal_audience_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-NARRATION-STRUCTURE", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                result = save_selection(job["id"], {"items": _sample_projects()})

            project_line = next(segment["text"] for segment in result["segments"] if segment["id"] == "project-1")

        self.assertIn("AI 难接进真实工作流", project_line)
        self.assertIn("alpha 的核心动作是：把 AI 流程接进具体开发步骤", project_line)
        self.assertIn("适合：被「AI 难接进真实工作流」折磨的 AI 开发者。", project_line)
        self.assertNotIn("如果你卡在", project_line)
        self.assertNotIn("先看它", project_line)
        self.assertNotIn("README 可展示", project_line)
        self.assertNotIn("亮点：", project_line)

    def test_selection_skips_model_when_configured_provider_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                    "last_test": "连接失败: bad model",
                    "available": "",
                }),
                patch("src.console.jobs.chat_json_detail") as chat,
            ):
                job = create_job("GH-HOTLIST-20990101-UNAVAILABLE", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                result = save_selection(job["id"], {"items": _sample_projects()})

                self.assertIn("别再只按 Star 收藏项目了", result["segments"][0]["text"])
                chat.assert_not_called()
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"], [])
                logs = (jobs_dir / job["id"] / "logs.txt").read_text(encoding="utf-8")
                self.assertIn("模型供应商最近连接测试失败", logs)
                self.assertNotIn("未配置模型路由", logs)

    def test_selection_uses_hook_generation_when_available(self) -> None:
        def route(task: str) -> dict[str, str]:
            if task == "hook_generation":
                return {
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "hook-model",
                    "enabled": "1",
                    "configured": "1",
                }
            return {"provider": "", "provider_name": "", "model": "", "enabled": "", "configured": ""}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", side_effect=route),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": {
                        "title": "本周值得看的开源项目",
                        "opening_hook": "这几个项目不是单纯热闹，而是能放进真实工作流。",
                        "closing_cta": "想看哪一个实操，直接留项目名。",
                    },
                    "route": {"provider_name": "Mock", "model": "hook-model"},
                    "raw": "{}",
                    "error": "",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-HOOK", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                result = save_selection(job["id"], {"items": _sample_projects()})

                self.assertEqual(result["hook"]["title"], "本周值得看的开源项目")
                self.assertEqual(result["job"]["title"], "本周值得看的开源项目")
                hook = read_json(jobs_dir / job["id"] / "hook.json", {})
                self.assertEqual(hook["opening_hook"], "这几个项目不是单纯热闹，而是能放进真实工作流。")
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"][0]["task"], "hook_generation")
                self.assertEqual(saved["model_calls"][0]["status"], "success")

    def test_selection_keeps_default_title_when_hook_generation_is_invalid(self) -> None:
        def route(task: str) -> dict[str, str]:
            if task == "hook_generation":
                return {
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "hook-model",
                    "enabled": "1",
                    "configured": "1",
                }
            return {"provider": "", "provider_name": "", "model": "", "enabled": "", "configured": ""}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", side_effect=route),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": {"title": "缺少钩子"},
                    "route": {"provider_name": "Mock", "model": "hook-model"},
                    "raw": "{\"title\":\"缺少钩子\"}",
                    "error": "",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-HOOK-BAD", {"project_count": 2, "title": "原始标题"})
                _mark_awaiting_project_confirmation(job["id"])
                result = save_selection(job["id"], {"items": _sample_projects()})

                self.assertEqual(result["job"]["title"], "原始标题")
                self.assertEqual(result["hook"]["status"], "invalid_json")
                raw = read_json(jobs_dir / job["id"] / "ai-response-hook_generation.json", {})
                self.assertEqual(raw["model"], "hook-model")
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"][0]["task"], "hook_generation")
                self.assertEqual(saved["model_calls"][0]["status"], "invalid_json")

    def test_selection_writes_default_hook_when_unconfigured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
            ):
                job = create_job("GH-HOTLIST-20990101-HOOK-SKIP", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                result = save_selection(job["id"], {"items": _sample_projects()})

                self.assertEqual(result["hook"]["status"], "skipped")
                hook = read_json(jobs_dir / job["id"] / "hook.json", {})
                self.assertEqual(hook["title"], "GitHub热榜2个项目")
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"], [])

    def test_selection_uses_script_polishing_when_available(self) -> None:
        def route(task: str) -> dict[str, str]:
            if task == "script_polishing":
                return {
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "polish-model",
                    "enabled": "1",
                    "configured": "1",
                }
            return {"provider": "", "provider_name": "", "model": "", "enabled": "", "configured": ""}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", side_effect=route),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": {
                        "segments": [
                            {"id": "intro", "label": "开场", "text": "今天挑两个更值得上手的 GitHub 项目。"},
                            {"id": "project-1", "label": "第 1 名", "text": "alpha 的重点是把 AI 工作流变得更容易接入。"},
                            {"id": "project-2", "label": "第 2 名", "text": "beta 适合减少命令行里的重复切换。"},
                            {"id": "outro", "label": "结尾", "text": "想看实操拆解，可以先从最卡的一步开始。"},
                        ]
                    },
                    "route": {"provider_name": "Mock", "model": "polish-model"},
                    "raw": "{}",
                    "error": "",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-POLISH", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                result = save_selection(job["id"], {"items": _sample_projects()})

                self.assertEqual(result["segments"][0]["text"], "今天挑两个更值得上手的 GitHub 项目。")
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"][0]["task"], "script_polishing")
                self.assertEqual(saved["model_calls"][0]["status"], "success")

    def test_selection_keeps_original_script_when_polishing_is_invalid(self) -> None:
        def route(task: str) -> dict[str, str]:
            if task == "script_polishing":
                return {
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "polish-model",
                    "enabled": "1",
                    "configured": "1",
                }
            return {"provider": "", "provider_name": "", "model": "", "enabled": "", "configured": ""}

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", side_effect=route),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": {"segments": [{"id": "intro", "label": "开场", "text": "缺少其他段落"}]},
                    "route": {"provider_name": "Mock", "model": "polish-model"},
                    "raw": "{\"segments\":[]}",
                    "error": "",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-POLISH-BAD", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                result = save_selection(job["id"], {"items": _sample_projects()})

                self.assertIn("别再只按 Star 收藏项目了", result["segments"][0]["text"])
                raw = read_json(jobs_dir / job["id"] / "ai-response-script_polishing.json", {})
                self.assertEqual(raw["model"], "polish-model")
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"][0]["task"], "script_polishing")
                self.assertEqual(saved["model_calls"][0]["status"], "invalid_json")

    def test_selection_skips_script_polishing_when_unconfigured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
            ):
                job = create_job("GH-HOTLIST-20990101-POLISH-SKIP", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                result = save_selection(job["id"], {"items": _sample_projects()})

                self.assertIn("别再只按 Star 收藏项目了", result["segments"][0]["text"])
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"], [])
                logs = (jobs_dir / job["id"] / "logs.txt").read_text(encoding="utf-8")
                self.assertIn("脚本润色跳过", logs)

    def test_save_script_writes_quality_report_when_fact_check_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.model_router.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": {
                        "status": "pass",
                        "summary": "脚本事实风险低，表达清楚。",
                        "risk_flags": [],
                        "factual_notes": [],
                        "overclaim_notes": [],
                        "readability_score": 92,
                    },
                    "route": {"provider_name": "Mock", "model": "mock-model"},
                    "raw": "{}",
                    "error": "",
                }),
                patch("src.console.model_router.chat_json_detail", return_value={
                    "data": {
                        "status": "pass",
                        "summary": "脚本事实风险低，表达清楚。",
                        "risk_flags": [],
                        "factual_notes": [],
                        "overclaim_notes": [],
                        "readability_score": 92,
                    },
                    "route": {"provider_name": "Mock", "model": "mock-model"},
                    "raw": "{}",
                    "error": "",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-QA", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                result = save_script(job["id"], {"segments": selection["segments"]})

                self.assertEqual(result["job"]["status"], "awaiting_render")
                report = read_json(jobs_dir / job["id"] / "quality_report.json", {})
                self.assertEqual(report["status"], "pass")
                self.assertEqual(report["provider"], "Mock")
                self.assertEqual(report["readability_score"], 92)
                self.assertEqual(report["issues"], [])
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"][-1]["task"], "fact_check")
                self.assertEqual(saved["model_calls"][-1]["status"], "success")

    def test_save_script_binds_quality_issues_to_project_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.model_router.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": {
                        "status": "caution",
                        "summary": "第 1 名口播有事实风险。",
                        "risk_flags": [],
                        "factual_notes": ["demo/alpha 这段把效果说满了，建议收敛。"],
                        "overclaim_notes": [],
                        "readability_score": 80,
                    },
                    "route": {"provider_name": "Mock", "model": "mock-model"},
                    "raw": "{}",
                    "error": "",
                }),
                patch("src.console.model_router.chat_json_detail", return_value={
                    "data": {
                        "status": "caution",
                        "summary": "第 1 名口播有事实风险。",
                        "risk_flags": [],
                        "factual_notes": ["demo/alpha 这段把效果说满了，建议收敛。"],
                        "overclaim_notes": [],
                        "readability_score": 80,
                    },
                    "route": {"provider_name": "Mock", "model": "mock-model"},
                    "raw": "{}",
                    "error": "",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-QA-ISSUES", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})

                result = save_script(job["id"], {"segments": selection["segments"]})

                self.assertEqual(result["job"]["status"], "awaiting_input")
                report = read_json(jobs_dir / job["id"] / "quality_report.json", {})
                self.assertEqual(report["issues"][0]["type"], "事实")
                self.assertEqual(report["issues"][0]["segment_id"], "project-1")

    def test_save_script_writes_publish_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
            ):
                job = create_job("GH-HOTLIST-20990101-PUBLISH", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                result = save_script(job["id"], {"segments": selection["segments"]})

                pack = result["publish_pack"]
                self.assertEqual(pack["title"], "GitHub热榜2个项目")
                self.assertIn("本期项目：", pack["description"])
                self.assertIn("demo/alpha", pack["description"])
                self.assertIn("数据说明：", pack["description"])
                self.assertIn("估算日均 star", pack["description"])
                self.assertIn("GitHub", pack["hashtags"])
                self.assertIn("AI工具", pack["hashtags"])
                self.assertIn("本周黑马：alpha", pack["cover_text"]["subhead"])
                self.assertIn("估算日均 star", pack["cover_text"]["subhead"])
                self.assertIn("不是真实新增 star", pack["data_note"])
                saved = read_json(jobs_dir / job["id"] / "publish_pack.json", {})
                self.assertEqual(saved["source_projects"], ["demo/alpha", "demo/beta"])
                detail = job_detail(job["id"])
                self.assertEqual(detail["publish_pack"]["title"], "GitHub热榜2个项目")

    def test_save_script_flags_growth_overclaim_in_quality_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.model_router.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": {
                        "status": "pass",
                        "summary": "整体通过",
                        "risk_flags": [],
                        "factual_notes": [],
                        "overclaim_notes": [],
                        "readability_score": 90,
                    },
                    "route": {"provider_name": "Mock", "model": "mock-model"},
                    "raw": "{}",
                    "error": "",
                }),
                patch("src.console.model_router.chat_json_detail", return_value={
                    "data": {
                        "status": "pass",
                        "summary": "整体通过",
                        "risk_flags": [],
                        "factual_notes": [],
                        "overclaim_notes": [],
                        "readability_score": 90,
                    },
                    "route": {"provider_name": "Mock", "model": "mock-model"},
                    "raw": "{}",
                    "error": "",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-QA-GROWTH", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                overclaimed = [
                    {**segment, "text": "alpha 今天涨了 300 star，已经证明它是这周最猛的项目。" if segment["id"] == "project-1" else segment["text"]}
                    for segment in selection["segments"]
                ]

                result = save_script(job["id"], {"segments": overclaimed})

                self.assertEqual(result["job"]["status"], "awaiting_input")
                report = read_json(jobs_dir / job["id"] / "quality_report.json", {})
                self.assertEqual(report["status"], "caution")
                self.assertFalse(report["passed"])
                self.assertTrue(any("估算日均 star" in flag for flag in report["risk_flags"]))
                self.assertTrue(any(issue.get("segment_id") == "project-1" for issue in report["issues"]))

    def test_save_script_blocks_when_fact_check_returns_invalid_json_until_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.model_router.route_snapshot", return_value={
                    "provider": "mock",
                    "provider_name": "Mock",
                    "model": "mock-model",
                    "enabled": "1",
                    "configured": "1",
                }),
                patch("src.console.jobs.chat_json_detail", return_value={
                    "data": None,
                    "route": {"provider_name": "Mock", "model": "mock-model"},
                    "raw": "坏响应",
                    "error": "Expecting value",
                }),
                patch("src.console.model_router.chat_json_detail", return_value={
                    "data": None,
                    "route": {"provider_name": "Mock", "model": "mock-model"},
                    "raw": "坏响应",
                    "error": "Expecting value",
                }),
            ):
                job = create_job("GH-HOTLIST-20990101-QA-BAD", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                result = save_script(job["id"], {"segments": selection["segments"]})

                self.assertEqual(result["job"]["status"], "awaiting_input")
                self.assertEqual(result["job"]["stage"], "awaiting_script_confirmation")
                report = read_json(jobs_dir / job["id"] / "quality_report.json", {})
                self.assertEqual(report["status"], "invalid_json")
                self.assertFalse(report["passed"])
                self.assertEqual(report["issues"], [])
                raw = read_json(jobs_dir / job["id"] / "ai-response-fact_check.json", {})
                self.assertEqual(raw["raw"], "坏响应")
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"][-1]["task"], "fact_check")
                self.assertEqual(saved["model_calls"][-1]["status"], "invalid_json")

                result = save_script(job["id"], {"segments": selection["segments"], "ignore_quality_risk": True})
                self.assertEqual(result["job"]["status"], "awaiting_render")
                report = read_json(jobs_dir / job["id"] / "quality_report.json", {})
                self.assertTrue(report["manual_override"])
                self.assertTrue(report["passed"])

    def test_save_script_marks_quality_report_unverified_when_fact_check_is_unconfigured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
            ):
                job = create_job("GH-HOTLIST-20990101-QA-SKIP", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                result = save_script(job["id"], {"segments": selection["segments"]})

                self.assertEqual(result["job"]["status"], "awaiting_render")
                report = read_json(jobs_dir / job["id"] / "quality_report.json", {})
                self.assertEqual(report["status"], "unverified")
                self.assertFalse(report["passed"])
                self.assertFalse(report["verified"])
                self.assertEqual(report["issues"], [])
                saved = read_json(jobs_dir / job["id"] / "task.json", {})
                self.assertEqual(saved["model_calls"], [])

    def test_job_numbering_and_finalize_do_not_overwrite_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            publish_dir = Path(tmp) / "published"
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                today = datetime.now().strftime("%Y%m%d")
                self.assertTrue(next_job_id("GH-HOTLIST").endswith("-001"))
                first = create_job(f"GH-HOTLIST-{today}-001", {
                    "title": "测试 视频",
                    "template_params": {"official_output_dir": str(publish_dir)},
                })
                self.assertTrue(next_job_id("GH-HOTLIST").endswith("-002"))

                final = jobs_dir / first["id"] / "final.mp4"
                final.write_bytes(b"video")
                update_job(first["id"], status="running", stage="post_processing")
                one = finalize_numbered_output(first["id"], "测试 视频")["job"]["official_video"]
                two = finalize_numbered_output(first["id"], "测试 视频")["job"]["official_video"]

                self.assertEqual(Path(one), publish_dir / f"GH-HOTLIST-{today}-第001期-测试-视频.mp4")
                self.assertEqual(Path(two), publish_dir / f"GH-HOTLIST-{today}-第001期-测试-视频-v2.mp4")
                self.assertEqual(Path(one).read_bytes(), b"video")
                self.assertEqual(Path(two).read_bytes(), b"video")
                self.assertTrue(final.exists())
                self.assertFalse((jobs_dir / first["id"] / Path(one).name).exists())
                versions = job_detail(first["id"])["video_versions"]
                self.assertEqual([item["name"] for item in versions], [
                    Path(two).name,
                ])
                self.assertTrue(versions[0]["is_official"])
                self.assertTrue(versions[0]["external"])

    def test_finalize_writes_official_video_only_to_configured_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            publish_dir = Path(tmp) / "published"
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-001", {
                    "title": "测试视频",
                    "template_params": {
                        "issue_number": 24,
                        "official_output_dir": str(publish_dir),
                    },
                })
                final = jobs_dir / job["id"] / "final.mp4"
                final.write_bytes(b"video")
                update_job(job["id"], status="running", stage="post_processing")

                result = finalize_numbered_output(job["id"], "测试视频")
                official = Path(result["job"]["official_video"])
                published = publish_dir / "GH-HOTLIST-20990101-第024期-测试视频.mp4"

                self.assertEqual(official, published)
                self.assertEqual(official.read_bytes(), b"video")
                self.assertEqual(published.read_bytes(), b"video")
                self.assertTrue(final.exists())
                self.assertFalse((jobs_dir / job["id"] / published.name).exists())

    def test_video_versions_sort_by_version_when_timestamps_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-VERSIONS", {"title": "版本排序"})
                job_dir = jobs_dir / job["id"]
                base = job_dir / f"{job['id']}-版本排序.mp4"
                second = job_dir / f"{job['id']}-版本排序-v2.mp4"
                third = job_dir / f"{job['id']}-版本排序-v3.mp4"
                for path in (third, base, second):
                    path.write_bytes(b"video")
                    path.touch()

                stamp = 4102444800
                for path in (base, second, third):
                    os.utime(path, (stamp, stamp))

                versions = job_detail(job["id"])["video_versions"]

            self.assertEqual([item["name"] for item in versions], [base.name, second.name, third.name])
            self.assertTrue(all("duration_seconds" in item for item in versions))

    def test_video_versions_skip_symlinked_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            outside = Path(tmp) / "outside.mp4"
            outside.write_bytes(b"outside")
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-VERSION-LINK", {})
                job_dir = jobs_dir / job["id"]
                real = job_dir / f"{job['id']}-真实版本.mp4"
                real.write_bytes(b"video")
                (job_dir / f"{job['id']}-外部链接-v2.mp4").symlink_to(outside)

                versions = job_detail(job["id"])["video_versions"]

            self.assertEqual([item["name"] for item in versions], [real.name])

    def test_job_numbering_reserves_existing_directory_without_valid_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir):
                today = datetime.now().strftime("%Y%m%d")
                reserved = jobs_dir / f"GH-HOTLIST-{today}-001"
                reserved.mkdir(parents=True)
                (reserved / "candidates.json").write_text("{}", encoding="utf-8")

                self.assertTrue(next_job_id("GH-HOTLIST").endswith("-002"))

    def test_create_job_rejects_existing_job_directory_without_overwriting_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir):
                existing = jobs_dir / "GH-HOTLIST-20990101-EXISTS"
                existing.mkdir(parents=True)
                (existing / "candidates.json").write_text("{\"items\": []}", encoding="utf-8")

                with self.assertRaises(ValueError) as context:
                    create_job(existing.name, {"title": "新任务"})

                saved_candidates = (existing / "candidates.json").read_text(encoding="utf-8")

            self.assertIn("任务目录已存在", str(context.exception))
            self.assertEqual(saved_candidates, "{\"items\": []}")
            self.assertFalse((existing / "task.json").exists())

    def test_finalize_rejects_unrendered_job_even_with_final_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("src.console.jobs.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-NOT-RENDERED", {"title": "未渲染"})
                final = jobs_dir / job["id"] / "final.mp4"
                final.write_bytes(b"stale video")
                update_job(job["id"], status="ready_to_render", stage="preparing_plan")

                with self.assertRaises(ValueError) as context:
                    finalize_numbered_output(job["id"], "未渲染")

                saved = read_json(jobs_dir / job["id"] / "task.json", {})

            self.assertIn("当前阶段不能生成带编号正式文件", str(context.exception))
            self.assertEqual(saved["status"], "ready_to_render")
            self.assertEqual(saved["stage"], "preparing_plan")

    def test_create_job_persists_template_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            params = {
                "style": "sspai_editorial",
                "subtitle_mode": "standard",
                "narration_tone": "calm_analysis",
                "bgm": "none",
                "bgm_path": "",
                "orientation": "horizontal",
            }
            with patch("src.console.store.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-004", {"template_params": params})

            self.assertEqual(job["template_params"]["style"], "sspai_editorial")
            self.assertEqual(job["template_params"]["render_engine"], "hyperframes")
            self.assertEqual(job["template_params"]["orientation"], "vertical")
            self.assertEqual(job["template_params"]["official_output_dir"], "/Users/leohang/Movies/GitHub热榜视频")
            saved = read_json(jobs_dir / job["id"] / "task.json", {})
            self.assertEqual(saved["template_params"], job["template_params"])

    def test_create_hotlist_job_locks_next_auto_issue_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
            ):
                create_job("GH-HOTLIST-20990101-OLD", {"template_params": {"issue_number": 26}})
                job = create_hotlist_job({"template_params": {"bgm": "none"}})

            self.assertEqual(job["template_params"]["issue_number"], 27)
            saved = read_json(jobs_dir / job["id"] / "task.json", {})
            self.assertEqual(saved["template_params"]["issue_number"], 27)

    def test_create_job_accepts_frontend_visual_style_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-VISUAL-STYLE", {
                    "template_params": {
                        "visual_style": "black_gold",
                        "subtitle_mode": "standard",
                        "bgm": "none",
                    },
                })

            self.assertEqual(job["template_params"]["style"], "chinese_editorial")
            self.assertEqual(job["template_params"]["render_engine"], "hyperframes")
            self.assertNotIn("visual_style", job["template_params"])

    def test_create_job_normalizes_time_window_and_template_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir):
                job = create_job("GH-HOTLIST-20990101-BAD-TEMPLATE", {
                    "time_window": "yearly",
                    "template_params": {
                        "project_count": "bad",
                        "style": "neon",
                        "subtitle_mode": "tiny",
                        "bgm": "loud",
                        "narration_tone": "salesy",
                        "orientation": "horizontal",
                    },
                })

            self.assertEqual(job["time_window"], "weekly")
            params = job["template_params"]
            self.assertEqual(params["project_count"], 5)
            self.assertEqual(params["style"], "tech_hotspot")
            self.assertEqual(params["render_engine"], "hyperframes")
            self.assertEqual(params["subtitle_mode"], "large_hook")
            self.assertEqual(params["bgm"], "default")
            self.assertEqual(params["narration_tone"], "professional_review")
            self.assertEqual(params["orientation"], "vertical")

    def test_create_job_normalizes_project_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with patch("src.console.store.JOBS_DIR", jobs_dir):
                small = create_job("GH-HOTLIST-20990101-SMALL", {"project_count": 3})
                bad = create_job("GH-HOTLIST-20990101-BAD-COUNT", {"project_count": "many"})

            self.assertEqual(small["project_count"], 5)
            self.assertEqual(bad["project_count"], 5)

    def test_render_video_records_failed_pipeline_stage_and_log_tail(self) -> None:
        async def failing_pipeline(**kwargs):
            if kwargs.get("dry_run"):
                return Path(kwargs["from_plan"])
            Path(kwargs["output"]).write_bytes(b"partial video")
            official = Path(kwargs["from_plan"]) / "GH-HOTLIST-20990101-007-旧正式版.mp4"
            official.write_bytes(b"stale official")
            kwargs["stage_callback"]("generating_tts", "开始生成 TTS 语音。")
            raise RuntimeError("tts service unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=failing_pipeline),
            ):
                job = create_job("GH-HOTLIST-20990101-007", {
                    "project_count": 2,
                    "template_params": {"style": "tech_dark", "render_engine": "pil"},
                })
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])
                update_job(job["id"], official_video=str(jobs_dir / job["id"] / "GH-HOTLIST-20990101-007-旧正式版.mp4"))

                with self.assertRaises(RuntimeError):
                    asyncio.run(render_video(job["id"]))

                detail = job_detail(job["id"])
                job_dir = jobs_dir / job["id"]
                self.assertEqual(detail["job"]["status"], "failed")
                self.assertEqual(detail["job"]["stage"], "generating_tts")
                self.assertEqual(detail["failed_stage"], "generating_tts")
                self.assertIn("tts service unavailable", detail["log_tail"])
                self.assertIn("generating_tts", [item["stage"] for item in detail["stage_history"]])
                self.assertFalse((job_dir / "final.mp4").exists())
                self.assertTrue((job_dir / "GH-HOTLIST-20990101-007-旧正式版.mp4").exists())
                self.assertTrue((job_dir / "shot_plan.json").exists())
                self.assertEqual(detail["job"]["official_video"], "")
                self.assertIn("历史正式视频版本仍保留", detail["log_tail"])

    def test_reselecting_projects_preserves_historical_official_video(self) -> None:
        async def dry_run_pipeline(**kwargs):
            return Path(kwargs["from_plan"])

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            with (
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.run_pipeline", side_effect=dry_run_pipeline),
            ):
                job = create_job("GH-HOTLIST-20990101-STALE-SELECTION-VIDEO", {"project_count": 2})
                _mark_awaiting_project_confirmation(job["id"])
                selection = save_selection(job["id"], {"items": _sample_projects()})
                save_script(job["id"], {"segments": selection["segments"]})
                prepare_plan(job["id"])
                asyncio.run(validate_plan(job["id"]))

                job_dir = jobs_dir / job["id"]
                official = job_dir / f"{job['id']}-旧正式版.mp4"
                official.write_bytes(b"official")
                update_job(job["id"], official_video=str(official))
                update_job(job["id"], status="awaiting_input", stage="awaiting_project_confirmation")

                save_selection(job["id"], {"items": list(reversed(_sample_projects()))})

                self.assertTrue(official.exists())
                saved = read_json(job_dir / "task.json", {})
                self.assertEqual(saved["official_video"], "")

def _sample_projects() -> list[dict[str, object]]:
    return [
        {
            "name": "alpha",
            "full_name": "demo/alpha",
            "repo_url": "https://github.com/demo/alpha",
            "stars": 1520,
            "daily_growth": "估算日均 star 约 +217/天",
            "description": "AI agent workflow",
            "description_zh": "AI 工作流工具",
            "recommendation": "解决重复操作",
            "project_highlight": "把 AI 流程接进具体开发步骤",
            "viewer_benefit": "减少从想法到执行的中间步骤",
            "visual_potential": "README 可展示",
            "audience": "AI 开发者",
        },
        {
            "name": "beta",
            "full_name": "demo/beta",
            "repo_url": "https://github.com/demo/beta",
            "stars": 88,
            "daily_growth": "估算日均 star 约 +12/天",
            "description": "CLI helper",
            "description_zh": "命令行助手",
            "recommendation": "减少切工具",
            "project_highlight": "把重复命令收拢成更短路径",
            "viewer_benefit": "少在终端和文档之间来回切换",
            "visual_potential": "终端截图可展示",
            "audience": "开发者",
        },
    ]


def _extra_projects(count: int) -> list[dict[str, object]]:
    return [
        {
            "name": f"extra-{index}",
            "full_name": f"demo/extra-{index}",
            "repo_url": f"https://github.com/demo/extra-{index}",
            "stars": 40 + index,
            "description": "extra project",
            "description_zh": "额外项目",
        }
        for index in range(1, count + 1)
    ]


def _mark_awaiting_project_confirmation(job_id: str) -> None:
    write_json(console_jobs.JOBS_DIR / job_id / "candidates.json", {"items": _sample_projects()})
    update_job(job_id, status="awaiting_input", stage="awaiting_project_confirmation")


if __name__ == "__main__":
    unittest.main()
