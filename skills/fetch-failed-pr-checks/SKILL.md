---
name: fetch-failed-pr-checks
description: Use when the user asks to check / fetch / list / show failed CI checks (GitHub Actions, external CI) on a GitHub PR — including details/logs of the failures. Pulls the statusCheckRollup, filters to non-passing terminal states, and (for GitHub Actions runs) appends the failed-step log excerpt. Auto-approved globally.
---

# Fetch failed CI checks (and their failed-step logs) for a PR

## How to run

```bash
bash ~/.claude/skills/fetch-failed-pr-checks/scripts/fetch-failed-pr-checks.sh <PR_NUMBER> [--repo OWNER/REPO] [--max-log-lines N]
```

- `<PR_NUMBER>` — required.
- `--repo OWNER/REPO` — optional; defaults to the cwd repo via `gh repo view`.
- `--max-log-lines N` — cap each failed job's log excerpt at N lines (default 200). Pass `0` to skip log fetching entirely.

## Output

Always emits **both**:

- **Markdown to stdout** — one section per failed check: workflow / job name, conclusion, details URL, and (when available) the failed-step log excerpt inside a collapsible `<details>` block.
- **JSON file** at `${TMPDIR:-/tmp}/failed-pr-checks-<pr>-<utc-ts>.json`. Path printed on the last line, prefixed `JSON: `. Schema:

  ```json
  {
    "pr": 70,
    "repo": "owner/name",
    "failed_checks": [
      {
        "typename": "CheckRun" | "StatusContext" | "WorkflowRun",
        "name": "test",
        "workflow_name": "CI",
        "conclusion": "FAILURE",
        "status": "COMPLETED",
        "details_url": "https://github.com/.../actions/runs/12345/job/67890",
        "completed_at": "2026-05-03T07:42:13Z",
        "run_id": "12345",
        "job_id": "67890",
        "log_excerpt": "..."
      }
    ]
  }
  ```

## What counts as "failed"

Any check whose `conclusion` (CheckRun/WorkflowRun) or `state` (StatusContext) is one of:

- `FAILURE`
- `TIMED_OUT`
- `CANCELLED`
- `ACTION_REQUIRED`
- `STARTUP_FAILURE`
- `ERROR` (StatusContext only)

In-progress / pending / skipped checks are excluded.

## Steps

1. Run the script with the PR number the user gave (or infer from `gh pr view --json number -q .number`).
2. Read the Markdown output and present a concise summary — count, which workflows / jobs failed, the most likely root cause if visible in the log excerpt.
3. The log excerpt is `--log-failed` filtered, so it already targets failing steps. For deeper inspection, the JSON has `run_id` / `job_id` — call `gh run view --job <job_id> --log` for the full log, or follow the `details_url`.

## Why use this instead of `gh pr checks` / `gh run view` directly

- One call gives you all failed checks plus their failed-step logs, in both Markdown and JSON form.
- Handles the three `statusCheckRollup` typenames (CheckRun / StatusContext / WorkflowRun) — `gh pr checks` doesn't expose StatusContext cleanly.
- Auto-approved — no permission prompt.
- Truncated logs (default 200 lines per job) keep output bounded; raise with `--max-log-lines` when you need more.

If the script is missing a flag you need, extend the script rather than reaching for `gh` directly.
