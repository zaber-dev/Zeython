# Web Service

Flask-based service that serves routes and API blueprints.

## Enable
- Set FLASK_HOST (e.g., 0.0.0.0)
- Optional: FLASK_PORT, FLASK_DEBUG

## Access Flask app
```python
from app.Core.service_manager import service_manager
web = service_manager.get_service('web')
app = web.get_flask_app() if web else None
```
