const assert = require("node:assert/strict");
const { activeTemplateParams, api, appendLogLine, applyTemplateParams, autoTabForCompletedBackground, candidateChecked, candidateEmptyMessage, candidateOrder, candidateSourceLabel, copyText, createDraft, currentJobType, focusScriptSegment, formatDuration, formatFileSize, hasBackgroundWork, modelSummaryLabel, narrationSourceLabel, nextActionForJob, qualityBlocksRender, qualityNotes, recoveryHintForJob, refreshCurrentJob, renderArtifacts, renderArtifactSummary, renderDiagnostics, renderHistoryJobs, renderJob, renderPublishActions, renderQualityReport, renderScheduleQueue, renderScheduler, renderStageTimeline, renderTemplateStyles, scheduleQueueLabel, selectionButtonState, setBusy, state, syncDetailState, syncJobTypeFields, templatePayload, testProviderFromButton, updateRegenerateActions } = require("../src/console/static/app.js");

async function run() {
  await testJsonSuccess();
  await testJsonError();
  await testTextError();
  testRenderDiagnosticsIncludesLatestModelCall();
  testRecoveryHintMapsFailedStageToNextStep();
  testFailedJobsExposeRetryActions();
  testPlanStagesExposeSeparateActions();
  testDraftJobsExposeSeparateCreateAndCollectActions();
  testActiveAwaitingInputKeepsActionsBlocked();
  testCompletedBackgroundStagesChooseReviewTabs();
  await testRefreshCurrentJobReloadsHistoryWhenPollingCompletes();
  testRegenerateButtonsFollowStage();
  testUnverifiedQualityDoesNotHardBlockRender();
  testRenderTemplateStylesPopulatesStyleSelect();
  testTemplatePayloadUsesActiveTemplate();
  testApplyTemplateParamsRestoresBgmVolume();
  testRenderArtifactsShowsPreviewAndOfficialVideo();
  testRenderArtifactSummaryShowsPublishMetadata();
  testRenderHistoryJobsShowsOpenAndDeleteActions();
  testRenderScheduleQueueShowsPendingAndFailedScheduledJobs();
  testRenderStageTimelineShowsRecentHistory();
  testAppendLogLineUsesRealNewlines();
  testRenderJobRefreshesEmbeddedStageHistory();
  testBusyRestoreKeepsLatestJobActionState();
  testSyncDetailStateReplacesCandidateAndScriptSnapshots();
  testSyncDetailStateStripsSelectedField();
  testSelectionButtonStateShowsLimit();
  testCandidateDefaultsUseProjectCount();
  testFormatHelpersForArtifactWorkbench();
  testCandidateSourceLabelShowsSummary();
  testNarrationSourceLabelShowsFallbackReason();
  testModelSummaryLabelCombinesLatestCallAndNarrationSource();
  testRenderPublishActionsShowsCopyButtons();
  testRenderSchedulerShowsAutoScriptMode();
  testQualityNotesPreferStructuredIssues();
  testFocusScriptSegmentHighlightsTarget();
  testRenderQualityReportShowsLocateAction();
  await testCreateDraftDoesNotCollectCandidates();
  await testCreateSingleProjectDraftUsesRepoUrl();
  testSingleProjectCandidateEmptyMessage();
  testSyncJobTypeFieldsTogglesInputs();
  await testCopyTextUsesClipboardWhenAvailable();
  await testProviderTestKeepsUnsavedFormValues();
}

async function testJsonSuccess() {
  global.fetch = async () => ({
    ok: true,
    status: 200,
    text: async () => '{"ok":true}',
  });

  assert.deepEqual(await api("/api/health"), { ok: true });
}

async function testJsonError() {
  global.fetch = async () => ({
    ok: false,
    status: 400,
    text: async () => '{"error":"bad request"}',
  });

  await assert.rejects(() => api("/api/jobs"), /bad request/);
}

async function testTextError() {
  global.fetch = async () => ({
    ok: false,
    status: 502,
    text: async () => "proxy unavailable",
  });

  await assert.rejects(() => api("/api/jobs"), /proxy unavailable/);
}

function testRenderDiagnosticsIncludesLatestModelCall() {
  const nodes = {
    currentDiagnostics: { hidden: true, textContent: "" },
  };
  global.document = {
    getElementById(id) {
      return nodes[id];
    },
  };

  renderDiagnostics({
    job: { status: "failed" },
    failed_stage: "generating_script",
    latest_model_call: {
      task: "narration_generation",
      provider: "Anthropic",
      model: "claude-test",
      status: "failed",
      error: "model overloaded",
    },
    log_tail: "last line",
  });

  assert.equal(nodes.currentDiagnostics.hidden, false);
  assert.match(nodes.currentDiagnostics.textContent, /failed_stage: generating_script/);
  assert.match(nodes.currentDiagnostics.textContent, /model_call: narration_generation · Anthropic \/ claude-test · failed/);
  assert.match(nodes.currentDiagnostics.textContent, /model_error: model overloaded/);
  assert.match(nodes.currentDiagnostics.textContent, /last_logs:\nlast line/);
}

function testRecoveryHintMapsFailedStageToNextStep() {
  assert.match(
    recoveryHintForJob({ status: "failed", failed_stage: "rendering_hyperframes" }),
    /HyperFrames 渲染失败/,
  );
  assert.match(
    recoveryHintForJob({ status: "failed", failed_stage: "preparing_plan" }),
    /重新生成计划文件/,
  );
  assert.equal(recoveryHintForJob({ status: "completed", stage: "completed" }), "");
}

function testFailedJobsExposeRetryActions() {
  const cases = [
    ["collecting_candidates", "collect-candidates", "重试：拉取候选"],
    ["analyzing_candidates", "collect-candidates", "重试：分析候选"],
    ["generating_script", "confirm-selection", "重试：生成口播"],
    ["preparing_plan", "prepare-plan", "重试：准备计划"],
    ["capturing_assets", "render-video", "重试：采集素材"],
    ["generating_tts", "render-video", "重试：生成语音"],
    ["composing_video", "render-video", "重试：合成视频"],
    ["composing_html", "render-video", "重试：生成画面"],
    ["rendering_hyperframes", "render-video", "重试：渲染动画"],
    ["mixing_audio", "render-video", "重试：混合音频"],
    ["post_processing", "render-video", "重试：后处理"],
  ];

  for (const [stage, action, label] of cases) {
    assert.deepEqual(nextActionForJob({ status: "failed", stage }), {
      label,
      action,
      disabled: false,
    });
  }

  assert.deepEqual(nextActionForJob({ status: "failed", stage: "unknown_stage" }), {
    label: "无法自动重试",
    action: "failed",
    disabled: true,
  });
}

