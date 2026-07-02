# 炒股科普短视频生成器开发设计文档

## 1. 文档信息

| 字段 | 内容 |
|---|---|
| 项目 | `video-factory` |
| 功能域 | `finance_edu` |
| 目标版本 | MVP v0.1 |
| 文档类型 | 技术开发设计文档 |
| 主要入口 | Web 控制台新增“炒股科普”页面 |
| 输出 | 1080x1920 竖屏 MP4 |
| 内容边界 | 科普，不荐股，不预测，不承诺收益 |

---

## 2. 当前项目基础判断

当前项目已有以下可复用能力：

1. Web 控制台任务流。
2. AI 模型路由。
3. 脚本生成能力。
4. 分镜计划能力。
5. TTS 生成能力。
6. 视频合成能力。
7. HyperFrames / HTML 动画渲染能力。
8. 任务产物目录管理。
9. dry run 和预览帧机制。
10. ffmpeg 后处理能力。

因此，本次开发不建议重写视频流水线，而是新增一个独立内容域：

```text
src/finance_edu/
```

该模块负责金融科普主题、脚本、分镜、合规、模板和渲染适配。

---

## 3. 架构设计原则

### 3.1 不污染现有 GitHub 视频管线

现有 GitHub 项目视频逻辑仍然保留在：

```text
src/planner/
src/hotlist_v2/
src/scraper/
src/composer/
src/console/
```

新增功能不要把金融科普逻辑写进 `ProjectInfo`、`GitHub hotlist`、`desktop-review` 等模块。

### 3.2 独立领域模型

新增 `FinanceEduTopic`、`FinanceEduScript`、`FinanceEduScene`、`FinanceComplianceReport` 等模型。

不建议直接复用 `ProjectInfo`。可以适当转换成现有 `VideoScript` 和类似 `ShotPlan` 的结构，但领域模型应保持独立。

### 3.3 固定结构优先于自由生成

炒股科普视频要稳定，不应让 AI 自由决定结构。MVP 固定为 7 段式：

```text
Hook → Misunderstanding → Concept → How It Works → How To Use → Pitfall → Summary
```

### 3.4 合规检查必须前置

AI 生成脚本之后、生成视频之前，必须执行合规检查。若发现高风险内容，应阻断渲染或要求用户修改。

---

## 4. 推荐目录结构

新增目录：

```text
src/finance_edu/
├── __init__.py
├── models.py
├── constants.py
├── prompts.py
├── script_generator.py
├── storyboard.py
├── compliance.py
├── renderer.py
├── pipeline.py
├── storage.py
└── sample_data.py
```

建议后续再增加：

```text
src/finance_edu/templates/
├── black_gold.py
├── white_card.py
└── common.py
```

若 HyperFrames 需要 HTML 模板，可以增加：

```text
assets/templates/finance_edu/
├── black_gold.html
├── white_card.html
├── black_gold.css
├── white_card.css
└── finance_edu_renderer.js
```

控制台前端增加：

```text
src/console/static/
├── finance_edu.html 或复用 index.html 内新增 tab
├── finance_edu.js
└── finance_edu.css
```

控制台后端增加 API handler：

```text
src/console/server.py
src/console/jobs.py
```

按现有风格接入。

---

## 5. 数据模型设计

### 5.1 `FinanceEduTopic`

```python
from dataclasses import dataclass, field
from typing import Literal

TopicType = Literal["indicator", "trading_basic", "risk_discipline"]
Audience = Literal["beginner", "junior_retail"]
VisualStyle = Literal["black_gold", "white_card"]
RiskLevel = Literal["education_only"]

@dataclass
class FinanceEduTopic:
    topic: str
    topic_type: TopicType = "indicator"
    audience: Audience = "beginner"
    duration: int = 60
    platform: str = "douyin_wechat_channels"
    visual_style: VisualStyle = "black_gold"
    risk_level: RiskLevel = "education_only"
    keywords: list[str] = field(default_factory=list)
```

### 5.2 `FinanceEduScript`

```python
@dataclass
class FinanceEduScript:
    title: str
    hook: str
    narration: str
    segments: list["FinanceEduScriptSegment"]
    risk_disclaimer: str
    total_duration: int = 60
```

### 5.3 `FinanceEduScriptSegment`

```python
@dataclass
class FinanceEduScriptSegment:
    scene_type: str
    start: float
    duration: float
    narration: str
    screen_title: str
    screen_subtitle: str
    bullets: list[str]
```

