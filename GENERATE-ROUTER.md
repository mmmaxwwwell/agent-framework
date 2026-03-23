# Generate Router

Regenerate `ROUTER.md` at the repo root by scanning all skill definitions.

## Steps

1. **Find all skills**: Glob for `.claude/skills/*/SKILL.md`
2. **Parse each skill**: Read the YAML frontmatter from each `SKILL.md` and extract:
   - `name` — the skill name
   - `description` — used as the "Use when" column
   - Path — relative path to the `SKILL.md` file (`.claude/skills/<name>/SKILL.md`)
3. **Write `ROUTER.md`** with this exact structure:

```markdown
# Skill Router

Use this file to select the right skill(s) for a task. Read the table, match against the descriptions, then follow each matching skill's `SKILL.md`.

## Available Skills

| Skill | Path | Use when |
|-------|------|----------|
| <name> | `<path>` | <description> |
...

## Selection

Match the user's request against the **Use when** column. Apply every skill that matches — multiple skills can be used in the same task. If no skill matches, proceed without the router.

### Code review precedence

The code-review skills form a hierarchy. Language-specific skills include all base checks, so **never load code-review alongside a language-specific variant** — that would duplicate the base checks. Selection rules:

1. If the project is React / Next.js → use **code-review-react** (skip code-review)
2. If the project is Node.js / backend JS/TS → use **code-review-node** (skip code-review)
3. If the project is both (e.g. Next.js full-stack) → use **code-review-react** (it covers the most relevant frontend + general checks; Node-specific backend patterns are also covered by the general categories)
4. If the project uses neither React nor Node.js, or you can't determine the stack → use **code-review**

When uncertain, check `package.json` or file extensions in the diff to determine which skill to load.

## How to Use a Skill

1. **Announce**: Tell the user which skill(s) you are loading. ALWAYS say it out loud — e.g. "Loading skill: **generate-feature**". Never silently load a skill.
2. Read the skill's `SKILL.md` at the path above
3. Follow its instructions exactly
4. The `SKILL.md` contains the full prompt — frontmatter is metadata, the body is your instructions
```

4. **Sort** skills alphabetically by name in the table
5. **Report** what was written
