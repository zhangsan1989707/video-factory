const assert = require("node:assert/strict");
const { activeTemplateParams, api, nextActionForJob, renderArtifacts, renderArtifactSummary, renderDiagnostics, renderJob, renderStageTimeline, selectionButtonState, setBusy, state, syncDetailState, templatePayload } = require("../src/console/static/app.js");

async function run() {
  await testJsonSuccess();
  await testJsonError();
  await testTextError();
  testRenderDiagnosticsIncludesLatestModelCall();
  testFailedJobsExposeRetryActions();
  testPlanStagesExposeSeparateActions();
  testTemplatePayloadUsesActiveTemplate();
  testRenderArtifactsShowsPreviewAndOfficialVideo();
  testRenderArtifactSummaryShowsPublishMetadata();
  testRenderStageTimelineShowsRecentHistory();
  testRenderJobRefreshesEmbeddedStageHistory();
  testBusyRestoreKeepsLatestJobActionState();
  testSyncDetailStateReplacesCandidateAndScriptSnapshots();
  testSelectionButtonStateShowsLimit();
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

function testFailedJobsExposeRetryActions() {
  const cases = [
    ["collecting_candidates", "collect-candidates", "重试：拉取候选"],
    ["analyzing_candidates", "collect-candidates", "重试：分析候选"],
    ["generating_script", "confirm-selection", "重试：生成口播"],
    ["preparing_plan", "prepare-plan", "重试：准备计划"],
    ["capturing_assets", "render-video", "重试：采集素材"],
    ["generating_tts", "render-video", "重试：生成语音"],
    ["composing_video", "render-video", "重试：合成视频"],
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

function testTemplatePayloadUsesActiveTemplate() {
  const values = {
    projectCount: { value: "5" },
    visualStyle: { value: "black_gold" },
    subtitleMode: { value: "standard" },
    tone: { value: "short_video_hook" },
    bgmMode: { value: "none" },
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
      github_hotlist_vertical_v1: { style: "tech_dark", orientation: "vertical" },
    },
  };

  const payload = templatePayload(current);

  assert.deepEqual(activeTemplateParams(payload), {
    style: "black_gold",
    orientation: "vertical",
    project_count: 5,
    subtitle_mode: "standard",
    bgm: "none",
    bgm_path: "",
    narration_tone: "short_video_hook",
  });
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
    video_versions: [
      { name: "GH-HOTLIST-20990101-001-测试视频.mp4" },
      { name: "GH-HOTLIST-20990101-001-测试视频-v2.mp4" },
    ],
  });

  assert.equal(nodes.artifactSummary.className, "artifact-summary");
  assert.match(nodes.artifactSummary.innerHTML, /ready · 100/);
  assert.match(nodes.artifactSummary.innerHTML, /GitHub热榜2个项目/);
  assert.match(nodes.artifactSummary.innerHTML, /GH-HOTLIST-20990101-001-测试视频-v2\.mp4/);
  assert.match(nodes.artifactSummary.innerHTML, /GH-HOTLIST-20990101-001-%E6%B5%8B%E8%AF%95%E8%A7%86%E9%A2%91-v2\.mp4/);
  assert.match(nodes.artifactSummary.innerHTML, /GitHub \/ 开源项目 \/ AI工具/);
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

function testRenderJobRefreshesEmbeddedStageHistory() {
  const values = {
    currentJobId: { textContent: "" },
    currentStage: { textContent: "" },
    openJobFolderBtn: { disabled: true },
    currentModelCall: { textContent: "" },
    currentError: { hidden: true, textContent: "" },
    currentDiagnostics: { hidden: false, textContent: "stale" },
    visualStyle: { value: "" },
    subtitleMode: { value: "" },
    tone: { value: "" },
    bgmMode: { value: "" },
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
    subtitleMode: { value: "" },
    tone: { value: "" },
    bgmMode: { value: "" },
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

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
