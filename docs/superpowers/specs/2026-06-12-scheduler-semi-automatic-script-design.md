# 定时任务半自动脚本模式设计

## 背景

P2-2 要把定时任务从“只生成候选草稿”推进到“可选半自动出片”。当前 scheduler 到点后只创建热榜任务并生成候选，后续必须人工确认项目、生成口播、准备计划和渲染。本轮只增加安全的半自动脚本模式，不自动渲染。

## 范围

新增 `scheduler.mode`：

- `candidates_only`：默认值，保持旧行为，只生成候选草稿并停在项目确认。
- `auto_script`：生成候选后自动选择前 `project_count` 个候选，调用现有项目确认与口播生成逻辑，停在 `awaiting_script_confirmation`。

暂不实现：

- 自动准备计划
- 自动校验计划
- 自动渲染
- 定时任务创建非热榜任务

## 数据流

`run_due_scheduled_draft()` 读取标准化 scheduler 配置：

1. 创建 `github_hotlist` 定时任务。
2. 调用 `generate_candidates(job_id)`。
3. 如果 `mode=candidates_only`，直接返回候选任务。
4. 如果 `mode=auto_script`，读取候选结果中的前 `project_count` 个项目，调用 `save_selection(job_id, {"items": selected})`。
5. 成功后标记本次调度已运行，任务停在 `awaiting_script_confirmation`。

如果候选生成或自动脚本生成失败，不更新 `last_run_date`，保留失败日志，方便下一次重试。

## UI

配置抽屉的定时草稿区新增“模式”选择：

- 只生成候选草稿
- 自动生成口播草稿

状态说明会根据模式显示：

- 候选模式：不会自动确认或渲染。
- 自动脚本模式：会自动确认前 N 个候选并生成口播，但仍等待人工确认，不会自动渲染。

## 验收

- 默认配置仍为候选草稿模式。
- 自动脚本模式可配置、可保存、可在 snapshot 中恢复。
- 自动脚本模式会生成口播并停在 `awaiting_script_confirmation`。
- 失败时不会更新 `last_run_date`。
- 前端文案明确“不会自动渲染”。
