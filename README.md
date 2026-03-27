# Introduction
This repo's purpose is to make it easier to setup Claude Code on a new machine.

# Setup
1. Clone this repo, move the containing folder to `~/.claude` (sadly Claude doesn't seem to work with softlinks)
2. Put into a .env file located somewhere else your relevant API keys, as well as the extra directories for the PYTHONPATH. 
For example:
```bash
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
PYTHONPATH_DIRS="/path/to/your/first/directory:/path/to/your/second/directory"
PERPLEXITY_API_KEY=your_key_here
NOTION_API_KEY=your_key_here
```
Feel free to add other functionality to prepare.py as needed (triggered by new .env variables, so it's backwards compatible)

3. Put into `~/.bashrc`:
```bash
source ~/.claude/scripts/prepare.sh /path/to/your/.env/file
```

4. [Install Claude Code](https://docs.anthropic.com/en/docs/claude-code/setup), start up a new bash shell, 
for example inside your IDE, and start claude there. 

Then when you start a new shell, it will source the .env file and activate the conda environment 
(if specified in the .env file), as well as add any extra directories to the PYTHONPATH, 
so when you start claude code, it will have the correct paths and variables set up already.

Contents:
[Claude Code in Action.md](docs/Claude%20Code%20in%20Action.md) is a compilation of information from various sources to get you started with Claude Code.

`.mcp.json` is a compilation of useful MCP servers, **you need to copy it to each project directory for it to work there**.

Supposedly ~/.claude.json is the place to configure global MCP settings, but Claude Code randomly overwrites it 
on a whim, so **don't put anything important there**.

Also Claude writes conversation history to ~/.claude.json, so **don't put it in version control**.

To run this against a locally running instance of motley, change the URL in `.mcp.json` to `https://localhost:5173/api/v1/mcp/` 

