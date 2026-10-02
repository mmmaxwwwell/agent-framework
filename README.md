# Agent Framework

A collection of reusable Claude Code skills — self-contained prompts that teach an agent how to perform specific workflows. Packaged as nix flake outputs.

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI installed
- [Nix](https://nixos.org/download/) with flakes enabled

## Install

### With nix + home-manager

Add to your flake inputs:

```nix
inputs.agent-framework.url = "github:mmmaxwwwell/agent-framework";
```

Then enable in your home-manager config:

```nix
{ inputs, ... }: {
  imports = [ inputs.agent-framework.homeManagerModules.default ];

  programs.claude-skills = {
    enable = true;
    # Install all skills (default), or pick specific ones:
    # skills = [ "code-review" "eng-standards" "spec-kit" ];
  };
}
```

This installs slash commands (`/code-review`, `/spec-kit`, etc.) into `~/.claude/commands/`.

### Individual skill packages

Each skill is a separate nix package:

```bash
nix build github:mmmaxwwwell/agent-framework#code-review
nix build github:mmmaxwwwell/agent-framework#spec-kit
nix build github:mmmaxwwwell/agent-framework#all  # everything
```

### eng-standards auto-load

Add to your `~/CLAUDE.md` to auto-apply engineering standards on all software tasks:

```markdown
For software, programming, or computer-related tasks: read and apply the engineering standards skill at ~/git/agent-framework/skills/eng-standards/SKILL.md before starting work.
```

### Without nix

The skill files at `skills/*/SKILL.md` contain the full prompts. Paste the contents of any `SKILL.md` into any AI chat and it will work — the frontmatter is ignored by non-Claude-Code tools.

## Which skill should I use?

```
Building something new from scratch?
└── Want full spec-driven development (specs → plans → tasks → autonomous implementation)?
    └── /spec-kit

Reviewing code?
├── React / Next.js → /code-review-react
├── Node.js / backend JS/TS → /code-review-node
└── Anything else → /code-review

Reviewing UI?
└── /ux-review

Want engineering standards without a workflow?
└── /eng-standards (or auto-loaded via ~/CLAUDE.md)

Setting up MCP toolbelt in a project?
└── /toolbelt-setup (one-time, or on update)
```

## Skills

| Skill | Description |
|-------|-------------|
| [`code-review`](skills/code-review/SKILL.md) | Review code for bugs, security, performance — language-agnostic base layer |
| [`code-review-node`](skills/code-review-node/SKILL.md) | Node.js-specific review (extends code-review with async, event loop, dependency checks) |
| [`code-review-react`](skills/code-review-react/SKILL.md) | React-specific review (extends code-review with hooks, render perf, state management checks) |
| [`eng-standards`](skills/eng-standards/SKILL.md) | Engineering rigor baselines (presets) + reference standards library |
| [`execute-milestone`](skills/execute-milestone/SKILL.md) | Run one milestone of a `-TASKS.md` with fresh subagents per task, review, ≤2 fix rounds, rulings ledger, ship gate (+ `verify-gate.sh` Stop hook) |
| [`handoff`](skills/handoff/SKILL.md) | Regenerate a project's `-megaprompt.md` paste-to-resume prompt from plan/TASKS/git state |
| [`scout`](skills/scout/SKILL.md) | Match a plan or milestone against the registry of in-house MCP servers, skills and prior-art repos (`registry/inventory.md`), and record USE/PORT/LEARN verdicts in the plan |
| [`plan-feature`](skills/plan-feature/SKILL.md) | Interview → three-file funnel: `-plan.md` (LOCKED decisions + verification gate), `-TASKS.md`, `-megaprompt.md` |
| [`spec-kit`](skills/spec-kit/SKILL.md) | Initialize and drive spec-kit (SDD) projects — specs, plans, tasks, implementation |
| [`toolbelt`](skills/toolbelt/SKILL.md) | Behavioral skill — tells the agent to prefer MCP tools over built-ins (auto-loaded) |
| [`toolbelt-setup`](skills/toolbelt-setup/SKILL.md) | Set up mcp-toolbelt in a project: flake input, mkDevShell, CLAUDE.md, README |
| [`ux-review`](skills/ux-review/SKILL.md) | Review and fix accessibility, layout, and UX in React apps |

## Sub-flakes

spec-kit includes sub-projects that can be used as standalone flake inputs:

| Sub-flake | Path | Description |
|-----------|------|-------------|
| `runner-ts` | `skills/spec-kit/runner-ts/` | TypeScript parallel task runner |
| `runner` | `skills/spec-kit/runner/` | Python parallel task runner |
| `code-review-graph` | `skills/spec-kit/code-review-graph/` | Code knowledge graph for review |

Include them as flake inputs:

```nix
inputs.spec-kit-runner.url = "github:mmmaxwwwell/agent-framework?dir=skills/spec-kit/runner-ts";
```

## License

MIT
