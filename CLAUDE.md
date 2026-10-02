# CLAUDE.md — Agent Framework

## What this repo is

A collection of reusable Claude Code skills, packaged as nix flake outputs. Each skill is a self-contained prompt that teaches an agent how to perform a specific workflow.

## Repo structure

```
skills/<skill-name>/SKILL.md   # Skill definitions (content)
commands/<skill-name>.md       # Slash command wrappers (thin — reference SKILL.md)
flake.nix                      # Nix packaging — one output per skill + home-manager module
README.md                      # Human-facing docs
```

## How skills are consumed

1. **Nix package** — each skill is a separate derivation (`packages.<system>.<skill-name>`)
2. **Slash commands** — nix installs command wrappers to `~/.claude/commands/` via home-manager
3. **Auto-load** — `eng-standards` is referenced from `~/CLAUDE.md` for all software tasks
4. **Sub-flakes** — `spec-kit/runner-ts`, `spec-kit/runner`, `spec-kit/code-review-graph` are includable flake inputs

## Working in this repo

### Adding a new skill

1. Create `skills/<skill-name>/SKILL.md`
2. Include frontmatter: `name`, `description`, `user-invocable`, `allowed-tools`, `argument-hint`
3. Create `commands/<skill-name>.md` with `@SKILL_PATH@` placeholder
4. Add the skill name to `skillNames` in `flake.nix`
5. Add the skill to the `README.md` skills section

### Editing a skill

- Keep prompts dense but scannable: bullets, tables, code-formatted paths
- Every instruction should be specific and actionable
- Test by running the skill on a real project before committing

### Command wrappers

Command files in `commands/` use `@SKILL_PATH@` which nix substitutes at build time with the store path. This means slash commands always reference the correct skill version.

## Conventions

- Skill names are lowercase kebab-case
- One `SKILL.md` per skill directory
- Prompts are written for Claude but should work when pasted into any LLM
