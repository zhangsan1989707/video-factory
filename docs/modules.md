# GitHub Video Maker 模块参考文档

## 概述

本文档详细描述项目中每个模块的功能、接口和使用方法。

## 核心模块

### 1. src/models.py - 数据模型

定义了所有核心数据结构，是整个系统的基础。

#### ProjectInfo

GitHub 项目信息数据模型。

```python
@dataclass
class ProjectInfo:
    name: str                    # 仓库名称
    owner: str                   # 所有者
    description: str             # 项目描述
    readme: str                  # README 内容
    stars: int                   # Star 数量
    language: str                # 主要语言
    topics: list[str]            # 主题标签
    screenshots: list[str]       # 截图列表
    repo_url: str                # 仓库 URL
    homepage: str                # 主页 URL
    default_branch: str          # 默认分支

    @property
    def full_name(self) -> str:
        """返回 owner/name 格式"""
        return f"{self.owner}/{self.name}"
```

**使用示例**:
```python
info = ProjectInfo(
    name="awesome-project",
    owner="developer",
    description="An awesome project",
    readme="# Awesome Project\n\nThis is awesome.",
    stars=1234,
    language="Python",
    topics=["ai", "machine-learning"]
)
print(info.full_name)  # "developer/awesome-project"
```

#### ShotPlan

分镜方案数据模型。

```python
@dataclass
class ShotPlan:
    title: str                   # 视频标题
    shots: list[Shot]            # 镜头列表

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        pass
```

#### Shot

单个镜头数据模型。

```python
@dataclass
class Shot:
    start: float                 # 开始时间（秒）
    duration: float              # 持续时间（秒）
    visual_asset: str            # 视觉素材标识
    visual_treatment: str        # 视觉处理方式
    narration_intent: str        # 口播意图
    subtitle: str                # 字幕文本
```

**视觉处理方式 (visual_treatment) 可选值**:
- `hotlist_opening` - 热榜开场
- `hotlist_ranking` - 排行榜总览
- `hotlist_rank_card` - 单项目排名卡
- `hotlist_closing` - 结尾互动
- `single_hook` - 单项目钩子
- `single_judgment` - 单项目判断
- `single_project_card` - 单项目卡片
- `single_closing` - 单项目结尾

#### DesktopReviewPlan

桌面审阅风格分镜方案。

```python
@dataclass
class DesktopReviewPlan:
    title: str                   # 视频标题
    hook_title: str              # 钩子标题
    account_label: str           # 账号标签
    shots: list[DesktopReviewShot]  # 镜头列表
```

#### DesktopReviewShot

桌面审阅风格镜头。

```python
@dataclass
class DesktopReviewShot:
    start: float                 # 开始时间
    duration: float              # 持续时间
    url: str                     # 目标 URL
    action: str                  # 动作类型
    selector: str                # CSS 选择器
    cursor_label: str            # 鼠标标签
    narration: str               # 口播文本
    zoom: float                  # 缩放比例
```

**动作类型 (action) 可选值**:
- `navigate` - 导航到页面
- `scroll` - 滚动页面
- `click` - 点击元素
- `focus` - 聚焦元素
- `highlight` - 高亮元素

#### VideoScript

视频脚本数据模型。

```python
@dataclass
class VideoScript:
    title: str                   # 脚本标题
    segments: list[ScriptSegment]  # 片段列表
    total_duration: float        # 总时长
```

#### ScriptSegment

脚本片段数据模型。

```python
@dataclass
class ScriptSegment:
    timestamp: float             # 时间戳
    duration: float              # 持续时间
    narration: str               # 口播文本
    action: str                  # 动作类型
    target: str                  # 目标元素
    focus_area: str              # 焦点区域
```

#### ProjectPaths

项目输出路径管理。

```python
@dataclass
class ProjectPaths:
    base: Path                   # 基础路径

    @property
    def info_json(self) -> Path:
        """项目信息文件路径"""
        return self.base / "info.json"

    @property
    def script_json(self) -> Path:
        """脚本文件路径"""
        return self.base / "script.json"

    @property
    def shot_plan_json(self) -> Path:
        """分镜方案文件路径"""
        return self.base / "shot_plan.json"

    @property
    def desktop_review_plan_json(self) -> Path:
        """桌面审阅分镜文件路径"""
        return self.base / "desktop_review_plan.json"

    @property
    def audio_dir(self) -> Path:
        """音频目录路径"""
        d = self.base / "audio"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def frames_dir(self) -> Path:
        """帧目录路径"""
        d = self.base / "frames"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def final_video(self) -> Path:
        """最终视频文件路径"""
        return self.base / "final.mp4"
```

