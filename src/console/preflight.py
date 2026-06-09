"""Local render environment preflight checks."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any

from src.console.store import config_snapshot


def preflight_snapshot() -> dict[str, Any]:
    checks = [
        _module_check("python.openai", "openai"),
        _module_check("python.edge_tts", "edge_tts"),
        _module_check("python.moviepy", "moviepy"),
        _module_check("python.PIL", "PIL"),
        _command_check("ffmpeg", "ffmpeg"),
        _playwright_browser_check(),
        *_config_checks(),
    ]
    blocking = [item for item in checks if item["status"] == "missing" and item["severity"] == "blocking"]
    warnings = [item for item in checks if item["status"] in {"missing", "warning"} and item["severity"] == "warning"]
    status = "ready" if not blocking else "blocked"
    return {
        "status": status,
        "summary": _summary(status, len(warnings)),
        "blocking_count": len(blocking),
        "warning_count": len(warnings),
        "checks": checks,
    }


def _summary(status: str, warning_count: int) -> str:
    if status != "ready":
        return "本机渲染依赖不完整，最终出片可能失败。"
    if warning_count:
        return f"本机渲染依赖可用，但有 {warning_count} 项配置警告。"
    return "本机渲染依赖可用。"


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
