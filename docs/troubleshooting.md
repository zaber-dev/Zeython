# Troubleshooting

## Common issues

### 1) `mkdocs serve` fails
- Ensure `mkdocs` and `mkdocs-material` are installed
- Check `mkdocs.yml` nav paths and docs_dir

### 2) Flask not starting
- Verify `FLASK_HOST` is set
- Check port availability; change `FLASK_PORT`

### 3) Database errors
- Validate `DATABASE_URL`
- Confirm tables created during startup; check logs

### 4) Discord service missing
- Ensure `DISCORD_TOKEN` is set
- Confirm optional dependency is installed if required
