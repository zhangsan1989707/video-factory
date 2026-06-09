"""生成 10 项目热榜视频的计划文件"""

import asyncio
import json
import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent))

from src.scraper.github_api import fetch_repo_info
from src.models import AssetManifest, VisualAsset, Shot, ShotPlan

# ── 10 个项目的 GitHub URL（按配音稿顺序，第 10 名到第 1 名）──
PROJECT_URLS = [
    "https://github.com/decolua/9router",                    # #10
    "https://github.com/bytedance/UI-TARS-desktop",           # #9
    "https://github.com/AIDC-AI/Pixelle-Video",               # #8
    "https://github.com/harry0703/MoneyPrinterTurbo",         # #7
    "https://github.com/HKUDS/ViMax",                         # #6
    "https://github.com/Lum1104/Understand-Anything",         # #5
    "https://github.com/rohitg00/agentmemory",                # #4
    "https://github.com/mattpocock/skills",                    # #3
    "https://github.com/multica-ai/andrej-karpathy-skills",   # #2
    "https://github.com/colbymchenry/codegraph",               # #1
]

# ── 每个项目的钩子标题（显示在 rank card 最醒目位置）──
PROJECT_LABELS = [
    "40个AI模型 一个入口搞定",          # #10 9Router
    "AI终于能帮你点鼠标了",              # #9  UI-TARS
    "输入一句话 视频自动生成",           # #8  Pixelle
    "短视频批量生产 一键搞定",           # #7  MoneyPrinter
    "导演编剧剪辑 全部交给AI",          # #6  ViMax
    "看不懂的代码 AI帮你画成图",        # #5  Understand
    "AI终于记住你了",                    # #4  AgentMemory
    "装完这个 AI编程直接起飞",          # #3  MattPocock
    "Karpathy的编程秘籍 全公开了",     # #2  Karpathy
    "让AI秒懂你的代码库",                # #1  CodeGraph
]

# ── 每个项目的三要点（解决了什么 | 技术亮点 | 适合谁）──
PROJECT_DETAILS = [
    ("40+模型统一接入不用逐个对接", "三档自动降级 省20-40%Token", "做AI平台的开发者"),    # #10
    ("电脑操作不用自己点鼠标", "视觉大模型驱动 跨平台", "做自动化的团队"),                  # #9
    ("不用剪辑就能出视频", "自动脚本+配图+字幕合成", "短视频矩阵号"),                      # #8
    ("一句话批量出视频", "LLM驱动素材自动匹配", "知识号/科普号"),                          # #7
    ("导演编剧剪辑全交给AI", "多Agent协作 角色场景一致", "视频创作者"),                    # #6
    ("看不懂的代码秒变图谱", "多Agent管线 语义搜索", "学开源项目的人"),                    # #5
    ("AI终于有长期记忆了", "置信度评分+知识图谱", "做Agent的开发者"),                      # #4
    ("装完AI编程能力翻倍", "TDD/诊断/原型现成技能", "Claude Code用户"),                   # #3
    ("编程大牛的AI编程秘籍", "单文件即插即用", "Claude Code用户"),                         # #2
    ("让AI秒懂你的代码库", "本地索引 省Token省调用", "大型项目维护者"),                    # #1
]

# ── 自定义配音稿（每段对应一个 shot，精简版 ~60-90s）──
NARRATIONS = [
    # 开场
    "过去 7 天，GitHub 又爆了。我整理了本周最火的 10 个开源项目，建议收藏。",

    # 第 10 名到第 1 名
    "第 10 名，9Router。免费的 AI 中转网关，支持 Claude、Gemini、GPT 统一接入。",

    "第 9 名，UI-TARS Desktop。字节跳动开源的桌面 AI Agent，让 AI 直接帮你操作电脑。",

    "第 8 名，Pixelle Video。全自动 AI 视频框架，输入主题就能自动生成视频。",

    "第 7 名，MoneyPrinterTurbo。AI 视频圈老网红，一句话批量生产短视频。",

    "第 6 名，ViMax。它不只生成视频，而是把导演、编剧、剪辑全部交给 AI。",

    "第 5 名，Understand Anything。把复杂代码转成知识图谱，看不懂的项目丢进去就行。",

    "第 4 名，Agent Memory。解决 AI 健忘问题，让 Agent 拥有长期记忆。",

    "第 3 名，Matt Pocock Skills。Claude Code 最热门的 Skills 仓库，安装即增强编程能力。",

    "第 2 名，Andrej Karpathy Skills。Karpathy 风格的 Skills 集合，很多人当 Claude Code 外挂包用。",

    "第 1 名，CodeGraph。本周热榜冠军。构建代码知识图谱，让 AI 更快理解大型代码库。",

    # 结尾
    "AI 正在从聊天工具变成真正能干活的 Agent。关注我，每天带你看最新 AI 热榜。",
]

OUTPUT_DIR = Path(__file__).parent / "output" / "github-hotlist10"


def star_label(stars: int) -> str:
    if stars >= 1000:
        return f"{stars / 1000:.1f}K Star"
    return f"{stars:,} Star" if stars else "GitHub 项目"


