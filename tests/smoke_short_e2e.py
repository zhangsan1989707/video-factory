"""短链路 E2E 验收脚本。

一条命令完成"候选 → 口播 → 计划 → 渲染"全链路验证，不依赖真实
GitHub API、模型供应商，失败时输出明确的阶段报告。

用法：
    .venv/bin/python tests/smoke_short_e2e.py
    .venv/bin/python tests/smoke_short_e2e.py --skip-render  # 只验证到计划阶段
    .venv/bin/python tests/smoke_short_e2e.py --keep-output    # 保留输出目录

验收标准（对应 docs/tasks/next-development-roadmap.md 1.2）：
- 一条命令能在本机完成短链路验证
- 失败时报告阶段：候选、口播、计划、预览、TTS、渲染
- 不默认依赖真实 API key
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

# 确保可以导入 src.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.console.jobs import (  # noqa: E402
    generate_candidates,
    job_detail,
    prepare_plan,
    render_video,
    save_script,
    save_selection,
    validate_plan,
)
from src.console.store import create_job, update_job  # noqa: E402


# ---- 固定的 mock 候选数据（避免依赖实时外部榜单） ----

SAMPLE_CANDIDATES: list[dict[str, Any]] = [
    {
        "name": "alpha",
        "full_name": "demo/alpha",
        "repo_url": "https://github.com/demo/alpha",
        "stars": 1520,
        "stars_today": 42,
        "description": "AI agent workflow",
        "description_zh": "AI 工作流工具",
        "recommendation": "解决重复操作",
        "visual_potential": "README 可展示",
        "audience": "AI 开发者",
        "data_source": "trending",
        "language": "Python",
    },
    {
        "name": "beta",
        "full_name": "demo/beta",
        "repo_url": "https://github.com/demo/beta",
        "stars": 88,
        "stars_today": 12,
        "description": "CLI helper",
        "description_zh": "命令行助手",
        "recommendation": "减少切工具",
        "visual_potential": "终端截图可展示",
        "audience": "开发者",
        "data_source": "trending",
        "language": "Go",
    },
    {
        "name": "gamma",
        "full_name": "demo/gamma",
        "repo_url": "https://github.com/demo/gamma",
        "stars": 340,
        "stars_today": 8,
        "description": "Tiny media toolkit",
        "description_zh": "轻量媒体处理工具",
        "recommendation": "处理媒体文件",
        "visual_potential": "命令行截图",
        "audience": "媒体工作者",
        "data_source": "trending",
        "language": "Rust",
    },
]


@dataclass
class StageResult:
    """单个阶段的执行结果。"""

    name: str
    label: str
    status: str  # "passed" | "failed" | "skipped"
    duration_seconds: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "status": self.status,
            "duration_seconds": round(self.duration_seconds, 3),
            "detail": self.detail,
            "error": self.error,
        }


@dataclass
class E2EReport:
    """完整的短链路验收报告。"""

    job_id: str
    started_at: str
    overall_status: str = "running"
    stages: list[StageResult] = field(default_factory=list)
    output_dir: str = ""
    error: str = ""

    def add_stage(self, result: StageResult) -> None:
        self.stages.append(result)
        if result.status == "failed":
            self.overall_status = "failed"
            self.error = f"{result.label} 失败：{result.error}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "started_at": self.started_at,
            "overall_status": self.overall_status,
            "stages": [stage.to_dict() for stage in self.stages],
            "output_dir": self.output_dir,
            "error": self.error,
        }

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("短链路 E2E 验收报告")
        print("=" * 60)
        print(f"任务 ID: {self.job_id}")
        print(f"总体状态: {self.overall_status}")
        if self.output_dir:
            print(f"输出目录: {self.output_dir}")
        if self.error:
            print(f"错误: {self.error}")
        print("-" * 60)
        for stage in self.stages:
            icon = {"passed": "✓", "failed": "✗", "skipped": "○"}.get(stage.status, "?")
            duration = f" ({stage.duration_seconds:.2f}s)" if stage.duration_seconds > 0 else ""
            print(f"  {icon} {stage.label}{duration}")
            if stage.status == "failed" and stage.error:
                print(f"      ↳ {stage.error}")
        print("=" * 60)


def _run_stage(report: E2EReport, name: str, label: str):
    """阶段执行装饰器：记录耗时和异常。"""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            if report.overall_status == "failed":
                report.add_stage(StageResult(name=name, label=label, status="skipped"))
                return None
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration = time.perf_counter() - start
                detail = result if isinstance(result, dict) else {}
                report.add_stage(StageResult(
                    name=name, label=label, status="passed",
                    duration_seconds=duration, detail=detail,
                ))
                return result
            except Exception as exc:
                duration = time.perf_counter() - start
                report.add_stage(StageResult(
                    name=name, label=label, status="failed",
                    duration_seconds=duration,
                    error=f"{exc.__class__.__name__}: {exc}",
                ))
                # 打印堆栈帮助调试
                traceback.print_exc()
                return None

        return wrapper

    return decorator


def _mock_run_pipeline_factory(jobs_dir: Path):
    """构造一个 mock run_pipeline side_effect，写出最小可用 final.mp4。"""

    def _write_minimal_mp4(path: Path) -> None:
        """使用 ffmpeg 生成 1 秒静默视频+音频；无 ffmpeg 时写占位。"""
        import shutil as _sh
        ffmpeg = _sh.which("ffmpeg")
        if ffmpeg:
            subprocess.run(
                [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1",
                 "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                 "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path)],
                check=True, capture_output=True,
            )
        else:
            path.write_bytes(b"\x00\x00\x00\x20ftypisom")

    def _side_effect(*args, **kwargs):
        output = kwargs.get("output") or (args[1] if len(args) > 1 else "")
        if not output:
            return {}
        output_path = Path(str(output))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _write_minimal_mp4(output_path)
        # 调用 stage_callback 让 jobs.py 的进度跟踪正常工作
        stage_callback = kwargs.get("stage_callback")
        if stage_callback:
            for stage in ("capturing_assets", "generating_tts", "composing_html",
                          "rendering_hyperframes", "mixing_audio", "composing_video"):
                try:
                    stage_callback(stage)
                except Exception:
                    pass
        progress_callback = kwargs.get("progress_callback")
        if progress_callback:
            try:
                progress_callback("composing_video", 1, 1)
            except Exception:
                pass
        return {"output": str(output_path)}

    return _side_effect


async def run_short_e2e(skip_render: bool = False, keep_output: bool = False) -> E2EReport:
    """执行完整的短链路验收。"""

    from datetime import datetime, timezone

    report = E2EReport(
        job_id="GH-HOTLIST-SMOKE-E2E",
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    tmp_dir = tempfile.mkdtemp(prefix="github-video-e2e-")
    jobs_dir = Path(tmp_dir) / "jobs"
    report.output_dir = tmp_dir

    try:
        with (
            patch("src.console.store.JOBS_DIR", jobs_dir),
            patch("src.console.jobs.JOBS_DIR", jobs_dir),
            patch("src.console.jobs.route_snapshot", return_value={
                "provider": "", "provider_name": "", "model": "",
                "enabled": "", "configured": "",
            }),
            # 候选生成：注入 mock 数据，不依赖真实 GitHub API
            patch("src.console.jobs.collect_candidates_with_meta") as mock_collect,
            patch("src.console.jobs.read_github_token", return_value=""),
            # 渲染管线：mock 避免依赖 Edge TTS / Playwright / HyperFrames
            patch("src.console.jobs.run_pipeline", new=AsyncMock(side_effect=_mock_run_pipeline_factory(jobs_dir))),
            patch("src.console.jobs.post_process_video", side_effect=lambda *a, **kw: None),
        ):
            mock_collect.return_value = {
                "items": SAMPLE_CANDIDATES,
                "rate_limit": "mock (E2E)",
                "cache_status": "miss",
                "data_source": "mock",
            }

            # === 阶段 1: 创建任务 + 候选生成 ===
            @_run_stage(report, "candidates", "候选生成")
            async def stage_candidates():
                job = create_job("GH-HOTLIST-SMOKE-E2E", {
                    "title": "E2E 短链路验收",
                    "project_count": 2,
                    "time_window": "weekly",
                    "template_params": {"bgm": "none"},
                })
                report.job_id = job["id"]
                result = await generate_candidates(job["id"], force_refresh=True)
                candidates = result.get("candidates") or []
                if not candidates:
                    raise AssertionError("候选生成返回空列表")
                return {
                    "candidate_count": len(candidates),
                    "first_candidate": candidates[0].get("name") if candidates else "",
                    "data_source": result.get("data_source", "mock"),
                }

            candidate_result = await stage_candidates()
            if candidate_result is None:
                return report

            # === 阶段 2: 确认项目 + 口播生成 ===
            @_run_stage(report, "script", "口播生成")
            async def stage_script():
                update_job(report.job_id, status="awaiting_input",
                           stage="awaiting_project_confirmation")
                # 选择前 2 个候选
                selected_items = [{"name": c["name"], "full_name": c["full_name"],
                                   "repo_url": c.get("repo_url", ""),
                                   "stars": c.get("stars", 0),
                                   "description": c.get("description", ""),
                                   "description_zh": c.get("description_zh", ""),
                                   "recommendation": c.get("recommendation", ""),
                                   "visual_potential": c.get("visual_potential", ""),
                                   "audience": c.get("audience", "")}
                                  for c in SAMPLE_CANDIDATES[:2]]
                selection = save_selection(report.job_id, {"items": selected_items})
                segments = selection.get("segments") or []
                if not segments:
                    raise AssertionError("口播生成返回空 segments")
                # 传入 ignore_quality_risk 让脚本质检不阻断计划生成
                save_script(report.job_id, {"segments": segments, "ignore_quality_risk": True})
                return {
                    "segment_count": len(segments),
                    "hook": bool(selection.get("hook")),
                }

            script_result = await stage_script()
            if script_result is None:
                return report

            # === 阶段 3: 计划生成 ===
            @_run_stage(report, "plan", "计划生成")
            async def stage_plan():
                prepared = await asyncio.to_thread(prepare_plan, report.job_id)
                readiness = prepared.get("readiness_report", {})
                if readiness.get("status") not in {"ready", "review"}:
                    raise AssertionError(f"readiness 状态异常: {readiness.get('status')}")
                return {
                    "readiness": readiness.get("status"),
                    "shot_count": len(prepared.get("shot_plan", {}).get("shots") or []),
                    "asset_count": len(prepared.get("asset_manifest", {}).get("assets") or []),
                }

            plan_result = await stage_plan()
            if plan_result is None:
                return report

            # === 阶段 4: 计划校验 ===
            @_run_stage(report, "validation", "计划校验")
            async def stage_validation():
                validated = await validate_plan(report.job_id)
                status = validated.get("plan_validation", {}).get("status")
                if status != "passed":
                    raise AssertionError(f"校验未通过: {status}")
                return {"validation_status": status}

            validation_result = await stage_validation()
            if validation_result is None:
                return report

            # === 阶段 5: 渲染（可选跳过） ===
            if skip_render:
                report.add_stage(StageResult(
                    name="render", label="视频渲染", status="skipped",
                    detail={"reason": "--skip-render"},
                ))
            else:
                @_run_stage(report, "render", "视频渲染")
                async def stage_render():
                    rendered = await render_video(report.job_id)
                    job = rendered.get("job", {})
                    if job.get("status") != "completed":
                        raise AssertionError(f"渲染未完成: {job.get('status')} - {job.get('error', '')}")
                    official = job.get("official_video", "")
                    if not official:
                        raise AssertionError("未生成正式视频路径")
                    official_path = Path(official)
                    if not official_path.exists() or official_path.stat().st_size <= 0:
                        raise AssertionError(f"正式视频文件无效: {official}")
                    # ffprobe 验证视频流
                    probe = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
                         "-show_streams", "-of", "json", str(official_path)],
                        check=True, capture_output=True, text=True,
                    )
                    probe_data = json.loads(probe.stdout)
                    streams = probe_data.get("streams", [])
                    has_video = any(s.get("codec_type") == "video" for s in streams)
                    has_audio = any(s.get("codec_type") == "audio" for s in streams)
                    if not has_video:
                        raise AssertionError("视频文件无视频流")
                    if not has_audio:
                        raise AssertionError("视频文件无音频流")
                    return {
                        "official_video": official,
                        "duration": probe_data.get("format", {}).get("duration"),
                        "size_bytes": probe_data.get("format", {}).get("size"),
                    }

                render_result = await stage_render()
                if render_result is None:
                    return report

            # === 阶段 6: 产物完整性 ===
            @_run_stage(report, "artifacts", "产物完整性")
            async def stage_artifacts():
                detail = job_detail(report.job_id)
                artifact_names = {item["name"] for item in detail.get("artifacts", {}).get("files", [])}
                required = {"script.json", "shot_plan.json", "asset_manifest.json"}
                missing = sorted(required - artifact_names)
                if missing:
                    raise AssertionError(f"缺失产物: {missing}")
                return {
                    "artifact_count": len(artifact_names),
                    "has_final_video": any(name.endswith(".mp4") for name in artifact_names),
                }

            await stage_artifacts()

        if report.overall_status != "failed":
            report.overall_status = "passed"

    except Exception as exc:
        report.overall_status = "failed"
        report.error = f"未预期异常: {exc}"
        traceback.print_exc()
    finally:
        if not keep_output:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            report.output_dir = "(已清理)"

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="短链路 E2E 验收")
    parser.add_argument("--skip-render", action="store_true",
                        help="跳过视频渲染阶段，只验证到计划校验")
    parser.add_argument("--keep-output", action="store_true",
                        help="保留输出目录用于排查")
    parser.add_argument("--json", action="store_true",
                        help="以 JSON 格式输出报告")
    args = parser.parse_args()

    report = asyncio.run(run_short_e2e(
        skip_render=args.skip_render,
        keep_output=args.keep_output,
    ))

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        report.print_summary()

    return 0 if report.overall_status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