#### CreativeBrief

短视频选题判断数据模型。

```python
@dataclass
class CreativeBrief:
    target_audience: str         # 目标受众
    viewer_pain: str             # 观众痛点
    one_line_value: str          # 一句话价值
    proof_points: list[str]      # 证据点
    visual_opportunities: list[str]  # 视觉机会
    risks: list[str]             # 风险点
    recommendation: str          # 推荐/跳过
    reason: str                  # 原因
```

#### AssetManifest

素材清单数据模型。

```python
@dataclass
class AssetManifest:
    assets: list[VisualAsset]    # 素材列表
```

#### VisualAsset

视觉素材数据模型。

```python
@dataclass
class VisualAsset:
    id: str                      # 素材 ID
    type: str                    # 素材类型
    source: str                  # 来源
    path: str                    # 文件路径
    caption: str                 # 说明文字
    use_case: str                # 使用场景
    quality: str                 # 质量等级
```

**素材类型 (type) 可选值**:
- `screenshot` - 截图
- `image` - 图片
- `icon` - 图标
- `logo` - Logo

**使用场景 (use_case) 可选值**:
- `opening` - 开场
- `rank_card` - 排名卡
- `project_card` - 项目卡
- `closing` - 结尾
- `background` - 背景

### 2. src/pipeline.py - 流程协调器

核心流程协调器，负责编排整个视频生成流程。

#### run_pipeline()

主流程函数。

```python
async def run_pipeline(
    url: str = "",
    output: str | None = None,
    orientation: str = "horizontal",
    voice: str = TTS_VOICE,
    min_duration: int = MIN_DURATION,
    max_duration: int = MAX_DURATION,
    fps: int = VIDEO_FPS,
    dry_run: bool = False,
    from_plan: str | None = None,
    style: str = "default",
    no_bgm: bool = False,
    bgm_volume: float = BGM_VOLUME,
    bgm_path: str | None = None,
) -> None:
    """
    运行视频生成流程

    Args:
        url: GitHub 仓库 URL（多个用逗号分隔）
        output: 输出文件路径
        orientation: 视频方向 (horizontal/vertical)
        voice: TTS 语音名称
        min_duration: 最短时长（秒）
        max_duration: 最长时长（秒）
        fps: 帧率
        dry_run: 只生成计划，不渲染视频
        from_plan: 从已有计划文件继续
        style: 视频风格 (default/single-review/hotlist/desktop-review)
        no_bgm: 不添加背景音乐
        bgm_volume: 背景音乐音量 (0.0-1.0)
        bgm_path: 自定义 BGM 路径
    """
```

**使用示例**:
```python
import asyncio
from src.pipeline import run_pipeline

# 单项目竖屏视频
asyncio.run(run_pipeline(
    url="https://github.com/owner/repo",
    orientation="vertical",
    output="output/repo/final.mp4"
))

# 热榜视频
asyncio.run(run_pipeline(
    url="https://github.com/repo1,https://github.com/repo2,https://github.com/repo3",
    orientation="vertical",
    style="hotlist",
    output="output/hotlist/final.mp4"
))

# 从计划文件继续
asyncio.run(run_pipeline(
    from_plan="output/repo",
    output="output/repo/final.mp4"
))
```

### 3. src/cli.py - CLI 入口

命令行接口，封装了 pipeline 的调用。

```bash
# 基本用法
.venv/bin/python -m src.cli <url> [options]

# 选项
--output, -o       输出文件路径
--vertical         使用竖屏模式
--dry-run          只生成计划，不渲染
--style            视频风格 (default/single-review/hotlist/desktop-review)
--from-plan        从已有计划文件继续
--voice            TTS 语音名称
--min-duration     最短时长（秒）
--max-duration     最长时长（秒）
--fps              帧率
--no-bgm           不添加背景音乐
--bgm-volume       背景音乐音量 (0.0-1.0)
--bgm-path         自定义 BGM 路径
--verbose, -v      详细输出
```

