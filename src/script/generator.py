"""AI 脚本生成器"""

import json
from openai import OpenAI

from src.models import ProjectInfo, VideoScript, ScriptSegment
from src.script.prompts import SCRIPT_GENERATION_PROMPT
from src.utils.config import AI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL


def generate_script(
    project: ProjectInfo,
    min_duration: int = 30,
    max_duration: int = 60,
) -> VideoScript:
    """使用 AI 生成视频脚本"""
    if not OPENAI_API_KEY:
        # 无 API key 时使用默认脚本
        return generate_default_script(project, min_duration)

    client_kwargs = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        client_kwargs["base_url"] = OPENAI_BASE_URL

    client = OpenAI(**client_kwargs)

    # 准备 README 摘要
    readme_summary = project.readme[:2000] if project.readme else project.description

    # 计算中间时间点
    target_duration = (min_duration + max_duration) / 2
    middle_end = target_duration - 8

    prompt = SCRIPT_GENERATION_PROMPT.format(
        name=project.name,
        full_name=project.full_name,
        description=project.description,
        stars=project.stars,
        language=project.language,
        topics=", ".join(project.topics) if project.topics else "无",
        readme_summary=readme_summary,
        duration=int(target_duration),
        middle_end=int(middle_end),
    )

    response = client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": "你是一个专业的视频脚本写手，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.8,
        max_tokens=3000,
    )

    content = response.choices[0].message.content.strip()

    # 解析 JSON
    try:
        # 尝试提取 JSON（可能被 markdown 包裹）
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        segments_data = json.loads(content)
    except json.JSONDecodeError:
        # JSON 解析失败，使用默认脚本
        return generate_default_script(project, min_duration)

    # 构建脚本对象（修正 navigate 目标为 GitHub 页面）
    repo_base = f"https://github.com/{project.owner}/{project.name}"
    segments = []
    for s in segments_data:
        action = s["action"]
        target = s["target"]

        # 强制修正 navigate 目标：必须指向正确的 GitHub 仓库页面
        if action == "navigate":
            if target.startswith("https://github.com"):
                # 验证 owner/repo 是否正确，不正确则替换
                parts = target.replace("https://github.com/", "").split("/")
                if len(parts) < 2 or parts[0] != project.owner or parts[1] != project.name:
                    target = repo_base
            else:
                # 非 GitHub 链接，直接替换为仓库页面
                target = repo_base

        segments.append(ScriptSegment(
            timestamp=s["timestamp"],
            duration=s["duration"],
            narration=s["narration"],
            action=action,
            target=target,
            focus_area=s.get("focus_area", ""),
        ))

    total_duration = sum(s.duration for s in segments)

    return VideoScript(
        title=f"介绍 {project.full_name}",
        segments=segments,
        total_duration=total_duration,
    )


def generate_default_script(project: ProjectInfo, duration: int = 45) -> VideoScript:
    """生成默认脚本（无 AI 时使用）"""
    segments = [
        ScriptSegment(
            timestamp=0,
            duration=4,
            narration="兄弟们，发现一个宝藏项目！",
            action="navigate",
            target=project.repo_url,
        ),
        ScriptSegment(
            timestamp=4,
            duration=5,
            narration="这也太好用了吧！",
            action="highlight",
            target="article h1",
            focus_area="项目标题",
        ),
        ScriptSegment(
            timestamp=9,
            duration=7,
            narration="你看这个功能，真的绝了",
            action="scroll",
            target=".markdown-body",
            focus_area="功能介绍",
        ),
        ScriptSegment(
            timestamp=16,
            duration=7,
            narration="居然还能这样用！",
            action="scroll",
            target=".markdown-body",
            focus_area="核心功能",
        ),
        ScriptSegment(
            timestamp=23,
            duration=7,
            narration="我已经 Star 了，你呢？",
            action="scroll",
            target=".markdown-body",
            focus_area="更多功能",
        ),
        ScriptSegment(
            timestamp=30,
            duration=7,
            narration=f"已经有 {project.stars} 人收藏了",
            action="highlight",
            target="[id*='star'], .stargazers-count",
            focus_area="Star 数量",
        ),
        ScriptSegment(
            timestamp=37,
            duration=8,
            narration="强烈建议去 Star 一下！",
            action="click",
            target="button:has-text('Star'), [aria-label='Star']",
            focus_area="Star 按钮",
        ),
    ]

    return VideoScript(
        title=f"介绍 {project.full_name}",
        segments=segments,
        total_duration=sum(s.duration for s in segments),
    )