### 5.4 `FinanceEduScene`

```python
@dataclass
class FinanceEduScene:
    scene_id: str
    scene_type: str
    start: float
    duration: float
    title: str
    subtitle: str
    bullets: list[str]
    narration: str
    visual_style: str
    template_id: str
    chart_type: str
    chart_hint: str
    risk_note: str = ""
```

### 5.5 `FinanceComplianceReport`

```python
@dataclass
class FinanceComplianceIssue:
    level: str  # low / medium / high
    category: str
    text: str
    suggestion: str

@dataclass
class FinanceComplianceReport:
    passed: bool
    max_risk_level: str
    issues: list[FinanceComplianceIssue]
    rewritten_text: str | None = None
```

---

## 6. 任务产物目录

每次生成一个任务目录：

```text
output/jobs/finance-edu-{yyyyMMdd-HHmmss}/
├── topic.json
├── script.json
├── storyboard.json
├── compliance_check.json
├── render_plan.json
├── preview_frames/
├── audio/
├── frames/
├── final.mp4
└── timing_report.json
```

### 6.1 `topic.json`

保存用户输入参数。

### 6.2 `script.json`

保存 AI 生成和人工编辑后的口播脚本。

### 6.3 `storyboard.json`

保存每个 scene 的模板、时间、画面标题、字幕、图表类型。

### 6.4 `compliance_check.json`

保存合规扫描结果。

### 6.5 `render_plan.json`

保存传递给 HyperFrames 的最终渲染参数。

---

## 7. Pipeline 设计

新增：

```text
src/finance_edu/pipeline.py
```

### 7.1 主流程

```python
async def run_finance_edu_video(
    topic: FinanceEduTopic,
    output_dir: Path | None = None,
    voice: str | None = None,
    dry_run: bool = False,
) -> Path:
    """生成炒股科普短视频。"""
```

### 7.2 流程图

```text
创建任务目录
  ↓
保存 topic.json
  ↓
生成脚本 script.json
  ↓
执行合规检查 compliance_check.json
  ↓
高风险则阻断 / 中低风险自动改写
  ↓
生成分镜 storyboard.json
  ↓
生成 TTS 音频
  ↓
生成 render_plan.json
  ↓
HyperFrames 渲染视频
  ↓
ffmpeg 后处理
  ↓
输出 final.mp4
```

### 7.3 伪代码

```python
async def run_finance_edu_video(topic, output_dir=None, voice=None, dry_run=False):
    paths = create_finance_job_paths(output_dir)
    write_json(paths.topic_json, topic_to_dict(topic))

    script = await generate_finance_script(topic)
    write_json(paths.script_json, script_to_dict(script))

    report = check_finance_compliance(script)
    write_json(paths.compliance_check_json, report_to_dict(report))

    if not report.passed and report.max_risk_level == "high":
        raise ValueError("脚本包含高风险荐股或收益承诺内容，请修改后再渲染")

    storyboard = await generate_finance_storyboard(topic, script)
    write_json(paths.storyboard_json, storyboard_to_dict(storyboard))

    if dry_run:
        return paths.base

    await generate_tts_for_finance_script(script, paths.audio_dir, voice)

    render_plan = build_finance_render_plan(topic, script, storyboard, paths)
    write_json(paths.render_plan_json, render_plan)

    raw_video = await render_finance_hyperframes(render_plan, paths)
    final_video = post_process_video(raw_video)
    return final_video
```

---

## 8. Prompt 设计

### 8.1 脚本生成 Prompt

文件：

```text
src/finance_edu/prompts.py
```

常量：

```python
FINANCE_SCRIPT_PROMPT = """
你是一个中文短视频股票知识科普编导。

任务：根据用户给定主题，生成一条 60 秒左右的股票知识科普口播稿。

内容边界：
1. 只做知识科普，不构成投资建议。
2. 不推荐任何具体股票。
3. 不预测明天涨跌。
4. 不承诺收益。
5. 不使用“稳赚”“必涨”“抄底”“梭哈”“牛股”等营销话术。
6. 可以讲历史案例或模拟案例，但必须说明案例不代表未来。

目标用户：股市新手 / 初级散户。
语言风格：大白话、克制、可信、不要装专家。

视频结构固定为 7 段：
1. hook：0-3 秒，提出反常识或痛点。
2. misunderstanding：3-8 秒，纠正常见误区。
3. concept：8-18 秒，解释核心概念。
4. how_it_works：18-32 秒，解释指标或方法如何运作。
5. how_to_use：32-45 秒，说明正确使用方式。
6. pitfall：45-55 秒，提醒常见坑。
7. summary：55-60 秒，一句话总结。

输出 JSON，不要输出 Markdown。
字段：title, hook, segments, risk_disclaimer。
segments 中每项包含：scene_type, start, duration, narration, screen_title, screen_subtitle, bullets。

主题：{topic}
主题类型：{topic_type}
视觉风格：{visual_style}
"""
```

