# Service Development

Build your own services that run alongside web/Discord.

## Create a service
```python
from typing import Dict, Any
from app.Core.service import ThreadedService

class EmailService(ThreadedService):
    def __init__(self, name: str = "email", config: Dict[str, Any] = None):
        super().__init__(name, config)

    def is_enabled(self) -> bool:
        return self.config.get('enabled', False)

    def _run(self):
        self.logger.info("Email service started")
        while self.is_running:
            # Do work, sleep, or wait on a queue
            import time
            time.sleep(1)
```

## Register the service
```python
from app.Core.service_manager import service_manager
from app.Services.email_service import EmailService

service_manager.register_service_class(EmailService, "email")
```

## Configure
```env
EMAIL_ENABLED=true
EMAIL_SMTP_HOST=smtp.example.com
```

## Start
```python
service_manager.start_all_enabled_services()
```

## Tips
- Keep I/O blocking minimal inside loops
- Guard long-running tasks with `self.is_running`
- Use `get_status()` to expose service health
