"""Tests for guard_writes.py PreToolUse hook."""
import json
import subprocess
import sys
import os
import re

import pytest

HOOK_PATH = os.path.join(os.path.dirname(__file__), "guard_writes.py")

# Import regex patterns and functions for direct unit testing.
# The module runs as __main__ with stdin reading, so we extract only
# the constant/function definitions by skipping the stdin-reading block.
_module_globals = {"__builtins__": __builtins__}
with open(HOOK_PATH) as f:
    source = f.read()
# Extract: imports + everything after the try/except block up to the main logic
_imports = "import sys\nimport json\nimport re\nimport os\nimport shlex\n"
_after_stdin = source.split("unsandboxed = tool_input.get", 1)[1]
_after_stdin = "unsandboxed = False\n" + _after_stdin.split("\n", 1)[1]
_defs_source = _after_stdin.split("# Only Bash commands need guarding")[0]
exec(compile(_imports + _defs_source, HOOK_PATH, "exec"), _module_globals)

normalize_cmd = _module_globals["normalize_cmd"]
UNSAFE_META = _module_globals["UNSAFE_META"]
SAFE_REDIRECTS = _module_globals["SAFE_REDIRECTS"]
ASK_ALWAYS_PATTERNS = _module_globals["ASK_ALWAYS_PATTERNS"]
GH_READ_PATTERNS = _module_globals["GH_READ_PATTERNS"]
SAFE_UNSANDBOXED_PATTERNS = _module_globals["SAFE_UNSANDBOXED_PATTERNS"]
split_on_and = _module_globals["split_on_and"]
split_on_pipe = _module_globals["split_on_pipe"]
strip_safe_pipes = _module_globals["strip_safe_pipes"]
strip_quoted_strings = _module_globals["strip_quoted_strings"]
evaluate_single_cmd = _module_globals["evaluate_single_cmd"]
strip_safe_tmp_redirects = _module_globals["strip_safe_tmp_redirects"]


def run_hook(tool_name, tool_input):
    """Run guard_writes.py with the given input and return parsed output."""
    stdin_data = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=stdin_data,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Hook crashed: {result.stderr}"
    return json.loads(result.stdout)


def get_decision(tool_name, tool_input):
    """Run hook and return just the permission decision string."""
    output = run_hook(tool_name, tool_input)
    return output["hookSpecificOutput"]["permissionDecision"]


def run_hook_raw(stdin_text):
    """Run guard_writes.py with raw stdin text."""
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=stdin_text,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Hook crashed: {result.stderr}"
    return json.loads(result.stdout)


# --- JSON error handling ---

class TestJsonErrorHandling:
    def test_invalid_json(self):
        output = run_hook_raw("not valid json")
        assert output["hookSpecificOutput"]["permissionDecision"] == "ask"
        assert "Failed to parse" in output["hookSpecificOutput"]["permissionDecisionReason"]

    def test_empty_stdin(self):
        output = run_hook_raw("")
        assert output["hookSpecificOutput"]["permissionDecision"] == "ask"


# --- normalize_cmd ---

class TestNormalizeCmd:
    def test_plain_command(self):
        assert normalize_cmd("git push") == "git push"

    def test_env_var_prefix(self):
        assert normalize_cmd("VAR=1 git push") == "git push"

    def test_multiple_env_vars(self):
        assert normalize_cmd("A=1 B=2 git push") == "git push"

    def test_command_wrapper(self):
        assert normalize_cmd("command git push") == "git push"

    def test_env_wrapper(self):
        assert normalize_cmd("env git push") == "git push"

    def test_absolute_path(self):
        assert normalize_cmd("/usr/bin/git push") == "git push"

    def test_combined(self):
        assert normalize_cmd("env GIT_SSH=x /usr/bin/git push") == "git push"

    def test_empty(self):
        assert normalize_cmd("") == ""

    def test_whitespace(self):
        assert normalize_cmd("  git status  ") == "git status"


# --- UNSAFE_META detection ---

