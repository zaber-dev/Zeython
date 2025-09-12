# Modular MVC Architecture Examples

This document provides comprehensive examples of how to use the modular MVC framework.

## Basic Usage Examples

### 1. Web Service Only

**Configuration (.env):**
```env
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
DATABASE_URL=sqlite:///database.db
```

**Run:**
```bash
python config/application.py
```

### 2. Web + Discord Services

**Configuration (.env):**
```env
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
DISCORD_TOKEN=your_discord_token_here
DISCORD_PREFIX=!
DATABASE_URL=sqlite:///database.db
```

**Run:**
```bash
python config/application.py
```

### 3. Discord Service Only

**Configuration (.env):**
```env
DISCORD_TOKEN=your_discord_token_here
DISCORD_PREFIX=!
DATABASE_URL=sqlite:///database.db
```

## Creating Custom Services

### Example: Email Service

```python
# app/Services/email_service.py
import smtplib
from email.mime.text import MIMEText
from typing import Dict, Any
from app.Core.service import ThreadedService

class EmailService(ThreadedService):
    """Email service for sending notifications."""
    
    def __init__(self, name: str = "email", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.smtp_server = None
    
    def is_enabled(self) -> bool:
        """Check if email service is enabled."""
        return bool(
            self.config.get('smtp_host') and 
            self.config.get('smtp_user') and 
            self.config.get('smtp_password')
        )
    
    def _run(self):
        """Initialize SMTP connection."""
        try:
            self.smtp_server = smtplib.SMTP(
                self.config.get('smtp_host'),
                self.config.get('smtp_port', 587)
            )
            self.smtp_server.starttls()
            self.smtp_server.login(
                self.config.get('smtp_user'),
                self.config.get('smtp_password')
            )
            self.logger.info("Email service connected")
            
            # Keep service running
            while self.is_running:
                # Process email queue or wait for shutdown
                import time
                time.sleep(1)
                
        except Exception as e:
            self.logger.error(f"Email service error: {e}")
        finally:
            if self.smtp_server:
                self.smtp_server.quit()
    
    def send_email(self, to: str, subject: str, body: str):
        """Send an email."""
        if not self.smtp_server:
            self.logger.error("SMTP not connected")
            return False
        
        try:
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = self.config.get('smtp_user')
            msg['To'] = to
            
            self.smtp_server.send_message(msg)
            self.logger.info(f"Email sent to {to}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send email: {e}")
            return False
```

**Register the service:**

```python
# config/application.py (add to register_optional_services)
def register_optional_services():
    # ... existing code ...
    
    # Register email service
    try:
        from app.Services.email_service import EmailService
        service_manager.register_service_class(EmailService, "email")
        logger.info("Email service registered")
    except ImportError:
        logger.info("Email service not available")
```

**Configure the service (.env):**
```env
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USER=your-email@gmail.com
EMAIL_SMTP_PASSWORD=your-app-password
EMAIL_ENABLED=true
```

### Example: Task Scheduler Service

```python
# app/Services/scheduler_service.py
import time
import schedule
from typing import Dict, Any
from app.Core.service import ThreadedService

class SchedulerService(ThreadedService):
    """Task scheduler service."""
    
    def is_enabled(self) -> bool:
        return self.config.get('enabled', False)
    
    def _run(self):
        """Run the scheduler."""
        # Schedule tasks
        schedule.every(1).minutes.do(self.minute_task)
        schedule.every().hour.do(self.hourly_task)
        schedule.every().day.at("00:00").do(self.daily_task)
        
        self.logger.info("Scheduler service started")
        
        while self.is_running:
            schedule.run_pending()
            time.sleep(1)
    
    def minute_task(self):
        """Task that runs every minute."""
        self.logger.debug("Running minute task")
    
    def hourly_task(self):
        """Task that runs every hour."""
        self.logger.info("Running hourly task")
    
    def daily_task(self):
        """Task that runs daily."""
        self.logger.info("Running daily task")
```

## Working with the User Model

### Basic Usage

