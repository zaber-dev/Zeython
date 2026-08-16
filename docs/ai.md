# AI

`zeython.ai` gives your app's own code a way to call an LLM — a completion
client bound in the container, the same shape as `Mailer`, `Storage`, or
`Cache`.

This is a different thing from [AI Agents](ai-agents.md) (`zeython.mcp`):
that module lets an AI coding agent introspect and operate on a Zeython
*project*. This module lets a Zeython *app* call an LLM as part of its own
logic — summarizing a support ticket, drafting a reply, classifying input.

## Setup

```bash
pip install zeython[ai]
```

Register the provider where you need it — it's opt-in, not registered by
default:

```python
from zeython import AIServiceProvider

app.register(AIServiceProvider)
```

## Usage

```python
from zeython import AI

async def summarize(self, request):
    ai: AI = request.app.state.container.make(AI)
    data = await request.json()

    response = await ai.complete(
        data["text"],
        system="Summarize the following text in one sentence.",
    )
    return JSONResponse({"summary": response.text})
```

`complete()` returns an `AIResponse` with `.text` and `.model`.

## Configuration

```env
AI_PROVIDER=echo          # default -- no network, no credentials required
# AI_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-ant-...
# AI_MODEL=claude-sonnet-5
```

`AI_PROVIDER` defaults to `echo` — the same role `LogMailer` and
`InMemoryQueue` play for their subsystems: a fresh `zeython new` project
(and its tests) work immediately with zero external credentials.
`EchoAI.complete()` returns the prompt back verbatim, prefixed with
`[echo]`, so you can wire the plumbing (routes, request handling, response
shape) before you have an API key.

Switch to `AI_PROVIDER=anthropic` once you do. `AIServiceProvider` raises a
clear `RuntimeError` at registration time (not on the first request) if
`ANTHROPIC_API_KEY` is missing — a misconfigured AI provider should fail
loudly at boot, not silently on whichever request happens to hit it first.

## Other providers

There's no plugin registry — implement `AI` yourself and bind it in place
of the default, the same pattern as `RateLimiter`, `Cache`, and `Storage`:

```python
from zeython import AI, AIResponse

class MyOpenAI(AI):
    async def complete(self, prompt, *, system=None, max_tokens=1024):
        ...
        return AIResponse(text=..., model=...)

app.container.singleton(AI, lambda: MyOpenAI())
```

## Scope

`complete()` is deliberately the entire interface — no streaming, no tool
use, no conversation/message history management. Those are real needs for
some apps and belong in application code (or a dedicated package) once you
need them, not in the framework's core: the value here is a consistent,
swappable seam for the common "send a prompt, get text back" case, not a
full LLM orchestration layer.
