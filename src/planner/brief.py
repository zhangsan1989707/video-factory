"""Creative brief generation for short-form videos."""

import json
import re

from openai import OpenAI

from src.models import CreativeBrief, ProjectInfo
from src.utils.config import AI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL


HYPE_WORDS = ("神器", "宝藏", "绝了", "卧槽", "真的牛", "兄弟们")


def _project_category(project: ProjectInfo) -> str:
    text = f"{project.description} {' '.join(project.topics)} {project.readme[:800]}".lower()
    if any(word in text for word in ("english", "learn", "word", "typing", "语言", "英语")):
        return "学习者"
    if any(word in text for word in ("stock", "finance", "data", "api", "a股", "行情", "数据")):
        return "需要数据接口的开发者"
    if any(word in text for word in ("cli", "terminal", "shell", "命令行")):
        return "命令行工具用户"
    if any(word in text for word in ("ai", "agent", "llm", "openai", "claude")):
        return "AI 工具开发者"
    return "关注开源工具的开发者"


def _extract_readme_headings(readme: str) -> list[str]:
    headings = []
    for line in readme.splitlines():
        match = re.match(r"^#{1,3}\s+(.+)", line.strip())
        if match:
            headings.append(match.group(1).strip())
    return headings[:5]


def _fallback_brief(project: ProjectInfo) -> CreativeBrief:
    audience = _project_category(project)
    headings = _extract_readme_headings(project.readme)
    proof_points = []

    if project.description:
        proof_points.append(project.description)
    if project.stars:
        proof_points.append(f"GitHub 上已有 {project.stars} stars，说明有一定使用关注度")
    if project.language:
        proof_points.append(f"主要技术栈是 {project.language}")
    proof_points.extend(headings[: max(0, 5 - len(proof_points))])

    visual_opportunities = []
    if re.search(r"!\[[^\]]*\]\([^)]+\)", project.readme):
        visual_opportunities.append("README 中有图片，可作为产品演示画面")
    if project.homepage:
        visual_opportunities.append("仓库提供官网链接，可截图展示真实界面")
    if "```" in project.readme:
        visual_opportunities.append("README 中有代码块，可展示安装或调用方式")
    visual_opportunities.append("GitHub 仓库页可作为来源证明")

    risks = []
    if not project.homepage and not re.search(r"!\[[^\]]*\]\([^)]+\)", project.readme):
        risks.append("可视化素材偏少，容易像纯仓库介绍")
    if len(project.readme) < 500:
        risks.append("README 内容偏少，卖点可能需要人工补充")

    recommendation = "produce" if proof_points and len(visual_opportunities) > 1 else "skip"
    reason = "有可解释卖点和可用素材" if recommendation == "produce" else "素材或卖点不足，直接生成会显得模板化"

    return CreativeBrief(
        target_audience=audience,
        viewer_pain=f"{audience}需要快速判断这个项目是否真的能解决自己的问题",
        one_line_value=project.description or f"{project.full_name} 是一个开源项目",
        proof_points=proof_points[:5],
        visual_opportunities=visual_opportunities,
        risks=risks,
        recommendation=recommendation,
        reason=reason,
    )


def _sanitize_brief(data: dict, fallback: CreativeBrief) -> CreativeBrief:
    proof_points = data.get("proof_points") or fallback.proof_points
    visual_opportunities = data.get("visual_opportunities") or fallback.visual_opportunities
    risks = data.get("risks") or fallback.risks
    recommendation = data.get("recommendation") or fallback.recommendation
    if recommendation not in ("produce", "skip"):
        recommendation = fallback.recommendation

    one_line_value = str(data.get("one_line_value") or fallback.one_line_value)
    for word in HYPE_WORDS:
        one_line_value = one_line_value.replace(word, "")

    return CreativeBrief(
        target_audience=str(data.get("target_audience") or fallback.target_audience),
        viewer_pain=str(data.get("viewer_pain") or fallback.viewer_pain),
        one_line_value=one_line_value.strip() or fallback.one_line_value,
        proof_points=[str(item) for item in proof_points[:5]],
        visual_opportunities=[str(item) for item in visual_opportunities[:5]],
        risks=[str(item) for item in risks[:5]],
        recommendation=recommendation,
        reason=str(data.get("reason") or fallback.reason),
    )


def generate_creative_brief(project: ProjectInfo) -> CreativeBrief:
    """Generate a grounded short-video creative brief."""
    fallback = _fallback_brief(project)
    if not OPENAI_API_KEY:
        return fallback

    client_kwargs = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        client_kwargs["base_url"] = OPENAI_BASE_URL

    client = OpenAI(**client_kwargs)
    prompt = f"""
你是短视频选题编辑。请判断这个 GitHub 项目是否适合做中文抖音短视频。
不要使用夸张词，不要默认推荐。所有卖点必须来自输入信息。

项目: {project.full_name}
描述: {project.description}
Stars: {project.stars}
语言: {project.language}
Topics: {", ".join(project.topics)}
Homepage: {project.homepage}
README 摘要:
{project.readme[:2500]}

只输出 JSON:
{{
  "target_audience": "...",
  "viewer_pain": "...",
  "one_line_value": "...",
  "proof_points": ["..."],
  "visual_opportunities": ["..."],
  "risks": ["..."],
  "recommendation": "produce 或 skip",
  "reason": "..."
}}
"""

    try:
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": "你只输出 JSON，不写解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=1800,
        )
        content = response.choices[0].message.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        return _sanitize_brief(json.loads(content), fallback)
    except Exception:
        return fallback
