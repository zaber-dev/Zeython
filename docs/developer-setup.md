# Developer Setup

This guide helps contributors get a productive dev environment quickly.

## Prerequisites
- Python 3.9+
- Git
- Optional: Docker, Make (or Windows equivalents)

## Clone and install
```bash
git clone https://github.com/zaber-dev/Zeython.git
cd Zeython
python -m venv .venv
. .venv/Scripts/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Environment variables
Create `.env` (copy from `.env_example` if available):
```env
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
DATABASE_URL=sqlite:///database.db
```

## Run app (modular)
```bash
python config/application.py
```

## Run tests (if using pytest)
```bash
pytest -q
```

## Linting and formatting
- Recommended: ruff/flake8 and black (can be added later)
- Configure your editor to format on save

## Local docs preview
```bash
mkdocs serve
```
