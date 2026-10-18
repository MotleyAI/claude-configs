"""Tests for block_claude_attribution.py PreToolUse hook."""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

HOOK_PATH = os.path.join(os.path.dirname(__file__), "block_claude_attribution.py")
_spec = importlib.util.spec_from_file_location("block_claude_attribution", HOOK_PATH)
assert _spec and _spec.loader
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


def run_hook(payload):
    """Run the hook with `payload` as stdin; return its stdout."""
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    result = subprocess.run(
        [sys.executable, HOOK_PATH], input=stdin, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def bash(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


ATTRIBUTIONS = [
    "Generated with [Claude Code](https://claude.com/claude-code)",
    "generated with claude code",
    "Co-Authored-By: Claude <noreply@anthropic.com>",
    "see https://claude.com/claude-code",
]


class TestInlineBody:
    @pytest.mark.parametrize("text", ATTRIBUTIONS)
    @pytest.mark.parametrize("prefix", [
        "gh pr create --title t --body",
        "gh pr edit 1 --body",
        "gh pr comment 1 --body",
        "gh pr review 1 --approve --body",
        "gh issue create --title t --body",
        "gh issue edit 1 --body",
        "gh issue comment 1 --body",
        "gh release create v1 --notes",
        "gh release edit v1 --notes",
        "gh api repos/o/r/issues/1/comments -f body=",
    ])
    def test_publishing_with_attribution_blocked(self, prefix, text):
        assert hook._offending(f"{prefix} '{text}'")

    def test_clean_body_allowed(self):
        assert not hook._offending("gh pr create --title t --body 'Adds X'")

    @pytest.mark.parametrize("cmd", [
        "git commit -m 'Generated with Claude Code'",  # commit-msg git hook's job
        "echo 'Co-Authored-By: Claude'",
        "gh pr view 1",  # reads, doesn't publish
    ])
    def test_non_publishing_commands_ignored(self, cmd):
        assert not hook._offending(cmd)


class TestBodyFile:
    @pytest.mark.parametrize("flag", ["--body-file", "-F", "--input", "--notes-file"])
    def test_attribution_in_file_blocked(self, tmp_path, flag):
        body = tmp_path / "body.md"
        body.write_text("Fixes X\n\n" + ATTRIBUTIONS[0] + "\n")
        assert hook._offending(f"gh pr create --title t {flag} {body}")

    def test_body_file_equals_form(self, tmp_path):
        body = tmp_path / "body.md"
        body.write_text(ATTRIBUTIONS[2])
        assert hook._offending(f"gh pr create --body-file={body}")

    def test_api_field_at_file(self, tmp_path):
        body = tmp_path / "body.md"
        body.write_text(ATTRIBUTIONS[1])
        assert hook._offending(f"gh api repos/o/r/issues/1/comments -F body=@{body}")

    def test_clean_file_allowed(self, tmp_path):
        body = tmp_path / "body.md"
        body.write_text("Fixes X\n")
        assert not hook._offending(f"gh pr create --title t --body-file {body}")

    def test_missing_file_allowed(self, tmp_path):
        assert not hook._offending(f"gh pr create --body-file {tmp_path / 'nope.md'}")


class TestFileArgs:
    def test_collects_every_form(self):
        tokens = ["gh", "api", "x", "--input", "a", "-F", "k=@b", "-f", "k=@c",
                  "--body-file=d", "--notes-file", "e"]
        assert hook._file_args(tokens) == ["a", "b", "c", "d", "e"]

    def test_plain_field_value_not_a_file(self):
        assert hook._file_args(["gh", "api", "x", "-f", "body=hi"]) == []


class TestHookProcess:
    def test_denies_with_reason(self):
        out = json.loads(run_hook(bash(
            f"gh pr create --title t --body '{ATTRIBUTIONS[0]}'")))
        decision = out["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny"
        assert "attribution" in decision["permissionDecisionReason"]

    def test_clean_command_no_output(self):
        assert run_hook(bash("gh pr create --title t --body 'Adds X'")) == ""

    def test_non_bash_tool_ignored(self):
        assert run_hook({"tool_name": "Write", "tool_input": {
            "content": ATTRIBUTIONS[0]}}) == ""

    def test_invalid_json_ignored(self):
        assert run_hook("not json") == ""

    def test_unbalanced_quotes_still_checked(self):
        out = run_hook(bash(f"gh pr create --body \"{ATTRIBUTIONS[0]}"))
        assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