function testPlanStagesExposeSeparateActions() {
  assert.deepEqual(nextActionForJob({ stage: "preparing_plan", status: "awaiting_render" }), {
    label: "生成计划文件",
    action: "prepare-plan",
    disabled: false,
  });
  assert.deepEqual(nextActionForJob({ stage: "preparing_plan", status: "awaiting_validation" }), {
    label: "校验计划文件",
    action: "validate-plan",
    disabled: false,
  });
}

function testDraftJobsExposeSeparateCreateAndCollectActions() {
  assert.deepEqual(nextActionForJob({ stage: "draft_pending", status: "draft_pending" }), {
    label: "创建任务",
    action: "create",
    disabled: false,
  });
  assert.deepEqual(nextActionForJob({ id: "GH-HOTLIST-20990101-001", stage: "draft_pending", status: "draft_pending" }), {
    label: "生成候选草稿",
    action: "collect-candidates",
    disabled: false,
  });

  state.currentJobId = "";
  assert.equal(candidateEmptyMessage(), "还没有任务。先选择时间维度和项目数，再点击“创建任务”。");
  state.currentJobId = "GH-HOTLIST-20990101-001";
  assert.equal(candidateEmptyMessage(), "任务已创建。点击“生成候选草稿”拉取候选项目。");
}

function testActiveAwaitingInputKeepsActionsBlocked() {
  assert.equal(hasBackgroundWork({ status: "awaiting_input", stage: "awaiting_project_confirmation", active: true }), true);
  assert.deepEqual(nextActionForJob({ status: "awaiting_input", stage: "awaiting_project_confirmation", active: true }), {
    label: "任务执行中",
    action: "running",
    disabled: true,
  });
}

function testCompletedBackgroundStagesChooseReviewTabs() {
  assert.equal(autoTabForCompletedBackground({ status: "awaiting_input", stage: "awaiting_project_confirmation" }), "candidates");
  assert.equal(autoTabForCompletedBackground({ status: "awaiting_input", stage: "awaiting_script_confirmation" }), "script");
  assert.equal(autoTabForCompletedBackground({ status: "awaiting_render", stage: "preparing_plan" }), "");
}

async function testRefreshCurrentJobReloadsHistoryWhenPollingCompletes() {
  const calls = [];
  global.fetch = async (path) => {
    calls.push(path);
    if (path === "/api/jobs/GH-HOTLIST-20990101-001") {
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({
          job: {
            id: "GH-HOTLIST-20990101-001",
            status: "completed",
            stage: "completed",
            template_params: {},
          },
          candidates: [],
          segments: [],
          artifacts: {},
          stage_history: [],
        }),
      };
    }
    if (path === "/api/jobs") {
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({
          jobs: [
            { id: "GH-HOTLIST-20990101-001", status: "completed", stage: "completed" },
          ],
        }),
      };
    }
    throw new Error(`unexpected fetch: ${path}`);
  };
  const elements = basicConsoleNodes();
  global.document = {
    getElementById(id) {
      return elements[id] || null;
    },
    querySelectorAll() {
      return [];
    },
  };
  global.window = {
    clearInterval(id) {
      calls.push(`clear:${id}`);
    },
  };

  state.currentJobId = "GH-HOTLIST-20990101-001";
  state.pollTimer = 7;
  await refreshCurrentJob();

  assert.equal(state.pollTimer, null);
  assert.deepEqual(calls.slice(0, 3), [
    "/api/jobs/GH-HOTLIST-20990101-001",
    "clear:7",
    "/api/jobs",
  ]);
  assert.match(elements.historyList.innerHTML, /completed/);
}

function basicConsoleNodes() {
  const emptyListNode = () => ({
    className: "",
    innerHTML: "",
    textContent: "",
    querySelectorAll() {
      return [];
    },
  });
  const buttonNode = () => ({
    textContent: "",
    dataset: {},
    disabled: false,
  });
  return {
    currentJobId: { textContent: "" },
    currentStage: { textContent: "" },
    currentModelCall: { textContent: "" },
    currentError: { hidden: true, textContent: "" },
    currentDiagnostics: { hidden: true, textContent: "" },
    candidateSourceSummary: { textContent: "" },
    narrationSourceSummary: { textContent: "" },
    openJobFolderBtn: buttonNode(),
    nextActionBtn: buttonNode(),
    confirmSelectionBtn: buttonNode(),
    saveScriptBtn: buttonNode(),
    regenerateCandidatesBtn: buttonNode(),
    regenerateScriptBtn: buttonNode(),
    regenerateVideoBtn: buttonNode(),
    cancelJobBtn: buttonNode(),
    refreshCandidatesBtn: buttonNode(),
    refreshCandidatesBtn2: buttonNode(),
    visualStyle: { value: "tech_hotspot" },
    renderEngine: { value: "hyperframes" },
    subtitleMode: { value: "large_hook" },
    tone: { value: "professional_review" },
    bgmMode: { value: "default" },
    bgmVolume: { value: "0.13" },
    bgmPath: { value: "" },
    issueNumber: { value: "" },
    projectCount: { value: "5" },
    candidateRows: emptyListNode(),
    scriptEditor: emptyListNode(),
    qualityReport: emptyListNode(),
    logBox: { textContent: "" },
    stageTimeline: emptyListNode(),
    artifactSummary: emptyListNode(),
    publishActions: emptyListNode(),
    artifactList: emptyListNode(),
    scheduleQueue: emptyListNode(),
    historyList: emptyListNode(),
  };
}

