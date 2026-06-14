#!/usr/bin/env python3
"""渲染各风格的开场预览 HTML — 纯静态，不依赖 GSAP"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).parent / "assets" / "templates"
OUTPUT_DIR = Path(__file__).parent / "output" / "style_previews"

CST = timezone(timedelta(hours=8))


def make_mock_data():
    now = datetime.now(CST)
    return {
        "intro_screen": {"start": 0, "duration": 4},
        "list_screen": {"start": 4, "duration": 4},
        "detail_screen": {"start": 8, "duration": 4},
        "hook_screen": {"start": 12, "duration": 4},
        "total_projects": 8,
        "total_languages": 5,
        "total_new_stars": "2.4k",
        "date": f"{now.year} 年 {now.month} 月 {now.day} 日",
        "issue": now.isocalendar()[1],
        "theme_highlight": "LLM + 开发工具",
        "theme_tags": ["AI", "开发效率", "开源"],
        "languages": [
            {"name": "Python", "color": "#3572A5"},
            {"name": "TypeScript", "color": "#3178c6"},
            {"name": "Rust", "color": "#dea584"},
            {"name": "Go", "color": "#00ADD8"},
            {"name": "C++", "color": "#f34b7d"},
        ],
        "top_projects": [
            {
                "rank": 1, "name": "DevChat", "owner": "devchat-ai",
                "hook": "让 AI 成为你的代码伙伴",
                "proof_point": "基于 RAG 的代码问答，支持多种模型",
                "language": "Python", "language_color": "#3572A5",
                "stars_display": "18.2k ★",
                "trend_heat": "hot", "trend_label": "估算热度↑↑",
                "display_tags": ["AI", "RAG", "代码助手"],
                "preview_url": "https://github.com/devchat-ai/devchat",
            },
            {
                "rank": 2, "name": "Bolt", "owner": "stackblitz",
                "hook": "浏览器里的 VS Code",
                "proof_point": "WebContainer 技术，云端开发环境",
                "language": "TypeScript", "language_color": "#3178c6",
                "stars_display": "12.8k ★",
                "trend_heat": "warm", "trend_label": "估算热度↑",
                "display_tags": ["IDE", "WebContainer"],
                "preview_url": "https://github.com/stackblitz/bolt",
            },
            {
                "rank": 3, "name": "SWIFT", "owner": "ratatui-org",
                "hook": "终端 UI 也能很优雅",
                "proof_point": "Rust 写的 TUI 框架，性能极佳",
                "language": "Rust", "language_color": "#dea584",
                "stars_display": "9.1k ★",
                "trend_heat": "hot", "trend_label": "估算热度↑↑",
                "display_tags": ["TUI", "Rust"],
                "preview_url": "https://github.com/ratatui-org/ratatui",
            },
        ],
        "top1": {
            "name": "DevChat",
            "hook": "让 AI 成为你的代码伙伴",
            "stars_display": "18.2k ★",
            "language": "Python",
            "language_color": "#3572A5",
            "owner_avatar_url": "https://avatars.githubusercontent.com/u/1234567",
        },
    }


def render_all_styles():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    from src.hotlist_v2.template import (
        STYLE_PROFILES, TEMPLATE_REGISTRY, DEFAULT_STYLE, DEFAULT_DURATIONS,
    )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,
    )

    data = make_mock_data()

    for style_key in STYLE_PROFILES:
        profile = STYLE_PROFILES[style_key]
        template_file = TEMPLATE_REGISTRY[style_key]["template_file"]
        template = env.get_template(template_file)

        context = {
            **DEFAULT_DURATIONS,
            **data,
            "style_key": style_key,
            "default_style_profile": STYLE_PROFILES[DEFAULT_STYLE],
            "style_profile": profile,
            "style_registry": TEMPLATE_REGISTRY[style_key],
        }

        html = template.render(**context)

        # 关键修复：
        # 1. 删除所有 .screen 的 visibility:hidden / opacity:0
        # 2. 注入 CSS 隐藏非 intro screens
        # 3. 删除所有 CSS animation（fadeInUp 等会让元素初始 opacity:0）
        # 4. 删除 GSAP script（不需要动画）

        import re
        # 替换 .screen { ... visibility: hidden; opacity: 0; ... }
        html = re.sub(
            r'\.screen\s*\{[^}]*visibility:\s*hidden;[^}]*\}',
            '.screen { position: absolute; top: 0; left: 0; width: 100%; height: 100%; }',
            html
        )

        # 注入 CSS：隐藏非 intro screens，让 intro 可见
        hide_css = """
<style>
  #screen-list, #screen-detail, #screen-hook { display: none !important; }
  #screen-intro { visibility: visible !important; opacity: 1 !important; }
</style>
"""
        html = html.replace("</head>", hide_css + "</head>")

        # 删除所有 CSS animation 定义和引用
        html = re.sub(r'@keyframes\s+\w+\s*\{[^}]*\}', '', html)
        html = re.sub(r'animation:\s*[^;]+;', '', html)
        html = re.sub(r'animation-delay:\s*[^;]+;', '', html)

        # 删除 GSAP script
        html = re.sub(
            r'<script>\s*// GSAP timeline.*?</script>',
            '', html, flags=re.DOTALL
        )

        # 删除 GSAP CDN script tag
        html = re.sub(
            r'<script\s+src="[^"]*gsap[^"]*"\s*></script>',
            '', html
        )

        out_path = OUTPUT_DIR / f"{style_key}.html"
        out_path.write_text(html, encoding="utf-8")
        print(f"  ✅ {style_key} → {out_path}")

    # 生成导航页
    index_html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>视觉风格预览</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, sans-serif; background: #111; color: #fff; padding: 40px; }
  h1 { font-size: 24px; margin-bottom: 24px; color: #f0f0f0; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
  .card { background: #1a1a1a; border-radius: 16px; overflow: hidden; transition: transform 0.2s, box-shadow 0.2s; border: 1px solid #333; cursor: pointer; }
  .card:hover { transform: translateY(-4px); box-shadow: 0 12px 40px rgba(0,0,0,0.6); }
  .card iframe { width: 100%; height: 560px; border: none; display: block; }
  .card-info { padding: 14px 18px; }
  .card-name { font-size: 15px; font-weight: 600; margin-bottom: 3px; }
  .card-key { font-size: 12px; color: #666; font-family: monospace; margin-bottom: 6px; }
  .card-theme { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; }
  .theme-dark { background: #2a2a2a; color: #ccc; }
  .theme-light { background: #eee; color: #333; }
</style>
</head>
<body>
<h1>🎨 视觉风格预览 — 开场热榜速递</h1>
<div class="grid">
"""

    for style_key in STYLE_PROFILES:
        label = TEMPLATE_REGISTRY[style_key]["label"]
        theme = "dark" if STYLE_PROFILES[style_key].get("theme") == "dark" else "light"
        index_html += f"""
  <div class="card">
    <iframe src="{style_key}.html" loading="lazy"></iframe>
    <div class="card-info">
      <div class="card-name">{label}</div>
      <div class="card-key">{style_key}</div>
      <div class="card-theme theme-{theme}">{'深色' if theme == 'dark' else '浅色'}主题</div>
    </div>
  </div>
"""

    index_html += """
</div>
</body>
</html>"""

    index_path = OUTPUT_DIR / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    print(f"\n  🌐 导航页 → {index_path}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    render_all_styles()
