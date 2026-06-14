# BGM Volume Control Design

## Goal

Add a visible control in the console for global background music volume, and make that value affect video rendering.

## Scope

- Add a `BGM 音量` control near the existing `BGM` and `BGM 路径` fields in the console sidebar.
- Persist the value in `template_params.bgm_volume` with the rest of the render template settings.
- Apply the value when rendering both hotlist HyperFrames videos and pipeline-rendered videos.
- Keep existing BGM mode behavior:
  - `default` uses the first audio file in `bgm/`.
  - `custom` uses `bgm_path`.
  - `none` disables BGM, so the volume value is saved but not used.

## Non-Goals

- No music library picker.
- No upload flow.
- No fade-in or fade-out controls.
- No redesign of the console sidebar.

## UI

The console sidebar gets one additional field:

- Label: `BGM 音量`
- Default: `0.13`
- Range: `0.0` to `1.0`
- Step: `0.01`

The preferred UI is a range slider with a small percentage readout. If that requires too much styling churn, use a numeric input with the same range and step. The control should stay visually close to `BGM` and `BGM 路径` so users understand it belongs to background music.

## Data Flow

`currentTemplateParams()` reads the control value and normalizes empty or invalid input to `0.13`.

`templatePayload()` stores the value under the active template:

```json
{
  "bgm_volume": 0.13
}
```

`applyTemplateParams()` restores the saved value when loading a job or config. Existing jobs without `bgm_volume` fall back to `0.13`.

The backend reads `job.template_params.bgm_volume`, clamps it to `0.0-1.0`, and passes it to:

- `post_process_video(..., bgm_volume=value)` for HyperFrames hotlist rendering.
- `run_pipeline(..., bgm_volume=value)` for pipeline rendering.

`src.composer.bgm.post_process_video` already accepts `bgm_volume`, so no change is needed in the mixer implementation.

## Validation

- Frontend unit tests verify payload creation and saved-value restore for `bgm_volume`.
- Backend tests verify render paths pass the configured volume to the post-processing or pipeline call.
- Existing BGM tests continue to verify the default `0.13` behavior.

## Acceptance Criteria

- Users can adjust global BGM volume from the console before creating or rendering a job.
- The selected value is saved in the job template parameters.
- Reloading a job restores the saved volume.
- Rendering uses the selected value for BGM mixing.
- `bgm: "none"` still disables BGM regardless of the saved volume.
