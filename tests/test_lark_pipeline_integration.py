"""Integration tests for the lark sync pipeline: _generate_candidates_snapshot → sync_all_candidates."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def test_generate_candidates_triggers_all_data_sync(monkeypatch, tmp_path):
    """候选拉取完成后触发全量同步"""
    import src.console.store as store_mod
    from src.console import jobs

    monkeypatch.setattr(store_mod, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)

    job_id = "J1"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "task.json").write_text(json.dumps({
        "id": job_id, "scheduled": True, "type": "github_hotlist",
        "status": "draft_pending", "stage": "draft_pending",
        "time_window": "daily",
    }))

    # mock collect_candidates_with_meta
    fake_candidates = [{"full_name": "a/b", "name": "A", "html_url": "u",
                        "stargazers_count": 10, "rank": 1, "topics": []}]
    fake_meta = {"cache_status": "fresh", "data_source": "trending", "time_window": "daily",
                 "rate_limit": "60/60"}

    async def fake_collect(*a, **k):
        return {"items": fake_candidates, **fake_meta}

    monkeypatch.setattr("src.console.jobs.collect_candidates_with_meta", fake_collect)

    # mock sync_all_candidates
    sync_calls = []

    def fake_sync_all(**kwargs):
        sync_calls.append(kwargs)
        return {"status": "synced", "created": 1, "updated": 0, "records_count": 1}

    monkeypatch.setattr("src.console.lark_sync.sync_all_candidates", fake_sync_all)

    # mock read_lark_config
    monkeypatch.setattr("src.console.lark_sync.read_lark_config",
                        lambda: {"enabled": True, "base_token": "bt",
                                 "all_data_table_id": "tblA", "sync_all_data": True})

    # mock _analyze_candidates and _rank_candidates to avoid model calls
    monkeypatch.setattr(jobs, "_analyze_candidates", lambda jid, cands: cands)
    monkeypatch.setattr(jobs, "_rank_candidates", lambda jid, cands: cands)

    # mock read_github_token
    monkeypatch.setattr("src.console.jobs.read_github_token", lambda: "fake-token")

    # mock update_github_rate_limit
    monkeypatch.setattr("src.console.jobs.update_github_rate_limit", lambda x: None)

    import asyncio
    asyncio.get_event_loop().run_until_complete(
        jobs._generate_candidates_snapshot(job_id, {"id": job_id, "scheduled": True, "time_window": "daily"}, force_refresh=False)
    )

    assert len(sync_calls) == 1
    assert sync_calls[0]["fetch_time"]  # must have unified timestamp
    # task.json should have lark_sync.all_data status
    task = json.loads((job_dir / "task.json").read_text())
    assert task.get("lark_sync", {}).get("all_data", {}).get("status") == "synced"


def test_generate_candidates_skips_sync_when_lark_disabled(monkeypatch, tmp_path):
    """飞书同步关闭时不触发全量同步"""
    import src.console.store as store_mod
    from src.console import jobs

    monkeypatch.setattr(store_mod, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)

    job_id = "J2"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "task.json").write_text(json.dumps({
        "id": job_id, "scheduled": True, "type": "github_hotlist",
        "status": "draft_pending", "stage": "draft_pending",
        "time_window": "daily",
    }))

    fake_candidates = [{"full_name": "a/b", "name": "A", "html_url": "u",
                        "stargazers_count": 10, "rank": 1, "topics": []}]

    async def fake_collect(*a, **k):
        return {"items": fake_candidates, "cache_status": "fresh",
                "data_source": "trending", "time_window": "daily", "rate_limit": "60/60"}

    monkeypatch.setattr("src.console.jobs.collect_candidates_with_meta", fake_collect)

    sync_calls = []
    def fake_sync_all(**kwargs):
        sync_calls.append(kwargs)
        return {"status": "synced", "created": 1, "updated": 0, "records_count": 1}

    monkeypatch.setattr("src.console.lark_sync.sync_all_candidates", fake_sync_all)

    # lark disabled
    monkeypatch.setattr("src.console.lark_sync.read_lark_config",
                        lambda: {"enabled": False, "base_token": "", "all_data_table_id": "", "sync_all_data": False})

    monkeypatch.setattr(jobs, "_analyze_candidates", lambda jid, cands: cands)
    monkeypatch.setattr(jobs, "_rank_candidates", lambda jid, cands: cands)
    monkeypatch.setattr("src.console.jobs.read_github_token", lambda: "fake-token")
    monkeypatch.setattr("src.console.jobs.update_github_rate_limit", lambda x: None)

    import asyncio
    asyncio.get_event_loop().run_until_complete(
        jobs._generate_candidates_snapshot(job_id, {"id": job_id, "scheduled": True, "time_window": "daily"}, force_refresh=False)
    )

    assert len(sync_calls) == 0
    task = json.loads((job_dir / "task.json").read_text())
    assert task.get("lark_sync", {}).get("all_data", {}).get("status") == "disabled"


def test_generate_candidates_sync_failure_does_not_break_job(monkeypatch, tmp_path):
    """全量同步失败不影响候选生成主流程"""
    import src.console.store as store_mod
    from src.console import jobs

    monkeypatch.setattr(store_mod, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)

    job_id = "J3"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "task.json").write_text(json.dumps({
        "id": job_id, "scheduled": True, "type": "github_hotlist",
        "status": "draft_pending", "stage": "draft_pending",
        "time_window": "daily",
    }))

    fake_candidates = [{"full_name": "a/b", "name": "A", "html_url": "u",
                        "stargazers_count": 10, "rank": 1, "topics": []}]

    async def fake_collect(*a, **k):
        return {"items": fake_candidates, "cache_status": "fresh",
                "data_source": "trending", "time_window": "daily", "rate_limit": "60/60"}

    monkeypatch.setattr("src.console.jobs.collect_candidates_with_meta", fake_collect)

    def fake_sync_all(**kwargs):
        raise RuntimeError("lark-cli error")

    monkeypatch.setattr("src.console.lark_sync.sync_all_candidates", fake_sync_all)

    monkeypatch.setattr("src.console.lark_sync.read_lark_config",
                        lambda: {"enabled": True, "base_token": "bt",
                                 "all_data_table_id": "tblA", "sync_all_data": True})

    monkeypatch.setattr(jobs, "_analyze_candidates", lambda jid, cands: cands)
    monkeypatch.setattr(jobs, "_rank_candidates", lambda jid, cands: cands)
    monkeypatch.setattr("src.console.jobs.read_github_token", lambda: "fake-token")
    monkeypatch.setattr("src.console.jobs.update_github_rate_limit", lambda x: None)

    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        jobs._generate_candidates_snapshot(job_id, {"id": job_id, "scheduled": True, "time_window": "daily"}, force_refresh=False)
    )

    # Main flow should still succeed
    assert result is not None
    task = json.loads((job_dir / "task.json").read_text())
    assert task.get("lark_sync", {}).get("all_data", {}).get("status") == "failed"


def test_finalize_triggers_mark_published(monkeypatch, tmp_path):
    """视频输出完成后触发已发布标记"""
    import src.console.store as store_mod
    from src.console import jobs

    monkeypatch.setattr(store_mod, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)

    job_id = "J1"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "task.json").write_text(json.dumps({
        "id": job_id, "scheduled": True, "type": "github_hotlist",
        "status": "running", "stage": "post_processing",
        "fetch_time": "2026-06-18 09:00",
    }))
    (job_dir / "selected_projects.json").write_text(json.dumps({
        "items": [{"full_name": "a/b", "video_title": "T", "official_video": "/v/a.mp4"}]
    }))

    # 创建 final.mp4 存根
    (job_dir / "final.mp4").write_bytes(b"\x00\x00\x00")

    # mock _write_to_official_output_dir 避免真实文件复制
    fake_target = tmp_path / "output" / "official.mp4"
    fake_target.parent.mkdir(parents=True, exist_ok=True)
    fake_target.write_bytes(b"\x00")
    monkeypatch.setattr(jobs, "_write_to_official_output_dir",
                        lambda job, source, base_name: fake_target)

    # mock mark_published_in_lark
    mark_calls = []

    def fake_mark(**kwargs):
        mark_calls.append(kwargs)
        return {"status": "synced", "updated": 1, "missing": [], "errors": []}

    monkeypatch.setattr("src.console.lark_sync.mark_published_in_lark", fake_mark)

    # mock read_lark_config
    monkeypatch.setattr("src.console.lark_sync.read_lark_config",
                        lambda: {"enabled": True, "base_token": "bt",
                                 "selected_data_table_id": "tblS", "sync_selected_data": True})

    result = jobs.finalize_numbered_output(job_id)

    # mark_published_in_lark 应被调用
    assert len(mark_calls) == 1
    assert mark_calls[0]["base_token"] == "bt"
    assert mark_calls[0]["table_id"] == "tblS"
    # task.json 应有 lark_sync.publish_mark 状态
    task = json.loads((job_dir / "task.json").read_text())
    assert task.get("lark_sync", {}).get("publish_mark", {}).get("status") == "synced"


def test_finalize_skips_mark_published_when_lark_disabled(monkeypatch, tmp_path):
    """飞书同步关闭时 finalize 不触发已发布标记"""
    import src.console.store as store_mod
    from src.console import jobs

    monkeypatch.setattr(store_mod, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)

    job_id = "J2"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "task.json").write_text(json.dumps({
        "id": job_id, "scheduled": True, "type": "github_hotlist",
        "status": "running", "stage": "post_processing",
        "fetch_time": "2026-06-18 09:00",
    }))
    (job_dir / "selected_projects.json").write_text(json.dumps({
        "items": [{"full_name": "a/b", "video_title": "T", "official_video": "/v/a.mp4"}]
    }))
    (job_dir / "final.mp4").write_bytes(b"\x00\x00\x00")

    fake_target = tmp_path / "output" / "official.mp4"
    fake_target.parent.mkdir(parents=True, exist_ok=True)
    fake_target.write_bytes(b"\x00")
    monkeypatch.setattr(jobs, "_write_to_official_output_dir",
                        lambda job, source, base_name: fake_target)

    mark_calls = []
    monkeypatch.setattr("src.console.lark_sync.mark_published_in_lark",
                        lambda **kwargs: mark_calls.append(kwargs))

    # lark disabled
    monkeypatch.setattr("src.console.lark_sync.read_lark_config",
                        lambda: {"enabled": False, "base_token": "",
                                 "selected_data_table_id": "", "sync_selected_data": False})

    result = jobs.finalize_numbered_output(job_id)

    assert len(mark_calls) == 0
    task = json.loads((job_dir / "task.json").read_text())
    assert task.get("lark_sync", {}).get("publish_mark", {}).get("status") == "disabled"


def test_finalize_mark_published_failure_does_not_break_job(monkeypatch, tmp_path):
    """已发布标记失败不影响视频输出主流程"""
    import src.console.store as store_mod
    from src.console import jobs

    monkeypatch.setattr(store_mod, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)

    job_id = "J3"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "task.json").write_text(json.dumps({
        "id": job_id, "scheduled": True, "type": "github_hotlist",
        "status": "running", "stage": "post_processing",
        "fetch_time": "2026-06-18 09:00",
    }))
    (job_dir / "selected_projects.json").write_text(json.dumps({
        "items": [{"full_name": "a/b", "video_title": "T", "official_video": "/v/a.mp4"}]
    }))
    (job_dir / "final.mp4").write_bytes(b"\x00\x00\x00")

    fake_target = tmp_path / "output" / "official.mp4"
    fake_target.parent.mkdir(parents=True, exist_ok=True)
    fake_target.write_bytes(b"\x00")
    monkeypatch.setattr(jobs, "_write_to_official_output_dir",
                        lambda job, source, base_name: fake_target)

    def fake_mark(**kwargs):
        raise RuntimeError("lark-cli error")

    monkeypatch.setattr("src.console.lark_sync.mark_published_in_lark", fake_mark)
    monkeypatch.setattr("src.console.lark_sync.read_lark_config",
                        lambda: {"enabled": True, "base_token": "bt",
                                 "selected_data_table_id": "tblS", "sync_selected_data": True})

    # finalize 不应抛出异常
    result = jobs.finalize_numbered_output(job_id)
    assert result is not None

    # 主流程应正常完成
    task = json.loads((job_dir / "task.json").read_text())
    assert task.get("status") == "completed"
    # 标记状态应为 failed
    assert task.get("lark_sync", {}).get("publish_mark", {}).get("status") == "failed"
