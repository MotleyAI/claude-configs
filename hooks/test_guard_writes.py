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
NEEDS_UNSANDBOXED_PATTERNS = _module_globals["NEEDS_UNSANDBOXED_PATTERNS"]
NEEDS_UNSANDBOXED = _module_globals["NEEDS_UNSANDBOXED"]


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

    def test_absolute_path_local_bin(self):
        assert normalize_cmd("/usr/local/bin/foo arg") == "foo arg"

    def test_absolute_path_sbin(self):
        assert normalize_cmd("/sbin/ifconfig") == "ifconfig"

    def test_tmp_path_not_basenamed(self):
        # /tmp/ is NOT a standard bin dir — keep the path so a malicious
        # `/tmp/git` can't masquerade as `git` in the allowlist.
        assert normalize_cmd("/tmp/git push") == "/tmp/git push"

    def test_home_bin_path_not_basenamed(self):
        # User-controlled bin dirs are also not in the safe-prefix list.
        assert normalize_cmd("/home/user/bin/foo arg") == "/home/user/bin/foo arg"

    def test_tmp_script_not_basenamed(self):
        # The motivating case: an attacker dropping a same-named script in
        # /tmp must not normalize to the bare-name allowlist form.
        assert normalize_cmd("/tmp/fetch-coderabbit-threads.sh 7") == \
            "/tmp/fetch-coderabbit-threads.sh 7"

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

    # --- pipe-target arg-aware allowlist (CodeRabbit #12) ---
    # head/tail/sort/wc with file operands must not be auto-stripped, because
    # the operand reads a file. Only stdin-mode (flags only, or "-") is safe.

    def test_head_with_file_operand_rejected(self):
        # `cmd | head /etc/passwd` — head reads /etc/passwd, not stdin
        assert strip_safe_pipes("gh pr view 4 | head /etc/passwd") is None

    def test_tail_with_file_operand_rejected(self):
        assert strip_safe_pipes("gh pr view 4 | tail /etc/passwd") is None

    def test_sort_with_file_operand_rejected(self):
        assert strip_safe_pipes("gh pr view 4 | sort /etc/passwd") is None

    def test_wc_with_file_operand_rejected(self):
        assert strip_safe_pipes("gh pr view 4 | wc /etc/passwd") is None

    def test_head_flags_only_allowed(self):
        assert strip_safe_pipes("gh pr view 4 | head -n 5") == "gh pr view 4"

    def test_head_short_flag_allowed(self):
        assert strip_safe_pipes("gh pr view 4 | head -5") == "gh pr view 4"

    def test_head_dash_stdin_allowed(self):
        # `head -` explicitly reads from stdin
        assert strip_safe_pipes("gh pr view 4 | head -") == "gh pr view 4"

    def test_tail_flags_only_allowed(self):
        assert strip_safe_pipes("git log | tail -n 20") == "git log"

    def test_grep_one_pattern_allowed(self):
        # `grep PATTERN` with no FILE = reads stdin
        assert strip_safe_pipes("git log | grep fix") == "git log"

    def test_grep_pattern_plus_file_rejected(self):
        # `grep PATTERN FILE` reads FILE, not stdin
        assert strip_safe_pipes("gh pr view 4 | grep root /etc/passwd") is None

    def test_grep_only_flags_allowed(self):
        # `grep -c` (count, no pattern) — degenerate but harmless on stdin
        assert strip_safe_pipes("ls | grep -c .") == "ls"

    def test_grep_file_short_flag_rejected(self):
        # `grep -f FILE` reads patterns FROM FILE — a sensitive-file-read
        # bypass disguised as a pattern source.
        assert strip_safe_pipes("gh pr view 4 | grep -f /etc/passwd") is None

    def test_grep_file_long_flag_rejected(self):
        assert strip_safe_pipes("gh pr view 4 | grep --file=/etc/passwd") is None

    def test_grep_file_long_flag_separate_value_rejected(self):
        assert strip_safe_pipes("gh pr view 4 | grep --file /etc/passwd") is None

    def test_grep_dash_e_with_two_patterns_allowed(self):
        # `grep -e PATTERN -e PATTERN2` — each -e consumes its next token as
        # a pattern, not a file. The pre-fix simple count incorrectly rejected
        # this; walking argv with -e as value-taking allows it through.
        assert strip_safe_pipes("git log | grep -e fix -e bug") == "git log"

    def test_grep_dash_e_pattern_plus_file_rejected(self):
        # With `-e PATTERN`, the positional pattern slot is already filled,
        # so any subsequent non-flag is a FILE operand — must reject.
        assert strip_safe_pipes("gh pr view 1 | grep -e x /etc/passwd") is None

    def test_grep_long_regexp_plus_file_rejected(self):
        # `--regexp=PATTERN FILE` — same shape as `-e` form.
        assert strip_safe_pipes("gh pr view 1 | grep --regexp=x /etc/passwd") is None

    def test_grep_long_regexp_space_plus_file_rejected(self):
        # `--regexp PATTERN FILE` (space-separated) — same.
        assert strip_safe_pipes("gh pr view 1 | grep --regexp x /etc/passwd") is None

    def test_grep_dash_e_no_file_allowed(self):
        assert strip_safe_pipes("git log | grep -e fix") == "git log"

    def test_sort_output_flag_rejected(self):
        # `sort -o FILE` writes FILE — must not auto-strip
        assert strip_safe_pipes("ls | sort -o /tmp/owned") is None

    def test_sort_long_output_flag_rejected(self):
        assert strip_safe_pipes("ls | sort --output=/tmp/owned") is None

    def test_sort_short_output_attached_rejected(self):
        # `-oFILE` (no space)
        assert strip_safe_pipes("ls | sort -o/tmp/owned") is None

    def test_sort_files0_from_short_rejected(self):
        # `--files0-from FILE` reads FILE — sensitive-read bypass via pipe.
        assert strip_safe_pipes("gh pr view 1 | sort --files0-from /etc/passwd") is None

    def test_sort_files0_from_equals_rejected(self):
        assert strip_safe_pipes("gh pr view 1 | sort --files0-from=/etc/passwd") is None

    def test_sort_compress_program_rejected(self):
        # `--compress-program PROG` runs PROG — code-execution bypass.
        assert strip_safe_pipes("gh pr view 1 | sort --compress-program /tmp/evil") is None

    def test_sort_compress_program_equals_rejected(self):
        assert strip_safe_pipes("gh pr view 1 | sort --compress-program=/tmp/evil") is None

    def test_sort_with_value_taking_flag_allowed(self):
        # `sort -k 2 -t :` — both flags take values, no file operands
        assert strip_safe_pipes("ls | sort -k 2 -t :") == "ls"

    def test_tail_follow_flag_allowed(self):
        # `-f` is not value-taking on tail; the next token (if non-flag)
        # would be a file operand. With no operand it's fine.
        assert strip_safe_pipes("journalctl | tail -f -n 5") == "journalctl"


