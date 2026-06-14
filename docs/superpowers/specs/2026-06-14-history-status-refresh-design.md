# History Status Refresh Design

## Context

The right-side history list is rendered from `/api/jobs`, while the active job panel is refreshed from `/api/jobs/:id`. When a background render finishes, the active panel sees `completed`, but the history list can keep showing the stage captured by the previous `loadJobs()` call.

## Approach

Refresh the jobs list once when `refreshCurrentJob()` observes that a previously polled background job is no longer active. This keeps the change local to the existing polling lifecycle and avoids adding constant extra polling for the history list.

## Data Flow

1. A background action starts polling the current job.
2. `refreshCurrentJob()` updates the active job detail.
3. If the job no longer has background work, polling stops.
4. The console calls `loadJobs()` once so the history list reads fresh job summaries.

## Testing

Add a focused frontend static test that mocks:

- an active polling timer,
- `/api/jobs/:id` returning `status=completed`,
- `/api/jobs` returning the refreshed history item.

The test passes when `/api/jobs` is requested after the job completes.