async function testCreateDraftDoesNotCollectCandidates() {
  const calls = [];
  global.fetch = async (path, options = {}) => {
    calls.push({ path, method: options.method || "GET", body: options.body ? JSON.parse(options.body) : null });
    if (path === "/api/jobs" && options.method === "POST") {
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({
          job: {
            id: "GH-HOTLIST-20990101-DRAFT",
            status: "draft_pending",
            stage: "draft_pending",
            time_window: "monthly",
            project_count: 10,
            template_params: {},
            stage_history: [{ stage: "draft_pending", status: "draft_pending", at: "2026-06-10T10:00:00" }],
          },
        }),
      };
    }
    if (path === "/api/jobs") {
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ jobs: [{ id: "GH-HOTLIST-20990101-DRAFT", status: "draft_pending", stage: "draft_pending" }] }),
      };
    }
    throw new Error(`unexpected fetch: ${path}`);
  };
  global.alert = (message) => {
    throw new Error(message);
  };

  const buttons = [];
  const values = {
    timeWindow: { value: "monthly" },
    projectCount: { value: "10" },
    visualStyle: { value: "tech_hotspot" },
    renderEngine: { value: "hyperframes" },
    subtitleMode: { value: "large_hook" },
    tone: { value: "professional_review" },
    bgmMode: { value: "default" },
    bgmVolume: { value: "0.13" },
    bgmPath: { value: "" },
    currentJobId: { textContent: "" },
    currentStage: { textContent: "" },
    openJobFolderBtn: { disabled: true },
    currentModelCall: { textContent: "" },
    currentError: { hidden: true, textContent: "" },
    currentDiagnostics: { hidden: true, textContent: "" },
    stageTimeline: { className: "", innerHTML: "", textContent: "" },
    nextActionBtn: { textContent: "", dataset: {}, disabled: false },
    confirmSelectionBtn: { textContent: "", disabled: false },
    saveScriptBtn: { textContent: "", disabled: false },
    regenerateCandidatesBtn: { disabled: true },
    regenerateScriptBtn: { disabled: true },
    regenerateVideoBtn: { disabled: true },
    cancelJobBtn: { disabled: true, textContent: "" },
    candidateRows: { innerHTML: "", querySelectorAll() { return []; } },
    scriptEditor: { className: "", textContent: "", innerHTML: "" },
    qualityReport: { hidden: false, innerHTML: "", className: "" },
    publishActions: { hidden: true, innerHTML: "", querySelectorAll() { return []; } },
    logBox: { textContent: "" },
    historyList: {
      className: "",
      textContent: "",
      innerHTML: "",
      querySelectorAll() {
        return [];
      },
    },
  };
  buttons.push(values.nextActionBtn, values.confirmSelectionBtn, values.saveScriptBtn);
  buttons.forEach((button) => {
    button.dataset ||= {};
  });
  global.document = {
    getElementById(id) {
      return values[id];
    },
    querySelectorAll(selector) {
      assert.equal(selector, "button:not(#closeSettingsBtn):not(#openSettingsBtn)");
      return buttons;
    },
  };

  state.currentJobId = "";
  state.currentJob = null;
  state.candidates = [{ full_name: "old/candidate" }];
  state.segments = [{ id: "intro", text: "old" }];
  state.qualityReport = { status: "caution" };

  await createDraft();

  assert.deepEqual(calls.map((call) => [call.method, call.path]), [["POST", "/api/jobs"], ["GET", "/api/jobs"]]);
  assert.equal(calls[0].body.time_window, "monthly");
  assert.equal(calls[0].body.project_count, 10);
  assert.equal(calls[0].body.template_params.bgm_volume, 0.13);
  assert.equal(values.nextActionBtn.textContent, "生成候选草稿");
  assert.equal(values.nextActionBtn.dataset.action, "collect-candidates");
  assert.equal(values.logBox.textContent, "任务已按当前时间维度和项目数创建。点击“生成候选草稿”拉取候选项目。\n");
  assert.equal(values.candidateRows.innerHTML.includes("任务已创建"), true);
  assert.deepEqual(state.candidates, []);
  assert.deepEqual(state.segments, []);
  assert.equal(state.qualityReport, null);
}

async function testCreateSingleProjectDraftUsesRepoUrl() {
  const calls = [];
  global.fetch = async (path, options = {}) => {
    calls.push({ path, method: options.method || "GET", body: options.body ? JSON.parse(options.body) : null });
    if (path === "/api/jobs" && options.method === "POST") {
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({
          job: {
            id: "GH-SINGLE-20990101-DRAFT",
            type: "single_project_vertical",
            status: "awaiting_render",
            stage: "preparing_plan",
            repo_url: "https://github.com/demo/alpha",
            project_count: 1,
            template_params: {},
            stage_history: [{ stage: "preparing_plan", status: "awaiting_render", at: "2026-06-10T10:00:00" }],
          },
        }),
      };
    }
    if (path === "/api/jobs") {
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ jobs: [{ id: "GH-SINGLE-20990101-DRAFT", type: "single_project_vertical", status: "awaiting_render", stage: "preparing_plan" }] }),
      };
    }
    throw new Error(`unexpected fetch: ${path}`);
  };
  global.alert = (message) => {
    throw new Error(message);
  };

  const timeLabel = { hidden: false };
  const countLabel = { hidden: false };
  const buttons = [];
  const values = {
    jobType: { value: "single_project_vertical" },
    repoUrlField: { hidden: true },
    repoUrl: { value: "https://github.com/demo/alpha" },
    timeWindow: { value: "weekly", parentElement: timeLabel },
    projectCount: { value: "5", parentElement: countLabel },
    visualStyle: { value: "tech_hotspot" },
    renderEngine: { value: "hyperframes" },
    subtitleMode: { value: "large_hook" },
    tone: { value: "professional_review" },
    bgmMode: { value: "default" },
    bgmVolume: { value: "0.13" },
    bgmPath: { value: "" },
    currentJobId: { textContent: "" },
    currentStage: { textContent: "" },
    openJobFolderBtn: { disabled: true },
    currentModelCall: { textContent: "" },
    currentError: { hidden: true, textContent: "" },
    currentDiagnostics: { hidden: true, textContent: "" },
    stageTimeline: { className: "", innerHTML: "", textContent: "" },
    nextActionBtn: { textContent: "", dataset: {}, disabled: false },
    confirmSelectionBtn: { textContent: "", disabled: false },
    saveScriptBtn: { textContent: "", disabled: false },
    refreshCandidatesBtn: { disabled: true },
    regenerateCandidatesBtn: { disabled: true },
    regenerateScriptBtn: { disabled: true },
    regenerateVideoBtn: { disabled: true },
    cancelJobBtn: { disabled: true, textContent: "" },
    candidateRows: { innerHTML: "", querySelectorAll() { return []; } },
    candidateSourceSummary: { textContent: "" },
    narrationSourceSummary: { textContent: "" },
    scriptEditor: { className: "", textContent: "", innerHTML: "" },
    qualityReport: { hidden: false, innerHTML: "", className: "" },
    artifactSummary: { className: "", innerHTML: "", textContent: "" },
    publishActions: { hidden: true, innerHTML: "", querySelectorAll() { return []; } },
    artifactList: { className: "", innerHTML: "", textContent: "" },
    logBox: { textContent: "" },
    historyList: {
      className: "",
      textContent: "",
      innerHTML: "",
      querySelectorAll() {
        return [];
      },
    },
  };
  buttons.push(values.nextActionBtn, values.confirmSelectionBtn, values.saveScriptBtn);
  buttons.forEach((button) => {
    button.dataset ||= {};
  });
  global.document = {
    getElementById(id) {
      return values[id];
    },
    querySelectorAll(selector) {
      assert.equal(selector, "button:not(#closeSettingsBtn):not(#openSettingsBtn)");
      return buttons;
    },
  };

  state.currentJobId = "";
  state.currentJob = null;
  state.candidates = [{ full_name: "old/candidate" }];
  state.segments = [{ id: "intro", text: "old" }];
  state.qualityReport = { status: "caution" };

  await createDraft();

  assert.equal(calls[0].body.type, "single_project_vertical");
  assert.equal(calls[0].body.repo_url, "https://github.com/demo/alpha");
  assert.equal(values.nextActionBtn.dataset.action, "prepare-plan");
  assert.equal(values.logBox.textContent, "单项目竖屏任务已创建。点击“生成计划文件”准备分镜和脚本。\n");
  assert.equal(values.candidateRows.innerHTML.includes("单项目竖屏任务不需要候选列表"), true);
}

