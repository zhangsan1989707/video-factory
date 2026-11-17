"""炒股科普任务产物目录管理"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class FinanceJobPaths:
    """任务产物路径"""
    base: Path

    @property
    def topic_json(self) -> Path:
        return self.base / "topic.json"

    @property
    def script_json(self) -> Path:
        return self.base / "script.json"

    @property
    def storyboard_json(self) -> Path:
        return self.base / "storyboard.json"

    @property
    def compliance_check_json(self) -> Path:
        return self.base / "compliance_check.json"

    @property
    def render_plan_json(self) -> Path:
        return self.base / "render_plan.json"

    @property
    def audio_dir(self) -> Path:
        d = self.base / "audio"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def preview_frames_dir(self) -> Path:
        d = self.base / "preview_frames"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def frames_dir(self) -> Path:
        d = self.base / "frames"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def final_video(self) -> Path:
        return self.base / "final.mp4"

    @property
    def timing_report(self) -> Path:
        return self.base / "timing_report.json"


def create_finance_job_paths(output_dir: Path | None = None) -> FinanceJobPaths:
    """创建任务目录并返回路径对象"""
    if output_dir:
        base = output_dir
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = Path("output/jobs") / f"finance-edu-{timestamp}"
    base.mkdir(parents=True, exist_ok=True)
    return FinanceJobPaths(base=base)


def write_json(path: Path, data: dict | list) -> None:
    """写入 JSON 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_json(path: Path, default: dict | None = None) -> dict:
    """读取 JSON 文件"""
    if not path.exists():
        return default or {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)
