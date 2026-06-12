# 全功能流程持续改进计划

## 目标

把现有 GitHub Video Maker 从“热榜主流程已可用”推进到“日常稳定出片、流程可信、可交给他人持续使用”。本计划用于长期跟踪所有功能流程的提升点，每次开发完成后更新状态、证据和下一步。

当前判断：

- 热榜控制台主流程已打通：创建任务、生成候选、确认项目、生成与质检口播、生成计划、dry run、渲染、正式 mp4。
- 单项目、横屏、竖屏、desktop-review、from-plan 等能力主要在 CLI 中，尚未形成统一控制台任务入口。
- 自动化测试覆盖了核心控制台与轻量渲染路径，但真实 API、真实 TTS、真实浏览器录制和长视频渲染仍需要更强端到端验收。

## 状态约定

| 状态 | 含义 |
| --- | --- |
| `todo` | 尚未开始 |
| `doing` | 正在开发 |
| `blocked` | 有阻塞，需注明原因 |
| `done` | 已完成并通过验收 |
| `deferred` | 暂缓处理，需注明原因 |

更新规则：

1. 每次开发只更新与本次改动直接相关的条目。
2. 状态改为 `done` 时，必须补充验收证据：测试命令、手动验收记录或产物路径。
3. 如果发现新问题，优先追加到本文件，不直接混入无关重构。
4. 若条目拆分成更小任务，保留原条目并链接到新增子任务。

## P0：可信与稳定

### P0-1 保护历史正式视频版本

状态：`done`

问题：

重新生成最终视频时，前端提示会保留历史正式视频版本；但渲染失败路径可能清理带编号的正式 mp4，和用户预期不一致。

建议：

- 失败时只清理当前失败产物 `final.mp4`、临时文件或未完成输出。
- 保留已定稿的 `{job_id}-*.mp4`。
- 日志中明确区分“当前渲染失败”和“历史版本仍保留”。

验收证据：

- `2026-06-11`：`.venv/bin/python tests/test_console_jobs.py`
- 回归覆盖：
  - `test_reset_video_for_regeneration_keeps_script_and_clears_video_outputs`
  - `test_resaving_script_clears_stale_plan_artifacts`
  - `test_reselecting_projects_preserves_historical_official_video`
  - `test_render_video_records_failed_pipeline_stage_and_log_tail`

验收标准：

- 任务已有一个带编号正式 mp4 时，触发重新生成并模拟失败，历史 mp4 仍存在。
- 控制台产物列表仍能展示历史版本。
- 增加或更新对应测试。

参考位置：

- `src/console/jobs.py`
- `src/console/static/app.js`

### P0-2 统一耗时步骤为后台任务

状态：`done`

问题：

最终渲染已走后台线程，但候选生成、AI 分析、脚本生成、计划生成和计划校验仍以同步 POST 为主。模型或网络慢时，前端可能长时间等待。

建议：

- 把候选生成、重新生成候选、确认项目并生成脚本、重新生成脚本、生成计划、校验计划都纳入后台任务机制。
- API 立即返回 `started/active/job`，前端继续轮询任务状态。
- 保留当前阶段重试能力。

验收证据：

- `2026-06-11`：`.venv/bin/python tests/test_console_jobs.py`
- `2026-06-11`：`.venv/bin/python tests/test_console_server_smoke.py`
- `2026-06-11`：`node tests/test_console_static_app.js`
- 回归覆盖：
  - `test_start_candidates_job_returns_background_status_without_candidates`
  - `test_start_save_script_job_preserves_bad_request_validation`
  - `test_start_prepare_plan_job_preserves_bad_request_validation`
  - `test_http_workflow_reaches_render_start_and_artifacts`
  - `test_list_jobs_does_not_fail_active_background_request`

验收标准：

- 点击上述耗时按钮后，HTTP 请求快速返回。
- 刷新页面后能继续看到运行中任务状态。
- 控制台重启后，悬挂的 `running` 任务会被标记为可重试失败状态。
- 增加服务端和前端状态测试。

参考位置：

- `src/console/background.py`
- `src/console/server.py`
- `src/console/static/app.js`

### P0-3 明确热榜数据口径

状态：`done`

问题：

当前候选来自 GitHub Search 的新建仓库 + stars 排序，`daily_growth` 是估算值，不是真实新增 star。如果 UI 或口播把估算热度说成事实，会影响可信度。