### 8.2 分镜生成 Prompt

```python
FINANCE_STORYBOARD_PROMPT = """
你是一个短视频分镜设计师。

请把股票科普口播稿转换成 1080x1920 竖屏视频分镜。

要求：
1. 每个分镜只表达一个核心信息。
2. 主标题不超过 16 个中文字符。
3. 副标题不超过 24 个中文字符。
4. 每屏最多 3 个 bullet。
5. 每个 bullet 不超过 12 个中文字符。
6. 不要出现具体买卖建议。
7. 不要出现收益承诺。
8. 图表使用虚拟示意，不使用真实个股数据。

可用模板：
- hook_title
- myth_vs_truth
- concept_card
- indicator_chart
- three_points
- risk_warning
- summary_quote

输出 JSON。
字段：scenes。
每个 scene 包含：scene_id, scene_type, start, duration, title, subtitle, bullets, narration, visual_style, template_id, chart_type, chart_hint, risk_note。
"""
```

---

## 9. 合规检查设计

文件：

```text
src/finance_edu/compliance.py
```

### 9.1 风险词库

```python
BANNED_PATTERNS = [
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
]
```

### 9.2 风险类别

| 类别 | 示例 | 风险等级 |
|---|---|---|
| buy_sell_advice | 建议买入、建议卖出 | high |
| price_prediction | 明天上涨、即将拉升 | high |
| profit_promise | 稳赚、翻倍 | high |
| hype_marketing | 牛股、赶紧上车 | medium |
| missing_disclaimer | 没有风险提示 | medium |

### 9.3 检查函数

```python
def check_finance_compliance(script: FinanceEduScript) -> FinanceComplianceReport:
    text = collect_all_script_text(script)
    issues = []
    for pattern in BANNED_PATTERNS:
        if pattern in text:
            issues.append(build_issue(pattern))

    if not has_disclaimer(text):
        issues.append(missing_disclaimer_issue())

    max_level = resolve_max_level(issues)
    return FinanceComplianceReport(
        passed=max_level != "high",
        max_risk_level=max_level,
        issues=issues,
    )
```

### 9.4 阻断规则

| 风险等级 | 处理 |
|---|---|
| low | 允许继续 |
| medium | 提醒用户，允许继续或自动追加风险提示 |
| high | 阻断渲染，要求修改 |

---

## 10. 渲染设计

### 10.1 渲染策略

MVP 优先使用 HyperFrames / HTML 动画渲染。若现有 HyperFrames 入口只服务热榜，可为 `finance_edu` 新增独立渲染入口，避免污染 `hotlist_v2`。

建议文件：

```text
src/finance_edu/renderer.py
assets/templates/finance_edu/finance_edu.html
assets/templates/finance_edu/finance_edu.css
assets/templates/finance_edu/finance_edu_renderer.js
```

### 10.2 渲染输入 `render_plan.json`

```json
{
  "width": 1080,
  "height": 1920,
  "fps": 30,
  "duration": 60,
  "style": "black_gold",
  "title": "60 秒搞懂 MACD：金叉不是买入按钮",
  "scenes": [
    {
      "scene_id": "s1",
      "template_id": "hook_title",
      "start": 0,
      "duration": 3,
      "title": "金叉就能买？",
      "subtitle": "新手最容易踩的坑",
      "bullets": [],
      "chart_type": "none"
    }
  ]
}
```

### 10.3 模板类型

| 模板 ID | 用途 | 适用段落 |
|---|---|---|
| hook_title | 大标题开场 | Hook |
| myth_vs_truth | 误区对比 | Misunderstanding |
| concept_card | 概念解释 | Concept |
| indicator_chart | 指标示意图 | How It Works |
| three_points | 三点总结 | How To Use |
| risk_warning | 风险提醒 | Pitfall |
| summary_quote | 一句话总结 | Summary |

---

## 11. 视觉主题设计

