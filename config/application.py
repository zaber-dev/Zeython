"""
Modular application bootstrap system.

This file provides a clean, modular way to start the Zeython application
with configurable services. Services are loaded dynamically based on
configuration, making the system truly modular and extensible.

To add new services:
1. Create a service class that inherits from ServiceInterface
2. Register it with the service manager
3. Configure it in the environment or config file

Services are automatically enabled/disabled based on configuration.
"""

import os
import sys
import logging
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import core components
from app.Core.config import config
from app.Core.service_manager import service_manager
from app.Services.web_service import WebService

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.get('app.log_level', 'INFO')),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("application")


def setup_database():
    """Initialize database tables."""
    try:
        from database.db import engine, Base
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to setup database: {e}")
        raise


def register_core_services():
    """Register core services with the service manager."""
    # Register web service
    service_manager.register_service_class(WebService, "web")
    logger.info("Core services registered")


def register_optional_services():
    """Register optional services if available."""
    # Try to register Discord service if dependencies are available
    try:
        from app.Services.discord_service import DiscordService
        service_manager.register_service_class(DiscordService, "discord")
        logger.info("Discord service registered")
    except ImportError:
        logger.info("Discord service not available (dependencies not installed)")
    except Exception as e:
        logger.warning(f"Failed to register Discord service: {e}")


def create_configured_services():
    """Create service instances based on configuration."""
    created_services = []
    
    # Create web service if enabled
    if config.is_service_enabled('web'):
        web_config = config.get_service_config('web')
        service = service_manager.create_service('web', web_config)
        if service:
            created_services.append('web')
            logger.info("Web service created")
    
    # Create Discord service if enabled and available
    if config.is_service_enabled('discord') and 'discord' in service_manager.list_available_services():
        discord_config = config.get_service_config('discord')
        service = service_manager.create_service('discord', discord_config)
        if service:
            created_services.append('discord')
            logger.info("Discord service created")
    
    return created_services


def start_application():
    """Start the application with all configured services."""
    logger.info(f"Starting {config.get('app.name', 'Zeython')}")
    
    try:
        # Setup database
        setup_database()
        
        # Register services
        register_core_services()
        register_optional_services()
        
        # Create and configure services
        created_services = create_configured_services()
        
        if not created_services:
            logger.warning("No services were created. Check your configuration.")
            return
        
        # Start all enabled services
        logger.info("Starting enabled services...")
        success = service_manager.start_all_enabled_services()
        
        if success:
            logger.info("All services started successfully")
            
            # Print status
            status = service_manager.get_service_status()
            logger.info(f"Running services: {status['running_services']}/{status['total_services']}")
            
            # Wait for services to complete
            service_manager.wait_for_services()
        else:
            logger.error("Some services failed to start")
            
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.error(f"Application startup failed: {e}")
        raise
    finally:
        # Clean shutdown
        logger.info("Shutting down services...")
        service_manager.stop_all_services()
        logger.info("Application shutdown complete")


def main():
    """Main entry point."""
    start_application()


if __name__ == "__main__":
    main()