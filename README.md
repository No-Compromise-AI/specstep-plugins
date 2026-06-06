# SpecStep plugins

Public distribution point for [SpecStep](https://specstep.com)'s Claude Code plugins.

This repository is a **Claude Code plugin marketplace**. Add it, then install a plugin:

```bash
claude plugin marketplace add No-Compromise-AI/specstep-plugins
claude plugin install specstep-session@specstep
```

## Available plugins

| Plugin | What it does |
|---|---|
| [`specstep-session`](./plugins/specstep-session) | Session-start / session-end protocol skills for driving SpecStep's session-state MCP tools (build sessions, decision log, backlog, projects, cross-aggregate) with discipline, plus an automatic per-session token-usage reporter that feeds each project's "cost to build" rollup. |

See the plugin's own [README](./plugins/specstep-session/README.md) for prerequisites, install options, and configuration.

## About this repo

This is a **read-only mirror**. The canonical source lives in SpecStep's main repository;
the `.claude-plugin/` manifest and everything under `plugins/` here are synced from there
by `scripts/sync-public-plugins.sh`. Please don't open pull requests against this repo —
send feedback through SpecStep instead.
