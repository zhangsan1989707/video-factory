# GitHub Video Maker - 设计文档

## 项目概述

AI 驱动的 GitHub 项目介绍视频生成工具。输入 GitHub 项目地址，自动生成 30-60 秒的宣传视频，包含旁白讲解、鼠标动画、放大效果等。

**目标用户**: 视频博主，批量制作 GitHub 项目介绍视频涨粉

**核心价值**:
- 全自动化：输入 URL，输出完整视频
- 专业效果：鼠标动效、放大聚焦、动态布局
- 高质量语音：微软 TTS 神经网络语音

---

## 需求规格

| 维度 | 选择 | 说明 |
|------|------|------|
| 视频时长 | 30-60 秒 | 短视频，适合抖音/快手 |
| 画面风格 | 动态切换 | 根据内容自动切换布局 |
| 旁白配音 | edge-tts | 微软 TTS，免费高质量 |
| 鼠标动画 | 全套动效 | 移动、点击、高亮、拖拽、滚动、打字、放大 |
| 内容生成 | 全自动 | AI 分析 README，生成完整脚本 |
| 批量处理 | 单个处理 | 先做单个，后续可扩展 |
| 视频格式 | 横屏 + 竖屏 | 1080p 横屏 + 1080p 竖屏 |
| 运行方式 | 本地 CLI | 命令行工具 |

---

## 技术方案

### 技术栈

- **语言**: Python 3.11+
- **浏览器自动化**: Playwright
- **视频处理**: MoviePy + FFmpeg
- **TTS**: edge-tts (微软 TTS 免费接口)
- **AI 脚本生成**: OpenAI API / Claude API
- **CLI 框架**: Typer + Rich

### 核心依赖

```toml
dependencies = [
    "typer>=0.9.0",
    "rich>=13.0.0",
    "playwright>=1.40.0",
    "openai>=1.0.0",
    "anthropic>=0.18.0",
    "edge-tts>=7.0.0",
    "moviepy>=1.0.3",
    "Pillow>=10.0.0",
    "numpy>=1.24.0",
    "httpx>=0.25.0",
    "PyGithub>=2.1.0",
    "pydantic>=2.0.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0.0",
]
```

---

## 系统架构

### 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      CLI 入口 (cli.py)                       │
│                         │                                    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Pipeline 协调器 (pipeline.py)            │   │
│  └──────────────────────────────────────────────────────┘   │
│                         │                                    │
│    ┌────────────────────┼────────────────────┐               │
│    ▼                    ▼                    ▼               │
│ ┌─────────┐      ┌─────────────┐      ┌─────────────┐       │
│ │ 1.抓取  │      │ 2.脚本生成  │      │ 3.录制浏览器 │       │
│ │ scraper │      │ script_gen  │      │  recorder   │       │
│ └─────────┘      └─────────────┘      └─────────────┘       │
│    │                    │                    │               │
│    │                    ▼                    ▼               │
│    │             ┌─────────────┐      ┌─────────────┐       │
│    │             │ 4.TTS 生成  │      │ 5.鼠标动效  │       │
│    │             │    tts      │      │  animator   │       │
│    │             └─────────────┘      └─────────────┘       │
│    │                    │                    │               │
│    └────────────────────┴────────────────────┘               │
│                         │                                    │
│                         ▼                                    │
│              ┌─────────────────────┐                         │
│              │ 6.视频合成 (FFmpeg) │                         │
│              │    composer         │                         │
│              └─────────────────────┘                         │
│                         │                                    │
│                         ▼                                    │
│                    output.mp4                                │
└─────────────────────────────────────────────────────────────┘
```

### 数据流

1. `scraper` 抓取 GitHub 项目信息（README、截图、结构）
2. `script_gen` 调用 AI 生成讲解脚本（文字 + 时间轴）
3. `tts` 将脚本转为语音（edge-tts）
4. `recorder` 用 Playwright 录制浏览器操作
5. `animator` 在录制时添加鼠标动效
6. `composer` 将浏览器录屏 + 语音 + 鼠标动效合成最终视频

---

## 项目结构

```
github-video-maker/
├── src/
│   ├── __init__.py
│   ├── cli.py                # CLI 入口
│   ├── pipeline.py           # 流程协调器
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── github_api.py     # GitHub API 抓取
│   │   └── playwright.py     # 浏览器抓取（备选）
│   ├── script/
│   │   ├── __init__.py
│   │   ├── generator.py      # 脚本生成
│   │   └── prompts.py        # AI 提示词模板
│   ├── browser/
│   │   ├── __init__.py
│   │   ├── recorder.py       # 浏览器录制
│   │   └── actions.py        # 浏览器动作定义
│   ├── animation/
│   │   ├── __init__.py
│   │   ├── mouse.py          # 鼠标动效
│   │   ├── highlight.py      # 高亮效果
│   │   └── zoom.py           # 放大效果
│   ├── tts/
│   │   ├── __init__.py
│   │   └── azure.py          # edge-tts 集成
│   ├── composer/
│   │   ├── __init__.py
│   │   ├── video.py          # 视频合成
│   │   ├── audio.py          # 音频混合
│   │   └── subtitle.py       # 字幕叠加
│   └── utils/
│       ├── __init__.py
│       ├── config.py         # 配置管理
│       └── helpers.py        # 工具函数
├── assets/
│   ├── cursors/              # 鼠标指针素材
│   ├── sounds/               # 音效
│   └── music/                # 背景音乐
├── templates/                # 视频模板
├── tests/
├── pyproject.toml
├── README.md
└── .env.example
```

---

## 核心模块设计

### 模块 1：GitHub 抓取器 (scraper.py)

**职责**: 输入 GitHub URL，输出结构化项目信息

```python
@dataclass
class ProjectInfo:
    name: str              # 项目名称
    description: str       # 一句话描述
    readme: str            # README 完整内容
    stars: int             # star 数
    language: str          # 主要语言
    topics: list[str]      # 标签
    screenshots: list[str] # 截图 URL（如有）
    repo_url: str          # 仓库地址
