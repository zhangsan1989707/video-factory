# 下一阶段开发路线图

## 目标

把当前视频工厂从“核心流程可用”推进到“日常稳定出片、可诊断、可扩展到多数据源栏目”的生产工具。

本路线图只排列下一阶段开发任务，不直接改变现有业务代码。执行时每次只领取一个小任务，完成后补充验收证据。

## 当前前提

- 控制台主流程已经可用：创建任务、生成候选、确认项目、生成口播、生成计划、校验、渲染、发布产物。
- GitHub 热榜与 Skills 热榜已经接入同一候选型任务流程。
- `src/console/jobs.py` 与 `src/console/static/app.js` 已经超过 2400 行，是后续维护风险最高的两个文件。
- 当前本地分支曾出现 `ahead/behind` 与未提交测试改动，后续开发前必须先确认工作区基线。

## 总体验收标准

- 每个任务都有明确测试命令或手动验收记录。
- 不把用户已有未提交改动混入新提交。
- 不在一次任务里同时做功能、重构和视觉大改。
- 优先保证真实出片链路可诊断，再扩展新数据源和新栏目。

## 阶段 0：开发基线整理

### 0.1 清理 Git 与测试基线

优先级：P0

目标：让后续开发建立在清晰的工作区和远端状态上。

执行步骤：

1. 检查 `git status --short` 与 `git status --branch --short`。
2. 明确当前未提交文件的归属：保留、提交、拆分或丢弃。
3. 明确本地分支与远端 `origin/main` 的同步方式。
4. 跑核心测试集合，记录失败项。

验收标准：

- 工作区没有来源不明的改动。
- 当前分支 ahead/behind 状态已处理或明确记录原因。
- 至少完成一次核心测试验证：

```bash
.venv/bin/python -m pytest tests/test_console_jobs.py tests/test_skills_hotlist.py -q
node --check src/console/static/app.js
git diff --check
```

参考文件：

- `tests/test_console_server_smoke.py`
- `tests/test_console_static_app.js`

## 阶段 1：出片可靠性

### 1.1 出片可靠性仪表盘

优先级：P0

目标：打开控制台后，用户能一眼判断今天能不能顺利出片，以及失败会卡在哪一层。

执行步骤：

1. 扩展现有 preflight 快照，汇总数据源、模型供应商、TTS、ffmpeg、HyperFrames、Playwright 状态。
2. 在控制台首页或设置页展示“生产链路状态”。
3. 把最近一次失败阶段、错误摘要和可重试动作展示出来。
4. 给 GitHub 与 Skills 数据源分别展示最近成功时间、缓存状态和降级原因。

验收标准：

- 未配置模型时，仪表盘明确显示“可使用模板回退”。
- GitHub Token 缺失时，能提示候选可能受限，但不误报整体不可用。
- Skills 数据源不可用但有缓存时，能显示“缓存可用”。
- 增加后端与前端测试覆盖。

参考文件：

- `src/console/preflight.py`
- `src/console/server.py`
- `src/console/static/app.js`
- `src/console/github_hotlist.py`
- `src/console/skills_hotlist.py`

### 1.2 真实短链路 E2E 验收

优先级：P1

目标：提供一条日常可跑的短验收链路，避免单元测试通过但真实出片流程断裂。

执行步骤：

1. 固定 mock 或缓存候选数据，避免依赖实时外部榜单。
2. 只生成少量候选与短计划，优先验证 preview/plan/script 产物。
3. 可选渲染 1-2 个短 shot，避免完整视频耗时过长。
4. 输出明确的阶段报告。

验收标准：

- 一条命令能在本机完成短链路验证。
- 失败时报告阶段：候选、口播、计划、预览、TTS、渲染。
- 不默认依赖真实 API key。

参考文件：

- `tests/smoke_console_render_job.py`
- `tests/test_real_e2e_smoke.py`
- `docs/e2e-manual-checklist.md`

## 阶段 2：复杂度控制

### 2.1 拆分 `src/console/jobs.py`

优先级：P1

目标：降低任务编排文件复杂度，为多数据源和多栏目继续扩展留空间。

执行步骤：

1. 保留 `jobs.py` 作为对外门面，先移动纯内部函数。
2. 拆出候选生成模块：GitHub/Skills 收集、候选分析、排序、缓存来源摘要。
3. 拆出口播模块：选择项目、feature extract、钩子、口播生成、润色。
4. 拆出计划模块：asset manifest、shot plan、preview、readiness report。
5. 拆出渲染模块：validate/render/finalize/post process。

验收标准：

- 对外导入路径和 API 行为不变。
- 每次移动一个模块，相关测试通过后再继续。
- `jobs.py` 行数明显下降，且不引入新的行为差异。

建议模块：

- `src/console/candidate_jobs.py`
- `src/console/script_jobs.py`
- `src/console/plan_jobs.py`
- `src/console/render_jobs.py`

核心验证：

