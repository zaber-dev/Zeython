# Architecture

Zeython follows a modular MVC architecture with a service manager that runs services in parallel.

## High-level
- Core (interfaces, config, service manager)
- Services (web/Flask, optional Discord, your plugins)
- Models (business entities, validation, caching, audit)
- Controllers (web and service-specific logic)
- Routes (web and API Blueprints)
- Resources (templates and static assets)

## Service manager
- Register service classes
- Create instances from configuration
- Start/stop services safely
- Status/health reporting

## Threads and lifecycle
- Services extend ThreadedService and run in their own thread
- is_enabled() gates startup
- start/stop/join managed via the manager

See EXAMPLES.md for examples and config/application.py for bootstrapping.
