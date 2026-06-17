# 多定时任务 + 执行历史 设计文档

## 背景与目标

当前 `scheduler.json` 是**单一全局配置**：只能有一个定时计划，UI 上"定时生产"页面只是一个表单，没有任务列表概念。用户添加定时任务后看不到对应的记录条目，也无法查看每次执行的结果和卡点位置。

**目标**：
1. 支持多个独立的定时任务，每个任务有独立的频率/时间/模式/参数
2. 每个任务有独立的执行历史记录，显示：执行了没、结果如何、卡在哪个 stage
3. 向后兼容：现有单一配置自动迁移为第一个任务

## 数据模型

### `scheduler.json` 结构升级

从单一配置对象升级为包含任务列表和执行历史的结构：

```json
{
  "version": 2,
  "tasks": [
    {
      "id": "task-01J2X...",
      "name": "每日热榜草稿",
      "enabled": true,
      "mode": "candidates_only",
      "frequency": "daily",
      "time": "09:00",
      "time_window": "daily",
      "project_count": 5,
      "template_params": {"style": "tech_hotspot", "official_output_dir": "..."},
      "created_at": "2026-06-17T10:00:00",
      "last_run_date": "2026-06-17"
    }
  ],
  "runs": [
    {
      "run_id": "run-01J2X...",
      "task_id": "task-01J2X...",
      "job_id": "GH-HOTLIST-20260617-001",
      "run_key": "2026-06-17",
      "started_at": "2026-06-17T09:00:12",
      "finished_at": "2026-06-17T09:02:34",
      "status": "success",
      "stage": "awaiting_project_confirmation",
      "error": null
    }
  ]
}
```

### Task 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 任务唯一 ID（ULID 风格，`task-` 前缀） |
| `name` | string | 用户可读名称，默认从 mode+frequency 生成 |
| `enabled` | bool | 是否启用 |
| `mode` | enum | `candidates_only` / `auto_script` / `auto_video` |
| `frequency` | enum | `daily` / `weekly` |
| `time` | string | `HH:MM` 格式 |
| `time_window` | enum | `daily` / `weekly` / `monthly`（榜单窗口） |
| `project_count` | int | 5-10 |
| `template_params` | object | 视频参数 patch |
| `created_at` | string | ISO 时间戳 |
| `last_run_date` | string | 本任务上次执行的 run_key（用于去重） |

### Run 字段（执行历史）

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | string | 执行记录唯一 ID（`run-` 前缀） |
| `task_id` | string | 关联的任务 ID |
| `job_id` | string | 关联的 job ID（用于跳转） |
| `run_key` | string | 去重 key（daily=`YYYY-MM-DD`，weekly=`YYYY-Www`） |
| `started_at` | string | 开始时间 ISO |
| `finished_at` | string | 结束时间 ISO，运行中为 null |
| `status` | enum | `running` / `success` / `failed` / `cancelled` |
| `stage` | string | 最后到达的 stage（用于显示"卡在哪"） |
| `error` | string | 错误信息，成功时为 null |

### 向后兼容迁移

启动时（`ensure_storage` 或首次读取）检测 `scheduler.json`：
- 如果有 `version: 2` 字段 → 新格式，直接用
- 如果是旧格式（有 `enabled`/`mode` 顶层字段但无 `version`）→ 迁移：
  - 把旧配置转为 `tasks[0]`，生成 `id`、`name="迁移的定时计划"`、`created_at=now`
  - 旧 `last_run_date` 保留到 `tasks[0].last_run_date`
  - `runs: []`（旧格式没有历史）
  - 写回 `version: 2`

## API 设计

### GET /api/scheduler

返回完整调度状态：

```json
{
  "tasks": [...],
  "runs": [...]
}
```

`runs` 默认返回最近 50 条（按 `started_at` 倒序）。

### POST /api/scheduler/tasks

创建新任务。请求体：

```json
{
  "name": "每周热榜视频",
  "enabled": true,
  "mode": "auto_video",
  "frequency": "weekly",
  "time": "09:00",
  "time_window": "weekly",
  "project_count": 10,
  "template_params": {...}
}
```

响应：`{"task": {...}}`

### PUT /api/scheduler/tasks/{task_id}

更新任务配置（全量替换 task 字段，保留 `id`/`created_at`/`last_run_date`）。

响应：`{"task": {...}}`

### DELETE /api/scheduler/tasks/{task_id}

删除任务。同时删除该任务关联的 run 记录。

响应：`{"ok": true}`

### POST /api/scheduler/tasks/{task_id}/run

手动触发指定任务（force，绕过到期检查）。

响应（与现有 run-due 一致）：
```json
{"started": true, "reason": "forced", "job": {...}}
```

### POST /api/scheduler/run-due（保留，向后兼容）

遍历所有 enabled tasks 执行到期的任务。响应改为数组：

```json
{
  "results": [
    {"task_id": "task-xxx", "started": true, "reason": "due", "job": {...}},
    {"task_id": "task-yyy", "started": false, "reason": "not_due", "job": null}
  ]
}
```

前端"立即试跑"按钮改为调用 `POST /api/scheduler/tasks/{task_id}/run`。

## 调度器逻辑

### `start_scheduler_loop`

每 60s 调用 `run_due_scheduled_drafts()`（复数），遍历所有 enabled tasks：

```python
def run_due_scheduled_drafts(now=None, force=False) -> list[dict]:
    now = now or datetime.now()
    tasks = load_scheduler_tasks()  # 只读 enabled 的
    results = []
    for task in tasks:
        result = run_scheduled_task(task, now=now, force=force)
        results.append(result)
    return results
```

