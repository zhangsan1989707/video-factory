# GitHub Video Maker 开发指南

## 概述

本文档为开发者提供项目搭建、开发、测试和贡献的完整指南。

## 环境要求

### 系统要求
- **操作系统**: macOS 10.15+ (主要支持), Linux (部分支持)
- **Python**: 3.11+
- **Node.js**: 18+ (可选，用于 HyperFrames 渲染)
- **磁盘空间**: 至少 2GB（用于浏览器和依赖）

### 依赖工具
- **ffmpeg**: 视频/音频处理
- **ffprobe**: 媒体信息获取
- **Playwright**: 浏览器自动化

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/zhangsan1989707/video-factory.git
cd video-factory
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# 或
.venv\Scripts\activate     # Windows
```

### 3. 安装依赖

```bash
# Python 依赖
pip install -r requirements.txt

# Playwright 浏览器
playwright install chromium

# Node.js 依赖 (可选)
npm install
```

### 4. 配置环境变量

创建 `.env` 文件：

```bash
# GitHub Token (必需)
GITHUB_TOKEN=ghp_your_github_token

# AI API (可选，用于 AI 功能)
OPENAI_API_KEY=sk_your_openai_key
OPENAI_BASE_URL=https://api.openai.com/v1
```

### 5. 运行测试

```bash
# 运行所有测试
.venv/bin/python -m pytest tests/

# 运行特定测试
.venv/bin/python tests/test_console_jobs.py

# 运行冒烟测试
.venv/bin/python tests/smoke_console_render_job.py

# 查看真实端到端手动验收清单
open docs/e2e-manual-checklist.md

# 显式运行慢速真实 e2e；默认测试不会执行这条链路
GITHUB_VIDEO_RUN_SLOW_E2E=1 .venv/bin/python -m pytest tests/test_real_e2e_smoke.py -q
```

### 6. 启动服务

```bash
# 启动 Web 控制台
.venv/bin/python -m src.console --port 8765

# 访问控制台
open http://127.0.0.1:8765
```

## 项目结构

```
github-video/
├── src/                        # 源代码
│   ├── cli.py                 # CLI 入口
│   ├── pipeline.py            # 流程协调器
│   ├── models.py              # 数据模型
│   ├── console/               # Web 控制台
│   │   ├── server.py          # HTTP 服务器
│   │   ├── jobs.py            # 任务编排
│   │   ├── store.py           # 文件存储
│   │   ├── model_router.py    # AI 模型路由
│   │   └── static/            # 前端文件
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
├── assets/                    # 资源文件
│   └── templates/             # HTML 模板
├── output/                    # 输出目录
├── .config/                   # 配置文件
├── docs/                      # 文档
├── scripts/                   # 脚本工具
├── bgm/                       # 背景音乐
├── CLAUDE.md                  # Claude 配置
├── package.json               # Node.js 配置
└── README.md                  # 项目说明
```

## 开发流程

### 1. 创建功能分支

```bash
git checkout -b feature/your-feature-name
```

### 2. 编写代码

遵循项目编码规范：
- 2 空格缩进
- const 优先于 var
- 异步函数优先于回调
- 函数短小，专注单一职责

### 3. 编写测试

```bash
# 创建测试文件
touch tests/test_your_feature.py

# 编写测试
def test_your_feature():
    # Arrange
    # Act
    # Assert
    pass
```

### 4. 运行测试

```bash
# 运行单个测试
.venv/bin/python tests/test_your_feature.py

# 运行所有测试
.venv/bin/python -m pytest tests/

# 运行带覆盖率的测试
.venv/bin/python -m pytest tests/ --cov=src --cov-report=html
```

### 5. 代码审查

```bash
# 运行代码检查
.venv/bin/python -m flake8 src/
.venv/bin/python -m mypy src/

# 运行安全检查
.venv/bin/python -m bandit -r src/
```

### 6. 提交代码

```bash
git add .
git commit -m "feat: add your feature description"
git push origin feature/your-feature-name
```

### 7. 创建 Pull Request

在 GitHub 上创建 PR，填写：
- 功能描述
- 测试计划
- 相关 Issue

## 测试指南

### 测试类型

#### 1. 单元测试
测试单个函数或类的功能。

```python
# tests/test_models.py
def test_project_info_creation():
    info = ProjectInfo(
        name="test-repo",
        owner="test-owner",
        description="Test repository",
        readme="# Test",
        stars=100,
        language="Python"
    )
    assert info.full_name == "test-owner/test-repo"
