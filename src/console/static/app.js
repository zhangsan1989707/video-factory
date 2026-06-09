const state = {
  currentJobId: "",
  currentJob: null,
  candidates: [],
  segments: [],
  qualityReport: null,
  config: null,
  pollTimer: null,
};

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
  $("confirmSelectionBtn").addEventListener("click", confirmSelection);
  $("saveScriptBtn").addEventListener("click", saveScript);
  $("openSettingsBtn").addEventListener("click", openSettings);
  $("closeSettingsBtn").addEventListener("click", closeSettings);
  $("settingsOverlay").addEventListener("click", closeSettings);
  $("saveSettingsBtn").addEventListener("click", saveSettings);
  $("providerEditor").addEventListener("click", testProviderFromButton);
  $("openJobFolderBtn").addEventListener("click", openJobFolder);
  $("visualStyle").addEventListener("change", syncRenderEngineForStyle);
  $("renderEngine").addEventListener("change", syncStyleForRenderEngine);
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
  } catch (error) {
    $("preflightStatus").textContent = "检测失败";
    $("preflightStatus").title = error.message;
  }
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
    return;
  }
  list.className = "history-list";
  list.innerHTML = data.jobs.map((job) => `
    <button class="history-item" data-job="${escapeAttr(job.id || "")}">
      <code>${escapeHtml(job.id || "")}</code>
      <span class="status ${escapeAttr(job.status || "")}">${escapeHtml(job.stage || "")}</span>
    </button>
  `).join("");
  list.querySelectorAll("[data-job]").forEach((item) => {
    item.addEventListener("click", () => loadJob(item.dataset.job));
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
    const created = await post("/api/jobs", {
      title: "GitHub 热榜视频",
      time_window: $("timeWindow").value,
      project_count: Number($("projectCount").value),
      template: "github_hotlist_vertical_v1",
      template_params: currentTemplateParams(),
    });
    state.currentJobId = created.job.id;
    renderJob(created.job);
    switchTab("progress");
    renderLogs("任务已创建，正在拉取候选项目...\n");

    const result = await post(`/api/jobs/${state.currentJobId}/candidates`);
    state.candidates = result.candidates || [];
    renderJob(result.job);
    renderCandidates();
    await refreshCurrentJob();
    await loadJobs();
    switchTab("candidates");
  } catch (error) {
    alert(error.message);
  } finally {
    setBusy(false);
  }
}

