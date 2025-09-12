# Performance Guide

## Service performance
- Use `is_enabled()` to prevent unnecessary startup
- Keep main loops efficient; sleep appropriately
- Offload heavy tasks to queues/workers

## Web performance
- Cache common queries (model_cache)
- Avoid N+1 queries in controllers
- Use pagination for large datasets

## Monitoring
- Leverage PerformanceMetric and ActivityLog models
- Track response times and resource usage