```

#### 2. 集成测试
测试多个模块协作的功能。

```python
# tests/test_pipeline.py
async def test_pipeline_from_plan():
    # 准备测试数据
    # 执行 pipeline
    # 验证输出
    pass
```

#### 3. 冒烟测试
测试关键功能是否正常工作。

```python
# tests/smoke_console_render_job.py
def test_render_job_smoke():
    # 创建任务
    # 生成候选
    # 选择项目
    # 渲染视频
    # 验证输出文件
    pass
```

#### 4. 真实端到端验收

真实端到端验收会访问 GitHub、采集浏览器截图、生成 TTS、合成 MP4，并用 `ffprobe` 检查音视频流。它不属于默认测试，避免日常开发被网络、限流和语音服务影响。

```bash
# 默认应跳过
.venv/bin/python -m pytest tests/test_real_e2e_smoke.py -q

# 显式开启真实慢速链路
GITHUB_VIDEO_RUN_SLOW_E2E=1 .venv/bin/python -m pytest tests/test_real_e2e_smoke.py -q
```

手动验收步骤见 `docs/e2e-manual-checklist.md`。

### 测试命名规范

```python
# 测试文件: test_<module>.py
# 测试函数: test_<function_name>_<scenario>
# 测试类: Test<ClassName>

def test_generate_candidates_with_valid_token():
    pass

def test_generate_candidates_with_invalid_token():
    pass

class TestModelRouter:
    def test_chat_json_success(self):
        pass

    def test_chat_json_failure(self):
        pass
```

### Mock 和 Fixture

```python
import pytest
from unittest.mock import patch, MagicMock

@pytest.fixture
def mock_github_api():
    with patch('src.scraper.github_api.fetch_repo_info') as mock:
        mock.return_value = ProjectInfo(
            name="test-repo",
            owner="test-owner",
            description="Test",
            readme="# Test",
            stars=100,
            language="Python"
        )
        yield mock

def test_with_mock_github_api(mock_github_api):
    # 使用 mock
    pass
```

## 模块开发指南

### 1. 添加新视频风格

#### 步骤 1: 创建分镜生成器

```python
# src/planner/new_style.py
def generate_new_style_plan(project_info: ProjectInfo) -> ShotPlan:
    """生成新风格的分镜方案"""
    shots = [
        Shot(
            start=0,
            duration=4,
            visual_asset="opening",
            visual_treatment="new_style_opening",
            narration_intent="开场介绍",
            subtitle="新风格视频"
        ),
        # ... 更多镜头
    ]
    return ShotPlan(title="新风格视频", shots=shots)
```

#### 步骤 2: 创建视频合成器

```python
# src/composer/new_style.py
def compose_new_style_video(
    shot_plan: ShotPlan,
    assets: list,
    audio_files: list,
    output_path: Path
) -> Path:
    """合成新风格视频"""
    # 实现视频合成逻辑
    return output_path
```

#### 步骤 3: 在 Pipeline 中注册

```python
# src/pipeline.py
async def run_pipeline(...):
    if style == "new-style":
        shot_plan = generate_new_style_plan(project_info)
        output = compose_new_style_video(shot_plan, ...)
```

### 2. 添加新渲染引擎

#### 步骤 1: 实现渲染函数

```python
# src/hotlist_v2/new_engine.py
def render_with_new_engine(
    html_content: str,
    output_path: Path,
    duration: float
) -> Path:
    """使用新引擎渲染视频"""
    # 实现渲染逻辑
    return output_path
```

#### 步骤 2: 在模板配置中注册

```json
// .config/video-console/templates.json
{
  "templates": {
    "github_hotlist_vertical_v1": {
      "style": "tech_hotspot",
      "render_engine": "new_engine"
    }
  }
}
```

### 3. 添加新 AI 供应商

#### 步骤 1: 实现 API 调用

```python
# src/console/model_router.py
async def _call_new_provider(
    config: dict,
    messages: list,
    response_format: str = "text"
) -> str:
    """调用新供应商 API"""
    # 实现 API 调用逻辑
    pass
