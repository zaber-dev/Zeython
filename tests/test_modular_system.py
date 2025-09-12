"""
Basic tests for the modular MVC framework.
"""

import unittest
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.Core.service_manager import ServiceManager
from app.Core.config import Config
from app.Core.service import ServiceInterface, ThreadedService
from app.Services.web_service import WebService


class MockService(ThreadedService):
    """Mock service for testing."""
    
    def __init__(self, name: str, config: dict = None):
        super().__init__(name, config)
        self.run_called = False
    
    def is_enabled(self) -> bool:
        return self.config.get('enabled', True)
    
    def _run(self):
        self.run_called = True


class TestServiceManager(unittest.TestCase):
    """Test the service manager functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.service_manager = ServiceManager()
    
    def test_register_service_class(self):
        """Test service class registration."""
        self.service_manager.register_service_class(MockService, "mock")
        self.assertIn("mock", self.service_manager.list_available_services())
    
    def test_create_service(self):
        """Test service creation."""
        self.service_manager.register_service_class(MockService, "mock")
        service = self.service_manager.create_service("mock", {"enabled": True})
        
        self.assertIsNotNone(service)
        self.assertIsInstance(service, MockService)
        self.assertIn("mock", self.service_manager.list_registered_services())
    
    def test_service_lifecycle(self):
        """Test service start/stop lifecycle."""
        self.service_manager.register_service_class(MockService, "mock")
        service = self.service_manager.create_service("mock", {"enabled": True})
        
        # Test start
        self.assertTrue(self.service_manager.start_service("mock"))
        
        # Test stop
        self.assertTrue(self.service_manager.stop_service("mock"))
    
    def test_service_status(self):
        """Test service status reporting."""
        self.service_manager.register_service_class(MockService, "mock")
        service = self.service_manager.create_service("mock", {"enabled": True})
        
        status = self.service_manager.get_service_status()
        self.assertIn('services', status)
        self.assertIn('total_services', status)
        self.assertEqual(status['total_services'], 1)


class TestConfig(unittest.TestCase):
    """Test configuration management."""
    
    def setUp(self):
        """Set up test environment."""
        self.config = Config()
    
    def test_get_set(self):
        """Test getting and setting configuration values."""
        self.config.set('test.key', 'test_value')
        self.assertEqual(self.config.get('test.key'), 'test_value')
        self.assertEqual(self.config.get('nonexistent.key', 'default'), 'default')
    
    def test_service_config(self):
        """Test service-specific configuration."""
        self.config.set('web.host', '127.0.0.1')
        self.config.set('web.port', 5000)
        
        web_config = self.config.get_service_config('web')
        self.assertEqual(web_config['host'], '127.0.0.1')
        self.assertEqual(web_config['port'], 5000)
    
    def test_service_enabled(self):
        """Test service enabled check."""
        self.config.set('test_service.enabled', True)
        self.assertTrue(self.config.is_service_enabled('test_service'))
        
        self.config.set('test_service.enabled', False)
        self.assertFalse(self.config.is_service_enabled('test_service'))


class TestWebService(unittest.TestCase):
    """Test web service functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.config = {
            'host': '127.0.0.1',
            'port': 5000,
            'enabled': True
        }
    
    def test_web_service_creation(self):
        """Test web service creation."""
        service = WebService("web", self.config)
        self.assertIsNotNone(service)
        self.assertIsNotNone(service.get_flask_app())
    
    def test_web_service_enabled(self):
        """Test web service enabled check."""
        service = WebService("web", self.config)
        self.assertTrue(service.is_enabled())
        
        # Test with disabled config
        disabled_config = {'enabled': False}
        service = WebService("web", disabled_config)
        self.assertFalse(service.is_enabled())
    
    def test_web_service_status(self):
        """Test web service status."""
        service = WebService("web", self.config)
        status = service.get_status()
        
        self.assertIn('name', status)
        self.assertIn('host', status)
        self.assertIn('port', status)
        self.assertIn('app_initialized', status)
        self.assertTrue(status['app_initialized'])


class TestUserModel(unittest.TestCase):
    """Test the generalized User model."""
    
    def setUp(self):
        """Set up test environment."""
        # Import here to avoid database connection issues during test discovery
        from app.Models.users import Users
        self.Users = Users
    
    def test_external_id_management(self):
        """Test external ID management methods."""
        # Create a user instance (without saving to DB)
        user = self.Users(
            name="Test User",
            email="test@example.com",
            password="password123"
        )
        
        # Test setting and getting external IDs
        user.set_external_id('discord', '123456789')
        self.assertEqual(user.get_external_id('discord'), '123456789')
        
        # Test Discord backward compatibility
        user.discord_id = '987654321'
        self.assertEqual(user.discord_id, '987654321')
    
    def test_profile_data_management(self):
        """Test profile data management methods."""
        # Create a user instance (without saving to DB)
        user = self.Users(
            name="Test User",
            email="test@example.com",
            password="password123"
        )
        
        # Test setting and getting profile data
        user.set_profile_data('theme', 'dark')
        self.assertEqual(user.get_profile_data('theme'), 'dark')
        self.assertEqual(user.get_profile_data('nonexistent', 'default'), 'default')


if __name__ == '__main__':
    # Set environment variable for testing
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    
    unittest.main()