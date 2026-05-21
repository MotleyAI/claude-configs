---
name: process-reviews
description: Use when the user asks to process / triage / address / handle PR reviews from CodeRabbit, SonarQube, Codex, and CI all together. First waits (polling every 1 min, max 30 min) until CodeRabbit, Sonar, and every CI check on the PR are in a terminal state — while a Codex review runs concurrently against the local diff. Then fetches unresolved threads from all three code-review sources plus failed CI checks, validates each against the actual code / log, handles invalid ones in place (reply on thread / NOSONAR comment), and presents a unified plan for fixing the valid ones (split into logical groups if more than 3).
---

# Process unresolved review feedback (CodeRabbit + SonarQube + Codex + failed CI)

Combine CodeRabbit, SonarQube, Codex, and failed CI feedback into a single triage workflow. Stops at a written plan — does not start fixing.

## Inputs

- PR number. If the user didn't say, infer from the cwd: `gh pr view --json number -q .number`. If that fails, ask the user.
- Repository (auto-detected from cwd via `gh repo view`, or pass explicitly).
- SonarQube project key. Resolve via the sonarqube MCP server's standard lookup order: `.sonarlint/connectedMode.json` → `sonar-project.properties` → `pom.xml`/`build.gradle*`/`package.json` → CI config. If still unresolved, call `mcp__sonarqube__search_my_sonarqube_projects` and pick the right one with the user's confirmation.

**Sonar fetching is MCP-only.** Use the `mcp__sonarqube__*` tools (`search_my_sonarqube_projects`, `search_sonar_issues_in_projects`, `get_project_quality_gate_status`, `search_security_hotspots`, `show_rule`). Do NOT shell out to the `sonar` CLI binary, do NOT invoke the `sonarqube:sonar-list-issues` skill (it wraps the CLI), and do NOT reach for raw `gh api` against the SonarCloud GitHub-App comments. If the `mcp__sonarqube__*` tools are not registered in this session, stop and ask the user to load the MCP — do not fall back to the CLI or `gh api`.

## Steps

### 0. Wait until reviews and CI are done (and kick off Codex in parallel)

Don't fetch anything until every status check on the PR is in a terminal state. Mid-flight checks mean late-arriving CodeRabbit nitpicks, Sonar issues that haven't been computed yet, or test failures that haven't reported — triaging that is wasted work.

**Run Codex in parallel with the gate-wait.** Codex doesn't depend on GitHub — it analyses the local working-tree diff against the PR's base branch. Kick it off in the SAME assistant turn that arms the gate-wait Monitor, so the two run concurrently. By the time the gate clears (often 5–15 minutes), Codex has already returned and you save that whole window.