建议：

- 字段命名或展示文案改为“估算日均 star”。
- 候选表、日志、发布包中标注数据来源与缓存状态。
- 口播生成提示中禁止把估算增长描述成真实增量。

验收证据：

- `2026-06-11`：`.venv/bin/python tests/test_github_hotlist.py`
- `2026-06-11`：`.venv/bin/python tests/test_console_jobs.py`
- `2026-06-11`：`.venv/bin/python tests/test_hotlist_v2_render.py`
- `2026-06-11`：`node tests/test_console_static_app.js`
- 回归覆盖：
  - `test_collect_candidates_without_token`
  - `test_save_script_writes_publish_pack`
  - `test_save_script_flags_growth_overclaim_in_quality_report`
  - `test_ai_projects_get_specific_hooks_outcomes_and_tags`

验收标准：

- 候选表能看到热度口径。
- 发布包或 readiness report 能看到数据来源说明。
- 脚本质检能识别“真实增长”类过度表述。

参考位置：

- `src/console/github_hotlist.py`
- `src/console/jobs.py`
- `src/console/static/app.js`

### P0-4 修正 HyperFrames 阶段显示

状态：`done`

问题：

HyperFrames 分支会先把状态设为 `generating_tts`，随后很快设为 `composing_video`，但实际渲染函数内部仍会生成 TTS。用户看到的阶段不够准确。

建议：

- 为 `render_hotlist_v2_from_projects` 增加阶段回调，细分 TTS、HTML composition、HyperFrames render、audio mix、post process。
- 前端阶段时间线展示这些真实阶段。

验收证据：

- `2026-06-11`：`.venv/bin/python tests/test_console_jobs.py`
- `2026-06-11`：`.venv/bin/python tests/test_hotlist_v2_render.py`
- `2026-06-11`：`node tests/test_console_static_app.js`
- 回归覆盖：
  - `test_render_video_auto_validates_unchecked_plan`
  - `test_render_video_records_precise_hyperframes_failed_stage`
  - `test_hyperframes_render_emits_stage_callbacks_in_real_order`
  - `testFailedJobsExposeRetryActions`

验收标准：

- 日志和阶段历史能反映真实渲染步骤。
- 取消任务至少能在步骤边界生效。
- 测试覆盖阶段回调顺序。

参考位置：

- `src/console/jobs.py`
- `src/hotlist_v2/render.py`

## P1：工作流效率

### P1-1 强化 AI 生成与回退标识

状态：`done`

问题：

当前模型不可用时会启发式评分、模板口播或跳过质检。稳定性较好，但用户不一定能立刻看出哪些内容来自 AI，哪些来自规则回退。

建议：

- 候选表展示分析来源：AI、启发式、缓存。
- 口播区展示生成来源：AI 成功、模型失败回退、模型跳过。
- 产物摘要中记录模型调用状态。

验收标准：

- 不配置模型供应商时，用户能明确看到回退状态。
- 配置模型但调用失败时，日志和 UI 都能看到失败原因摘要。
- 回退状态不阻塞用户继续手动编辑。

验收证据：

- `2026-06-11`：`.venv/bin/python -m pytest tests/test_console_jobs.py -q`
- `2026-06-11`：`node tests/test_console_static_app.js`
- 回归覆盖：
  - `test_generate_candidates_records_cache_and_fallback_source_summary`
  - `test_candidate_analysis_invalid_response_is_saved_for_review`
  - `test_selection_falls_back_when_model_is_unconfigured`
  - `testCandidateSourceLabelShowsSummary`
  - `testNarrationSourceLabelShowsFallbackReason`
  - `testModelSummaryLabelCombinesLatestCallAndNarrationSource`

参考位置：

- `src/console/model_router.py`
- `src/console/jobs.py`
- `src/console/static/app.js`

### P1-2 做成可操作的脚本质检闭环

状态：`done`

问题：

脚本质检能阻断渲染，也支持人工忽略，但 UI 中“修正建议”按钮目前不可用，用户需要自己在大段文本里找问题。

建议：

- 质检风险项绑定到具体口播段落。
- 点击风险项定位到对应 textarea。
- 可选：生成一版局部改写建议，但不自动覆盖用户文本。

验收标准：

