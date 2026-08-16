# AI Agents

Zeython ships an MCP ([Model Context Protocol](https://modelcontextprotocol.io))
server so AI coding agents (Claude Code, Cursor, and any other MCP client)
can inspect a real, running-shaped Zeython project instead of guessing at
its routes, its database schema, or the framework's own API from
training-data memory.

> Looking for how to call an LLM *from your own app code* (not an agent
> operating on the project)? See [AI](ai.md) instead.

## Setup

```bash
pip install zeython[mcp]
```

Point your MCP client at `zeython mcp`, run from your project directory.
For Claude Code, add it as a project-scoped server:

```bash
claude mcp add zeython -- zeython mcp
```

Or add directly to your client's MCP config (the shape varies by client,
but the command is always the same):

```json
{
  "mcpServers": {
    "zeython": {
      "command": "zeython",
      "args": ["mcp"]
    }
  }
}
```

## Tools

| Tool | What it does |
|---|---|
| `list_routes(project_root=".")` | Every registered HTTP route: path, methods, name. |
| `list_models(project_root=".")` | Every `Model` subclass under `app/Models/`: table, columns, relationships. |
| `app_info(project_root=".")` | App name, environment, debug flag, Zeython version, registered service providers. |
| `search_docs(query)` | Searches the documentation bundled with the **exact installed Zeython version** -- not a possibly-stale memory of some other version. |

All four read the real project, not the source text: `list_routes` reflects
routes added via `.resource()` or mounted by a service provider, not just
what a `@app.get(...)` grep would find; `list_models` reflects SQLAlchemy's
actual mapped columns, including ones inherited from `Model` itself
(`id`, `created_at`, `is_deleted`, ...).

## Why this exists

An agent working in an unfamiliar Zeython project otherwise has two bad
options: grep source files and hope it read every route/model definition
correctly, or trust its training data about "how Zeython works" — which,
for a framework this young, is either absent or stale. `list_routes` /
`list_models` / `app_info` answer "what does this project actually have"
directly; `search_docs` answers "how does Zeython actually work" from docs
that ship with the version you're using, not a guess.

## Guidelines for agents: `AGENTS.md`

The tools above answer factual questions about a specific project. For
framework *conventions* — the difference between `throttle()` and
`require_auth()`, why `to_dict(include=...)` exists, where jobs live — see
[AGENTS.md](https://github.com/zaber-dev/Zeython/blob/main/AGENTS.md) at
the repository root. Most MCP-capable coding agents read a project's own
`AGENTS.md` automatically; a generated Zeython project doesn't currently
ship one of its own (the framework's `AGENTS.md` covers building *with*
Zeython, not a specific app) -- copy the relevant sections into your
project's own `AGENTS.md` if your agent doesn't already have access to the
framework repository.

## Scope

This is deliberately read-only introspection, not a way to run arbitrary
code or modify a project through the protocol -- an agent with shell access
can already run `zeython make`, `zeython db migrate`, or `pytest` directly,
and doing that through an MCP tool call instead wouldn't add anything. What
these tools add is information an agent can't get any other way: the
actual state of a live project's routing table and schema.