### 11.1 黑金交易室 `black_gold`

```python
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
```

### 11.2 白底科普卡片 `white_card`

```python
WHITE_CARD_THEME = {
    "background": "#F7F3EA",
    "panel": "#FFFFFF",
    "primary": "#1F2937",
    "accent": "#D9A441",
    "text": "#111827",
    "muted": "#6B7280",
    "warning": "#B45309",
}
```

### 11.3 安全区

```python
SAFE_AREA = {
    "top": 120,
    "bottom": 160,
    "left": 72,
    "right": 72,
}
```

---

## 12. 模拟图表设计

MVP 不接入真实行情，使用虚拟示意图。

### 12.1 MACD 图

元素：

- 虚拟 K 线背景，可弱化。
- DIF 快线。
- DEA 慢线。
- 红绿柱。
- 金叉 / 死叉提示点。

注意：不要显示真实股票代码、真实价格、真实日期。

### 12.2 KDJ 图

元素：

- K、D、J 三条线。
- 高位区 / 低位区。
- 不直接写“买入”“卖出”，改为“风险区”“观察区”。

### 12.3 均线图

元素：

- K 线示意。
- 5 日线、10 日线、20 日线。
- 趋势向上 / 震荡 / 拐头示意。

### 12.4 成交量图

元素：

- 下方量柱。
- 放量 / 缩量标注。
- 配合价格变化的示意箭头。

---

## 13. Web 控制台 API 设计

建议新增 API：

### 13.1 创建任务

```http
POST /api/finance-edu/jobs
```

请求：

```json
{
  "topic": "60秒带你搞懂MACD",
  "topic_type": "indicator",
  "audience": "beginner",
  "visual_style": "black_gold"
}
```

响应：

```json
{
  "job_id": "finance-edu-20260702-103000",
  "status": "created"
}
```

### 13.2 生成脚本

```http
POST /api/finance-edu/jobs/{job_id}/script
```

### 13.3 保存脚本

```http
PUT /api/finance-edu/jobs/{job_id}/script
```

### 13.4 生成分镜

```http
POST /api/finance-edu/jobs/{job_id}/storyboard
```

### 13.5 合规检查

```http
POST /api/finance-edu/jobs/{job_id}/compliance
```

### 13.6 渲染视频

```http
POST /api/finance-edu/jobs/{job_id}/render
```

### 13.7 查询任务状态

```http
GET /api/finance-edu/jobs/{job_id}
```

### 13.8 获取产物

复用现有产物访问机制，或增加：

```http
GET /api/finance-edu/jobs/{job_id}/artifacts
```

---

## 14. 前端页面设计

建议新增一个 Tab：

```text
炒股科普
```

页面分区：

```text
┌──────────────────────────────┐
│ 主题配置                     │
│ topic / type / audience      │
├──────────────────────────────┤
│ 脚本生成与编辑               │
│ textarea + generate button   │
├──────────────────────────────┤
│ 分镜预览                     │
│ scene cards                  │
├──────────────────────────────┤
│ 合规检查                     │
│ risk report                  │
├──────────────────────────────┤
│ 渲染与产物                   │
│ preview / final.mp4 / logs   │
└──────────────────────────────┘
```

### 14.1 页面状态

```text
idle
script_generating
script_ready
storyboard_generating
storyboard_ready
compliance_checking
compliance_passed
rendering
completed
failed
```

---

## 15. Codex 开发任务清单

### 15.1 第一阶段：领域模型和基础管线

1. 新建 `src/finance_edu/` 目录。
2. 新建 `models.py`，定义 Topic、Script、Scene、ComplianceReport。
3. 新建 `constants.py`，定义主题类型、视觉风格、禁用风险词。
4. 新建 `storage.py`，创建任务目录和 JSON 读写工具。
5. 新建 `pipeline.py`，实现 dry run 流程。

验收：能输入 topic，输出 `topic.json`、`script.json`、`storyboard.json`、`compliance_check.json`。

### 15.2 第二阶段：AI 生成与合规

1. 新建 `prompts.py`。
2. 新建 `script_generator.py`。
3. 新建 `storyboard.py`。
4. 新建 `compliance.py`。
5. 合规高风险时阻断渲染。

验收：输入“60 秒带你搞懂 MACD”，可生成 7 段脚本和分镜；出现“建议买入”时被合规检查拦截。

### 15.3 第三阶段：HyperFrames 渲染

