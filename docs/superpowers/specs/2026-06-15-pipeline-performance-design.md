# Pipeline Performance Optimization Design

## Context

`docs/pipeline-analysis-report.md` identifies several performance bottlenecks in the legacy pipeline. Code review confirms the most valuable issues are in the old `src/pipeline.py` vertical and hotlist paths, `src/tts/edge_tts.py`, `src/planner/capture.py`, and `src/composer/vertical.py`.

The Console and Hotlist v2 flows already have some separate optimizations and must keep their current workflow semantics.

## Goals

- Reduce runtime for legacy vertical and hotlist video generation.
- Keep generated artifact names, JSON checkpoints, stage callbacks, and output paths stable.
- Keep concurrency conservative so network-dependent services remain reliable.
- Add focused tests for ordering, reuse, and pipeline orchestration.

## Non-Goals

- Do not merge LLM calls in the Console workflow.
- Do not merge BGM mixing and loudness normalization.
- Do not add persistent cross-run asset caching.
- Do not change Hotlist v2 data selection or rendering semantics.

## Design

### Pipeline Orchestration

In `src/pipeline.py`, the legacy hotlist path will fetch up to 10 repositories concurrently with `asyncio.gather`. The final `projects` and `manifests` lists will preserve the input URL order.

For vertical, hotlist, from-plan, and desktop-review paths where TTS and asset capture or recording do not depend on each other, the pipeline will run them concurrently after script and plan files have been written. After capture completes, updated asset manifests will still be written before composition.

### TTS Generation

`generate_all_audio` will generate missing segments with bounded concurrency. Existing valid mp3 files will still be reused, single-segment retry behavior will stay in `generate_audio_segment`, and the returned file list will remain ordered by segment index.

The default concurrency should be small, around 3, to avoid making Edge TTS less reliable.

### Asset Capture

Image downloads will run concurrently. Browser screenshots will remain conservative: reuse the launched browser, keep ordering stable, and avoid high page-level concurrency.

Screenshot waiting will prefer page load state plus a short settling delay instead of relying only on a fixed long sleep. Existing placeholder fallback behavior stays unchanged.

### Vertical Rendering

`compose_vertical_video` will use per-render in-memory caches:

- Loaded asset images by path.
- Static blurred background base by asset path and dimensions.
- Rendered frame arrays by shot metadata and discretized frame progress.

The cache will exist only during one composition call. It will not write cache files or change visual treatments.

## Testing

Focused tests should verify:

- TTS returns files in segment order while running missing segments concurrently.
- Existing valid audio files are reused.
- Legacy hotlist repository fetches are scheduled concurrently and keep output order.
- Pipeline paths can run TTS and capture/recording concurrently where intended.
- Vertical composition avoids repeated rendering for the same discretized frame when frame caching is active.

Run the relevant test subset after implementation, then a broader test command if runtime is reasonable.

## Risks

- Network services can reject overly aggressive concurrency, so concurrency limits must stay conservative.
- Playwright `networkidle` can wait too long on some pages, so screenshot waiting needs a timeout and a short fallback delay.
- Frame caching can increase memory use, so the cache should be scoped to one composition call and keyed only by the limited dynamic frame grid already used by the renderer.
