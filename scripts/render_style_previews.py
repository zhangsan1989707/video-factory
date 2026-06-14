#!/usr/bin/env python3
"""Render static preview frames for all visual styles.

Quick start:
    .venv/bin/python scripts/render_style_previews.py

Options:
    .venv/bin/python scripts/render_style_previews.py --style tech_hotspot
    .venv/bin/python scripts/render_style_previews.py --style apple_minimal claude_warm
    .venv/bin/python scripts/render_style_previews.py --projects 7
    .venv/bin/python scripts/render_style_previews.py -o output/my-previews
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hotlist_v2.render import _data_from_projects, _timeline_context, _capture_html_screens
from src.hotlist_v2.template import render_composition, STYLE_PROFILES, supported_styles

# ---------------------------------------------------------------------------
# Sample project data — enough to fill all 4 screens meaningfully
# ---------------------------------------------------------------------------

SAMPLE_PROJECTS = [
    {
        "name": "OpenDevin",
        "full_name": "All-Hands-AI/OpenHands",
        "repo_url": "https://github.com/All-Hands-AI/OpenHands",
        "stars": 32800,
        "language": "Python",
        "description": "A platform for AI software engineers",
        "description_zh": "面向 AI 软件开发者的开源平台，能自主编写、调试和运行代码",
        "topics": ["ai", "agent", "llm", "coding-assistant"],
        "homepage": "https://www.all-hands.dev",
        "forks_count": 4200,
        "open_issues_count": 180,
        "audience": "AI 开发者",
        "daily_growth": "+850/天",
        "readme_excerpt": "OpenHands is a platform for autonomous software engineers.",
        "feature_extract": {
            "core_problem": "AI 写代码还靠人盯着",
            "core_action": "让 AI 自主完成编码、调试和测试全流程",
            "quantified_benefit": "减少 70% 重复编码时间",
        },
    },
    {
        "name": "RustDesk",
        "full_name": "rustdesk/rustdesk",
        "repo_url": "https://github.com/rustdesk/rustdesk",
        "stars": 78500,
        "language": "Rust",
        "description": "An open-source remote desktop application",
        "description_zh": "开源远程桌面工具，TeamViewer 的免费替代品",
        "topics": ["rust", "remote-desktop", "security", "self-hosted"],
        "homepage": "https://rustdesk.com",
        "forks_count": 9800,
        "open_issues_count": 420,
        "audience": "运维与远程办公",
        "daily_growth": "+320/天",
        "readme_excerpt": "RustDesk is a full-featured open source remote control software.",
        "feature_extract": {
            "core_problem": "远程桌面工具贵又不透明",
            "core_action": "用 Rust 实现高性能、可自部署的远程桌面",
            "quantified_benefit": "延迟低于 30ms，支持自建中继服务器",
        },
    },
    {
        "name": "LobeChat",
        "full_name": "lobehub/lobe-chat",
        "repo_url": "https://github.com/lobehub/lobe-chat",
        "stars": 52300,
        "language": "TypeScript",
        "description": "Modern design ChatGPT/LLMs UI and framework",
        "description_zh": "现代化设计的 ChatGPT 客户端，支持多模型、插件和知识库",
        "topics": ["chatgpt", "llm", "react", "nextjs", "ai"],
        "homepage": "https://chat-preview.lobehub.com",
        "forks_count": 12000,
        "open_issues_count": 260,
        "audience": "AI 爱好者",
        "daily_growth": "+560/天",
        "readme_excerpt": "LobeChat is an open-source, modern-design ChatGPT/LLMs UI.",
        "feature_extract": {
            "core_problem": "ChatGPT 官方界面功能单一",
            "core_action": "提供多模型切换、插件市场和知识库管理的一站式聊天界面",
            "quantified_benefit": "支持 10+ 大模型，插件生态覆盖 50+ 场景",
        },
    },
    {
        "name": "Dify",
        "full_name": "langgenius/dify",
        "repo_url": "https://github.com/langgenius/dify",
        "stars": 61200,
        "language": "Python",
        "description": "An open-source LLM app development platform",
        "description_zh": "开源 LLM 应用开发平台，可视化编排 Agent 和工作流",
        "topics": ["llm", "agent", "workflow", "low-code", "ai"],
        "homepage": "https://dify.ai",
        "forks_count": 10500,
        "open_issues_count": 350,
        "audience": "AI 产品经理和开发者",
        "daily_growth": "+480/天",
        "readme_excerpt": "Dify is an open-source LLM app development platform.",
        "feature_extract": {
            "core_problem": "搭 LLM 应用要从零写胶水代码",
            "core_action": "用可视化画布编排 Agent、RAG 和工作流，5 分钟上线应用",
            "quantified_benefit": "降低 80% LLM 应用搭建门槛",
        },
    },
    {
        "name": "Ollama",
        "full_name": "ollama/ollama",
        "repo_url": "https://github.com/ollama/ollama",
        "stars": 95000,
        "language": "Go",
        "description": "Get up and running with large language models locally",
        "description_zh": "一键本地运行大模型，支持 Llama、Mistral、Gemma 等主流开源模型",
        "topics": ["llm", "local-ai", "golang", "self-hosted"],
        "homepage": "https://ollama.com",
        "forks_count": 8200,
        "open_issues_count": 520,
        "audience": "AI 开发者和研究者",
        "daily_growth": "+620/天",
        "readme_excerpt": "Ollama makes it easy to get up and running with large language models.",
        "feature_extract": {
            "core_problem": "本地跑大模型环境配置复杂",
            "core_action": "一条命令下载并运行 Llama、Mistral 等模型，自动适配硬件",
            "quantified_benefit": "3 行命令完成部署，支持 GPU 加速",
        },
    },
]

# Key screens to capture (screen_id → filename suffix)
SCREEN_TARGETS = [
    ("screen-intro", "01-intro"),
    ("screen-list", "02-list"),
    ("screen-hook", "hook"),
]


def _build_targets(detail_count: int) -> list[tuple[str, str]]:
    """Build (screen_id, filename) pairs including detail screens."""
    targets = [("screen-intro", "01-intro"), ("screen-list", "02-list")]
    # Only capture the first detail screen to keep output concise
    if detail_count > 0:
        targets.append(("screen-detail-01", "03-detail"))
    targets.append(("screen-hook", f"{len(targets) + 1:02d}-hook"))
    return targets


def main():
    parser = argparse.ArgumentParser(
        description="渲染所有视觉风格的静态预览帧",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--style", "-s",
        nargs="+",
        default=None,
        choices=sorted(supported_styles()),
        help="指定要渲染的风格（默认全部）",
    )
    parser.add_argument(
        "--projects", "-p",
        type=int,
        default=5,
        choices=range(1, 10),
        help="测试数据项目数（默认 5）",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出目录（默认 output/style-previews）",
    )
    parser.add_argument(
        "--all-details",
        action="store_true",
        help="捕获所有详情页截图（默认只截第 1 个）",
    )
    args = parser.parse_args()

    styles = args.style or sorted(supported_styles())
    output_base = Path(args.output) if args.output else Path("output/style-previews")
    projects = SAMPLE_PROJECTS[: args.projects]

    # Pad if user requests more projects than sample data
    while len(projects) < args.projects:
        idx = len(projects)
        projects.append({
            "name": f"Project-{idx + 1}",
            "full_name": f"demo/project-{idx + 1}",
            "repo_url": "",
            "stars": max(50, 5000 - idx * 800),
            "language": "Python",
            "description": f"Sample project #{idx + 1}",
            "description_zh": f"示例项目 #{idx + 1}，用于验证视觉布局",
            "topics": ["ai", "tool"],
            "homepage": "",
            "forks_count": 100,
            "open_issues_count": 10,
            "audience": "开发者",
            "daily_growth": "+100/天",
            "readme_excerpt": "",
        })

    print(f"项目数: {len(projects)}  |  风格: {', '.join(styles)}  |  输出: {output_base.resolve()}\n")

    # Build render data once (shared across styles)
    data = _data_from_projects(projects, issue_number=24)
    timeline = _timeline_context(data, limit=args.projects)
    render_data = {**data, **timeline}

    detail_count = len(render_data.get("detail_screens") or [])
    targets = _build_targets(detail_count)
    if args.all_details:
        targets = [("screen-intro", "01-intro"), ("screen-list", "02-list")]
        for index, detail in enumerate(render_data.get("detail_screens") or [], start=1):
            targets.append((detail["screen_id"], f"{index + 2:02d}-detail"))
        targets.append(("screen-hook", f"{len(targets) + 1:02d}-hook"))

    total_start = time.time()

    for style in styles:
        style_dir = output_base / style
        html_dir = style_dir / "html"
        html_dir.mkdir(parents=True, exist_ok=True)

        # Render HTML
        html_path = html_dir / "composition.html"
        render_composition(render_data, html_path, style=style)

        # Build capture targets
        capture_targets = [
            (screen_id, style_dir / f"{name}.png")
            for screen_id, name in targets
        ]

        # Capture screenshots
        t0 = time.time()
        print(f"  {style}...", end="", flush=True)
        _capture_html_screens(html_path, capture_targets)
        elapsed = time.time() - t0
        print(f" {len(capture_targets)} 张截图  ({elapsed:.1f}s)")

    total_elapsed = time.time() - total_start
    print(f"\n完成: {len(styles)} 种风格, 每种 {len(targets)} 张截图, 耗时 {total_elapsed:.1f}s")
    print(f"输出目录: {output_base.resolve()}")


if __name__ == "__main__":
    main()