class TestUnsafeMeta:
    def _has_meta(self, cmd):
        """Check if cmd has unsafe shell metacharacters after stripping safe redirects."""
        cleaned = SAFE_REDIRECTS.sub('', cmd)
        return bool(UNSAFE_META.search(cleaned))

    def test_simple_command_no_meta(self):
        assert not self._has_meta("git status")

    def test_semicolon(self):
        assert self._has_meta("echo hello; git push")

    def test_backtick(self):
        assert self._has_meta("echo `whoami`")

    def test_dollar_expansion(self):
        assert self._has_meta("echo $(whoami)")

    def test_subshell_parens(self):
        assert self._has_meta("(git push)")

    def test_brace_group(self):
        assert self._has_meta("{ git push; }")

    def test_newline(self):
        assert self._has_meta("echo hello\ngit push")

    def test_heredoc(self):
        assert self._has_meta("cat <<EOF")

    # && and | are NOT in UNSAFE_META (handled separately)
    def test_and_not_unsafe_meta(self):
        assert not self._has_meta("git status && git diff")

    def test_pipe_not_unsafe_meta(self):
        assert not self._has_meta("git log | head")

    # Safe redirections should NOT trigger
    def test_stderr_redirect_safe(self):
        assert not self._has_meta("gh api repos/foo/bar 2>&1")

    def test_dev_null_redirect_safe(self):
        assert not self._has_meta("git status 2>/dev/null")

    def test_stdout_to_dev_null(self):
        assert not self._has_meta("git status >/dev/null")

    # Redirections to files SHOULD trigger
    def test_redirect_to_file(self):
        assert self._has_meta("git status > /tmp/out")

    def test_input_redirect(self):
        assert self._has_meta("cmd < /etc/passwd")


# --- strip_quoted_strings ---

class TestStripQuotedStrings:
    def test_no_quotes(self):
        assert strip_quoted_strings("git status") == "git status"

    def test_single_quotes(self):
        assert strip_quoted_strings("echo 'hello world'") == "echo ___"

    def test_double_quotes(self):
        assert strip_quoted_strings('echo "hello world"') == "echo ___"

    def test_metacharacters_in_quotes(self):
        result = strip_quoted_strings("gh api --jq '[.[] | select(.x > 1)]'")
        assert "|" not in result
        assert "(" not in result
        assert ">" not in result

    def test_nested_quotes(self):
        result = strip_quoted_strings("""echo "it's fine" """)
        assert "'" not in result


# --- split_on_and ---

class TestSplitOnAnd:
    def test_no_and(self):
        assert split_on_and("git status") == ["git status"]

    def test_simple_and(self):
        assert split_on_and("git status && git diff") == ["git status", "git diff"]

    def test_triple_and(self):
        assert split_on_and("a && b && c") == ["a", "b", "c"]

    def test_quoted_and(self):
        """&& inside quotes should not split."""
        assert split_on_and('echo "foo && bar"') == ['echo "foo && bar"']

    def test_single_quoted_and(self):
        assert split_on_and("echo 'foo && bar'") == ["echo 'foo && bar'"]

    def test_background_ampersand(self):
        """Single & should return None (can't safely split)."""
        assert split_on_and("sleep 10 &") is None

    def test_unbalanced_quotes(self):
        assert split_on_and('echo "unbalanced') is None


# --- split_on_pipe ---

class TestSplitOnPipe:
    def test_no_pipe(self):
        assert split_on_pipe("git status") == ["git status"]

    def test_simple_pipe(self):
        assert split_on_pipe("git log | head") == ["git log", "head"]

    def test_multi_pipe(self):
        assert split_on_pipe("git log | sort | head") == ["git log", "sort", "head"]

    def test_or_operator_returns_none(self):
        """|| should return None (not a pipe, it's an operator we don't handle)."""
        assert split_on_pipe("cmd1 || cmd2") is None

    def test_quoted_pipe(self):
        assert split_on_pipe('grep "foo|bar" file') == ['grep "foo|bar" file']


