# Deployment

## Docker
```bash
docker build -t zeython .
docker run -e FLASK_HOST=0.0.0.0 -e FLASK_PORT=5000 -p 5000:5000 zeython
```

## Environment
- Ensure .env is configured for your environment
- Use production-ready DB (PostgreSQL/MySQL) in DATABASE_URL