# --- TMPDIR resolution in is_safe_tee_path (CodeRabbit #8) ---

class TestIsSafeTeePathTmpdirResolution:
    """`$TMPDIR/...` paths should only be considered safe when the resolved
    TMPDIR env var actually points under /tmp/. If TMPDIR is unset or points
    elsewhere (e.g. $HOME/tmp), reject the path."""

    def test_tmpdir_unset_rejects(self, monkeypatch):
        monkeypatch.delenv("TMPDIR", raising=False)
        assert _module_globals["is_safe_tee_path"]("$TMPDIR/x") is False

    def test_tmpdir_pointing_to_tmp_allows(self, monkeypatch):
        monkeypatch.setenv("TMPDIR", "/tmp")
        assert _module_globals["is_safe_tee_path"]("$TMPDIR/x") is True

    def test_tmpdir_pointing_to_subtmp_allows(self, monkeypatch):
        monkeypatch.setenv("TMPDIR", "/tmp/claude")
        assert _module_globals["is_safe_tee_path"]("$TMPDIR/x") is True

    def test_tmpdir_pointing_to_home_rejects(self, monkeypatch):
        monkeypatch.setenv("TMPDIR", "/home/james/tmp")
        assert _module_globals["is_safe_tee_path"]("$TMPDIR/x") is False

    def test_tmpdir_pointing_to_etc_rejects(self, monkeypatch):
        monkeypatch.setenv("TMPDIR", "/etc")
        assert _module_globals["is_safe_tee_path"]("$TMPDIR/passwd") is False

    def test_bare_tmp_path_unaffected_by_tmpdir(self, monkeypatch):
        # /tmp/... paths should remain safe regardless of TMPDIR value
        monkeypatch.setenv("TMPDIR", "/etc")
        assert _module_globals["is_safe_tee_path"]("/tmp/foo") is True

    def test_tmpdir_path_traversal_still_rejected(self, monkeypatch):
        # Traversal attempts should be rejected even if TMPDIR is /tmp
        monkeypatch.setenv("TMPDIR", "/tmp")
        assert _module_globals["is_safe_tee_path"]("$TMPDIR/../etc/passwd") is False


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

    def test_plain_git_push_sandboxed_denies(self):
        # Plain push hits NEEDS_UNSANDBOXED_PATTERNS — sandbox blocks keyring.
        decision, _reason = evaluate_single_cmd("git push", False)
        assert decision == "deny"

    def test_plain_git_push_unsandboxed_allows(self):
        # Plain push is auto-approved unsandboxed (SAFE_UNSANDBOXED_PATTERNS).
        assert evaluate_single_cmd("git push", True) == ("allow", None)

    def test_force_git_push_unsandboxed_asks(self):
        # --force still hits ASK_ALWAYS_PATTERNS regardless of sandbox bypass.
        decision, _reason = evaluate_single_cmd("git push --force", True)
        assert decision == "ask"

    def test_force_git_push_sandboxed_denies(self):
        # Sandboxed force-push: ASK_ALWAYS becomes deny with bypass message.
        decision, _reason = evaluate_single_cmd("git push --force", False)
        assert decision == "deny"

    def test_gh_read_sandboxed_denies(self):
        decision, reason = evaluate_single_cmd("gh pr view 4", False)
        assert decision == "deny"
        assert reason == NEEDS_UNSANDBOXED

    def test_gh_write_sandboxed_denies(self):
        decision, _reason = evaluate_single_cmd("gh pr create", False)
        assert decision == "deny"

    def test_safe_pipe_stripped(self):
        assert evaluate_single_cmd("git log | head", False) == ("allow", None)

    def test_unsafe_pipe_unsandboxed_asks(self):
        decision, _reason = evaluate_single_cmd("ls | bash", True)
        assert decision == "ask"

    def test_unsafe_pipe_sandboxed_allows(self):
        assert evaluate_single_cmd("ls | bash", False) == ("allow", None)

    def test_logical_or_sandboxed_allows(self):
        assert evaluate_single_cmd("foo || bar", False) == ("allow", None)

    def test_logical_or_unsandboxed_asks(self):
        decision, _reason = evaluate_single_cmd("foo || bar", True)
        assert decision == "ask"

    def test_unsandboxed_safe(self):
        assert evaluate_single_cmd("gh pr view 4", True) == ("allow", None)

    def test_unsandboxed_unknown_asks(self):
        decision, _reason = evaluate_single_cmd("whoami", True)
        assert decision == "ask"


