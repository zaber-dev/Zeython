# Migration Guide

Moving from the legacy MVC-Python or the legacy boot.py style to Zeython’s modular system.

## From boot.py to application.py
- Old: direct setup in `config/boot.py`
- New: register services and let `config/application.py` orchestrate

### Steps
1. Ensure env vars are set (FLASK_HOST, DATABASE_URL)
2. Register optional services (e.g., Discord) if needed
3. Start via `python config/application.py`

## Renaming and branding
- Old name: MVC-Python → New name: Zeython
- Update clone URLs and Docker tags

## Backward compatibility
- Existing Discord code continues to work via the Discord service
- Models enhanced; legacy usage patterns still supported
