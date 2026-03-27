---
name: manage-cowork
description: Manage the Cowork service and Claude Desktop. Use when the user wants to start, stop, or reinstall cowork.
---

# Manage Cowork

## Starting Cowork

Start the cowork service and launch Claude Desktop:

```bash
/bin/bash ~/.claude/skills/manage-cowork/scripts/start-cowork.sh
```

Report the output to the user.

## Stopping Cowork

Stop the cowork service and kill Claude Desktop:

```bash
/bin/bash ~/.claude/skills/manage-cowork/scripts/stop-cowork.sh
```

## Reinstalling Cowork

Fully reinstall Claude Desktop and the cowork service (removes state, reinstalls packages via APT). **Note: this script requires sudo.**

```bash
/bin/bash ~/.claude/skills/manage-cowork/scripts/reinstall-cowork.sh
```
