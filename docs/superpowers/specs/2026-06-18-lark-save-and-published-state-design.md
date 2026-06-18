# Lark 多维表格：全量/已选同步 + 已发布状态

**状态**：草案（待用户复核）
**日期**：2026-06-18
**作者**：brainstorming 输出

## 背景与目标

GitHub 热榜视频项目已稳定运行一段时间，每次跑调度器会：
1. 拉一份候选（25~30 个 trending 仓库）
2. 选 N 个做成视频
3. 渲染正式 mp4 输出

目前飞书侧只有一个"已选项目"表，且只在 `_sync_selection_to_lark` 一次性写入 `sync_selected_projects`，没有"全量候选"沉淀，也没有"已发布"标记。

需求方反馈两件事：

1. **可观测性**：每天拉到的候选和最终选入的项目都希望沉淀到飞书，方便事后回看（"那天我们看了哪些项目"、"最终选的是哪几个"）。
2. **避免重复选入**：用户希望基于"已发过视频"的历史，在下次拉候选时由 UI 提示哪些项目已出过片。**只做提示，不自动过滤**，最终决定权交回给用户。

本设计落地这两个需求，并对前后端 schema 同步加测试约束，避免常见的"后端加字段、前端忘渲染"问题。

## 设计原则

- **单一数据源**：已选表就是"完整入榜+出片历史"，加两个字段（已发布、发布时间）而不是新建第三张表。
- **最小破坏**：保留现有 `sync_selected_projects` 的字段集合与调用方语义，向后兼容旧 `table_id` 配置。
- **失败不阻塞**：飞书写失败只 log + 写 `job.lark_sync`，不抛错影响主流程。
- **可观测**：任务面板展示三段同步历史（all_data / selected / publish_mark）。
- **前后端对齐**：通过共享 ID 列表 + HTML 锚点测试 + 端到端 render 测试，确保改一处不会漏一处。

## 1. 配置与状态

### 1.1 `lark.json` 字段变化

`lark.json` 从 1 个 table 变成 2 个 table + 2 个开关：

```jsonc
{
  "enabled": true,
  "base_token": "xxxx",                  // 保留：同一个 Bitable
  "all_data_table_id": "tblAllC...",      // 🆕 全量候选表
  "selected_data_table_id": "tblSel...",  // 🆕 已选项目表（替代旧 table_id）
  "sync_all_data": true,                  // 🆕 全量同步开关
  "sync_selected_data": true              // 🆕 已选同步开关
}
```

向后兼容：
- `_normalize_lark` 读取时若旧 `table_id` 有值且新 `selected_data_table_id` 为空，自动映射为 `selected_data_table_id`。
- 已保存的 `lark.json` 不会因字段缺失报错；新字段给默认值（开关默认 `True`，table_id 默认空字符串）。

### 1.2 任务状态

每个 `task.json` 新增 `lark_sync` 字段（dict），记录最近一次同步结果：

```json
"lark_sync": {
  "all_data":    {"status": "synced", "count": 28, "error": "", "at": "2026-06-18T09:01:00Z"},
  "selected":    {"status": "synced", "count": 5,  "error": "", "at": "2026-06-18T09:05:00Z"},
  "publish_mark":{"status": "synced", "count": 5,  "error": "", "at": "2026-06-18T09:30:00Z"}
}
```

三段独立 status：`synced` / `skipped` / `failed` / `disabled`。`errors` 数组可选，记录单条 record 失败详情。

### 1.3 同步时机总览

| 触发点 | 全量候选表 | 已选项目表 | 标记已发布 |
|---|---|---|---|
| 候选拉取完成（`_generate_candidates_snapshot` 末尾） | ✅ upsert | — | — |
| 项目确认（`_sync_selection_to_lark`） | — | ✅ upsert（**仅 `job.scheduled==True`**） | — |
| 视频输出完成（`finalize_numbered_output` 末尾） | — | ✅ update（设 `已发布=True, 发布时间, 视频路径`） | — |