function testSingleProjectCandidateEmptyMessage() {
  state.currentJobId = "GH-SINGLE-20990101-DRAFT";
  state.currentJob = { type: "single_project_vertical" };
  assert.equal(candidateEmptyMessage(), "单项目竖屏任务不需要候选列表。生成计划文件后会进入口播确认。");
}

function testSyncJobTypeFieldsTogglesInputs() {
  const timeLabel = { hidden: false };
  const countLabel = { hidden: false };
  const nodes = {
    jobType: { value: "single_project_vertical" },
    repoUrlField: { hidden: true },
    timeWindow: { parentElement: timeLabel },
    projectCount: { parentElement: countLabel },
  };
  global.document = {
    getElementById(id) {
      return nodes[id];
    },
  };

  assert.equal(currentJobType(), "single_project_vertical");
  syncJobTypeFields();
  assert.equal(nodes.repoUrlField.hidden, false);
  assert.equal(timeLabel.hidden, true);
  assert.equal(countLabel.hidden, true);

  nodes.jobType.value = "github_hotlist";
  syncJobTypeFields();
  assert.equal(nodes.repoUrlField.hidden, true);
  assert.equal(timeLabel.hidden, false);
  assert.equal(countLabel.hidden, false);
}

function testRegenerateButtonsFollowStage() {
  const nodes = {
    regenerateCandidatesBtn: { disabled: true },
    regenerateScriptBtn: { disabled: true },
    regenerateVideoBtn: { disabled: true },
    cancelJobBtn: { disabled: true, textContent: "" },
  };
  global.document = {
    getElementById(id) {
      return nodes[id];
    },
  };

  updateRegenerateActions({ id: "job-1", status: "awaiting_input", stage: "awaiting_project_confirmation" });
  assert.equal(nodes.regenerateCandidatesBtn.disabled, false);
  assert.equal(nodes.regenerateScriptBtn.disabled, true);
  assert.equal(nodes.regenerateVideoBtn.disabled, true);
  assert.equal(nodes.cancelJobBtn.disabled, true);

  updateRegenerateActions({ id: "job-1", status: "awaiting_input", stage: "awaiting_script_confirmation" });
  assert.equal(nodes.regenerateCandidatesBtn.disabled, false);
  assert.equal(nodes.regenerateScriptBtn.disabled, false);
  assert.equal(nodes.regenerateVideoBtn.disabled, true);
  assert.equal(nodes.cancelJobBtn.disabled, true);

  updateRegenerateActions({ id: "job-1", status: "completed", stage: "completed" });
  assert.equal(nodes.regenerateCandidatesBtn.disabled, false);
  assert.equal(nodes.regenerateScriptBtn.disabled, false);
  assert.equal(nodes.regenerateVideoBtn.disabled, false);
  assert.equal(nodes.cancelJobBtn.disabled, true);

  updateRegenerateActions({ id: "job-1", status: "running", stage: "composing_video" });
  assert.equal(nodes.regenerateCandidatesBtn.disabled, true);
  assert.equal(nodes.regenerateScriptBtn.disabled, true);
  assert.equal(nodes.regenerateVideoBtn.disabled, true);
  assert.equal(nodes.cancelJobBtn.disabled, false);
  assert.equal(nodes.cancelJobBtn.textContent, "取消任务");

  updateRegenerateActions({ id: "job-1", status: "running", stage: "composing_video", cancel_requested: true });
  assert.equal(nodes.cancelJobBtn.disabled, true);
  assert.equal(nodes.cancelJobBtn.textContent, "取消中");

  updateRegenerateActions({ id: "job-1", status: "awaiting_input", stage: "awaiting_project_confirmation", active: true });
  assert.equal(nodes.regenerateCandidatesBtn.disabled, true);
  assert.equal(nodes.regenerateScriptBtn.disabled, true);
  assert.equal(nodes.regenerateVideoBtn.disabled, true);
  assert.equal(nodes.cancelJobBtn.disabled, false);
}

function testUnverifiedQualityDoesNotHardBlockRender() {
  assert.equal(qualityBlocksRender({ status: "unverified", passed: false }), false);
  assert.equal(qualityBlocksRender({ status: "invalid_json", passed: false }), true);
}