```python
from app.Models.users import Users

# Create a user
user = Users.create(
    name="John Doe",
    email="john@example.com",
    password="secure_password"
)

# Set external service IDs
user.set_external_id('discord', '123456789')
user.set_external_id('github', 'johndoe')

# Set profile data
user.set_profile_data('theme', 'dark')
user.set_profile_data('language', 'en')

# Get external IDs
discord_id = user.get_external_id('discord')
github_username = user.get_external_id('github')

# Get profile data
theme = user.get_profile_data('theme', 'light')  # default to 'light'
```

### Backward Compatibility

```python
# Old Discord-specific code still works
user.discord_id = "123456789"
print(user.discord_id)  # "123456789"

# But the new approach is more flexible
user.set_external_id('discord', "123456789")
user.set_external_id('telegram', "987654321")
```

## Service Communication

### Getting Services

```python
from app.Core.service_manager import service_manager

# Get web service
web_service = service_manager.get_service('web')
if web_service:
    flask_app = web_service.get_flask_app()

# Get Discord service
discord_service = service_manager.get_service('discord')
if discord_service:
    bot = discord_service.get_bot()
```

### Service Status Monitoring

```python
from app.Core.service_manager import service_manager

# Get status of all services
status = service_manager.get_service_status()
print(f"Running services: {status['running_services']}/{status['total_services']}")

# Get status of specific service
web_status = service_manager.get_service_status('web')
print(f"Web service status: {web_status}")
```

## Configuration Management

### Environment Variables

```python
from app.Core.config import config

# Get configuration values
db_url = config.get('database.url')
web_host = config.get('web.host', '127.0.0.1')
app_name = config.get('app.name', 'Zeython')

# Set configuration values
config.set('custom.setting', 'value')

# Check if service is enabled
if config.is_service_enabled('email'):
    print("Email service is enabled")
```

### Configuration Files

```python
from app.Core.config import config

# Load from JSON file
config.load_from_file('config/settings.json')

# Load from YAML file (requires PyYAML)
config.load_from_file('config/settings.yaml')

# Load from Python file
config.load_from_file('config/settings.py')
```

## Testing Services

```python
import unittest
from app.Core.service_manager import ServiceManager
from app.Services.custom_service import CustomService

class TestCustomService(unittest.TestCase):
    
    def setUp(self):
        self.service_manager = ServiceManager()
        self.service_manager.register_service_class(CustomService, "custom")
    
    def test_service_creation(self):
        service = self.service_manager.create_service("custom", {"enabled": True})
        self.assertIsNotNone(service)
        self.assertTrue(service.is_enabled())
    
    def test_service_lifecycle(self):
        service = self.service_manager.create_service("custom", {"enabled": True})
        
        # Start service
        self.assertTrue(self.service_manager.start_service("custom"))
        
        # Check status
        status = service.get_status()
        self.assertTrue(status['is_running'])
        
        # Stop service
        self.assertTrue(self.service_manager.stop_service("custom"))
```

## Docker Examples

### Dockerfile for Custom Services

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONPATH=/app

# Expose ports
EXPOSE 5000

# Run the application
CMD ["python", "config/application.py"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  zeython:
    build: .
    ports:
      - "5000:5000"
    environment:
      - FLASK_HOST=0.0.0.0
      - FLASK_PORT=5000
      - DATABASE_URL=postgresql://user:pass@db:5432/dbname
      - DISCORD_TOKEN=${DISCORD_TOKEN}
    depends_on:
      - db
    volumes:
      - ./logs:/app/logs
  
  db:
    image: postgres:13
    environment:
      - POSTGRES_DB=dbname
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

## Migration from Legacy System

### Old boot.py approach:
```python
# Old way - tightly coupled
if flask_enabled:
    # Flask setup code mixed with application logic
    
if discord_enabled:
    # Discord setup code mixed with application logic
```

### New modular approach:
```python
# New way - modular and clean
service_manager.register_service_class(WebService, "web")
service_manager.register_service_class(DiscordService, "discord")

# Services auto-configure based on environment
service_manager.start_all_enabled_services()
```

The new system provides:
- Better separation of concerns
- Easier testing
- Configurable services
- Cleaner error handling
- Service status monitoring
- Extensible architecture