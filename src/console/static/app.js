const state = {
  currentJobId: "",
  currentJob: null,
  candidates: [],
  segments: [],
  qualityReport: null,
  config: null,
  pollTimer: null,
  templateStyles: [],
  _refreshInFlight: false,
};

const DEFAULT_BGM_VOLUME = 0.065;
const DEFAULT_OFFICIAL_OUTPUT_DIR = "/Users/leohang/Movies/GitHub热榜视频";

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (error) {
      data = { error: text };
    }
  }
  if (!response.ok) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

function post(path, body = {}) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

function del(path) {
  return api(path, { method: "DELETE" });
}

async function boot() {
  if (window.location.protocol === "file:") {
    document.body.insertAdjacentHTML(
      "afterbegin",
      '<div class="boot-warning">请不要直接打开 HTML 文件。请先运行 <code>.venv/bin/python -m src.console --port 8765 --open</code>，再访问 <code>http://127.0.0.1:8765</code>。</div>',
    );
    return;
  }
  bindEvents();
  await Promise.all([loadConfig(), loadPreflight(), loadJobs()]);
}

function bindEvents() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
  $("nextActionBtn").addEventListener("click", runNextAction);
  $("newJobBtn").addEventListener("click", startNewJob);
  $("confirmSelectionBtn").addEventListener("click", confirmSelection);
  $("saveScriptBtn").addEventListener("click", saveScript);
  $("regenerateCandidatesBtn").addEventListener("click", regenerateCandidates);
  $("refreshCandidatesBtn").addEventListener("click", refreshCandidates);
  $("refreshCandidatesBtn2").addEventListener("click", refreshCandidates);
  $("regenerateScriptBtn").addEventListener("click", regenerateScript);
  $("regenerateVideoBtn").addEventListener("click", regenerateVideo);
  $("cancelJobBtn").addEventListener("click", cancelCurrentJob);
  $("openScheduleBtn").addEventListener("click", openScheduleView);
  $("openScheduleSideBtn").addEventListener("click", openScheduleView);
  $("closeScheduleBtn").addEventListener("click", closeScheduleView);
  $("saveScheduleBtn").addEventListener("click", saveSchedule);
  $("runScheduleNowBtn").addEventListener("click", runScheduleNow);
  $("openSettingsBtn").addEventListener("click", openSettings);
  $("closeSettingsBtn").addEventListener("click", closeSettings);
  $("settingsOverlay").addEventListener("click", closeSettings);
  $("saveSettingsBtn").addEventListener("click", saveSettings);
  $("openScheduleFromSettingsBtn").addEventListener("click", () => {
    closeSettings();
    openScheduleView();
  });
  $("providerEditor").addEventListener("click", testProviderFromButton);
  $("openJobFolderBtn").addEventListener("click", openJobFolder);
  $("runRealSmokeBtn").addEventListener("click", runRealSmoke);
  $("jobType").addEventListener("change", syncJobTypeFields);
  $("visualStyle").addEventListener("change", syncRenderEngineForStyle);
  $("renderEngine").addEventListener("change", syncStyleForRenderEngine);
  $("scheduleVisualStyle").addEventListener("change", syncScheduleRenderEngineForStyle);
  $("scheduleRenderEngine").addEventListener("change", syncScheduleStyleForRenderEngine);
  $("projectCount").addEventListener("change", () => { if (state.candidates.length) renderCandidates(); });
  syncJobTypeFields();
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
  $(`${name}Tab`).classList.add("active");
}

async function loadConfig() {
  const config = await api("/api/config");
  state.config = config;
  const rateLimit = config.github.last_rate_limit ? ` · ${config.github.last_rate_limit}` : "";
  $("githubStatus").textContent = (config.github.configured ? `已配置 ${config.github.token_preview}` : "未配置") + rateLimit;
  $("routingStatus").textContent = providerStatusLabel(config.providers.providers || []);
  renderTemplateStyles(config.template_styles || []);
  applyTemplateParams(activeTemplateParams(config.templates || {}));
  renderSettings(config);
  renderScheduler(config.scheduler || {});
}

function providerStatusLabel(providers) {
  const available = providers.filter((provider) => provider.available).length;
  const pending = providers.filter((provider) => (provider.enabled || provider.configured) && !provider.available).length;
  if (available && pending) return `${available} 个已通过测试 · ${pending} 个待处理`;
  if (available) return `${available} 个已通过测试`;
  if (pending) return `${pending} 个待处理`;
  return "未配置模型供应商";
}

async function loadPreflight() {
  try {
    const report = await api("/api/preflight");
    const warningCount = report.warning_count || 0;
    const label = report.status === "ready"
      ? (warningCount ? `可渲染 · 警告 ${warningCount}` : "可渲染")
      : `阻塞 ${report.blocking_count || 0} · 警告 ${warningCount}`;
    $("preflightStatus").textContent = label;
    $("preflightStatus").title = report.summary || "";
    renderRealSmokeStatus(report.latest_real_smoke || {});
  } catch (error) {
    $("preflightStatus").textContent = "检测失败";
    $("preflightStatus").title = error.message;
    renderRealSmokeStatus({});
  }
}

async function runRealSmoke() {
  const button = $("runRealSmokeBtn");
  button.disabled = true;
  $("realSmokeStatus").textContent = "运行中";
  try {
    const result = await post("/api/preflight/smoke", {});
    renderRealSmokeStatus(result);
    await loadPreflight();
  } catch (error) {
    $("realSmokeStatus").textContent = "失败";
    $("realSmokeStatus").title = error.message;
  } finally {
    button.disabled = false;
  }
}

function renderRealSmokeStatus(result) {
  const node = $("realSmokeStatus");
  if (!node) return;
  const status = result.status || "";
  if (!status) {
    node.textContent = "未运行";
    node.title = "尚未手动运行低成本真实 smoke。";
    return;
  }
  const time = formatStageTime(result.completed_at || result.started_at || "");
  const labels = {
    passed: "通过",
    failed: "失败",
    running: "运行中",
  };
  node.textContent = `${labels[status] || status}${time && time !== "-" ? ` · ${time}` : ""}`;
  node.title = result.summary || result.error || "";
}

async function loadJobs() {
  const data = await api("/api/jobs");
  const list = $("historyList");
  if (!state.currentJobId) {
    updateActionState({ stage: "draft_pending", status: "draft_pending" });
  }
  if (!data.jobs.length) {
    list.className = "history-list empty";
    list.textContent = "暂无历史任务。";
    renderScheduleQueue([]);
    renderScheduleRecentJobs([]);
    return;
  }
  renderScheduleQueue(data.jobs);
  renderScheduleRecentJobs(data.jobs);
  renderHistoryJobs(data.jobs);
}

function renderScheduleQueue(jobs) {
  const box = $("scheduleQueue");
  if (!box) return;
  const items = (jobs || []).filter((job) => job.scheduled && ["awaiting_input", "failed"].includes(job.status));
  if (!items.length) {
    box.className = "history-list empty";
    box.textContent = "暂无定时待办。";
    return;
  }
  box.className = "history-list";
  box.innerHTML = items.slice(0, 5).map((job) => `
    <div class="history-item scheduled">
      <button class="history-open" data-schedule-job="${escapeAttr(job.id || "")}">
        <code>${escapeHtml(job.id || "")}</code>
        <span class="status ${escapeAttr(job.status || "")}">${escapeHtml(scheduleQueueLabel(job))}</span>
      </button>
    </div>
  `).join("");
  box.querySelectorAll("[data-schedule-job]").forEach((item) => {
    item.addEventListener("click", () => loadJob(item.dataset.scheduleJob));
  });
}

function scheduleQueueLabel(job) {
  if (job.status === "failed") {
    return `失败：${_shortUiText(job.error || job.failed_stage || "待查看", 36)}`;
  }
  if (job.stage === "awaiting_script_confirmation") return "待确认口播";
  if (job.stage === "awaiting_project_confirmation") return "待确认项目";
  return stageLabel(job.stage || "");
}

function renderScheduleRecentJobs(jobs) {
  const box = $("scheduleRecentJobs");
  if (!box) return;
  const items = (jobs || []).filter((job) => job.scheduled);
  if (!items.length) {
    box.className = "history-list empty";
    box.textContent = "暂无定时任务。";
    return;
  }
  box.className = "history-list";
  box.innerHTML = items.slice(0, 8).map((job) => `
    <div class="history-item scheduled">
      <button class="history-open" data-schedule-recent-job="${escapeAttr(job.id || "")}">
        <code>${escapeHtml(job.id || "")}</code>
        <span class="status ${escapeAttr(job.status || "")}">${escapeHtml(scheduleRecentLabel(job))}</span>
      </button>
    </div>
  `).join("");
  box.querySelectorAll("[data-schedule-recent-job]").forEach((item) => {
    item.addEventListener("click", () => {
      closeScheduleView();
      loadJob(item.dataset.scheduleRecentJob);
    });
  });
}

function scheduleRecentLabel(job) {
  const status = String(job.status || "");
  const stage = String(job.stage || "");
  const labels = {
    completed: `已完成 · ${stageLabel(stage)}`,
    failed: `失败：${_shortUiText(job.error || job.failed_stage || "待查看", 36)}`,
    running: `运行中 · ${stageLabel(stage)}`,
    awaiting_input: `待处理 · ${scheduleQueueLabel(job)}`,
  };
  return labels[status] || scheduleQueueLabel(job);
}

