# Pipeline Benchmark

Use this when checking whether pipeline performance changes helped in practice.

## Safe Dry Run

This command creates a tiny local from-plan fixture and writes a timing report. It does not call GitHub, TTS, Playwright, or FFmpeg.

```bash
.venv/bin/python scripts/benchmark_pipeline.py --output output/benchmark-dry-run
```

Read the generated report:

```bash
cat output/benchmark-dry-run/timing_report.json
```

## Real Hotlist Sample

This command runs the real legacy hotlist path with two stable public repositories. It can call GitHub, Playwright, Edge TTS, MoviePy, and FFmpeg.

```bash
.venv/bin/python scripts/benchmark_pipeline.py \
  --real-hotlist \
  --no-bgm \
  --output output/benchmark-hotlist/final.mp4
```

To use your own repositories:

```bash
.venv/bin/python scripts/benchmark_pipeline.py \
  --real-hotlist \
  --no-bgm \
  --repo https://github.com/owner/repo-a \
  --repo https://github.com/owner/repo-b \
  --output output/benchmark-hotlist/final.mp4
```

## Comparing Runs

Compare `timing_report.json` files by stage:

- `repository_fetch`: GitHub API and repo metadata.
- `capture_assets`: image download and webpage screenshots.
- `generate_tts`: Edge TTS audio generation.
- `capture_and_tts_concurrent`: elapsed wall time for the concurrent capture/TTS block.
- `compose_video`: MoviePy/Pillow composition and encoding.
- `post_processing`: BGM and loudness normalization.

For concurrent blocks, do not add child stages together. Use the `*_concurrent` stage as the wall-clock cost of that block.
