"""炒股科普常量定义"""

# 主题类型
TOPIC_TYPES = {
    "indicator": "技术指标",
    "trading_basic": "交易基础",
    "risk_discipline": "风险纪律",
}

# 受众
AUDIENCES = {
    "beginner": "股市新手",
    "junior_retail": "初级散户",
}

# 视觉风格
VISUAL_STYLES = {
    "black_gold": "黑金交易室",
    "white_card": "白底科普卡片",
}

# 固定 7 段结构
SCRIPT_STRUCTURE = [
    {"scene_type": "hook", "start": 0, "duration": 3, "label": "Hook"},
    {"scene_type": "misunderstanding", "start": 3, "duration": 5, "label": "Misunderstanding"},
    {"scene_type": "concept", "start": 8, "duration": 10, "label": "Concept"},
    {"scene_type": "how_it_works", "start": 18, "duration": 14, "label": "How It Works"},
    {"scene_type": "how_to_use", "start": 32, "duration": 13, "label": "How To Use"},
    {"scene_type": "pitfall", "start": 45, "duration": 10, "label": "Pitfall"},
    {"scene_type": "summary", "start": 55, "duration": 5, "label": "Summary"},
]

# 模板 ID
TEMPLATE_IDS = [
    "hook_title",
    "myth_vs_truth",
    "concept_card",
    "indicator_chart",
    "three_points",
    "risk_warning",
    "summary_quote",
]

# 场景类型到模板映射
SCENE_TEMPLATE_MAP = {
    "hook": "hook_title",
    "misunderstanding": "myth_vs_truth",
    "concept": "concept_card",
    "how_it_works": "indicator_chart",
    "how_to_use": "three_points",
    "pitfall": "risk_warning",
    "summary": "summary_quote",
}

# 禁止话术 - 高风险（直接阻断）
BANNED_HIGH_RISK = [
    "可以买",
    "可以买入",
    "建议买入",
    "建议卖出",
    "明天上涨",
    "明天大涨",
    "必涨",
    "稳赚",
    "稳赚不赔",
    "翻倍",
    "牛股",
    "黑马股",
    "赶紧上车",
    "闭眼买",
    "梭哈",
    "抄底",
    "逃顶",
    "这只股票可以买",
    "明天大概率上涨",
    "现在就是买点",
    "主力要拉升",
    "闭眼买入",
    "无脑买入",
]

# 禁止话术 - 中风险（提醒改写）
BANNED_MEDIUM_RISK = [
    "收益",
    "胜率",
    "涨停",
    "跌停",
    "加仓",
    "减仓",
    "满仓",
    "清仓",
]

# 缺少风险提示的检测
DISCLAIMER_KEYWORDS = [
    "风险",
    "不构成投资建议",
    "仅供学习",
    "知识科普",
    "历史案例不代表",
    "谨慎",
]

# 默认风险提示
DEFAULT_RISK_DISCLAIMER = "以上内容仅作知识科普，不构成投资建议。投资有风险，入市需谨慎。"

# 黑金交易室主题
BLACK_GOLD_THEME = {
    "background": "#070A0F",
    "panel": "#101722",
    "primary": "#F2C94C",
    "text": "#F8FAFC",
    "muted": "#94A3B8",
    "red": "#EF4444",
    "green": "#22C55E",
    "grid": "rgba(148, 163, 184, 0.18)",
}

# 白底科普卡片主题
WHITE_CARD_THEME = {
    "background": "#F7F3EA",
    "panel": "#FFFFFF",
    "primary": "#1F2937",
    "accent": "#D9A441",
    "text": "#111827",
    "muted": "#6B7280",
    "warning": "#B45309",
}

# 安全区
SAFE_AREA = {
    "top": 120,
    "bottom": 160,
    "left": 72,
    "right": 72,
}

# 视频尺寸
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30