Call `mcp__codex__codex` directly (don't shell out to the `codex-review` skill, which is the single-call form). Use `sandbox: "read-only"`, `approval-policy: "never"`, and `cwd` set to the repo root. Prompt template:

```
Review the PR diff for this branch against `origin/<base>`. Steps you should take:

1. Run `git fetch origin <base>` then `git diff --stat origin/<base>...HEAD` to scope the review to this PR's changes only.
2. For each changed file, read the diff (`git diff origin/<base>...HEAD -- <file>`) and the surrounding code as needed.
3. Flag actionable findings only. Categories: correctness, regressions, security, test gaps, maintainability, cross-file consistency, missed edge cases.
4. For each finding return: file:line range, severity (critical|major|minor|info), one-sentence summary, and a one-paragraph rationale.
5. Skip stylistic nits unless they materially impact readability. Skip findings you have less than 70% confidence in.

Do NOT modify files. Do NOT run tests. Return only the findings list (or "No findings." if clean). Be terse — no preamble.
```

Substitute the actual base branch (`main`, `master`, or what `gh pr view --json baseRefName --jq .baseRefName` returns) and run `mcp__codex__codex` once. Stash the response — you'll merge it into the normalised list at Step 2.

If `mcp__codex__codex` is not registered in this session, do NOT fall back to a different review tool; just skip Codex and proceed with the three GitHub-side sources. Note the skip in the plan header.

A check is **non-terminal** if it's:
- a `StatusContext` with `state` ∈ {`PENDING`, `EXPECTED`} — this is how CodeRabbit reports, and
- a `CheckRun` or `WorkflowRun` with `status` ∈ {`QUEUED`, `IN_PROGRESS`, `WAITING`, `REQUESTED`, `PENDING`} — this is how Sonar and GitHub Actions jobs report.

Anything else (`SUCCESS` / `FAILURE` / `ERROR` / `COMPLETED`) counts as terminal — even a failed check is "done". Checks that are *missing entirely* from the rollup (e.g. CodeRabbit not installed on the repo) do not block — only checks that exist AND are non-terminal do.

#### 0a. Wait for the status-check rollup

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
  echo "Waiting on: $pending (elapsed $((elapsed/60))m). Sleeping 1m."

  if (( elapsed >= TIMEOUT )); then
    echo "Gate timed out after 30 min. Still pending: $pending. Aborting."
    exit 1
  fi

  sleep 60
done
```

#### 0b. Settle for CodeRabbit's review delivery

The `statusCheckRollup` only covers the CodeRabbit *status check* — the bot's `StatusContext` flips to `SUCCESS` when it finishes analysing, but the actual review content (top-level summary + line-level threads) is delivered on separate GitHub timelines that can lag the status flip by 1–5 minutes. If you fetch threads in that window you get an empty (or partial) view and incorrectly declare the PR clean.

The authoritative signal is the **top-level summary comment** that CodeRabbit maintains on the PR: it's posted by `coderabbitai[bot]` on the issue-comments endpoint, contains the `summarize by coderabbit.ai` HTML marker, and CodeRabbit **updates the same comment** for every push (it does not create a new one). The summary comment's `updated_at` reliably advances past the push, and line-level review threads are visible by then.

Do **not** rely on `Review.submittedAt`: CodeRabbit typically submits one `PullRequestReview` per PR — the first one — and pushes thereafter only update the summary comment and (when applicable) the line-level review threads. `Review.submittedAt` is therefore stuck on the original review and never advances past subsequent HEADs.

After Step 0a clears, wait for the CodeRabbit summary comment's `updated_at` to be newer than the PR's HEAD `committedDate`. Skip this if no CodeRabbit `StatusContext` ever appeared in the rollup (CodeRabbit isn't installed on this repo). Cap at 10 minutes.

```bash
CR_SETTLE=$((10 * 60))

has_coderabbit=$(gh pr view "$PR" --repo "$REPO" --json statusCheckRollup --jq '
  any(.statusCheckRollup[];
      (.__typename == "StatusContext")
      and ((.context // .name // "") | ascii_downcase | test("coderabbit")))')

if [[ "$has_coderabbit" == "true" ]]; then
  head_oid=$(gh pr view "$PR" --repo "$REPO" --json headRefOid --jq '.headRefOid')
  head_committed=$(gh api "repos/$REPO/commits/$head_oid" \
    --jq '.commit.committer.date')
  CR_START=$(date +%s)
  while :; do
    # Latest update of any coderabbitai[bot] top-level issue comment. The
    # bot reuses the same summary comment across pushes — checking
    # ``updated_at`` (not ``created_at``) catches subsequent reviews.
    cr_updated=$(gh api "repos/$REPO/issues/$PR/comments" --jq '
      [.[] | select(.user.login | test("coderabbitai"; "i")) | .updated_at]
      | sort | last // ""')
    if [[ -n "$cr_updated" && "$cr_updated" > "$head_committed" ]]; then
      echo "CodeRabbit summary updated ($cr_updated) — review delivered."
      break
    fi
    elapsed=$(( $(date +%s) - CR_START ))
    if (( elapsed >= CR_SETTLE )); then
      echo "CodeRabbit settle hit 10m cap — proceeding without a fresh review."
      break
    fi
    echo "Waiting for CodeRabbit summary > head ($head_committed). Sleeping 30s."
    sleep 30
  done
fi
```

Why summary `updated_at` and not other signals:

- **Status check flip**: too early — the bot's CheckRun terminalizes when its analysis is queued, not when its output is fully delivered.
- **`Review.submittedAt`**: only set on the *first* review; subsequent pushes update the existing comment without producing a new Review object, so the timestamp never advances.
- **Line-level review comments (`pulls/N/comments`)**: only exist when there are findings; on a clean PR they never appear, so polling them would always hit the 10-minute cap.
- **Summary `updated_at`**: advances on every CodeRabbit pass (whether it found anything or not), is monotonic with respect to HEAD, and is set after the bot has finished posting line-level threads (the summary is the last thing the bot writes).

Once both 0a and 0b have cleared, proceed to Step 1.

### 1. Fetch all unresolved feedback (in parallel)

- **Codex** — already returned from Step 0's parallel call. Parse the response into findings: one entry per flagged file:line, with severity from the model's own classification. If the response was "No findings." treat the channel as empty.
- **CodeRabbit** — invoke the `fetch-coderabbit-threads` skill (script: `~/.claude/skills/fetch-coderabbit-threads/scripts/fetch-coderabbit-threads.sh <PR>`). Read the JSON file it writes (`JSON: <path>` last line of stdout) — that's the structured input for the rest of this skill.
- **SonarQube — check EVERY gate criterion, not just issues.** The SonarCloud quality gate can fail on issues, duplications, coverage, security hotspots, or other metrics independently. Fetch all of them so the plan is not missing the actual cause of a red gate. **Mandatory calls** (all MCP, never the CLI / `sonarqube:sonar-*` skills / `gh api`):
  - `mcp__sonarqube__get_project_quality_gate_status(projectKey=..., pullRequest="<PR>")` — the headline pass/fail and the individual gate conditions (which metric tripped, threshold vs actual). Treat any non-OK condition as something to address even if no Sonar issue is filed against it.
  - `mcp__sonarqube__search_sonar_issues_in_projects(projects=["<key>"], pullRequestId="<PR>", issueStatuses=["OPEN","CONFIRMED"])` — bugs, vulnerabilities, code smells.
  - `mcp__sonarqube__search_security_hotspots(projectKey=..., pullRequest="<PR>", status=["TO_REVIEW"])` — hotspots are NOT issues; they have a separate review workflow and are easy to miss.
  - For each duplication-related gate condition (`new_duplicated_lines_density` etc.) or whenever the quality gate cites duplication: `mcp__sonarqube__search_duplicated_files(projectKey=..., pullRequest="<PR>")` and then `mcp__sonarqube__get_duplications(componentKey=..., pullRequest="<PR>")` on the specific file(s). Duplications never surface as Sonar issues — they show up only via these tools and the gate.
  - For each coverage-related gate condition (`new_coverage`, `new_lines_to_cover` etc.): `mcp__sonarqube__search_files_by_coverage(projectKey=..., pullRequest="<PR>", ...)` to find under-covered files, then `mcp__sonarqube__get_file_coverage_details(componentKey=..., pullRequest="<PR>")` for the specific uncovered lines.
  - Optional but useful when the gate cites a metric you don't recognise: `mcp__sonarqube__get_component_measures(component=..., metricKeys=[...], pullRequest="<PR>")` and `mcp__sonarqube__search_metrics(...)` to look up what the metric means.

  If `mcp__sonarqube__*` tools are not registered in this session, stop and ask the user to load the MCP — do not fall back to the CLI or `gh api`.
- **Failed CI** — invoke the `fetch-failed-pr-checks` skill (script: `~/.claude/skills/fetch-failed-pr-checks/scripts/fetch-failed-pr-checks.sh <PR>`). Read its JSON for the failed checks plus failed-step log excerpts.

Run the three GitHub-side fetches in parallel — they're independent. Codex is already done (Step 0). Inside SonarQube, the gate-status call comes first so you know which secondary tools (duplications / coverage / hotspots) are actually load-bearing; everything else can run in parallel.

### 2. Merge into one normalised list

Build a single in-memory list. Each entry:

- `source`: `"coderabbit"` | `"sonar"` | `"codex"` | `"ci"`
- `sonar_kind` (when `source == "sonar"`): `"issue"` | `"hotspot"` | `"duplication"` | `"coverage"` | `"gate_condition"` — distinguishes the gate-criterion subtypes since each has its own invalid-handling channel (NOSONAR only applies to issues; hotspots have a review workflow; duplications/coverage/gate-conditions need code changes or `--force-clean`-style suppressions specific to the metric).
- `file`: path relative to repo root, or `null` for CI failures (the failure may not map to a single file) and for project-level gate conditions
- `line`: integer or `null` (or a `[start, end]` range for duplication blocks; codex findings should carry a line range when they cite one, single line otherwise)
- `severity`: `critical` | `major` | `minor` | `info` (best-effort mapping; CodeRabbit emoji → severity: 🔴/⚠️ Potential issue → major, 🟡/💡 → minor, 💤 → info; CI failures default to `major`; gate-condition entries inherit from the failing condition's severity field; hotspots default to `major`; codex findings use the severity the model assigned)
- `rule`: Sonar rule key (issues / hotspots), the metric key (`new_duplicated_lines_density`, `new_coverage`, ...) for gate / duplication / coverage entries, the CodeRabbit thread/comment ID, the CI workflow/job name, or `"codex"` + a short tag for codex findings (codex doesn't issue rule keys)
- `summary`: one-line description (for CI: `<workflow> / <job>` failed at conclusion `<X>`; for gate conditions: `<metric>: <actual> vs <threshold>`; for codex: the model's one-sentence summary line)
- `body`: full text (CodeRabbit comment body, Sonar issue/hotspot message + rule description, duplication block range + duplicate locations, coverage's uncovered-line list, the failed-step log excerpt, or codex's one-paragraph rationale)
- `ref`: thread URL (CodeRabbit), Sonar issue/hotspot key, run/job URL (CI), or `null` for codex (no remote thread to link)

Don't dedupe across sources blindly — if multiple sources flag the same area, keep them all. They need separate invalid-handling channels. **Don't drop a failing quality-gate condition just because no individual issue is filed** — duplication and coverage conditions routinely fail the gate without producing any `search_sonar_issues_in_projects` rows.

**Codex overlap with CodeRabbit / Sonar is expected and fine.** Codex and CodeRabbit both flag broad correctness/security/regression issues; sometimes they catch the same thing, sometimes one catches what the other misses. Treat overlapping findings as independent entries — the plan can collapse them into a single fix at Step 5 when the proposed change is identical, but keep both rows during triage so each source's invalid-handling channel stays intact.

### 3. Validate each issue

For each entry, classify as VALID or INVALID using a source-appropriate signal:

- **CodeRabbit / Sonar / Codex** — READ the cited file at the cited line(s). Apply the user's global rules from `~/.claude/CLAUDE.md` (trust internal code, validate only at boundaries; imports at the top; etc.). Lean toward VALID when uncertain — false positives are easier to defend later than missed bugs now.
- **CI failure** — READ the failed-step log excerpt in the JSON. Classify as INVALID only when the failure is clearly unrelated to this PR's changes (network blip / runner died / well-known flaky test that the user has previously confirmed is flaky / out-of-date Action that times out before doing anything). Otherwise VALID. **A test failure that points at code this PR touched is always VALID** — don't argue your way out of it.

Codex-specific validation hazards (apply on top of the shared CodeRabbit/Sonar rules):

- Codex sometimes flags issues that are TRUE in isolation but resolved by other lines in the diff it didn't read. Always verify by reading a wider slice of the cited file, not just the cited line, before classifying.
- Codex doesn't see CI output, so it can re-raise the same concern as a CI failure. If both fire on the same area, mark them as overlapping in the plan rather than deduping — Step 5's group strategy collapses them.

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

#### Codex (invalid)

Codex has no remote thread or status check to update — it's a local-only review. For invalid codex findings, list them in the plan at Step 5 under an `INVALID — codex` sub-section with the rationale. No reply, no suppression comment, no NOSONAR. The whole audit trail lives in the plan output you give the user, which they can refer back to.

#### CI failure (invalid — flake / infrastructure)

Do **not** silently dismiss. Surface in the plan as an "INVALID — flake/infra" note with the rationale and the run/job URL. Suggest a rerun in the plan but do **not** run `gh run rerun` automatically — that mutates shared state and needs the user's go-ahead. (If the user later says "rerun it", `gh run rerun <run-id> --repo <repo>` is fine.)

### 5. Plan for the VALID issues

After step 4, present a written plan to the user covering ONLY the valid issues. Include:

- A header line: `Triaged: <V> valid / <I> invalid (<C> CodeRabbit + <S> Sonar + <X> Codex + <CI> CI)` — show every source even when its count is 0, so the user can see which channels ran.
- One section per valid issue (or per group if >3 — see below): file:line, source, severity, summary, the proposed fix in 1–3 lines. When two or more sources flag the same fix (e.g. Codex + CodeRabbit both raise the same correctness concern), list each row but mark them as `[merged: <other-source>]` so the user sees the corroboration; the actual code change is one edit.

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
- User asks for just a Codex review of the local diff → use the `codex-review` skill directly.
- User says "fix the CodeRabbit comments" without mentioning Sonar / Codex → use `fetch-coderabbit-threads` and skip the merge step.
- User wants you to start coding immediately → this skill is triage + plan only.