# --- strip_safe_pipes ---

class TestStripSafePipes:
    def test_no_pipe(self):
        assert strip_safe_pipes("git status") == "git status"

    def test_safe_head(self):
        assert strip_safe_pipes("git log | head") == "git log"

    def test_safe_tail(self):
        assert strip_safe_pipes("git log | tail -20") == "git log"

    def test_safe_grep(self):
        assert strip_safe_pipes("git log | grep fix") == "git log"

    def test_safe_wc(self):
        assert strip_safe_pipes("git status | wc -l") == "git status"

    def test_safe_sort(self):
        assert strip_safe_pipes("ls | sort") == "ls"

    def test_chained_safe(self):
        assert strip_safe_pipes("ls | sort | head") == "ls"

    def test_unsafe_target(self):
        assert strip_safe_pipes("ls | bash") is None

    def test_unsafe_in_chain(self):
        assert strip_safe_pipes("ls | bash | head") is None

    def test_or_operator(self):
        assert strip_safe_pipes("cmd1 || cmd2") is None

    # tee with safe destinations
    def test_tee_tmp_path_allowed(self):
        assert strip_safe_pipes("cmd | tee /tmp/x") == "cmd"

    def test_tee_append_flag_allowed(self):
        assert strip_safe_pipes("cmd | tee -a /tmp/x") == "cmd"

    def test_tee_long_append_flag_allowed(self):
        assert strip_safe_pipes("cmd | tee --append /tmp/x") == "cmd"

    def test_tee_multiple_safe_dests_allowed(self):
        assert strip_safe_pipes("cmd | tee /tmp/a /tmp/b") == "cmd"

    def test_tee_chained_with_tail_allowed(self):
        assert strip_safe_pipes("cmd | tee /tmp/x | tail") == "cmd"

    def test_tee_tmpdir_var_allowed(self):
        assert strip_safe_pipes("cmd | tee $TMPDIR/x") == "cmd"

    def test_tee_no_args_allowed(self):
        # `tee` with no destinations is just a stdout passthrough
        assert strip_safe_pipes("cmd | tee") == "cmd"

    # tee with unsafe destinations
    def test_tee_home_rejected(self):
        assert strip_safe_pipes("cmd | tee ~/.bashrc") is None

    def test_tee_home_var_rejected(self):
        assert strip_safe_pipes("cmd | tee $HOME/foo") is None

    def test_tee_etc_rejected(self):
        assert strip_safe_pipes("cmd | tee /etc/passwd") is None

    def test_tee_path_traversal_rejected(self):
        assert strip_safe_pipes("cmd | tee /tmp/../etc/passwd") is None

    def test_tee_command_substitution_rejected(self):
        assert strip_safe_pipes("cmd | tee /tmp/$(whoami)") is None

    def test_tee_backtick_substitution_rejected(self):
        assert strip_safe_pipes("cmd | tee /tmp/`whoami`") is None

    def test_tee_unknown_flag_rejected(self):
        assert strip_safe_pipes("cmd | tee -D /tmp/x") is None

    def test_tee_mixed_safe_unsafe_rejected(self):
        assert strip_safe_pipes("cmd | tee /tmp/a /etc/passwd") is None


# --- strip_safe_tmp_redirects ---