- 质检失败时，用户能从风险项跳到对应段落。
- 修改后重新确认口播会重新运行质检。
- 忽略风险会写入 `quality_report.json`。

验收证据：

- `2026-06-11`：`.venv/bin/python -m pytest tests/test_console_jobs.py -q`
- `2026-06-11`：`node tests/test_console_static_app.js`
- 回归覆盖：
  - `test_save_script_binds_quality_issues_to_project_segments`
  - `test_save_script_flags_growth_overclaim_in_quality_report`
  - `test_save_script_blocks_when_fact_check_returns_invalid_json_until_overridden`
  - `testQualityNotesPreferStructuredIssues`
  - `testFocusScriptSegmentHighlightsTarget`
  - `testRenderQualityReportShowsLocateAction`

参考位置：

- `src/console/jobs.py`
- `src/console/static/app.js`

### P1-3 优化产物预览与发布工作台

状态：`done`

问题：

现在产物列表能查看文件和预览帧，但日常出片还缺少更直接的工作台体验。

建议：

- 内嵌最终 mp4 播放器。
- 展示封面、视频时长、文件大小、版本列表。
- 发布标题、标签、口播摘要支持一键复制。
- 明确标注当前正式版本。

验收标准：

- 完成任务后不用打开文件夹即可预览最终视频。
- 多个版本能清晰区分。
- 发布文案可直接复制。

验收证据：

- `2026-06-12`：`.venv/bin/python -m pytest tests/test_console_jobs.py -q`
- `2026-06-12`：`node tests/test_console_static_app.js`
- 回归覆盖：
  - `test_video_versions_sort_by_version_when_timestamps_match`
  - `test_job_numbering_and_finalize_do_not_overwrite_outputs`
  - `testRenderArtifactSummaryShowsPublishMetadata`
  - `testFormatHelpersForArtifactWorkbench`
  - `testRenderPublishActionsShowsCopyButtons`
  - `testCopyTextUsesClipboardWhenAvailable`

参考位置：

- `src/console/static/index.html`
- `src/console/static/app.js`
- `src/console/static/styles.css`

### P1-4 增强预检为真实 smoke check

状态：`done`

问题：

当前预检主要检查依赖是否存在，不能证明真实渲染、TTS、ffmpeg 组合一定可用。

建议：

- 增加最小 HTML 预览帧生成检查。
- 增加 ffmpeg/ffprobe 对短样例的检查。
- 可选增加 TTS 连通性检查，但必须避免每次打开控制台都触发昂贵网络请求。

验收标准：

- 预检报告区分“依赖存在”和“真实 smoke 通过”。
- smoke 检查失败时给出可执行修复建议。
- 不显著拖慢控制台启动。

验收证据：

- `2026-06-12`：`.venv/bin/python -m pytest tests/test_console_preflight.py -q`
- `2026-06-12`：手动快照：`preflight_snapshot()` 返回 `ready 本机渲染依赖和 smoke 均可用。`
- 回归覆盖：
  - `test_preflight_snapshot_reports_required_render_checks`
  - `test_preflight_summary_mentions_smoke_when_all_smoke_checks_pass`
  - `test_ffmpeg_smoke_failure_is_blocking_and_actionable`
  - `test_preflight_endpoint_returns_snapshot`

参考位置：

- `src/console/preflight.py`
- `src/console/static/app.js`

## P2：能力统一

### P2-1 将 CLI 视频能力纳入控制台任务类型

状态：`todo`

问题：

CLI 支持单项目、横屏、竖屏、desktop-review、from-plan；控制台主入口基本只支持热榜。用户会感知为两个产品。

建议：

- 引入 `job.type`：`github_hotlist`、`single_project_vertical`、`desktop_review`、`from_plan_render`。
- 新建任务时选择任务类型。
- 每种任务复用相同的任务状态、日志、产物、重试机制。

验收标准：

- 控制台可创建至少一种非热榜任务。
- 非热榜任务能生成计划、渲染并展示产物。
- 原热榜任务兼容旧数据。

参考位置：

- `src/cli.py`
- `src/pipeline.py`
- `src/console/store.py`
- `src/console/jobs.py`

### P2-2 定时任务从草稿走向半自动出片

状态：`todo`

问题：

定时任务目前适合自动生成候选草稿，但不会继续脚本、计划或渲染，也没有明确的待办提醒。

建议：