async function collectCandidatesForCurrentJob() {
  if (!state.currentJobId) {
    alert("请先创建任务");
    return;
  }
  setBusy(true);
  try {
    switchTab("progress");
    renderLogs(`${$("logBox").textContent}\\n正在重新拉取候选项目...\\n`);
    const result = await post(`/api/jobs/${state.currentJobId}/candidates`);
    state.candidates = result.candidates || [];
    renderJob(result.job);
    renderCandidates();
    await refreshCurrentJob();
    await loadJobs();
    switchTab("candidates");
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
    const result = await post(`/api/jobs/${state.currentJobId}/selection`, { items: selected });
    state.segments = result.segments || [];
    renderJob(result.job);
    renderScript();
    await refreshCurrentJob();
    switchTab("script");
  } catch (error) {
    alert(error.message);
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
  setBusy(true);
  try {
    const result = await post(`/api/jobs/${state.currentJobId}/script`, { segments });
    state.segments = result.segments || segments;
    state.qualityReport = result.quality_report || null;
    renderJob(result.job);
    renderQualityReport();
    await refreshCurrentJob();
    switchTab("progress");
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
    const prepared = await post(`/api/jobs/${state.currentJobId}/prepare-plan`);
    renderJob(prepared.job);
    renderArtifacts(prepared.artifacts || {});
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
    renderLogs(`${$("logBox").textContent}\n正在校验计划文件...\n`);
    const validated = await post(`/api/jobs/${state.currentJobId}/validate-plan`);
    renderJob(validated.job);
    renderArtifacts(validated.artifacts || {});
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
    renderLogs(`${$("logBox").textContent}\\n正在生成最终视频，请不要关闭控制台...\\n`);
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
  if (!state.currentJobId) return;
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
  renderArtifacts(detail.artifacts || {});
  if (detail.job && detail.job.status !== "running") stopPollingCurrentJob();
}

function syncDetailState(detail) {
  state.candidates = detail.candidates || [];
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
  if (job.project_count) $("projectCount").value = String(job.project_count);
  $("openJobFolderBtn").disabled = !job.id;
  renderModelCall(job.model_calls || []);
  renderJobError(job.error || "");
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

function currentTemplateParams() {
  return {
    visual_style: $("visualStyle").value,
    render_engine: $("renderEngine").value,
    subtitle_mode: $("subtitleMode").value,
    narration_tone: $("tone").value,
    bgm: $("bgmMode").value,
    bgm_path: $("bgmPath").value.trim(),
  };
}

function applyTemplateParams(params) {
  if (params.visual_style) $("visualStyle").value = params.visual_style;
  if (params.style) $("visualStyle").value = params.style;
  if (params.render_engine) $("renderEngine").value = params.render_engine;
  if (!params.render_engine) syncRenderEngineForStyle();
  if (params.subtitle_mode) $("subtitleMode").value = params.subtitle_mode;
  if (params.narration_tone) $("tone").value = params.narration_tone;
  if (params.bgm) $("bgmMode").value = params.bgm;
  $("bgmPath").value = params.bgm_path || "";
}

function syncRenderEngineForStyle() {
  $("renderEngine").value = $("visualStyle").value === "tech_hotspot" ? "hyperframes" : "pil";
}

function syncStyleForRenderEngine() {
  if ($("renderEngine").value === "hyperframes") $("visualStyle").value = "tech_hotspot";
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
      style: params.visual_style,
      render_engine: params.render_engine,
      subtitle_mode: params.subtitle_mode,
      bgm: params.bgm,
      bgm_path: params.bgm_path,
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
  confirmSelection.disabled = action !== "confirm-selection";
  saveScriptButton.textContent = "确认口播并进入出片";
  saveScriptButton.disabled = action !== "confirm-script";
}

function nextActionForJob(job) {
  const stage = job.stage || "draft_pending";
  const status = job.status || "";
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
  if (status === "running") {
    return { label: "任务执行中", action: "running", disabled: true };
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
      post_processing: "render-video",
    };
    const retryAction = retryActions[stage];
    return retryAction
      ? { label: `重试：${stageLabel(stage)}`, action: retryAction, disabled: false }
      : { label: "无法自动重试", action: "failed", disabled: true };
  }
  return { label: "生成候选草稿", action: "create", disabled: false };
}

function renderCandidates() {
  const body = $("candidateRows");
  if (!state.candidates.length) {
    body.innerHTML = '<tr><td colspan="8" class="empty">还没有候选项目。点击“生成候选草稿”。</td></tr>';
    return;
  }
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
      <td>${Number(item.stars || 0).toLocaleString()}</td>
      <td>${escapeHtml(item.language || "-")}</td>
      <td>${escapeHtml(item.recommendation || "")}<small>${escapeHtml(item.ranking_reason || item.visual_potential || "")}</small></td>
      <td>${escapeHtml(item.risk || "")}</td>
    </tr>
  `).join("");
  body.querySelectorAll("input[type='checkbox'], .order-input").forEach((input) => {
    input.addEventListener("input", updateSelectionState);
    input.addEventListener("change", updateSelectionState);
  });
  updateSelectionState();
}

function candidateAutoLimit() {
  return Number((state.currentJob && state.currentJob.project_count) || $("projectCount").value || 10);
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
  const notes = [
    ...(report.risk_flags || []),
    ...(report.factual_notes || []),
    ...(report.overclaim_notes || []),
  ].slice(0, 4);
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
    ${notes.length ? `<ul>${notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>` : ""}
    ${report.error ? `<small>${escapeHtml(report.error)}</small>` : ""}
  `;
}

function qualityStatusLabel(status) {
  const labels = {
    pass: "质检通过",
    caution: "需要注意",
    skipped: "质检跳过",
    failed: "质检失败",
    invalid_json: "质检响应异常",
  };
  return labels[status] || status;
}

function renderLogs(logs) {
  $("logBox").textContent = logs || "暂无日志。";
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
      <a class="preview-thumb" href="${escapeAttr(artifactHref(artifacts.job_id, file.name))}" target="_blank" rel="noreferrer">
        <img src="${escapeAttr(artifactHref(artifacts.job_id, file.name))}" alt="${escapeAttr(file.name)}">
        <code>${escapeHtml(file.name.replace("preview_frames/", ""))}</code>
      </a>
    `),
    ...others.map((file) => `
      <div class="artifact">
        <a href="${escapeAttr(artifactHref(artifacts.job_id, file.name))}" target="_blank" rel="noreferrer">
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
  const latestVideo = versions.length ? versions[versions.length - 1] : null;
  const summaryJobId = detail.job?.id || detail.artifacts?.job_id || "";
  const latestVideoMarkup = latestVideo
    ? (summaryJobId
      ? `<a href="${escapeAttr(artifactHref(summaryJobId, latestVideo.name))}" target="_blank" rel="noreferrer">${escapeHtml(latestVideo.name)}</a>`
      : escapeHtml(latestVideo.name))
    : "-";
  const hasSummary = readiness.status || publish.title || cover.status || versions.length;
  box.className = hasSummary ? "artifact-summary" : "artifact-summary empty";
  if (!hasSummary) {
    box.textContent = "暂无任务摘要。";
    return;
  }
  const tags = (publish.hashtags || []).slice(0, 4).join(" / ");
  box.innerHTML = `
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
    ${tags ? `<small>${escapeHtml(tags)}</small>` : ""}
  `;
}

function officialVideoLabel(jobId, fileName) {
  return fileName.startsWith(`${jobId}-`) && fileName.endsWith(".mp4") ? "正式版本 · " : "";
}

function artifactHref(jobId, fileName) {
  return `/api/jobs/${encodeURIComponent(jobId)}/artifacts/${fileName.split("/").map(encodeURIComponent).join("/")}`;
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
  $("scheduleFrequency").value = schedule.frequency || "daily";
  $("scheduleTime").value = schedule.time || "09:00";
  $("scheduleWindow").value = schedule.time_window || "daily";
  $("scheduleProjectCount").value = String(schedule.project_count || 10);
  const lastRun = schedule.last_run_date ? `上次运行: ${schedule.last_run_date}` : "尚未运行";
  $("scheduleStatus").textContent = `定时任务只生成候选草稿，不会自动确认或渲染。${lastRun}`;
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

  const schedulerPayload = {
    enabled: $("scheduleEnabled").checked,
    frequency: $("scheduleFrequency").value,
    time: $("scheduleTime").value || "09:00",
    time_window: $("scheduleWindow").value,
    project_count: Number($("scheduleProjectCount").value),
    template_params: currentTemplateParams(),
    last_run_date: current.scheduler?.last_run_date || "",
  };

  setBusy(true);
  $("settingsMessage").textContent = "保存中...";
  try {
    await post("/api/config", {
      github: githubPayload,
      providers: { providers },
      "model-routing": routing,
      scheduler: schedulerPayload,
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
    state.config = result.config;
    renderSettings(state.config);
    await loadConfig();
    $("settingsMessage").textContent = result.saved ? result.message : `${result.message}；当前表单尚未保存，状态未写回。`;
  } catch (error) {
    button.textContent = "失败";
    alert(error.message);
  } finally {
    button.disabled = false;
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
  const limit = Number($("projectCount").value || 10);
  const canConfirm = $("nextActionBtn").dataset.action === "confirm-selection";
  const summary = selectionButtonState(selectedCount, limit, canConfirm);
  button.textContent = summary.label;
  if (canConfirm) button.disabled = summary.disabled;
}

function selectionButtonState(selectedCount, limit, canConfirm) {
  const safeLimit = Number(limit || 10);
  return {
    label: selectedCount > safeLimit
      ? `已选 ${selectedCount} / 最多 ${safeLimit}`
      : `确认 ${selectedCount} / ${safeLimit} 个项目`,
    disabled: canConfirm && (selectedCount < 1 || selectedCount > safeLimit),
  };
}

function setBusy(isBusy) {
  document.querySelectorAll("button:not(#closeSettingsBtn):not(#openSettingsBtn)").forEach((button) => {
    if (isBusy) {
      button.dataset.wasDisabled = button.disabled ? "1" : "0";
      button.disabled = true;
      return;
    }
    button.disabled = button.dataset.wasDisabled === "1";
    delete button.dataset.wasDisabled;
  });
  if (!isBusy && state.currentJob) updateActionState(state.currentJob);
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
  module.exports = { activeTemplateParams, api, candidateChecked, candidateOrder, nextActionForJob, renderArtifacts, renderArtifactSummary, renderDiagnostics, renderJob, renderStageTimeline, selectionButtonState, setBusy, state, syncDetailState, templatePayload };
}