class TestStripSafeTmpRedirects:
    def test_no_redirect(self):
        assert strip_safe_tmp_redirects("git status") == "git status"

    def test_redirect_to_tmp(self):
        assert strip_safe_tmp_redirects("cmd > /tmp/foo") == "cmd"

    def test_append_to_tmp(self):
        assert strip_safe_tmp_redirects("cmd >> /tmp/foo") == "cmd"

    def test_stderr_to_tmp(self):
        assert strip_safe_tmp_redirects("cmd 2> /tmp/foo") == "cmd"

    def test_both_to_tmp(self):
        assert strip_safe_tmp_redirects("cmd &> /tmp/foo") == "cmd"

    def test_redirect_to_tmpdir(self):
        assert strip_safe_tmp_redirects("cmd > $TMPDIR/foo") == "cmd"

    def test_redirect_to_etc_kept(self):
        assert strip_safe_tmp_redirects("cmd > /etc/foo") == "cmd > /etc/foo"

    def test_redirect_path_traversal_kept(self):
        s = "cmd > /tmp/../etc/foo"
        assert strip_safe_tmp_redirects(s) == s

    def test_redirect_command_substitution_kept(self):
        s = "cmd > /tmp/$(whoami)"
        assert strip_safe_tmp_redirects(s) == s

    def test_redirect_home_var_kept(self):
        s = "cmd > $HOME/foo"
        assert strip_safe_tmp_redirects(s) == s


# --- evaluate_single_cmd ---

class TestEvaluateSingleCmd:
    def test_safe_command(self):
        assert evaluate_single_cmd("ls -la", False) == ("allow", None)

    def test_dangerous_git_push_sandboxed_denies(self):
        decision, reason = evaluate_single_cmd("git push", False)
        assert decision == "deny"

    def test_dangerous_git_push_unsandboxed_asks(self):
        decision, reason = evaluate_single_cmd("git push", True)
        assert decision == "ask"

    def test_gh_read_allows(self):
        assert evaluate_single_cmd("gh pr view 4", False) == ("allow", None)

    def test_gh_write_sandboxed_denies(self):
        decision, reason = evaluate_single_cmd("gh pr create", False)
        assert decision == "deny"

    def test_safe_pipe_stripped(self):
        assert evaluate_single_cmd("git log | head", False) == ("allow", None)

    def test_unsafe_pipe_unsandboxed_asks(self):
        decision, reason = evaluate_single_cmd("ls | bash", True)
        assert decision == "ask"

    def test_unsafe_pipe_sandboxed_allows(self):
        assert evaluate_single_cmd("ls | bash", False) == ("allow", None)

    def test_logical_or_sandboxed_allows(self):
        assert evaluate_single_cmd("foo || bar", False) == ("allow", None)

    def test_logical_or_unsandboxed_asks(self):
        decision, reason = evaluate_single_cmd("foo || bar", True)
        assert decision == "ask"

    def test_unsandboxed_safe(self):
        assert evaluate_single_cmd("gh pr view 4", True) == ("allow", None)

    def test_unsandboxed_unknown_asks(self):
        decision, reason = evaluate_single_cmd("whoami", True)
        assert decision == "ask"


# --- ASK_ALWAYS_PATTERNS ---

class TestAskAlwaysPatterns:
    def _matches_dangerous(self, cmd):
        return any(re.match(p, cmd) for p in ASK_ALWAYS_PATTERNS)

    def test_git_push(self):
        assert self._matches_dangerous("git push")

    def test_git_push_with_remote(self):
        assert self._matches_dangerous("git push origin main")

    def test_git_push_force(self):
        assert self._matches_dangerous("git --no-pager push --force")

    def test_git_status_not_dangerous(self):
        assert not self._matches_dangerous("git status")

    def test_git_commit_not_dangerous(self):
        assert not self._matches_dangerous("git commit -m 'test'")

    def test_docker(self):
        assert self._matches_dangerous("docker run hello")

    def test_docker_compose(self):
        assert self._matches_dangerous("docker compose up")

    def test_ls_not_dangerous(self):
        assert not self._matches_dangerous("ls -la")


# --- GH_READ_PATTERNS ---

