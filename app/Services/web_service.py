"""
Web Service implementation using Flask.
Provides HTTP server capabilities for the Zeython framework.
"""

import os
import sys
from typing import Dict, Any
from flask import Flask
from app.Core.service import ThreadedService


class WebService(ThreadedService):
    """
    Flask-based web service for handling HTTP requests.
    
    Provides a modular web server that can be enabled/disabled
    through configuration and runs independently of other services.
    """
    
    def __init__(self, name: str = "web", config: Dict[str, Any] = None):
        """
        Initialize the web service.
        
        Args:
            name (str): Service name
            config (Dict[str, Any]): Service configuration
        """
        super().__init__(name, config)
        self.app = None
        self._setup_flask_app()
    
    def _setup_flask_app(self):
        """Set up the Flask application."""
        try:
            # Create Flask app with template folder
            template_folder = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..', 'resources', 'views')
            )
            self.app = Flask(__name__, template_folder=template_folder)
            
            # Load routes in app context
            with self.app.app_context():
                self._load_routes()
            
            self.logger.info("Flask application initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize Flask application: {e}")
            raise
    
    def _load_routes(self):
        """Load web routes and API blueprints."""
        try:
            # Add project root to path for imports
            project_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..')
            )
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            
            # Import and register routes
            import routes.web  # This loads web routes
            
            # Import and register API blueprint
            from routes.api import api
            self.app.register_blueprint(api)
            
            self.logger.info("Routes loaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to load routes: {e}")
            # Don't raise here, let the service start with basic functionality
    
    def is_enabled(self) -> bool:
        """
        Check if the web service is enabled.
        
        Returns:
            bool: True if FLASK_HOST is set in configuration, False otherwise
        """
        return bool(self.config.get('host') or self.config.get('enabled', False))
    
    def _run(self):
        """Run the Flask development server."""
        if not self.app:
            self.logger.error("Flask app not initialized")
            return
        
        try:
            host = self.config.get('host', '127.0.0.1')
            port = self.config.get('port', 5000)
            debug = self.config.get('debug', False)
            
            self.logger.info(f"Starting Flask server on {host}:{port}")
            
            # Run Flask app
            self.app.run(
                host=host,
                port=port,
                debug=debug,
                use_reloader=False,  # Disable reloader to avoid threading issues
                threaded=True
            )
        except Exception as e:
            self.logger.error(f"Flask server error: {e}")
        finally:
            self.is_running = False
    
    def get_flask_app(self) -> Flask:
        """
        Get the Flask application instance.
        
        Returns:
            Flask: The Flask application instance
        """
        return self.app
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the web service.
        
        Returns:
            Dict[str, Any]: Service status including Flask-specific information
        """
        status = super().get_status()
        status.update({
            'host': self.config.get('host', 'Not set'),
            'port': self.config.get('port', 'Not set'),
            'debug': self.config.get('debug', False),
            'app_initialized': self.app is not None
        })
        return status