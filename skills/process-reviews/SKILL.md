---
name: process-reviews
description: Use when the user asks to process / triage / address / handle PR reviews from CodeRabbit, SonarQube, and CI all together. First waits (polling every 5 min, max 30 min) until CodeRabbit, Sonar, and every CI check on the PR are in a terminal state. Then fetches unresolved threads from both code-review sources plus failed CI checks, validates each against the actual code / log, handles invalid ones in place (reply on thread / NOSONAR comment), and presents a plan for fixing the valid ones (split into logical groups if more than 3).
---

# Process unresolved review feedback (CodeRabbit + SonarQube + failed CI)

Combine CodeRabbit, SonarQube, and failed CI feedback into a single triage workflow. Stops at a written plan — does not start fixing.

## Inputs

- PR number. If the user didn't say, infer from the cwd: `gh pr view --json number -q .number`. If that fails, ask the user.
- Repository (auto-detected from cwd via `gh repo view`, or pass explicitly).
- SonarQube project key. Resolve via the sonarqube MCP server's standard lookup order: `.sonarlint/connectedMode.json` → `sonar-project.properties` → `pom.xml`/`build.gradle*`/`package.json` → CI config. If still unresolved, run `sonarqube:sonar-list-projects` (or `mcp__sonarqube__search_my_sonarqube_projects`) and pick the right one with the user's confirmation.

## Steps

### 0. Wait until reviews and CI are done

Don't fetch anything until every status check on the PR is in a terminal state. Mid-flight checks mean late-arriving CodeRabbit nitpicks, Sonar issues that haven't been computed yet, or test failures that haven't reported — triaging that is wasted work.

A check is **non-terminal** if it's:
- a `StatusContext` with `state` ∈ {`PENDING`, `EXPECTED`} — this is how CodeRabbit reports, and
- a `CheckRun` or `WorkflowRun` with `status` ∈ {`QUEUED`, `IN_PROGRESS`, `WAITING`, `REQUESTED`, `PENDING`} — this is how Sonar and GitHub Actions jobs report.

Anything else (`SUCCESS` / `FAILURE` / `ERROR` / `COMPLETED`) counts as terminal — even a failed check is "done". Checks that are *missing entirely* from the rollup (e.g. CodeRabbit not installed on the repo) do not block — only checks that exist AND are non-terminal do.

Run this loop. Bail with a non-zero exit (skill aborts, no fetch, no plan) if the gate doesn't clear within 30 minutes:

```bash
PR=<pr-number>
REPO=<owner/repo>
START=$(date +%s)
TIMEOUT=$((30 * 60))

while :; do
  pending=$(gh pr view "$PR" --repo "$REPO" --json statusCheckRollup --jq '
    [.statusCheckRollup[]
     | select(
         (.__typename == "StatusContext"
            and (.state == "PENDING" or .state == "EXPECTED"))
         or ((.__typename == "CheckRun" or .__typename == "WorkflowRun")
            and (.status == "QUEUED" or .status == "IN_PROGRESS"
              or .status == "WAITING" or .status == "REQUESTED"
              or .status == "PENDING"))
       )
     | (.name // .context)] | join(", ")')

  if [[ -z "$pending" ]]; then
    break
  fi

  elapsed=$(( $(date +%s) - START ))
  echo "Waiting on: $pending (elapsed $((elapsed/60))m). Sleeping 5m."

  if (( elapsed >= TIMEOUT )); then
    echo "Gate timed out after 30 min. Still pending: $pending. Aborting."
    exit 1
  fi

  sleep 300
done
```

Once the loop exits cleanly, proceed to Step 1.

### 1. Fetch all unresolved feedback (in parallel)

- **CodeRabbit** — invoke the `fetch-coderabbit-threads` skill (script: `~/.claude/skills/fetch-coderabbit-threads/scripts/fetch-coderabbit-threads.sh <PR>`). Read the JSON file it writes (`JSON: <path>` last line of stdout) — that's the structured input for the rest of this skill.
- **SonarQube** — invoke the `sonarqube:sonar-list-issues` skill, scoped to the same PR if Sonar PR analysis is configured, otherwise to the branch. Filter to unresolved issues only (statuses `OPEN`, `CONFIRMED`, `REOPENED`).
- **Failed CI** — invoke the `fetch-failed-pr-checks` skill (script: `~/.claude/skills/fetch-failed-pr-checks/scripts/fetch-failed-pr-checks.sh <PR>`). Read its JSON for the failed checks plus failed-step log excerpts.

Run all three in parallel — they're independent.

### 2. Merge into one normalised list

Build a single in-memory list. Each entry:

- `source`: `"coderabbit"` | `"sonar"` | `"ci"`
- `file`: path relative to repo root, or `null` for CI failures (the failure may not map to a single file)
- `line`: integer or `null`
- `severity`: `critical` | `major` | `minor` | `info` (best-effort mapping; CodeRabbit emoji → severity: 🔴/⚠️ Potential issue → major, 🟡/💡 → minor, 💤 → info; CI failures default to `major`)
- `rule`: Sonar rule key, CodeRabbit thread/comment ID, or CI workflow/job name
- `summary`: one-line description (for CI: `<workflow> / <job>` failed at conclusion `<X>`)
- `body`: full text (CodeRabbit comment body, Sonar issue message + rule description, or the failed-step log excerpt)
- `ref`: thread URL (CodeRabbit), Sonar issue key, or run/job URL (CI) — needed for invalid handling and for surfacing in the plan

Don't dedupe across sources blindly — if multiple sources flag the same area, keep them all. They need separate invalid-handling channels.

### 3. Validate each issue