```

**实现方式**:
- 优先用 GitHub API（需 token，限流友好）
- 备选：Playwright 直接抓取页面

---

### 模块 2：脚本生成器 (script_generator.py)

**职责**: 根据 ProjectInfo 生成视频脚本

```python
@dataclass
class ScriptSegment:
    timestamp: float       # 开始时间（秒）
    duration: float        # 持续时间（秒）
    narration: str         # 旁白文字
    action: str            # 浏览器动作（scroll/click/zoom/highlight）
    target: str            # 动作目标（CSS 选择器或坐标）
    highlight_text: str    # 需要高亮的文字（可选）

@dataclass
class VideoScript:
    title: str             # 视频标题
    segments: list[ScriptSegment]
    total_duration: float  # 总时长
```

**AI 提示词策略**:
- 分析 README，提取核心亮点
- 生成口语化旁白（每句 ≤15 字）
- 配合浏览器动作指令

---

### 模块 3：浏览器录制器 (browser_recorder.py)

**职责**: 根据脚本录制浏览器操作画面

**录制策略**: 截图序列 + 后期合成（非直接录屏）

理由：
- 截图可精确控制每帧
- 方便后期叠加鼠标动效
- 可任意调整播放速度
- 不受网络加载影响

---

### 模块 4：鼠标动效引擎 (mouse_animator.py)

**职责**: 在截图上绘制鼠标动画

**支持的动效**:
| 动效 | 描述 |
|------|------|
| move | 平滑移动到目标位置（贝塞尔曲线） |
| click | 移动 + 点击光圈 |
| highlight | 目标区域高亮光晕 |
| drag | 拖拽轨迹 |
| scroll | 滚动指示器 |
| typing | 打字光标动画 |
| zoom | 放大镜聚焦效果 |

**分层渲染**:
```
┌─────────────────────────────┐
│      浏览器截图 (底层)       │
├─────────────────────────────┤
│      高亮光晕 (中层)         │
├─────────────────────────────┤
│      鼠标指针 (顶层)         │
└─────────────────────────────┘
```

---

### 模块 5：TTS 集成 (tts.py)

**职责**: 将旁白文字转为语音

**方案**: edge-tts（微软 TTS 免费接口）

可用中文语音:
- `zh-CN-XiaoxiaoNeural` - 女声，温暖（推荐）
- `zh-CN-YunxiNeural` - 男声，阳光
- `zh-CN-YunyangNeural` - 男声，专业

---

### 模块 6：视频合成器 (video_composer.py)

**职责**: 将所有素材合成为最终视频

**合成流程**:
1. 浏览器截图序列 → 视频轨
2. 鼠标动效叠加 → 动效轨
3. 旁白音频 → 音频轨
4. 背景音乐（可选）→ 混音
5. 文字叠加（标题、字幕）→ 字幕轨
6. FFmpeg 输出最终 mp4

---

## 动态布局系统

### 布局类型

| 布局 | 适用场景 | 画面构成 |
|------|----------|----------|
| **full-browser** | 展示整体页面、操作流程 | 全屏浏览器窗口 |
| **split-left** | 展示功能点、要点提示 | 左 70% 浏览器 + 右 30% 文字 |
| **split-right** | 强调文字信息、对比 | 左 30% 文字 + 右 70% 浏览器 |
| **focus-zoom** | 放大细节、代码片段 | 全屏 + 右下角放大镜 |
| **title-card** | 开头/结尾 | 全屏大标题 + 背景 |

### 切换逻辑

- 开头和结尾 → title-card
- 放大效果 → focus-zoom
- 有文字要点 → split-left
- 默认 → full-browser

---

## CLI 命令设计

### 基本用法

```bash
# 最简单的用法
github-video https://github.com/owner/repo