```bash
.venv/bin/python -m pytest tests/test_console_jobs.py tests/test_skills_hotlist.py -q
.venv/bin/python -m py_compile src/console/jobs.py
```

### 2.2 拆分 `src/console/static/app.js`

优先级：P1

目标：让前端工作台状态、API、候选区、调度区、设置区分开维护。

执行步骤：

1. 先抽纯函数与无副作用渲染函数，不改 UI。
2. 拆出 API helper 与 state 同步逻辑。
3. 拆出候选区渲染与选择逻辑。
4. 拆出 scheduler/settings/artifacts 相关视图。
5. 暂不引入复杂构建工具，除非拆分后静态加载明显困难。

验收标准：

- 页面行为不变。
- `node --check` 通过。
- 现有前端测试继续覆盖关键纯函数。

参考文件：

- `src/console/static/app.js`
- `src/console/static/index.html`
- `tests/test_console_static_app.js`

## 阶段 3：Skills 热榜栏目化

### 3.1 Skills 热榜候选质量升级

优先级：P1

目标：让 Skills 热榜不只是能抓取，而是能稳定产出适合短视频的选题。

执行步骤：

1. 给每个 Skill 生成稳定字段：`适合谁`、`解决哪一步`、`实测看点`。
2. 在候选表显示来源、分类、推荐理由和风险。
3. 记录已做过、跳过、收藏状态，避免重复出片。
4. 增强 SkillHub 解析，减少真实数据过度依赖 ClawHub。

验收标准：

- 创建 Skills 热榜任务后，候选表能直接支持人工选题判断。
- 默认口播与模型提示词不出现 GitHub 项目语义。
- 数据源失败时能清楚显示降级或缓存状态。

参考文件：

- `src/console/skills_hotlist.py`
- `src/console/jobs.py`
- `src/console/static/app.js`
- `tests/test_skills_hotlist.py`

### 3.2 Skills 栏目发布包

优先级：P2

目标：完成视频后直接给出可发布的标题、简介、标签和评论区引导。

执行步骤：

1. 根据任务类型生成不同发布包：GitHub 热榜 / Skills 热榜。
2. 输出 3 个标题版本。
3. 输出短视频简介、标签、封面标题建议和评论引导。
4. 写入 job 目录，前端提供复制入口。

验收标准：

- 渲染完成后，产物区能复制平台发布文案。
- Skills 发布包不包含 GitHub Star 等不相关口径。
- 发布包可复现写入本地任务目录。

参考文件：

- `src/console/jobs.py`
- `src/console/static/app.js`
- `output/jobs/<job_id>/publish_pack.json`

## 阶段 4：多数据源扩展

### 4.1 统一候选数据源接口

优先级：P2

目标：为 GitHub、Skills、AI 新闻、产品榜、论文榜等数据源建立一致的最小接口。

执行步骤：

1. 明确 collector 返回结构：`items/cache_status/data_source/degraded/degraded_reason`。
2. 明确候选 item 最小字段集。
3. 让 GitHub 与 Skills 都显式适配这个接口。
4. 控制台候选流程只依赖统一字段，不依赖具体来源。

候选 item 最小字段：

```json
{
  "name": "",
  "description_zh": "",
  "source_url": "",
  "topics": [],
  "score": 0,
  "recommendation": "",
  "visual_potential": "",
  "audience": "",
  "data_source": ""
}
```

验收标准：

- 新增一个数据源时，不需要复制 job 主流程。
- 候选表、口播、计划和渲染能复用同一套逻辑。
- GitHub 与 Skills 现有行为不回退。

参考文件：

- `src/console/github_hotlist.py`
- `src/console/skills_hotlist.py`
- `src/console/jobs.py`

### 4.2 新栏目候选池

优先级：P3

目标：在 GitHub 与 Skills 稳定后，再扩展更多短视频栏目。

候选方向：

- AI 产品/工具热榜。
- AI 新闻热点。
- 论文/模型发布榜。
- A 股/科技供应链主题榜。

验收标准：

- 每个新栏目先有独立 collector 与离线测试。
- 不在首版就接入完整渲染，先验证候选质量。
- 至少产出 5 条可讲、可视化、可验证的候选。

## 暂缓事项

- 暂缓大规模 UI 重设计。当前优先级是稳定、可诊断、信息密度。
- 暂缓引入数据库。文件存储仍适合本地工具，除非出现多人协作或任务量瓶颈。
- 暂缓全自动无人值守出片。候选和口播仍应保留人工确认。
- 暂缓一次性接入大量数据源。先把 GitHub 与 Skills 两条链路做稳。

## 推荐执行顺序

1. `0.1 清理 Git 与测试基线`
2. `1.1 出片可靠性仪表盘`
3. `1.2 真实短链路 E2E 验收`
4. `2.1 拆分 jobs.py`
5. `2.2 拆分 app.js`
6. `3.1 Skills 热榜候选质量升级`
7. `3.2 Skills 栏目发布包`
8. `4.1 统一候选数据源接口`
9. `4.2 新栏目候选池`
