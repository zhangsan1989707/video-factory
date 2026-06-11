# GitHub 热榜多视觉风格模板开发任务

## 目标

在本地控制台中支持选择不同视觉风格，用同一批 GitHub 热榜数据、同一份口播脚本和同一条时间线，生成不同视觉风格的竖屏视频。生产输出统一为 1080x1920，优先走 HyperFrames HTML 模板管线。

本任务是长期开发入口，不要求一次性把所有参考稿细节迁移完，但每一步都必须让“UI 可选择、后端可识别、预览可生成、最终渲染可落地”更接近真实完成。

## 当前资产盘点

| 文件 | 定位 | 视觉特征 | 动态化状态 | 首批策略 |
| --- | --- | --- | --- | --- |
| `hotlist-v2.html` | 生产基准模板 | 科技热点、深色、数据卡片、GSAP 时间线 | 已接入 Jinja、1080x1920、`data-start/data-duration`、`window.__timelines["main"]` | 默认风格 `tech_hotspot`，也是共享生产骨架 |
| `github-trending-screens-v3-apple.html` | 参考稿 | Apple 极简、浅色、玻璃卡片、系统字体 | 静态 375x812 预览稿 | 首批风格 `apple_minimal` |
| `github-trending-screens-v4-claude.html` | 参考稿 | Claude 暖橘、浅暖背景、柔和卡片 | 静态 375x812 预览稿 | 首批风格 `claude_warm` |
| `github-trending-screens-v10-sspai.html` | 参考稿 | 少数派编辑风、红色强调、杂志感排版 | 静态 375x812 预览稿 | 首批风格 `sspai_editorial` |
| `github-trending-screens-v8-bytedance.html` | 参考稿 | 字节产品风、蓝色强调、企业产品信息密度 | 静态 375x812 预览稿 | 首批风格 `bytedance_product` |
| `github-trending-screens-v5-chinese.html` | 参考稿 | 中国风、纸张底色、红金强调、宋体气质 | 静态 375x812 预览稿 | 首批风格 `chinese_editorial` |
| `github-trending-screens-v2.html` / `github-trending-screens-v2-2-初始设计稿件.html` | 历史参考稿 | 早期科技深色方案 | 静态 375x812 预览稿 | 只作为 `tech_hotspot` 的历史参考，不作为首批独立入口 |

## 首批风格注册

模板注册表是唯一可信来源，字段至少包括：

- `style`: 稳定风格 key。
- `label`: UI 展示名称。
- `template_file`: 实际 Jinja/HyperFrames 模板文件。
- `render_engine`: 默认渲染引擎。
- `default_params`: 默认项目数、字幕模式、口播语气、BGM、方向等参数。
- `supports_preview`: 是否支持静态预览帧。
- `source_reference`: 来源参考稿。

首批 style：

- `tech_hotspot`: 科技热点风，生产基准。
- `apple_minimal`: Apple 极简风。
- `claude_warm`: Claude 暖橘风。
- `sspai_editorial`: 少数派编辑风。
- `bytedance_product`: 字节产品风。
- `chinese_editorial`: 中国风编辑版。

旧字段兼容：

- `tech_dark` 规范化为 `tech_hotspot`。
- `minimal_white` 规范化为 `apple_minimal`。
- `black_gold` 规范化为 `chinese_editorial`。
- 前端旧字段 `visual_style` 仍可读取，但保存和任务内部统一使用 `template_params.style`。

## 开发规则

1. 新增风格必须先补注册表，再补 UI 和测试。
2. 新风格默认复用 hotlist v2 的数据结构：`intro_screen`、`list_screen`、`detail_screens`、`hook_screen`、`top_projects`、`total_duration`。
3. 每个生产模板都必须保留：
   - `data-composition-id="main"`
   - 1080x1920 画布
   - `screen-intro`、`screen-list`、`screen-detail-*`、`screen-hook`
   - `data-start/data-duration`
   - `window.__timelines["main"]`
4. 风格差异优先用参数表达：色板、字体、字号比例、卡片密度、圆角、阴影、榜单行高、详情页模块权重、图表表现、动效速度与转场强度。
5. 不为每个风格复制整套渲染流程。除非明确证明某风格无法使用 HyperFrames，否则走统一 HTML 管线。
6. 任何缺失字段必须由数据层或模板层 fallback 到基准模板可用内容，不能让画面空白或渲染失败。
7. 提交前必须检查 worktree，只提交任务相关文件，不混入已有无关修改、临时文件或用户未要求处理的删除项。

## 验收标准

- `/api/config` 返回 `template_styles`，UI 可据此展示首批风格。
- 创建任务、配置模板、定时任务都能保存并规范化 `template_params.style`。
- `prepare_plan` 根据任务 style 生成对应 HyperFrames 预览帧。
- `render_video` 根据任务 style 渲染最终视频。
- 已确认的 `narration.json` 继续传入 `render_hotlist_v2_from_projects`，最终视频不丢失人工确认口播。
- `scripts/render_hotlist_v2.py --style <style>` 支持注册表中的所有首批风格。

## 推荐验证

```bash
.venv/bin/python -m unittest tests.test_hotlist_v2_render tests.test_console_jobs tests.test_console_providers tests.test_console_scheduler tests.test_console_server_smoke
node tests/test_console_static_app.js
node --check src/console/static/app.js
.venv/bin/python -m compileall src scripts
git diff --check
```

手动验收时，用同一组 5 个项目分别渲染：

- `tech_hotspot`
- `apple_minimal`
- `sspai_editorial`

检查点：

- 三个输出视觉明显不同。
- 榜单可读，详情页指标不溢出。
- `intro/list/detail/hook` 均出现。
- 最终 mp4 可正常播放。