**使用示例**:
```bash
# 单项目竖屏视频
.venv/bin/python -m src.cli https://github.com/owner/repo --vertical -o output/repo/final.mp4

# 热榜视频
.venv/bin/python -m src.cli https://github.com/repo1,https://github.com/repo2 --vertical --style hotlist -o output/hotlist/final.mp4

# 从计划文件继续
.venv/bin/python -m src.cli --from-plan output/repo -o output/repo/final.mp4

# 只生成计划
.venv/bin/python -m src.cli https://github.com/owner/repo --vertical --dry-run
```

## 控制台模块 (src/console/)

### 4. src/console/server.py - HTTP 服务器

基于 Python 标准库的 HTTP 服务器，提供 REST API。

#### 主要功能

- 静态文件服务
- REST API 路由
- 请求处理
- 错误处理

#### 启动方式

```bash
.venv/bin/python -m src.console --port 8765
```

### 5. src/console/jobs.py - 任务编排

控制台的核心业务逻辑，实现了完整的热榜视频生成工作流。

#### 主要函数

##### create_hotlist_job()

创建热榜任务。

```python
def create_hotlist_job(
    config: dict,
    job_id: str | None = None
) -> dict:
    """
    创建热榜任务

    Args:
        config: 任务配置
            - frequency: 频率 (daily/weekly)
            - project_count: 项目数量
            - style: 视频风格
        job_id: 任务 ID（自动生成）

    Returns:
        任务信息字典
    """
```

##### generate_candidates()

生成候选项目。

```python
def generate_candidates(job_id: str) -> dict:
    """
    生成候选项目

    Args:
        job_id: 任务 ID

    Returns:
        候选项目列表
    """
```

##### save_selection()

保存项目选择。

```python
def save_selection(
    job_id: str,
    selected: list[dict]
) -> dict:
    """
    保存项目选择

    Args:
        job_id: 任务 ID
        selected: 选中的项目列表
            - rank: 排名
            - name: 项目名称
            - owner: 所有者

    Returns:
        选择结果，包含钩子标题和口播脚本
    """
```

##### save_script()

保存口播脚本。

```python
def save_script(
    job_id: str,
    script: dict
) -> dict:
    """
    保存口播脚本

    Args:
        job_id: 任务 ID
        script: 脚本内容

    Returns:
        质量检查结果和发布辅助包
    """
```

##### prepare_plan()

生成计划文件。

```python
def prepare_plan(job_id: str) -> dict:
    """
    生成计划文件

    Args:
        job_id: 任务 ID

    Returns:
        分镜方案、素材清单和预览帧路径
    """
```

##### validate_plan()

校验计划。

```python
def validate_plan(job_id: str) -> dict:
    """
    校验计划

    Args:
        job_id: 任务 ID

    Returns:
        校验结果
    """
```

##### render_video()

渲染视频。

```python
def render_video(job_id: str) -> dict:
    """
    渲染视频

    Args:
        job_id: 任务 ID

    Returns:
        渲染状态
    """
```

##### finalize_numbered_output()

生成带编号的正式文件。

```python
def finalize_numbered_output(job_id: str) -> dict:
    """
    生成带编号的正式文件

    Args:
        job_id: 任务 ID

    Returns:
        编号文件列表
    """
```

### 6. src/console/store.py - 文件存储层

负责所有配置和任务数据的文件持久化。

#### 主要函数

##### ensure_storage()

初始化存储目录。

```python
def ensure_storage() -> None:
    """确保存储目录存在"""
```

##### create_job()

创建任务。

```python
def create_job(job_id: str, job_data: dict) -> None:
    """
    创建任务

    Args:
        job_id: 任务 ID
        job_data: 任务数据
    """
```

##### read_job()

读取任务。

```python
def read_job(job_id: str) -> dict:
    """
    读取任务

    Args:
        job_id: 任务 ID

    Returns:
        任务数据
    """
```

##### update_job()

更新任务。

```python
def update_job(job_id: str, updates: dict) -> None:
    """
    更新任务

    Args:
        job_id: 任务 ID
        updates: 更新内容
    """
```

##### next_job_id()

生成任务 ID。

```python
def next_job_id() -> str:
    """
    生成任务 ID

    Returns:
        任务 ID，格式: GH-HOTLIST-YYYYMMDD-001
    """
```

##### config_snapshot()

获取配置快照。

```python
def config_snapshot() -> dict:
    """
    获取配置快照（API Key 已脱敏）

    Returns:
        配置字典
    """
```

### 7. src/console/model_router.py - AI 模型路由

统一的 AI 模型调用层，支持多个供应商。

