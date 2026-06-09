"""Shot plan generation."""

from src.models import AssetManifest, CreativeBrief, ProjectInfo, Shot, ShotPlan


def _asset_id(manifest: AssetManifest, preferred: tuple[str, ...]) -> str:
    for type_ in preferred:
        for asset in manifest.assets:
            if asset.type == type_:
                return asset.id
    return manifest.assets[0].id if manifest.assets else ""


def _short_text(text: str, limit: int) -> str:
    text = " ".join(text.replace("\n", " ").split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def _star_label(stars: int) -> str:
    if stars >= 1000:
        return f"{stars / 1000:.1f}K Star"
    return f"{stars:,} Star" if stars else "GitHub 项目"


def _safe_part(text: str) -> str:
    return text.replace(":", " ").replace("|", " ").replace(";", " ").strip()


def _treatment(kind: str, *parts: str) -> str:
    return ":".join([kind, *[_safe_part(part) for part in parts]])


def _short_audience(text: str) -> str:
    lower = text.lower()
    if "英语" in text or "english" in lower:
        return "英语学习者"
    if "ai" in lower or "agent" in lower or "llm" in lower:
        return "AI 工具开发者"
    if "数据" in text or "data" in lower:
        return "数据开发者"
    if "命令行" in text or "cli" in lower:
        return "命令行用户"
    for sep in ("，", ",", "、", "如", "；", ";"):
        if sep in text:
            text = text.split(sep, 1)[0]
    return _short_text(text, 16)


def _short_points(points: list[str], stars: int) -> list[str]:
    cleaned = []
    for point in points:
        point = point.replace("GitHub Stars", "Star").replace("GitHub", "")
        if "star" in point.lower() or "受欢迎" in point:
            cleaned.append(_star_label(stars))
        elif "记忆曲线" in point or "智能" in point:
            cleaned.append("记忆曲线复习")
        elif "模式" in point or "跟读" in point or "听写" in point:
            cleaned.append("多种练习模式")
        elif "中文" in point:
            cleaned.append("中文用户友好")
        elif "在线" in point or "访问" in point:
            cleaned.append("在线可访问")
        else:
            cleaned.append(_short_text(point.strip(" ，。"), 12))
    return cleaned[:3]


def _short_value(text: str) -> str:
    lower = text.lower()
    if "英语" in text or "english" in lower:
        if "打字" in text or "typing" in lower:
            return "打字练英语，自动安排复习"
        return "更高效地练英语"
    if "ai" in lower or "agent" in lower:
        return "把 AI 工作流做成可复用能力"
    if "数据" in text or "data" in lower:
        return "把数据获取流程封装好"
    return _short_text(text, 24)


def _project_use(project: ProjectInfo, brief: CreativeBrief | None = None) -> str:
    text = f"{project.name} {project.description} {' '.join(project.topics)}".lower()
    if "typewords" in text or "english" in text or "英语" in project.description:
        return "用打字练英语，顺手把复习节奏安排好"
    if "mcp" in text and "github" in text:
        return "把 GitHub 接进 MCP，让 Agent 能直接处理仓库信息"
    if "stock" in text or "a股" in project.description or "finance" in text:
        return "把 A 股数据接口封装好，少踩数据源的坑"
    if "ai" in text or "agent" in text or "llm" in text:
        return "把 AI 工作流封成工具，减少重复配置"
    if brief and brief.one_line_value:
        return _short_value(brief.one_line_value)
    return "把一个具体问题做成可直接使用的开源工具"


def _project_benefit(project: ProjectInfo, brief: CreativeBrief | None = None) -> str:
    text = f"{project.name} {project.description} {' '.join(project.topics)}".lower()
    if "typewords" in text or "english" in text:
        return "适合想稳定练英语的人，也适合研究轻量工具站"
    if "mcp" in text and "github" in text:
        return "适合做开发助手、代码审查和仓库自动化"
    if "stock" in text or "a股" in project.description or "finance" in text:
        return "适合做行情分析、量化研究和数据看板"
    if "ai" in text or "agent" in text or "llm" in text:
        return "适合想把 AI 能力接进真实工作流的人"
    if brief:
        return f"适合{_short_audience(brief.target_audience)}先收藏试用"
    return "适合有同类需求的人先收藏试用"


def _topic_tags(project: ProjectInfo, brief: CreativeBrief | None = None) -> list[str]:
    tags = [tag for tag in project.topics if tag][:3]
    if project.language:
        tags.append(project.language)
    if not tags and brief:
        tags = [brief.target_audience, "GitHub"]
    return tags[:4] or ["GitHub"]


def _project_label(project: ProjectInfo) -> str:
    return project.name.replace("-", " ")


def generate_single_review_shot_plan(
    project: ProjectInfo,
    brief: CreativeBrief,
    manifest: AssetManifest,
) -> ShotPlan:
    """Create a single-project teardown vertical short-video plan."""
    proof_points = brief.proof_points or [brief.one_line_value]
    short_points = _short_points(proof_points, project.stars)
    product_asset = _asset_id(manifest, ("webpage", "image"))
    evidence_asset = _asset_id(manifest, ("image", "readme_code", "webpage"))
    repo_asset = _asset_id(manifest, ("github_repo",))
    main_asset = product_asset or evidence_asset or repo_asset
    repo_label = _project_label(project)
    stars = _star_label(project.stars)
    language = project.language or "开源项目"
    audience = _short_audience(brief.target_audience)

    shots = [
        Shot(
            start=0,
            duration=3.0,
            visual_asset=main_asset,
            visual_treatment=_treatment("single_hook", repo_label, stars),
            narration_intent="用数据钩子抓住观众",
            subtitle=f"一个开源项目，在 GitHub 拿了 {stars}。",
        ),
        Shot(
            start=3.0,
            duration=3.8,
            visual_asset=repo_asset or main_asset,
            visual_treatment=_treatment("single_judgment", repo_label),
            narration_intent="给出单项目判断",
            subtitle=f"它叫 {repo_label}，核心用途是：{_project_use(project, brief)}。",
        ),
        Shot(
            start=6.8,
            duration=4.6,
            visual_asset=main_asset,
            visual_treatment=_treatment("single_project_card", repo_label, language),
            narration_intent="项目卡片定位",
            subtitle=f"我会看三点：它能做什么，能带来什么，为什么推荐。",
        ),
        Shot(
            start=11.4,
            duration=5.2,
            visual_asset=evidence_asset or main_asset,
            visual_treatment="feature_breakdown",
            narration_intent="拆出三个可验证卖点",
            subtitle=f"我会先看三件事：{'；'.join(short_points)}。",
        ),
        Shot(
            start=16.6,
            duration=4.8,
            visual_asset=evidence_asset or main_asset,
            visual_treatment="evidence_screenshot",
            narration_intent="展示真实页面或 README 证据",
            subtitle=f"它的核心价值是：{_short_value(brief.one_line_value)}。",
        ),
        Shot(
            start=21.4,
            duration=4.8,
            visual_asset=repo_asset or main_asset,
            visual_treatment="source_proof",
            narration_intent="回到 GitHub 来源和适合人群",
            subtitle=f"如果你是{audience}，这个项目可以先收藏再试。",
        ),
        Shot(
            start=26.2,
            duration=4.8,
            visual_asset=repo_asset or main_asset,
            visual_treatment="single_closing",
            narration_intent="具体互动入口",
            subtitle="评论区打：AI、运维、独立开发。我下期按方向继续看 GitHub 项目。",
        ),
    ]

    return ShotPlan(title=f"GitHub 项目观察：{project.name}", shots=shots)


def generate_hotlist_shot_plan(
    projects: list[ProjectInfo],
    manifests: list[AssetManifest],
    custom_narrations: list[str] | None = None,
) -> ShotPlan:
    """Create a real multi-project GitHub hotlist vertical plan.

    Args:
        custom_narrations: Optional list of narration texts. If provided,
            length should be len(ranked) + 2 (intro + per-project + outro).
    """
    ranked = sorted(projects, key=lambda project: project.stars, reverse=True)[:10]
    manifest_by_name = {
        project.name: manifest
        for project, manifest in zip(projects, manifests)
    }
    rows = [f"#{i + 1} {project.name} {_star_label(project.stars)}" for i, project in enumerate(ranked)]
    row_payload = ";".join(rows)

    if custom_narrations and len(custom_narrations) >= 2:
        intro_text = custom_narrations[0]
        outro_text = custom_narrations[-1]
        project_narrations = custom_narrations[1:-1]
    else:
        intro_text = f"这期 GitHub 热榜，我挑了 {len(ranked)} 个真实项目。"
        outro_text = "这期都是真实开源项目。你想先看哪个项目的完整用法？"
        project_narrations = []

    shots = [
        Shot(
            start=0,
            duration=5.0,
            visual_asset="",
            visual_treatment="hotlist_opening",
            narration_intent="多项目热榜开场",
            subtitle=intro_text,
        ),
        Shot(
            start=5.0,
            duration=5.0,
            visual_asset="",
            visual_treatment=f"hotlist_ranking:{row_payload}",
            narration_intent="真实榜单总览",
            subtitle=f"先看榜单：{ranked[0].name} 暂时排第一，后面几个也值得看。",
        ),
    ]

    start = 10.0
    for index, project in enumerate(ranked, start=1):
        manifest = manifest_by_name.get(project.name, AssetManifest([]))
        asset = _asset_id(manifest, ("webpage", "image", "github_repo"))
        if index - 1 < len(project_narrations):
            narration = project_narrations[index - 1]
        else:
            use_line = _project_use(project)
            narration = f"第 {index} 个，{project.name}，{_star_label(project.stars)}。{use_line}。"
        shots.append(Shot(
            start=start,
            duration=5.0,
            visual_asset=asset,
            visual_treatment=_treatment("hotlist_rank_card", str(index), project.name, _star_label(project.stars)),
            narration_intent=f"热榜项目 {index}",
            subtitle=narration,
        ))
        start += 5.0

    shots.append(Shot(
        start=start,
        duration=5.0,
        visual_asset="",
        visual_treatment=f"hotlist_closing:{row_payload}",
        narration_intent="多项目趋势总结",
        subtitle=outro_text,
    ))

    return ShotPlan(title="GitHub 本期热榜", shots=shots)


def generate_shot_plan(
    project: ProjectInfo,
    brief: CreativeBrief,
    manifest: AssetManifest,
) -> ShotPlan:
    """Backward-compatible vertical plan."""
    return generate_single_review_shot_plan(project, brief, manifest)