**手动 vs 调度判定**：任务本身在创建时携带 `scheduled` 标志（`store.py:create_job` 读取 `payload.get("scheduled")`），调度器（[scheduler.py:34-58](file:///Users/leohang/project/github-video/src/console/scheduler.py#L34-L58)）创建的任务显式 `scheduled=True`。手动/前端创建的任务 `scheduled=False`。本设计不依赖前端 hidden 字段，直接读 `job.get("scheduled")`。

**全量数据"总是同步"**：手动+调度都同步，因为全量表语义是"原始 trending 数据"，跟是否出片无关。

**已选数据"仅调度同步"**：手动选入不入表，避免实验性选择污染"出片历史"。

## 2. 表 schema

### 2.1 全量候选表（每日 trending 拉取的所有项目）

| 字段 | 类型 | 说明 |
|---|---|---|
| 抓取时间 | datetime | **去重 key part 1**，UTC ISO |
| 项目全名 | text | **去重 key part 2**（`owner/repo`） |
| 时间窗口 | single_select | `daily` / `weekly` / `monthly` |
| 数据源 | single_select | `trending` / `search_api` |
| 排名 | number | 1..30 |
| 抓取任务ID | text | `GH-HOTLIST-20260618-001` |
| 仓库URL | url | |
| 项目名 | text | |
| 描述原文 | multiline | |
| 描述中文 | multiline | `description_zh` |
| Stars | number | |
| Daily Growth | text | `估算日均 star 约 +179/天` |
| 语言 | text | |
| Topics | multiline | join 多个 topic |
| 推荐理由 | text | |
| 风险 | text | |
| 受众 | text | |
| 评分 | number | 0..100 |
| 是否有主页 | checkbox | |
| 缓存状态 | single_select | `fresh` / `hit` / `stale_rate_limit` |
| 抓取方式 | single_select | `手动` / `调度` |

去重：`(抓取时间, 项目全名)`。飞书 `+record-list` 按此过滤，存在则 update，否则 create。

### 2.2 已选项目表（最终入榜项目 + 出片历史）

| 字段 | 类型 | 说明 |
|---|---|---|
| 抓取时间 | datetime | **去重 key part 1** |
| 项目全名 | text | **去重 key part 2** |
| 时间窗口 | single_select | `daily` / `weekly` / `monthly` |
| 任务ID | text | `GH-HOTLIST-...` |
| 选择顺序 | number | 1..N |
| 仓库URL | url | |
| 项目名 | text | |
| 描述 | multiline | |
| 描述中文 | multiline | |
| Stars | number | |
| Daily Growth | text | |
| 语言 | text | |
| 推荐理由 | text | |
| 视频标题 | text | hook.title |
| 视频路径 | text | `official_video` 绝对路径（task.json 里的 `official_video` 字段） |
| **已发布** | checkbox | **🆕 视频输出完成时置 True** |
| **发布时间** | datetime | **🆕** `finalize_numbered_output` 时刻 |

去重：`(抓取时间, 项目全名)`。同一天重复选入 → update；不同天 → 追加为新行（保留"选入历史"）。

> **抓取时间口径**：单次拉取产生 25~30 个 candidate，"抓取时间"必须**任务内统一**为同一时间戳（`_generate_candidates_snapshot` 进入时取一次 `datetime.now()`，传给同步函数），否则同一批 candidate 会有不同秒级时间戳，去重键失效。`已选表`复用同一时间戳，与"已发布"标记查询对齐。

### 2.3 飞书写入机制

飞书 `+record-batch-update` 是"同值批量更新"，不适合逐行不同值。采用**查找后分桶**：

```text
upsert_records(base_token, table_id, records, key_fields):
  for record in records:
    list(filter={项目全名: ..., 抓取时间: ...})
    if found_existing:
      collect_to_update(record_id, record)
    else:
      collect_to_create(record)
  batch_create(records_to_create)
  for record_id, record in records_to_update:
    record_update(record_id, fields=record)  # 串行避免 1254291
```

## 3. 调用点详解

### 3.1 全量同步（`_generate_candidates_snapshot` 末尾）

```python
def _generate_candidates_snapshot(job_id, job, force_refresh=True):
    # ... 现有逻辑 ...
    write_json(JOBS_DIR / job_id / "candidates.json", {"items": candidates})
    _sync_all_candidates_to_lark(job_id, job, candidates, result_meta)
    # ...
```

`_sync_all_candidates_to_lark`：
1. 读 `lark.json` config
2. 若 `enabled` 且 `sync_all_data` 且 `all_data_table_id` 非空，调用 `sync_all_candidates(job, candidates, result_meta, fetch_time)`
3. 写结果到 `job.lark_sync.all_data`，错误写 `append_log` + `job.lark_sync.all_data.error`

`sync_all_candidates`：
- 入参：`job`, `candidates: list[dict]`, `result_meta: dict`（含 `cache_status` / `data_source` / `time_window`）, `fetch_time: str`（**任务级统一时间戳**）
- 逐条构造 record，按 `(项目全名, 抓取时间=fetch_time)` upsert
- 抓取方式 = `"调度"` if `job.get("scheduled")` else `"手动"`

### 3.2 已选同步（`_sync_selection_to_lark`）

```python
def _sync_selection_to_lark(job_id, selected):
    job = read_job(job_id)
    if not bool_value(job.get("scheduled")):
        append_log(job_id, "手动选入不同步到飞书已选表。")
        update_job(job_id, lark_sync={**job.get("lark_sync", {}), "selected": {"status": "skipped", "reason": "manual"}})
        return
    result = sync_selected_projects(job, selected)
    # ... 写 job.lark_sync.selected ...
```

### 3.3 标记已发布（`finalize_numbered_output` 末尾）

```python
def finalize_numbered_output(job_id, title=""):
    # ... 现有逻辑写 official_video ...
    _mark_published_in_lark(job_id)
    return {"job": read_job(job_id), "artifacts": job_artifacts(job_id)}
```

`_mark_published_in_lark`：
1. 读 `selected_projects.json` 和 `lark.json` config
2. 若 `enabled` 且 `sync_selected_data` 且 `selected_data_table_id` 非空
3. 对每个 selected project：按 `(项目全名, 抓取时间)` 在已选表查 record；找到则 `+record-update` 设 `已发布=True, 发布时间, 视频路径`；找不到则 log warning
4. 写 `job.lark_sync.publish_mark`

### 3.4 候选"已发过"提示（`generate_candidates` 返回前）

```python
def generate_candidates(job_id, force_refresh=True):
    result = await _generate_candidates_snapshot(job_id, job, force_refresh)
    published = _scan_published_full_names()  # 扫 JOBS_DIR
    for candidate in result["candidates"]:
        candidate["_already_published"] = candidate.get("full_name") in published
    return result
```

`_scan_published_full_names`：
- 遍历 `JOBS_DIR/*/task.json`，过滤 `status == "completed"` 且 `official_video` 非空
- 读 `selected_projects.json`，提取 `full_name` 集合
- 返回 `set[str]`

不查飞书（避免 API 依赖），仅本地。跨机器一致性放后续版本。

## 4. 前后端 schema 对齐

### 4.1 共享 ID 列表

在 [src/console/static/app.js](file:///Users/leohang/project/github-video/src/console/static/app.js) 顶部 export `LARK_SETTINGS_IDS`：

```js
const LARK_SETTINGS_IDS = [
  "larkSyncEnabled",            // 保留：总开关
  "larkBaseTokenInput",         // 保留
  "larkTableIdInput",           // 保留：旧表 ID（向后兼容展示用）
  "larkAllDataTableIdInput",    // 🆕 全量候选表
  "larkSelectedDataTableIdInput",// 🆕 已选项目表
  "larkSyncAllDataEnabled",     // 🆕 全量同步开关
  "larkSyncSelectedDataEnabled",// 🆕 已选同步开关
  "larkSyncStatus",             // 保留：状态展示
];
```

新增/删除 ID 必须同步改 [index.html](file:///Users/leohang/project/github-video/src/console/static/index.html#L480-L497) 和 `app.js`。

### 4.2 测试覆盖

在 [tests/test_console_static_app.js](file:///Users/leohang/project/github-video/tests/test_console_static_app.js) 新增：

```js
function testLarkSettingsIdsArePresentInHtml() {
  const fs = require("node:fs");
  const path = require("node:path");
  const html = fs.readFileSync(
    path.join(__dirname, "../src/console/static/index.html"),
    "utf-8",
  );
  for (const id of LARK_SETTINGS_IDS) {
    assert.match(html, new RegExp(`id="${id}"`), `index.html 缺少 id="${id}"`);
  }
}
```

### 4.3 renderLarkSettings 新签名

```js
function renderLarkSettings(lark) {
  $("larkSyncEnabled").checked = Boolean(lark.enabled);
  $("larkAllDataTableIdInput").value = lark.all_data_table_id || "";
  $("larkSelectedDataTableIdInput").value = lark.selected_data_table_id || "";
  $("larkSyncAllDataEnabled").checked = lark.sync_all_data !== false;
  $("larkSyncSelectedDataEnabled").checked = lark.sync_selected_data !== false;
  $("larkTableIdInput").value = lark.selected_data_table_id || ""; // 向后兼容
  // 状态文案分段显示
  const allDataStatus = lark.all_data_table_id ? `全量表：已配置 ${lark.all_data_table_id}` : "全量表：未配置";
  const selectedStatus = lark.selected_data_table_id ? `已选表：已配置 ${lark.selected_data_table_id}` : "已选表：未配置";
  $("larkSyncStatus").textContent = `${allDataStatus} · ${selectedStatus}`;
}
```

### 4.4 候选"已发过"徽章

`renderCandidates`（或对应的 render 入口）渲染时，对每个 `candidate._already_published == true` 的卡片，加 `class="badge-already-published"`，文案"已发过视频"。

### 4.5 任务详情"飞书同步历史"

`renderJob` / 任务详情面板加一段"飞书同步历史"，展示 `job.lark_sync.all_data` / `selected` / `publish_mark` 三段，状态为 `synced/skipped/failed/disabled`，附 `count`、`at`、`error`。

## 5. 错误处理

- 飞书写失败：try/except 包裹，错误写 `append_log` + `job.lark_sync.{segment}.error`，**不阻塞主流程**。
- `mark_published` 找不到对应 record：log warning（可能已选表同步被禁用或时机不一致），不抛错。
- 单条 record 失败：捕获后继续写下一条，错误详情进 `job.lark_sync.errors[]`（可选）。
- 批量超过 200 条：飞书 `1254104`，分批调用。
- 并发写冲突：`1254291`，批次间短暂等待 + 重试。

## 6. 测试矩阵

### 6.1 后端（`tests/test_lark_sync.py`）

| 用例 | 验证 |
|---|---|
| `test_sync_all_candidates_upserts_by_key` | 全量表按 `(项目全名, 抓取时间)` upsert，调用序列：list → create/update |
| `test_sync_selected_projects_writes_lark_records` | 已选表 upsert，字段映射（保留） |
| `test_mark_published_updates_published_flag` | `mark_published` 找到 record 后 update `已发布=True, 发布时间, 视频路径` |
| `test_mark_published_logs_warning_when_missing` | 找不到 record 时 log warning，不抛错 |
| `test_selected_sync_skips_manual_job` | `job.scheduled=False` 时 `_sync_selection_to_lark` 不调 subprocess |
| `test_selected_sync_runs_for_scheduled_job` | `job.scheduled=True` 时正常调 |
| `test_lark_config_normalize_maps_legacy_table_id` | 旧 `table_id` 读入时映射到 `selected_data_table_id` |
| `test_redacted_lark_exposes_new_fields` | `_redacted_lark` 返回值含 `all_data_table_id` / `selected_data_table_id` / `sync_all_data` / `sync_selected_data` |
| `test_scan_published_full_names_filters_completed` | `_scan_published_full_names` 只取 `status=completed` 任务的 `full_name` 集合 |

### 6.2 集成（`tests/test_lark_pipeline_integration.py`）

| 用例 | 验证 |
|---|---|
| `test_full_lark_flow_on_scheduled_job` | 模拟完整链路：拉候选 → 同步全量 → 选入 → 同步已选 → 渲染 → mark published。验证三段 lark_sync 状态都正确。 |
| `test_manual_job_skips_selected_sync` | `scheduled=False` 任务：全量表写入，但已选表/发布标记都 skipped。 |

### 6.3 前端（`tests/test_console_static_app.js`）

| 用例 | 验证 |
|---|---|
| `testLarkSettingsIdsArePresentInHtml` | `LARK_SETTINGS_IDS` 全部出现在 `index.html` |
| `testRenderLarkSettingsPopulatesNewFields` | mock 后端响应含新字段，验证 `renderLarkSettings` 正确填到 DOM |
| `testLarkPayloadFromFormCollectsNewFields` | `larkPayloadFromForm` 收集 `all_data_table_id` / `selected_data_table_id` / `sync_*` |
| `testRenderCandidateShowsAlreadyPublishedBadge` | mock `candidates[0]._already_published=true`，验证渲染含徽章 |
| `testRenderLarkSyncHistoryShowsThreeSegments` | mock `job.lark_sync` 三段，验证都渲染 |
| `testScheduleStatusSkipsSelectedSyncHint` | 调度 status 文案提及"已选表只同步调度器任务的选入" |

## 7. 不在本期范围

为保持本设计 YAGNI，下列项**不做**：

- ❌ 跨机器/重装环境的"已发过"提示一致性（需查飞书）→ 留待 v2
- ❌ 滑动窗口过滤（"过去 N 天已发过则隐藏"）→ 用户决定不做自动过滤
- ❌ 单项目/桌面审阅任务写飞书 → 这两类任务没有"候选"概念，保持现状
- ❌ 飞书写失败时通知用户 → 错误写 log + lark_sync 状态即可，UI 自行展示
- ❌ 把"已发布"反过来驱动"自动跳过候选" → 提示但不过滤
- ❌ 重新组织已选表数据迁移（保留 `table_id` → `selected_data_table_id` 兼容）

## 8. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 飞书 API 限额 / 速率限制 | batch 串行、捕获 `1254291` 重试、写入失败不阻塞主流程 |
| 拉取大候选池（30+）分批失败 | 飞书单批上限 200，30 远低于，单批即可 |
| 重复拉取导致全量表行爆炸 | upsert 键 `(项目全名, 抓取时间)`，同一天重拉只更新不新增 |
| `mark_published` 时机与 `sync_selected_projects` 顺序错位 | 同一天内 selected 同步在前、mark_published 在后；mark_published 找不到 record 时仅 log warning |
| 前端忘加 input | `testLarkSettingsIdsArePresentInHtml` 锚点测试 |
| 后端忘暴露字段 | `test_redacted_lark_exposes_new_fields` |
| 旧 `table_id` 配置被忽略 | `_normalize_lark` 兼容映射 + 单测 |
| 飞书 schema 与代码不一致 | 提供 `docs/lark_tables.md` 文档说明两张表的字段定义（手维护，本期不做 schema 自动化校验） |