#### 主要函数

##### chat_json()

调用 AI 获取 JSON 响应。

```python
async def chat_json(
    task: str,
    messages: list[dict],
    fallback: Any = None
) -> Any:
    """
    调用 AI 获取 JSON 响应

    Args:
        task: 任务类型
        messages: 消息列表
        fallback: 失败时的回退值

    Returns:
        解析后的 JSON 数据
    """
```

##### chat_text()

调用 AI 获取文本响应。

```python
async def chat_text(
    task: str,
    messages: list[dict],
    fallback: str = ""
) -> str:
    """
    调用 AI 获取文本响应

    Args:
        task: 任务类型
        messages: 消息列表
        fallback: 失败时的回退值

    Returns:
        文本响应
    """
```

##### test_provider()

测试供应商连接。

```python
async def test_provider(provider_id: str) -> dict:
    """
    测试供应商连接

    Args:
        provider_id: 供应商 ID

    Returns:
        测试结果
    """
```

### 8. src/console/github_hotlist.py - GitHub 热榜候选收集

通过 GitHub Search API 拉取近期高星项目。

#### 主要函数

##### fetch_candidates()

获取候选项目。

```python
def fetch_candidates(
    token: str,
    limit: int = 10,
    window: str = "daily"
) -> list[dict]:
    """
    获取候选项目

    Args:
        token: GitHub Token
        limit: 返回数量
        window: 时间窗口 (daily/weekly/monthly)

    Returns:
        候选项目列表
    """
```

**返回数据结构**:
```python
{
    "rank": 1,
    "name": "project-name",
    "owner": "owner",
    "full_name": "owner/project-name",
    "stars": 1234,
    "language": "Python",
    "description": "项目描述",
    "topics": ["ai", "machine-learning"],
    "recommendation": "推荐理由",
    "target_audience": "目标受众",
    "score": 85,
    "star_history": "1000 → 1234 (+234)",
    "tech_tags": ["AI", "Python", "Machine Learning"]
}
```

### 9. src/console/scheduler.py - 定时调度器

支持定时任务调度。

#### 主要函数

##### start_scheduler()

启动调度器。

```python
def start_scheduler() -> None:
    """启动后台调度器"""
```

##### stop_scheduler()

停止调度器。

```python
def stop_scheduler() -> None:
    """停止调度器"""
```

##### run_due_jobs()

运行到期的任务。

```python
def run_due_jobs() -> list[dict]:
    """
    运行到期的任务

    Returns:
        运行的任务列表
    """
```

### 10. src/console/preflight.py - 渲染环境预检

检查渲染环境是否就绪。

#### 主要函数

##### run_preflight()

运行环境预检。

```python
def run_preflight() -> dict:
    """
    运行环境预检

    Returns:
        预检结果
    """
```

**检查项目**:
- Python 模块是否安装
- ffmpeg 是否可用
- Playwright 浏览器是否安装
- GitHub Token 是否有效
- 模型供应商是否连接成功

## 视频生成模块

### 11. src/planner/ - 分镜规划

#### brief.py - 选题判断

```python
def generate_creative_brief(
    project_info: ProjectInfo,
    use_ai: bool = True
) -> CreativeBrief:
    """
    生成短视频选题判断

    Args:
        project_info: 项目信息
        use_ai: 是否使用 AI

    Returns:
        选题判断结果
    """
```

#### shot_plan.py - 分镜方案生成

```python
def generate_single_review_shot_plan(
    project_info: ProjectInfo
) -> ShotPlan:
    """
    生成单项目竖屏分镜

    Args:
        project_info: 项目信息

    Returns:
        分镜方案（7 个镜头，约 31 秒）
    """
```

```python
def generate_hotlist_shot_plan(
    projects: list[ProjectInfo]
) -> ShotPlan:
    """
    生成多项目热榜分镜

    Args:
        projects: 项目信息列表

    Returns:
        分镜方案（开场 + 排行榜 + N 个项目 + 结尾）
    """
```

#### script_v2.py - 分镜转 TTS 脚本

```python
def generate_script_from_shot_plan(
    shot_plan: ShotPlan,
    project_info: ProjectInfo | None = None
) -> VideoScript:
    """
    将分镜方案转换为 TTS 脚本

    Args:
        shot_plan: 分镜方案
        project_info: 项目信息（可选）

    Returns:
        视频脚本
    """
```