function testTemplatePayloadUsesActiveTemplate() {
  const values = {
    projectCount: { value: "5" },
    visualStyle: { value: "sspai_editorial" },
    renderEngine: { value: "hyperframes" },
    subtitleMode: { value: "standard" },
    tone: { value: "short_video_hook" },
    bgmMode: { value: "none" },
    bgmVolume: { value: "0.32" },
    bgmPath: { value: "" },
  };
  global.document = {
    getElementById(id) {
      return values[id];
    },
  };
  const current = {
    templates: {
      active_template: "github_hotlist_vertical_v1",
      github_hotlist_vertical_v1: { style: "apple_minimal", orientation: "vertical" },
    },
  };

  const payload = templatePayload(current);

  assert.deepEqual(activeTemplateParams(payload), {
    style: "sspai_editorial",
    render_engine: "hyperframes",
    orientation: "vertical",
    project_count: 5,
    subtitle_mode: "standard",
    bgm: "none",
    bgm_volume: 0.32,
    bgm_path: "",
    narration_tone: "short_video_hook",
  });
}

function testApplyTemplateParamsRestoresBgmVolume() {
  const values = {
    visualStyle: { value: "" },
    renderEngine: { value: "" },
    subtitleMode: { value: "" },
    tone: { value: "" },
    bgmMode: { value: "" },
    bgmVolume: { value: "" },
    bgmPath: { value: "" },
    issueNumber: { value: "" },
  };
  global.document = {
    getElementById(id) {
      return values[id];
    },
  };

  applyTemplateParams({ bgm_volume: 0.45, bgm_path: "/tmp/music.mp3" });
  assert.equal(values.bgmVolume.value, "0.45");
  assert.equal(values.bgmPath.value, "/tmp/music.mp3");

  applyTemplateParams({ bgm_volume: "loud" });
  assert.equal(values.bgmVolume.value, "0.07");
}

function testRenderTemplateStylesPopulatesStyleSelect() {
  const visualStyle = { value: "tech_hotspot", innerHTML: "" };
  global.document = {
    getElementById(id) {
      return { visualStyle }[id];
    },
  };

  renderTemplateStyles([
    { style: "tech_hotspot", label: "科技热点风", render_engine: "hyperframes" },
    { style: "apple_minimal", label: "Apple 极简风", render_engine: "hyperframes" },
  ]);

  assert.match(visualStyle.innerHTML, /tech_hotspot/);
  assert.match(visualStyle.innerHTML, /apple_minimal/);
  assert.equal(visualStyle.value, "tech_hotspot");
}

function testRenderArtifactsShowsPreviewAndOfficialVideo() {
  const nodes = {
    artifactList: { className: "", innerHTML: "", textContent: "" },
  };
  global.document = {
    getElementById(id) {
      return nodes[id];
    },
  };

  renderArtifacts({
    job_id: "GH-HOTLIST-20990101-001",
    files: [
      { name: "preview_frames/shot-01.png", size: 1024 },
      { name: "GH-HOTLIST-20990101-001-测试 视频.mp4", size: 2048 },
    ],
  });

  assert.equal(nodes.artifactList.className, "artifact-list");
  assert.match(nodes.artifactList.innerHTML, /preview-thumb/);
  assert.match(nodes.artifactList.innerHTML, /正式版本 · 2 KB/);
  assert.match(nodes.artifactList.innerHTML, /GH-HOTLIST-20990101-001-%E6%B5%8B%E8%AF%95%20%E8%A7%86%E9%A2%91\.mp4/);
}

function testRenderArtifactSummaryShowsPublishMetadata() {
  const nodes = {
    artifactSummary: { className: "", innerHTML: "", textContent: "" },
  };
  global.document = {
    getElementById(id) {
      return nodes[id];
    },
  };

  renderArtifactSummary({});
  assert.equal(nodes.artifactSummary.className, "artifact-summary empty");
  assert.equal(nodes.artifactSummary.textContent, "暂无任务摘要。");

  renderArtifactSummary({
    job: { id: "GH-HOTLIST-20990101-001" },
    readiness_report: { status: "ready", score: 100 },
    publish_pack: { title: "GitHub热榜2个项目", hashtags: ["GitHub", "开源项目", "AI工具"] },
    cover_frame: { status: "ready" },
    latest_model_call: { task: "fact_check", provider: "Mock", model: "mock-model", status: "success" },
    narration_source: { status: "ai_success", provider: "Mock", model: "mock-model" },
    video_versions: [
      { name: "GH-HOTLIST-20990101-001-测试视频.mp4", size: 2048, duration_seconds: 61, is_official: false },
      { name: "GH-HOTLIST-20990101-001-测试视频-v2.mp4", size: 3145728, duration_seconds: 125, is_official: true },
    ],
  });

  assert.equal(nodes.artifactSummary.className, "artifact-summary");
  assert.match(nodes.artifactSummary.innerHTML, /artifact-player/);
  assert.match(nodes.artifactSummary.innerHTML, /artifact-cover/);
  assert.match(nodes.artifactSummary.innerHTML, /ready · 100/);
  assert.match(nodes.artifactSummary.innerHTML, /GitHub热榜2个项目/);
  assert.match(nodes.artifactSummary.innerHTML, /GH-HOTLIST-20990101-001-测试视频-v2\.mp4/);
  assert.match(nodes.artifactSummary.innerHTML, /GH-HOTLIST-20990101-001-%E6%B5%8B%E8%AF%95%E8%A7%86%E9%A2%91-v2\.mp4/);
  assert.match(nodes.artifactSummary.innerHTML, /GitHub \/ 开源项目 \/ AI工具/);
  assert.match(nodes.artifactSummary.innerHTML, /正式版本 · 3\.0 MB · 2:05/);
  assert.match(nodes.artifactSummary.innerHTML, /历史版本 · 2 KB · 1:01/);
  assert.match(nodes.artifactSummary.innerHTML, /脚本质检 · Mock \/ mock-model · success/);
  assert.match(nodes.artifactSummary.innerHTML, /口播: AI Mock \/ mock-model/);
}

