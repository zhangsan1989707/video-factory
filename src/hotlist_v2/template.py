"""Jinja2 template rendering for hotlist v2 HTML composition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "templates"
DEFAULT_STYLE = "tech_hotspot"

DEFAULT_STYLE_PARAMS = {
    "project_count": 5,
    "render_engine": "hyperframes",
    "subtitle_mode": "large_hook",
    "bgm": "default",
    "narration_tone": "professional_review",
    "orientation": "vertical",
}

STYLE_PROFILES: dict[str, dict[str, str]] = {
    "tech_hotspot": {
        "canvas_bg": "#040914",
        "bg_deep": "#07101d",
        "bg_card": "#0d1728",
        "bg_panel": "#10213a",
        "accent_cyan": "#00d4ff",
        "accent_cyan_rgb": "0, 212, 255",
        "accent_blue": "#3b82f6",
        "accent_blue_rgb": "59, 130, 246",
        "accent_purple": "#8b5cf6",
        "accent_purple_rgb": "139, 92, 246",
        "accent_green": "#10b981",
        "accent_green_rgb": "16, 185, 129",
        "accent_amber": "#f59e0b",
        "accent_amber_rgb": "245, 158, 11",
        "text_primary": "#f6f9ff",
        "text_secondary": "#a9b8d4",
        "text_dim": "#7184a7",
        "font_display": "'Orbitron', monospace",
        "font_body": "'Space Grotesk', sans-serif",
        "font_mono": "'JetBrains Mono', monospace",
    },
    "apple_minimal": {
        "canvas_bg": "#f5f5f7",
        "bg_deep": "#f5f5f7",
        "bg_card": "#ffffff",
        "bg_panel": "#f0f0f2",
        "accent_cyan": "#007aff",
        "accent_cyan_rgb": "0, 122, 255",
        "accent_blue": "#3395ff",
        "accent_blue_rgb": "51, 149, 255",
        "accent_purple": "#af52de",
        "accent_purple_rgb": "175, 82, 222",
        "accent_green": "#34c759",
        "accent_green_rgb": "52, 199, 89",
        "accent_amber": "#ff9500",
        "accent_amber_rgb": "255, 149, 0",
        "text_primary": "#1d1d1f",
        "text_secondary": "#5f6368",
        "text_dim": "#86868b",
        "font_display": "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Helvetica Neue', sans-serif",
        "font_body": "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif",
        "font_mono": "'SF Mono', 'Menlo', 'Consolas', monospace",
    },
    "claude_warm": {
        "canvas_bg": "#faf7f2",
        "bg_deep": "#faf7f2",
        "bg_card": "#ffffff",
        "bg_panel": "#f5f0ea",
        "accent_cyan": "#d97706",
        "accent_cyan_rgb": "217, 119, 6",
        "accent_blue": "#ea580c",
        "accent_blue_rgb": "234, 88, 12",
        "accent_purple": "#7c3aed",
        "accent_purple_rgb": "124, 58, 237",
        "accent_green": "#16a34a",
        "accent_green_rgb": "22, 163, 74",
        "accent_amber": "#f59e0b",
        "accent_amber_rgb": "245, 158, 11",
        "text_primary": "#1c1917",
        "text_secondary": "#78716c",
        "text_dim": "#a8a29e",
        "font_display": "system-ui, -apple-system, 'Segoe UI', sans-serif",
        "font_body": "system-ui, -apple-system, 'Segoe UI', sans-serif",
        "font_mono": "'SF Mono', 'Menlo', 'Consolas', monospace",
    },
    "sspai_editorial": {
        "canvas_bg": "#faf9f7",
        "bg_deep": "#faf9f7",
        "bg_card": "#ffffff",
        "bg_panel": "#f5f4f2",
        "accent_cyan": "#d71a1b",
        "accent_cyan_rgb": "215, 26, 27",
        "accent_blue": "#b31516",
        "accent_blue_rgb": "179, 21, 22",
        "accent_purple": "#8a2d2d",
        "accent_purple_rgb": "138, 45, 45",
        "accent_green": "#337a5b",
        "accent_green_rgb": "51, 122, 91",
        "accent_amber": "#b8872b",
        "accent_amber_rgb": "184, 135, 43",
        "text_primary": "#1a1a1a",
        "text_secondary": "#555555",
        "text_dim": "#999999",
        "font_display": "'Noto Serif SC', 'STSong', serif",
        "font_body": "'Noto Sans SC', -apple-system, sans-serif",
        "font_mono": "'Noto Sans SC', -apple-system, sans-serif",
    },
    "bytedance_product": {
        "canvas_bg": "#f7f8fa",
        "bg_deep": "#f7f8fa",
        "bg_card": "#ffffff",
        "bg_panel": "#f0f2f5",
        "accent_cyan": "#3259e8",
        "accent_cyan_rgb": "50, 89, 232",
        "accent_blue": "#5b7af0",
        "accent_blue_rgb": "91, 122, 240",
        "accent_purple": "#7a5cff",
        "accent_purple_rgb": "122, 92, 255",
        "accent_green": "#00b96b",
        "accent_green_rgb": "0, 185, 107",
        "accent_amber": "#ff7d00",
        "accent_amber_rgb": "255, 125, 0",
        "text_primary": "#1d2129",
        "text_secondary": "#4e5969",
        "text_dim": "#86909c",
        "font_display": "'Noto Sans SC', -apple-system, sans-serif",
        "font_body": "'Noto Sans SC', -apple-system, sans-serif",
        "font_mono": "'JetBrains Mono', monospace",
    },
    "chinese_editorial": {
        "canvas_bg": "#f5f0e8",
        "bg_deep": "#f5f0e8",
        "bg_card": "#fffaf0",
        "bg_panel": "#e8e0d0",
        "accent_cyan": "#c41e3a",
        "accent_cyan_rgb": "196, 30, 58",
        "accent_blue": "#8b1a2b",
        "accent_blue_rgb": "139, 26, 43",
        "accent_purple": "#7b3f18",
        "accent_purple_rgb": "123, 63, 24",
        "accent_green": "#557a46",
        "accent_green_rgb": "85, 122, 70",
        "accent_amber": "#c9a84c",
        "accent_amber_rgb": "201, 168, 76",
        "text_primary": "#1a1a1a",
        "text_secondary": "#6b5e4e",
        "text_dim": "#a09888",
        "font_display": "'Noto Serif SC', 'STSong', serif",
        "font_body": "'Noto Serif SC', 'STSong', serif",
        "font_mono": "'Noto Sans SC', -apple-system, sans-serif",
    },
}

TEMPLATE_REGISTRY: dict[str, dict[str, Any]] = {
    "tech_hotspot": {
        "style": "tech_hotspot",
        "label": "科技热点风",
        "template_file": "hotlist-v2.html",
        "render_engine": "hyperframes",
        "default_params": dict(DEFAULT_STYLE_PARAMS),
        "supports_preview": True,
        "source_reference": "hotlist-v2.html",
    },
    "apple_minimal": {
        "style": "apple_minimal",
        "label": "Apple 极简风",
        "template_file": "hotlist-v2.html",
        "render_engine": "hyperframes",
        "default_params": dict(DEFAULT_STYLE_PARAMS),
        "supports_preview": True,
        "source_reference": "github-trending-screens-v3-apple.html",
    },
    "claude_warm": {
        "style": "claude_warm",
        "label": "Claude 暖橘风",
        "template_file": "hotlist-v2.html",
        "render_engine": "hyperframes",
        "default_params": dict(DEFAULT_STYLE_PARAMS),
        "supports_preview": True,
        "source_reference": "github-trending-screens-v4-claude.html",
    },
    "sspai_editorial": {
        "style": "sspai_editorial",
        "label": "少数派编辑风",
        "template_file": "hotlist-v2.html",
        "render_engine": "hyperframes",
        "default_params": {**DEFAULT_STYLE_PARAMS, "narration_tone": "calm_analysis"},
        "supports_preview": True,
        "source_reference": "github-trending-screens-v10-sspai.html",
    },
    "bytedance_product": {
        "style": "bytedance_product",
        "label": "字节产品风",
        "template_file": "hotlist-v2.html",
        "render_engine": "hyperframes",
        "default_params": dict(DEFAULT_STYLE_PARAMS),
        "supports_preview": True,
        "source_reference": "github-trending-screens-v8-bytedance.html",
    },
    "chinese_editorial": {
        "style": "chinese_editorial",
        "label": "中国风编辑版",
        "template_file": "hotlist-v2.html",
        "render_engine": "hyperframes",
        "default_params": {**DEFAULT_STYLE_PARAMS, "narration_tone": "calm_analysis"},
        "supports_preview": True,
        "source_reference": "github-trending-screens-v5-chinese.html",
    },
}

STYLE_ALIASES = {
    "tech_dark": "tech_hotspot",
    "minimal_white": "apple_minimal",
    "black_gold": "chinese_editorial",
}

STYLE_TEMPLATES = {
    style: str(item["template_file"])
    for style, item in TEMPLATE_REGISTRY.items()
}

DEFAULT_DURATIONS = {
    "intro_duration": 4,
    "list_duration": 4,
    "detail_duration": 4,
    "hook_duration": 4,
}


def supported_styles() -> set[str]:
    return set(TEMPLATE_REGISTRY)


def normalize_style(style: str | None) -> str:
    key = str(style or "").strip()
    key = STYLE_ALIASES.get(key, key)
    return key if key in TEMPLATE_REGISTRY else DEFAULT_STYLE


def render_engine_for_style(style: str | None) -> str:
    return str(TEMPLATE_REGISTRY[normalize_style(style)]["render_engine"])


def default_params_for_style(style: str | None) -> dict[str, Any]:
    key = normalize_style(style)
    return dict(TEMPLATE_REGISTRY[key]["default_params"])


def list_template_styles() -> list[dict[str, Any]]:
    return [
        {
            "style": item["style"],
            "label": item["label"],
            "template_file": item["template_file"],
            "render_engine": item["render_engine"],
            "default_params": dict(item["default_params"]),
            "supports_preview": bool(item["supports_preview"]),
            "source_reference": item["source_reference"],
        }
        for item in TEMPLATE_REGISTRY.values()
    ]


def render_composition(
    data: dict,
    output_path: Path,
    durations: dict[str, int] | None = None,
    style: str = DEFAULT_STYLE,
) -> Path:
    """Render the hotlist v2 HTML composition from data.

    Args:
        data: Trending data dict from fetch.py
        output_path: Where to write the rendered HTML
        durations: Optional overrides for screen durations (seconds)
        style: Visual style key

    Returns:
        Path to the rendered HTML file
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,
    )
    style_key = normalize_style(style)
    template = env.get_template(STYLE_TEMPLATES[style_key])

    merged = {**DEFAULT_DURATIONS, **(durations or {})}
    context = {
        **merged,
        **data,
        "style_key": style_key,
        "default_style_profile": STYLE_PROFILES[DEFAULT_STYLE],
        "style_profile": STYLE_PROFILES[style_key],
        "style_registry": TEMPLATE_REGISTRY[style_key],
    }
    html = template.render(**context)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
