"""Local render environment preflight checks."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.console.store import CONFIG_DIR, config_snapshot, read_json, write_json
from src.utils.config import ROOT_DIR


def preflight_snapshot() -> dict[str, Any]:
    checks = [
        _module_check("python.openai", "openai"),
        _module_check("python.edge_tts", "edge_tts"),
        _module_check("python.moviepy", "moviepy"),
        _module_check("python.PIL", "PIL"),
        _command_check("ffmpeg", "ffmpeg"),
        _command_check("ffprobe", "ffprobe"),
        _command_check("node", "node"),
        _command_check("npx", "npx"),
        _node_package_check("node.hyperframes", "hyperframes"),
        _playwright_browser_check(),
        *_config_checks(),
        _ffmpeg_smoke_check(),
        _hyperframes_cli_smoke_check(),
    ]
    blocking = [item for item in checks if item["status"] == "missing" and item["severity"] == "blocking"]
    warnings = [item for item in checks if item["status"] in {"missing", "warning"} and item["severity"] == "warning"]
    smoke_failed = [item for item in checks if item["id"].startswith("smoke.") and item["status"] == "missing"]
    status = "ready" if not blocking else "blocked"
    return {
        "status": status,
        "summary": _summary(status, len(warnings), not smoke_failed),
        "blocking_count": len(blocking),
        "warning_count": len(warnings),
        "checks": checks,
        "latest_real_smoke": latest_real_smoke(),
    }


def latest_real_smoke() -> dict[str, Any]:
    return read_json(CONFIG_DIR / "real-smoke.json", {})


def run_real_smoke_check() -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = {
        "status": "running",
        "started_at": started_at,
        "completed_at": "",
        "summary": "真实 smoke 运行中。",
        "output": "",
        "duration_seconds": None,
        "size": 0,
        "error": "",
    }
    write_json(CONFIG_DIR / "real-smoke.json", result)
    try:
        with tempfile.TemporaryDirectory(prefix="github-video-real-smoke-") as tmp:
            output = Path(tmp) / "final.mp4"
            _run_tiny_media_smoke(output)
            probe = _probe_media(output)
            result.update({
                "status": "passed",
                "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "summary": "低成本真实 smoke 通过：ffmpeg 生成短样例，ffprobe 可读取音视频流。",
                "output": str(output),
                "duration_seconds": probe["duration_seconds"],
                "size": probe["size"],
            })
    except Exception as exc:
        result.update({
            "status": "failed",
            "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "summary": "低成本真实 smoke 失败，请查看错误并运行完整 E2E 清单。",
            "error": _short_error(exc),
        })
    write_json(CONFIG_DIR / "real-smoke.json", result)
    return result


def _run_tiny_media_smoke(output: Path) -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("缺少 ffmpeg 或 ffprobe")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:d=0.5",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-shortest",
            "-y",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=8,
    )


def _probe_media(output: Path) -> dict[str, Any]:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-show_streams",
            "-of",
            "json",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    data = json.loads(probe.stdout or "{}")
    streams = data.get("streams", [])
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise RuntimeError("smoke 输出缺少 video stream")
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise RuntimeError("smoke 输出缺少 audio stream")
    return {
        "duration_seconds": round(float(data.get("format", {}).get("duration") or 0), 2),
        "size": int(data.get("format", {}).get("size") or output.stat().st_size),
    }


def _summary(status: str, warning_count: int, smoke_passed: bool = True) -> str:
    if status != "ready":
        return "本机渲染依赖或 smoke 检查未通过，最终出片可能失败。"
    if warning_count:
        return f"本机渲染依赖和 smoke 可用，但有 {warning_count} 项配置警告。"
    return "本机渲染依赖和 smoke 均可用。"


def _module_check(check_id: str, module_name: str) -> dict[str, Any]:
    found = importlib.util.find_spec(module_name) is not None
    return {
        "id": check_id,
        "label": f"Python module: {module_name}",
        "status": "ok" if found else "missing",
        "severity": "blocking",
        "message": "已安装" if found else f"缺少 Python 模块 {module_name}",
    }


def _command_check(check_id: str, command: str) -> dict[str, Any]:
    path = shutil.which(command)
    return {
        "id": check_id,
        "label": f"Command: {command}",
        "status": "ok" if path else "missing",
        "severity": "blocking",
        "message": path or f"PATH 中找不到 {command}",
    }


def _node_package_check(check_id: str, package_name: str) -> dict[str, Any]:
    package_path = ROOT_DIR / "node_modules" / package_name / "package.json"
    found = package_path.exists() and package_path.is_file()
    return {
        "id": check_id,
        "label": f"Node package: {package_name}",
        "status": "ok" if found else "missing",
        "severity": "blocking",
        "message": "已安装" if found else f"缺少 Node 依赖 {package_name}，请运行 npm install",
    }


def _playwright_browser_check() -> dict[str, Any]:
    roots = [
        Path.home() / "Library" / "Caches" / "ms-playwright",
        Path.home() / ".cache" / "ms-playwright",
    ]
    installed = any(root.exists() and any(root.iterdir()) for root in roots)
    return {
        "id": "playwright.browsers",
        "label": "Playwright browsers",
        "status": "ok" if installed else "missing",
        "severity": "blocking",
        "message": "已发现浏览器缓存" if installed else "未发现 Playwright 浏览器缓存，请运行 playwright install",
    }


def _ffmpeg_smoke_check() -> dict[str, Any]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return _smoke_result(
            "smoke.ffmpeg_ffprobe",
            "ffmpeg/ffprobe smoke",
            False,
            "缺少 ffmpeg 或 ffprobe，无法执行短视频 smoke。请先安装 ffmpeg 并确认命令在 PATH 中。",
        )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "smoke.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=16x16:d=0.2",
                    "-an",
                    "-y",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            duration = float((probe.stdout or "").strip())
            return _smoke_result(
                "smoke.ffmpeg_ffprobe",
                "ffmpeg/ffprobe smoke",
                output.exists() and duration > 0,
                f"短视频 smoke 通过，样例时长 {duration:.1f}s。",
            )
    except Exception as exc:
        return _smoke_result(
            "smoke.ffmpeg_ffprobe",
            "ffmpeg/ffprobe smoke",
            False,
            f"ffmpeg/ffprobe smoke 失败：{_short_error(exc)}。请执行 ffmpeg -version 和 ffprobe -version 排查安装与编码器。",
        )


def _hyperframes_cli_smoke_check() -> dict[str, Any]:
    if not shutil.which("npx"):
        return _smoke_result(
            "smoke.hyperframes_cli",
            "HyperFrames CLI smoke",
            False,
            "缺少 npx，无法验证 HyperFrames CLI。请安装 Node.js/npm。",
        )
    if not (ROOT_DIR / "node_modules" / "hyperframes" / "package.json").exists():
        return _smoke_result(
            "smoke.hyperframes_cli",
            "HyperFrames CLI smoke",
            False,
            "缺少 HyperFrames Node 依赖。请运行 npm install。",
        )
    try:
        subprocess.run(
            ["npx", "hyperframes", "--help"],
            cwd=ROOT_DIR,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return _smoke_result(
            "smoke.hyperframes_cli",
            "HyperFrames CLI smoke",
            True,
            "HyperFrames CLI 可启动。",
        )
    except Exception as exc:
        return _smoke_result(
            "smoke.hyperframes_cli",
            "HyperFrames CLI smoke",
            False,
            f"HyperFrames CLI smoke 失败：{_short_error(exc)}。请运行 npm install 或 npx hyperframes doctor。",
        )


def _smoke_result(check_id: str, label: str, ok: bool, message: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "ok" if ok else "missing",
        "severity": "blocking",
        "message": message,
    }


def _config_checks() -> list[dict[str, Any]]:
    config = config_snapshot()
    providers = config.get("providers", {}).get("providers", [])
    enabled = [provider for provider in providers if provider.get("enabled") and provider.get("configured")]
    github = config.get("github", {})
    provider_status, provider_message = _model_provider_status(enabled)
    return [
        {
            "id": "config.github_token",
            "label": "GitHub Token",
            "status": "ok" if github.get("configured") else "warning",
            "severity": "warning",
            "message": "已配置" if github.get("configured") else "未配置，GitHub API 容易触发低额度限制",
        },
        {
            "id": "config.model_provider",
            "label": "Model provider",
            "status": provider_status,
            "severity": "warning",
            "message": provider_message,
        },
    ]


def _model_provider_status(providers: list[dict[str, Any]]) -> tuple[str, str]:
    if not providers:
        return "warning", "未配置可用模型供应商，AI 阶段将使用默认/跳过逻辑"

    passed = [provider for provider in providers if str(provider.get("last_test") or "").startswith("连接成功")]
    if passed:
        return "ok", f"{len(passed)} 个供应商已通过连接测试"

    failed = [provider for provider in providers if str(provider.get("last_test") or "").startswith("连接失败")]
    if failed:
        return "warning", f"{len(providers)} 个供应商已配置，但最近连接测试失败"

    return "warning", f"{len(providers)} 个供应商已配置，但尚未通过连接测试"


def _short_error(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:180] or exc.__class__.__name__
