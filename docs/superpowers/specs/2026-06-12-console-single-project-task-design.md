# 控制台单项目竖屏任务设计

## 背景

P2-1 要把 CLI 已有的视频能力逐步纳入控制台任务类型。当前控制台只完整支持 `github_hotlist`，而 CLI 已经支持单项目竖屏、desktop-review 和 from-plan。一次性纳入所有模式会扩大状态机、前端表单和错误恢复范围，因此本轮先实现最小可验收闭环：`single_project_vertical`。

## 范围

本轮新增一种控制台任务类型：

- `github_hotlist`：保持现有热榜候选、口播、计划、渲染流程不变。
- `single_project_vertical`：用户输入 GitHub 仓库 URL，控制台创建任务后可直接生成计划、校验计划、渲染最终视频，并沿用日志、阶段、产物、重试和历史版本能力。

暂不实现：

- `desktop_review`
- `from_plan_render`
- 单项目任务的 AI 口播编辑闭环
- 多任务类型的复杂表单编排

## 数据流

`POST /api/jobs` 根据 `payload.type` 分发：

- 未传 `type` 时按旧逻辑创建 `github_hotlist`，保证历史兼容。
- `type=single_project_vertical` 时校验 `repo_url`，使用 `GH-SINGLE-YYYYMMDD-XXX` 编号创建任务。

单项目任务的状态从 `draft_pending` 进入 `preparing_plan`，不经过候选列表和口播确认。点击主按钮时调用现有 `/prepare-plan`，服务端用 `run_pipeline(..., orientation="vertical", style="single-review", dry_run=True)` 生成 `info.json`、`asset_manifest.json`、`shot_plan.json` 和 `script.json`，再生成预览帧与 readiness report。

渲染时复用 `/render-video`，对 `single_project_vertical` 调用 `run_pipeline(..., from_plan=job_dir, orientation="vertical")`，最终仍生成 `final.mp4` 和带编号正式版本。

## UI

顶部新增任务类型选择：

- GitHub 热榜视频：显示时间维度和项目数。
- 单项目竖屏视频：显示仓库 URL 输入框，隐藏时间维度和项目数。

候选页在单项目任务下展示说明：该任务不需要候选项目，直接生成计划文件。

## 错误处理

- 单项目任务缺少或非法仓库 URL 时，创建请求返回 400。
- 计划生成、校验、渲染失败时继续使用现有 `failed_stage`、日志尾部和重试按钮。
- 热榜任务的候选、选择、口播接口仍只服务 `github_hotlist`；单项目任务误触发这些动作会返回明确错误。

## 验收

- 控制台可以创建 `single_project_vertical` 任务。
- 单项目任务可以生成计划文件，并展示产物。
- 单项目任务可以进入现有渲染后台任务。
- 旧热榜任务不传 `type` 时仍按 `github_hotlist` 创建。
- 测试覆盖服务端创建、计划生成分发、前端创建 payload 和动作文案。