### `run_scheduled_task(task, now, force)`

单个任务的执行逻辑（从现有 `run_due_scheduled_draft` 提取）：

1. `if not force and not _is_due(task, now): return not_due`
2. `run_key = _run_key(task, now)`
3. `if task_id+run_key in _RUNNING_KEYS: return already_running`
4. 创建 run 记录（status=running, started_at=now）
5. 创建 job，执行 pipeline
6. 成功：更新 run（status=success, finished_at, stage）+ 更新 task.last_run_date
7. 失败/取消：更新 run（status=failed/cancelled, finished_at, stage, error），**不**更新 task.last_run_date

### 去重

`_RUNNING_KEYS` 从 `set[str]` 改为 `set[str]`，元素为 `f"{task_id}:{run_key}"`。

### `_is_due` / `_run_key`

改为接收 task dict（字段与旧 schedule 兼容），逻辑不变。

## UI 设计

### 定时生产页面改造

**布局**：从单一表单改为"任务列表 + 编辑表单"两态。

#### 任务列表态（默认）

```
┌─────────────────────────────────────────────────────┐
│ 定时生产                              [+ 添加任务]   │
├─────────────────────────────────────────────────────┤
│ ● 每日热榜草稿    每天 09:00  候选草稿  上次: 06-17  │
│   └ 展开 history ▼                                   │
│     06-17 09:00 ✓ success  → GH-HOTLIST-...-001     │
│     06-16 09:01 ✓ success  → GH-HOTLIST-...-002     │
│     06-15 09:00 ✗ failed   卡在 collecting_candidates│
│                       错误: GitHub rate limit        │
│                                                       │
│ ○ 每周热榜视频    每周一 09:00  正式视频  未运行     │
│   └ 展开 history ▼                                   │
│     （暂无执行记录）                                  │
└─────────────────────────────────────────────────────┘
```

每行任务卡片显示：
- 启用状态（●/○）
- 任务名称
- 频率 + 时间
- 模式标签
- 上次运行 run_key
- 展开按钮 → 显示该任务最近 10 条 run 记录
- 编辑按钮 → 切换到编辑表单态
- 删除按钮（带确认）

每条 run 记录显示：
- 时间（started_at）
- 状态图标（✓/✗/⏸）
- stage（卡在/到达的位置）
- 错误信息（失败时）
- 点击跳转到对应 job 详情

#### 编辑/添加表单态

复用现有表单字段（mode/frequency/time/window/project_count/template_params），顶部增加"任务名称"输入框。底部按钮：
- 保存（新建或更新）
- 立即试跑（仅编辑已有任务时显示）
- 取消（返回列表态）

### 前端状态管理

```javascript
state.scheduleTasks = [];      // 任务列表
state.scheduleRuns = [];       // 所有 run 记录
state.editingTaskId = null;    // 当前编辑的任务 ID，null=列表态
```

## 错误处理

1. **任务执行失败**：run 记录 status=failed，记录 error 和最后 stage，不更新 task.last_run_date（下个周期重试）
2. **任务被取消**：run 记录 status=cancelled，不更新 last_run_date
3. **服务重启恢复**：`recover_hanging_jobs` 把 running 状态的 run 记录标记为 failed（status=failed, error="服务重启时中断"），daily 任务 advance last_run_date，weekly 跳过（catch-up 窗口接管）
4. **迁移失败**：如果 scheduler.json 损坏，回退到 DEFAULT_SCHEDULER 单任务，不阻塞启动

## 测试策略

### 后端测试（`tests/test_console_scheduler.py` 扩展）

1. **迁移**：旧格式 scheduler.json → 新格式，字段保留
2. **CRUD**：创建/更新/删除任务
3. **多任务调度**：两个任务，一个 daily 一个 weekly，各自独立触发
4. **执行历史**：成功/失败/取消各产生正确的 run 记录
5. **去重**：同一 task+run_key 不重复执行
6. **恢复**：重启后 running 的 run 记录被标记 failed
7. **向后兼容**：旧 API `/api/scheduler/run-due` 仍可用

### 前端测试（`tests/test_console_static_app.js` 扩展）

1. 渲染任务列表
2. 添加任务 → 列表新增一行
3. 编辑任务 → 表单回填
4. 展开历史 → 显示 run 记录
5. 删除任务 → 列表移除

## 实现范围

### 改动文件

| 文件 | 改动 |
|---|---|
| `src/console/store.py` | `DEFAULT_SCHEDULER` 升级为 v2 结构；新增 task/run CRUD 函数；迁移逻辑 |
| `src/console/scheduler.py` | `run_due_scheduled_draft` → `run_scheduled_task`；新增 `run_due_scheduled_drafts`；run 记录写入 |
| `src/console/server.py` | 新增 task CRUD + run API 路由 |
| `src/console/static/index.html` | 定时生产页面改为列表+表单两态 |
| `src/console/static/app.js` | 任务列表渲染、CRUD、历史展开 |
| `src/console/static/styles.css` | 任务卡片、历史列表样式 |
| `tests/test_console_scheduler.py` | 多任务 + 历史 + 迁移测试 |
| `tests/test_console_jobs.py` | recovery 适配新 run 记录 |
| `tests/test_console_static_app.js` | 前端渲染测试 |
| `docs/api.md` | API 文档同步 |

### 不在范围内

- 定时任务的 cron 表达式（仍只支持 daily/weekly）
- 跨时区支持
- 任务依赖（任务 A 完成后触发任务 B）
- 邮件/通知集成
