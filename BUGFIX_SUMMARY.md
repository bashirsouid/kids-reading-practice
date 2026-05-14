# Root Cause Analysis: Random Story Generation Never Finishes

## Symptoms
- Clicking "Generate Story" with random mode starts the job but never completes
- No error messages shown in the UI
- No progress logs visible — the process appears dead
- The spinner keeps spinning indefinitely

---

## Root Cause: THREE Interacting Bugs

### Bug 1 (CRITICAL): `job_worker()` references undefined names — `backend/jobs.py`

The `job_worker()` coroutine referenced bare `jobs` and `job_queue` names at module level:
```python
# BROKEN — these names don't exist in this module's scope
async def job_worker():
    while True:
        job_id = await job_queue.get()    # ← NameError!
        job = jobs.get(job_id)             # ← NameError!
```

The correct names are `global_state.job_queue` and `global_state.jobs`. This caused a silent `NameError` that killed the worker coroutine at startup. The HTTP API happily created jobs and added them to the queue, but no worker was alive to process them. Hence: no "START PROCESSING JOB" log ever appears.

**Fix**: Change to `global_state.job_queue.get()` and `global_state.jobs.get()`.

---

### Bug 2 (CRITICAL): `api_proceed_to_next_stage` dead code + missing stage — `backend/api/routes.py` and `server.py`

Two problems in one function:

**Problem A — Dead code / wrong scope:**
```python
# BROKEN CODE
if job.stage == "reference":
    if not job.story or not job.story.master_reference:
        raise HTTPException(...)
    elif job.stage == "panel_breakdown":    # ← DEAD CODE: impossible inside "reference" block
        if not job.story or not job.story.panels:
            raise HTTPException(...)
    job.stage = "panels"                    # ← Only runs inside "reference" branch!
```

When stage is `"reference"`, the `elif job.stage == "panel_breakdown"` can never be true (we already know it's `"reference"`). And `job.stage = "panels"` only executes inside the reference branch — when called from `"panel_breakdown"`, nothing happens.

**Problem B — Missing `"synopsis_confirmation"` stage handler:**
After the story synopsis is generated, `process_job()` sets `job.stage = "synopsis_confirmation"` and waits for the user to click Next. The frontend (StoryContentPage) calls `/api/proceed`, but the endpoint had **no branch** for `"synopsis_confirmation"`. So the job stayed stuck at this stage forever.

**Fix**: Use `if/elif` at the same level. Add a `"synopsis_confirmation"` branch that sets `job.wait_for_user = False` (signaling `process_job()` to continue to reference generation).

---

### Bug 3 (MINOR): No WebSocket error handling in ComicInfoPage — `frontend/src/pages/ComicInfoPage.tsx`

The WebSocket `onmessage` handler only checked for `data.story` and never handled `data.error`. If the backend sent an error update, the frontend silently ignored it, leaving users with a spinning spinner and no explanation.

**Fix**: Add a check for `data.error` before checking for `data.story`:
```typescript
if (data.error) {
  setError(data.error);
  setIsGenerating(false);
  return;
}
```

---

## The Corrected Generation Flow

1. User clicks "Generate Story" → `POST /api/generate` → job created, queued
2. **Worker** (now alive) picks up job → generates synopsis → generates title
3. Worker sets stage to `"synopsis_confirmation"`, sets `wait_for_user = True`
4. Frontend shows StoryContentPage, user sees generated synopsis
5. User clicks "Next" → `POST /api/proceed` → **now handled** (`synopsis_confirmation` branch), sets `wait_for_user = False`
6. Worker wakes up, generates reference profile (characters, art style)
7. Worker sets stage to `"reference"`, sets `wait_for_user = True`
8. Frontend shows StyleReferencePage, user generates/regenerates reference image
9. User clicks "Next" → `POST /api/proceed` → stage advances to `"panel_breakdown"`
10. Frontend shows PanelBreakdownPage, generates panel descriptions
11. User clicks "Next" → `POST /api/proceed` → stage advances to `"panels"`
12. Worker generates panel images → stage `"complete"` → done!