For each entry, classify as VALID or INVALID using a source-appropriate signal:

- **CodeRabbit / Sonar** — READ the cited file at the cited line(s). Apply the user's global rules from `~/.claude/CLAUDE.md` (trust internal code, validate only at boundaries; imports at the top; etc.). Lean toward VALID when uncertain — false positives are easier to defend later than missed bugs now.
- **CI failure** — READ the failed-step log excerpt in the JSON. Classify as INVALID only when the failure is clearly unrelated to this PR's changes (network blip / runner died / well-known flaky test that the user has previously confirmed is flaky / out-of-date Action that times out before doing anything). Otherwise VALID. **A test failure that points at code this PR touched is always VALID** — don't argue your way out of it.

For each entry, write a one-line classification rationale (`why-valid` or `why-invalid`) — used in steps 4 and 5.

### 4. Handle INVALID issues in place

#### CodeRabbit (invalid)

**Never** call the resolve mutation. Post a reply on the thread tagging `@coderabbitai` with the rationale, using the `reply-to-pr-thread` skill (auto-approved):

```bash
echo "@coderabbitai <one or two sentences explaining why this is invalid / where it was already addressed>" | \
  bash ~/.claude/skills/reply-to-pr-thread/scripts/reply-to-pr-thread.sh \
    <discussion-url-from-fetch-coderabbit-threads-output>
```

Reference the relevant `CLAUDE.md` rule or commit hash when possible — gives the bot and the human reviewer something concrete to evaluate against. Do NOT call `gh api .../replies` directly; the skill is the only allowed channel.

#### SonarQube (invalid)

NOSONAR is a code change, and this skill stops at the plan — so do **not**
apply NOSONAR comments in step 4. Instead, list each invalid Sonar issue in
the plan (step 5) with the proposed NOSONAR line ready to apply. The user
picks a group; only then does the suppression actually land.

When the user does pick a group containing invalid Sonar issues, use the
following format. Bare `// NOSONAR` is forbidden — always include rule and
reason. The rule key inside `NOSONAR(...)` MUST be alphanumeric only (e.g.
`S125`, `S7632`); never include the language prefix like `python:` /
`javascript:` — Sonar's own `python:S7632` rule rejects `# NOSONAR(python:S125)`
as malformed, and a malformed suppression silently suppresses nothing.

| Language family | Syntax |
|---|---|
| Python, Shell, Ruby, YAML | `# NOSONAR(<rule>) — <reason>` |
| C, C++, Java, JS, TS, Go, Rust, Scala | `// NOSONAR(<rule>) — <reason>` |
| HTML, XML, Vue templates | `<!-- NOSONAR(<rule>) — <reason> -->` |
| SQL | `-- NOSONAR(<rule>) — <reason>` |

Examples:
- ✅ `# NOSONAR(S125) — arithmetic explanation, not commented-out code`
- ❌ `# NOSONAR(python:S125) — ...` (colon in rule key — silently fails to parse)
- ❌ `# NOSONAR` (bare — no rule key, no reason)

Place the comment at the end of the offending line. For multi-line issues (e.g. cognitive complexity on a function), put the suppression on the line Sonar cites.

(CodeRabbit invalid replies stay in step 4 — they're comments, not code changes.)

#### CI failure (invalid — flake / infrastructure)

Do **not** silently dismiss. Surface in the plan as an "INVALID — flake/infra" note with the rationale and the run/job URL. Suggest a rerun in the plan but do **not** run `gh run rerun` automatically — that mutates shared state and needs the user's go-ahead. (If the user later says "rerun it", `gh run rerun <run-id> --repo <repo>` is fine.)

### 5. Plan for the VALID issues

After step 4, present a written plan to the user covering ONLY the valid issues. Include:

- A header line: `Triaged: <V> valid / <I> invalid (<C> CodeRabbit + <S> Sonar)`
- One section per valid issue (or per group if >3 — see below): file:line, source, severity, summary, the proposed fix in 1–3 lines.

If there are **more than 3** valid issues, split them into 2–4 LOGICAL GROUPS. Group by what makes them coherent to fix together — usually one of:

- **Same root cause** (one bug surfaces in multiple places)
- **Same module / file**
- **Same category** (e.g. all formatting, all imports, all unused-var)
- **Same severity tier** (all majors first)

Within each group, list the individual issues. End each group with a 1–2 line "fix strategy" describing the unified approach.

End the plan with a one-line proposal:

> Want me to implement group 1 first? (or: pick a group, or say "all" to do them in order)

Do **not** start writing code until the user picks.

## Constraints

- NEVER call any "resolve" mutation on CodeRabbit threads (no `resolveReviewThread`, no UI-equivalent). Only `/replies`. This is a hard global rule from the user.
- NOSONAR suppressions MUST include the rule key and a reason. Bare `// NOSONAR` is forbidden. The rule key inside the parentheses must be alphanumeric only — never include the `python:` / `javascript:` / etc. language prefix (it makes Sonar treat the suppression as malformed).
- This skill stops at the plan. Code fixes happen only after the user picks a group.
- If validation makes you LESS than 80% confident an issue is invalid, classify it as VALID and put it in the plan. Better to over-fix than to silently dismiss a real bug.

## When NOT to use this skill

- User asks for just CodeRabbit threads → use `fetch-coderabbit-threads` directly.
- User asks for just Sonar issues → use `sonarqube:sonar-list-issues` directly.
- User says "fix the CodeRabbit comments" without mentioning Sonar → use `fetch-coderabbit-threads` and skip the merge step.
- User wants you to start coding immediately → this skill is triage + plan only.
