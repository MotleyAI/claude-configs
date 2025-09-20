 Run `coderabbit review --plain` to get comprehensive code analysis and improvement suggestions. Apply the feedback to write cleaner, more maintainable code.

Only run this from a git repository root directory.

Before running the command, check whether the codebase has any changes since the last commit, if yes just call the command normally, if not first ask the user what they want to use as a baseline: previous commit, the moment when the branch was first created, the codebase as a whole, etc, and use the corresponding option from the below.

ALWAYS use the --config command and attach ALL CLAUDE.md files that you yourself would have used to write code in this repo (so global-level, repository-level, and any contained deeper down in the repo).

Available options for the `coderabbit review` command:
  Options:
  -V, --version            output the version number
  --plain                  Output in plain text format (non-interactive)
  --prompt-only            Show only AI agent prompts (implies --plain)
  -t, --type <type>        Review type: all, committed, uncommitted (default: "all")
  -c, --config <files...>  Additional instructions for CodeRabbit AI (e.g., claude.md, coderabbit.yaml)
  --base <branch>          Base branch for comparison
  --base-commit <commit>   Base commit on current branch for comparison
  --cwd <path>             Working directory path
  --no-color               Disable colored output
  -h, --help               display help for command


ALWAYS SET THE bash TIMEOUT TO 15 MINUTES as this might take a while to run.
