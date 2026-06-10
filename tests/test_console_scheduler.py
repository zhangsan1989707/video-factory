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
            self.assertEqual(first["job"]["time_window"], "weekly")
            self.assertEqual(first["job"]["project_count"], 5)
            self.assertEqual(first["job"]["template_params"]["bgm"], "none")
            self.assertEqual(first["job"]["stage"], "awaiting_project_confirmation")
            self.assertEqual(second["reason"], "not_due")
            self.assertEqual(len(calls), 1)
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
                    "template_params": {"style": "black_gold"},
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
            self.assertEqual(saved["template_params"], {"style": "black_gold"})

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
                    "frequency": "hourly",
                    "time": "soon",
                    "time_window": "yearly",
                    "project_count": 5,
                    "template_params": "bad",
                    "last_run_date": 20990102,
                })

            saved = read_json(config_dir / "scheduler.json", {})
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
                    "style": "black_gold",
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
            self.assertEqual(result["job"]["template_params"]["style"], "black_gold")
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

            self.assertEqual(result["job"]["template_params"]["style"], "black_gold")
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


if __name__ == "__main__":
    unittest.main()