class TestGhReadPatterns:
    def _matches_read(self, cmd):
        return any(re.match(p, cmd) for p in GH_READ_PATTERNS)

    def test_pr_view(self):
        assert self._matches_read("gh pr view 123")

    def test_pr_list(self):
        assert self._matches_read("gh pr list")

    def test_issue_view(self):
        assert self._matches_read("gh issue view 456")

    def test_issue_list(self):
        assert self._matches_read("gh issue list")

    def test_run_list(self):
        assert self._matches_read("gh run list")

    def test_repo_view(self):
        assert self._matches_read("gh repo view")

    def test_api_get_default(self):
        assert self._matches_read("gh api repos/foo/bar")

    def test_api_with_method_get(self):
        assert self._matches_read("gh api --method GET repos/foo/bar")

    def test_api_post_blocked(self):
        assert not self._matches_read("gh api --method POST repos/foo/bar")

    def test_api_post_equals_blocked(self):
        assert not self._matches_read("gh api --method=POST repos/foo/bar")

    def test_api_x_post_no_space_blocked(self):
        assert not self._matches_read("gh api -XPOST repos/foo/bar")

    def test_api_x_patch_no_space_blocked(self):
        assert not self._matches_read("gh api -XPATCH repos/foo/bar")

    def test_api_with_field_blocked(self):
        assert not self._matches_read("gh api repos/foo/bar -f title=test")

    def test_api_with_field_equals_blocked(self):
        assert not self._matches_read("gh api repos/foo/bar --field=title=test")

    def test_api_with_F_no_space_blocked(self):
        assert not self._matches_read("gh api repos/foo/bar -Ftitle=test")

    def test_api_with_f_no_space_blocked(self):
        assert not self._matches_read("gh api repos/foo/bar -ftitle=test")

    def test_api_with_raw_field_equals_blocked(self):
        assert not self._matches_read("gh api repos/foo/bar --raw-field=data=x")

    def test_api_with_input_equals_blocked(self):
        assert not self._matches_read("gh api repos/foo/bar --input=file.json")

    def test_auth_status(self):
        assert self._matches_read("gh auth status")

    def test_pr_create_not_read(self):
        assert not self._matches_read("gh pr create")

    def test_issue_create_not_read(self):
        assert not self._matches_read("gh issue create")


# --- Integration: full hook invocation ---