function renderHistoryJobs(jobs) {
  const list = $("historyList");
  list.className = "history-list";
  list.innerHTML = jobs.map((job) => `
    <div class="history-item">
      <button class="history-open" data-job="${escapeAttr(job.id || "")}">
        <code>${escapeHtml(job.id || "")}</code>
        <span class="status ${escapeAttr(job.status || "")}">${escapeHtml(job.stage || "")}</span>
      </button>
      <button class="history-delete tiny" data-delete-job="${escapeAttr(job.id || "")}" title="删除历史任务">删除</button>
    </div>
  `).join("");
  list.querySelectorAll("[data-job]").forEach((item) => {
    item.addEventListener("click", () => loadJob(item.dataset.job));
  });
  list.querySelectorAll("[data-delete-job]").forEach((item) => {
    item.addEventListener("click", () => deleteHistoryJob(item.dataset.deleteJob));
  });
}

async function loadJob(jobId) {
  const detail = await api(`/api/jobs/${jobId}`);
  state.currentJobId = jobId;
  syncDetailState(detail);
  renderJob(detail.job);
  renderCandidates();
  renderScript();
  renderQualityReport();
  renderLogs(detail.logs || "");
  renderStageTimeline(detail.stage_history || []);
  renderDiagnostics(detail);
  renderArtifactSummary(detail);
  renderArtifacts(detail.artifacts || {});
}

async function createDraft() {
  setBusy(true);
  try {
    const type = currentJobType();
    const repoNode = $("repoUrl");
    const repoUrl = repoNode ? repoNode.value.trim() : "";
    const planNode = $("planPath");
    const planPath = planNode ? planNode.value.trim() : "";
    if (jobTypeNeedsRepo(type) && !repoUrl) {
      throw new Error("请输入 GitHub 仓库 URL");
    }
    if (type === "from_plan_render" && !planPath) {
      throw new Error("请输入计划文件目录");
    }
    const created = await post("/api/jobs", {
      type,
      title: defaultJobTitle(type),
      repo_url: repoUrl,
      plan_path: planPath,
      time_window: $("timeWindow").value,
      project_count: Number($("projectCount").value),
      template: "github_hotlist_vertical_v1",
      template_params: currentTemplateParams(),
    });
    state.currentJobId = created.job.id;
    state.candidates = [];
    state.segments = [];
    state.qualityReport = null;
    renderJob(created.job);
    renderCandidates();
    renderScript();
    renderQualityReport();
    renderLogs(createdJobMessage(type));
    await loadJobs();
  } catch (error) {
    alert(error.message);
  } finally {
    setBusy(false);
  }
}

function startNewJob() {
  stopPollingCurrentJob();
  clearCurrentJob();
  switchTab("candidates");
  syncJobTypeFields();
  renderLogs(currentJobType() === "single_project_vertical"
    ? "已准备单项目任务。请输入仓库 URL，然后点击“创建任务”。\n"
    : currentJobType() === "desktop_review"
      ? "已准备桌面审阅任务。请输入仓库 URL，然后点击“创建任务”。\n"
      : currentJobType() === "from_plan_render"
        ? "已准备计划文件继续渲染任务。请输入计划目录，然后点击“创建任务”。\n"
    : "已准备新任务。请选择时间维度和项目数，然后点击“创建任务”。\n");
  const focusTarget = jobTypeNeedsRepo(currentJobType()) ? $("repoUrl") : currentJobType() === "from_plan_render" ? $("planPath") : $("timeWindow");
  if (focusTarget && typeof focusTarget.focus === "function") focusTarget.focus();
}

