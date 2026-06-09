"""Asset manifest generation."""

import re
from urllib.parse import urljoin, urlparse

from src.models import AssetManifest, ProjectInfo, VisualAsset


IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


def _raw_github_url(project: ProjectInfo, value: str) -> str:
    value = value.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("./"):
        value = value[2:]
    return (
        f"https://raw.githubusercontent.com/{project.owner}/{project.name}/"
        f"{project.default_branch}/{value}"
    )


def _looks_like_homepage(url: str, project: ProjectInfo) -> bool:
    host = urlparse(url).netloc.lower()
    if not host or "github.com" in host:
        return False
    if project.homepage and url.rstrip("/") == project.homepage.rstrip("/"):
        return True
    return any(part.lower() in host for part in project.name.lower().split("-") if part)


def generate_asset_manifest(project: ProjectInfo) -> AssetManifest:
    """Collect usable visual material references from repo metadata."""
    assets: list[VisualAsset] = []
    seen_sources: set[str] = set()

    def add_asset(type_: str, source: str, caption: str, use_case: str, quality: str) -> None:
        if source in seen_sources:
            return
        seen_sources.add(source)
        assets.append(VisualAsset(
            id=f"asset-{len(assets) + 1:03d}",
            type=type_,
            source=source,
            path=source,
            caption=caption,
            use_case=use_case,
            quality=quality,
        ))

    if project.homepage:
        add_asset(
            "webpage",
            project.homepage,
            "项目官网或在线演示",
            "展示真实产品界面",
            "high",
        )

    for match in IMAGE_RE.finditer(project.readme):
        source = _raw_github_url(project, match.group(1))
        add_asset(
            "image",
            source,
            "README 产品截图",
            "展示功能实际长相",
            "high",
        )
        if len(assets) >= 5:
            break

    for label, url in LINK_RE.findall(project.readme):
        if _looks_like_homepage(url, project):
            add_asset(
                "webpage",
                urljoin(url, "/"),
                label.strip() or "项目页面",
                "补充真实界面截图",
                "medium",
            )
        if len(assets) >= 7:
            break

    if "```" in project.readme:
        add_asset(
            "readme_code",
            f"{project.repo_url}#readme",
            "README 安装或调用代码",
            "说明项目怎么使用",
            "medium",
        )

    add_asset(
        "github_repo",
        project.repo_url,
        "GitHub 仓库来源页",
        "作为项目来源证明",
        "low",
    )

    return AssetManifest(assets=assets)
