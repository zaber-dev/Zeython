# Coding Standards

Consistent, readable code helps everyone contribute effectively.

## General
- Follow PEP 8 style
- Prefer type hints throughout
- Small, focused functions
- Descriptive names; avoid abbreviations

## Project conventions
- Services extend `ThreadedService`
- Use `service_manager` to register and manage services
- Keep routes thin; place logic in controllers/services
- Models use enhanced base model features

## Errors and logging
- Raise specific exceptions from `app.Models.error_handling`
- Log using module-level loggers

## Tests
- Put tests under `tests/`
- Cover happy paths and 1-2 edge cases
