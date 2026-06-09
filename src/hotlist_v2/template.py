"""Jinja2 template rendering for hotlist v2 HTML composition."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "templates"
STYLE_TEMPLATES = {
    "tech_hotspot": "hotlist-v2.html",
}
DEFAULT_STYLE = "tech_hotspot"

DEFAULT_DURATIONS = {
    "intro_duration": 4,
    "list_duration": 4,
    "detail_duration": 4,
    "hook_duration": 4,
}


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
    template = env.get_template(STYLE_TEMPLATES.get(style, STYLE_TEMPLATES[DEFAULT_STYLE]))

    merged = {**DEFAULT_DURATIONS, **(durations or {})}
    html = template.render(**data, **merged)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
