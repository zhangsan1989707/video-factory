# Pipeline Timing and Benchmark Design

## Context

The legacy pipeline now has bounded concurrency and in-memory render caching. The next need is measurement: each real run should show which stage still dominates runtime.

Existing stage callbacks are used by the Console and tests, so timing must not change the callback signature or UI behavior.

## Goals

- Write a machine-readable timing report for each completed pipeline run.
- Keep timing scoped to existing pipeline stages and artifact directories.
- Provide a small manual benchmark entrypoint for repeatable local checks.
- Avoid machine-dependent performance thresholds in tests.

## Non-Goals

- Do not change the Web Console UI.
- Do not write timing data into Console `stage_history`.
- Do not make slow real e2e benchmarks part of default tests.
- Do not change generated video contents.

## Design

### Timing Report

`src/pipeline.py` will create a lightweight timing collector inside `run_pipeline`. It will record:

- `started_at`
- `finished_at`
- `total_seconds`
- `stages`, each with `name` and `seconds`

The report will be written as `timing_report.json` in the current output directory after a successful pipeline run. If the pipeline raises an exception, it will not write a success-looking report.

The existing `stage_callback(stage, message)` signature will remain unchanged. Timing collection will wrap internal stage boundaries without changing callback consumers.

### Stage Boundaries

Timing should cover the high-value stages already visible in the pipeline:

- repository fetching
- brief generation
- manifest generation
- shot plan generation
- script generation
- asset capture or browser recording
- TTS generation
- video composition
- post processing

When capture and TTS run concurrently, the report should record the combined concurrent block and, where practical, separate child durations for capture and TTS.

### Benchmark Script

Add `scripts/benchmark_pipeline.py` as a manual helper. It will run a fixed or user-provided command through the existing pipeline and print:

- output path
- total seconds
- per-stage timing summary
- timing report path

By default it should use a safe dry-run style invocation. A `--real-hotlist` option can run a real two-repository hotlist sample for manual checks.

### Documentation

Add `docs/pipeline-benchmark.md` with recommended commands and guidance for comparing timing reports before and after changes.

### Testing

Focused tests should verify:

- successful runs write `timing_report.json`
- existing stage callback behavior remains intact
- failed runs do not write a success timing report
- the benchmark helper can format a timing summary without running network-dependent work

## Risks

- Too much timing detail can make the pipeline harder to read, so helpers should stay small and local.
- Concurrent capture/TTS timing can be misleading if represented as additive totals, so the report must clearly include the combined block duration.
