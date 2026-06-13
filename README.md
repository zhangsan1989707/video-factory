# GitHub Video Maker

AI 驱动的 GitHub 项目介绍视频自动生成工具，主要面向中文短视频平台（抖音/快手）。

## 功能特性

- **多种视频风格**: 横屏浏览器录制、竖屏科技风、桌面审阅风格、热榜排行
- **双渲染引擎**: PIL 逐帧渲染 + HyperFrames HTML 动画渲染
- **多供应商 AI**: 支持 OpenAI、Anthropic、DeepSeek、小米等 AI 供应商
- **Web 控制台**: 可视化操作界面，支持完整的热榜视频生成工作流
- **CLI 命令行**: 灵活的命令行接口，支持批量处理
- **定时调度**: 支持 daily/weekly 自动任务

## 快速开始

### 环境要求

- Python 3.11+
- ffmpeg
- Playwright (chromium)

### 安装

```bash
# 克隆项目
git clone https://github.com/zhangsan1989707/video-factory.git
cd video-factory

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装 Python 与 Node 依赖
pip install -e .
npm install

# 安装 Playwright 浏览器
playwright install chromium
```

### 配置

创建 `.env` 文件:

```bash
GITHUB_TOKEN=ghp_your_github_token
OPENAI_API_KEY=sk_your_api_key  # 可选
```

## 使用方式

### Web 控制台（推荐）

```bash
.venv/bin/python -m src.console --port 8765
```

打开 http://127.0.0.1:8765

#### 控制台流程

1. 在配置里填写 GitHub Token 和模型供应商
2. 选择日榜、周榜或月榜，生成候选草稿
3. 人工选择并排序项目
4. 生成并编辑口播脚本
5. 生成计划文件、校验 dry run，然后渲染最终视频
6. 在产物栏查看预览帧、日志、`final.mp4` 和带编号的正式 mp4

### CLI 命令行

```bash
# 生成单项目竖屏视频
.venv/bin/python -m src.cli https://github.com/owner/repo --vertical -o output/dir/final.mp4

# 生成热榜视频
.venv/bin/python -m src.cli https://github.com/repo1,https://github.com/repo2 --vertical --style hotlist -o output/dir/final.mp4

# 从计划文件继续渲染
.venv/bin/python -m src.cli --from-plan output/dir -o output/dir/final.mp4

# 使用独立的热榜渲染脚本
.venv/bin/python scripts/render_hotlist_v2.py --style tech_hotspot --token “$GITHUB_TOKEN” -o output/hotlist-v2/final.mp4
```

### 视频风格

| 风格 | 分辨率 | 特点 | 适用场景 |
|------|--------|------|----------|
| desktop-review | 1592x1080 | 桌面浏览器风格，带鼠标指针 | B站、YouTube |
| vertical | 1080x1920 | 竖屏科技风 | 抖音、快手 |
| hotlist | 1080x1920 | 热榜排行风格 | 短视频平台 |

## 启动控制台

```bash
.venv/bin/python -m src.console --port 8765
```

打开:

```text
http://127.0.0.1:8765
```

控制台会保存本地配置到 `.config/video-console/`，任务和产物保存到 `output/jobs/`。

## 控制台流程

1. 在配置里填写 GitHub Token 和模型供应商。
2. 选择日榜、周榜或月榜，生成候选草稿。
3. 人工选择并排序项目。
4. 生成并编辑口播脚本。
5. 生成计划文件、校验 dry run，然后渲染最终视频。
6. 在产物栏查看预览帧、日志、`final.mp4` 和带编号的正式 mp4。

## 命令行渲染

```bash
.venv/bin/python -m src.cli https://github.com/owner/repo --style desktop-review --vertical --dry-run -o output/dir/final.mp4
.venv/bin/python -m src.cli --from-plan output/dir -o output/dir/final.mp4 --vertical
.venv/bin/python scripts/render_hotlist_v2.py --style tech_hotspot --token "$GITHUB_TOKEN" -o output/hotlist-v2/final.mp4
```

## 文档

详细文档请参阅 [docs/](docs/) 目录:

- [架构设计文档](docs/architecture.md) - 系统架构、模块关系、数据流
- [API 文档](docs/api.md) - REST API 接口说明
- [开发指南](docs/development.md) - 环境搭建、开发流程、测试指南
- [模块参考文档](docs/modules.md) - 各模块详细接口说明

## 项目结构

```
github-video/
├── src/                        # 源代码
│   ├── cli.py                 # CLI 入口
│   ├── pipeline.py            # 流程协调器
│   ├── models.py              # 数据模型
│   ├── console/               # Web 控制台
│   ├── hotlist_v2/            # 热榜 V2 渲染
│   ├── planner/               # 分镜规划
│   ├── composer/              # 视频合成
│   ├── animation/             # 动画引擎
│   ├── browser/               # 浏览器录制
│   ├── scraper/               # 数据抓取
│   ├── tts/                   # 语音合成
│   ├── script/                # 脚本生成
│   └── utils/                 # 工具函数
├── tests/                     # 测试文件
├── assets/templates/          # HTML 模板
├── output/                    # 输出目录
├── docs/                      # 文档
└── bgm/                       # 背景音乐
```

## 验证

```bash
.venv/bin/python tests/test_bgm.py && \
.venv/bin/python tests/test_console_jobs.py && \
.venv/bin/python tests/test_console_preflight.py && \
.venv/bin/python tests/test_console_providers.py && \
.venv/bin/python tests/test_console_scheduler.py && \
.venv/bin/python tests/test_console_server_smoke.py && \
.venv/bin/python tests/test_github_hotlist.py && \
.venv/bin/python tests/test_pipeline_from_plan.py && \
.venv/bin/python -m compileall src tests generate_hotlist10.py && \
node --check src/console/static/app.js && \
node --check tests/test_console_static_app.js && \
node tests/test_console_static_app.js && \
git diff --check
```

真实端到端验收默认不运行；需要验证 GitHub API、浏览器采集、TTS 和 ffmpeg 合成时，按 [真实端到端验收清单](docs/e2e-manual-checklist.md) 执行，或显式运行：

```bash
GITHUB_VIDEO_RUN_SLOW_E2E=1 .venv/bin/python -m pytest tests/test_real_e2e_smoke.py -q
```
