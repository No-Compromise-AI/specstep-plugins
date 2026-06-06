# SpecStep plugins

This directory is a [Claude Code plugin marketplace](https://docs.claude.com/en/docs/claude-code/plugins). The marketplace manifest lives at [`../.claude-plugin/marketplace.json`](../.claude-plugin/marketplace.json) (repo root), and each plugin is a subdirectory here.

## Add the marketplace

```bash
claude plugin marketplace add No-Compromise-AI/specstep-plugins
```

(Or point it at a local checkout: `claude plugin marketplace add /path/to/specstep-plugins`.)

## Available plugins

| Plugin | What it does |
|---|---|
| [`specstep-session`](./specstep-session) | Session-start / session-end protocol skills for driving SpecStep's session-state MCP tools (build sessions, decision log, backlog, projects, cross-aggregate) with discipline, plus an automatic per-session token-usage reporter that feeds each project's "cost to build" rollup. |

```bash
claude plugin install specstep-session@specstep
```

See each plugin's `README.md` for prerequisites, install options, and configuration.