- 保留默认安全模式：只生成候选，等待人工确认。
- 增加可选模式：生成候选 + 自动选前 N 个 + 生成脚本，等待人工确认。
- 暂不默认自动渲染，避免错误内容直接出片。

验收标准：

- 定时任务生成后，历史列表中有明显“待确认”状态。
- 自动脚本模式可配置、可关闭。
- 失败日志能说明是 GitHub、模型还是渲染前置问题。

参考位置：

- `src/console/scheduler.py`
- `src/console/static/app.js`

### P2-3 建立真实端到端验收样例

状态：`todo`

问题：

当前测试对核心逻辑有保护，但真实 API、真实 TTS、真实浏览器录制、真实长视频渲染还缺少稳定验收方案。

建议：

- 增加一个手动验收清单文档，记录真实出片步骤。
- 增加可选的慢速 e2e 测试标记，不默认跑。
- 固定一组公共仓库作为 smoke 样例，避免选题波动影响判断。

验收标准：

- 开发者能按文档从空环境跑出一条视频。
- 慢速 e2e 可以用环境变量显式开启。
- 失败时能定位到 GitHub、TTS、HyperFrames、ffmpeg 或浏览器录制环节。

参考位置：

- `tests/`
- `docs/development.md`
- `README.md`

## 推荐开发顺序

1. P0-1 保护历史正式视频版本。
2. P0-4 修正 HyperFrames 阶段显示。
3. P0-2 统一耗时步骤为后台任务。
4. P0-3 明确热榜数据口径。
5. P1-2 做成可操作的脚本质检闭环。
6. P1-3 优化产物预览与发布工作台。
7. P2-1 将 CLI 视频能力纳入控制台任务类型。

## 通用验证命令

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

## 更新记录

| 日期 | 更新 | 证据 |
| --- | --- | --- |
| 2026-06-12 | 完成 P1-4：预检新增 `ffmpeg/ffprobe` 短视频 smoke 和 HyperFrames CLI smoke，摘要可区分真实 smoke 状态并给出修复建议 | `.venv/bin/python -m pytest tests/test_console_preflight.py -q` ; `preflight_snapshot()` |
| 2026-06-12 | 完成 P1-3：右侧工作台支持内嵌最终视频预览、封面/时长/大小/版本列表展示，并提供发布标题/标签/描述复制按钮 | `.venv/bin/python -m pytest tests/test_console_jobs.py -q` ; `node tests/test_console_static_app.js` |
| 2026-06-11 | 完成 P1-1：候选区补充缓存/AI/启发式来源标识，口播区明确 AI 成功与回退状态，产物摘要展示最近模型调用与口播来源 | `.venv/bin/python -m pytest tests/test_console_jobs.py -q` ; `node tests/test_console_static_app.js` |
| 2026-06-11 | 完成 P0-3：`daily_growth` 统一改为“估算日均 star”口径，候选表/发布辅助包/准备度报告展示数据说明，质检可拦截“真实增长”类口播 | `.venv/bin/python tests/test_github_hotlist.py` ; `.venv/bin/python tests/test_console_jobs.py` ; `.venv/bin/python tests/test_hotlist_v2_render.py` ; `node tests/test_console_static_app.js` |
| 2026-06-11 | 完成 P0-2：候选生成、项目确认、口播确认、计划生成与计划校验统一改为后台任务快速返回，前端改为轮询接管 | `.venv/bin/python tests/test_console_jobs.py` ; `.venv/bin/python tests/test_console_server_smoke.py` ; `node tests/test_console_static_app.js` |
| 2026-06-11 | 完成 P0-4：HyperFrames 渲染改为按真实步骤记录 `generating_tts -> composing_html -> rendering_hyperframes -> mixing_audio -> post_processing` | `.venv/bin/python tests/test_console_jobs.py` ; `.venv/bin/python tests/test_hotlist_v2_render.py` ; `node tests/test_console_static_app.js` |
| 2026-06-11 | 完成 P0-1：重新生成、重选项目、重存脚本与渲染失败时保留历史正式视频版本，仅清理当前 `final.mp4` 与工作产物 | `.venv/bin/python tests/test_console_jobs.py` |
| 2026-06-11 | 创建全功能流程持续改进计划 | 基于控制台、CLI、任务编排、热榜抓取、渲染、预检与测试覆盖审计 |