```

#### 步骤 2: 在配置中添加

```json
// .config/video-console/providers.json
{
  "providers": {
    "new_provider": {
      "enabled": true,
      "api_key": "your-api-key",
      "base_url": "https://api.new-provider.com/v1"
    }
  }
}
```

## 调试技巧

### 1. 启用详细日志

```bash
# 设置环境变量
export LOG_LEVEL=DEBUG

# 或在代码中
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 2. 使用断点调试

```python
# 在代码中添加断点
import pdb; pdb.set_trace()

# 或使用 IPython
from IPython import embed; embed()
```

### 3. 查看中间产物

```bash
# 查看生成的分镜
cat output/jobs/GH-HOTLIST-20260610-001/shot_plan.json | jq

# 查看素材清单
cat output/jobs/GH-HOTLIST-20260610-001/asset_manifest.json | jq

# 查看预览帧
open output/jobs/GH-HOTLIST-20260610-001/preview_frames/
```

### 4. 测试单个模块

```python
# 单独测试 TTS 模块
from src.tts.edge_tts import generate_audio_segment
import asyncio

asyncio.run(generate_audio_segment(
    text="测试语音",
    output_path=Path("test.mp3"),
    voice="zh-CN-YunxiNeural"
))
```

## 常见问题

### 1. Playwright 安装失败

```bash
# 安装系统依赖 (macOS)
brew install libsrtp libvpx libopus

# 重新安装 Playwright
playwright install chromium
```

### 2. ffmpeg 找不到

```bash
# macOS
brew install ffmpeg

# 验证安装
ffmpeg -version
```

### 3. 字体问题

项目使用 macOS 系统字体，如果在其他系统运行，需要修改字体路径：

```python
# src/utils/config.py
FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"  # macOS
# FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"  # Linux
```

### 4. 内存不足

处理大视频时可能内存不足，可以：

```bash
# 增加 Python 内存限制
ulimit -s 65536

# 或使用分段处理
```

## 性能优化

### 1. 并行处理

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

async def parallel_capture(assets):
    with ThreadPoolExecutor(max_workers=4) as executor:
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(executor, capture_asset, asset)
            for asset in assets
        ]
        return await asyncio.gather(*tasks)
```

### 2. 缓存机制

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def expensive_operation(param):
    # 耗时操作
    pass
```

### 3. 增量处理

```python
def process_incremental(old_data, new_data):
    # 只处理变化的部分
    pass
```

## 部署指南

### 本地部署

```bash
# 启动服务
.venv/bin/python -m src.console --port 8765

# 后台运行
nohup .venv/bin/python -m src.console --port 8765 > console.log 2>&1 &
```

### Docker 部署 (未来)

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "-m", "src.console", "--port", "8765"]
```

## 贡献指南

### 1. 代码风格

- 遵循 PEP 8
- 使用类型注解
- 编写文档字符串
- 保持函数短小

### 2. 提交规范

```
<type>(<scope>): <subject>

<body>

<footer>
```

类型：
- `feat`: 新功能
- `fix`: 修复 Bug
- `docs`: 文档更新
- `style`: 代码格式
- `refactor`: 重构
- `test`: 测试
- `chore`: 构建/工具

### 3. Pull Request 流程

1. Fork 项目
2. 创建功能分支
3. 编写代码和测试
4. 确保所有测试通过
5. 提交 PR
6. 等待代码审查
7. 合并到主分支

### 4. Issue 报告

使用 Issue 模板报告 Bug 或提出功能建议。

## 资源链接

- [项目仓库](https://github.com/zhangsan1989707/video-factory)
- [Playwright 文档](https://playwright.dev/python/)
- [MoviePy 文档](https://zulko.github.io/moviepy/)
- [Edge TTS 文档](https://github.com/rany2/edge-tts)
- [HyperFrames 文档](https://github.com/hyperframes/hyperframes)

## 联系方式

- 项目维护者: zhangsan1989707
- 邮箱: [待补充]
- 微信群: [待补充]

## 许可证

本项目采用 ISC 许可证，详见 LICENSE 文件。
