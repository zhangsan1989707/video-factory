"""批量生成 edge-tts 中文声音试听样本。"""

import asyncio
from pathlib import Path

import edge_tts

OUTPUT_DIR = Path("output/voice_samples")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_CONCURRENT = 2  # 限流，避免 edge-tts 拒绝
MAX_RETRIES = 3

# 7 个常见中文声音
VOICES = [
    "zh-CN-YunxiNeural",   # 男 · 青年活力（当前默认）
    "zh-CN-YunjianNeural",  # 男 · 运动
    "zh-CN-YunyangNeural",  # 男 · 资讯专业
    "zh-CN-YunyeNeural",    # 男 · 成熟温暖
    "zh-CN-XiaoxiaoNeural", # 女 · 温柔
    "zh-CN-XiaoyiNeural",   # 女 · 活泼
    "zh-CN-YunxiNeural",    # 重复用 Xiaoxiao 对比
]

# 4 段 GitHub 热榜口播文本（覆盖不同语速和情感）
SAMPLES = [
    "voice1_hook",  # 钩子开场
    "voice2_ranking",  # 榜单介绍
    "voice3_proof",  # 价值证明
    "voice4_cta",  # 互动引导
]

TEXTS = {
    "voice1_hook": (
        "兄弟们，GitHub 上又杀出一匹黑马！"
        "这个项目刚开源不到一周，Star 数就突破了 1.2 万，"
        "直接冲上了 Trending 榜首。"
    ),
    "voice2_ranking": (
        "本期热榜我挑了十个值得关注的开源项目。"
        "排在第一的是一个能让 AI 自己写 AI 训练的框架，"
        "第二名是终端里的可视化数据库工具，"
        "第三名则解决了困扰前端工程师多年的打包速度问题。"
    ),
    "voice3_proof": (
        "它的核心价值只有一句话：把原本需要三小时的环境配置，"
        "压缩到一杯咖啡的时间。"
        "我在自己的 M2 Mac 上跑过，"
        "从克隆仓库到跑通示例，只用了四分十二秒。"
    ),
    "voice4_cta": (
        "如果你也在关注 AI 编程、运维自动化或者独立开发，"
        "评论区告诉我你最想看哪个方向。"
        "下期我会按点赞最高的选题继续拆解 GitHub 上的好项目。"
    ),
}


async def synth(voice: str, name: str, text: str) -> None:
    safe_voice = voice.replace("-", "_")
    out = OUTPUT_DIR / f"{safe_voice}_{name}.mp3"
    if out.exists() and out.stat().st_size > 1000:
        print(f"  · 复用 {out.name}")
        return
    # 男声 30% 提速，女声 20% 提速，符合短视频节奏
    rate = "+30%" if "Yun" in voice and "Xiaoxiao" not in voice else "+20%"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            comm = edge_tts.Communicate(text, voice, rate=rate)
            await comm.save(str(out))
            size_kb = out.stat().st_size // 1024
            print(f"  ✓ {out.name}  ({size_kb} KB)")
            return
        except Exception as exc:
            print(f"  ⚠ {voice}/{name} 第 {attempt}/{MAX_RETRIES} 次失败: {type(exc).__name__}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 * attempt)
    print(f"  ✗ {voice}/{name} 全部重试失败")


async def main() -> None:
    # 女生单独加进来
    actual_voices = [
        "zh-CN-YunxiNeural",
        "zh-CN-YunjianNeural",
        "zh-CN-YunyangNeural",
        "zh-CN-YunxiaNeural",   # 成熟男声（Yunye 微软端已下架）
        "zh-CN-XiaoxiaoNeural",
        "zh-CN-XiaoyiNeural",
    ]
    print(f"生成 {len(actual_voices)} 个声音 × {len(SAMPLES)} 段文本 = {len(actual_voices) * len(SAMPLES)} 个文件")
    print(f"输出目录: {OUTPUT_DIR.absolute()}")
    print(f"并发限制: {MAX_CONCURRENT}\n")

    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _limited(voice: str, name: str, text: str) -> None:
        async with sem:
            await synth(voice, name, text)

    tasks = []
    for voice in actual_voices:
        for sample in SAMPLES:
            tasks.append(_limited(voice, sample, TEXTS[sample]))
    await asyncio.gather(*tasks)

    print(f"\n✅ 全部生成完成，文件位于: {OUTPUT_DIR.absolute()}")


if __name__ == "__main__":
    asyncio.run(main())
