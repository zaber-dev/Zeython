# Debugging

Tips to diagnose issues in Zeython.

## Flask debugging
- Set `FLASK_DEBUG=true` in `.env`
- Check the web service logs on startup

## Service status
```python
from app.Core.service_manager import service_manager
service_manager.get_service_status()
```

## Database issues
- Verify `DATABASE_URL`
- Use SQLite first, then swap to Postgres/MySQL

## Logging
- Adjust `APP_LOG_LEVEL` (e.g., DEBUG)
- Add contextual info to logs (service name, request id)
