# Tutorial: Build TaskFlow

[Getting Started](getting-started.md) gets you from zero to a running app
in five minutes, but five minutes isn't enough to actually learn a
framework — you need to build something. This tutorial builds **TaskFlow**,
a small multi-project task tracker, from an empty scaffold to a tested,
authenticated API, introducing one concept at a time the way
[Django's official tutorial](https://docs.djangoproject.com/en/stable/intro/tutorial01/)
or [Laravel Bootcamp](https://bootcamp.laravel.com/) do.

By the end you'll have written two real models with a relationship
between them, a full set of CRUD routes, an authorization rule that only
lets a task's owner delete it, and a test suite that actually exercises
all of it — and you'll understand *why* each piece works the way it does,
not just that it does.

## What you'll build

- **Projects** — a name and a owner.
- **Tasks** — belong to a project, have a title and a done flag.
- Anyone can list and view projects/tasks; only a logged-in user can
  create a task, and only the task's own creator can delete it.
- A test suite covering the CRUD routes and the authorization rule.

## Prerequisites

Python 3.11+, and fifteen minutes. No prior Zeython knowledge assumed —
if you haven't yet, skim [Getting Started](getting-started.md) first for
the one-paragraph mental model of what `zeython new` gives you; this
tutorial re-explains everything as it comes up either way.

## Parts

1. [Setup](tutorial-1-setup.md) — scaffold the project, look around, run it,
   log in with the built-in User model.
2. [Models](tutorial-2-models.md) — define `Project` and `Task`, add
   validation, run your first migration.
3. [Controllers & Routes](tutorial-3-controllers.md) — a full CRUD API for
   tasks, tested with real HTTP requests as you go.
4. [Relationships](tutorial-4-relationships.md) — connect `Task` to
   `Project`, load them together safely, avoid the #1 async ORM mistake.
5. [Authentication & Authorization](tutorial-5-auth.md) — require login to
   create a task; only its owner can delete it.
6. [Testing](tutorial-6-testing.md) — a real pytest suite for everything
   you just built, including the authorization rule.

Each part leaves you with a working app — run `zeython serve` and try
what you just built before moving on. If something doesn't match what
this tutorial says, that's worth stopping on: either you hit a real bug
(open an issue, or see [SECURITY.md](https://github.com/zaber-dev/Zeython/blob/main/SECURITY.md)
if it's security-relevant) or a step got skipped — every command here is
meant to be copy-pasteable and correct against the current release.

Start with [Part 1: Setup](tutorial-1-setup.md).
