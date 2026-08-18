# Contributing to Zeython

Thanks for considering a contribution. Zeython is a young project moving
fast, so the most valuable contributions right now are: bug reports against
real usage, missing pieces in the core framework (`src/zeython/`), and
documentation gaps.

## Reporting bugs

Open an issue with:
- A clear description of the bug and what you expected instead.
- A minimal reproduction (a few lines against `zeython`, or `zeython new` + a diff).
- The Zeython version (`python -c "import zeython; print(zeython.__version__)"`) and Python version.

**Found a security vulnerability instead?** Don't open a public issue for
it — see `SECURITY.md` for how to report it privately.

## Proposing features

Open an issue describing the problem before the implementation. Framework-level
additions (new core modules, CLI commands, breaking API changes) should be
discussed there first — application-level features belong in your own app, not
the framework.

## Development setup

```bash
git clone https://github.com/zaber-dev/Zeython.git
cd Zeython
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Repository layout:

```
src/zeython/            # the framework itself
  application.py         # Application (ASGI app, boot lifecycle)
  container.py            # dependency injection container
  routing.py               # Router, Controller, resource()
  config.py                 # .env-backed configuration
  providers.py               # ServiceProvider, DatabaseServiceProvider, RouteServiceProvider
  db/                          # async SQLAlchemy session + Model base class
  cli/                          # the `zeython` command (new/serve/make/db)
  cli/templates/starter/         # files copied by `zeython new`
tests/                    # the framework's own test suite
docs/                     # mkdocs source
```

## Making changes

- Keep the core small and typed. Every public function/method should have type
  hints; `mypy src/zeython` must pass clean.
- Add tests for anything you change in `src/zeython/` — `pytest` must pass.
- Run `ruff check src tests` before opening a PR; CI enforces it.
- If you change `src/zeython/cli/templates/starter/`, regenerate a project with
  `zeython new` and confirm it boots (`zeython serve`) and its own `pytest`
  passes — the CI `scaffold-smoke-test` job does this automatically, but it's
  much faster to catch locally.
- Commit messages: short, imperative, descriptive (`Fix session leak in
  DatabaseSessionMiddleware`, `Add zeython make:provider command`).

## Pull requests

1. Fork the repository and create a branch off `main`.
2. Make your change with tests.
3. `pytest && ruff check src tests && mypy src/zeython`
4. Open a PR describing the change and, for behavior changes, why it's needed.

## License

By contributing, you agree your contributions are licensed under the project's
GNU General Public License v3.0.

## Questions

Open an issue, or reach out to zaber@zealtyro.com.
