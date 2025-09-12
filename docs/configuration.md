# Configuration

Zeython configuration is environment-driven with safe defaults.

## App settings
- APP_NAME (default: Zeython)
- APP_LOG_LEVEL (default: INFO)

## Web service
- FLASK_HOST (enable when set)
- FLASK_PORT (default: 5000)
- FLASK_DEBUG (default: false)

## Discord service (optional)
- DISCORD_TOKEN (enables Discord service)
- DISCORD_PREFIX (default: !)

## Database
- DATABASE_URL (e.g., sqlite:///database.db)

## Service-specific configs
Use config.get_service_config(name) to retrieve service configs.

See `app/Core/config.py` for resolution order and helpers.
