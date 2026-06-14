# ByteDance Hotlist Visual Refresh Design

## Context

The `bytedance_product` hotlist style needs a focused visual refresh for the intro screen. The user confirmed the browser preview direction on 2026-06-14.

## Scope

Only update the existing `bytedance_product` profile and its style-specific CSS in the shared hotlist template. Do not create a new template or refactor unrelated styles.

## Visual Rules

- Use ByteDance blue `#3D7EFF` as the primary blue token.
- Change the top intro badge to a dark capsule with a small blue status dot.
- Keep `TOP 5` in the headline, but reduce the intro title weight to `500`.
- Make the three intro stat cards light-gray surfaces with centered content.
- Highlight the estimated daily star value, such as `2.8k`, in ByteDance blue.
- Add top and bottom dividers around the language tag row.
- Render the intro date as a thin-border capsule with a right-side trend mark.
- Change the bottom highlight card to a left blue border with a pale blue gradient background, similar to Feishu card styling.

## Acceptance

- Rendering `bytedance_product` includes the new color token and intro CSS rules.
- Existing date and issue fields remain visible.
- The change is limited to the ByteDance style surface unless shared markup needs a minimal class hook.
- Existing hotlist rendering tests pass.
