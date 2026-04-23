---
name: skill-creation
description: Guide for creating valid Claude Code skills. Use when user asks how to create a skill, make a skill, or needs help with skill structure.
---

# Claude Code Skill Creation Guide

This skill documents how to create valid Claude Code skills.

## CRITICAL: Placement Requirements

Skills MUST be in a `.claude/skills/` folder - Claude Code only scans these locations:

- **Global skills**: `~/.claude/skills/your-skill-name/SKILL.md`
- **Project-local skills**: `<project-root>/.claude/skills/your-skill-name/SKILL.md`

**Skills placed anywhere else will NOT be discovered.**

## CRITICAL: Naming Requirements

- **File MUST be named exactly `SKILL.md`** (case-sensitive - not `skill.md` or `SKILL.MD`)
- **Folder names MUST use kebab-case** (e.g., `notion-project-setup`)
- No spaces, underscores, or capital letters in folder names

## Required Structure

```
your-skill-name/           # kebab-case folder name
├── SKILL.md               # REQUIRED - exact filename
├── scripts/               # Optional - executable code
├── references/            # Optional - documentation
└── assets/                # Optional - templates, examples
```

## YAML Frontmatter (Required)

Every SKILL.md must start with YAML frontmatter:

```yaml
---
name: your-skill-name
description: When Claude should invoke this skill
---
```

The `description` field is critical - Claude uses it to decide when to automatically invoke the skill.

## Key Configuration Options

Add these to frontmatter as needed:

- `user-invocable: false` - Only Claude can invoke automatically (user cannot use `/command`)
- `disable-model-invocation: true` - Only user can invoke via `/command` (Claude cannot auto-invoke)
- `context: fork` - Run with specific agent type

## Best Practices

1. **Keep skills focused** - One workflow per skill
2. **Write clear descriptions** - Specific trigger conditions help Claude invoke appropriately
3. **Include examples** - In SKILL.md body or assets/ folder
4. **Test incrementally** - Verify skill is discovered before adding complexity
5. **All docs in skill folder** - No separate README.md, put everything in SKILL.md or subfolders

## Example: Minimal Skill

```markdown
---
name: my-task
description: Use when user asks to perform my-task or mentions my-task workflow
---

# My Task Skill

Instructions for Claude when this skill is invoked...

## Steps
1. First do X
2. Then do Y
3. Finally do Z
```

## Example: User-Only Skill

```yaml
---
name: deploy
description: Deploy the application to production
disable-model-invocation: true
---
```

User invokes with `/deploy` - Claude cannot auto-invoke.

## Verification Checklist

- [ ] File is exactly `SKILL.md` (case-sensitive)
- [ ] Folder uses kebab-case (no spaces, underscores, capitals)
- [ ] Located in `~/.claude/skills/` or `<project>/.claude/skills/`
- [ ] YAML frontmatter has `name` and `description`
- [ ] Description clearly states when skill should be invoked
