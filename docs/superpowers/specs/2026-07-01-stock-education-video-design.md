# 炒股科普视频赛道设计文档

## 目标

新建「炒股科普」视频赛道，与现有 GitHub 热榜赛道平行。生成 60 秒竖屏科普视频，系列名「60 秒带你看懂 xxx」，面向抖音平台。

## 核心约束

- 时长：固定 60 秒
- 系列：「60 秒带你看懂 xxx」
- BGM：无
- 字幕：必须有
- 视觉风格：杂志风（精致排版，专业媒体感）
- 动画引擎：`feicaiclub/video-spec-builder`
- 平台：抖音竖屏（1080x1920）

## 产品定位

### 与 GitHub 赛道的区别

| 维度 | GitHub 赛道 | 炒股科普赛道 |
|------|------------|-------------|
| 内容来源 | GitHub Trending | 财经网站 / LLM / 手动输入 |
| 内容类型 | 项目推荐 | 概念解读 / 名词科普 / 技术分析 |
| 叙事风格 | 博主安利，发现感 | 科普讲解，专业但亲切 |
| 动画需求 | 基础 | 丰富（图表动效、数据可视化、过渡动画） |
| 系列命名 | 无固定系列 | 「60 秒带你看懂 xxx」 |

### 第一版范围

- 单条视频完整流程：输入主题 → 生成脚本 → 渲染视频 → 输出 MP4
- 三种内容来源混合模式
- 固定杂志风视觉模板
- 固定 60 秒时长
- 无 BGM，有字幕
- 复用现有 TTS 系统

### 第一版不包含

- 多条视频批量生成
- 自动选题或热点追踪
- 视频编辑或脚本修改（生成即确认）
- 发布辅助（标题、话题标签）
- 横屏版本

## 系统架构

### 赛道隔离

```
src/
├── github/          # GitHub 赛道（现有）
│   ├── scraper/
│   ├── script/
│   ├── planner/
│   └── composer/
└── stock/           # 炒股科普赛道（新增）
    ├── scraper/     # 财经网站抓取
    ├── script/      # 科普脚本生成
    ├── spec/        # video-spec-builder 封装
    ├── planner/     # 分镜规划
    ├── composer/    # 视频合成
    └── templates/   # 杂志风模板资源
```

### 复用与扩展

| 组件 | 复用方式 |
|------|---------|
| TTS (Edge TTS) | 直接复用，stock 赛道调用相同接口 |
| BGM | 固定无 BGM，composer 绕过 BGM 步骤 |
| LLM 调用 | 复用 model_router，根据赛道加载不同 prompt 模板 |
| Console UI | 扩展赛道切换器，共用任务列表、设置面板 |
| 任务存储 | 共用 jobs 目录，按赛道前缀隔离（STOCK-YYYYMMDD-###） |

## 数据流

### 输入层

```
用户输入
├── 主题（必填）：如 "MACD指标" / "什么是市盈率"
├── 内容来源：
│   ├── 财经网站抓取 → 输入 URL 或概念搜索词
│   ├── LLM 生成 → 输入主题关键词
│   └── 手动输入 → 直接粘贴文章或要点
└── 补充信息（可选）：背景知识、目标受众、特殊要求
```

### 处理层

1. **内容获取**
   - 财经网站抓取：东方财富、雪球、同花顺等，解析文章提取关键段落
   - LLM 生成：根据主题关键词生成科普内容
   - 手动输入：直接使用用户提供的文本

2. **内容提炼**（LLM）
   - 从原始内容中提取 3-5 个核心要点
   - 每个要点一句话（20 字以内）
   - 生成开场钩子：「60 秒带你看懂 xxx」

3. **脚本生成**（LLM）
   - 生成 60 秒口播脚本
   - 配合分镜时间戳
   - 每句话不超过 15 字（抖音节奏）

4. **分镜规划**
   - 调用 video-spec-builder 生成动画分镜
   - 杂志风排版：大字标题 + 副标题 + 装饰元素
   - 60 秒固定分镜数量（约 8-12 个镜头）

5. **字幕生成**
   - 从脚本提取字幕
   - 时间戳对齐
   - SRT 格式输出

### 输出层

```
output/jobs/STOCK-YYYYMMDD-001/
├── task.json              # 任务元数据
├── source_content.json    # 原始内容
├── key_points.json       # 提炼要点
├── script.json           # 口播脚本（含时间戳）
├── subtitle.srt          # 字幕文件
├── shot_spec.json        # video-spec-builder 分镜规范
├── rendered_frames/      # 渲染帧序列
├── preview_frames/       # 预览帧
└── STOCK-YYYYMMDD-001-60秒带你看懂MACD.mp4
```

## 前端 Console 扩展

### 赛道切换器

顶部导航栏添加赛道选择：

```
[GitHub 热榜] [炒股科普]  ← radio tab 风格
```

切换赛道时：
- 工作区内容完全切换
- 任务列表按赛道过滤
- 配置面板显示对应赛道的参数

### 炒股科普工作区

```
┌─────────────────────────────────────────────┐
│ 炒股科普 · 60秒科普系列          [新建任务]   │
├─────────────────────────────────────────────┤
│ 主题：______________________________         │
│                                             │
│ 内容来源：○ 财经网站  ○ LLM生成  ○ 手动输入   │
│                                             │
│ [根据来源显示对应输入框]                      │
│                                             │
│ 时长：60秒（固定）                           │
│ 字幕：✓ 启用（固定）                         │
│ BGM：无（固定）                              │
│                                             │
│ [生成科普视频]                               │
└─────────────────────────────────────────────┘
```

