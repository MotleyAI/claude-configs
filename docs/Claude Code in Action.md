---
---

# Table of Contents

- [CLI commands and config](#cli-commands-and-config)
  - [Config files](#config-files)
  - [CLI basics](#cli-basics)
  - [File Mentions with '@'](#file-mentions-with-)
  - [Rewinding Conversations](#rewinding-conversations)
- [Thinking vs Planning modes](#thinking-vs-planning-modes)
  - [Planning Mode](#planning-mode)
  - [Thinking Modes](#thinking-modes)
  - [When to Use Planning vs Thinking](#when-to-use-planning-vs-thinking)
- [Use of subagents](#use-of-subagents)
- [Creating Custom Commands](#creating-custom-commands)
  - [Example: Audit Command](#example-audit-command)
  - [Commands with Arguments](#commands-with-arguments)
  - [Key Benefits](#key-benefits)
- [Multiple sessions using git trees](#multiple-sessions-using-git-trees)
- [The GitHub Integration](#the-github-integration)
  - [Customizing the Workflows](#customizing-the-workflows)
  - [Adding Project Setup](#adding-project-setup)
  - [Custom Instructions](#custom-instructions)
  - [MCP Server Configuration](#mcp-server-configuration)
  - [Tool Permissions](#tool-permissions)
- [Tool usage](#tool-usage)
  - [Builtin tools](#builtin-tools)
  - [MCP servers (mostly by example)](#mcp-servers-mostly-by-example)
    - [Installing the Playwright MCP Server](#installing-the-playwright-mcp-server)
    - [Managing Permissions](#managing-permissions)
    - [Using Figma MCP server to create web app based on a mockup](#using-figma-mcp-server-to-create-web-app-based-on-a-mockup)
  - [Hooks](#hooks)
    - [Hook Configuration](#hook-configuration)
  - [Practical Applications](#practical-applications)
  - [Example Use Case](#example-use-case)
  - [Key Benefits](#key-benefits-1)
- [Claude SDK](#claude-sdk)
  - [JS example](#js-example)
  - [Permissions and Tools](#permissions-and-tools)
- [Other](#other)
  - [Notebook interaction](#notebook-interaction)
    - [AWS Bedrock and Google Vertex](#aws-bedrock-and-google-vertex)
  - [Other](#other-1)

This is a merge of information mostly from these courses:
<https://anthropic.skilljar.com/claude-code-in-action>
<https://learn.deeplearning.ai/courses/claude-code-a-highly-agentic-coding-assistant>
<https://www.coursera.org/learn/claude-code>

# CLI commands and config

## Config files

![[image.1.png]]
JSON config files:

|                                                                      |        |                                                                                                                                                                                                                                                    |
| -------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| File Name / Location                                                 | Format | Purpose / Intent                                                                                                                                                                                                                                   |
| ~/.claude.json(User home directory)                                  | JSON   | Main global configuration for the user’s environment; **highest-priority** settings such as tool access, MCP servers<br>**Gets randomly overwritten by Claude itself - don't save anything important there, such as global MCP servers settings!** |
| ~/.claude/settings.json(User home directory)                         | JSON   | User-specific global settings; applies defaults to all projects but is overrdden by both ~.claude.json and<br>project-specific settings                                                                                                            |
| ~/.claude/settings.local.json(User home directory)                   | JSON   | User-specific local settings for preferences and experimentation; ignored by git, not shared                                                                                                                                                       |
| .mcp.json (Project directory)                                        | JSON   | Project-specific MCP configs                                                                                                                                                                                                                       |
| .claude/settings.json(Project directory)                             | JSON   | Project settings shared via source control; permissions, hooks, tool configs—effective for project team                                                                                                                                            |
| .claude/settings.local.json(Project directory)                       | JSON   | Local project-specific settings for personal preferences or experimental changes; not checked into source control                                                                                                                                  |
| /Library/Application Support/ClaudeCode/managed-settings.json(macOS) | JSON   | Enterprise managed policy settings (admin-controlled); override user/project                                                                                                                                                                       |
| /etc/claude-code/managed-settings.json(Linux/WSL)                    | JSON   | Enterprise managed policy settings (admin-controlled)                                                                                                                                                                                              |
| C:\\ProgramData\\ClaudeCode\\managed-settings.json(Windows)          | JSON   | Enterprise managed policy settings (admin-controlled)                                                                                                                                                                                              |

Markdown files, especially `CLAUDE.md`, act as persistent project instructions and are highly flexible for conveying documentation, workflow, and behavioral rules for Claude Code
	
Here is a [pretty radical example](https://github.com/citypaul/.dotfiles/blob/main/claude/.claude/CLAUDE.md) of a `CLAUDE.md`
## CLI basics

When you first start Claude Code in a new repo, run /init to create the `CLAUDE.md` for the directory

You can have `CLAUDE.md` files in subrdirs too, with specific context for those subdirs.
You can also have a `CLAUDE.md` in ~/.claude

/help

It also understands git, you can ask it to commit stuff

Ask Claude Code for explanations, including diagrams and visualizations (eg ascii art). 
"Can augment Claude code with additional tools for generating visualizations" - how?

* You can press the Escape key to stop Claude mid-response, allowing you to redirect the conversation.
* Use the ==`#` command to enter "memory mode"== - this lets you edit your `CLAUDE.md` files intelligently. 
	* Just type something like: `# Use comments sparingly. Only comment complex code.` and Claude will merge this instruction into your CLAUDE.md file automatically.

* Combining Escape with Memories
	When Claude makes the same mistake repeatedly across different conversations, you can:
	* Press Escape to stop the current response
	* Use the # shortcut to add a memory about the correct approach
	* Continue the conversation with the corrected information
* To paste a screenshot into Claude Code, use Ctrl+V (even on Mac!), or you can specify a filename
* To resume a conversations start claude like `claude --resume`
* /permissions manage tool permissions
* **/** to see all available commands
* Use /ide command to connect to the IDE you're in (careful, this might also confuse it with unneeded context)
* ==The== **==/clear==** ==command completely removes the conversation history, giving you a fresh start==.
	
* ==The== **==/compact==** ==command summarizes your entire conversation history while preserving the key information Claude has learned.==  Use compact when Claude has learned a lot about the current task and you want to maintain that knowledge as it moves to the next related task.This is ideal when:
	* Claude has gained valuable knowledge about your project
	* You want to continue with related tasks
	* The conversation has become long but contains important context

		People have been complaining about this destroying context, though, so use with caution

### File Mentions with '@'

==When you need Claude to look at specific files, use the @symbol followed by the file path.== This automatically includes that file's contents in your request to Claude.
For example, if you want to ask about your authentication system and you know the relevant files, you can type: `How does the auth system work? @auth`
Claude will show you a list of auth-related files to choose from, then include the selected file in your conversation.
==You can also mention files directly in your== `CLAUDE.md` file using the same **==@==**==syntax.== This is particularly useful for files that are relevant to many aspects of your project.
For example, if you have a database schema file that defines your data structure, you might add this to your `CLAUDE.md`
"The database schema is defined in the @prisma/schema.prisma file. Reference it anytime you need to understand the structure of data stored in the database."
When you mention a file this way, its contents are automatically included in every request, so Claude can answer questions about your data structure immediately without having to search for and read the schema file each time.

### Rewinding Conversations

==You can rewind the conversation by pressing Escape twice. This shows you all the messages you've sent==, allowing you to jump back to an earlier point and continue from there. This technique helps you:

* Maintain valuable context (like Claude's understanding of your codebase)
* Remove distracting or irrelevant conversation history
* Keep Claude focused on the current task

## Thinking vs Planning modes

### Planning Mode

For more complex tasks that require extensive research across your codebase, you can enable Planning Mode. This feature makes Claude do thorough exploration of your project before implementing changes.
==Enable Planning Mode by pressing== **==Shift + Tab==** ==twice (or once if you're already auto-accepting edits).== In this mode, Claude will:

* Read more files in your project
* Create a detailed implementation plan
* Show you exactly what it intends to do
* Wait for your approval before proceeding

This gives you the opportunity to review the plan and redirect Claude if it missed something important or didn't consider a particular scenario.

### Thinking Modes

Claude offers different levels of reasoning through "thinking" modes. These allow Claude to spend more time reasoning about complex problems before providing solutions.
The available thinking modes include:

* "Think" - Basic reasoning
* "Think more" - Extended reasoning
* "Think a lot" - Comprehensive reasoning
* "Think longer" - Extended time reasoning
* "Ultrathink" - Maximum reasoning capability

Each mode gives Claude progressively more tokens to work with, allowing for deeper analysis of challenging problems.

### When to Use Planning vs Thinking

These two features handle different types of complexity:
Planning Mode is best for:

* Tasks requiring broad understanding of your codebase
* Multi-step implementations
* Changes that affect multiple files or components

Thinking Mode is best for:

* Complex logic problems
* Debugging difficult issues
* Algorithmic challenges

You can combine both modes for tasks that require both breadth and depth. Just keep in mind that both features consume additional tokens, so there's a cost consideration for using them.

Example for calling think mode:
![[image.8.png]]
==Use== `/model` ==to toggle between Opus and Sonnet, separately for planning and regular mode==, can persist it
* According to some reports on LinkedIn, Sonnet is actually better at coding, so  a sane default might be the "opusplan" option there, Opus for planning, Sonnet for coding.

## Creating and using documentation
Here is a [great blog](https://mcpcat.io/guides/ask-claude-code-to-read-documentation/) on that

# Creating Custom Commands

https://docs.anthropic.com/en/docs/claude-code/slash-commands
A custom command is defined by a markdown file either in `~/.claude/commands` or in `[project_dir]/.claude/commands`.
==The filename becomes your command name== \- so audit.md creates the **/audit** command.

Excercise: build a custom command for a documentation generator

## Example: Audit Command

Here's a practical example of a custom command that audits project dependencies for vulnerabilities:
![[image.2.png]]
==After creating your command file, you must restart Claude Code== for it to recognize the new command.

## Commands with Arguments

==Custom commands can accept arguments using the== **==$ARGUMENTS==** ==placeholder.== This makes them much more flexible and reusable. For example, a **write\_tests.md** command might contain:

```
Write comprehensive tests for: $ARGUMENTS

Testing conventions:
* Use Vitests with React Testing Library
* Place test files in a __tests__ directory in the same folder as the source file
* Name test files as [filename].test.ts(x)
* Use @/ prefix for imports

Coverage:
* Test happy paths
* Test edge cases
* Test error states
```
You can then run this command with a file path:
**/write\_tests the use-auth.ts file in the hooks directory** 
The arguments don't have to be file paths - they can be any string you want to pass to give Claude context and direction for the task.

## Key Benefits

* Automation- Turn repetitive workflows into single commands
* Consistency- Ensure the same steps are followed every time
* Context- Provide Claude with specific instructions and conventions for your project
* Flexibility- Use arguments to make commands work with different inputs

Custom commands are particularly useful for project-specific workflows like running test suites, deploying code, or generating boilerplate following your team's conventions.

# Parallelization

## Use of subagents

You've learned that one of the out-of-the-box tools for Claude Code is Task, which Claude Code can use to launch subagents for complex multi-step tasks. You can explicitly ask Claude Code to use subagents to brainstorm ideas or to investigate multiple aspects of a question or a problem you want to solve. These built-in agents are of general purpose.
You can also create your customized specialized subagents. Each subagent has its own context window, and you can define a custom system prompt and specific tools for each subagent. You can check the details in the documentation [here](https://docs.anthropic.com/en/docs/claude-code/sub-agents).

=="Use two parallel subagents to brainstorm possible plans."==

## Multiple sessions using git trees

Worktrees for git, to avoid sessions getting in each other's way.
`mkdir .trees`
![[image.9.png]]
Then start Claude in the respective dir's directory, run it separately
Once all of them done, in the main claude say
"Use the git merge command to merge all of the worktrees in the .trees folder and fix any conflicts if there are any"
"Remove the .trees folder and the underlying worktrees, and once you're done, push this code to github"
Also see [this blog](https://incident.io/blog/shipping-faster-with-claude-code-and-git-worktrees#git-worktrees-the-unsung-hero)

# The GitHub Integration

To get started, run **/install-github-app** in Claude. This command walks you through the setup process:

* Install the Claude Code app on GitHub
* Add your API key
* Automatically generate a pull request with the workflow files

The generated pull request adds two GitHub Actions to your repository. Once merged, you'll have the workflow files in your **.github/workflows** directory.

The initial actions are PR review and tagging claude, eg ==in issues, @claude can you fix this for me== and the bot does so live right in GitHub!

## Customizing the Workflows

After merging the initial pull request, you can customize the workflow files to fit your project's needs. Here's how to enhance the mention workflow:

## Adding Project Setup

Before Claude runs, you can add steps to prepare your environment:

```
- name: Project Setup
  run: |
    npm run setup
    npm run dev:daemon
```

## Custom Instructions

Provide Claude with context about your project setup:

```
custom_instructions: |
  The project is already set up with all dependencies installed.
  The server is already running at localhost:3000. Logs from it
  are being written to logs.txt. If needed, you can query the
  db with the 'sqlite3' cli. If needed, use the mcp__playwright
  set of tools to launch a browser and interact with the app.
```

## MCP Server Configuration

You can configure MCP servers to give Claude additional capabilities:

```
mcp_config: |
  {
    "mcpServers": {
      "playwright": {
        "command": "npx",
        "args": [
          "@playwright/mcp@latest",
          "--allowed-origins",
          "localhost:3000;cdn.tailwindcss.com;esm.sh"
        ]
      }
    }
  }
```

## Tool Permissions

When running Claude in GitHub Actions, you must explicitly list all allowed tools. This is especially important when using MCP servers.

```
allowed_tools: "Bash(npm:*),Bash(sqlite3:*),mcp__playwright__browser_snapshot,mcp__playwright__browser_click,..."
```
Unlike local development, there's no shortcut for permissions in GitHub Actions. Each tool from each MCP server must be individually listed.
[Anthropic Blog](https://support.anthropic.com/en/articles/10167454-using-the-github-integration)

# Tool usage

## Builtin tools

![[image.png]]

![[image.png]]
## MCP servers (mostly by example)
Here is a [guide on troubleshooting](https://mcpcat.io/guides/adding-an-mcp-server-to-claude-code/) (careful: its Notion MCP config for example is out of date)


* You can use env variables in the jsons, like 
```
"env": {
  "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
}
```
* Quick toggle servers like
```
# Disable without removing
"github": {
  "disabled": true,  // Add this
  "command": "npx",
  ...
}
```

Here is a [list of useful servers](https://mcpcat.io/guides/best-mcp-servers-for-claude-code/)
### Installing the Playwright MCP Server

To add the Playwright server to Claude Code, run this command in your terminal (not inside Claude Code):
`claude mcp add playwright npx @playwright/mcp@latest`

This command does two things:
* Names the MCP server "playwright"
* Provides the command that starts the server locally on your machine

You can remove it again by `claude mcp remove playwright`
### Managing Permissions

When you first use MCP server tools, Claude will ask for permission each time. If you get tired of these permission prompts, ==you can pre-approve the server by editing your settings.==

Open the **.claude/settings.local.json** file and add the server to the allow array:

```
{
  "permissions": {
    "allow": ["mcp__playwright"],
    "deny": []
  }
}
```
Note the double underscores in **mcp\_\_playwright**.

### Using Figma MCP server to create web app based on a mockup

To init a new app: npx create-next-app@latest .
In figma, Preferences >  enable dev mode mcp server
https://learn.deeplearning.ai/courses/claude-code-a-highly-agentic-coding-assistant/lesson/vvq28/creating-web-app-based-on-a-figma-mockup
Copy link to selection: ctrl-L
claude mcp add --transport http figma-dev-mode-mcp-server http://127.0.0.1:3845/mcp
also add playwright mcp like above
![[image.10.png]]

### Combined search MCP server
Built by Scott Spence [here](https://scottspence.com/posts/configuring-mcp-tools-in-claude-code#consolidating-my-mcp-tools-with-mcp-omnisearch)
### Sequential Thinking - Complex Tasks
```
"sequential-thinking": {
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
}
```

### Context7: up-to-date docs
```
"context7": {
  "command": "npx",
  "args": ["-y", "@upstash/context7-mcp@latest"]
}
```

## Hooks

There are two types of hooks:

* PreToolUse hooks- Run before a tool is called
* PostToolUse hooks- Run after a tool is called

![[image.3.png]]

### Hook Configuration

==You can write hooks by hand in these files or use the== **==/hooks==** ==command inside Claude Code.==

![[image.4.png]]![[image.5.png]]![[image.6.png]]

## Practical Applications

Here are some common ways to use hooks:

* Code formatting- Automatically format files after Claude edits them
* Testing- Run tests automatically when files are changed
* Access control- Block Claude from reading or editing specific files
* Code quality- Run linters or type checkers and provide feedback to Claude
* Logging- Track what files Claude accesses or modifies
* Validation- Check naming conventions or coding standards

## Example Use Case

A common use case is preventing Claude from reading sensitive files like **.env** files.
(more details in <https://anthropic.skilljar.com/claude-code-in-action/312002>, will ingest later)

## Key Benefits

This approach provides several advantages:

* Proactive protection- blocks access before sensitive data is read
* Transparent operation- Claude understands why the operation failed
* Flexible matching- works with multiple tools (read, grep, etc.)
* Clear feedback- provides meaningful error messages

# Claude SDK

![[image.7.png]]

## [JS example](https://anthropic.skilljar.com/claude-code-in-action/312001)

## Permissions and Tools

By default, the SDK only has read-only permissions. It can read files, search directories, and perform grep operations, but it cannot write, edit, or create files.

To enable write permissions, you can add the **allowedTools** option to your query
Alternatively, you can configure permissions in your settings file within the **.claude**directory for project-wide access.

https://learn.deeplearning.ai/courses/claude-code-a-highly-agentic-coding-assistant/lesson/66b35/introduction

# Other

## Notebook interaction

[Specific code to interact with notebooks!](https://learn.deeplearning.ai/courses/claude-code-a-highly-agentic-coding-assistant/lesson/33kzr/refactoring-a-jupyter-notebook-&-creating-a-dashboard)

### AWS Bedrock and Google Vertex

If you're making use of AWS Bedrock or Google Cloud Vertex, there is some additional setup:

* Special directions for AWS Bedrock: <https://docs.anthropic.com/en/docs/claude-code/amazon-bedrock>
* Special directions for Google Cloud Vertex: [https://docs.anthropic.com/en/docs/claude-code/google-vertex-](https://docs.anthropic.com/en/docs/claude-code/google-vertex-ai)

## Other

[Prompts, summaries of lessons, and general pointers:](https://learn.deeplearning.ai/courses/claude-code-a-highly-agentic-coding-assistant/lesson/hhfj3/prompts-&-summaries-of-lessons)