function testRenderHistoryJobsShowsOpenAndDeleteActions() {
  const nodes = {
    historyList: {
      className: "",
      innerHTML: "",
      querySelectorAll() {
        return [];
      },
    },
  };
  global.document = {
    getElementById(id) {
      return nodes[id];
    },
  };

  renderHistoryJobs([
    { id: "GH-HOTLIST-20990101-001", status: "completed", stage: "completed" },
  ]);

  assert.equal(nodes.historyList.className, "history-list");
  assert.match(nodes.historyList.innerHTML, /data-job="GH-HOTLIST-20990101-001"/);
  assert.match(nodes.historyList.innerHTML, /data-delete-job="GH-HOTLIST-20990101-001"/);
  assert.match(nodes.historyList.innerHTML, /删除/);
}

function testRenderScheduleQueueShowsPendingAndFailedScheduledJobs() {
  const nodes = {
    scheduleQueue: {
      className: "",
      innerHTML: "",
      textContent: "",
      querySelectorAll() {
        return [];
      },
    },
  };
  global.document = {
    getElementById(id) {
      return nodes[id];
    },
  };

  assert.equal(scheduleQueueLabel({ status: "awaiting_input", stage: "awaiting_script_confirmation" }), "待确认口播");
  assert.equal(scheduleQueueLabel({ status: "failed", error: "GitHub API 失败" }), "失败：GitHub API 失败");

  renderScheduleQueue([
    { id: "GH-HOTLIST-20990101-001", scheduled: true, status: "awaiting_input", stage: "awaiting_project_confirmation" },
    { id: "GH-HOTLIST-20990101-002", scheduled: true, status: "failed", stage: "collecting_candidates", error: "GitHub API 失败" },
    { id: "GH-HOTLIST-20990101-003", scheduled: false, status: "awaiting_input", stage: "awaiting_project_confirmation" },
  ]);

  assert.equal(nodes.scheduleQueue.className, "history-list");
  assert.match(nodes.scheduleQueue.innerHTML, /待确认项目/);
  assert.match(nodes.scheduleQueue.innerHTML, /失败：GitHub API 失败/);
  assert.doesNotMatch(nodes.scheduleQueue.innerHTML, /GH-HOTLIST-20990101-003/);
}

function testRenderStageTimelineShowsRecentHistory() {
  const nodes = {
    stageTimeline: { className: "", innerHTML: "", textContent: "" },
  };
  global.document = {
    getElementById(id) {
      return nodes[id];
    },
  };

  renderStageTimeline([]);
  assert.equal(nodes.stageTimeline.className, "stage-timeline empty");
  assert.equal(nodes.stageTimeline.textContent, "暂无阶段记录。");

  renderStageTimeline([
    { stage: "draft_pending", status: "draft_pending", at: "2026-06-09T09:00:00" },
    { stage: "collecting_candidates", status: "running", at: "2026-06-09T09:01:02" },
    { stage: "awaiting_project_confirmation", status: "awaiting_input", at: "2026-06-09T09:02:03" },
  ]);

  assert.equal(nodes.stageTimeline.className, "stage-timeline");
  assert.match(nodes.stageTimeline.innerHTML, /等待草稿/);
  assert.match(nodes.stageTimeline.innerHTML, /拉取候选/);
  assert.match(nodes.stageTimeline.innerHTML, /等待确认项目/);
  assert.match(nodes.stageTimeline.innerHTML, /awaiting_input · 09:02:03/);
  assert.match(nodes.stageTimeline.innerHTML, /stage-step current/);
}

function testAppendLogLineUsesRealNewlines() {
  const nodes = {
    logBox: { textContent: "[10:00:00] 已完成" },
  };
  global.document = {
    getElementById(id) {
      return nodes[id];
    },
  };

  appendLogLine("正在重新生成口播脚本...");

  assert.equal(nodes.logBox.textContent, "[10:00:00] 已完成\n正在重新生成口播脚本...\n");
  assert.doesNotMatch(nodes.logBox.textContent, /\\n/);

  nodes.logBox.textContent = "暂无日志。";
  appendLogLine("正在重新拉取候选项目...");
  assert.equal(nodes.logBox.textContent, "正在重新拉取候选项目...\n");
}

function testRenderJobRefreshesEmbeddedStageHistory() {
  const values = {
    currentJobId: { textContent: "" },
    currentStage: { textContent: "" },
    openJobFolderBtn: { disabled: true },
    currentModelCall: { textContent: "" },
    currentError: { hidden: true, textContent: "" },
    currentDiagnostics: { hidden: false, textContent: "stale" },
    candidateSourceSummary: { textContent: "" },
    narrationSourceSummary: { textContent: "" },
    visualStyle: { value: "" },
    renderEngine: { value: "" },
    subtitleMode: { value: "" },
    tone: { value: "" },
    bgmMode: { value: "" },
    bgmVolume: { value: "0.13" },
    bgmPath: { value: "" },
    nextActionBtn: { textContent: "", dataset: {}, disabled: false },
    confirmSelectionBtn: { textContent: "", disabled: false },
    saveScriptBtn: { textContent: "", disabled: false },
    stageTimeline: { className: "", innerHTML: "", textContent: "" },
  };
  global.document = {
    getElementById(id) {
      return values[id];
    },
  };

  renderJob({
    id: "GH-HOTLIST-20990101-UI",
    status: "running",
    stage: "collecting_candidates",
    template_params: { visual_style: "tech_dark", subtitle_mode: "standard", narration_tone: "calm_analysis", bgm: "none" },
    stage_history: [
      { stage: "draft_pending", status: "draft_pending", at: "2026-06-09T10:00:00" },
      { stage: "collecting_candidates", status: "running", at: "2026-06-09T10:01:00" },
    ],
  });

  assert.equal(values.currentJobId.textContent, "GH-HOTLIST-20990101-UI");
  assert.equal(values.stageTimeline.className, "stage-timeline");
  assert.match(values.stageTimeline.innerHTML, /拉取候选/);
  assert.equal(values.currentDiagnostics.hidden, true);
  assert.equal(values.nextActionBtn.textContent, "任务执行中");
}