1. 新建 `renderer.py`。
2. 新建 `assets/templates/finance_edu/`。
3. 实现黑金交易室模板。
4. 实现白底科普卡片模板。
5. 生成 `preview_frames` 和 `final.mp4`。

验收：生成 1080x1920 MP4，60 秒左右，字幕可读。

### 15.4 第四阶段：Web 控制台接入

1. 控制台增加“炒股科普”入口。
2. 新增 API：创建任务、生成脚本、生成分镜、合规检查、渲染。
3. 前端增加脚本编辑区。
4. 前端增加分镜预览卡片。
5. 前端增加产物展示。

验收：从 Web 控制台完整跑通一条 MACD 视频。

### 15.5 第五阶段：测试与样例

1. 增加 `tests/test_finance_edu_models.py`。
2. 增加 `tests/test_finance_edu_compliance.py`。
3. 增加 `tests/test_finance_edu_pipeline.py`。
4. 增加样例 `examples/finance_edu_macd.json`。
5. 更新 README，增加炒股科普使用说明。

---

## 16. 测试设计

### 16.1 模型测试

```python
def test_finance_topic_defaults():
    topic = FinanceEduTopic(topic="60秒带你搞懂MACD")
    assert topic.duration == 60
    assert topic.risk_level == "education_only"
```

### 16.2 合规测试

```python
def test_compliance_blocks_buy_advice():
    script = make_script("这只股票现在可以买入")
    report = check_finance_compliance(script)
    assert not report.passed
    assert report.max_risk_level == "high"
```

### 16.3 分镜测试

```python
def test_storyboard_has_seven_scenes():
    storyboard = generate_default_storyboard(make_macd_script())
    assert len(storyboard.scenes) == 7
```

### 16.4 Pipeline dry run 测试

```python
async def test_finance_pipeline_dry_run(tmp_path):
    topic = FinanceEduTopic(topic="60秒带你搞懂MACD")
    path = await run_finance_edu_video(topic, output_dir=tmp_path, dry_run=True)
    assert (path / "topic.json").exists()
    assert (path / "script.json").exists()
    assert (path / "storyboard.json").exists()
```

---

## 17. MACD 样例分镜 JSON

```json
{
  "title": "60 秒搞懂 MACD：金叉不是买入按钮",
  "scenes": [
    {
      "scene_id": "s1",
      "scene_type": "hook",
      "start": 0,
      "duration": 3,
      "title": "金叉就能买？",
      "subtitle": "新手最容易踩的坑",
      "bullets": [],
      "narration": "很多新手一看到 MACD 金叉，就想马上买。但这恰恰是最容易踩坑的地方。",
      "visual_style": "black_gold",
      "template_id": "hook_title",
      "chart_type": "none",
      "chart_hint": "深色背景，MACD 金叉图形从背景中浮现",
      "risk_note": ""
    },
    {
      "scene_id": "s2",
      "scene_type": "misunderstanding",
      "start": 3,
      "duration": 5,
      "title": "它不是买卖按钮",
      "subtitle": "只是一个观察工具",
      "bullets": ["不是预测器", "不是指令", "只是辅助"],
      "narration": "MACD 不是买卖按钮，它只是帮你观察趋势变化的工具。",
      "visual_style": "black_gold",
      "template_id": "myth_vs_truth",
      "chart_type": "macd",
      "chart_hint": "左侧误区，右侧正确理解",
      "risk_note": ""
    },
    {
      "scene_id": "s3",
      "scene_type": "concept",
      "start": 8,
      "duration": 10,
      "title": "MACD 看趋势",
      "subtitle": "核心是快慢线变化",
      "bullets": ["DIF 是快线", "DEA 是慢线", "柱子看差距"],
      "narration": "简单理解，DIF 是快线，DEA 是慢线，红绿柱反映两条线之间的距离变化。",
      "visual_style": "black_gold",
      "template_id": "concept_card",
      "chart_type": "macd",
      "chart_hint": "分别标出 DIF、DEA、红绿柱",
      "risk_note": ""
    },
    {
      "scene_id": "s4",
      "scene_type": "how_it_works",
      "start": 18,
      "duration": 14,
      "title": "红绿柱看变化",
      "subtitle": "柱子变长，说明差距扩大",
      "bullets": ["红柱增强", "绿柱减弱", "趋势变化"],
      "narration": "当红柱逐渐变长，通常说明向上的动能在增强；当绿柱变长，说明向下的压力在扩大。",
      "visual_style": "black_gold",
      "template_id": "indicator_chart",
      "chart_type": "macd",
      "chart_hint": "动态展示红绿柱由短变长",
      "risk_note": ""
    },
    {
      "scene_id": "s5",
      "scene_type": "how_to_use",
      "start": 32,
      "duration": 13,
      "title": "别只看金叉",
      "subtitle": "还要看这三件事",
      "bullets": ["趋势位置", "成交量", "风险空间"],
      "narration": "真正使用 MACD 时，不能只看金叉死叉，还要结合趋势位置、成交量和自己的风险空间。",
      "visual_style": "black_gold",
      "template_id": "three_points",
      "chart_type": "none",
      "chart_hint": "三张卡片依次出现",
      "risk_note": ""
    },
    {
      "scene_id": "s6",
      "scene_type": "pitfall",
      "start": 45,
      "duration": 10,
      "title": "高位金叉也会坑",
      "subtitle": "位置不同，意义不同",
      "bullets": ["低位不等于安全", "高位不等于机会", "指标会滞后"],
      "narration": "尤其要注意，MACD 本身有滞后性。高位出现金叉，也不代表一定还能继续涨。",
      "visual_style": "black_gold",
      "template_id": "risk_warning",
      "chart_type": "macd",
      "chart_hint": "高位区域出现警示标记，不写买卖字样",
      "risk_note": "指标存在滞后性"
    },
    {
      "scene_id": "s7",
      "scene_type": "summary",
      "start": 55,
      "duration": 5,
      "title": "一句话记住",
      "subtitle": "MACD 看趋势，不预测未来",
      "bullets": [],
      "narration": "一句话记住，MACD 看的是趋势变化，不是预测未来，更不能单独作为买卖依据。",
      "visual_style": "black_gold",
      "template_id": "summary_quote",
      "chart_type": "none",
      "chart_hint": "金句居中，底部显示风险提示",
      "risk_note": "仅作知识科普，不构成投资建议"
    }
  ]
}
```