**特性**:
- 违禁词过滤（"兄弟们"、"卧槽"、"绝了"等）
- 英文翻译替换
- 口语化处理

#### assets.py - 素材清单生成

```python
def generate_asset_manifest(
    project_info: ProjectInfo,
    shot_plan: ShotPlan
) -> AssetManifest:
    """
    生成素材清单

    Args:
        project_info: 项目信息
        shot_plan: 分镜方案

    Returns:
        素材清单
    """
```

#### capture.py - 素材采集

```python
async def capture_assets(
    manifest: AssetManifest,
    output_dir: Path
) -> AssetManifest:
    """
    采集素材

    Args:
        manifest: 素材清单
        output_dir: 输出目录

    Returns:
        更新后的素材清单（包含本地路径）
    """
```

#### desktop_review.py - 桌面审阅风格分镜

```python
def generate_desktop_review_plan(
    project_info: ProjectInfo
) -> DesktopReviewPlan:
    """
    生成桌面审阅风格分镜

    Args:
        project_info: 项目信息

    Returns:
        分镜方案（6 个镜头）
    """
```

**镜头结构**:
1. 仓库首页
2. 项目价值
3. README 图片
4. 功能目录
5. 使用方式
6. Star 数

### 12. src/composer/ - 视频合成

#### vertical.py - 竖屏视频合成

```python
def compose_vertical_video(
    shot_plan: ShotPlan,
    assets: list[Path],
    audio_files: list[Path],
    output_path: Path,
    fps: int = 30
) -> Path:
    """
    合成竖屏视频

    Args:
        shot_plan: 分镜方案
        assets: 素材文件列表
        audio_files: 音频文件列表
        output_path: 输出路径
        fps: 帧率

    Returns:
        输出文件路径
    """
```

**支持的视觉处理方式**:
- `hotlist_opening` - 热榜开场帧
- `hotlist_ranking` - 排行榜总览帧
- `hotlist_rank_card` - 单项目排名卡
- `hotlist_closing` - 结尾互动帧
- `single_hook` - 单项目钩子
- `single_judgment` - 单项目判断
- `single_project_card` - 单项目卡片
- `single_closing` - 单项目结尾

#### desktop_review.py - 桌面审阅风格视频合成

```python
def compose_desktop_review_video(
    plan: DesktopReviewPlan,
    frames: list[Path],
    audio_files: list[Path],
    output_path: Path,
    fps: int = 30
) -> Path:
    """
    合成桌面审阅风格视频

    Args:
        plan: 分镜方案
        frames: 浏览器录制帧
        audio_files: 音频文件
        output_path: 输出路径
        fps: 帧率

    Returns:
        输出文件路径
    """
```

**画布规格**: 1592x1080

#### video.py - 横屏视频合成

```python
def compose_video(
    script: VideoScript,
    frames: list[Path],
    audio_files: list[Path],
    output_path: Path,
    fps: int = 30
) -> Path:
    """
    合成横屏视频

    Args:
        script: 视频脚本
        frames: 浏览器录制帧
        audio_files: 音频文件
        output_path: 输出路径
        fps: 帧率

    Returns:
        输出文件路径
    """
```

**画布规格**: 1920x1080

#### bgm.py - BGM 混音

```python
def add_bgm(
    video_path: Path,
    bgm_path: Path | None = None,
    volume: float = 0.13,
    fade_in: float = 1.0,
    fade_out: float = 1.0
) -> Path:
    """
    添加背景音乐

    Args:
        video_path: 视频文件路径
        bgm_path: BGM 文件路径（自动查找）
        volume: 音量 (0.0-1.0)
        fade_in: 淡入时间（秒）
        fade_out: 淡出时间（秒）

    Returns:
        输出文件路径
    """
```

```python
def normalize_audio(
    video_path: Path,
    target_lufs: float = -17.0
) -> Path:
    """
    响度标准化

    Args:
        video_path: 视频文件路径
        target_lufs: 目标响度 (LUFS)

    Returns:
        输出文件路径
    """
```

```python
def post_process_video(
    video_path: Path,
    bgm_path: Path | None = None,
    bgm_volume: float = 0.13,
    no_bgm: bool = False
) -> Path:
    """
    视频后处理

    Args:
        video_path: 视频文件路径
        bgm_path: BGM 路径
        bgm_volume: BGM 音量
        no_bgm: 不添加 BGM

    Returns:
        输出文件路径
    """
```

