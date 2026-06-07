# Timeout Investigation Summary

## Files with timeout settings

- **backend/api/routes.py**
  - Line 182: `await asyncio.wait_for(..., timeout=30)` – WebSocket receive timeout.
  - Line 555-560: Reference generation timeout set to **90 seconds**.
  - Line 656-659: Panel generation timeout set to **60 seconds per panel**.

- **backend/jobs.py**
  - Lines 112, 117, 167, 194, 259: Various timeouts for synopsis, panel, and other generation steps (30‑90 seconds).
  - Lines 376‑379: Panel generation timeout **60 seconds per panel**.

- **generator.py**
  - Line 149: HTTP request timeout set to **120 seconds** for image generation service.
  - Line 673: Timeout **180 seconds** (context unclear).
  - Lines 695, 711: Image download timeout **60 seconds**.

## Potential areas to extend by 50%

- Increase the **panel generation** timeout from 60 s to **90 s** (both in `routes.py` and `jobs.py`).
- Raise the **image download** timeout from 60 s to **90 s** in `generator.py`.
- Consider bumping the **overall request** timeout from 120 s to **180 s** if image generation frequently exceeds the current limit.

## Recommendations

1. Locate the timeout constants and replace the hard‑coded values with variables (e.g., `PANEL_TIMEOUT = 60`).
2. Adjust those constants by a factor of 1.5.
3. Add documentation/comments indicating the new limits.
4. Run integration tests to verify that longer timeouts do not cause other side‑effects.

---
*Scout summary saved to `./tmp/scout_timeout_report.md`*\nEOF