class TestHookIntegration:
    # Basic tool routing
    def test_non_bash_tool_allows(self):
        assert get_decision("Read", {"file_path": "/etc/passwd"}) == "allow"

    def test_non_bash_edit_allows(self):
        assert get_decision("Edit", {"file_path": "foo.py"}) == "allow"

    # Simple commands
    def test_safe_bash_allows(self):
        assert get_decision("Bash", {"command": "ls -la"}) == "allow"

    def test_git_status_allows(self):
        assert get_decision("Bash", {"command": "git status"}) == "allow"

    def test_git_push_denies_sandboxed(self):
        assert get_decision("Bash", {"command": "git push"}) == "deny"

    def test_docker_denies_sandboxed(self):
        assert get_decision("Bash", {"command": "docker run hello"}) == "deny"

    # gh commands
    def test_gh_pr_view_allows(self):
        assert get_decision("Bash", {"command": "gh pr view 4"}) == "allow"

    def test_gh_pr_create_denies_sandboxed(self):
        assert get_decision("Bash", {"command": "gh pr create"}) == "deny"

    def test_gh_api_read_allows(self):
        assert get_decision("Bash", {"command": "gh api repos/foo/bar"}) == "allow"

    def test_gh_api_post_denies_sandboxed(self):
        assert get_decision("Bash", {"command": "gh api --method POST repos/foo/bar"}) == "deny"

    # Safe redirections
    def test_stderr_redirect_not_compound(self):
        assert get_decision("Bash", {"command": "gh api repos/foo/bar 2>&1"}) == "allow"

    # Sandbox bypass
    def test_unsandboxed_gh_read_allows(self):
        assert get_decision("Bash", {
            "command": "gh pr view 4",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_unsandboxed_git_fetch_allows(self):
        assert get_decision("Bash", {
            "command": "git fetch",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_unsandboxed_unknown_asks(self):
        assert get_decision("Bash", {
            "command": "whoami",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_unsandboxed_git_push_asks(self):
        assert get_decision("Bash", {
            "command": "git push",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    # Normalization
    def test_normalized_env_prefix_git_push_denies_sandboxed(self):
        assert get_decision("Bash", {
            "command": "env GIT_SSH=x /usr/bin/git push",
        }) == "deny"

    # Unsafe metacharacters — sandboxed: sandbox contains them, allow
    def test_subshell_sandboxed_allows(self):
        assert get_decision("Bash", {"command": "(echo hello)"}) == "allow"

    def test_backtick_sandboxed_allows(self):
        assert get_decision("Bash", {"command": "echo `whoami`"}) == "allow"

    def test_dollar_expansion_sandboxed_allows(self):
        assert get_decision("Bash", {"command": "echo $(whoami)"}) == "allow"

    def test_git_commit_heredoc_sandboxed_allows(self):
        """Real-world: git commit with heredoc message."""
        assert get_decision("Bash", {
            "command": "git commit -m \"$(cat <<'EOF'\nmessage\nEOF\n)\""
        }) == "allow"

    # Unsafe metacharacters — unsandboxed: must ask
    def test_subshell_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "(git push)",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_semicolon_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "echo hi; git push",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_backtick_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "echo `whoami`",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_dollar_expansion_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "echo $(whoami)",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    # --- && chain handling ---

    def test_safe_and_chain_allows(self):
        """Both parts are safe → allow."""
        assert get_decision("Bash", {"command": "git status && git diff"}) == "allow"

    def test_dangerous_and_chain_denies_sandboxed(self):
        """One part is dangerous → deny (needs unsandboxed)."""
        assert get_decision("Bash", {"command": "echo hi && git push"}) == "deny"

    def test_triple_and_chain_allows(self):
        assert get_decision("Bash", {"command": "ls && git status && git diff"}) == "allow"

    def test_triple_and_chain_with_danger_asks(self):
        assert get_decision("Bash", {"command": "ls && git status && git push"}) == "deny"

    def test_quoted_and_not_split(self):
        """&& inside quotes should not split — treat as single safe command."""
        assert get_decision("Bash", {"command": 'echo "foo && bar"'}) == "allow"

    def test_and_chain_with_gh_read_allows(self):
        assert get_decision("Bash", {"command": "git status && gh pr view 4"}) == "allow"

    def test_and_chain_with_gh_write_denies_sandboxed(self):
        assert get_decision("Bash", {"command": "git status && gh pr create"}) == "deny"

    # --- Safe pipe handling ---

    def test_pipe_to_head_allows(self):
        assert get_decision("Bash", {"command": "git log | head"}) == "allow"

    def test_pipe_to_tail_allows(self):
        assert get_decision("Bash", {"command": "git log | tail -20"}) == "allow"

    def test_pipe_to_grep_allows(self):
        assert get_decision("Bash", {"command": "git log | grep fix"}) == "allow"

    def test_pipe_to_wc_allows(self):
        assert get_decision("Bash", {"command": "git status | wc -l"}) == "allow"

    def test_pipe_to_sort_allows(self):
        assert get_decision("Bash", {"command": "ls | sort"}) == "allow"

    def test_chained_safe_pipes_allows(self):
        assert get_decision("Bash", {"command": "ls | sort | head"}) == "allow"

    def test_pipe_to_unsafe_sandboxed_allows(self):
        assert get_decision("Bash", {"command": "ls | bash"}) == "allow"

    def test_pipe_to_unsafe_unsandboxed_asks(self):
        assert get_decision("Bash", {"command": "ls | bash", "dangerouslyDisableSandbox": True}) == "ask"

    def test_pipe_dangerous_producer_denies_sandboxed(self):
        """git push piped to head — needs unsandboxed."""
        assert get_decision("Bash", {"command": "git push | head"}) == "deny"

    # --- Combined: && with pipes and redirects ---

    def test_and_chain_with_pipe(self):
        assert get_decision("Bash", {"command": "git status && git log | head"}) == "allow"

    def test_redirect_with_safe_pipe(self):
        assert get_decision("Bash", {
            "command": "gh api repos/foo/bar 2>&1 | head -20"
        }) == "allow"

    def test_pytest_with_grep(self):
        """Real-world command: pytest output piped to grep with redirect."""
        assert get_decision("Bash", {
            "command": 'poetry run pytest tests/test_sql.py -v --no-header --tb=short 2>&1 | grep -A 10 "FAILED"'
        }) == "allow"

    def test_and_chain_with_safe_pipe_and_danger(self):
        """Safe pipe doesn't save a dangerous command in the chain."""
        assert get_decision("Bash", {
            "command": "git status | head && git push"
        }) == "deny"

    def test_gh_api_with_jq_unsandboxed_allows(self):
        """gh api with --jq containing metacharacters in quotes should auto-approve."""
        assert get_decision("Bash", {
            "command": """gh api repos/MotleyAI/claude-configs/pulls/4/comments --jq '[.[] | select(.created_at > "2026-04-23T15:00:00Z") | {id, path, line, body: .body[:500]}]' 2>&1""",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    # --- Redirection to files (unsandboxed) ---

    def test_redirect_to_tmp_unsandboxed_allows(self):
        """Redirect to /tmp/... is treated like tee /tmp/..."""
        assert get_decision("Bash", {
            "command": "gh pr view 4 > /tmp/out",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_redirect_append_to_tmp_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "gh pr view 4 >> /tmp/out 2>&1",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_redirect_to_tmpdir_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "gh pr view 4 > $TMPDIR/out",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_redirect_to_etc_unsandboxed_asks(self):
        """Redirects to non-/tmp paths still trip the metacheck."""
        assert get_decision("Bash", {
            "command": "gh pr view 4 > /etc/passwd",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_redirect_path_traversal_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "gh pr view 4 > /tmp/../etc/passwd",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_redirect_command_substitution_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "gh pr view 4 > /tmp/$(whoami)",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_redirect_and_chain_with_wc_unsandboxed_allows(self):
        """The motivating case: gh api > /tmp/foo && wc -l /tmp/foo."""
        assert get_decision("Bash", {
            "command": "gh api repos/foo/bar > /tmp/x && wc -l /tmp/x",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_redirect_to_file_sandboxed_allows(self):
        """Inside sandbox, redirects are contained."""
        assert get_decision("Bash", {"command": "git status > /tmp/out"}) == "allow"

    # --- wc as standalone unsandboxed command ---

    def test_wc_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "wc -l /tmp/claude/foo.json",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_wc_sensitive_path_unsandboxed_allows(self):
        """wc emits only counts, not contents — safe even on sensitive files."""
        assert get_decision("Bash", {
            "command": "wc -l /home/x/.ssh/id_rsa",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_cat_unsandboxed_asks(self):
        """cat would leak file contents — not allowlisted."""
        assert get_decision("Bash", {
            "command": "cat /etc/passwd",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_head_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "head /etc/passwd",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_grep_recursive_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "grep -r secret /",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    # --- gh api hardened flag forms ---

    def test_gh_api_method_equals_post_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "gh api --method=POST repos/foo/bar",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_gh_api_xpost_no_space_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "gh api -XPOST repos/foo/bar",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_gh_api_f_no_space_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "gh api repos/foo/bar -ftitle=test",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    # tee in pipe — uses an allowlisted producer (`gh pr view`) so we
    # exercise the pipe-target logic, not the producer-allowlist logic.
    def test_tee_tmp_log_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "gh pr view 4 | tee /tmp/install.log | tail -80",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_tee_tmp_no_consumer_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "gh pr view 4 | tee /tmp/x",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_tee_home_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "gh pr view 4 | tee ~/.bashrc",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_tee_etc_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "gh pr view 4 | tee /etc/something",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_tee_home_sandboxed_allows(self):
        # Inside sandbox, unsafe pipe targets are allowed because the
        # sandbox itself contains the write.
        assert get_decision("Bash", {
            "command": "echo hi | tee ~/.bashrc",
        }) == "allow"