#### effects.py - 视觉特效

```python
def create_title_card(
    title: str,
    width: int = 1080,
    height: int = 1920
) -> Image:
    """
    创建开场标题卡

    Args:
        title: 标题文本
        width: 宽度
        height: 高度

    Returns:
        PIL Image 对象
    """
```

```python
def add_particles(
    frame: Image,
    particle_count: int = 50
) -> Image:
    """
    添加粒子效果

    Args:
        frame: 原始帧
        particle_count: 粒子数量

    Returns:
        添加粒子后的帧
    """
```

### 13. src/hotlist_v2/ - 热榜 V2 渲染

#### fetch.py - GitHub 热榜数据抓取

```python
def fetch_trending(
    token: str,
    limit: int = 10,
    window: str = "daily"
) -> dict:
    """
    获取 GitHub 热榜数据

    Args:
        token: GitHub Token
        limit: 返回数量
        window: 时间窗口

    Returns:
        热榜数据
    """
```

**返回数据结构**:
```python
{
    "projects": [
        {
            "rank": 1,
            "name": "project-name",
            "owner": "owner",
            "stars": 1234,
            "language": "Python",
            "description": "项目描述",
            "stars_display": "1.2k",
            "daily_growth": "+234",
            "tech_tags": ["AI", "Python"],
            "star_history": "1000 → 1234",
            "reason": "推荐理由"
        }
    ],
    "language_stats": {
        "Python": 5,
        "JavaScript": 3,
        "TypeScript": 2
    },
    "topic_tags": ["ai", "machine-learning", "web"]
}
```

#### render.py - 端到端渲染管线

```python
async def render_hotlist_v2(
    token: str,
    limit: int = 10,
    window: str = "daily",
    style: str = "tech_hotspot",
    output_path: Path | None = None
) -> Path:
    """
    渲染热榜 V2 视频

    Args:
        token: GitHub Token
        limit: 项目数量
        window: 时间窗口
        style: 视频风格
        output_path: 输出路径

    Returns:
        输出文件路径
    """
```

```python
async def render_hotlist_v2_from_projects(
    projects: list[dict],
    style: str = "tech_hotspot",
    output_path: Path | None = None
) -> Path:
    """
    从控制台选中项目数据渲染

    Args:
        projects: 项目数据列表
        style: 视频风格
        output_path: 输出路径

    Returns:
        输出文件路径
    """
```

#### template.py - Jinja2 模板渲染

```python
def render_composition(
    data: dict,
    style: str = "tech_hotspot"
) -> str:
    """
    渲染 HTML 合成页面

    Args:
        data: 模板数据
        style: 视频风格

    Returns:
        HTML 内容
    """
```

### 14. src/browser/ - 浏览器录制

#### recorder.py - 浏览器录制器

```python
async def record_browser(
    script: VideoScript,
    output_dir: Path,
    fps: int = 30
) -> list[Path]:
    """
    录制浏览器截图序列

    Args:
        script: 视频脚本
        output_dir: 输出目录
        fps: 帧率

    Returns:
        截图文件路径列表
    """
```

#### actions.py - 浏览器动作

```python
async def execute_action(
    page: Page,
    action: str,
    target: str
) -> None:
    """
    执行浏览器动作

    Args:
        page: Playwright Page 对象
        action: 动作类型 (navigate/scroll/click/highlight/zoom)
        target: 目标元素或 URL
    """
```

#### desktop_review_recorder.py - 桌面审阅录制器

```python
async def record_desktop_review(
    plan: DesktopReviewPlan,
    output_dir: Path
) -> list[Path]:
    """
    录制桌面审阅风格截图

    Args:
        plan: 分镜方案
        output_dir: 输出目录

    Returns:
        截图文件路径列表
    """
```

**特性**:
- 1440x900 视口
- 2x 设备缩放
- 暗色模式
- 反自动化检测脚本注入

### 15. src/animation/ - 动画引擎

#### camera.py - 镜头缩放

```python
def calculate_camera_states(
    frames: list[dict],
    fps: int = 30
) -> list[CameraState]:
    """
    计算镜头状态

    Args:
        frames: 帧信息列表
        fps: 帧率

    Returns:
        镜头状态列表
    """
```

**动作缩放参数**:
- `navigate`: 1.0x
- `scroll`: 1.1x
- `click`: 1.8x
- `highlight`: 1.6x
- `zoom`: 2.2x

