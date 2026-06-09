# Hotlist Vertical MVP Design

## Goal

Turn the existing vertical pipeline from a single screenshot review into a GitHub hotlist-style short video prototype. The first MVP keeps the current one-repo CLI input, but gives the output the structure of a weekly hotlist segment: opening trend, rank card, evidence screenshot, feature breakdown, source proof, keyword closing.

## Scope

- Keep the existing `--vertical` and `--from-plan` workflows.
- Keep the existing `ShotPlan` and `VideoScript` model shape.
- Replace the hard-coded TypeWords shot plan with project-derived hotlist shots.
- Add multiple vertical render templates inside `src/composer/vertical.py`.
- Do not change desktop-review generation.
- Do not add new dependencies.

## Design

`src/planner/shot_plan.py` will generate 7 shots:

1. `opening_trend`: series intro and trend hook.
2. `ranking_overview`: ranking-style summary with stars, language, and topics.
3. `rank_card`: hero rank card for the repo.
4. `feature_breakdown`: proof points from the brief.
5. `evidence_screenshot`: real product, README, or repo asset.
6. `source_proof`: GitHub source proof and suitability judgment.
7. `keyword_closing`: keywords and comment prompt.

`src/composer/vertical.py` will route each shot by `visual_treatment` prefix. If a shot uses a screenshot template, it will still render the captured asset. If it uses a data-card template, it will render text and metrics from the shot/script without needing new model fields.

## Data Flow

Existing flow remains:

GitHub repo info -> creative brief -> asset manifest -> shot plan -> script -> TTS -> captured assets -> vertical composer.

The shot subtitle remains the narration source. Visual metadata is encoded in `visual_treatment` using simple prefixes such as `opening_trend`, `ranking_overview`, and `keyword_closing`.

## Testing

- Run `python -m compileall src`.
- Run a dry run against an existing URL and inspect `shot_plan.json`.
- Render from plan and inspect output metadata.
- Generate a contact sheet to verify the video has multiple visual templates, not repeated screenshot frames.

## Non-Goals

- Multi-repo hotlist input.
- Automatic GitHub trending scrape.
- New animation framework.
- Perfect visual polish.
