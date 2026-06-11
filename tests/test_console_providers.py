from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.console.model_router import chat_text, route_snapshot, test_provider
from src.console.store import (
    DEFAULT_MODEL_ROUTING,
    DEFAULT_PROVIDERS,
    DEFAULT_TEMPLATES,
    append_log,
    config_snapshot,
    create_job,
    job_artifacts,
    list_jobs,
    provider_connection_matches_saved,
    read_job,
    read_json,
    read_log,
    update_config,
    update_configs,
    update_provider_test_result,
    write_json,
)


class ConsoleProvidersTest(unittest.TestCase):
    def test_route_snapshot_reads_provider_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-test",
                        "enabled": True,
                    }
                ]
            })
            write_json(config_dir / "model-routing.json", {
                "candidate_analysis": {"provider": "openai", "model": "test-model"}
            })

            with patch("src.console.model_router.CONFIG_DIR", config_dir):
                route = route_snapshot("candidate_analysis")

            self.assertEqual(route["provider"], "openai")
            self.assertEqual(route["model"], "test-model")
            self.assertEqual(route["enabled"], "1")
            self.assertEqual(route["configured"], "1")
            self.assertEqual(route["available"], "")

    def test_route_snapshot_marks_provider_available_after_successful_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-test",
                        "enabled": True,
                        "last_test": "连接成功: ok",
                    }
                ]
            })
            write_json(config_dir / "model-routing.json", {
                "candidate_analysis": {"provider": "openai", "model": "test-model"}
            })

            with patch("src.console.model_router.CONFIG_DIR", config_dir):
                route = route_snapshot("candidate_analysis")

            self.assertEqual(route["configured"], "1")
            self.assertEqual(route["last_test"], "连接成功: ok")
            self.assertEqual(route["available"], "1")

    def test_route_snapshot_treats_legacy_string_false_as_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-test",
                        "enabled": "false",
                        "last_test": "连接成功: ok",
                    }
                ]
            })
            write_json(config_dir / "model-routing.json", {
                "candidate_analysis": {"provider": "openai", "model": "test-model"}
            })

            with patch("src.console.model_router.CONFIG_DIR", config_dir):
                route = route_snapshot("candidate_analysis")

            self.assertEqual(route["enabled"], "")
            self.assertEqual(route["configured"], "1")
            self.assertEqual(route["available"], "")

    def test_model_routing_config_keeps_only_known_tasks_and_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "providers.json", DEFAULT_PROVIDERS)

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                update_config("model-routing", {
                    "candidate_analysis": {"provider": "openai", "model": "gpt-4.1"},
                    "hotlist_ranking": {"provider": "missing-provider", "model": "bad-model"},
                    "unknown_task": {"provider": "openai", "model": "gpt-4.1"},
                })
                routing = read_json(config_dir / "model-routing.json", {})

            self.assertEqual(routing["candidate_analysis"], {"provider": "openai", "model": "gpt-4.1"})
            self.assertEqual(routing["hotlist_ranking"], DEFAULT_MODEL_ROUTING["hotlist_ranking"])
            self.assertNotIn("unknown_task", routing)
            self.assertEqual(set(routing), set(DEFAULT_MODEL_ROUTING))

    def test_model_routing_normalizes_xiaomi_model_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "providers.json", DEFAULT_PROVIDERS)

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                update_config("model-routing", {
                    "candidate_analysis": {"provider": "xiaomi", "model": "mimo-v2-pro"},
                    "hotlist_ranking": {"provider": "xiaomi", "model": "MiMo-V2.5-Pro"},
                })
                routing = read_json(config_dir / "model-routing.json", {})

            self.assertEqual(routing["candidate_analysis"], {"provider": "xiaomi", "model": "mimo-v2.5-pro"})
            self.assertEqual(routing["hotlist_ranking"], {"provider": "xiaomi", "model": "mimo-v2.5-pro"})

    def test_template_config_normalizes_supported_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            jobs_dir = Path(tmp) / "jobs"

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                update_config("templates", {
                    "active_template": "github_hotlist_vertical_v1",
                    "github_hotlist_vertical_v1": {
                        "project_count": "5",
                        "style": "apple_minimal",
                        "subtitle_mode": "standard",
                        "bgm": "custom",
                        "bgm_path": "/tmp/bgm.mp3",
                        "narration_tone": "calm_analysis",
                        "orientation": "horizontal",
                    },
                })
                templates = read_json(config_dir / "templates.json", {})

            template = templates["github_hotlist_vertical_v1"]
            self.assertEqual(template["project_count"], 5)
            self.assertEqual(template["style"], "apple_minimal")
            self.assertEqual(template["subtitle_mode"], "standard")
            self.assertEqual(template["bgm"], "custom")
            self.assertEqual(template["bgm_path"], "/tmp/bgm.mp3")
            self.assertEqual(template["narration_tone"], "calm_analysis")
            self.assertEqual(template["orientation"], "vertical")

    def test_config_snapshot_normalizes_legacy_template_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "templates.json", {
                "active_template": "missing",
                "github_hotlist_vertical_v1": {
                    "project_count": "bad",
                    "style": "unknown",
                    "subtitle_mode": "unknown",
                    "bgm": "unknown",
                    "narration_tone": "unknown",
                    "orientation": "horizontal",
                },
            })

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                snapshot = config_snapshot()
                templates = snapshot["templates"]

            active = templates["active_template"]
            self.assertEqual(active, DEFAULT_TEMPLATES["active_template"])
            self.assertEqual(templates[active]["project_count"], 5)
            self.assertEqual(templates[active]["style"], DEFAULT_TEMPLATES[active]["style"])
            self.assertEqual(templates[active]["orientation"], "vertical")
            self.assertIn("apple_minimal", {item["style"] for item in snapshot["template_styles"]})

    def test_config_snapshot_does_not_treat_template_metadata_as_template_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "templates.json", {
                "active_template": "active_template",
            })

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                templates = config_snapshot()["templates"]

            active = templates["active_template"]
            self.assertEqual(active, DEFAULT_TEMPLATES["active_template"])
            self.assertIsInstance(templates[active], dict)

    def test_update_provider_test_result_preserves_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-secret",
                        "last_test": "未测试",
                    }
                ]
            })

            with patch("src.console.store.CONFIG_DIR", config_dir):
                update_provider_test_result("openai", "连接成功: ok")
                providers = read_json(config_dir / "providers.json", {})["providers"]

            self.assertEqual(providers[0]["api_key"], "sk-secret")
            self.assertEqual(providers[0]["last_test"], "连接成功: ok")

    def test_write_json_preserves_existing_file_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            write_json(path, {"value": "old"})
            original = path.read_text(encoding="utf-8")

            with patch("pathlib.Path.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    write_json(path, {"value": "new"})

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_update_configs_rejects_unknown_config_before_writing_any_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                with self.assertRaises(ValueError):
                    update_configs({
                        "github": {"token": "ghp_test", "last_rate_limit": "ok"},
                        "unknown": {},
                    })

            self.assertFalse((config_dir / "github.json").exists())
            self.assertFalse((config_dir / "unknown.json").exists())

    def test_update_configs_rejects_non_object_config_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                with self.assertRaises(ValueError):
                    update_configs({"github": []})

    def test_update_configs_restores_written_files_when_later_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            original_github = {"token": "ghp_old", "last_rate_limit": "old"}
            write_json(config_dir / "github.json", original_github)
            write_json(config_dir / "scheduler.json", {"enabled": False})

            real_write_json = write_json

            def flaky_write_json(path: Path, data: object) -> None:
                if path.name == "scheduler.json":
                    raise OSError("disk full")
                real_write_json(path, data)

            with (
                patch("src.console.store.CONFIG_DIR", config_dir),
                patch("src.console.store.JOBS_DIR", jobs_dir),
                patch("src.console.store.write_json", side_effect=flaky_write_json),
            ):
                with self.assertRaises(OSError):
                    update_configs({
                        "github": {"token": "ghp_new", "last_rate_limit": "new"},
                        "scheduler": {"enabled": True},
                    })

            self.assertEqual(read_json(config_dir / "github.json", {}), original_github)

    def test_scheduler_config_save_preserves_current_last_run_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "scheduler.json", {
                "enabled": True,
                "frequency": "daily",
                "time": "09:00",
                "time_window": "daily",
                "project_count": 5,
                "template_params": {},
                "last_run_date": "2099-01-02",
            })

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                update_config("scheduler", {
                    "enabled": False,
                    "frequency": "weekly",
                    "time": "10:30",
                    "time_window": "monthly",
                    "project_count": 10,
                    "template_params": {"bgm": "none"},
                    "last_run_date": "",
                })

            saved = read_json(config_dir / "scheduler.json", {})
            self.assertIs(saved["enabled"], False)
            self.assertEqual(saved["frequency"], "weekly")
            self.assertEqual(saved["time"], "10:30")
            self.assertEqual(saved["time_window"], "monthly")
            self.assertEqual(saved["project_count"], 10)
            self.assertEqual(saved["template_params"], {"bgm": "none"})
            self.assertEqual(saved["last_run_date"], "2099-01-02")

    def test_read_json_returns_default_copy_for_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("{broken", encoding="utf-8")
            default = {"items": []}

            first = read_json(path, default)
            first["items"].append("changed")
            second = read_json(path, default)

            self.assertEqual(second, {"items": []})
            self.assertEqual(default, {"items": []})

    def test_read_json_returns_default_copy_for_invalid_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_bytes(b"\xff")
            default = {"items": []}

            first = read_json(path, default)
            first["items"].append("changed")
            second = read_json(path, default)

            self.assertEqual(second, {"items": []})
            self.assertEqual(default, {"items": []})

    def test_read_json_returns_default_copy_when_file_cannot_be_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("{}", encoding="utf-8")
            default = {"items": []}

            with patch("builtins.open", side_effect=OSError("read failed")):
                first = read_json(path, default)
            first["items"].append("changed")
            with patch("builtins.open", side_effect=OSError("read failed")):
                second = read_json(path, default)

            self.assertEqual(second, {"items": []})
            self.assertEqual(default, {"items": []})

    def test_read_json_returns_default_copy_for_wrong_container_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("[]", encoding="utf-8")
            default = {"items": []}

            first = read_json(path, default)
            first["items"].append("changed")
            second = read_json(path, default)

            self.assertEqual(second, {"items": []})
            self.assertEqual(default, {"items": []})

    def test_config_snapshot_recovers_wrong_container_type_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            jobs_dir = Path(tmp) / "jobs"
            (config_dir / "providers.json").parent.mkdir(parents=True, exist_ok=True)
            (config_dir / "providers.json").write_text("[]", encoding="utf-8")

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                providers = config_snapshot()["providers"]["providers"]

            self.assertEqual([item["id"] for item in providers], [item["id"] for item in DEFAULT_PROVIDERS["providers"]])

    def test_list_jobs_skips_invalid_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            valid_dir = jobs_dir / "GH-HOTLIST-20990101-VALID"
            corrupt_dir = jobs_dir / "GH-HOTLIST-20990101-CORRUPT"
            empty_dir = jobs_dir / "GH-HOTLIST-20990101-EMPTY"
            mismatched_dir = jobs_dir / "GH-HOTLIST-20990101-MISMATCH"
            valid_dir.mkdir(parents=True)
            corrupt_dir.mkdir(parents=True)
            empty_dir.mkdir(parents=True)
            mismatched_dir.mkdir(parents=True)
            write_json(valid_dir / "task.json", {"id": valid_dir.name, "status": "completed"})
            (corrupt_dir / "task.json").write_text("{bad", encoding="utf-8")
            write_json(empty_dir / "task.json", {})
            write_json(mismatched_dir / "task.json", {"id": "GH-HOTLIST-20990101-OTHER"})

            with patch("src.console.store.JOBS_DIR", jobs_dir):
                jobs = list_jobs()

            self.assertEqual([job["id"] for job in jobs], [valid_dir.name])

    def test_list_jobs_sorts_by_updated_at_then_id_descending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            older_dir = jobs_dir / "GH-HOTLIST-20990101-002"
            newer_dir = jobs_dir / "GH-HOTLIST-20990101-001"
            tie_dir = jobs_dir / "GH-HOTLIST-20990101-003"
            older_dir.mkdir(parents=True)
            newer_dir.mkdir(parents=True)
            tie_dir.mkdir(parents=True)
            write_json(older_dir / "task.json", {
                "id": older_dir.name,
                "updated_at": "2099-01-02T09:00:00",
            })
            write_json(newer_dir / "task.json", {
                "id": newer_dir.name,
                "updated_at": "2099-01-02T10:00:00",
            })
            write_json(tie_dir / "task.json", {
                "id": tie_dir.name,
                "updated_at": "2099-01-02T09:00:00",
            })

            with patch("src.console.store.JOBS_DIR", jobs_dir):
                jobs = list_jobs()

            self.assertEqual([job["id"] for job in jobs], [
                newer_dir.name,
                tie_dir.name,
                older_dir.name,
            ])

    def test_job_snapshot_symlink_is_not_treated_as_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            job_dir = jobs_dir / "GH-HOTLIST-20990101-LINK"
            job_dir.mkdir(parents=True)
            outside = Path(tmp) / "outside-task.json"
            write_json(outside, {"id": job_dir.name, "status": "completed"})
            (job_dir / "task.json").symlink_to(outside)

            with patch("src.console.store.JOBS_DIR", jobs_dir):
                job = read_job(job_dir.name)
                jobs = list_jobs()

            self.assertEqual(job, {})
            self.assertEqual(jobs, [])

    def test_provider_config_preserves_test_result_when_connection_settings_do_not_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-secret",
                        "base_url": "",
                        "default_model": "gpt-4.1-mini",
                        "enabled": True,
                        "last_test": "连接成功: ok",
                    }
                ]
            })

            with patch("src.console.store.CONFIG_DIR", config_dir):
                update_config("providers", {
                    "providers": [
                        {
                            **DEFAULT_PROVIDERS["providers"][0],
                            "api_key": "",
                            "base_url": "",
                            "default_model": "gpt-4.1-mini",
                            "enabled": True,
                            "last_test": "连接成功: ok",
                        }
                    ]
                })
                providers = read_json(config_dir / "providers.json", {})["providers"]

            self.assertEqual(providers[0]["api_key"], "sk-secret")
            self.assertEqual(providers[0]["last_test"], "连接成功: ok")

    def test_provider_config_treats_redacted_api_key_as_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-secret",
                        "base_url": "",
                        "default_model": "gpt-4.1-mini",
                        "enabled": True,
                        "last_test": "连接成功: ok",
                    }
                ]
            })

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                redacted = config_snapshot()["providers"]
                update_config("providers", redacted)
                providers = read_json(config_dir / "providers.json", {})["providers"]

            self.assertEqual(providers[0]["api_key"], "sk-secret")
            self.assertEqual(providers[0]["last_test"], "连接成功: ok")

    def test_github_config_treats_redacted_token_as_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "github.json", {
                "token": "ghp_secret",
                "last_rate_limit": "50/60",
            })

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                redacted = config_snapshot()["github"]
                update_config("github", {"token": redacted["token_preview"], "last_rate_limit": "55/60"})
                github = read_json(config_dir / "github.json", {})

            self.assertEqual(github["token"], "ghp_secret")
            self.assertEqual(github["last_rate_limit"], "50/60")

    def test_github_rate_limit_uses_dedicated_writer(self) -> None:
        from src.console.store import update_github_rate_limit

        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "github.json", {
                "token": "ghp_secret",
                "last_rate_limit": "50/60",
            })

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                update_github_rate_limit("55/60")
                github = read_json(config_dir / "github.json", {})

            self.assertEqual(github["token"], "ghp_secret")
            self.assertEqual(github["last_rate_limit"], "55/60")

    def test_provider_config_keeps_only_supported_provider_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", DEFAULT_PROVIDERS)

            with patch("src.console.store.CONFIG_DIR", config_dir):
                update_config("providers", {
                    "providers": [
                        {
                            **DEFAULT_PROVIDERS["providers"][0],
                            "name": "Forged",
                            "type": "unknown",
                            "api_key": "sk-openai",
                            "enabled": True,
                        },
                        {
                            "id": "unlisted",
                            "name": "Unlisted",
                            "type": "openai-compatible",
                            "api_key": "sk-hidden",
                            "enabled": True,
                        },
                    ]
                })
                providers = read_json(config_dir / "providers.json", {})["providers"]

            self.assertEqual([item["id"] for item in providers], [item["id"] for item in DEFAULT_PROVIDERS["providers"]])
            self.assertEqual(providers[0]["name"], DEFAULT_PROVIDERS["providers"][0]["name"])
            self.assertEqual(providers[0]["type"], DEFAULT_PROVIDERS["providers"][0]["type"])
            self.assertEqual(providers[0]["api_key"], "sk-openai")
            self.assertNotIn("unlisted", [item["id"] for item in providers])

    def test_provider_config_ignores_malformed_provider_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-existing",
                    }
                ]
            })

            with patch("src.console.store.CONFIG_DIR", config_dir):
                update_config("providers", {"providers": ["bad"]})
                providers = read_json(config_dir / "providers.json", {})["providers"]

            self.assertEqual(providers[0]["api_key"], "sk-existing")
            self.assertEqual([item["id"] for item in providers], [item["id"] for item in DEFAULT_PROVIDERS["providers"]])

    def test_provider_config_treats_non_list_providers_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", DEFAULT_PROVIDERS)

            with patch("src.console.store.CONFIG_DIR", config_dir):
                update_config("providers", {"providers": "bad"})
                providers = read_json(config_dir / "providers.json", {})["providers"]

            self.assertEqual([item["id"] for item in providers], [item["id"] for item in DEFAULT_PROVIDERS["providers"]])

    def test_provider_config_resets_test_result_when_connection_settings_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-secret",
                        "base_url": "",
                        "default_model": "gpt-4.1-mini",
                        "enabled": True,
                        "last_test": "连接成功: ok",
                    }
                ]
            })

            with patch("src.console.store.CONFIG_DIR", config_dir):
                update_config("providers", {
                    "providers": [
                        {
                            **DEFAULT_PROVIDERS["providers"][0],
                            "api_key": "",
                            "base_url": "",
                            "default_model": "gpt-4.1",
                            "enabled": True,
                            "last_test": "连接成功: ok",
                        }
                    ]
                })
                providers = read_json(config_dir / "providers.json", {})["providers"]

            self.assertEqual(providers[0]["api_key"], "sk-secret")
            self.assertEqual(providers[0]["last_test"], "未测试")

    def test_provider_config_normalizes_xiaomi_default_model_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", DEFAULT_PROVIDERS)

            with patch("src.console.store.CONFIG_DIR", config_dir):
                update_config("providers", {
                    "providers": [
                        {
                            **DEFAULT_PROVIDERS["providers"][3],
                            "api_key": "tp-test",
                            "default_model": "MiMo-V2.5-Pro",
                            "enabled": True,
                        }
                    ]
                })
                providers = read_json(config_dir / "providers.json", {})["providers"]

            self.assertEqual(providers[3]["default_model"], "mimo-v2.5-pro")
            self.assertEqual(providers[3]["last_test"], "未测试")

    def test_provider_config_normalizes_enabled_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", DEFAULT_PROVIDERS)

            with patch("src.console.store.CONFIG_DIR", config_dir):
                update_config("providers", {
                    "providers": [
                        {
                            **DEFAULT_PROVIDERS["providers"][0],
                            "api_key": "sk-openai",
                            "enabled": "false",
                        },
                        {
                            **DEFAULT_PROVIDERS["providers"][2],
                            "api_key": "sk-deepseek",
                            "enabled": "true",
                        },
                    ]
                })
                providers = read_json(config_dir / "providers.json", {})["providers"]

            self.assertIs(providers[0]["enabled"], False)
            self.assertIs(providers[2]["enabled"], True)

    def test_provider_config_preserves_test_result_when_legacy_enabled_is_equivalent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-secret",
                        "base_url": "",
                        "default_model": "gpt-4.1-mini",
                        "enabled": "false",
                        "last_test": "连接成功: ok",
                    }
                ]
            })

            with patch("src.console.store.CONFIG_DIR", config_dir):
                update_config("providers", {
                    "providers": [
                        {
                            **DEFAULT_PROVIDERS["providers"][0],
                            "api_key": "",
                            "base_url": "",
                            "default_model": "gpt-4.1-mini",
                            "enabled": False,
                            "last_test": "连接成功: ok",
                        }
                    ]
                })
                providers = read_json(config_dir / "providers.json", {})["providers"]

            self.assertIs(providers[0]["enabled"], False)
            self.assertEqual(providers[0]["last_test"], "连接成功: ok")

    def test_provider_config_resets_test_result_when_new_key_is_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-oldsecret",
                        "base_url": "",
                        "default_model": "gpt-4.1-mini",
                        "enabled": True,
                        "last_test": "连接成功: ok",
                    }
                ]
            })

            with patch("src.console.store.CONFIG_DIR", config_dir):
                update_config("providers", {
                    "providers": [
                        {
                            **DEFAULT_PROVIDERS["providers"][0],
                            "api_key": "sk-newsecret",
                            "base_url": "",
                            "default_model": "gpt-4.1-mini",
                            "enabled": True,
                            "last_test": "连接成功: ok",
                        }
                    ]
                })
                providers = read_json(config_dir / "providers.json", {})["providers"]

            self.assertEqual(providers[0]["api_key"], "sk-newsecret")
            self.assertEqual(providers[0]["last_test"], "未测试")

    def test_provider_connection_match_detects_unsaved_form_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-saved",
                        "base_url": "https://saved.example/v1",
                        "default_model": "saved-model",
                        "enabled": True,
                    }
                ]
            })

            with patch("src.console.store.CONFIG_DIR", config_dir):
                same = provider_connection_matches_saved("openai", {
                    "api_key": "",
                    "base_url": "https://saved.example/v1",
                    "default_model": "saved-model",
                    "enabled": True,
                })
                changed = provider_connection_matches_saved("openai", {
                    "api_key": "",
                    "base_url": "https://draft.example/v1",
                    "default_model": "saved-model",
                    "enabled": True,
                })

            self.assertTrue(same)
            self.assertFalse(changed)

    def test_provider_connection_match_treats_legacy_enabled_as_equivalent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-saved",
                        "base_url": "https://saved.example/v1",
                        "default_model": "saved-model",
                        "enabled": "true",
                    }
                ]
            })

            with patch("src.console.store.CONFIG_DIR", config_dir):
                same = provider_connection_matches_saved("openai", {
                    "api_key": "",
                    "base_url": "https://saved.example/v1",
                    "default_model": "saved-model",
                    "enabled": True,
                })
                changed = provider_connection_matches_saved("openai", {
                    "api_key": "",
                    "base_url": "https://saved.example/v1",
                    "default_model": "saved-model",
                    "enabled": False,
                })

            self.assertTrue(same)
            self.assertFalse(changed)

    def test_config_snapshot_marks_only_successfully_tested_providers_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-success",
                        "enabled": True,
                        "last_test": "连接成功: ok",
                    },
                    {
                        **DEFAULT_PROVIDERS["providers"][2],
                        "api_key": "sk-failed",
                        "enabled": True,
                        "last_test": "连接失败: bad model",
                    },
                ]
            })

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                providers = config_snapshot()["providers"]["providers"]

            self.assertEqual(providers[0]["api_key"], "sk-s...cess")
            self.assertTrue(providers[0]["available"])
            self.assertTrue(providers[1]["configured"])
            self.assertFalse(providers[1]["available"])

    def test_config_snapshot_treats_legacy_string_false_as_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-success",
                        "enabled": "false",
                        "last_test": "连接成功: ok",
                    },
                ]
            })

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                provider = config_snapshot()["providers"]["providers"][0]

            self.assertFalse(provider["enabled"])
            self.assertFalse(provider["available"])

    def test_config_snapshot_skips_malformed_legacy_provider_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "providers.json", {
                "providers": [
                    "bad",
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-success",
                        "enabled": True,
                        "last_test": "连接成功: ok",
                    },
                ]
            })

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                providers = config_snapshot()["providers"]["providers"]

            self.assertEqual(len(providers), 1)
            self.assertEqual(providers[0]["id"], "openai")

    def test_model_routing_ignores_malformed_legacy_provider_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            jobs_dir = Path(tmp) / "jobs"
            write_json(config_dir / "providers.json", {
                "providers": [
                    "bad",
                    DEFAULT_PROVIDERS["providers"][0],
                ]
            })

            with patch("src.console.store.CONFIG_DIR", config_dir), patch("src.console.store.JOBS_DIR", jobs_dir):
                update_config("model-routing", {
                    "candidate_analysis": {"provider": "openai", "model": "gpt-4.1-mini"},
                })
                routing = read_json(config_dir / "model-routing.json", {})

            self.assertEqual(routing["candidate_analysis"], {"provider": "openai", "model": "gpt-4.1-mini"})

    def test_provider_test_reports_unconfigured_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", DEFAULT_PROVIDERS)

            with patch("src.console.model_router.CONFIG_DIR", config_dir):
                ok, message = test_provider("openai", "test-model")

            self.assertFalse(ok)
            self.assertIn("未启用", message)

    def test_provider_test_treats_legacy_string_false_as_disabled(self) -> None:
        calls = []

        class FakeOpenAI:
            def __init__(self, **kwargs):
                calls.append(kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-saved",
                        "enabled": "false",
                    }
                ]
            })

            with patch("src.console.model_router.CONFIG_DIR", config_dir), patch("src.console.model_router.OpenAI", FakeOpenAI):
                ok, message = test_provider("openai", "test-model")

        self.assertFalse(ok)
        self.assertIn("未启用", message)
        self.assertEqual(calls, [])

    def test_provider_test_uses_inline_form_config(self) -> None:
        calls = []

        class FakeOpenAI:
            def __init__(self, **kwargs):
                calls.append({"kwargs": kwargs})
                self.chat = self
                self.completions = self

            def create(self, **kwargs):
                calls.append({"request": kwargs})
                return _fake_chat_response("ok")

        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-saved",
                        "base_url": "https://saved.example/v1",
                        "default_model": "saved-model",
                        "enabled": True,
                    }
                ]
            })

            with patch("src.console.model_router.CONFIG_DIR", config_dir), patch("src.console.model_router.OpenAI", FakeOpenAI):
                ok, message = test_provider("openai", "draft-model", {
                    "api_key": "sk-draft",
                    "base_url": "https://draft.example/v1",
                    "default_model": "draft-default",
                    "enabled": True,
                })

        self.assertTrue(ok)
        self.assertEqual(message, "ok")
        self.assertEqual(calls[0]["kwargs"]["api_key"], "sk-draft")
        self.assertEqual(calls[0]["kwargs"]["base_url"], "https://draft.example/v1")
        self.assertEqual(calls[0]["kwargs"]["timeout"], 120)
        self.assertEqual(calls[0]["kwargs"]["max_retries"], 0)
        self.assertEqual(calls[1]["request"]["model"], "draft-model")

    def test_provider_test_merges_saved_key_when_inline_key_is_blank(self) -> None:
        calls = []

        class FakeOpenAI:
            def __init__(self, **kwargs):
                calls.append({"kwargs": kwargs})
                self.chat = self
                self.completions = self

            def create(self, **kwargs):
                calls.append({"request": kwargs})
                return _fake_chat_response("ok")

        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][0],
                        "api_key": "sk-saved",
                        "base_url": "",
                        "default_model": "saved-model",
                        "enabled": True,
                    }
                ]
            })

            with patch("src.console.model_router.CONFIG_DIR", config_dir), patch("src.console.model_router.OpenAI", FakeOpenAI):
                ok, _ = test_provider("openai", "", {
                    "api_key": "",
                    "base_url": "https://draft.example/v1",
                    "default_model": "draft-default",
                    "enabled": True,
                })

        self.assertTrue(ok)
        self.assertEqual(calls[0]["kwargs"]["api_key"], "sk-saved")
        self.assertEqual(calls[0]["kwargs"]["base_url"], "https://draft.example/v1")
        self.assertEqual(calls[1]["request"]["model"], "draft-default")

    def test_anthropic_provider_test_uses_messages_api(self) -> None:
        calls = []

        class FakeAnthropicResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"content": [{"type": "text", "text": "ok"}]}

        def fake_post(url, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeAnthropicResponse()

        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][1],
                        "api_key": "sk-ant",
                        "enabled": True,
                    }
                ]
            })

            with patch("src.console.model_router.CONFIG_DIR", config_dir), patch("src.console.model_router.httpx.post", side_effect=fake_post):
                ok, message = test_provider("anthropic", "claude-test")

        self.assertTrue(ok)
        self.assertEqual(message, "ok")
        self.assertEqual(calls[0]["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(calls[0]["headers"]["x-api-key"], "sk-ant")
        self.assertEqual(calls[0]["json"]["model"], "claude-test")
        self.assertEqual(calls[0]["json"]["messages"][0]["content"], "ping")

    def test_anthropic_chat_text_uses_routed_provider(self) -> None:
        calls = []

        class FakeAnthropicResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"content": [{"type": "text", "text": "{\"ok\": true}"}]}

        def fake_post(url, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeAnthropicResponse()

        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp)
            write_json(config_dir / "providers.json", {
                "providers": [
                    {
                        **DEFAULT_PROVIDERS["providers"][1],
                        "api_key": "sk-ant",
                        "enabled": True,
                        "last_test": "连接成功: ok",
                    }
                ]
            })
            write_json(config_dir / "model-routing.json", {
                "candidate_analysis": {"provider": "anthropic", "model": "claude-test"}
            })

            with patch("src.console.model_router.CONFIG_DIR", config_dir), patch("src.console.model_router.httpx.post", side_effect=fake_post):
                content, route = chat_text("candidate_analysis", "system prompt", "user prompt", max_tokens=123)

        self.assertEqual(content, "{\"ok\": true}")
        self.assertEqual(route["provider"], "anthropic")
        self.assertEqual(calls[0]["json"]["system"], "system prompt")
        self.assertEqual(calls[0]["json"]["messages"][0]["content"], "user prompt")
        self.assertEqual(calls[0]["json"]["max_tokens"], 123)

    def test_anthropic_base_url_does_not_duplicate_v1_suffix(self) -> None:
        calls = []

        class FakeAnthropicResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"content": [{"type": "text", "text": "ok"}]}

        def fake_post(url, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeAnthropicResponse()

        with patch("src.console.model_router.httpx.post", side_effect=fake_post):
            ok, _ = test_provider("anthropic", "claude-test", {
                **DEFAULT_PROVIDERS["providers"][1],
                "api_key": "sk-ant",
                "base_url": "https://proxy.example/v1",
                "enabled": True,
            })

        self.assertTrue(ok)
        self.assertEqual(calls[0]["url"], "https://proxy.example/v1/messages")

    def test_job_artifacts_include_preview_subdirectories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_dir = jobs_dir / "GH-HOTLIST-20990101-001"
            (job_dir / "preview_frames").mkdir(parents=True)
            (job_dir / "task.json").write_text("{}", encoding="utf-8")
            (job_dir / "preview_frames" / "shot-01.png").write_bytes(b"png")

            with patch("src.console.store.JOBS_DIR", jobs_dir):
                artifacts = job_artifacts("GH-HOTLIST-20990101-001")

            names = [item["name"] for item in artifacts["files"]]
            self.assertIn("task.json", names)
            self.assertIn("preview_frames/shot-01.png", names)

    def test_job_artifacts_hide_dotfiles_and_hidden_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_dir = jobs_dir / "GH-HOTLIST-20990101-HIDDEN"
            (job_dir / ".cache").mkdir(parents=True)
            (job_dir / "task.json").write_text("{}", encoding="utf-8")
            (job_dir / ".env").write_text("SECRET=1", encoding="utf-8")
            (job_dir / ".cache" / "token.txt").write_text("secret", encoding="utf-8")

            with patch("src.console.store.JOBS_DIR", jobs_dir):
                artifacts = job_artifacts("GH-HOTLIST-20990101-HIDDEN")

            names = [item["name"] for item in artifacts["files"]]
            self.assertEqual(names, ["task.json"])

    def test_job_artifacts_skip_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_dir = jobs_dir / "GH-HOTLIST-20990101-LINK"
            job_dir.mkdir(parents=True)
            (job_dir / "task.json").write_text("{}", encoding="utf-8")
            outside = Path(tmp) / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            (job_dir / "outside-link.txt").symlink_to(outside)

            with patch("src.console.store.JOBS_DIR", jobs_dir):
                artifacts = job_artifacts("GH-HOTLIST-20990101-LINK")

            names = [item["name"] for item in artifacts["files"]]
            self.assertEqual(names, ["task.json"])

    def test_job_artifacts_skip_files_that_cannot_be_statted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_dir = jobs_dir / "GH-HOTLIST-20990101-STALE"
            job_dir.mkdir(parents=True)
            (job_dir / "task.json").write_text("{}", encoding="utf-8")
            (job_dir / "transient.txt").write_text("soon gone", encoding="utf-8")

            original_stat = Path.stat

            def flaky_stat(path: Path, *args, **kwargs):
                if path.name == "transient.txt":
                    raise OSError("vanished")
                return original_stat(path, *args, **kwargs)

            with patch("src.console.store.JOBS_DIR", jobs_dir), patch("pathlib.Path.stat", flaky_stat):
                artifacts = job_artifacts("GH-HOTLIST-20990101-STALE")

            names = [item["name"] for item in artifacts["files"]]
            self.assertEqual(names, ["task.json"])

    def test_read_log_returns_empty_for_symlinked_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_dir = jobs_dir / "GH-HOTLIST-20990101-LOG-LINK"
            job_dir.mkdir(parents=True)
            outside = Path(tmp) / "outside.log"
            outside.write_text("secret", encoding="utf-8")
            (job_dir / "logs.txt").symlink_to(outside)

            with patch("src.console.store.JOBS_DIR", jobs_dir):
                logs = read_log(job_dir.name)

            self.assertEqual(logs, "")

    def test_read_log_returns_empty_for_invalid_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_dir = jobs_dir / "GH-HOTLIST-20990101-LOG-BAD"
            job_dir.mkdir(parents=True)
            (job_dir / "logs.txt").write_bytes(b"\xff")

            with patch("src.console.store.JOBS_DIR", jobs_dir):
                logs = read_log(job_dir.name)

            self.assertEqual(logs, "")

    def test_append_log_rejects_symlinked_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp)
            job_dir = jobs_dir / "GH-HOTLIST-20990101-LOG-LINK"
            job_dir.mkdir(parents=True)
            outside = Path(tmp) / "outside.log"
            outside.write_text("secret", encoding="utf-8")
            (job_dir / "logs.txt").symlink_to(outside)

            with patch("src.console.store.JOBS_DIR", jobs_dir):
                with self.assertRaises(ValueError):
                    append_log(job_dir.name, "should not write")

            self.assertEqual(outside.read_text(encoding="utf-8"), "secret")

    def test_job_id_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = Path(tmp) / "jobs"
            outside_dir = Path(tmp) / "outside"
            outside_dir.mkdir()
            write_json(outside_dir / "task.json", {"id": "../outside", "status": "completed"})

            with patch("src.console.store.JOBS_DIR", jobs_dir):
                with self.assertRaises(ValueError):
                    create_job("../outside", {})
                with self.assertRaises(ValueError):
                    append_log("../outside", "should not write")
                self.assertEqual(read_job("../outside"), {})
                self.assertEqual(job_artifacts("../outside")["files"], [])

            self.assertFalse((jobs_dir / ".." / "outside").exists())
            self.assertFalse((outside_dir / "logs.txt").exists())

def _fake_chat_response(content: str):
    message = type("Message", (), {"content": content})()
    choice = type("Choice", (), {"message": message})()
    return type("Response", (), {"choices": [choice]})()


if __name__ == "__main__":
    unittest.main()
