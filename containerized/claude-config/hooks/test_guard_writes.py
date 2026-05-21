"""Tests for the containerized external-mutation guard hook."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from guard_writes import _token_scan, offending  # noqa: E402


class TestTokenScanGhApiWrites:
    """gh api calls that mutate GitHub must be detected as external mutations."""

    def test_method_post_space(self):
        assert _token_scan("gh api /repos/o/r/issues -X POST")

    def test_method_post_equals(self):
        assert _token_scan("gh api /repos/o/r/issues --method=POST")

    def test_method_post_lowercase(self):
        assert _token_scan("gh api /repos/o/r/issues -X post")

    def test_method_post_attached(self):
        assert _token_scan("gh api /repos/o/r/issues -XPOST")

    def test_field_short(self):
        # `-f title=x` implicitly switches gh api to POST.
        assert _token_scan("gh api /repos/o/r/issues -f title=test")

    def test_field_long(self):
        assert _token_scan("gh api /repos/o/r/issues --field title=test")

    def test_field_equals(self):
        assert _token_scan("gh api /repos/o/r/issues --field=title=test")

    def test_raw_field_short(self):
        assert _token_scan("gh api /repos/o/r/issues -F count=1")

    def test_raw_field_long(self):
        assert _token_scan("gh api /repos/o/r/issues --raw-field count=1")

    def test_raw_field_equals(self):
        assert _token_scan("gh api /repos/o/r/issues --raw-field=count=1")

    def test_input_long(self):
        assert _token_scan("gh api /repos/o/r/issues --input body.json")

    def test_input_equals(self):
        assert _token_scan("gh api /repos/o/r/issues --input=body.json")

    def test_field_attached_short(self):
        # `-ftitle=x` (no space) — gh's cobra parser is unlikely to use
        # this form, but defensive flagging is harmless.
        assert _token_scan("gh api /repos/o/r/issues -ftitle=test")


class TestTokenScanGhApiReads:
    """GET-by-default gh api calls must NOT be flagged."""

    def test_plain_get(self):
        assert not _token_scan("gh api /repos/o/r/issues")

    def test_explicit_get_method(self):
        assert not _token_scan("gh api /repos/o/r/issues -X GET")

    def test_jq_filter(self):
        # `--jq` is not a body flag and must not match.
        assert not _token_scan("gh api /repos/o/r/issues --jq .id")

    def test_header(self):
        # `-H` / `--header` is not a body flag and must not match.
        assert not _token_scan("gh api /repos/o/r/issues -H Accept:application/json")

    def test_paginate(self):
        assert not _token_scan("gh api /repos/o/r/issues --paginate")


class TestTokenScanGitPush:
    """git push (any form) is an external mutation."""

    def test_simple_push(self):
        assert _token_scan("git push origin main")

    def test_push_with_dash_c(self):
        assert _token_scan("git -C /workspace/repo push origin main")

    def test_git_status_not_push(self):
        assert not _token_scan("git status")


class TestOffendingChain:
    """offending() walks compound commands and returns the first hit."""

    def test_and_chain_catches_push(self):
        assert offending("git status && git push") == "git push"

    def test_pipe_chain_catches_api_field(self):
        assert offending("echo body | gh api /repos/o/r -f title=x") == "gh api /repos/o/r -f title=x"

    def test_no_offending(self):
        assert offending("git status && git diff") is None
