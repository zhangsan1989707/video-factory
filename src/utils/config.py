"""配置管理"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent.parent

# 输出目录
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))

# GitHub Token
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# OpenAI API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")

# TTS 配置
TTS_VOICE = "zh-CN-YunxiNeural"
TTS_RATE = "+40%"

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
BGM_VOLUME = 0.15
BGM_FADE_IN = 1.0
BGM_FADE_OUT = 1.0
