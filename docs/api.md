# API and Routes

- Web routes are defined in `routes/web.py`
- API blueprint is defined in `routes/api.py` and registered by the web service

## Adding routes
```python
# routes/web.py
from flask import current_app as app

@app.route('/hello')
def hello():
    return 'Hello, Zeython!'
```

## API blueprint
```python
# routes/api.py
from flask import Blueprint

api = Blueprint('api', __name__)

@api.route('/status')
def status():
    return {'ok': True}
```
