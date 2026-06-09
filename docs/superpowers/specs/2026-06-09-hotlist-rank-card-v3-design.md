# Hotlist Rank Card V3 Design

## Goal

Improve the GitHub hotlist project intro card when no project screenshot is available. The card should feel more like a polished SaaS product launch or GitHub annual ranking frame, and less like a tech PPT.

The change is limited to the `hotlist_rank_card` visual template and related text cleanup. It will not add screenshot capture, new plan fields, or a new editing workflow.

## Current Problem

The current v2 card has better hierarchy than the original version, but its color emphasis is still too evenly distributed:

- The background grid is visible enough to compete with foreground content.
- Yellow appears in both the top hook and rank badge, weakening the rank badge.
- Green appears on Star, the progress line, and bullet dots, so Star is not the only focus.
- Body text and label text are close in brightness.
- Motion is mostly limited to the progress bar, so a screenshot-free card can feel static.

## Design Direction

Use a calmer dark-blue system with only two accents:

- Green means Star only.
- Yellow means rank only.

Recommended palette:

- Background: `#021426`
- Grid: `#0B3550` at low opacity
- Project name: `#F5F8FF`
- Body text: `#D7E3F5`
- Labels: `#7FA3C8`
- Star accent: `#2EF2C2`
- Rank accent: `#FFD84D`
- Muted line and bullet: `#4A5D75`

The top hook should become a restrained dark-blue pill with body or label-colored text, not yellow.

## Motion

Use the existing `progress` parameter inside the PIL renderer. Do not change the video pipeline frame scheduler in this iteration.

The card animation should be subtle:

- Background grid drifts by a few pixels over the shot.
- Project name fades in and rises slightly during the first third of the shot.
- Project name gets a very light glow, without outline or heavy shadow.
- Rank badge pops once, then holds still.
- Star text fades/scales in after the title.
- Muted line expands from center to both sides.
- The three detail rows appear one by one with short staggered fades.

Avoid particle effects, strong shaking, repeated bouncing, or fast flashing.

## Implementation Scope

Update `src/composer/vertical.py`:

- Adjust `_hotlist_bg` colors and grid opacity.
- Add small drawing helpers only if they reduce repeated logic.
- Update `_render_hotlist_rank_card_frame` palette.
- Add progress-based alpha and y-offset calculations for the title, Star, line, rank, and detail rows.
- Keep subtitle rendering unchanged.

Update `src/console/jobs.py` only if text cleanup directly affects on-screen card copy.

Update tests only for behavior that should stay stable, such as removing visual-potential rating prefixes from card text.

## Acceptance Criteria

- The generated rank card preview clearly prioritizes project name, Star, and rank.
- Green appears only on the Star text.
- Yellow appears only on the rank badge.
- The top hook no longer uses yellow.
- Detail row bullets and separator line use muted gray-blue.
- Motion is visible in the final video render without feeling noisy.
- Existing console job tests pass.
- `compileall` and `git diff --check` pass.

## Out Of Scope

- Project screenshots.
- README or homepage capture improvements.
- New shot plan schema.
- New UI controls for theme configuration.
- Full redesign of opening, ranking overview, closing, or subtitle templates.