# 指定输出路径
github-video https://github.com/owner/repo -o my-video.mp4

# 指定视频方向
github-video https://github.com/owner/repo --orientation vertical

# 指定语音
github-video https://github.com/owner/repo --voice zh-CN-YunxiNeural
```

### 命令选项

```
github-video <url> [options]

Arguments:
  url                  GitHub 仓库地址

Options:
  -o, --output         输出文件路径（默认: output/<repo-name>.mp4）
  --orientation        视频方向: horizontal/vertical（默认: horizontal）
  --voice              微软 TTS 语音名称（默认: zh-CN-XiaoxiaoNeural）
  --min-duration       最短时长秒数（默认: 30）
  --max-duration       最长时长秒数（默认: 60）
  --fps                录制帧率（默认: 30）
  --no-music           不添加背景音乐
  --template           视频模板: quick-review/deep-dive/tutorial（默认: quick-review）
  -v, --verbose        详细输出
  -h, --help           显示帮助
```

### 交互流程示例

```bash
$ github-video https://github.com/MadsLorentzen/ai-job-search

🔍 正在抓取项目信息...
   ✓ MadsLorentzen/ai-job-search - AI 驱动求职申请框架
   ⭐ 1.2k stars | TypeScript

📝 正在生成脚本...
   ✓ 生成 5 个片段，总时长 45 秒

🎙️ 正在生成语音...
   ✓ 使用语音: zh-CN-XiaoxiaoNeural

🖥️ 正在录制浏览器...
   ✓ 截取 1350 帧 (45 秒 × 30fps)

🖱️ 正在生成鼠标动效...
   ✓ 12 个动作已完成

🎬 正在合成视频...
   ✓ 输出: output/ai-job-search/final.mp4

✅ 完成！视频时长: 45 秒
```

---

## 脚本生成示例

**项目**: `MadsLorentzen/ai-job-search`
**主题**: AI 驱动的求职申请框架
**时长**: 45 秒

```json
[
  {
    "timestamp": 0,
    "duration": 6,
    "narration": "找工作还在海投简历？",
    "action": "navigate",
    "target": "https://github.com/MadsLorentzen/ai-job-search",
    "focus_area": null
  },
  {
    "timestamp": 6,
    "duration": 8,
    "narration": "这个项目让 AI 帮你精准求职",
    "action": "highlight",
    "target": "article.markdown-body h1",
    "focus_area": "项目标题"
  },
  {
    "timestamp": 14,
    "duration": 10,
    "narration": "自动搜索职位、评估匹配度",
    "action": "scroll",
    "target": "h2:has-text('What it does')",
    "focus_area": "功能介绍区域"
  },
  {
    "timestamp": 24,
    "duration": 12,
    "narration": "还能定制简历、写求职信、准备面试",
    "action": "scroll",
    "target": "h2:has-text('Commands')",
    "focus_area": "命令列表 /scrape /apply"
  },
  {
    "timestamp": 36,
    "duration": 9,
    "narration": "1200 多人已经用上了",
    "action": "highlight",
    "target": "#repo-stars-counter-star",
    "focus_area": "Star 数量"
  }
]
```

---

## 错误处理

### 常见错误场景

| 场景 | 处理方式 |
|------|----------|
| GitHub 限流 | 使用 token 或等待重试 |
| 页面加载超时 | 增加等待时间，最多重试 3 次 |
| README 过短/为空 | 使用项目描述 + 标签生成脚本 |
| 无截图可用 | 纯浏览器操作录制 |
| TTS 生成失败 | 降级到系统自带 TTS |
| FFmpeg 编码失败 | 降低分辨率/码率重试 |

### 降级策略

- TTS: edge-tts → 系统 TTS → 纯字幕
- 浏览器: Chromium → Firefox
- 抓取: GitHub API → Playwright 抓取

---

## 输出文件结构

```
output/
└── ai-job-search/
    ├── info.json          # 项目信息缓存
    ├── script.json        # 生成的脚本
    ├── audio/
    │   ├── segment-001.mp3
    │   ├── segment-002.mp3
    │   └── ...
    ├── frames/
    │   ├── frame-0001.png
    │   ├── frame-0002.png
    │   └── ...
    ├── mouse/
    │   ├── mouse-0001.png
    │   ├── mouse-0002.png
    │   └── ...
    └── final.mp4          # 最终视频
```

---

## 环境变量配置

```bash
# .env.example

# GitHub API（可选，有 token 限流更友好）
GITHUB_TOKEN=ghp_xxxxxxxxxxxx

# OpenAI API（脚本生成）
OPENAI_API_KEY=sk-xxxxxxxxxxxx

# 输出目录
OUTPUT_DIR=./output
```

---

## 后续扩展方向

- [ ] 批量处理模式
- [ ] Web UI 界面
- [ ] 更多视频模板
- [ ] 自定义背景音乐
- [ ] 多语言支持
- [ ] 云端部署
