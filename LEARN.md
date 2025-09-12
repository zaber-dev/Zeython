# Learn Zeython

Welcome to Zeython! This guide walks you from zero to productive with the modular MVC framework.

Zeython is created by Md Mahedi Zaman Zaber and is the improved, advanced version of MVC-Python.

- Repository: https://github.com/zaber-dev/Zeython
- License: GPL-3.0-or-later

## Who is this for?

- Python developers who want a clean MVC foundation with services (web, Discord, and more)
- Teams that value configuration-driven, modular architecture
- Learners exploring service-oriented application design with Flask

## Quick Start

1) Clone and install

```bash
git clone https://github.com/zaber-dev/Zeython.git
cd Zeython
pip install -r requirements.txt
```

2) Configure environment

Create a `.env` in the project root (see `.env_example` if present):

```env
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
DATABASE_URL=sqlite:///database.db
```

3) Run

```bash
python config/application.py
```

Open http://127.0.0.1:5000/

## What you’ll build/learn

- MVC structure with clear separation of concerns
- Service management: register, enable, run in parallel
- Database layer and models with enhanced features
- Web routes and APIs, plus optional Discord integration

## Concepts map

- Architecture overview: docs/architecture.md
- Getting started: docs/getting-started.md
- Configuration: docs/configuration.md
- Models and database: docs/models.md, docs/database.md
- Services: docs/services/web.md, docs/services/discord.md
- APIs and routes: docs/api.md
- Advanced topics: docs/authentication.md, docs/file-management.md, docs/vendor-integrations.md,
  docs/error-monitoring.md, docs/deployment.md, docs/testing.md, docs/faq.md
  
    For developers:
    - docs/developer-setup.md
    - docs/coding-standards.md
    - docs/service-development.md
    - docs/debugging.md

## Recommended path

1. Read docs/getting-started.md
2. Skim docs/architecture.md
3. Configure web service and run a local server
4. Explore docs/models.md and docs/database.md, then add a simple model
5. Add/modify a route in routes/web.py and a controller
6. Optional: enable Discord service and add a command
7. Deploy with Docker (docs/deployment.md)

## Examples

See EXAMPLES.md for end-to-end snippets, including creating custom services.

## Troubleshooting

- Port already in use: change FLASK_PORT or stop the conflicting process.
- Flask not installed: ensure `pip install -r requirements.txt` succeeded.
- Database errors: verify DATABASE_URL and that `database/db.py` initializes correctly.

## Next steps

- Explore tests in `tests/` and add your own.
- Contribute improvements—see CONTRIBUTING.md.

Happy building with Zeython!