async function deleteHistoryJob(jobId) {
  if (!jobId) return;
  if (!confirmDelete(`删除历史任务 ${jobId}？对应产物目录也会一并删除。`)) return;
  setBusy(true);
  try {
    await del(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (state.currentJobId === jobId) clearCurrentJob();
    await loadJobs();
  } catch (error) {
    alert(error.message);
  } finally {
    setBusy(false);
  }
}

function confirmDelete(message) {
  return typeof window === "undefined" || typeof window.confirm !== "function" || window.confirm(message);
}

function isBackgroundStart(result) {
  return Boolean(result && result.started);
}

function hasBackgroundWork(job) {
  return Boolean(job && (job.active || job.status === "running"));
}

function autoTabForCompletedBackground(job) {
  const stage = job && job.stage;
  if (stage === "awaiting_project_confirmation") return "candidates";
  if (stage === "awaiting_script_confirmation") return "script";
  return "";
}

function clearCurrentJob() {
  state.currentJobId = "";
  state.currentJob = null;
  state.candidates = [];
  state.segments = [];
  state.qualityReport = null;
  $("currentJobId").textContent = "未创建";
  $("currentStage").textContent = "等待创建任务";
  $("currentModelCall").textContent = "model: -";
  $("openJobFolderBtn").disabled = true;
  $("cancelJobBtn").disabled = true;
  $("cancelJobBtn").textContent = "取消任务";
  renderJobError("");
  renderDiagnostics({});
  renderCandidates();
  renderScript();
  renderLogs("");
  renderStageTimeline([]);
  renderArtifactSummary({});
  renderPublishActions({});
  renderArtifacts({});
  updateActionState({ stage: "draft_pending", status: "draft_pending" });
}

async function collectCandidatesForCurrentJob() {
  if (!state.currentJobId) {
    alert("请先创建任务");
    return;
  }
  setBusy(true);
  try {
    switchTab("progress");
    appendLogLine("正在重新拉取候选项目...");
    startPollingCurrentJob();
    const result = await post(`/api/jobs/${state.currentJobId}/candidates`);
    renderJob(result.job);
    await refreshCurrentJob();
    await loadJobs();
    if (!isBackgroundStart(result)) switchTab("candidates");
  } catch (error) {
    alert(error.message);
    await refreshCurrentJob();
  } finally {
    setBusy(false);
  }
}

async function regenerateCandidates() {
  if (!state.currentJobId) {
    alert("请先创建任务");
    return;
  }
  if (!confirmRegenerate("重新生成候选项目会清除已选项目、口播脚本、计划文件和视频产物。继续吗？")) return;
  setBusy(true);
  try {
    switchTab("progress");
    appendLogLine("正在重新生成候选项目...");
    startPollingCurrentJob();
    const result = await post(`/api/jobs/${state.currentJobId}/regenerate-candidates`);
    state.segments = [];
    state.qualityReport = null;
    renderJob(result.job);
    renderScript();
    await refreshCurrentJob();
    await loadJobs();
    if (!isBackgroundStart(result)) switchTab("candidates");
  } catch (error) {
    alert(error.message);
    await refreshCurrentJob();
  } finally {
    setBusy(false);
  }
}

async function refreshCandidates() {
  if (!state.currentJobId) {
    alert("请先创建任务");
    return;
  }
  if (!confirm("将跳过缓存，直接从 GitHub API 拉取最新候选数据。已选项目和口播不会被清除。继续吗？")) return;
  setBusy(true);
  try {
    switchTab("progress");
    appendLogLine("正在跳过缓存，刷新候选数据...");
    startPollingCurrentJob();
    const result = await post(`/api/jobs/${state.currentJobId}/refresh-candidates`);
    renderJob(result.job);
    await refreshCurrentJob();
    await loadJobs();
    if (!isBackgroundStart(result)) switchTab("candidates");
  } catch (error) {
    alert(error.message);
    await refreshCurrentJob();
  } finally {
    setBusy(false);
  }
}

async function confirmSelection() {
  if (!state.currentJobId) {
    alert("请先生成候选草稿");
    return;
  }
  const selected = selectedCandidates();
  if (!selected.length) {
    alert("请至少选择一个项目");
    return;
  }
  setBusy(true);
  try {
    switchTab("progress");
    appendLogLine("正在生成口播脚本...");
    startPollingCurrentJob();
    const result = await post(`/api/jobs/${state.currentJobId}/selection`, { items: selected });
    renderJob(result.job);
    await refreshCurrentJob();
    if (!isBackgroundStart(result)) switchTab("script");
  } catch (error) {
    alert(error.message);
  } finally {
    setBusy(false);
  }
}

async function regenerateScript() {
  if (!state.currentJobId) {
    alert("请先创建任务");
    return;
  }
  if (!confirmRegenerate("重新生成口播脚本会清除已确认口播后的计划文件和视频产物。继续吗？")) return;
  setBusy(true);
  try {
    switchTab("progress");
    appendLogLine("正在重新生成口播脚本...");
    startPollingCurrentJob();
    const result = await post(`/api/jobs/${state.currentJobId}/regenerate-script`);
    state.qualityReport = null;
    renderJob(result.job);
    await refreshCurrentJob();
    if (!isBackgroundStart(result)) switchTab("script");
  } catch (error) {
    alert(error.message);
    await refreshCurrentJob();
  } finally {
    setBusy(false);
  }
}

async function saveScript() {
  if (!state.currentJobId) {
    alert("请先创建任务");
    return;
  }
  const segments = [...document.querySelectorAll("[data-segment-id]")].map((node) => ({
    id: node.dataset.segmentId,
    label: node.querySelector("label").textContent,
    text: node.querySelector("textarea").value.trim(),
  }));
  const ignoreQualityRisk = qualityBlocksRender(state.qualityReport) && confirmQualityOverride(state.qualityReport);
  setBusy(true);
  try {
    switchTab("progress");
    appendLogLine("正在确认口播并执行质检...");
    startPollingCurrentJob();
    const result = await post(`/api/jobs/${state.currentJobId}/script`, {
      segments,
      ignore_quality_risk: ignoreQualityRisk,
    });
    renderJob(result.job);
    await refreshCurrentJob();
  } catch (error) {
    alert(error.message);
  } finally {
    setBusy(false);
  }
}

async function preparePlan() {
  if (!state.currentJobId) {
    alert("请先创建任务");
    return;
  }
  setBusy(true);
  try {
    switchTab("progress");
    appendLogLine("正在生成计划文件...");
    startPollingCurrentJob();
    const prepared = await post(`/api/jobs/${state.currentJobId}/prepare-plan`);
    renderJob(prepared.job);
    await refreshCurrentJob();
  } catch (error) {
    alert(error.message);
    await refreshCurrentJob();
  } finally {
    setBusy(false);
  }
}

async function validatePlan() {
  if (!state.currentJobId) {
    alert("请先创建任务");
    return;
  }
  setBusy(true);
  try {
    switchTab("progress");
    appendLogLine("正在校验计划文件...");
    startPollingCurrentJob();
    const validated = await post(`/api/jobs/${state.currentJobId}/validate-plan`);
    renderJob(validated.job);
    await refreshCurrentJob();
  } catch (error) {
    alert(error.message);
    await refreshCurrentJob();
  } finally {
    setBusy(false);
  }
}

async function renderVideo() {
  if (!state.currentJobId) {
    alert("请先创建任务");
    return;
  }
  setBusy(true);
  try {
    switchTab("progress");
    appendLogLine("正在生成最终视频，请不要关闭控制台...");
    const result = await post(`/api/jobs/${state.currentJobId}/render-video`);
    renderJob(result.job);
    await refreshCurrentJob();
    startPollingCurrentJob();
  } catch (error) {
    alert(error.message);
    await refreshCurrentJob();
  } finally {
    setBusy(false);
  }
}

async function regenerateVideo() {
  if (!state.currentJobId) {
    alert("请先创建任务");
    return;
  }
  if (!confirmRegenerate("重新生成最终视频会清除当前 final.mp4，保留历史正式视频版本、项目与口播脚本。继续吗？")) return;
  setBusy(true);
  try {
    switchTab("progress");
    appendLogLine("正在重新生成最终视频，请不要关闭控制台...");
    const result = await post(`/api/jobs/${state.currentJobId}/regenerate-video`);
    renderJob(result.job);
    await refreshCurrentJob();
    startPollingCurrentJob();
  } catch (error) {
    alert(error.message);
    await refreshCurrentJob();
  } finally {
    setBusy(false);
  }
}

async function cancelCurrentJob() {
  if (!state.currentJobId) {
    alert("请先创建任务");
    return;
  }
  if (!confirmRegenerate("取消当前运行中的任务？系统会在下一个安全检查点停止。")) return;
  setBusy(true);
  try {
    switchTab("progress");
    appendLogLine("已请求取消当前任务...");
    const result = await post(`/api/jobs/${state.currentJobId}/cancel`);
    renderJob(result.job);
    await refreshCurrentJob();
    startPollingCurrentJob();
  } catch (error) {
    alert(error.message);
    await refreshCurrentJob();
  } finally {
    setBusy(false);
  }
}

function confirmRegenerate(message) {
  return typeof window === "undefined" || typeof window.confirm !== "function" || window.confirm(message);
}

async function runNextAction() {
  const stage = $("nextActionBtn").dataset.action;
  if (stage === "create") return createDraft();
  if (stage === "collect-candidates") return collectCandidatesForCurrentJob();
  if (stage === "confirm-selection") return confirmSelection();
  if (stage === "confirm-script") return saveScript();
  if (stage === "prepare-plan") return preparePlan();
  if (stage === "validate-plan") return validatePlan();
  if (stage === "render-video") return renderVideo();
}

async function refreshCurrentJob() {
  if (!state.currentJobId || state._refreshInFlight) return;
  state._refreshInFlight = true;
  try {
    const wasPolling = Boolean(state.pollTimer);
    const detail = await api(`/api/jobs/${state.currentJobId}`);
    syncDetailState(detail);
    renderJob(detail.job);
    renderCandidates();
    renderScript();
    renderQualityReport();
    renderLogs(detail.logs || "");
    renderStageTimeline(detail.stage_history || []);
    renderDiagnostics(detail);
    renderArtifactSummary(detail);
    renderPublishActions(detail);
    renderArtifacts(detail.artifacts || {});
    if (detail.job && !hasBackgroundWork(detail.job)) {
      const nextTab = wasPolling ? autoTabForCompletedBackground(detail.job) : "";
      stopPollingCurrentJob();
      if (wasPolling) await loadJobs();
      if (nextTab) switchTab(nextTab);
    }
  } finally {
    state._refreshInFlight = false;
  }
}

function syncDetailState(detail) {
  state.candidates = (detail.candidates || []).map((item) => {
    const { selected, ...rest } = item;
    return rest;
  });
  state.segments = detail.segments || [];
  state.qualityReport = detail.quality_report || null;
}

function startPollingCurrentJob() {
  stopPollingCurrentJob();
  state.pollTimer = window.setInterval(() => {
    refreshCurrentJob().catch((error) => {
      console.error(error);
      stopPollingCurrentJob();
    });
  }, 2000);
}

function stopPollingCurrentJob() {
  if (!state.pollTimer) return;
  window.clearInterval(state.pollTimer);
  state.pollTimer = null;
}

function renderJob(job) {
  if (!job) return;
  state.currentJob = job;
  $("currentJobId").textContent = job.id || "未创建";
  $("currentStage").textContent = job.stage || "未知阶段";
  if (job.type && $("jobType")) $("jobType").value = String(job.type);
  if (job.repo_url && $("repoUrl")) $("repoUrl").value = String(job.repo_url);
  if (job.plan_path && $("planPath")) $("planPath").value = String(job.plan_path);
  if (job.time_window) $("timeWindow").value = String(job.time_window);
  if (job.project_count) $("projectCount").value = String(job.project_count);
  syncJobTypeFields();
  $("openJobFolderBtn").disabled = !job.id;
  renderModelCall(job.model_calls || []);
  renderCandidateSourceSummary(job.candidate_source || {});
  renderNarrationSourceSummary(job.narration_source || {});
  renderJobError(job.error || "");
  renderRecoveryHint(job);
  if (job.status !== "failed") renderDiagnostics({});
  if (Array.isArray(job.stage_history)) renderStageTimeline(job.stage_history);
  applyTemplateParams(job.template_params || {});
  updateActionState(job);
}

function renderModelCall(calls) {
  const latest = calls.length ? calls[calls.length - 1] : null;
  const source = (state.currentJob && state.currentJob.narration_source) || {};
  const narration = narrationSourceLabel(source);
  const model = latest
    ? `model: ${latest.task} · ${latest.provider || "-"} / ${latest.model || "-"} · ${latest.status}`
    : "model: -";
  $("currentModelCall").textContent = narration ? `${model} · ${narration}` : model;
}

function narrationSourceLabel(source) {
  const status = source.status || "";
  if (!status) return "";
  const provider = source.provider || "-";
  const model = source.model || "-";
  const reason = source.reason ? ` (${_shortUiText(source.reason, 60)})` : "";
  if (status === "ai_success") return `口播: AI ${provider} / ${model}`;
  if (status === "model_skipped") return `口播: 模型跳过后模板回退${reason}`;
  if (status === "ai_failed_fallback") return `口播: AI失败后模板回退${reason}`;
  return `口播: ${status}`;
}

function candidateSourceLabel(source) {
  if (!source || !Object.keys(source).length) return "候选来源：待生成。";
  return `候选来源：${source.summary || "待生成。"}`;
}

function renderCandidateSourceSummary(source) {
  const node = $("candidateSourceSummary");
  if (!node) return;
  node.textContent = candidateSourceLabel(source);
}

function renderNarrationSourceSummary(source) {
  const node = $("narrationSourceSummary");
  if (!node) return;
  const label = narrationSourceLabel(source || {});
  node.textContent = label || "口播来源：待生成。";
}

async function openJobFolder() {
  if (!state.currentJobId) return;
  try {
    await post(`/api/jobs/${state.currentJobId}/open-folder`);
  } catch (error) {
    alert(error.message);
  }
}

function renderJobError(message) {
  const errorBox = $("currentError");
  const text = String(message || "").trim();
  errorBox.hidden = !text;
  errorBox.textContent = text ? _shortUiText(text, 180) : "";
}

function renderRecoveryHint(job) {
  const box = $("recoveryHint");
  if (!box) return;
  const hint = recoveryHintForJob(job || {});
  box.hidden = !hint;
  box.textContent = hint;
}

function recoveryHintForJob(job) {
  if (!job || job.status !== "failed") return "";
  const stage = job.failed_stage || job.stage || "";
  const labels = {
    collecting_candidates: "候选拉取失败。建议检查 GitHub Token/网络后点击“重试：拉取候选”。",
    analyzing_candidates: "候选分析失败。可以直接重试候选生成；模型不可用时会回退到启发式结果。",
    generating_script: "口播生成失败。建议回到候选项目，重新确认项目生成口播。",
    awaiting_script_confirmation: "口播确认失败。请检查质检风险或缩短异常段落后再次确认。",
    preparing_plan: "计划生成或校验失败。建议先重新生成计划文件；如果是计划目录任务，请确认目录含有效 JSON。",
    capturing_assets: "素材采集失败。建议检查 Playwright/网络后点击“重试：采集素材”。",
    generating_tts: "语音生成失败。建议检查 Edge TTS 网络后点击“重试：生成语音”。",
    composing_video: "视频合成失败。建议检查 ffmpeg、BGM 路径和磁盘空间后重试渲染。",
    composing_html: "HTML 画面生成失败。建议检查 Node/HyperFrames 后重试渲染。",
    rendering_hyperframes: "HyperFrames 渲染失败。建议运行真实 smoke 或 npm install 后重试渲染。",
    mixing_audio: "音频混合失败。建议检查 ffmpeg 和 BGM 设置后重试渲染。",
    post_processing: "后处理失败。建议检查 ffmpeg、BGM 路径和输出目录权限后重试渲染。",
  };
  return labels[stage] || "任务失败。请查看 last_logs，并从当前主按钮或重生成按钮继续。";
}

function renderDiagnostics(detail) {
  const box = $("currentDiagnostics");
  const job = detail.job || {};
  const failedStage = detail.failed_stage || job.failed_stage || "";
  const latestModelCall = detail.latest_model_call || {};
  const tail = String(detail.log_tail || "").trim();
  const shouldShow = job.status === "failed" || Boolean(failedStage);
  box.hidden = !shouldShow;
  if (!shouldShow) {
    box.textContent = "";
    return;
  }
  const lines = [];
  if (failedStage) lines.push(`failed_stage: ${failedStage}`);
  if (latestModelCall.task || latestModelCall.provider || latestModelCall.model) {
    lines.push(`model_call: ${latestModelCall.task || "-"} · ${latestModelCall.provider || "-"} / ${latestModelCall.model || "-"} · ${latestModelCall.status || "-"}`);
  }
  if (latestModelCall.error) lines.push(`model_error: ${_shortUiText(latestModelCall.error, 180)}`);
  if (tail) lines.push("last_logs:", tail);
  box.textContent = lines.join("\n");
}

function templateParamNodes(prefix = "") {
  if (!prefix) {
    return {
      visualStyle: $("visualStyle"),
      renderEngine: $("renderEngine"),
      subtitleMode: $("subtitleMode"),
      tone: $("tone"),
      bgmMode: $("bgmMode"),
      bgmVolume: $("bgmVolume"),
      bgmPath: $("bgmPath"),
      officialOutputDir: $("officialOutputDir"),
      issueNumber: $("issueNumber"),
    };
  }
  return {
    visualStyle: $(`${prefix}VisualStyle`),
    renderEngine: $(`${prefix}RenderEngine`),
    subtitleMode: $(`${prefix}SubtitleMode`),
    tone: prefix ? $(`${prefix}Tone`) : $("tone"),
    bgmMode: $(`${prefix}BgmMode`),
    bgmVolume: $(`${prefix}BgmVolume`),
    bgmPath: $(`${prefix}BgmPath`),
    officialOutputDir: prefix ? $(`${prefix}OfficialOutputDir`) : null,
    issueNumber: prefix ? null : $("issueNumber"),
  };
}

function currentTemplateParams(prefix = "") {
  const nodes = templateParamNodes(prefix);
  const issueInput = nodes.issueNumber;
  const issueVal = issueInput && issueInput.value.trim() ? Number(issueInput.value) : null;
  const officialOutputDir = nodes.officialOutputDir ? (nodes.officialOutputDir.value.trim() || DEFAULT_OFFICIAL_OUTPUT_DIR) : DEFAULT_OFFICIAL_OUTPUT_DIR;
  return {
    style: nodes.visualStyle.value,
    render_engine: nodes.renderEngine.value,
    subtitle_mode: nodes.subtitleMode.value,
    narration_tone: nodes.tone.value,
    bgm: nodes.bgmMode.value,
    bgm_volume: normalizedBgmVolume(undefined, prefix),
    bgm_path: nodes.bgmPath.value.trim(),
    official_output_dir: officialOutputDir,
    issue_number: issueVal,
  };
}

function normalizedBgmVolume(value, prefix = "") {
  const node = templateParamNodes(prefix).bgmVolume;
  const raw = value != null ? value : (node ? node.value : DEFAULT_BGM_VOLUME);
  const number = Number(raw);
  if (!Number.isFinite(number)) return DEFAULT_BGM_VOLUME;
  return Math.min(1, Math.max(0, number));
}

function setBgmVolume(value, prefix = "") {
  const node = templateParamNodes(prefix).bgmVolume;
  if (!node) return;
  node.value = normalizedBgmVolume(value, prefix).toFixed(2);
}

function applyTemplateParams(params, prefix = "") {
  const nodes = templateParamNodes(prefix);
  if (params.visual_style) nodes.visualStyle.value = params.visual_style;
  if (params.style) nodes.visualStyle.value = params.style;
  if (params.render_engine) nodes.renderEngine.value = params.render_engine;
  if (!params.render_engine) {
    if (prefix) syncScheduleRenderEngineForStyle();
    else syncRenderEngineForStyle();
  }
  if (params.subtitle_mode) nodes.subtitleMode.value = params.subtitle_mode;
  if (params.narration_tone) nodes.tone.value = params.narration_tone;
  if (params.bgm) nodes.bgmMode.value = params.bgm;
  setBgmVolume(params.bgm_volume, prefix);
  nodes.bgmPath.value = params.bgm_path || "";
  if (nodes.officialOutputDir) nodes.officialOutputDir.value = params.official_output_dir || DEFAULT_OFFICIAL_OUTPUT_DIR;
  const issueInput = nodes.issueNumber;
  if (issueInput) issueInput.value = params.issue_number != null ? params.issue_number : "";
}

function syncRenderEngineForStyle() {
  const style = state.templateStyles.find((item) => item.style === $("visualStyle").value);
  if (style && style.render_engine) $("renderEngine").value = style.render_engine;
}

function syncStyleForRenderEngine() {
  if ($("renderEngine").value !== "hyperframes") return;
  const current = state.templateStyles.find((item) => item.style === $("visualStyle").value);
  if (!current || current.render_engine !== "hyperframes") {
    const fallback = state.templateStyles.find((item) => item.render_engine === "hyperframes");
    if (fallback) $("visualStyle").value = fallback.style;
  }
}

function syncScheduleRenderEngineForStyle() {
  const style = state.templateStyles.find((item) => item.style === $("scheduleVisualStyle").value);
  if (style && style.render_engine) $("scheduleRenderEngine").value = style.render_engine;
}

function syncScheduleStyleForRenderEngine() {
  if ($("scheduleRenderEngine").value !== "hyperframes") return;
  const current = state.templateStyles.find((item) => item.style === $("scheduleVisualStyle").value);
  if (!current || current.render_engine !== "hyperframes") {
    const fallback = state.templateStyles.find((item) => item.render_engine === "hyperframes");
    if (fallback) $("scheduleVisualStyle").value = fallback.style;
  }
}

function renderTemplateStyles(styles) {
  state.templateStyles = Array.isArray(styles) ? styles : [];
  if (!state.templateStyles.length) return;
  const selected = $("visualStyle").value;
  $("visualStyle").innerHTML = state.templateStyles
    .map((item) => `<option value="${escapeAttr(item.style)}">${escapeHtml(item.label || item.style)}</option>`)
    .join("");
  if (state.templateStyles.some((item) => item.style === selected)) $("visualStyle").value = selected;
  const scheduleStyle = $("scheduleVisualStyle");
  if (scheduleStyle) {
    const scheduleSelected = scheduleStyle.value;
    scheduleStyle.innerHTML = $("visualStyle").innerHTML;
    if (state.templateStyles.some((item) => item.style === scheduleSelected)) scheduleStyle.value = scheduleSelected;
  }
}

function activeTemplateParams(templates) {
  const active = templates.active_template || "github_hotlist_vertical_v1";
  return templates[active] || {};
}

function templatePayload(current) {
  const templates = current.templates || {};
  const active = templates.active_template || "github_hotlist_vertical_v1";
  const params = currentTemplateParams();
  return {
    ...templates,
    active_template: active,
    [active]: {
      ...(templates[active] || {}),
      project_count: Number($("projectCount").value),
      style: params.style,
      render_engine: params.render_engine,
      subtitle_mode: params.subtitle_mode,
      bgm: params.bgm,
      bgm_volume: params.bgm_volume,
      bgm_path: params.bgm_path,
      official_output_dir: params.official_output_dir,
      narration_tone: params.narration_tone,
      orientation: "vertical",
    },
  };
}

function updateActionState(job) {
  const button = $("nextActionBtn");
  const confirmSelection = $("confirmSelectionBtn");
  const saveScriptButton = $("saveScriptBtn");
  const { label, action, disabled } = nextActionForJob(job);

  button.textContent = label;
  button.dataset.action = action;
  button.disabled = disabled;
  confirmSelection.textContent = "确认项目并生成口播";
  updateSelectionState();
  saveScriptButton.textContent = "确认口播并进入出片";
  saveScriptButton.disabled = action !== "confirm-script";
  updateRegenerateActions(job);
}

function updateRegenerateActions(job) {
  const candidatesButton = $("regenerateCandidatesBtn");
  const scriptButton = $("regenerateScriptBtn");
  const videoButton = $("regenerateVideoBtn");
  const cancelButton = $("cancelJobBtn");
  const refreshBtn = $("refreshCandidatesBtn");
  const refreshBtn2 = $("refreshCandidatesBtn2");
  if (!candidatesButton || !scriptButton || !videoButton || !cancelButton) return;
  const stage = job.stage || "draft_pending";
  const status = job.status || "";
  const type = job.type || "github_hotlist";
  const hasJob = Boolean(job.id);
  const isRunning = hasBackgroundWork(job);
  if (type !== "github_hotlist") {
    candidatesButton.disabled = true;
    scriptButton.disabled = true;
    videoButton.disabled = !hasJob || isRunning || !["ready_to_render", "completed", "failed"].includes(status);
    cancelButton.disabled = !hasJob || !isRunning || Boolean(job.cancel_requested);
    cancelButton.textContent = job.cancel_requested ? "取消中" : "取消任务";
    if (refreshBtn) refreshBtn.disabled = true;
    if (refreshBtn2) refreshBtn2.disabled = true;
    return;
  }
  const hasSelection = !["draft_pending", "collecting_candidates", "analyzing_candidates", "awaiting_project_confirmation"].includes(stage);
  const hasScript = hasSelection && !["generating_script", "awaiting_script_confirmation"].includes(stage);
  const canRefreshCandidates = hasJob && !isRunning &&
    ["draft_pending", "collecting_candidates", "analyzing_candidates", "awaiting_project_confirmation"].includes(stage);
  candidatesButton.disabled = !hasJob || isRunning;
  scriptButton.disabled = !hasJob || isRunning || !hasSelection;
  videoButton.disabled = !hasJob || isRunning || !hasScript;
  cancelButton.disabled = !hasJob || !isRunning || Boolean(job.cancel_requested);
  cancelButton.textContent = job.cancel_requested ? "取消中" : "取消任务";
  if (refreshBtn) refreshBtn.disabled = !canRefreshCandidates;
  if (refreshBtn2) refreshBtn2.disabled = !canRefreshCandidates;
}

function nextActionForJob(job) {
  const stage = job.stage || "draft_pending";
  const status = job.status || "";
  if (hasBackgroundWork(job)) {
    return { label: "任务执行中", action: "running", disabled: true };
  }
  if (stage === "awaiting_project_confirmation") {
    return { label: "确认项目并生成口播", action: "confirm-selection", disabled: false };
  }
  if (stage === "awaiting_script_confirmation") {
    return { label: "确认口播并进入出片", action: "confirm-script", disabled: false };
  }
  if (stage === "preparing_plan" && status === "awaiting_render") {
    return { label: "生成计划文件", action: "prepare-plan", disabled: false };
  }
  if (stage === "preparing_plan" && status === "awaiting_validation") {
    return { label: "校验计划文件", action: "validate-plan", disabled: false };
  }
  if (status === "ready_to_render") {
    return { label: "生成最终视频（耗时）", action: "render-video", disabled: false };
  }
  if (status === "completed") {
    return { label: "已完成", action: "completed", disabled: true };
  }
  if (status === "failed") {
    const retryActions = {
      collecting_candidates: "collect-candidates",
      analyzing_candidates: "collect-candidates",
      generating_script: "confirm-selection",
      preparing_plan: "prepare-plan",
      capturing_assets: "render-video",
      generating_tts: "render-video",
      composing_video: "render-video",
      composing_html: "render-video",
      rendering_hyperframes: "render-video",
      mixing_audio: "render-video",
      post_processing: "render-video",
    };
    const retryAction = retryActions[stage];
    return retryAction
      ? { label: `重试：${stageLabel(stage)}`, action: retryAction, disabled: false }
      : { label: "无法自动重试", action: "failed", disabled: true };
  }
  if (stage === "draft_pending" && job.id) {
    return { label: "生成候选草稿", action: "collect-candidates", disabled: false };
  }
  return { label: "创建任务", action: "create", disabled: false };
}

function renderCandidates() {
  const body = $("candidateRows");
  renderCandidateSourceSummary((state.currentJob && state.currentJob.candidate_source) || {});
  if (!state.candidates.length) {
    body.innerHTML = `<tr><td colspan="8" class="empty">${escapeHtml(candidateEmptyMessage())}</td></tr>`;
    return;
  }
  const prevChecked = _snapshotCheckboxState();
  const prevOrders = _snapshotOrderState();
  body.innerHTML = state.candidates.map((item, index) => `
    <tr>
      <td><input type="checkbox" data-index="${index}" ${candidateChecked(item, index) ? "checked" : ""}></td>
      <td><input class="order-input" type="number" min="1" max="30" data-order-index="${index}" value="${candidateOrder(item, index)}" aria-label="选择顺序"></td>
      <td>
        <strong>${escapeHtml(item.full_name || item.name)}</strong>
        <small>${escapeHtml(item.description_zh || "需要打开仓库确认用途")}</small>
        <small class="source-desc">${escapeHtml(item.description || "无英文描述")}</small>
      </td>
      <td class="score">${item.score}</td>
      <td>${Number(item.stars || 0).toLocaleString()}<small class="source-desc">${escapeHtml(item.daily_growth || "估算日均 star 暂无")}</small></td>
      <td>${escapeHtml(item.language || "-")}</td>
      <td>${escapeHtml(publicCandidateText(item.recommendation || ""))}<small>${escapeHtml(publicCandidateText(item.ranking_reason || item.visual_potential || ""))}</small></td>
      <td>${escapeHtml(item.risk || "")}</td>
    </tr>
  `).join("");
  _restoreCheckboxState(prevChecked);
  _restoreOrderState(prevOrders);
  body.querySelectorAll("input[type='checkbox'], .order-input").forEach((input) => {
    input.addEventListener("input", updateSelectionState);
    input.addEventListener("change", updateSelectionState);
  });
  updateSelectionState();
}

function publicCandidateText(value) {
  return String(value || "")
    .replace(/标签完善[，,、。；;]?\s*/g, "")
    .replace(/信息待补充[，,、。；;]?\s*/g, "")
    .replace(/可用标签和/g, "可用")
    .trim();
}


function _snapshotCheckboxState() {
  const map = {};
  document.querySelectorAll("#candidateRows input[type='checkbox']").forEach((input) => {
    const key = _candidateRowKey(Number(input.dataset.index));
    if (key) map[key] = input.checked;
  });
  return map;
}

function _snapshotOrderState() {
  const map = {};
  document.querySelectorAll("#candidateRows .order-input").forEach((input) => {
    const key = _candidateRowKey(Number(input.dataset.orderIndex));
    if (key) map[key] = input.value;
  });
  return map;
}

function _restoreCheckboxState(snapshot) {
  if (!snapshot || !Object.keys(snapshot).length) return;
  document.querySelectorAll("#candidateRows input[type='checkbox']").forEach((input) => {
    const key = _candidateRowKey(Number(input.dataset.index));
    if (key && key in snapshot) input.checked = snapshot[key];
  });
}

function _restoreOrderState(snapshot) {
  if (!snapshot || !Object.keys(snapshot).length) return;
  document.querySelectorAll("#candidateRows .order-input").forEach((input) => {
    const key = _candidateRowKey(Number(input.dataset.orderIndex));
    if (key && key in snapshot) input.value = snapshot[key];
  });
}

function _candidateRowKey(index) {
  const item = state.candidates[index];
  return item ? (item.full_name || item.name || item.repo_url || "") : "";
}

function candidateEmptyMessage() {
  const type = state.currentJob && state.currentJob.type;
  if (type === "single_project_vertical") {
    return "单项目竖屏任务不需要候选列表。生成计划文件后会进入口播确认。";
  }
  if (type === "desktop_review") {
    return "桌面审阅任务不需要候选列表。点击“生成计划文件”准备桌面分镜。";
  }
  if (type === "from_plan_render") {
    return "计划文件继续渲染任务不需要候选列表。点击“生成计划文件”导入计划快照。";
  }
  return state.currentJobId
    ? "任务已创建。点击“生成候选草稿”拉取候选项目。"
    : "还没有任务。先选择时间维度和项目数，再点击“创建任务”。";
}

function currentJobType() {
  const node = $("jobType");
  return node && node.value ? node.value : "github_hotlist";
}

function jobTypeNeedsRepo(type) {
  return type === "single_project_vertical" || type === "desktop_review";
}

function defaultJobTitle(type) {
  const titles = {
    single_project_vertical: "单项目竖屏视频",
    desktop_review: "桌面审阅视频",
    from_plan_render: "计划文件继续渲染",
  };
  return titles[type] || "GitHub 热榜视频";
}

function createdJobMessage(type) {
  if (type === "single_project_vertical") return "单项目竖屏任务已创建。点击“生成计划文件”准备分镜和脚本。\n";
  if (type === "desktop_review") return "桌面审阅任务已创建。点击“生成计划文件”准备桌面分镜。\n";
  if (type === "from_plan_render") return "计划文件继续渲染任务已创建。点击“生成计划文件”导入计划快照。\n";
  return "任务已按当前时间维度和项目数创建。点击“生成候选草稿”拉取候选项目。\n";
}

function syncJobTypeFields() {
  const type = currentJobType();
  const repoField = $("repoUrlField");
  const planField = $("planPathField");
  const timeField = $("timeWindow") && $("timeWindow").parentElement;
  const countField = $("projectCount") && $("projectCount").parentElement;
  const isDirectPlanTask = type !== "github_hotlist";
  if (repoField) repoField.hidden = !jobTypeNeedsRepo(type);
  if (planField) planField.hidden = type !== "from_plan_render";
  if (timeField) timeField.hidden = isDirectPlanTask;
  if (countField) countField.hidden = isDirectPlanTask;
}

function candidateAutoLimit() {
  return Number((state.currentJob && state.currentJob.project_count) || $("projectCount").value || 5);
}

function candidateChecked(item, index) {
  if (item.selected !== undefined) return Boolean(item.selected);
  return index < candidateAutoLimit();
}

function candidateOrder(item, index) {
  if (item.order) return item.order;
  return index < candidateAutoLimit() ? index + 1 : "";
}

function renderScript() {
  const editor = $("scriptEditor");
  renderNarrationSourceSummary((state.currentJob && state.currentJob.narration_source) || {});
  if (!state.segments.length) {
    editor.className = "script-editor empty";
    editor.textContent = "确认项目后会在这里生成口播草稿。";
    renderQualityReport();
    return;
  }
  editor.className = "script-editor";
  editor.innerHTML = state.segments.map((segment) => `
    <div class="script-segment" data-segment-id="${escapeAttr(segment.id)}">
      <label>${escapeHtml(segment.label || segment.id)}</label>
      <textarea>${escapeHtml(segment.text || "")}</textarea>
    </div>
  `).join("");
  renderQualityReport();
}

function renderQualityReport() {
  const box = $("qualityReport");
  if (!box) return;
  const report = state.qualityReport || {};
  const status = report.status || "";
  if (!status) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  const notes = qualityNotes(report);
  const score = report.readability_score === null || report.readability_score === undefined
    ? ""
    : ` · ${report.readability_score}/100`;
  box.hidden = false;
  box.className = `quality-report ${escapeAttr(status)}`;
  box.innerHTML = `
    <div class="quality-head">
      <span>${qualityStatusLabel(status)}${score}</span>
      <code>${escapeHtml(report.provider || "-")} / ${escapeHtml(report.model || "-")}</code>
    </div>
    <p>${escapeHtml(report.summary || "暂无质检结论。")}</p>
    ${notes.length ? `
      <table class="quality-table">
        <tbody>
          ${notes.map((note) => `
            <tr>
              <th>${escapeHtml(note.type)}</th>
              <td>${escapeHtml(note.text)}</td>
              <td>
                <button
                  class="tiny"
                  type="button"
                  data-quality-segment-id="${escapeAttr(note.segment_id || "")}"
                  ${note.segment_id ? "" : 'disabled title="当前风险未定位到具体段落"'}
                >${note.segment_id ? "定位段落" : "未定位"}</button>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    ` : ""}
    ${report.manual_override ? '<small>已人工确认忽略风险。</small>' : ""}
    ${report.error ? `<small>${escapeHtml(report.error)}</small>` : ""}
  `;
  box.querySelectorAll("[data-quality-segment-id]").forEach((button) => {
    button.addEventListener("click", () => focusScriptSegment(button.dataset.qualitySegmentId || ""));
  });
}

function qualityNotes(report) {
  if (Array.isArray(report.issues) && report.issues.length) {
    return report.issues.map((issue) => ({
      type: issue.type || "风险",
      text: issue.text || "",
      segment_id: issue.segment_id || "",
    })).filter((issue) => issue.text).slice(0, 8);
  }
  return [
    ...(report.risk_flags || []).map((text) => ({ type: "风险", text, segment_id: "" })),
    ...(report.factual_notes || []).map((text) => ({ type: "事实", text, segment_id: "" })),
    ...(report.overclaim_notes || []).map((text) => ({ type: "夸大", text, segment_id: "" })),
  ].slice(0, 8);
}

function focusScriptSegment(segmentId) {
  if (!segmentId) return false;
  const segment = document.querySelector(`[data-segment-id="${segmentId}"]`);
  if (!segment) return false;
  document.querySelectorAll(".script-segment.focused").forEach((node) => node.classList.remove("focused"));
  segment.classList.add("focused");
  if (typeof segment.scrollIntoView === "function") {
    segment.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  const textarea = segment.querySelector("textarea");
  if (textarea && typeof textarea.focus === "function") textarea.focus();
  if (typeof window !== "undefined" && typeof window.setTimeout === "function") {
    window.setTimeout(() => segment.classList.remove("focused"), 1800);
  }
  return true;
}

function qualityBlocksRender(report) {
  if (!report) return false;
  if (!report.status) return false;
  if (report.manual_override || report.passed === true) return false;
  return !["pass", "skipped", "unverified"].includes(report.status || "");
}

function confirmQualityOverride(report) {
  const notes = qualityNotes(report);
  const lines = [
    "脚本质检未通过，继续渲染前需要确认风险：",
    report.summary || "",
    ...notes.map((note) => `- ${note.type}: ${note.text}`),
    "",
    "仍要忽略风险并继续生成计划文件吗？",
  ].filter(Boolean);
  return typeof window === "undefined" || typeof window.confirm !== "function" || window.confirm(lines.join("\n"));
}

function qualityStatusLabel(status) {
  const labels = {
    pass: "质检通过",
    caution: "需要注意",
    skipped: "质检跳过",
    unverified: "质检未验证",
    failed: "质检失败",
    invalid_json: "质检响应异常",
  };
  return labels[status] || status;
}

function renderLogs(logs) {
  $("logBox").textContent = logs || "暂无日志。";
}

function appendLogLine(message) {
  const box = $("logBox");
  const current = box.textContent === "暂无日志。" ? "" : box.textContent;
  const prefix = current && !current.endsWith("\n") ? `${current}\n` : current;
  renderLogs(`${prefix}${message}\n`);
}

function renderStageTimeline(history) {
  const box = $("stageTimeline");
  if (!box) return;
  const stages = (history || []).slice(-12);
  if (!stages.length) {
    box.className = "stage-timeline empty";
    box.textContent = "暂无阶段记录。";
    return;
  }
  box.className = "stage-timeline";
  box.innerHTML = stages.map((entry, index) => `
    <div class="stage-step ${index === stages.length - 1 ? "current" : ""}">
      <span class="stage-dot"></span>
      <div>
        <strong>${escapeHtml(stageLabel(entry.stage || ""))}</strong>
        <small>${escapeHtml(entry.status || "-")} · ${escapeHtml(formatStageTime(entry.at || ""))}</small>
      </div>
    </div>
  `).join("");
}

function stageLabel(stage) {
  const labels = {
    draft_pending: "等待草稿",
    collecting_candidates: "拉取候选",
    analyzing_candidates: "分析候选",
    awaiting_project_confirmation: "等待确认项目",
    generating_script: "生成口播",
    awaiting_script_confirmation: "等待确认口播",
    preparing_plan: "准备计划",
    capturing_assets: "采集素材",
    generating_tts: "生成语音",
    composing_video: "合成视频",
    composing_html: "生成画面",
    rendering_hyperframes: "渲染动画",
    mixing_audio: "混合音频",
    post_processing: "后处理",
    completed: "已完成",
    failed: "失败",
  };
  return labels[stage] || stage || "-";
}

function formatStageTime(value) {
  if (!value) return "-";
  const match = String(value).match(/T(\d{2}:\d{2}(?::\d{2})?)/);
  return match ? match[1] : String(value);
}

function renderArtifacts(artifacts) {
  const list = $("artifactList");
  const files = artifacts.files || [];
  if (!files.length) {
    list.className = "artifact-list empty";
    list.textContent = "暂无产物。";
    return;
  }
  list.className = "artifact-list";
  const previews = files.filter((file) => file.name.startsWith("preview_frames/") && file.name.endsWith(".png"));
  const others = files.filter((file) => !previews.includes(file));
  list.innerHTML = [
    ...previews.map((file) => `
      <a class="preview-thumb" href="${escapeAttr(artifactHref(artifacts.job_id, file.name, file))}" target="_blank" rel="noreferrer">
        <img src="${escapeAttr(artifactHref(artifacts.job_id, file.name, file))}" alt="${escapeAttr(file.name)}">
        <code>${escapeHtml(file.name.replace("preview_frames/", ""))}</code>
      </a>
    `),
    ...others.map((file) => `
      <div class="artifact">
        <a href="${escapeAttr(artifactHref(artifacts.job_id, file.name, file))}" target="_blank" rel="noreferrer">
        <code>${escapeHtml(file.name)}</code>
        </a>
        <span>${officialVideoLabel(artifacts.job_id, file.name)}${Math.ceil((file.size || 0) / 1024)} KB</span>
      </div>
    `),
  ].join("");
}

function renderArtifactSummary(detail) {
  const box = $("artifactSummary");
  if (!box) return;
  const readiness = detail.readiness_report || {};
  const publish = detail.publish_pack || {};
  const cover = detail.cover_frame || {};
  const versions = detail.video_versions || [];
  const latestModelCall = detail.latest_model_call || {};
  const narrationSource = detail.narration_source || {};
  const officialVideo = versions.find((item) => item.is_official) || null;
  const latestVideo = officialVideo || (versions.length ? versions[versions.length - 1] : null);
  const summaryJobId = detail.job?.id || detail.artifacts?.job_id || "";
  const coverHref = cover.status === "ready" && summaryJobId ? artifactHref(summaryJobId, "cover_frame.png", {}) : "";
  const latestVideoMarkup = latestVideo
    ? (latestVideo.external
      ? `<code>${escapeHtml(latestVideo.path || latestVideo.name)}</code>`
      : summaryJobId
      ? `<a href="${escapeAttr(artifactHref(summaryJobId, latestVideo.name, latestVideo))}" target="_blank" rel="noreferrer">${escapeHtml(latestVideo.name)}</a>`
      : escapeHtml(latestVideo.name))
    : "-";
  const playerMarkup = latestVideo && summaryJobId && !latestVideo.external
    ? `<video class="artifact-player" controls preload="metadata" src="${escapeAttr(artifactHref(summaryJobId, latestVideo.name, latestVideo))}"></video>`
    : "";
  const hasSummary = readiness.status || publish.title || cover.status || versions.length;
  box.className = hasSummary ? "artifact-summary" : "artifact-summary empty";
  if (!hasSummary) {
    box.textContent = "暂无任务摘要。";
    return;
  }
  const tags = (publish.hashtags || []).slice(0, 4).join(" / ");
  const modelStatus = modelSummaryLabel(latestModelCall, narrationSource);
  const versionItems = versions.map((item) => `
    <div class="artifact-version">
      ${item.external
        ? `<code>${escapeHtml(item.path || item.name)}</code>`
        : `<a href="${escapeAttr(artifactHref(summaryJobId, item.name, item))}" target="_blank" rel="noreferrer">${escapeHtml(item.name)}</a>`}
      <span>${item.is_official ? "正式版本" : "历史版本"} · ${formatFileSize(item.size || 0)} · ${formatDuration(item.duration_seconds)}</span>
    </div>
  `).join("");
  box.innerHTML = `
    ${playerMarkup}
    ${coverHref ? `<img class="artifact-cover" src="${escapeAttr(coverHref)}" alt="cover frame">` : ""}
    <div class="summary-row">
      <span>准备度</span>
      <strong>${escapeHtml(readiness.status || "-")}${readiness.score === undefined ? "" : ` · ${readiness.score}`}</strong>
    </div>
    <div class="summary-row">
      <span>发布标题</span>
      <strong>${escapeHtml(publish.title || "-")}</strong>
    </div>
    <div class="summary-row">
      <span>封面</span>
      <strong>${escapeHtml(cover.status || "-")}</strong>
    </div>
    <div class="summary-row">
      <span>版本</span>
      <strong>${latestVideoMarkup}</strong>
    </div>
    <div class="summary-row">
      <span>时长</span>
      <strong>${escapeHtml(formatDuration(latestVideo && latestVideo.duration_seconds))}</strong>
    </div>
    <div class="summary-row">
      <span>大小</span>
      <strong>${escapeHtml(latestVideo ? formatFileSize(latestVideo.size || 0) : "-")}</strong>
    </div>
    <div class="summary-row">
      <span>模型状态</span>
      <strong>${escapeHtml(modelStatus)}</strong>
    </div>
    ${versionItems ? `<div class="artifact-version-list">${versionItems}</div>` : ""}
    ${tags ? `<small>${escapeHtml(tags)}</small>` : ""}
  `;
}

function renderPublishActions(detail) {
  const box = $("publishActions");
  if (!box) return;
  const publish = detail.publish_pack || {};
  const title = String(publish.title || "").trim();
  const hashtags = (publish.hashtags || []).join(" / ");
  const description = String(publish.description || "").trim();
  const hasPublish = title || hashtags || description;
  box.hidden = !hasPublish;
  if (!hasPublish) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = `
    <button class="tiny" type="button" data-copy-publish="title">复制标题</button>
    <button class="tiny" type="button" data-copy-publish="hashtags">复制标签</button>
    <button class="tiny" type="button" data-copy-publish="description">复制描述</button>
  `;
  box.querySelectorAll("[data-copy-publish]").forEach((button) => {
    button.addEventListener("click", async () => {
      const kind = button.dataset.copyPublish || "";
      const value = kind === "title" ? title : kind === "hashtags" ? hashtags : description;
      await copyText(value, kind);
    });
  });
}

function modelSummaryLabel(call, narrationSource) {
  const parts = [];
  if (call && (call.task || call.status)) {
    parts.push(`${modelTaskLabel(call.task || "-")} · ${call.provider || "-"} / ${call.model || "-"} · ${call.status || "-"}`);
  }
  const narration = narrationSourceLabel(narrationSource || {});
  if (narration) parts.push(narration);
  return parts.length ? parts.join(" · ") : "暂无模型记录";
}

function formatFileSize(bytes) {
  const value = Number(bytes || 0);
  if (!value) return "0 KB";
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.ceil(value / 1024)} KB`;
}

function formatDuration(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value <= 0) return "-";
  const total = Math.round(value);
  const minutes = Math.floor(total / 60);
  const remain = total % 60;
  return `${minutes}:${String(remain).padStart(2, "0")}`;
}

async function copyText(text, label) {
  const value = String(text || "").trim();
  if (!value) return;
  try {
    const clipboard = typeof globalThis !== "undefined" ? globalThis.navigator?.clipboard : undefined;
    if (clipboard && clipboard.writeText) {
      await clipboard.writeText(value);
      return;
    }
  } catch (_error) {
  }
  if (typeof window !== "undefined" && typeof window.prompt === "function") {
    window.prompt(`复制${label || "内容"}`, value);
  }
}

function modelTaskLabel(task) {
  const labels = {
    candidate_analysis: "候选分析",
    hotlist_ranking: "热榜排序",
    hook_generation: "标题钩子",
    feature_extraction: "功能摘要",
    narration_generation: "口播生成",
    script_polishing: "脚本润色",
    fact_check: "脚本质检",
  };
  return labels[task] || task || "-";
}

function officialVideoLabel(jobId, fileName) {
  return fileName.startsWith(`${jobId}-`) && fileName.endsWith(".mp4") ? "正式版本 · " : "";
}

function artifactHref(jobId, fileName, file = {}) {
  const path = `/api/jobs/${encodeURIComponent(jobId)}/artifacts/${fileName.split("/").map(encodeURIComponent).join("/")}`;
  const version = [file.mtime, file.size].filter(Boolean).join("-");
  return version ? `${path}?v=${encodeURIComponent(version)}` : path;
}

function openSettings() {
  renderSettings(state.config);
  $("settingsOverlay").hidden = false;
  $("settingsDrawer").hidden = false;
}

function closeSettings() {
  $("settingsOverlay").hidden = true;
  $("settingsDrawer").hidden = true;
  $("settingsMessage").textContent = "";
}

function renderSettings(config) {
  if (!config) return;
  $("githubTokenInput").value = "";
  const providers = config.providers.providers || [];
  $("providerEditor").innerHTML = providers.map((provider) => `
    <div class="provider-card" data-provider-id="${escapeAttr(provider.id)}">
      <div class="provider-title">
        <label class="check-row">
          <input type="checkbox" data-field="enabled" ${provider.enabled ? "checked" : ""}>
          <strong>${escapeHtml(provider.name)}</strong>
        </label>
        <span>${escapeHtml(provider.last_test || (provider.configured ? "key 已保存" : "未配置 key"))}</span>
      </div>
      <div class="provider-grid">
        <label>
          <span>Base URL</span>
          <input data-field="base_url" value="${escapeAttr(provider.base_url || "")}" placeholder="https://api.example.com">
        </label>
        <label>
          <span>默认模型</span>
          <input data-field="default_model" value="${escapeAttr(provider.default_model || "")}" placeholder="model-name">
        </label>
        <label class="wide">
          <span>API Key</span>
          <input data-field="api_key" type="password" placeholder="留空不修改；输入新 key 会覆盖">
        </label>
      </div>
      <div class="provider-actions">
        <button data-provider-test="${escapeAttr(provider.id)}" type="button">测试</button>
      </div>
    </div>
  `).join("");

  const routing = config.model_routing || {};
  const labels = {
    candidate_analysis: "候选分析",
    hotlist_ranking: "热榜排序",
    hook_generation: "标题钩子",
    narration_generation: "口播脚本",
    script_polishing: "脚本润色",
    fact_check: "事实检查",
  };
  $("routingEditor").innerHTML = Object.entries(routing).map(([task, value]) => `
    <div class="route-row" data-route="${escapeAttr(task)}">
      <span>${labels[task] || task}</span>
      <select data-field="provider">
        ${providers.map((provider) => `<option value="${escapeAttr(provider.id)}" ${provider.id === value.provider ? "selected" : ""}>${escapeHtml(provider.name)}</option>`).join("")}
      </select>
      <input data-field="model" value="${escapeAttr(value.model || "")}" placeholder="model">
    </div>
  `).join("");
}

function renderScheduler(schedule) {
  $("scheduleEnabled").checked = Boolean(schedule.enabled);
  $("scheduleMode").value = schedule.mode || "candidates_only";
  $("scheduleFrequency").value = schedule.frequency || "daily";
  $("scheduleTime").value = schedule.time || "09:00";
  $("scheduleWindow").value = schedule.time_window || "daily";
  $("scheduleProjectCount").value = String(schedule.project_count || 5);
  applyTemplateParams(schedule.template_params || activeTemplateParams(state.config?.templates || {}), "schedule");
  $("scheduleModeLabel").textContent = scheduleModeLabel(schedule.mode || "candidates_only");
  $("scheduleLastRun").textContent = schedule.last_run_date || "尚未运行";
  $("scheduleNextRun").textContent = nextScheduleLabel(schedule);
  $("scheduleStatus").textContent = scheduleStatusText(schedule);
}

function scheduleModeLabel(mode) {
  const labels = {
    candidates_only: "只生成候选草稿",
    auto_script: "自动生成口播草稿",
    auto_video: "自动生成正式视频",
  };
  return labels[mode] || labels.candidates_only;
}

function scheduleStatusText(schedule) {
  const mode = schedule.mode || "candidates_only";
  const lastRun = schedule.last_run_date ? `上次运行: ${schedule.last_run_date}` : "尚未运行";
  const modeText = mode === "auto_video"
    ? "定时任务会自动确认项目、确认口播、校验计划并生成正式 mp4；质检阻断时不会自动忽略。"
    : mode === "auto_script"
      ? "定时任务会自动确认前 N 个候选并生成口播草稿，但不会自动渲染。"
      : "定时任务只生成候选草稿，不会自动确认或渲染。";
  return `${modeText}${lastRun}`;
}

function nextScheduleLabel(schedule) {
  if (!schedule.enabled) return "未启用";
  const frequency = schedule.frequency === "weekly" ? "每周一" : "每天";
  return `${frequency} ${schedule.time || "09:00"}`;
}

function schedulerPayloadFromForm(current) {
  return {
    enabled: $("scheduleEnabled").checked,
    mode: $("scheduleMode").value,
    frequency: $("scheduleFrequency").value,
    time: $("scheduleTime").value || "09:00",
    time_window: $("scheduleWindow").value,
    project_count: Number($("scheduleProjectCount").value),
    template_params: currentTemplateParams("schedule"),
    last_run_date: current?.scheduler?.last_run_date || "",
  };
}

function openScheduleView() {
  void refreshScheduleView();
  $("scheduleView").hidden = false;
}

function closeScheduleView() {
  $("scheduleView").hidden = true;
  $("scheduleMessage").textContent = "";
}

async function saveSchedule() {
  const current = state.config;
  if (!current) return;
  setBusy(true);
  $("scheduleMessage").textContent = "保存中...";
  try {
    await saveSchedulePayload(current);
    await loadConfig();
    $("scheduleMessage").textContent = "已保存";
  } catch (error) {
    $("scheduleMessage").textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function saveSchedulePayload(current) {
  return post("/api/config", {
    scheduler: schedulerPayloadFromForm(current),
  });
}

async function runScheduleNow() {
  const current = state.config;
  if (!current) return;
  setBusy(true);
  $("scheduleMessage").textContent = "正在试跑...";
  try {
    await saveSchedulePayload(current);
    await loadConfig();
    const result = await post("/api/scheduler/run-due", { force: true });
    if (result.job?.id) {
      await loadJobs();
      $("scheduleMessage").textContent = `试跑已启动/完成: ${result.job.id}`;
    } else {
      $("scheduleMessage").textContent = result.reason === "not_due" ? "当前计划尚未到执行时间" : result.reason || "未启动";
    }
  } catch (error) {
    $("scheduleMessage").textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function refreshScheduleView() {
  try {
    const config = state.config || await api("/api/config");
    state.config = config;
    renderScheduler(config.scheduler || {});
    const jobs = await api("/api/jobs");
    renderScheduleRecentJobs(jobs.jobs || []);
  } catch (error) {
    console.error(error);
  }
}

async function saveSettings() {
  const current = state.config;
  if (!current) return;
  const githubToken = $("githubTokenInput").value.trim();
  const githubPayload = {
    token: githubToken,
    last_rate_limit: current.github.last_rate_limit || "未检测",
  };

  const providers = [...document.querySelectorAll(".provider-card")].map((card) => {
    const original = (current.providers.providers || []).find((item) => item.id === card.dataset.providerId) || {};
    return {
      id: original.id,
      name: original.name,
      type: original.type,
      api_key: fieldValue(card, "api_key"),
      base_url: fieldValue(card, "base_url"),
      default_model: fieldValue(card, "default_model"),
      enabled: card.querySelector("[data-field='enabled']").checked,
      last_test: original.last_test || "未测试",
    };
  });

  const routing = {};
  document.querySelectorAll(".route-row").forEach((row) => {
    routing[row.dataset.route] = {
      provider: fieldValue(row, "provider"),
      model: fieldValue(row, "model"),
    };
  });

  setBusy(true);
  $("settingsMessage").textContent = "保存中...";
  try {
    await post("/api/config", {
      github: githubPayload,
      providers: { providers },
      "model-routing": routing,
      templates: templatePayload(current),
    });
    await loadConfig();
    $("settingsMessage").textContent = "已保存";
  } catch (error) {
    $("settingsMessage").textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function testProviderFromButton(event) {
  const button = event.target.closest("[data-provider-test]");
  if (!button) return;
  const card = button.closest(".provider-card");
  if (!card) return;
  const providerId = button.dataset.providerTest;
  const originalText = button.textContent || "测试";
  const model = fieldValue(card, "default_model");
  const original = (state.config?.providers?.providers || []).find((item) => item.id === providerId) || {};
  const provider = {
    id: providerId,
    type: original.type || "",
    api_key: fieldValue(card, "api_key"),
    base_url: fieldValue(card, "base_url"),
    default_model: model,
    enabled: card.querySelector("[data-field='enabled']").checked,
  };
  button.disabled = true;
  button.textContent = "测试中";
  try {
    const result = await post(`/api/providers/${encodeURIComponent(providerId)}/test`, { model, provider });
    if (result.saved) {
      state.config = result.config;
      $("routingStatus").textContent = providerStatusLabel(result.config.providers.providers || []);
      const statusSpan = card.querySelector(".provider-title > span");
      if (statusSpan) statusSpan.textContent = result.message;
    }
    $("settingsMessage").textContent = result.saved ? result.message : `${result.message}；当前表单尚未保存，状态未写回。`;
  } catch (error) {
    button.textContent = "失败";
    alert(error.message);
  } finally {
    if (button.isConnected !== false) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

function fieldValue(scope, name) {
  const node = scope.querySelector(`[data-field='${name}']`);
  return node ? node.value.trim() : "";
}

function selectedCandidates() {
  return [...document.querySelectorAll("#candidateRows input[type='checkbox']")]
    .filter((input) => input.checked)
    .map((input) => {
      const index = Number(input.dataset.index);
      const item = state.candidates[index];
      const orderInput = document.querySelector(`[data-order-index='${index}']`);
      return item ? { item, order: Number(orderInput?.value || 9999), index } : null;
    })
    .filter(Boolean)
    .sort((left, right) => left.order - right.order || left.index - right.index)
    .map((entry) => entry.item);
}

function updateSelectionState() {
  const button = $("confirmSelectionBtn");
  if (!button || !state.candidates.length) return;
  const selectedCount = document.querySelectorAll("#candidateRows input[type='checkbox']:checked").length;
  const limit = Number($("projectCount").value || 5);
  const canConfirm = $("nextActionBtn").dataset.action === "confirm-selection";
  const summary = selectionButtonState(selectedCount, limit, canConfirm);
  button.textContent = summary.label;
  if (canConfirm) button.disabled = summary.disabled;
}

function selectionButtonState(selectedCount, limit, canConfirm) {
  const safeLimit = Number(limit || 5);
  return {
    label: selectedCount > safeLimit
      ? `已选 ${selectedCount} / 最多 ${safeLimit}`
      : `确认 ${selectedCount} / ${safeLimit} 个项目`,
    disabled: canConfirm && (selectedCount < 1 || selectedCount > safeLimit),
  };
}

function setBusy(isBusy) {
  document.querySelectorAll("button:not(#closeSettingsBtn):not(#openSettingsBtn):not(#closeScheduleBtn):not(#openScheduleBtn):not(#openScheduleSideBtn):not(#openScheduleFromSettingsBtn)").forEach((button) => {
    if (isBusy) {
      button.dataset.wasDisabled = button.disabled ? "1" : "0";
      button.disabled = true;
      return;
    }
    button.disabled = button.dataset.wasDisabled === "1";
    delete button.dataset.wasDisabled;
  });
  if (!isBusy) updateActionState(state.currentJob || { stage: "draft_pending", status: "draft_pending" });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

function _shortUiText(value, limit) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}...`;
}

if (typeof window !== "undefined") {
  boot().catch((error) => {
    console.error(error);
    alert(error.message);
  });
}

if (typeof module !== "undefined") {
  module.exports = { activeTemplateParams, api, appendLogLine, applyTemplateParams, autoTabForCompletedBackground, candidateChecked, candidateEmptyMessage, candidateOrder, candidateSourceLabel, copyText, createDraft, currentJobType, focusScriptSegment, formatDuration, formatFileSize, hasBackgroundWork, modelSummaryLabel, narrationSourceLabel, nextActionForJob, nextScheduleLabel, publicCandidateText, qualityBlocksRender, qualityNotes, recoveryHintForJob, refreshCurrentJob, renderArtifacts, renderArtifactSummary, renderDiagnostics, renderHistoryJobs, renderJob, renderPublishActions, renderQualityReport, renderRecoveryHint, renderScheduleQueue, renderScheduleRecentJobs, renderScheduler, renderStageTimeline, renderTemplateStyles, scheduleModeLabel, scheduleRecentLabel, schedulerPayloadFromForm, scheduleQueueLabel, scheduleStatusText, selectionButtonState, setBusy, startNewJob, state, syncDetailState, syncJobTypeFields, templatePayload, testProviderFromButton, updateRegenerateActions };
}
