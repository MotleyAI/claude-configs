"""Tests for guard_writes.py PreToolUse hook."""
import json
import subprocess
import sys
import os
import re

import pytest

HOOK_PATH = os.path.join(os.path.dirname(__file__), "guard_writes.py")

# Import regex patterns and normalize_cmd for direct unit testing.
# The module runs as __main__ with stdin reading, so we extract only
# the constant/function definitions by skipping the stdin-reading block.
_module_globals = {"__builtins__": __builtins__}
with open(HOOK_PATH) as f:
    source = f.read()
# Extract: imports + everything after the try/except block up to the main logic
_imports = "import sys\nimport json\nimport re\nimport os\n"
_after_stdin = source.split("unsandboxed = tool_input.get", 1)[1]
_after_stdin = "unsandboxed = False\n" + _after_stdin.split("\n", 1)[1]
_defs_source = _after_stdin.split("# Only Bash commands need guarding")[0]
exec(compile(_imports + _defs_source, HOOK_PATH, "exec"), _module_globals)

normalize_cmd = _module_globals["normalize_cmd"]
SHELL_META = _module_globals["SHELL_META"]
SAFE_REDIRECTS = _module_globals["SAFE_REDIRECTS"]
ASK_ALWAYS_PATTERNS = _module_globals["ASK_ALWAYS_PATTERNS"]
GH_READ_PATTERNS = _module_globals["GH_READ_PATTERNS"]
SAFE_UNSANDBOXED_PATTERNS = _module_globals["SAFE_UNSANDBOXED_PATTERNS"]


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


# --- SHELL_META detection ---

class TestShellMeta:
    def _has_meta(self, cmd):
        """Check if cmd has shell metacharacters after stripping safe redirects."""
        cleaned = SAFE_REDIRECTS.sub('', cmd)
        return bool(SHELL_META.search(cleaned))

    def test_simple_command_no_meta(self):
        assert not self._has_meta("git status")

    def test_semicolon(self):
        assert self._has_meta("echo hello; git push")

    def test_and_operator(self):
        assert self._has_meta("echo hello && git push")

    def test_pipe(self):
        assert self._has_meta("echo hello | grep hello")

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

    # Safe redirections should NOT trigger
    def test_stderr_redirect_safe(self):
        assert not self._has_meta("gh api repos/foo/bar 2>&1")

    def test_dev_null_redirect_safe(self):
        assert not self._has_meta("git status 2>/dev/null")

    def test_stdout_to_dev_null(self):
        assert not self._has_meta("git status >/dev/null")

    def test_redirect_with_real_meta(self):
        # Has both safe redirect AND a real pipe — should detect
        assert self._has_meta("git status 2>&1 | grep error")


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

    def test_api_with_field_blocked(self):
        assert not self._matches_read("gh api repos/foo/bar -f title=test")

    def test_auth_status(self):
        assert self._matches_read("gh auth status")

    def test_pr_create_not_read(self):
        assert not self._matches_read("gh pr create")

    def test_issue_create_not_read(self):
        assert not self._matches_read("gh issue create")


# --- Integration: full hook invocation ---

class TestHookIntegration:
    def test_non_bash_tool_allows(self):
        assert get_decision("Read", {"file_path": "/etc/passwd"}) == "allow"

    def test_non_bash_edit_allows(self):
        assert get_decision("Edit", {"file_path": "foo.py"}) == "allow"

    def test_safe_bash_allows(self):
        assert get_decision("Bash", {"command": "ls -la"}) == "allow"

    def test_git_status_allows(self):
        assert get_decision("Bash", {"command": "git status"}) == "allow"

    def test_git_push_asks(self):
        assert get_decision("Bash", {"command": "git push"}) == "ask"

    def test_docker_asks(self):
        assert get_decision("Bash", {"command": "docker run hello"}) == "ask"

    def test_compound_command_asks(self):
        assert get_decision("Bash", {"command": "echo hi && git push"}) == "ask"

    def test_gh_pr_view_allows(self):
        assert get_decision("Bash", {"command": "gh pr view 4"}) == "allow"

    def test_gh_pr_create_asks(self):
        assert get_decision("Bash", {"command": "gh pr create"}) == "ask"

    def test_gh_api_read_allows(self):
        assert get_decision("Bash", {"command": "gh api repos/foo/bar"}) == "allow"

    def test_gh_api_post_asks(self):
        assert get_decision("Bash", {"command": "gh api --method POST repos/foo/bar"}) == "ask"

    def test_stderr_redirect_not_compound(self):
        """gh api ... 2>&1 should NOT be treated as compound command."""
        assert get_decision("Bash", {"command": "gh api repos/foo/bar 2>&1"}) == "allow"

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
        """git push should ask even when unsandboxed (dangerous pattern takes priority)."""
        assert get_decision("Bash", {
            "command": "git push",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_normalized_env_prefix_git_push_asks(self):
        assert get_decision("Bash", {
            "command": "env GIT_SSH=x /usr/bin/git push",
        }) == "ask"

    def test_subshell_asks(self):
        assert get_decision("Bash", {"command": "(git push)"}) == "ask"

    def test_brace_group_asks(self):
        assert get_decision("Bash", {"command": "{ git push; }"}) == "ask"