```python
def apply_camera_zoom(
    frame: Image,
    state: CameraState
) -> Image:
    """
    应用镜头缩放

    Args:
        frame: 原始帧
        state: 镜头状态

    Returns:
        缩放后的帧
    """
```

#### mouse.py - 鼠标动效引擎

```python
def create_cursor_image(size: int = 48) -> Image:
    """
    创建鼠标指针图像

    Args:
        size: 指针大小

    Returns:
        PIL Image 对象
    """
```

```python
def create_click_effect(
    x: int,
    y: int,
    frame: Image
) -> Image:
    """
    创建点击效果

    Args:
        x: X 坐标
        y: Y 坐标
        frame: 原始帧

    Returns:
        添加效果后的帧
    """
```

```python
def calculate_mouse_path(
    start: tuple[int, int],
    end: tuple[int, int],
    steps: int
) -> list[tuple[int, int]]:
    """
    计算鼠标移动路径（贝塞尔曲线）

    Args:
        start: 起始坐标
        end: 结束坐标
        steps: 步数

    Returns:
        路径坐标列表
    """
```

### 16. src/tts/ - 语音合成

#### edge_tts.py - Edge TTS 语音合成

```python
async def generate_audio_segment(
    text: str,
    output_path: Path,
    voice: str = "zh-CN-YunxiNeural",
    rate: str = "+30%"
) -> Path:
    """
    生成单段语音

    Args:
        text: 文本内容
        output_path: 输出路径
        voice: 语音名称
        rate: 语速

    Returns:
        输出文件路径
    """
```

```python
async def generate_all_audio(
    script: VideoScript,
    output_dir: Path,
    voice: str = "zh-CN-YunxiNeural",
    rate: str = "+30%"
) -> list[Path]:
    """
    为脚本所有片段生成语音

    Args:
        script: 视频脚本
        output_dir: 输出目录
        voice: 语音名称
        rate: 语速

    Returns:
        音频文件路径列表
    """
```

```python
def get_audio_duration(audio_path: Path) -> float:
    """
    获取音频时长

    Args:
        audio_path: 音频文件路径

    Returns:
        时长（秒）
    """
```

### 17. src/scraper/ - 数据抓取

#### github_api.py - GitHub API

```python
def fetch_repo_info(
    url: str,
    token: str | None = None
) -> ProjectInfo:
    """
    获取仓库信息

    Args:
        url: GitHub URL
        token: GitHub Token

    Returns:
        项目信息
    """
```

```python
def parse_github_url(url: str) -> tuple[str, str]:
    """
    解析 GitHub URL

    Args:
        url: GitHub URL

    Returns:
        (owner, repo) 元组
    """
```

### 18. src/script/ - 脚本生成

#### generator.py - AI 脚本生成器

```python
async def generate_script(
    project_info: ProjectInfo,
    api_key: str,
    base_url: str | None = None
) -> VideoScript:
    """
    用 AI 生成横屏视频脚本

    Args:
        project_info: 项目信息
        api_key: API Key
        base_url: API Base URL

    Returns:
        视频脚本
    """
```

```python
def generate_default_script(
    project_info: ProjectInfo
) -> VideoScript:
    """
    生成默认脚本（无 API Key 时）

    Args:
        project_info: 项目信息

    Returns:
        视频脚本
    """
```

### 19. src/utils/ - 工具函数

#### config.py - 全局配置

```python
# 路径配置
ROOT_DIR: Path          # 项目根目录
OUTPUT_DIR: Path        # 输出目录

# GitHub 配置
GITHUB_TOKEN: str       # GitHub Token
OPENAI_API_KEY: str     # OpenAI API Key
OPENAI_BASE_URL: str    # OpenAI API Base URL

# TTS 配置
TTS_VOICE: str          # TTS 语音名称
TTS_RATE: str           # TTS 语速

# 视频配置
VIDEO_FPS: int          # 帧率
VIDEO_WIDTH_H: int      # 横屏宽度
VIDEO_HEIGHT_H: int     # 横屏高度
VIDEO_WIDTH_V: int      # 竖屏宽度
VIDEO_HEIGHT_V: int     # 竖屏高度

# BGM 配置
BGM_DIR: Path           # BGM 目录
BGM_VOLUME: float       # BGM 音量
BGM_FADE_IN: float      # BGM 淡入时间
BGM_FADE_OUT: float     # BGM 淡出时间
```
