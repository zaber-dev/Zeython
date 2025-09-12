# Examples

A curated list of common tasks. See also the repository-level `EXAMPLES.md`.

## Start web service only
```python
# .env
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
```

```bash
python config/application.py
```

## Create a custom service
```python
from app.Core.service import ThreadedService

class Worker(ThreadedService):
    def is_enabled(self):
        return True
    def _run(self):
        self.logger.info("Worker running")
```

## Add a route
```python
# routes/web.py
from flask import current_app as app

@app.route('/ping')
def ping():
    return 'pong'
```
