"""Jinja2 template rendering for hotlist v2 HTML composition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

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
        # --- deep-restore visual params ---
        "theme": "dark",
        "deco_type": "cyber",
        "card_bg": "rgba(13, 23, 40, 0.94)",
        "card_border": "1px solid rgba(255,255,255,0.11)",
        "card_border_radius": "20px",
        "card_shadow": "inset 0 1px 0 rgba(255,255,255,0.04)",
        "item_border_radius": "20px",
        "badge_border_radius": "24px",
        "border_width": "1px",
        "border_color": "rgba(255,255,255,0.11)",
        "show_scanline": "1",
        "show_grid": "1",
        "show_orbit_rings": "1",
        "show_glow_orbs": "1",
        "stat_chip_bg": "var(--bg-panel)",
        "stat_chip_border": "1px solid var(--border-blue)",
        "stat_chip_radius": "22px",
        "stat_chip_shadow": "inset 0 1px 0 rgba(255,255,255,0.06), 0 18px 60px rgba(0,0,0,0.18)",
        "metric_card_bg": "rgba(13, 23, 40, 0.95)",
        "metric_card_border": "1px solid rgba(255,255,255,0.1)",
        "metric_card_radius": "18px",
        "reason_border_radius": "18px",
        "hook_card_bg": "rgba(20, 35, 60, 0.85)",
        "hook_card_border": "1px solid rgba(255,255,255,0.1)",
        "hook_card_radius": "18px",
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
        # --- deep-restore visual params ---
        "theme": "light",
        "deco_type": "apple",
        "card_bg": "rgba(255,255,255,0.72)",
        "card_border": "0.5px solid rgba(0,0,0,0.06)",
        "card_border_radius": "16px",
        "card_shadow": "0 2px 12px rgba(0,0,0,0.04)",
        "item_border_radius": "16px",
        "badge_border_radius": "20px",
        "border_width": "0.5px",
        "border_color": "rgba(0,0,0,0.06)",
        "show_scanline": "0",
        "show_grid": "0",
        "show_orbit_rings": "1",
        "show_glow_orbs": "1",
        "stat_chip_bg": "rgba(255,255,255,0.72)",
        "stat_chip_border": "0.5px solid rgba(0,0,0,0.06)",
        "stat_chip_radius": "16px",
        "stat_chip_shadow": "0 2px 12px rgba(0,0,0,0.04)",
        "metric_card_bg": "var(--bg-panel)",
        "metric_card_border": "0.5px solid rgba(0,0,0,0.06)",
        "metric_card_radius": "14px",
        "reason_border_radius": "14px",
        "hook_card_bg": "var(--bg-panel)",
        "hook_card_border": "0.5px solid rgba(0,0,0,0.06)",
        "hook_card_radius": "16px",
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
        # --- deep-restore visual params ---
        "theme": "light",
        "deco_type": "warm",
        "card_bg": "#ffffff",
        "card_border": "1px solid rgba(0,0,0,0.06)",
        "card_border_radius": "18px",
        "card_shadow": "0 1px 3px rgba(120,80,20,0.06)",
        "item_border_radius": "18px",
        "badge_border_radius": "24px",
        "border_width": "1px",
        "border_color": "rgba(0,0,0,0.06)",
        "show_scanline": "0",
        "show_grid": "0",
        "show_orbit_rings": "1",
        "show_glow_orbs": "1",
        "stat_chip_bg": "#ffffff",
        "stat_chip_border": "1px solid rgba(0,0,0,0.06)",
        "stat_chip_radius": "18px",
        "stat_chip_shadow": "0 1px 3px rgba(120,80,20,0.06)",
        "metric_card_bg": "#ffffff",
        "metric_card_border": "1px solid rgba(0,0,0,0.06)",
        "metric_card_radius": "16px",
        "reason_border_radius": "16px",
        "hook_card_bg": "#ffffff",
        "hook_card_border": "1px solid rgba(0,0,0,0.06)",
        "hook_card_radius": "18px",
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
        # --- deep-restore visual params ---
        "theme": "light",
        "deco_type": "editorial",
        "card_bg": "#ffffff",
        "card_border": "1px solid #e8e6e1",
        "card_border_radius": "0px",
        "card_shadow": "none",
        "item_border_radius": "0px",
        "badge_border_radius": "0px",
        "border_width": "1px",
        "border_color": "#e8e6e1",
        "show_scanline": "0",
        "show_grid": "0",
        "show_orbit_rings": "0",
        "show_glow_orbs": "0",
        "stat_chip_bg": "transparent",
        "stat_chip_border": "none",
        "stat_chip_radius": "0px",
        "stat_chip_shadow": "none",
        "metric_card_bg": "#ffffff",
        "metric_card_border": "1px solid #e8e6e1",
        "metric_card_radius": "0px",
        "reason_border_radius": "0px",
        "hook_card_bg": "#ffffff",
        "hook_card_border": "1px solid #e8e6e1",
        "hook_card_radius": "0px",
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
        # --- deep-restore visual params ---
        "theme": "light",
        "deco_type": "gradient_spot",
        "card_bg": "#ffffff",
        "card_border": "none",
        "card_border_radius": "16px",
        "card_shadow": "0 1px 6px rgba(0,0,0,0.03)",
        "item_border_radius": "16px",
        "badge_border_radius": "20px",
        "border_width": "0",
        "border_color": "transparent",
        "show_scanline": "0",
        "show_grid": "0",
        "show_orbit_rings": "0",
        "show_glow_orbs": "1",
        "stat_chip_bg": "transparent",
        "stat_chip_border": "none",
        "stat_chip_radius": "0px",
        "stat_chip_shadow": "none",
        "metric_card_bg": "#ffffff",
        "metric_card_border": "none",
        "metric_card_radius": "12px",
        "reason_border_radius": "12px",
        "hook_card_bg": "#ffffff",
        "hook_card_border": "none",
        "hook_card_radius": "14px",
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
        # --- deep-restore visual params ---
        "theme": "light",
        "deco_type": "chinese",
        "card_bg": "#ffffff",
        "card_border": "1px solid rgba(201,168,76,0.18)",
        "card_border_radius": "12px",
        "card_shadow": "none",
        "item_border_radius": "12px",
        "badge_border_radius": "20px",
        "border_width": "1px",
        "border_color": "rgba(201,168,76,0.25)",
        "show_scanline": "0",
        "show_grid": "0",
        "show_orbit_rings": "0",
        "show_glow_orbs": "0",
        "stat_chip_bg": "transparent",
        "stat_chip_border": "none",
        "stat_chip_radius": "0px",
        "stat_chip_shadow": "none",
        "metric_card_bg": "#ffffff",
        "metric_card_border": "1px solid rgba(201,168,76,0.15)",
        "metric_card_radius": "10px",
        "reason_border_radius": "10px",
        "hook_card_bg": "#ffffff",
        "hook_card_border": "1px solid rgba(201,168,76,0.15)",
        "hook_card_radius": "10px",
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
        autoescape=select_autoescape(["html"]),
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
