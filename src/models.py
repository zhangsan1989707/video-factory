"""数据模型定义"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProjectInfo:
    """GitHub 项目信息"""
    name: str
    owner: str
    description: str
    readme: str
    stars: int
    language: str
    topics: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    repo_url: str = ""
    homepage: str = ""
    default_branch: str = "main"

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass
class ScriptSegment:
    """视频脚本片段"""
    timestamp: float
    duration: float
    narration: str
    action: str  # navigate/scroll/click/highlight/zoom
    target: str
    focus_area: str = ""


@dataclass
class VideoScript:
    """视频脚本"""
    title: str
    segments: list[ScriptSegment]
    total_duration: float

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "total_duration": self.total_duration,
            "segments": [
                {
                    "timestamp": s.timestamp,
                    "duration": s.duration,
                    "narration": s.narration,
                    "action": s.action,
                    "target": s.target,
                    "focus_area": s.focus_area,
                }
                for s in self.segments
            ],
        }


@dataclass
class Frame:
    """视频帧"""
    image: bytes
    timestamp: float
    segment_index: int


@dataclass
class ProjectPaths:
    """项目输出路径"""
    base: Path

    @property
    def info_json(self) -> Path:
        return self.base / "info.json"

    @property
    def script_json(self) -> Path:
        return self.base / "script.json"

    @property
    def creative_brief_json(self) -> Path:
        return self.base / "creative_brief.json"

    @property
    def asset_manifest_json(self) -> Path:
        return self.base / "asset_manifest.json"

    @property
    def shot_plan_json(self) -> Path:
        return self.base / "shot_plan.json"

    @property
    def desktop_review_plan_json(self) -> Path:
        return self.base / "desktop_review_plan.json"

    @property
    def assets_dir(self) -> Path:
        d = self.base / "assets"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def preview_frames_dir(self) -> Path:
        d = self.base / "preview_frames"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def audio_dir(self) -> Path:
        d = self.base / "audio"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def frames_dir(self) -> Path:
        d = self.base / "frames"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def desktop_frames_dir(self) -> Path:
        d = self.base / "desktop_frames"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def mouse_dir(self) -> Path:
        d = self.base / "mouse"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def final_video(self) -> Path:
        return self.base / "final.mp4"


@dataclass
class CreativeBrief:
    """短视频选题判断"""
    target_audience: str
    viewer_pain: str
    one_line_value: str
    proof_points: list[str]
    visual_opportunities: list[str]
    risks: list[str]
    recommendation: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_audience": self.target_audience,
            "viewer_pain": self.viewer_pain,
            "one_line_value": self.one_line_value,
            "proof_points": self.proof_points,
            "visual_opportunities": self.visual_opportunities,
            "risks": self.risks,
            "recommendation": self.recommendation,
            "reason": self.reason,
        }


@dataclass
class VisualAsset:
    """短视频可用画面素材"""
    id: str
    type: str
    source: str
    path: str
    caption: str
    use_case: str
    quality: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "path": self.path,
            "caption": self.caption,
            "use_case": self.use_case,
            "quality": self.quality,
        }


@dataclass
class AssetManifest:
    """素材清单"""
    assets: list[VisualAsset]

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        return {"assets": [asset.to_dict() for asset in self.assets]}


@dataclass
class Shot:
    """竖屏短视频分镜"""
    start: float
    duration: float
    visual_asset: str
    visual_treatment: str
    narration_intent: str
    subtitle: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "duration": self.duration,
            "visual_asset": self.visual_asset,
            "visual_treatment": self.visual_treatment,
            "narration_intent": self.narration_intent,
            "subtitle": self.subtitle,
        }


@dataclass
class ShotPlan:
    """分镜方案"""
    title: str
    shots: list[Shot]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "shots": [shot.to_dict() for shot in self.shots],
        }


def shot_plan_from_dict(data: dict[str, Any]) -> ShotPlan:
    """从 JSON 数据恢复分镜方案"""
    return ShotPlan(
        title=data.get("title", "GitHub 项目推荐"),
        shots=[
            Shot(
                start=float(shot.get("start", 0)),
                duration=float(shot.get("duration", 4)),
                visual_asset=str(shot.get("visual_asset", "")),
                visual_treatment=str(shot.get("visual_treatment", "")),
                narration_intent=str(shot.get("narration_intent", "")),
                subtitle=str(shot.get("subtitle", "")),
            )
            for shot in data.get("shots", [])
        ],
    )


@dataclass
class DesktopReviewShot:
    """Desktop review style shot."""
    start: float
    duration: float
    url: str
    action: str
    selector: str
    cursor_label: str
    narration: str
    zoom: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "duration": self.duration,
            "url": self.url,
            "action": self.action,
            "selector": self.selector,
            "cursor_label": self.cursor_label,
            "narration": self.narration,
            "zoom": self.zoom,
        }


@dataclass
class DesktopReviewPlan:
    """Desktop review style plan."""
    title: str
    hook_title: str
    account_label: str
    shots: list[DesktopReviewShot]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "hook_title": self.hook_title,
            "account_label": self.account_label,
            "shots": [shot.to_dict() for shot in self.shots],
        }


def desktop_review_plan_from_dict(data: dict[str, Any]) -> DesktopReviewPlan:
    """从 JSON 数据恢复 desktop review 分镜方案"""
    return DesktopReviewPlan(
        title=data.get("title", "开源项目速看"),
        hook_title=data.get("hook_title", "信息差 AI 工具"),
        account_label=data.get("account_label", "开源工具筛选"),
        shots=[
            DesktopReviewShot(
                start=float(shot.get("start", 0)),
                duration=float(shot.get("duration", 4)),
                url=str(shot.get("url", "")),
                action=str(shot.get("action", "focus")),
                selector=str(shot.get("selector", "")),
                cursor_label=str(shot.get("cursor_label", "")),
                narration=str(shot.get("narration", "")),
                zoom=float(shot.get("zoom", 1.0)),
            )
            for shot in data.get("shots", [])
        ],
    )
