# Tutorial: Build TaskFlow

[Getting Started](https://zeython.zaber.dev/docs/getting-started/index.md) gets you from zero to a running app in five minutes, but five minutes isn't enough to actually learn a framework — you need to build something. This tutorial builds **TaskFlow**, a small multi-project task tracker, from an empty scaffold to a tested, authenticated API, introducing one concept at a time the way [Django's official tutorial](https://docs.djangoproject.com/en/stable/intro/tutorial01/) or [Laravel Bootcamp](https://bootcamp.laravel.com/) do.

By the end you'll have written two real models with a relationship between them, a full set of CRUD routes, an authorization rule that only lets a task's owner delete it, and a test suite that actually exercises all of it — and you'll understand *why* each piece works the way it does, not just that it does.

## What you'll build

- **Projects** — a name and a owner.
- **Tasks** — belong to a project, have a title and a done flag.
- Anyone can list and view projects/tasks; only a logged-in user can create a task, and only the task's own creator can delete it.
- A test suite covering the CRUD routes and the authorization rule.

## Prerequisites

Python 3.11+, and fifteen minutes. No prior Zeython knowledge assumed — if you haven't yet, skim [Getting Started](https://zeython.zaber.dev/docs/getting-started/index.md) first for the one-paragraph mental model of what `zeython new` gives you; this tutorial re-explains everything as it comes up either way.

## Parts

1. [Setup](https://zeython.zaber.dev/docs/tutorial-1-setup/index.md) — scaffold the project, look around, run it, log in with the built-in User model.
1. [Models](https://zeython.zaber.dev/docs/tutorial-2-models/index.md) — define `Project` and `Task`, add validation, run your first migration.
1. [Controllers & Routes](https://zeython.zaber.dev/docs/tutorial-3-controllers/index.md) — a full CRUD API for tasks, tested with real HTTP requests as you go.
1. [Relationships](https://zeython.zaber.dev/docs/tutorial-4-relationships/index.md) — connect `Task` to `Project`, load them together safely, avoid the #1 async ORM mistake.
1. [Authentication & Authorization](https://zeython.zaber.dev/docs/tutorial-5-auth/index.md) — require login to create a task; only its owner can delete it.
1. [Testing](https://zeython.zaber.dev/docs/tutorial-6-testing/index.md) — a real pytest suite for everything you just built, including the authorization rule.

Each part leaves you with a working app — run `zeython serve` and try what you just built before moving on. If something doesn't match what this tutorial says, that's worth stopping on: either you hit a real bug (open an issue, or see [SECURITY.md](https://github.com/zaber-dev/Zeython/blob/main/SECURITY.md) if it's security-relevant) or a step got skipped — every command here is meant to be copy-pasteable and correct against the current release.

Start with [Part 1: Setup](https://zeython.zaber.dev/docs/tutorial-1-setup/index.md).
