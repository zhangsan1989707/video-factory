"""Desktop review style planning."""

from src.models import DesktopReviewPlan, DesktopReviewShot, ProjectInfo, ScriptSegment, VideoScript


def _localized_value_line(project: ProjectInfo) -> str:
    description = project.description or ""

    # 如果有中文描述，直接使用
    if any("\u4e00" <= char <= "\u9fff" for char in description):
        for part in description.replace("；", ";").split(";"):
            if any("\u4e00" <= char <= "\u9fff" for char in part):
                cleaned = part.strip()
                if len(cleaned) > 5:
                    return cleaned[:42]
        return description[:42]

    # 英文描述，生成通用介绍
    if description:
        return f"先看看这个项目是干什么的。"

    return "先看看这个项目是干什么的。"


def _readme_url(project: ProjectInfo) -> str:
    if "README.zh-CN.md" in project.readme:
        return f"{project.repo_url}/blob/{project.default_branch}/docs/README.zh-CN.md"
    return f"{project.repo_url}#readme"


def generate_desktop_review_plan(project: ProjectInfo) -> DesktopReviewPlan:
    """Create a reference-video-like desktop review plan."""
    repo_url = project.repo_url
    readme_url = _readme_url(project)
    title = f"{project.name}: 开源项目速看"

    # 根据项目特点生成更自然的文案
    description = project.description or ""
    stars = project.stars

    # 开头文案：直接说项目名称
    hook_narration = f"今天看一个项目，{project.name}。"

    # 中间文案：客观介绍
    value_narration = _localized_value_line(project)

    # 结尾文案：简单判断，不强行引导
    if stars > 5000:
        ending_narration = f"Star 数不少，{stars} 多，可以看看。"
    elif stars > 1000:
        ending_narration = f"Star 数 {stars}，还在增长中。"
    else:
        ending_narration = f"Star 数还不多，{stars}，但可以先了解。"

    shots = [
        DesktopReviewShot(
            start=0,
            duration=4.0,
            url=repo_url,
            action="focus",
            selector="#readme, article.markdown-body, .repository-content",
            cursor_label="先看结论",
            narration=hook_narration,
            zoom=1.0,
        ),
        DesktopReviewShot(
            start=4.0,
            duration=4.4,
            url=repo_url,
            action="focus",
            selector=".BorderGrid-cell, [data-testid='repository-about']",
            cursor_label="项目价值",
            narration=value_narration,
            zoom=1.35,
        ),
        DesktopReviewShot(
            start=8.4,
            duration=5.0,
            url=readme_url,
            action="scroll",
            selector="article.markdown-body img, .markdown-body img",
            cursor_label="真实界面",
            narration="先看 README 里的界面图，了解它实际长什么样。",
            zoom=1.2,
        ),
        DesktopReviewShot(
            start=13.4,
            duration=5.0,
            url=readme_url,
            action="scroll",
            selector="article.markdown-body h2, .markdown-body h2, article.markdown-body h3",
            cursor_label="功能入口",
            narration="看看功能目录，了解它能做什么。",
            zoom=1.25,
        ),
        DesktopReviewShot(
            start=18.4,
            duration=5.2,
            url=readme_url,
            action="scroll",
            selector="article.markdown-body pre, .markdown-body pre, article.markdown-body code",
            cursor_label="怎么使用",
            narration="有安装和使用方式，可以自己试试。",
            zoom=1.25,
        ),
        DesktopReviewShot(
            start=23.6,
            duration=5.0,
            url=repo_url,
            action="focus",
            selector="#repo-stars-counter-star, [aria-label*='star'], .stargazers-count",
            cursor_label="值得收藏",
            narration=ending_narration,
            zoom=1.35,
        ),
    ]

    return DesktopReviewPlan(
        title=title,
        hook_title="信息差 AI 工具",
        account_label="开源工具筛选",
        shots=shots,
    )


def generate_script_from_desktop_review_plan(plan: DesktopReviewPlan) -> VideoScript:
    """Convert desktop review shots to TTS-compatible script."""
    segments = [
        ScriptSegment(
            timestamp=shot.start,
            duration=shot.duration,
            narration=shot.narration,
            action="desktop_review",
            target=shot.selector,
            focus_area=shot.cursor_label,
        )
        for shot in plan.shots
    ]
    return VideoScript(
        title=plan.title,
        segments=segments,
        total_duration=sum(segment.duration for segment in segments),
    )
