"""配置管理"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent.parent

# 输出目录（转为绝对路径）
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output")).resolve()

# GitHub Token
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# OpenAI API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")

# AI 模型配置
AI_MODEL = os.getenv("AI_MODEL", "mimo-v2.5-pro")

# 字体配置：跨平台字体查找
_FONT_CANDIDATES = {
    "darwin": [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ],
    "linux": [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ],
    "win32": [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
    ],
}


def find_cjk_font() -> str | None:
    """跨平台查找 CJK 字体路径"""
    candidates = _FONT_CANDIDATES.get(sys.platform, [])
    for path in candidates:
        if Path(path).exists():
            return path
    # 回退：尝试所有平台
    for platform_candidates in _FONT_CANDIDATES.values():
        for path in platform_candidates:
            if Path(path).exists():
                return path
    return None


CJK_FONT_PATH = find_cjk_font()

# TTS 配置
# 默认声音：zh-CN-XiaoxiaoNeural（女声，温柔清晰，适合短视频口播）
# 其他备选：zh-CN-YunxiNeural（男青年）、zh-CN-YunjianNeural（男运动）、zh-CN-YunyangNeural（男资讯）、
#          zh-CN-YunxiaNeural（男成熟）、zh-CN-XiaoyiNeural（女活泼）
TTS_VOICE = "zh-CN-XiaoxiaoNeural"
# 女声默认语速 +20%（男声可调至 +30%）
TTS_RATE = "+20%"

# 视频配置
VIDEO_FPS = 30
VIDEO_WIDTH_H = 1920
VIDEO_HEIGHT_H = 1080
VIDEO_WIDTH_V = 1080
VIDEO_HEIGHT_V = 1920

# 默认时长范围
MIN_DURATION = 30
MAX_DURATION = 60

# BGM 配置
BGM_DIR = ROOT_DIR / "bgm"
BGM_VOLUME = 0.065
BGM_FADE_IN = 1.0
BGM_FADE_OUT = 1.0