def safe_part(text: str) -> str:
    return text.replace(":", " ").replace("|", " ").replace(";", " ").strip()


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("🔍 正在抓取 10 个项目信息...")
    projects = []
    for i, url in enumerate(PROJECT_URLS):
        parts = url.rstrip("/").replace("https://github.com/", "").split("/")
        owner, repo = parts[0], parts[1]
        try:
            info = await fetch_repo_info(owner, repo)
            projects.append(info)
            print(f"   ✓ #{10 - i} {info.full_name} | {info.stars} stars")
        except Exception as e:
            print(f"   ✗ #{10 - i} {owner}/{repo}: {e}")
            return

    # projects 保持 PROJECT_URLS 顺序 = 配音稿顺序（#10 到 #1）
    # 排名按配音稿顺序：projects[0]=#10, projects[1]=#9, ..., projects[9]=#1
    # 排行榜总览也按此顺序（编辑选择的排名）
    sorted_by_stars = sorted(projects, key=lambda p: p.stars, reverse=True)
    rows = [f"#{10 - i} {projects[i].name} {star_label(projects[i].stars)}" for i in range(len(projects))]
    row_payload = ";".join(rows)

    shots = []
    start = 0.0

    # 开场 shot
    shots.append(Shot(
        start=start,
        duration=5.0,
        visual_asset="",
        visual_treatment="hotlist_opening",
        narration_intent="多项目热榜开场",
        subtitle=NARRATIONS[0],
    ))
    start += 5.0

    # 排行榜总览 shot
    shots.append(Shot(
        start=start,
        duration=5.0,
        visual_asset="",
        visual_treatment=f"hotlist_ranking:{row_payload}",
        narration_intent="真实榜单总览",
        subtitle="先看榜单，这 10 个项目你认识几个？",
    ))
    start += 5.0

    # 每个项目一个 shot，按 PROJECT_URLS 顺序（第10名到第1名）
    for i, project in enumerate(projects):
        rank = 10 - i  # projects[0]=#10, projects[9]=#1
        narration_idx = i + 1  # NARRATIONS[1]=第10名, NARRATIONS[10]=第1名
        narration = NARRATIONS[narration_idx] if narration_idx < len(NARRATIONS) - 1 else ""
        label = PROJECT_LABELS[i] if i < len(PROJECT_LABELS) else ""
        details = PROJECT_DETAILS[i] if i < len(PROJECT_DETAILS) else ("", "", "")
        detail_str = f"{details[0]}|{details[1]}|{details[2]}"

        shots.append(Shot(
            start=start,
            duration=5.0,
            visual_asset=f"p{i + 1}-asset-001",
            visual_treatment=f"hotlist_rank_card:{rank}:{safe_part(project.name)}:{star_label(project.stars)}:{label}:{detail_str}",
            narration_intent=f"热榜项目 {rank}",
            subtitle=narration,
        ))
        start += 5.0

    # 结尾 shot
    shots.append(Shot(
        start=start,
        duration=5.0,
        visual_asset="",
        visual_treatment=f"hotlist_closing:{row_payload}",
        narration_intent="多项目趋势总结",
        subtitle=NARRATIONS[-1],
    ))

    shot_plan = ShotPlan(title="GitHub 本周最火的 10 个项目", shots=shots)

    # ── 生成 asset_manifest.json ──
    assets = []
    for i, project in enumerate(projects):
        assets.append(VisualAsset(
            id=f"p{i + 1}-asset-001",
            type="github_repo",
            source=project.repo_url,
            path="",
            caption=f"{project.full_name} - {project.description[:60]}",
            use_case="热榜项目展示",
            quality="medium",
        ))
    manifest = AssetManifest(assets=assets)

    # ── 生成 info.json ──
    info_data = {
        "projects": [
            {
                "name": p.name,
                "owner": p.owner,
                "description": p.description,
                "stars": p.stars,
                "language": p.language,
                "topics": p.topics,
                "repo_url": p.repo_url,
                "homepage": p.homepage,
                "default_branch": p.default_branch,
            }
            for p in sorted_by_stars
        ]
    }

    # ── 写入文件 ──
    with open(OUTPUT_DIR / "shot_plan.json", "w", encoding="utf-8") as f:
        json.dump(shot_plan.to_dict(), f, ensure_ascii=False, indent=2)

    with open(OUTPUT_DIR / "asset_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest.to_dict(), f, ensure_ascii=False, indent=2)

    with open(OUTPUT_DIR / "info.json", "w", encoding="utf-8") as f:
        json.dump(info_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 计划文件已生成到: {OUTPUT_DIR}")
    print(f"   - shot_plan.json ({len(shots)} 个分镜)")
    print(f"   - asset_manifest.json ({len(assets)} 个素材)")
    print(f"   - info.json ({len(sorted_by_stars)} 个项目)")
    print(f"\n下一步运行:")
    print(f"   .venv/bin/python -m src.cli --from-plan {OUTPUT_DIR} -o {OUTPUT_DIR}/final.mp4 --vertical --max-duration 90")


if __name__ == "__main__":
    asyncio.run(main())
