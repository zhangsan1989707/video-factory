from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.console.scheduler import run_due_scheduled_draft
from src.console.server import reconcile_running_job
from src.console.store import config_snapshot, read_json, update_config, update_job, update_scheduler_last_run, write_json


class ConsoleSchedulerTest(unittest.TestCase):
    def tearDown(self) -> None:
        import src.console.scheduler as scheduler
        scheduler._RUNNING_KEYS.clear()

    def test_daily_schedule_runs_once_when_due(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {"bgm": "none"},
                "last_run_date": "",
            })
            calls = []

            async def fake_generate(job_id: str) -> dict:
                calls.append(job_id)
                return {"job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_project_confirmation"}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
            ):
                first = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))
                second = run_due_scheduled_draft(datetime(2099, 1, 2, 10, 0))

            self.assertTrue(first["started"])
            self.assertTrue(first["job"]["scheduled"])
            self.assertEqual(first["job"]["schedule_mode"], "candidates_only")
            self.assertEqual(first["job"]["time_window"], "weekly")
            self.assertEqual(first["job"]["project_count"], 5)
            self.assertEqual(first["job"]["template_params"]["bgm"], "none")
            self.assertEqual(first["job"]["stage"], "awaiting_project_confirmation")
            self.assertEqual(second["reason"], "not_due")
            self.assertEqual(len(calls), 1)
            saved_job = read_json(jobs_dir / first["job"]["id"] / "task.json", {})
            self.assertIs(saved_job["scheduled"], True)
            self.assertEqual(saved_job["schedule_mode"], "candidates_only")
            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "2099-01-02")

    def test_auto_script_schedule_selects_candidates_and_waits_for_script_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "mode": "auto_script",
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {},
                "last_run_date": "",
            })
            selected_payloads = []

            async def fake_generate(job_id: str) -> dict:
                return {
                    "job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_project_confirmation"},
                    "candidates": [
                        {"full_name": "demo/one"},
                        {"full_name": "demo/two"},
                        {"full_name": "demo/three"},
                        {"full_name": "demo/four"},
                        {"full_name": "demo/five"},
                        {"full_name": "demo/six"},
                    ],
                }

            def fake_save_selection(job_id: str, payload: dict) -> dict:
                selected_payloads.append((job_id, payload))
                return {"job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_script_confirmation"}}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
                patch("src.console.scheduler.save_selection", side_effect=fake_save_selection),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            self.assertTrue(result["started"])
            self.assertEqual(result["job"]["stage"], "awaiting_script_confirmation")
            self.assertEqual(
                [item["full_name"] for item in selected_payloads[0][1]["items"]],
                ["demo/one", "demo/two", "demo/three", "demo/four", "demo/five"],
            )
            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "2099-01-02")

    def test_auto_video_schedule_completes_formal_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "mode": "auto_video",
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {},
                "last_run_date": "",
            })
            calls = []

            async def fake_generate(job_id: str) -> dict:
                calls.append("generate")
                return {
                    "job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_project_confirmation"},
                    "candidates": [
                        {"full_name": "demo/one"},
                        {"full_name": "demo/two"},
                        {"full_name": "demo/three"},
                    ],
                }

            def fake_save_selection(job_id: str, payload: dict) -> dict:
                calls.append(("selection", [item["full_name"] for item in payload["items"]]))
                return {
                    "job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_script_confirmation"},
                    "segments": [{"id": "intro", "label": "开场", "text": "hello"}],
                }

            def fake_save_script(job_id: str, payload: dict) -> dict:
                calls.append(("script", payload["segments"]))
                return {"job": {"id": job_id, "status": "awaiting_render", "stage": "preparing_plan"}}

            def fake_prepare_plan(job_id: str) -> dict:
                calls.append("prepare")
                return {"job": {"id": job_id, "status": "awaiting_validation", "stage": "preparing_plan"}}

            async def fake_validate_plan(job_id: str) -> dict:
                calls.append("validate")
                return {"job": {"id": job_id, "status": "ready_to_render", "stage": "preparing_plan"}}

            async def fake_render_video(job_id: str) -> dict:
                calls.append("render")
                return {"job": {"id": job_id, "status": "completed", "stage": "completed", "official_video": str(jobs_dir / job_id / "formal.mp4")}}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
                patch("src.console.scheduler.save_selection", side_effect=fake_save_selection),
                patch("src.console.scheduler.save_script", side_effect=fake_save_script),
                patch("src.console.scheduler.prepare_plan", side_effect=fake_prepare_plan),
                patch("src.console.scheduler.validate_plan", side_effect=fake_validate_plan),
                patch("src.console.scheduler.render_video", side_effect=fake_render_video),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            self.assertTrue(result["started"])
            self.assertEqual(result["job"]["stage"], "completed")
            self.assertEqual(result["job"]["status"], "completed")
            self.assertEqual(result["job"]["schedule_mode"], "auto_video")
            self.assertEqual(calls, [
                "generate",
                ("selection", ["demo/one", "demo/two", "demo/three"]),
                ("script", [{"id": "intro", "label": "开场", "text": "hello"}]),
                "prepare",
                "validate",
                "render",
            ])
            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "2099-01-02")

    def test_due_schedule_does_not_start_duplicate_job_while_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {},
                "last_run_date": "",
            })
            started = threading.Event()
            release = threading.Event()
            calls = []

            async def slow_generate(job_id: str) -> dict:
                calls.append(job_id)
                started.set()
                release.wait(timeout=2)
                return {"job": {"id": job_id}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=slow_generate),
            ):
                first_result = {}

                def run_first() -> None:
                    first_result.update(run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1)))

                thread = threading.Thread(target=run_first)
                thread.start()
                self.assertTrue(started.wait(timeout=1))
                second = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))
                release.set()
                thread.join(timeout=2)

            self.assertTrue(first_result["started"])
            self.assertFalse(second["started"])
            self.assertEqual(second["reason"], "already_running")
            self.assertEqual(len(calls), 1)

    def test_due_schedule_active_job_is_not_reconciled_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {},
                "last_run_date": "",
            })
            started = threading.Event()
            release = threading.Event()
            seen_job_id = []

            async def slow_generate(job_id: str) -> dict:
                seen_job_id.append(job_id)
                update_job(job_id, status="running", stage="collecting_candidates")
                started.set()
                release.wait(timeout=2)
                return {"job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_project_confirmation"}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.server.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=slow_generate),
            ):
                result = {}

                def run_schedule() -> None:
                    result.update(run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1)))

                thread = threading.Thread(target=run_schedule)
                thread.start()
                self.assertTrue(started.wait(timeout=1))
                reconciled = reconcile_running_job(seen_job_id[0])
                release.set()
                thread.join(timeout=2)

            self.assertTrue(result["started"])
            self.assertEqual(reconciled["status"], "running")
            self.assertEqual(reconciled["stage"], "collecting_candidates")

    def test_schedule_before_time_is_not_due(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "last_run_date": "",
            })
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 8, 59))

            self.assertFalse(result["started"])
            self.assertEqual(result["reason"], "not_due")

    def test_force_schedule_runs_before_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {},
                "last_run_date": "",
            })

            async def fake_generate(job_id: str) -> dict:
                return {"job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_project_confirmation"}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 8, 59), force=True)

            self.assertTrue(result["started"])
            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "2099-01-02")

    def test_legacy_string_false_schedule_is_not_due(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "scheduler.json", {
                "enabled": "false",
                "frequency": "daily",
                "time": "09:00",
                "last_run_date": "",
            })

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            self.assertFalse(result["started"])
            self.assertEqual(result["reason"], "not_due")

    def test_failed_scheduled_draft_does_not_mark_day_as_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {"bgm": "none"},
                "last_run_date": "",
            })

            async def fail_generate(job_id: str) -> dict:
                raise RuntimeError(f"candidate failure for {job_id}")

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fail_generate),
            ):
                with self.assertRaises(RuntimeError):
                    run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "")

    def test_failed_auto_script_schedule_does_not_mark_day_as_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "mode": "auto_script",
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 2,
                "template_params": {},
                "last_run_date": "",
            })

            async def fake_generate(job_id: str) -> dict:
                return {"job": {"id": job_id}, "candidates": [{"full_name": "demo/one"}]}

            def fail_save_selection(job_id: str, payload: dict) -> dict:
                raise RuntimeError("script generation failed")

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
                patch("src.console.scheduler.save_selection", side_effect=fail_save_selection),
            ):
                with self.assertRaisesRegex(RuntimeError, "script generation failed"):
                    run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "")

    def test_failed_auto_video_quality_gate_does_not_mark_day_as_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "mode": "auto_video",
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 1,
                "template_params": {},
                "last_run_date": "",
            })

            async def fake_generate(job_id: str) -> dict:
                return {
                    "job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_project_confirmation"},
                    "candidates": [{"full_name": "demo/one"}],
                }

            def fake_save_selection(job_id: str, payload: dict) -> dict:
                return {
                    "job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_script_confirmation"},
                    "segments": [{"id": "intro", "label": "开场", "text": "hello"}],
                }

            def fake_save_script(job_id: str, payload: dict) -> dict:
                return {
                    "job": {
                        "id": job_id,
                        "status": "awaiting_input",
                        "stage": "awaiting_script_confirmation",
                        "error": "脚本质检未通过，请复核风险项或手动忽略后继续。",
                    }
                }

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
                patch("src.console.scheduler.save_selection", side_effect=fake_save_selection),
                patch("src.console.scheduler.save_script", side_effect=fake_save_script),
            ):
                with self.assertRaisesRegex(RuntimeError, "脚本质检未通过"):
                    run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "")

    def test_successful_schedule_preserves_concurrent_config_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {"bgm": "none"},
                "last_run_date": "",
            })

            async def fake_generate(job_id: str) -> dict:
                update_config("scheduler", {
                    "enabled": True,
                    "frequency": "weekly",
                    "time": "10:30",
                    "time_window": "monthly",
                    "project_count": 10,
                    "template_params": {"style": "sspai_editorial"},
                    "last_run_date": "",
                })
                return {"job": {"id": job_id}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            self.assertTrue(result["started"])
            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "2099-01-02")
            self.assertEqual(saved["frequency"], "weekly")
            self.assertEqual(saved["time"], "10:30")
            self.assertEqual(saved["time_window"], "monthly")
            self.assertEqual(saved["project_count"], 10)
            self.assertEqual(saved["template_params"], {"style": "sspai_editorial"})

    def test_scheduler_config_normalizes_bad_project_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
            ):
                update_config("scheduler", {
                    "enabled": True,
                    "frequency": "daily",
                    "time": "09:00",
                    "time_window": "weekly",
                    "project_count": "many",
                    "template_params": {},
                    "last_run_date": "",
                })

            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["project_count"], 5)

    def test_scheduler_config_normalizes_invalid_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {"last_run_date": "2099-01-01"})
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
            ):
                update_config("scheduler", {
                    "enabled": True,
                    "mode": "fully_automatic",
                    "frequency": "hourly",
                    "time": "soon",
                    "time_window": "yearly",
                    "project_count": 5,
                    "template_params": "bad",
                    "last_run_date": 20990102,
                })

            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["mode"], "candidates_only")
            self.assertEqual(saved["frequency"], "daily")
            self.assertEqual(saved["time"], "09:00")
            self.assertEqual(saved["time_window"], "daily")
            self.assertEqual(saved["template_params"], {})
            self.assertEqual(saved["last_run_date"], "2099-01-01")

    def test_scheduler_last_run_update_uses_dedicated_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "weekly",
                "time": "10:30",
                "time_window": "monthly",
                "project_count": 5,
                "template_params": {"bgm": "none"},
                "last_run_date": "",
            })

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                update_scheduler_last_run("2099-W01")

            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "2099-W01")
            self.assertEqual(saved["frequency"], "weekly")
            self.assertEqual(saved["time"], "10:30")
            self.assertEqual(saved["time_window"], "monthly")
            self.assertEqual(saved["template_params"], {"bgm": "none"})

    def test_scheduler_config_normalizes_enabled_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
            ):
                update_config("scheduler", {
                    "enabled": "false",
                    "frequency": "daily",
                    "time": "09:00",
                    "time_window": "weekly",
                    "project_count": 5,
                    "template_params": {},
                    "last_run_date": "",
                })

            saved = read_json(config_dir / "scheduler.json", {})
            self.assertIs(saved["enabled"], False)

    def test_config_snapshot_normalizes_legacy_scheduler_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": "false",
                "frequency": "hourly",
                "time": "soon",
                "time_window": "yearly",
                "project_count": "bad",
                "template_params": "bad",
                "last_run_date": 20990102,
            })

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
            ):
                scheduler = config_snapshot()["scheduler"]

            self.assertIs(scheduler["enabled"], False)
            self.assertEqual(scheduler["frequency"], "daily")
            self.assertEqual(scheduler["time"], "09:00")
            self.assertEqual(scheduler["time_window"], "daily")
            self.assertEqual(scheduler["project_count"], 5)
            self.assertEqual(scheduler["template_params"], {})
            self.assertEqual(scheduler["last_run_date"], "20990102")

    def test_scheduler_uses_normalized_project_count_for_legacy_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": "bad legacy value",
                "template_params": {},
                "last_run_date": "",
            })

            async def fake_generate(job_id: str) -> dict:
                return {"job": {"id": job_id}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            self.assertTrue(result["started"])
            self.assertEqual(result["job"]["project_count"], 5)

    def test_scheduler_uses_normalized_legacy_time_window_and_template_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "yearly",
                "project_count": 5,
                "template_params": "bad legacy value",
                "last_run_date": "",
            })

            async def fake_generate(job_id: str) -> dict:
                return {"job": {"id": job_id}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            self.assertTrue(result["started"])
            self.assertEqual(result["job"]["time_window"], "daily")
            self.assertEqual(result["job"]["template_params"]["style"], "tech_hotspot")
            self.assertEqual(result["job"]["template_params"]["render_engine"], "hyperframes")
            self.assertEqual(result["job"]["template_params"]["orientation"], "vertical")

    def test_scheduler_uses_active_template_params_with_schedule_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {"bgm": "none"},
                "last_run_date": "",
            })
            write_json(config_dir / "templates.json", {
                "active_template": "github_hotlist_vertical_v1",
                "github_hotlist_vertical_v1": {
                    "project_count": 10,
                    "style": "sspai_editorial",
                    "subtitle_mode": "standard",
                    "bgm": "custom",
                    "bgm_path": "/tmp/bgm.mp3",
                    "narration_tone": "calm_analysis",
                    "orientation": "vertical",
                },
            })

            async def fake_generate(job_id: str) -> dict:
                return {"job": {"id": job_id}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            self.assertTrue(result["started"])
            self.assertEqual(result["job"]["template"], "github_hotlist_vertical_v1")
            self.assertEqual(result["job"]["template_params"]["style"], "sspai_editorial")
            self.assertEqual(result["job"]["template_params"]["bgm"], "none")
            self.assertEqual(result["job"]["template_params"]["bgm_path"], "/tmp/bgm.mp3")

    def test_scheduler_accepts_frontend_visual_style_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {"visual_style": "black_gold"},
                "last_run_date": "",
            })

            async def fake_generate(job_id: str) -> dict:
                return {"job": {"id": job_id}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            self.assertEqual(result["job"]["template_params"]["style"], "chinese_editorial")
            self.assertNotIn("visual_style", result["job"]["template_params"])

    def test_scheduler_normalizes_legacy_template_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {"bgm": "none"},
                "last_run_date": "",
            })
            write_json(config_dir / "templates.json", {
                "active_template": "github_hotlist_vertical_v1",
                "github_hotlist_vertical_v1": {
                    "project_count": 99,
                    "style": "neon",
                    "subtitle_mode": "tiny",
                    "bgm": "loud",
                    "narration_tone": "salesy",
                    "orientation": "horizontal",
                },
            })

            async def fake_generate(job_id: str) -> dict:
                return {"job": {"id": job_id}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            params = result["job"]["template_params"]
            self.assertEqual(params["project_count"], 10)
            self.assertEqual(params["style"], "tech_hotspot")
            self.assertEqual(params["render_engine"], "hyperframes")
            self.assertEqual(params["subtitle_mode"], "large_hook")
            self.assertEqual(params["bgm"], "none")
            self.assertEqual(params["narration_tone"], "professional_review")
            self.assertEqual(params["orientation"], "vertical")

    def test_scheduler_ignores_template_metadata_as_active_template_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {},
                "last_run_date": "",
            })
            write_json(config_dir / "templates.json", {
                "active_template": "active_template",
            })

            async def fake_generate(job_id: str) -> dict:
                return {"job": {"id": job_id}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            self.assertTrue(result["started"])
            self.assertEqual(result["job"]["template"], "github_hotlist_vertical_v1")
            self.assertEqual(result["job"]["template_params"]["style"], "tech_hotspot")
            self.assertEqual(result["job"]["template_params"]["render_engine"], "hyperframes")
            self.assertEqual(result["job"]["template_params"]["orientation"], "vertical")

    # ----- weekly 模式 / catch-up 窗口 -----

    def test_weekly_schedule_runs_on_monday_at_scheduled_time(self) -> None:
        """weekly + 周一 9:01 → 触发。"""
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "weekly",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {},
                "last_run_date": "",
            })

            async def fake_generate(job_id: str) -> dict:
                return {"job": {"id": job_id}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
            ):
                # 2099-01-05 是周一
                result = run_due_scheduled_draft(datetime(2099, 1, 5, 9, 1))

            self.assertTrue(result["started"])
            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "2099-W02")

    def test_weekly_schedule_not_due_on_monday_before_scheduled_time(self) -> None:
        """weekly + 周一 8:00 → 不触发（时间未到）。"""
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "weekly",
                "time": "09:00",
                "last_run_date": "",
            })
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
            ):
                # 2099-01-05 是周一
                result = run_due_scheduled_draft(datetime(2099, 1, 5, 8, 59))

            self.assertFalse(result["started"])
            self.assertEqual(result["reason"], "not_due")

    def test_weekly_schedule_catch_up_on_tuesday(self) -> None:
        """weekly + 周二任意时间 → 触发（catch-up 窗口：周一宕机后补跑）。"""
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "weekly",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {},
                "last_run_date": "",
            })

            async def fake_generate(job_id: str) -> dict:
                return {"job": {"id": job_id}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
            ):
                # 2099-01-06 是周二
                result = run_due_scheduled_draft(datetime(2099, 1, 6, 2, 0))

            self.assertTrue(result["started"], "周二应在 catch-up 窗口内补跑")
            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "2099-W02")

    def test_weekly_schedule_not_due_on_wednesday_or_later(self) -> None:
        """weekly + 周三及以后 → 不触发（catch-up 窗口已关闭）。"""
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "weekly",
                "time": "09:00",
                "last_run_date": "",
            })
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
            ):
                # 2099-01-07 是周三
                wed_result = run_due_scheduled_draft(datetime(2099, 1, 7, 10, 0))
                # 2099-01-11 是周日
                sun_result = run_due_scheduled_draft(datetime(2099, 1, 11, 10, 0))

            self.assertEqual(wed_result["reason"], "not_due")
            self.assertEqual(sun_result["reason"], "not_due")

    def test_weekly_schedule_tuesday_skips_when_already_run_this_week(self) -> None:
        """weekly + 周二 + 本周已跑 → 不再触发（避免周一、周二各跑一次）。"""
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "weekly",
                "time": "09:00",
                "last_run_date": "2099-W02",
            })
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
            ):
                # 2099-01-06 是周二
                result = run_due_scheduled_draft(datetime(2099, 1, 6, 10, 0))

            self.assertFalse(result["started"])
            self.assertEqual(result["reason"], "not_due")

    def test_weekly_schedule_next_week_after_missed(self) -> None:
        """weekly + 上一周漏跑 + 本周一时 → 触发（避免持续漏跑）。"""
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "weekly",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {},
                "last_run_date": "2099-W01",  # 上一周已跑过
            })

            async def fake_generate(job_id: str) -> dict:
                return {"job": {"id": job_id}, "candidates": []}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
            ):
                # 2099-01-12 是下周一
                result = run_due_scheduled_draft(datetime(2099, 1, 12, 9, 1))

            self.assertTrue(result["started"])
            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "2099-W03")

    def test_auto_confirm_candidates_only_runs_to_completion(self) -> None:
        """auto_confirm=true + mode=candidates_only 应一路跑完，不停在「待确认项目」。"""
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "mode": "candidates_only",
                "auto_confirm": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {},
                "last_run_date": "",
            })
            calls = []

            async def fake_generate(job_id: str) -> dict:
                calls.append("generate")
                return {
                    "job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_project_confirmation"},
                    "candidates": [
                        {"full_name": "demo/one"},
                        {"full_name": "demo/two"},
                        {"full_name": "demo/three"},
                    ],
                }

            def fake_save_selection(job_id: str, payload: dict) -> dict:
                calls.append(("selection", [item["full_name"] for item in payload["items"]]))
                return {
                    "job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_script_confirmation"},
                    "segments": [{"id": "intro", "label": "开场", "text": "hello"}],
                }

            def fake_save_script(job_id: str, payload: dict) -> dict:
                calls.append(("script", payload.get("ignore_quality_risk")))
                return {"job": {"id": job_id, "status": "awaiting_render", "stage": "preparing_plan"}}

            def fake_prepare_plan(job_id: str) -> dict:
                calls.append("prepare")
                return {"job": {"id": job_id, "status": "awaiting_validation", "stage": "preparing_plan"}}

            async def fake_validate_plan(job_id: str) -> dict:
                calls.append("validate")
                return {"job": {"id": job_id, "status": "ready_to_render", "stage": "preparing_plan"}}

            async def fake_render_video(job_id: str) -> dict:
                calls.append("render")
                return {"job": {"id": job_id, "status": "completed", "stage": "completed", "official_video": str(jobs_dir / job_id / "formal.mp4")}}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
                patch("src.console.scheduler.save_selection", side_effect=fake_save_selection),
                patch("src.console.scheduler.save_script", side_effect=fake_save_script),
                patch("src.console.scheduler.prepare_plan", side_effect=fake_prepare_plan),
                patch("src.console.scheduler.validate_plan", side_effect=fake_validate_plan),
                patch("src.console.scheduler.render_video", side_effect=fake_render_video),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            self.assertTrue(result["started"])
            self.assertEqual(result["job"]["stage"], "completed")
            self.assertEqual(result["job"]["auto_confirm"], True)
            self.assertEqual(calls, [
                "generate",
                ("selection", ["demo/one", "demo/two", "demo/three"]),
                ("script", True),  # auto_confirm=true 透传到 save_script
                "prepare",
                "validate",
                "render",
            ])
            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "2099-01-02")

    def test_auto_confirm_auto_video_ignores_quality_block(self) -> None:
        """auto_confirm=true + auto_video：即使 save_script 返回 awaiting_script_confirmation，也会被
        scheduler 当作可忽略项继续出片（不抛错）。"""
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "mode": "auto_video",
                "auto_confirm": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 1,
                "template_params": {},
                "last_run_date": "",
            })

            async def fake_generate(job_id: str) -> dict:
                return {
                    "job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_project_confirmation"},
                    "candidates": [{"full_name": "demo/one"}],
                }

            def fake_save_selection(job_id: str, payload: dict) -> dict:
                return {
                    "job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_script_confirmation"},
                    "segments": [{"id": "intro", "label": "开场", "text": "hello"}],
                }

            def fake_save_script(job_id: str, payload: dict) -> dict:
                # 即便 quality 阻断，因为 ignore_quality_risk=True 也应继续
                self.assertTrue(payload.get("ignore_quality_risk"))
                return {"job": {"id": job_id, "status": "awaiting_render", "stage": "preparing_plan"}}

            def fake_prepare_plan(job_id: str) -> dict:
                return {"job": {"id": job_id, "status": "ready_to_render", "stage": "preparing_plan"}}

            async def fake_validate_plan(job_id: str) -> dict:
                return {"job": {"id": job_id, "status": "ready_to_render", "stage": "preparing_plan"}}

            async def fake_render_video(job_id: str) -> dict:
                return {"job": {"id": job_id, "status": "completed", "stage": "completed"}}

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
                patch("src.console.scheduler.save_selection", side_effect=fake_save_selection),
                patch("src.console.scheduler.save_script", side_effect=fake_save_script),
                patch("src.console.scheduler.prepare_plan", side_effect=fake_prepare_plan),
                patch("src.console.scheduler.validate_plan", side_effect=fake_validate_plan),
                patch("src.console.scheduler.render_video", side_effect=fake_render_video),
            ):
                result = run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            self.assertTrue(result["started"])
            self.assertEqual(result["job"]["stage"], "completed")
            self.assertTrue(result["job"]["auto_confirm"])
            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "2099-01-02")

    def test_scheduler_config_normalizes_auto_confirm_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
            ):
                update_config("scheduler", {
                    "enabled": True,
                    "mode": "candidates_only",
                    "auto_confirm": "true",  # 字符串形式也应被规范成 True
                    "frequency": "daily",
                    "time": "09:00",
                    "time_window": "weekly",
                    "project_count": 5,
                    "template_params": {},
                    "last_run_date": "",
                })

            saved = read_json(config_dir / "scheduler.json", {})
            self.assertIs(saved["auto_confirm"], True)

    def test_due_schedule_can_be_cancelled_mid_pipeline(self) -> None:
        """auto_video pipeline 中途调用 request_cancel 应能中断，避免长任务跑完才生效。"""
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "mode": "auto_video",
                "frequency": "daily",
                "time": "09:00",
                "time_window": "weekly",
                "project_count": 5,
                "template_params": {},
                "last_run_date": "",
            })
            job_id_seen = []
            cancel_after = []

            async def fake_generate(job_id: str) -> dict:
                job_id_seen.append(job_id)
                # 在 generate 阶段触发取消
                from src.console.background import request_cancel
                request_cancel(job_id)
                return {
                    "job": {"id": job_id, "status": "awaiting_input", "stage": "awaiting_project_confirmation"},
                    "candidates": [{"full_name": "demo/one"}],
                }

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.scheduler.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.jobs.JOBS_DIR", jobs_dir),
                patch("src.console.scheduler.generate_candidates", side_effect=fake_generate),
            ):
                with self.assertRaisesRegex(Exception, "取消|取消"):
                    run_due_scheduled_draft(datetime(2099, 1, 2, 9, 1))

            # 失败时不应推进 last_run_date
            saved = read_json(config_dir / "scheduler.json", {})
            self.assertEqual(saved["last_run_date"], "", "被取消的任务不应推进 last_run_date")

    def test_update_scheduler_last_run_uses_file_lock(self) -> None:
        """update_scheduler_last_run 在 macOS/Linux 下应通过 fcntl.flock 串行化写。"""
        import fcntl
        from unittest.mock import MagicMock, patch

        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            write_json(config_dir / "scheduler.json", {"last_run_date": ""})

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.fcntl") as mock_fcntl:
                mock_fcntl.LOCK_EX = fcntl.LOCK_EX
                mock_fcntl.LOCK_UN = fcntl.LOCK_UN
                lock_calls = MagicMock()
                mock_fcntl.flock = lock_calls
                # 标记 fcntl 可用
                import src.console.store as store_mod
                with patch.object(store_mod, "_HAS_FCNTL", True):
                    from src.console.store import update_scheduler_last_run
                    update_scheduler_last_run("2099-W01")

                # flock 应该被加锁和解锁各调用一次
                self.assertGreaterEqual(lock_calls.call_count, 2,
                                        "update_scheduler_last_run 应对 scheduler.json 加 fcntl 文件锁")
                saved = read_json(config_dir / "scheduler.json", {})
                self.assertEqual(saved["last_run_date"], "2099-W01")


if __name__ == "__main__":
    unittest.main()