---

## 18. 开发优先级建议

### P0：必须完成

1. `src/finance_edu/models.py`
2. `src/finance_edu/compliance.py`
3. `src/finance_edu/prompts.py`
4. `src/finance_edu/pipeline.py`
5. `src/finance_edu/renderer.py`
6. Web 控制台入口和 API。
7. MACD 样例跑通。

### P1：提升质量

1. 黑金交易室模板优化。
2. 白底卡片模板优化。
3. 预览帧质量优化。
4. 脚本编辑体验优化。
5. 更多主题默认提示词。

### P2：后续扩展

1. 封面图生成。
2. 批量生成。
3. 历史案例模式。
4. 模拟指标动画增强。
5. 导出发布文案。

---

## 19. 给 Codex 的执行提示词

可以直接把下面内容交给 Codex：

```text
请基于当前 video-factory 项目，新增 finance_edu 功能域，实现“炒股科普短视频生成器”的 MVP。

要求：
1. 不破坏现有 GitHub 项目视频、hotlist、desktop-review 管线。
2. 新增 src/finance_edu/ 目录，包含 models、constants、prompts、script_generator、storyboard、compliance、renderer、pipeline、storage。
3. 新增 Web 控制台“炒股科普”入口。
4. 支持输入主题，例如“60秒带你搞懂MACD”。
5. 固定生成 60 秒、7 段式结构：Hook、Misunderstanding、Concept、How It Works、How To Use、Pitfall、Summary。
6. 内容边界：只做科普，不荐股，不预测，不承诺收益。
7. 实现合规检查，高风险内容阻断渲染。
8. 使用 HyperFrames / HTML 模板渲染 1080x1920 竖屏视频。
9. 先实现 black_gold 和 white_card 两套风格。
10. 增加 MACD 样例数据和测试。

验收：
- Web 控制台可完整生成一条“60秒带你搞懂MACD”的视频。
- 输出 final.mp4、topic.json、script.json、storyboard.json、compliance_check.json。
- 合规检查能阻断“建议买入”“稳赚”“明天大涨”等话术。
```

---

## 20. 最终建议

第一版不要追求功能多，而要追求：

1. 脚本结构稳定。
2. 合规边界清楚。
3. 画面模板统一。
4. MACD 样例质量过关。
5. Web 控制台流程跑通。

只要 MACD 样例跑通，KDJ、均线、成交量、支撑压力、止损都可以通过同一套结构扩展。
