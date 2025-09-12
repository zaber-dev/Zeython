# Zeython — Modular Flask + Discord Bot Starter

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](requirements.txt)

Zeython is an MVC-structured Python starter built on **Flask**, with an
**optional Discord bot** (via [disnake](https://github.com/DisnakeDev/disnake))
that can be enabled independently of the web server. A small service
manager coordinates whichever of the two you turn on through environment
variables, so the web app and the bot don't depend on one another.

Repository: https://github.com/zaber-dev/Zeython

## Documentation

- Full docs: [docs/index.md](docs/index.md)
- Developer guide: [docs/developer-setup.md](docs/developer-setup.md)

## Project Structure

```bash
.
├── app
│   ├── Actions             # Utility functions (pagination, embeds, webhook handling, etc.)
│   ├── Commands            # Discord command handling (optional service)
│   │   ├── Context         # Traditional Discord commands
│   │   └── Slash           # Slash commands for Discord
│   ├── Controllers         # Controller logic for web and services
│   │   ├── Flask           # Controllers specific to the Flask web app
│   │   └── Discord         # Controllers for the Discord bot (optional)
│   ├── Core                # Service interface, service manager, config
│   │   ├── service.py      # Service interface and base classes
│   │   ├── service_manager.py  # Service lifecycle management
│   │   └── config.py       # Configuration management
│   ├── Models              # SQLAlchemy models for the application
│   ├── Services            # Service implementations
│   │   ├── web_service.py  # Flask web service
│   │   └── discord_service.py  # Discord bot service (optional)
│   └── Views               # Flask templates
├── config
│   ├── boot.py             # Legacy entry point (deprecated)
│   └── application.py      # Modular application bootstrap (recommended)
├── database
│   └── db.py               # SQLAlchemy engine/session setup
├── resources                # Static and template files for Flask
│   ├── css                 # CSS files
│   ├── js                  # JavaScript files
│   └── views               # HTML templates
├── routes
│   ├── api.py               # Routes for API endpoints
│   └── web.py                # Routes for web pages
├── storage                   # User file storage (uploads, etc.)
├── vendor                    # Placeholder for third-party integrations
├── requirements.txt          # Python dependencies (flask, disnake, sqlalchemy, python-dotenv)
├── Dockerfile                # Docker containerization file
└── .env_example               # Environment configuration template
```

## What's actually implemented

- **Two independent services** — a Flask web app (`app/Services/web_service.py`)
  and an optional Discord bot (`app/Services/discord_service.py`), each
  started or skipped by `app/Core/service_manager.py` depending on which
  environment variables are set. A couple of real routes exist
  (`routes/web.py`, `routes/api.py`) plus example Discord ping/greet
  commands under `app/Commands/`.
- **An enhanced SQLAlchemy base model** (`app/Models/base_model.py`) —
  active-record-style `create`/`get`/`update`/`delete`, field-level
  validators, a soft-delete mixin, an audit-fields mixin, a simple
  in-memory cache, and dict/JSON (de)serialization.
- **Additional data models** for users/sessions, balances, file uploads,
  and vendor/webhook/error-log records (`app/Models/*.py`) — schema and
  helper methods built on the base model above. These are not wired up to
  a working end-to-end flow yet (no OAuth login route, no webhook
  receiver endpoint, etc. exist in `routes/`).
- **Docker support** — a `Dockerfile` that installs `requirements.txt` and
  runs `config/application.py`.

See [MVC_ENHANCEMENTS.md](MVC_ENHANCEMENTS.md) for the model layer in more
detail, and [EXAMPLES.md](EXAMPLES.md) for usage snippets.

## Getting Started

1. **Clone the repository**:
   ```bash
   git clone https://github.com/zaber-dev/Zeython.git
   cd Zeython
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure services** — copy `.env_example` to `.env` and fill in
   whichever service(s) you want to run:
   ```bash
   cp .env_example .env
   ```

   **Web only**:
   ```env
   FLASK_HOST=127.0.0.1
   FLASK_PORT=5000
   DATABASE_URL=sqlite:///database.db
   ```

   **Web + Discord**:
   ```env
   FLASK_HOST=127.0.0.1
   FLASK_PORT=5000
   DISCORD_TOKEN=your_discord_token_here
   DISCORD_PREFIX=!
   DATABASE_URL=sqlite:///database.db
   ```

4. **Run it**:
   ```bash
   # Modular system (recommended)
   python config/application.py

   # Legacy entry point (deprecated)
   python config/boot.py
   ```

### Docker

```bash
docker build -t zeython .
docker run -e FLASK_HOST=0.0.0.0 -e FLASK_PORT=5000 -p 5000:5000 zeython
```

### Adding a new service

```python
from app.Core.service import ThreadedService

class MyService(ThreadedService):
    def is_enabled(self) -> bool:
        return self.config.get('enabled', False)

    def _run(self):
        # Your service logic here
        pass
```

```python
from app.Core.service_manager import service_manager
service_manager.register_service_class(MyService, "my_service")
```

## Collaboration

Contributions are welcome — fork the repository and open a pull request.
Check the **issues** section for current needs, or suggest your own.

## License

This project is licensed under the GNU General Public License v3.0.