function testBusyRestoreKeepsLatestJobActionState() {
  const buttons = [];
  const values = {
    currentJobId: { textContent: "" },
    currentStage: { textContent: "" },
    openJobFolderBtn: { disabled: true },
    currentModelCall: { textContent: "" },
    currentError: { hidden: true, textContent: "" },
    currentDiagnostics: { hidden: true, textContent: "" },
    visualStyle: { value: "" },
    renderEngine: { value: "" },
    subtitleMode: { value: "" },
    tone: { value: "" },
    bgmMode: { value: "" },
    bgmVolume: { value: "0.13" },
    bgmPath: { value: "" },
    nextActionBtn: { textContent: "生成最终视频（耗时）", dataset: { action: "render-video" }, disabled: false },
    confirmSelectionBtn: { textContent: "", dataset: {}, disabled: true },
    saveScriptBtn: { textContent: "", dataset: {}, disabled: true },
  };
  buttons.push(values.nextActionBtn, values.confirmSelectionBtn, values.saveScriptBtn);
  global.document = {
    getElementById(id) {
      return values[id];
    },
    querySelectorAll(selector) {
      assert.equal(selector, "button:not(#closeSettingsBtn):not(#openSettingsBtn)");
      return buttons;
    },
  };

  setBusy(true);
  renderJob({
    id: "GH-HOTLIST-20990101-RUNNING",
    status: "running",
    stage: "composing_video",
    template_params: {},
  });
  setBusy(false);

  assert.equal(values.nextActionBtn.disabled, true);
  assert.equal(values.nextActionBtn.dataset.action, "running");
  assert.equal(values.nextActionBtn.textContent, "任务执行中");
}

function testSyncDetailStateReplacesCandidateAndScriptSnapshots() {
  state.candidates = [{ full_name: "demo/old" }];
  state.segments = [{ id: "intro", text: "old intro" }];
  state.qualityReport = { status: "caution" };

  syncDetailState({
    candidates: [{ full_name: "demo/new" }],
    segments: [{ id: "intro", text: "new intro" }],
    quality_report: { status: "pass" },
  });

  assert.deepEqual(state.candidates, [{ full_name: "demo/new" }]);
  assert.deepEqual(state.segments, [{ id: "intro", text: "new intro" }]);
  assert.deepEqual(state.qualityReport, { status: "pass" });
}

function testSyncDetailStateStripsSelectedField() {
  state.candidates = [];
  state.segments = [];
  state.qualityReport = null;

  syncDetailState({
    candidates: [
      { full_name: "demo/a", selected: true, score: 50 },
      { full_name: "demo/b", selected: false, score: 20 },
      { full_name: "demo/c", selected: true, score: 60 },
    ],
    segments: [],
    quality_report: null,
  });

  assert.equal(state.candidates.length, 3);
  // selected field should be stripped so that candidateAutoLimit() controls default check
  assert.equal(state.candidates[0].selected, undefined);
  assert.equal(state.candidates[1].selected, undefined);
  assert.equal(state.candidates[2].selected, undefined);
  assert.equal(state.candidates[0].full_name, "demo/a");
  assert.equal(state.candidates[0].score, 50);
}

function testSelectionButtonStateShowsLimit() {
  assert.deepEqual(selectionButtonState(0, 5, true), {
    label: "确认 0 / 5 个项目",
    disabled: true,
  });
  assert.deepEqual(selectionButtonState(3, 5, true), {
    label: "确认 3 / 5 个项目",
    disabled: false,
  });
  assert.deepEqual(selectionButtonState(6, 5, true), {
    label: "已选 6 / 最多 5",
    disabled: true,
  });
  assert.deepEqual(selectionButtonState(6, 5, false), {
    label: "已选 6 / 最多 5",
    disabled: false,
  });
}

function testCandidateDefaultsUseProjectCount() {
  const values = { projectCount: { value: "5" } };
  global.document = {
    getElementById(id) {
      return values[id];
    },
  };
  state.currentJob = { project_count: 5 };

  assert.equal(candidateChecked({}, 0), true);
  assert.equal(candidateChecked({}, 4), true);
  assert.equal(candidateChecked({}, 5), false);
  assert.equal(candidateOrder({}, 0), 1);
  assert.equal(candidateOrder({}, 5), "");
  assert.equal(candidateChecked({ selected: false }, 0), false);
}

function testFormatHelpersForArtifactWorkbench() {
  assert.equal(formatFileSize(0), "0 KB");
  assert.equal(formatFileSize(2048), "2 KB");
  assert.equal(formatFileSize(3145728), "3.0 MB");
  assert.equal(formatDuration(61), "1:01");
  assert.equal(formatDuration(125), "2:05");
  assert.equal(formatDuration(null), "-");
}

function testCandidateSourceLabelShowsSummary() {
  assert.equal(candidateSourceLabel({ summary: "缓存命中 · 启发式评分 · 默认顺序" }), "候选来源：缓存命中 · 启发式评分 · 默认顺序");
  assert.equal(candidateSourceLabel({}), "候选来源：待生成。");
}

function testNarrationSourceLabelShowsFallbackReason() {
  assert.equal(
    narrationSourceLabel({ status: "ai_failed_fallback", reason: "model overloaded", provider: "Mock", model: "mock-model" }),
    "口播: AI失败后模板回退 (model overloaded)",
  );
}

function testModelSummaryLabelCombinesLatestCallAndNarrationSource() {
  assert.equal(
    modelSummaryLabel(
      { task: "candidate_analysis", provider: "Mock", model: "analysis-model", status: "failed" },
      { status: "model_skipped", reason: "未配置模型路由" },
    ),
    "候选分析 · Mock / analysis-model · failed · 口播: 模型跳过后模板回退 (未配置模型路由)",
  );
}

function testRenderPublishActionsShowsCopyButtons() {
  const handlers = [];
  const publishActions = {
    hidden: true,
    innerHTML: "",
    querySelectorAll(selector) {
      assert.equal(selector, "[data-copy-publish]");
      return [{
        dataset: { copyPublish: "title" },
        addEventListener(event, handler) {
          assert.equal(event, "click");
          handlers.push(handler);
        },
      }];
    },
  };
  global.document = {
    getElementById(id) {
      assert.equal(id, "publishActions");
      return publishActions;
    },
  };

  renderPublishActions({
    publish_pack: {
      title: "标题",
      hashtags: ["GitHub", "AI"],
      description: "描述",
    },
  });

  assert.equal(publishActions.hidden, false);
  assert.match(publishActions.innerHTML, /复制标题/);
  assert.match(publishActions.innerHTML, /复制标签/);
  assert.match(publishActions.innerHTML, /复制描述/);
  assert.equal(handlers.length, 1);
}

