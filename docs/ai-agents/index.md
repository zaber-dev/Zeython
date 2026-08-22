# AI Agents

Zeython ships an MCP ([Model Context Protocol](https://modelcontextprotocol.io)) server so AI coding agents (Claude Code, Cursor, and any other MCP client) can inspect a real, running-shaped Zeython project instead of guessing at its routes, its database schema, or the framework's own API from training-data memory.

> Looking for how to call an LLM *from your own app code* (not an agent operating on the project)? See [AI](https://zeython.zaber.dev/docs/ai/index.md) instead.

## Setup

```bash
pip install zeython[mcp]
```

Point your MCP client at `zeython mcp`, run from your project directory. For Claude Code, add it as a project-scoped server:

```bash
claude mcp add zeython -- zeython mcp
```

Or add directly to your client's MCP config (the shape varies by client, but the command is always the same):

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

| Tool                            | What it does                                                                                                                          |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `list_routes(project_root=".")` | Every registered HTTP route: path, methods, name.                                                                                     |
| `list_models(project_root=".")` | Every `Model` subclass under `app/Models/`: table, columns, relationships.                                                            |
| `app_info(project_root=".")`    | App name, environment, debug flag, Zeython version, registered service providers.                                                     |
| `search_docs(query)`            | Searches the documentation bundled with the **exact installed Zeython version** -- not a possibly-stale memory of some other version. |

All four read the real project, not the source text: `list_routes` reflects routes added via `.resource()` or mounted by a service provider, not just what a `@app.get(...)` grep would find; `list_models` reflects SQLAlchemy's actual mapped columns, including ones inherited from `Model` itself (`id`, `created_at`, `is_deleted`, ...).

## Why this exists

An agent working in an unfamiliar Zeython project otherwise has two bad options: grep source files and hope it read every route/model definition correctly, or trust its training data about "how Zeython works" — which, for a framework this young, is either absent or stale. `list_routes` / `list_models` / `app_info` answer "what does this project actually have" directly; `search_docs` answers "how does Zeython actually work" from docs that ship with the version you're using, not a guess.

## Guidelines for agents: `AGENTS.md`

The tools above answer factual questions about a specific project. For framework *conventions* — the difference between `throttle()` and `require_auth()`, why `to_dict(include=...)` exists, where jobs live — see [AGENTS.md](https://github.com/zaber-dev/Zeython/blob/main/AGENTS.md) at the repository root. Most MCP-capable coding agents read a project's own `AGENTS.md` automatically; a generated Zeython project doesn't currently ship one of its own (the framework's `AGENTS.md` covers building *with* Zeython, not a specific app) -- copy the relevant sections into your project's own `AGENTS.md` if your agent doesn't already have access to the framework repository.

## Feeding the docs site itself to an LLM

The MCP server above is for an agent *working inside* a Zeython project. For pasting documentation into an LLM chat, or letting a web-browsing agent fetch it directly, the [docs site](https://zeython.zaber.dev/docs/) is itself structured for that:

- Every page has a **"Copy page as Markdown"** button next to the "Edit this page" pencil icon — copies that page's content as clean Markdown (no nav chrome, no HTML), ready to paste into a chat.
- The same content is served directly at `<page-url>index.md` for any page — e.g. `/docs/csrf/index.md` — no button needed if you're fetching it programmatically.
- [`/docs/llms.txt`](https://zeython.zaber.dev/docs/llms.txt) lists every page as a Markdown link, grouped by section — the emerging [llms.txt](https://llmstxt.org/) convention for "here's what this site has, and where to find it" in a shape an LLM can consume without crawling HTML.
- [`/docs/llms-full.txt`](https://zeython.zaber.dev/docs/llms-full.txt) concatenates every page's Markdown into one file, for pasting the whole framework's documentation into a single context window at once.

## Scope

This is deliberately read-only introspection, not a way to run arbitrary code or modify a project through the protocol -- an agent with shell access can already run `zeython make`, `zeython db migrate`, or `pytest` directly, and doing that through an MCP tool call instead wouldn't add anything. What these tools add is information an agent can't get any other way: the actual state of a live project's routing table and schema.
