# Configuration Reference

Comprehensive reference of environment variables and config keys.

## App
- APP_NAME: Default app display name (default: Zeython)
- APP_LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR)

## Web Service
- FLASK_HOST: Enables the web service when set (e.g., 0.0.0.0)
- FLASK_PORT: Port (default: 5000)
- FLASK_DEBUG: true/false (default: false)

## Discord Service
- DISCORD_TOKEN: Enables the Discord service
- DISCORD_PREFIX: Command prefix (default: !)

## Database
- DATABASE_URL: SQLAlchemy connection string (e.g., sqlite:///database.db)

## Custom Services
- YOURSERVICE_ENABLED: true/false
- YOURSERVICE_...: other keys as needed

See `app/Core/config.py` for defaults and helpers (get, set, is_service_enabled, get_service_config).