function testRenderSchedulerShowsAutoScriptMode() {
  const nodes = {
    scheduleEnabled: { checked: false },
    scheduleMode: { value: "" },
    scheduleFrequency: { value: "" },
    scheduleTime: { value: "" },
    scheduleWindow: { value: "" },
    scheduleProjectCount: { value: "" },
    scheduleStatus: { textContent: "" },
  };
  global.document = {
    getElementById(id) {
      return nodes[id];
    },
  };

  renderScheduler({
    enabled: true,
    mode: "auto_script",
    frequency: "daily",
    time: "09:30",
    time_window: "weekly",
    project_count: 5,
    last_run_date: "2099-01-02",
  });

  assert.equal(nodes.scheduleEnabled.checked, true);
  assert.equal(nodes.scheduleMode.value, "auto_script");
  assert.equal(nodes.scheduleStatus.textContent.includes("自动确认前 N 个候选并生成口播草稿"), true);
  assert.equal(nodes.scheduleStatus.textContent.includes("不会自动渲染"), true);
}

async function testCopyTextUsesClipboardWhenAvailable() {
  let copied = "";
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      clipboard: {
        async writeText(value) {
          copied = value;
        },
      },
    },
  });
  global.window = {};

  await copyText("hello", "title");

  assert.equal(copied, "hello");
}

function testQualityNotesPreferStructuredIssues() {
  assert.deepEqual(qualityNotes({
    issues: [{ type: "风险", text: "定位到第 1 段", segment_id: "project-1" }],
    risk_flags: ["旧字段"],
  }), [{ type: "风险", text: "定位到第 1 段", segment_id: "project-1" }]);
}

function testFocusScriptSegmentHighlightsTarget() {
  let focused = false;
  let scrolled = false;
  const classNames = new Set();
  const textarea = { focus() { focused = true; } };
  const segment = {
    classList: {
      add(name) { classNames.add(name); },
      remove(name) { classNames.delete(name); },
    },
    querySelector(selector) {
      assert.equal(selector, "textarea");
      return textarea;
    },
    scrollIntoView() {
      scrolled = true;
    },
  };
  global.document = {
    querySelector(selector) {
      assert.equal(selector, '[data-segment-id="project-1"]');
      return segment;
    },
    querySelectorAll(selector) {
      assert.equal(selector, ".script-segment.focused");
      return [];
    },
  };
  global.window = { setTimeout(fn) { fn(); } };

  assert.equal(focusScriptSegment("project-1"), true);
  assert.equal(focused, true);
  assert.equal(scrolled, true);
  assert.equal(classNames.has("focused"), false);
}

function testRenderQualityReportShowsLocateAction() {
  const clickHandlers = [];
  const qualityReport = {
    hidden: true,
    className: "",
    innerHTML: "",
    querySelectorAll(selector) {
      assert.equal(selector, "[data-quality-segment-id]");
      return [{
        dataset: { qualitySegmentId: "project-1" },
        addEventListener(event, handler) {
          assert.equal(event, "click");
          clickHandlers.push(handler);
        },
      }];
    },
  };
  const textarea = { focus() {} };
  const segment = {
    classList: { add() {}, remove() {} },
    querySelector() { return textarea; },
    scrollIntoView() {},
  };
  global.document = {
    getElementById(id) {
      assert.equal(id, "qualityReport");
      return qualityReport;
    },
    querySelector(selector) {
      assert.equal(selector, '[data-segment-id="project-1"]');
      return segment;
    },
    querySelectorAll(selector) {
      if (selector === ".script-segment.focused") return [];
      throw new Error(`unexpected querySelectorAll: ${selector}`);
    },
  };
  global.window = { setTimeout() {} };
  state.qualityReport = {
    status: "caution",
    summary: "需要处理",
    provider: "Mock",
    model: "mock-model",
    issues: [{ type: "风险", text: "alpha 这一段过度承诺", segment_id: "project-1" }],
  };

  renderQualityReport();

  assert.equal(qualityReport.hidden, false);
  assert.match(qualityReport.innerHTML, /定位段落/);
  assert.equal(clickHandlers.length, 1);
}

async function testProviderTestKeepsUnsavedFormValues() {
  let requestBody = null;
  global.fetch = async (_path, options) => {
    requestBody = JSON.parse(options.body);
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify({
        ok: true,
        saved: false,
        message: "连接成功: ok",
        config: { providers: { providers: [] } },
      }),
    };
  };
  global.alert = (message) => {
    throw new Error(message);
  };

  const settingsMessage = { textContent: "" };
  global.document = {
    getElementById(id) {
      if (id === "settingsMessage") return settingsMessage;
      throw new Error(`unexpected render lookup: ${id}`);
    },
  };

  state.config = {
    providers: {
      providers: [
        { id: "deepseek", type: "openai-compatible", name: "DeepSeek" },
      ],
    },
  };
  const fields = {
    api_key: { value: "sk-draft" },
    base_url: { value: "https://api.deepseek.com" },
    default_model: { value: "deepseek-v4-flash" },
    enabled: { checked: true },
  };
  const card = {
    querySelector(selector) {
      const match = selector.match(/data-field='([^']+)'/);
      return match ? fields[match[1]] : null;
    },
  };
  const button = {
    dataset: { providerTest: "deepseek" },
    disabled: false,
    isConnected: true,
    textContent: "测试",
    closest(selector) {
      return selector === "[data-provider-test]" ? button : card;
    },
  };

  await testProviderFromButton({ target: button });

  assert.equal(requestBody.model, "deepseek-v4-flash");
  assert.equal(requestBody.provider.api_key, "sk-draft");
  assert.equal(requestBody.provider.base_url, "https://api.deepseek.com");
  assert.equal(requestBody.provider.enabled, true);
  assert.equal(fields.api_key.value, "sk-draft");
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "测试");
  assert.match(settingsMessage.textContent, /当前表单尚未保存/);
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