### 任务阶段

```
idle
  ↓ 创建任务
collecting_content
  ↓ 内容获取完成
refining_content
  ↓ 要点提炼完成
generating_script
  ↓ 脚本生成完成
planning_shots
  ↓ 分镜规划完成（调用 video-spec-builder）
rendering_frames
  ↓ 帧渲染完成
generating_tts
  ↓ TTS 生成完成
composing_video
  ↓ 视频合成完成
completed / failed
```

### 复用组件

| 组件 | 炒股科普赛道复用方式 |
|------|-------------------|
| 模型配置面板 | 直接复用，共用 LLM 设置 |
| TTS 配置 | 直接复用，声音/语速可调 |
| 任务历史列表 | 按赛道分组显示 |
| 日志面板 | 直接复用 |
| 预览播放器 | 直接复用 |

## video-spec-builder 集成

### 集成方式

通过子模块或复制代码引入 `feicaiclub/video-spec-builder`，封装为 `stock/spec/renderer.py`。

### 分镜规范格式

输入给 video-spec-builder 的分镜 JSON：

```json
{
  "version": "1.0",
  "resolution": [1080, 1920],
  "duration": 60,
  "font_family": "Noto Sans SC",
  "theme": {
    "primary": "#1A1A2E",
    "accent": "#E8B04B",
    "text": "#FFFFFF",
    "background": "#0F0F1A"
  },
  "shots": [
    {
      "id": 1,
      "start": 0,
      "end": 5,
      "type": "title",
      "content": {
        "main": "60秒带你看懂",
        "sub": "MACD指标",
        "style": "magazine_cover"
      },
      "animation": {
        "enter": "fade_in_scale",
        "exit": "fade_out"
      }
    },
    {
      "id": 2,
      "start": 5,
      "end": 12,
      "type": "definition",
      "content": {
        "term": "MACD",
        "definition": "Moving Average Convergence Divergence",
        "translation": "指数平滑异同移动平均线"
      },
      "animation": {
        "enter": "slide_up",
        "elements": ["term", "definition", "translation"]
      }
    }
  ]
}
```

### 支持的分镜类型

| 类型 | 说明 | 动画特点 |
|------|------|---------|
| `title` | 封面标题 | 杂志层叠、渐入、缩放 |
| `definition` | 名词定义 | 逐行滑入、强调高亮 |
| `chart` | 图表展示 | 数据动效、绘制动画 |
| `comparison` | 对比展示 | 左右切入、切换动效 |
| `timeline` | 时间线 | 依次展开、流动动画 |
| `summary` | 总结收尾 | 汇总要点、淡出 |

## 杂志风视觉设计

### 配色方案

```css
--stock-bg-primary: #0F0F1A;      /* 深邃背景 */
--stock-bg-secondary: #1A1A2E;    /* 卡片背景 */
--stock-accent: #E8B04B;          /* 金色强调 */
--stock-text-primary: #FFFFFF;     /* 主文字 */
--stock-text-secondary: #A0A0B0;   /* 副文字 */
--stock-chart-green: #4ADE80;     /* 涨 */
--stock-chart-red: #F87171;       /* 跌 */
```

### 字体层级

- 主标题：72px，粗体，字间距加宽
- 副标题：36px，常规
- 正文：28px，常规
- 注释：20px，浅色

### 装饰元素

- 细线条分隔（1px，金色）
- 角落装饰角标
- 微妙的渐变叠加
- 数字/百分比大字体突出

## 脚本生成 Prompt 设计

### 60 秒科普脚本 Prompt

```
你是一个炒股科普短视频专家，正在为抖音「60秒带你看懂xxx」系列生成脚本。

## 主题
{theme}

## 原始内容
{original_content}

## 要求

1. **开场钩子**：第一句必须抓住注意力，如「今天讲一个所有散户必须懂的指标」
2. **节奏**：60秒约 150-180 字，每句话 10-15 字
3. **结构**：
   - 0-5秒：钩子 + 主题引入
   - 5-25秒：核心概念解释（2-3个要点）
   - 25-45秒：实际应用/案例
   - 45-60秒：总结 + 引导互动
4. **语言**：通俗易懂，像跟朋友聊天，避免太专业的术语
5. **字幕**：每句话单独一行，方便提取

## 输出格式
严格输出 JSON：
{
  "title": "60秒带你看懂XXX",
  "segments": [
    {"timestamp": 0, "duration": 5, "narration": "台词", "subtitle": "字幕"},
    ...
  ]
}
```

## 测试验收

- 创建一个「什么是市盈率」测试任务，验证完整流程
- 验证 video-spec-builder 渲染输出
- 验证字幕时间戳对齐
- 验证 TTS 音画同步
- 验证输出 MP4 时长接近 60 秒
- 验证 Console UI 赛道切换正常

## 实施顺序

1. **第一阶段**：核心数据流
   - stock 目录结构搭建
   - scraper 实现（财经网站抓取）
   - script generator 实现
   - 基础 prompt 模板

2. **第二阶段**：video-spec-builder 集成
   - 封装 renderer
   - 定义分镜 JSON 格式
   - 实现杂志风模板

3. **第三阶段**：Console UI 扩展
   - 赛道切换器
   - 炒股科普工作区
   - 任务状态流转

4. **第四阶段**：端到端测试
   - 完整流程测试
   - 视频质量验收