# --- ASK_ALWAYS_PATTERNS ---

class TestAskAlwaysPatterns:
    def _matches_dangerous(self, cmd):
        return any(re.match(p, cmd) for p in ASK_ALWAYS_PATTERNS)

    def test_plain_git_push_not_dangerous(self):
        # Plain push is no longer in ASK_ALWAYS — it's been moved to
        # SAFE_UNSANDBOXED_PATTERNS so it auto-approves when bypassing sandbox.
        assert not self._matches_dangerous("git push")

    def test_plain_git_push_with_remote_not_dangerous(self):
        assert not self._matches_dangerous("git push origin main")

    def test_git_push_force(self):
        assert self._matches_dangerous("git --no-pager push --force")

    def test_git_push_force_with_lease(self):
        assert self._matches_dangerous("git push --force-with-lease origin main")

    def test_git_push_short_force(self):
        assert self._matches_dangerous("git push -f origin main")

    def test_git_push_bundled_force_upstream(self):
        # `-fu` = `-f -u` bundled — the `f` letter must be detected anywhere
        # in the short-option token.
        assert self._matches_dangerous("git push -fu origin main")

    def test_git_push_bundled_force_leading(self):
        assert self._matches_dangerous("git push -uf origin main")

    def test_git_push_bundled_force_middle(self):
        assert self._matches_dangerous("git push -vfn origin main")

    def test_git_push_bundled_delete(self):
        assert self._matches_dangerous("git push -du origin egor/foo")

    def test_git_push_safe_bundle_not_dangerous(self):
        # `-uv` = set-upstream + verbose, no force/delete — must NOT match.
        assert not self._matches_dangerous("git push -uv origin main")

    def test_git_push_long_flag_with_f_not_dangerous(self):
        # `--follow-tags` contains an `f` but is a long flag — must NOT
        # match the short-bundle force pattern (the inner `-` breaks the
        # `[A-Za-z]*f[A-Za-z]*` match).
        assert not self._matches_dangerous("git push --follow-tags origin main")

    def test_git_push_delete_long(self):
        assert self._matches_dangerous("git push --delete origin egor/foo")

    def test_git_push_delete_short(self):
        assert self._matches_dangerous("git push -d origin egor/foo")

    def test_git_push_deletion_refspec(self):
        assert self._matches_dangerous("git push origin :egor/foo")

    def test_git_push_deletion_refspec_with_extra_ref(self):
        # Multi-arg form: `push <remote> <ref> :<deleted>` slipped through the
        # old pattern because it required exactly one token before `:branch`.
        assert self._matches_dangerous("git push origin main :old-branch")

    def test_git_push_force_refspec(self):
        assert self._matches_dangerous("git push origin +egor/foo")

    def test_git_push_force_refspec_with_extra_ref(self):
        assert self._matches_dangerous("git push origin main +bad-branch")

    def test_git_push_normal_refspec_not_dangerous(self):
        # `src:dst` refspec is the normal push form — colon is mid-token, not
        # at the start, so it must NOT match the deletion pattern.
        assert not self._matches_dangerous("git push origin master:main")

    def test_git_push_mirror(self):
        # --mirror force-updates all refs and deletes remote refs not present
        # locally — same blast radius as --force + --delete combined.
        assert self._matches_dangerous("git push --mirror origin")

    def test_git_push_prune(self):
        # --prune deletes remote refs without a local counterpart.
        assert self._matches_dangerous("git push --prune origin refs/heads/*:refs/heads/*")

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

    def test_api_x_lowercase_post_blocked(self):
        # GitHub accepts lowercase HTTP method names — the regex must match
        # them too, or `-X post` bypasses the read-only allowlist.
        assert not self._matches_read("gh api -X post repos/foo/bar")

    def test_api_lowercase_method_equals_blocked(self):
        assert not self._matches_read("gh api --method=patch repos/foo/bar")

    def test_api_lowercase_method_space_blocked(self):
        assert not self._matches_read("gh api --method delete repos/foo/bar")

    def test_api_mixedcase_method_blocked(self):
        assert not self._matches_read("gh api -X PoSt repos/foo/bar")

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

    # gh commands — all denied inside sandbox (need bypass for keyring/network)
    def test_gh_pr_view_sandboxed_denies(self):
        assert get_decision("Bash", {"command": "gh pr view 4"}) == "deny"

    def test_gh_pr_create_denies_sandboxed(self):
        assert get_decision("Bash", {"command": "gh pr create"}) == "deny"

    def test_gh_api_read_sandboxed_denies(self):
        assert get_decision("Bash", {"command": "gh api repos/foo/bar"}) == "deny"

    def test_gh_api_post_denies_sandboxed(self):
        assert get_decision("Bash", {"command": "gh api --method POST repos/foo/bar"}) == "deny"

    def test_gh_api_read_sandboxed_message(self):
        """User must see the clear instruction to use bypass."""
        out = run_hook("Bash", {"command": "gh api repos/foo/bar"})
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert out["hookSpecificOutput"]["permissionDecisionReason"] == NEEDS_UNSANDBOXED

    # Safe redirections — verify metacheck still strips them. Use a non-gh
    # producer so the gh-deny rule doesn't dominate the assertion.
    def test_stderr_redirect_not_compound(self):
        assert get_decision("Bash", {"command": "git log --oneline 2>&1"}) == "allow"

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

    def test_unsandboxed_git_push_allows(self):
        # Plain push moved to SAFE_UNSANDBOXED_PATTERNS — auto-approves
        # when bypass is in effect. Force / delete variants still ask
        # (covered in TestGitPush below).
        assert get_decision("Bash", {
            "command": "git push",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

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

    def test_and_chain_with_gh_read_sandboxed_denies(self):
        """gh in a chain inside sandbox now denies — bypass needed."""
        assert get_decision("Bash", {"command": "git status && gh pr view 4"}) == "deny"

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
        """Verify redirect + safe pipe composition with a non-gh producer."""
        assert get_decision("Bash", {
            "command": "git log --oneline 2>&1 | head -20"
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

    # --- git fetch deny inside sandbox (parity with gh) ---

    def test_git_fetch_sandboxed_denies(self):
        out = run_hook("Bash", {"command": "git fetch"})
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert out["hookSpecificOutput"]["permissionDecisionReason"] == NEEDS_UNSANDBOXED

    def test_git_fetch_with_remote_sandboxed_denies(self):
        assert get_decision("Bash", {"command": "git fetch origin main"}) == "deny"

    def test_git_fetch_with_flags_sandboxed_denies(self):
        assert get_decision("Bash", {"command": "git --no-pager fetch --tags"}) == "deny"

    def test_git_fetch_unsandboxed_still_allows(self):
        """Bypass path unchanged — git fetch in SAFE_UNSANDBOXED_PATTERNS."""
        assert get_decision("Bash", {
            "command": "git fetch",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    # --- regression: don't over-match local git or affect git push ---

    def test_git_status_still_allows(self):
        assert get_decision("Bash", {"command": "git status"}) == "allow"

    def test_git_log_still_allows(self):
        assert get_decision("Bash", {"command": "git log --oneline"}) == "allow"

    def test_git_push_sandboxed_denies(self):
        """git push needs network/keyring — sandboxed it's denied with bypass instruction.
        Plain (non-force) variant: hits NEEDS_UNSANDBOXED_PATTERNS, not ASK_ALWAYS."""
        assert get_decision("Bash", {"command": "git push"}) == "deny"

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


class TestSkillScriptsUnsandboxed:
    """Skill scripts that wrap gh and need sandbox bypass should not prompt.
    Only accepted from home-rooted invocations (`bash ~/.claude/...`,
    `bash $HOME/.claude/...`, or `bash /home/<user>/.claude/...`). Arbitrary
    paths and bare-name forms must NOT be auto-approved."""

    # --- canonical bash forms: allow ---

    def test_fetch_coderabbit_threads_bash_form_allows(self):
        assert get_decision("Bash", {
            "command": "bash ~/.claude/skills/fetch-coderabbit-threads/scripts/fetch-coderabbit-threads.sh 70 --repo MotleyAI/slayer",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_fetch_failed_pr_checks_bash_form_allows(self):
        assert get_decision("Bash", {
            "command": "bash ~/.claude/skills/fetch-failed-pr-checks/scripts/fetch-failed-pr-checks.sh 70",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_reply_to_pr_thread_bash_form_allows(self):
        assert get_decision("Bash", {
            "command": "bash ~/.claude/skills/reply-to-pr-thread/scripts/reply-to-pr-thread.sh https://github.com/x/y/pull/1#discussion_r1",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_fetch_coderabbit_threads_absolute_home_allows(self):
        # `/home/<user>/.claude/...` is the resolved form of `~/.claude/...`
        assert get_decision("Bash", {
            "command": "bash /home/james/.claude/skills/fetch-coderabbit-threads/scripts/fetch-coderabbit-threads.sh 7",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    # `$HOME/...` is intentionally NOT in the allowlist regex: the
    # UNSAFE_META check (line 544) catches `$` as a shell metacharacter and
    # asks before we ever reach the allowlist. The shell expansion has to
    # happen earlier — either as `~/...` (no `$`) or a fully resolved
    # `/home/<user>/...` path.

    # --- spoofed prefixes: must ask ---

    def test_fetch_coderabbit_threads_tmp_prefix_asks(self):
        # `/tmp/.claude/skills/...` — an attacker-writable prefix. Must NOT
        # match the home-rooted allowlist; falls through to ask.
        assert get_decision("Bash", {
            "command": "bash /tmp/.claude/skills/fetch-coderabbit-threads/scripts/fetch-coderabbit-threads.sh 7",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_reply_to_pr_thread_tmp_prefix_asks(self):
        assert get_decision("Bash", {
            "command": "bash /tmp/.claude/skills/reply-to-pr-thread/scripts/reply-to-pr-thread.sh https://github.com/x/y/pull/1#discussion_r1",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    # --- bare-name direct forms: must ask (PATH could shadow with malicious) ---

    def test_fetch_failed_pr_checks_direct_form_asks(self):
        assert get_decision("Bash", {
            "command": "fetch-failed-pr-checks.sh 70 --repo MotleyAI/slayer",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_reply_to_pr_thread_direct_form_asks(self):
        assert get_decision("Bash", {
            "command": "reply-to-pr-thread.sh https://github.com/x/y/pull/1#discussion_r1",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    # --- unrelated scripts under skills/ are not auto-approved ---

    def test_unknown_skill_script_still_asks(self):
        assert get_decision("Bash", {
            "command": "bash ~/.claude/skills/some-other-script/scripts/foo.sh",
            "dangerouslyDisableSandbox": True,
        }) == "ask"


class TestGitPush:
    """git push: plain pushes are auto-approved unsandboxed; force/delete
    variants always ask; sandboxed pushes are denied with bypass instruction."""

    # --- plain push: allow when unsandboxed, deny when sandboxed ---

    def test_plain_push_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git push",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_push_origin_branch_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git push origin egor/foo",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_push_set_upstream_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git push -u origin egor/foo",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_push_long_set_upstream_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git push --set-upstream origin egor/foo",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_push_refspec_unsandboxed_allows(self):
        # source:dest refspec where source is non-empty — normal push, not deletion
        assert get_decision("Bash", {
            "command": "git push origin HEAD:refs/heads/egor/foo",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    # --- force / force-with-lease / etc.: always ask ---

    def test_push_force_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "git push --force",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_push_short_force_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "git push -f origin main",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_push_force_with_lease_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "git push --force-with-lease origin egor/foo",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_push_force_if_includes_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "git push --force-if-includes origin egor/foo",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    # --- delete variants: always ask ---

    def test_push_delete_long_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "git push --delete origin egor/foo",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_push_delete_short_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "git push -d origin egor/foo",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_push_deletion_refspec_unsandboxed_asks(self):
        # `:branch` with no source side deletes the remote branch
        assert get_decision("Bash", {
            "command": "git push origin :egor/foo",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_push_force_refspec_unsandboxed_asks(self):
        # `+ref` is a force-push refspec
        assert get_decision("Bash", {
            "command": "git push origin +egor/foo",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    # --- sandboxed: dangerous variants get denied (NEEDS_UNSANDBOXED) ---

    def test_push_force_sandboxed_denies(self):
        # When sandboxed, ASK_ALWAYS becomes deny ("This command needs unsandboxed access").
        # That's a stronger signal than the plain-push case below — both end up "deny"
        # but for different reasons (ASK_ALWAYS vs NEEDS_UNSANDBOXED).
        assert get_decision("Bash", {"command": "git push --force"}) == "deny"

    # --- regression: don't accidentally match unrelated git commands ---

    def test_push_substring_in_branch_name_doesnt_match_force(self):
        # Branch named "force-fix" — push body contains the literal "force" but
        # not as a flag. Token boundary requires `\s--force\b`; a branch name
        # `egor/force-fix` lacks the leading space and `--`, so no match.
        assert get_decision("Bash", {
            "command": "git push origin egor/force-fix",
            "dangerouslyDisableSandbox": True,
        }) == "allow"


class TestSafePipeScriptDirectForm:
    """Pipe-target safe-script allowlist accepts `bash <full-trusted-path>`
    only. The bare-name direct form and arbitrary paths (`/tmp/<spoofed>.sh`)
    must be rejected — a basename-only check would let any same-named script
    bypass the sandbox via the pipe path."""

    _trusted = os.path.expanduser(
        "~/.claude/skills/reply-to-pr-thread/scripts/reply-to-pr-thread.sh"
    )

    def test_bash_script_form_allows(self):
        # `echo body | bash <trusted-full-path>` — the canonical form.
        assert strip_safe_pipes(
            f"echo body | bash {self._trusted} https://github.com/x/y/pull/1#discussion_r1"
        ) == "echo body"

    def test_bash_script_with_tilde_allows(self):
        # The hook expands `~` before the membership check.
        assert strip_safe_pipes(
            "echo body | bash ~/.claude/skills/reply-to-pr-thread/scripts/reply-to-pr-thread.sh https://github.com/x/y/pull/1#discussion_r1"
        ) == "echo body"

    def test_bash_spoofed_path_rejected(self):
        # `bash /tmp/reply-to-pr-thread.sh ...` — same basename, different
        # path — must NOT be treated as a safe pipe target.
        assert strip_safe_pipes(
            "echo body | bash /tmp/reply-to-pr-thread.sh https://github.com/x/y/pull/1#discussion_r1"
        ) is None

    def test_direct_script_form_rejected(self):
        # Bare-name direct form drops the path information we'd need to
        # verify trust — must be rejected.
        assert strip_safe_pipes(
            "echo body | reply-to-pr-thread.sh https://github.com/x/y/pull/1#discussion_r1"
        ) is None

    def test_unknown_script_pipe_target_rejected(self):
        assert strip_safe_pipes("echo body | some-other-script.sh") is None

    def test_bash_unknown_script_pipe_rejected(self):
        assert strip_safe_pipes("echo body | bash /tmp/random.sh") is None


class TestGitPullMerge:
    """git pull / git merge: plain forms auto-approve unsandboxed; --rebase /
    -X theirs|ours / --squash variants are denied with custom advice telling
    Claude to use the plain form."""

    # --- plain git pull: deny sandboxed (NEEDS_UNSANDBOXED), allow unsandboxed ---

    def test_plain_pull_sandboxed_denies(self):
        assert get_decision("Bash", {"command": "git pull"}) == "deny"

    def test_plain_pull_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git pull",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_pull_origin_main_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git pull origin main",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_pull_ff_only_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git pull --ff-only",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_pull_no_rebase_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git pull --no-rebase",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    # --- plain git merge: deny sandboxed, allow unsandboxed ---

    def test_plain_merge_sandboxed_denies(self):
        assert get_decision("Bash", {"command": "git merge"}) == "deny"

    def test_merge_main_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git merge main",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_merge_abort_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git merge --abort",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_merge_no_ff_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git merge --no-ff main",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_merge_ff_only_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git merge --ff-only main",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    # --- pull --rebase / -r: deny with advice, regardless of sandbox ---

    def test_pull_rebase_long_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git pull --rebase",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_pull_rebase_short_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git pull -r origin main",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_pull_rebase_sandboxed_denies(self):
        assert get_decision("Bash", {"command": "git pull --rebase"}) == "deny"

    def test_pull_rebase_advice_mentions_plain_pull(self):
        # Sanity-check the deny reason — must steer the user toward the plain form.
        decision, reason = evaluate_single_cmd("git pull --rebase", True)
        assert decision == "deny"
        assert "git pull" in reason
        assert "rebase" in reason.lower()

    # --- merge -X theirs / ours / --strategy-option=...: deny with advice ---

    def test_merge_x_theirs_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git merge -X theirs",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_merge_x_theirs_no_space_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git merge -Xtheirs main",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_merge_strategy_option_theirs_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git merge --strategy-option=theirs main",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_merge_x_ours_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git merge -X ours",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_merge_x_ours_no_space_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git merge -Xours main",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_merge_strategy_option_ours_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git merge --strategy-option=ours main",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_merge_x_advice_mentions_plain_merge(self):
        decision, reason = evaluate_single_cmd("git merge -X theirs", True)
        assert decision == "deny"
        assert "git merge" in reason

    # --- merge / pull -s ours|theirs: deny with advice ---

    def test_merge_strategy_ours_unsandboxed_denies(self):
        # `-s ours` is more destructive than `-X ours` — it discards the
        # whole "theirs" tree, not just per-conflict hunks.
        assert get_decision("Bash", {
            "command": "git merge -s ours feature",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_merge_long_strategy_ours_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git merge --strategy=ours feature",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_merge_strategy_theirs_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git merge -s theirs feature",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_pull_strategy_ours_unsandboxed_denies(self):
        # pull = fetch + merge, so the strategy applies the same way
        assert get_decision("Bash", {
            "command": "git pull -s ours origin main",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_pull_long_strategy_theirs_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git pull --strategy=theirs origin main",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_merge_strategy_recursive_still_allowed(self):
        # `recursive` is git's default strategy — must NOT trip the deny.
        assert get_decision("Bash", {
            "command": "git merge -s recursive feature",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_pull_x_theirs_unsandboxed_denies(self):
        # `git pull` forwards `-X theirs` to the underlying merge, same
        # silent-conflict-resolution risk as `git merge -X theirs`.
        assert get_decision("Bash", {
            "command": "git pull -X theirs origin main",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_pull_x_ours_no_space_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git pull -Xours origin main",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_pull_strategy_option_theirs_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git pull --strategy-option=theirs origin main",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_merge_strategy_ours_advice_mentions_plain(self):
        decision, reason = evaluate_single_cmd("git merge -s ours feature", True)
        assert decision == "deny"
        assert "ours" in reason or "theirs" in reason
        assert "git merge" in reason or "git pull" in reason

    # --- merge --squash: deny with advice ---

    def test_merge_squash_unsandboxed_denies(self):
        assert get_decision("Bash", {
            "command": "git merge --squash main",
            "dangerouslyDisableSandbox": True,
        }) == "deny"

    def test_merge_squash_advice_mentions_plain_merge(self):
        decision, reason = evaluate_single_cmd("git merge --squash main", True)
        assert decision == "deny"
        assert "git merge" in reason
        assert "squash" in reason.lower()

    # --- regression: don't accidentally match unrelated commands ---

    def test_mergetool_doesnt_match_merge(self):
        # `git mergetool` has no word boundary after `merge`, so the merge
        # patterns shouldn't match. Falls through to the default "ask"
        # behavior for unsandboxed unknown commands.
        assert get_decision("Bash", {
            "command": "git mergetool",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_pull_substring_in_branch_doesnt_match_rebase(self):
        # Branch named `egor/rebase-fix` — token boundary requires `\s--rebase\b`
        # or `\s-r\b`; a branch name lacks the leading space-and-flag-prefix.
        assert get_decision("Bash", {
            "command": "git pull origin egor/rebase-fix",
            "dangerouslyDisableSandbox": True,
        }) == "allow"


class TestGitRemote:
    """git remote read-only subcommands: auto-approved unsandboxed (no network,
    just reads .git/config). Mutating subcommands (add/remove/set-url) still
    fall through to the default ask path."""

    def test_remote_bare_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git remote",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_remote_v_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git remote -v",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    def test_remote_get_url_unsandboxed_allows(self):
        assert get_decision("Bash", {
            "command": "git remote get-url origin",
            "dangerouslyDisableSandbox": True,
        }) == "allow"

    # `git remote show <name>` does network/keyring (per `git ls-remote`),
    # so it shouldn't auto-allow unsandboxed — it needs explicit bypass via
    # NEEDS_UNSANDBOXED_PATTERNS-equivalent path. Falls through to ask.
    def test_remote_show_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "git remote show origin",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    # --- mutating subcommands fall through to default ask ---

    def test_remote_add_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "git remote add upstream https://github.com/foo/bar.git",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_remote_set_url_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "git remote set-url origin https://github.com/foo/bar.git",
            "dangerouslyDisableSandbox": True,
        }) == "ask"

    def test_remote_remove_unsandboxed_asks(self):
        assert get_decision("Bash", {
            "command": "git remote remove origin",
            "dangerouslyDisableSandbox": True,
        }) == "ask"
