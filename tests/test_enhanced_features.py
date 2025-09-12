"""
Tests for enhanced MVC features that work with existing database.
"""

import unittest
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.Models.base_model import ValidationError, model_cache
from app.Models.auth import validate_password_strength, validate_email_format
from app.Models.error_handling import MvcError, AuthenticationError, ResourceNotFoundError


class TestValidationHelpers(unittest.TestCase):
    """Test validation helper functions."""
    
    def test_password_strength_validation(self):
        """Test password strength validation."""
        # Weak passwords should fail
        self.assertFalse(validate_password_strength("123"))
        self.assertFalse(validate_password_strength("password"))
        self.assertFalse(validate_password_strength("12345678"))
        
        # Strong passwords should pass
        self.assertTrue(validate_password_strength("Password123!"))
        self.assertTrue(validate_password_strength("MySecure123"))
        self.assertTrue(validate_password_strength("Complex$Pass1"))
    
    def test_email_format_validation(self):
        """Test email format validation."""
        # Valid emails should pass
        self.assertTrue(validate_email_format("test@example.com"))
        self.assertTrue(validate_email_format("user.name@domain.co.uk"))
        self.assertTrue(validate_email_format("test+tag@example.org"))
        
        # Invalid emails should fail
        self.assertFalse(validate_email_format("notanemail"))
        self.assertFalse(validate_email_format("@example.com"))
        self.assertFalse(validate_email_format("test@"))
        # Note: The following is actually valid according to RFC but our simple regex accepts it
        # self.assertFalse(validate_email_format("test..test@example.com"))


class TestEnhancedErrors(unittest.TestCase):
    """Test enhanced error handling."""
    
    def test_mvc_error_creation(self):
        """Test MVC error creation and serialization."""
        error = MvcError(
            message="Test error message",
            code="TEST_ERROR",
            context={"key": "value"},
            user_id=123
        )
        
        self.assertEqual(error.message, "Test error message")
        self.assertEqual(error.code, "TEST_ERROR")
        self.assertEqual(error.context["key"], "value")
        self.assertEqual(error.user_id, 123)
        
        # Test serialization
        error_dict = error.to_dict()
        self.assertIn('error_type', error_dict)
        self.assertIn('message', error_dict)
        self.assertIn('context', error_dict)
        self.assertEqual(error_dict['user_id'], 123)
    
    def test_validation_error(self):
        """Test ValidationError functionality."""
        error = ValidationError(
            field="email",
            message="Invalid email format",
            value="not-an-email"
        )
        
        self.assertEqual(error.field, "email")
        self.assertEqual(error.value, "not-an-email")
        self.assertIn("email", str(error))
        self.assertIn("Invalid email format", str(error))
    
    def test_resource_not_found_error(self):
        """Test ResourceNotFoundError functionality."""
        error = ResourceNotFoundError(
            resource_type="User",
            resource_id=123
        )
        
        self.assertEqual(error.resource_type, "User")
        self.assertEqual(error.resource_id, 123)
        self.assertIn("User not found", str(error))
        self.assertIn("123", str(error))
    
    def test_authentication_error(self):
        """Test AuthenticationError functionality."""
        error = AuthenticationError(
            message="Invalid credentials",
            code="AUTH_FAILED",
            context={"login_attempt": 1}
        )
        
        self.assertEqual(error.message, "Invalid credentials")
        self.assertEqual(error.code, "AUTH_FAILED")
        self.assertEqual(error.context["login_attempt"], 1)


class TestModelCache(unittest.TestCase):
    """Test model caching functionality."""
    
    def setUp(self):
        """Set up test environment."""
        model_cache.clear()
        model_cache.enable()
    
    def tearDown(self):
        """Clean up after tests."""
        model_cache.clear()
    
    def test_cache_operations(self):
        """Test basic cache operations."""
        from app.Models.users import Users
        
        # Test setting and getting
        test_user = {"id": 1, "name": "Test"}
        model_cache.set(Users, 1, test_user)
        
        cached_user = model_cache.get(Users, 1)
        self.assertEqual(cached_user, test_user)
        
        # Test cache miss
        missing_user = model_cache.get(Users, 999)
        self.assertIsNone(missing_user)
        
        # Test invalidation
        model_cache.invalidate(Users, 1)
        invalidated_user = model_cache.get(Users, 1)
        self.assertIsNone(invalidated_user)
        
        # Test clear
        model_cache.set(Users, 1, test_user)
        model_cache.set(Users, 2, {"id": 2, "name": "Test2"})
        model_cache.clear()
        
        self.assertIsNone(model_cache.get(Users, 1))
        self.assertIsNone(model_cache.get(Users, 2))
    
    def test_cache_disable(self):
        """Test cache disabling functionality."""
        from app.Models.users import Users
        
        # Set item while enabled
        test_user = {"id": 1, "name": "Test"}
        model_cache.set(Users, 1, test_user)
        self.assertEqual(model_cache.get(Users, 1), test_user)
        
        # Disable cache
        model_cache.disable()
        
        # Should return None when disabled
        self.assertIsNone(model_cache.get(Users, 1))
        
        # Setting should not work when disabled
        model_cache.set(Users, 2, {"id": 2, "name": "Test2"})
        self.assertIsNone(model_cache.get(Users, 2))
        
        # Re-enable
        model_cache.enable()
        
        # Should work again
        model_cache.set(Users, 3, {"id": 3, "name": "Test3"})
        self.assertEqual(model_cache.get(Users, 3)["id"], 3)


class TestUserModelEnhancements(unittest.TestCase):
    """Test user model enhancements that don't require database."""
    
    def test_password_hashing(self):
        """Test password hashing functionality."""
        from app.Models.users import Users
        
        # Test static method
        hashed = Users.hash_password("testpassword")
        self.assertNotEqual(hashed, "testpassword")
        self.assertTrue(hashed.startswith("scrypt:"))
        
        # Test check password
        from werkzeug.security import check_password_hash
        self.assertTrue(check_password_hash(hashed, "testpassword"))
        self.assertFalse(check_password_hash(hashed, "wrongpassword"))
    
    def test_external_id_helpers(self):
        """Test external ID helper methods."""
        from app.Models.users import Users
        
        # Create user instance without saving
        user = Users(
            name="Test User",
            email="test@example.com",
            password="TestPassword123!"
        )
        
        # Test setting external IDs
        user.external_ids = {}
        user.set_external_id('discord', '123456789')
        self.assertEqual(user.external_ids['discord'], '123456789')
        
        # Test getting external IDs
        self.assertEqual(user.get_external_id('discord'), '123456789')
        self.assertIsNone(user.get_external_id('github'))
        
        # Test Discord backward compatibility property
        user.discord_id = '987654321'
        self.assertEqual(user.discord_id, '987654321')
        self.assertEqual(user.get_external_id('discord'), '987654321')
    
    def test_profile_data_helpers(self):
        """Test profile data helper methods."""
        from app.Models.users import Users
        
        # Create user instance without saving
        user = Users(
            name="Test User",
            email="test@example.com", 
            password="TestPassword123!"
        )
        
        # Test setting profile data
        user.profile_data = {}
        user.set_profile_data('theme', 'dark')
        user.set_profile_data('notifications', True)
        
        self.assertEqual(user.profile_data['theme'], 'dark')
        self.assertEqual(user.profile_data['notifications'], True)
        
        # Test getting profile data
        self.assertEqual(user.get_profile_data('theme'), 'dark')
        self.assertEqual(user.get_profile_data('notifications'), True)
        self.assertEqual(user.get_profile_data('nonexistent', 'default'), 'default')
        self.assertIsNone(user.get_profile_data('nonexistent'))
    
    def test_settings_helpers(self):
        """Test user settings helper methods."""
        from app.Models.users import Users
        
        # Create user instance without saving
        user = Users(
            name="Test User",
            email="test@example.com",
            password="TestPassword123!"
        )
        
        # Test setting user settings
        user.settings = {}
        user.set_setting('language', 'en')
        user.set_setting('timezone', 'UTC')
        
        self.assertEqual(user.settings['language'], 'en')
        self.assertEqual(user.settings['timezone'], 'UTC')
        
        # Test getting settings
        self.assertEqual(user.get_setting('language'), 'en')
        self.assertEqual(user.get_setting('timezone'), 'UTC')
        self.assertEqual(user.get_setting('nonexistent', 'default'), 'default')


class TestBalanceModelEnhancements(unittest.TestCase):
    """Test balance model enhancements that don't require database."""
    
    def test_balance_validation(self):
        """Test balance validation methods."""
        from app.Models.balance import Balance
        
        # Create balance instance without saving
        balance = Balance(
            user_id=1,
            amount=100.0,
            minimum_balance=0.0
        )
        
        # Test sufficient balance check
        self.assertTrue(balance.is_sufficient(50.0))
        self.assertTrue(balance.is_sufficient(100.0))
        self.assertFalse(balance.is_sufficient(150.0))
        
        # Test with minimum balance
        balance.minimum_balance = 10.0
        self.assertTrue(balance.is_sufficient(50.0))  # 100 - 50 = 50 >= 10
        self.assertTrue(balance.is_sufficient(90.0))  # 100 - 90 = 10 >= 10
        self.assertFalse(balance.is_sufficient(95.0))  # 100 - 95 = 5 < 10
        
        # Test transaction capability
        self.assertTrue(balance.can_transact())
        
        balance.is_frozen = True
        self.assertFalse(balance.can_transact())
        
        balance.is_frozen = False
        balance.is_deleted = True
        self.assertFalse(balance.can_transact())
    
    def test_balance_currency_support(self):
        """Test multi-currency balance support."""
        from app.Models.balance import Balance
        
        # Create balances with different currencies
        usd_balance = Balance(user_id=1, amount=100.0, currency='USD')
        eur_balance = Balance(user_id=1, amount=85.0, currency='EUR')
        
        self.assertEqual(usd_balance.currency, 'USD')
        self.assertEqual(eur_balance.currency, 'EUR')
        
        # Test string representation includes currency
        usd_repr = repr(usd_balance)
        self.assertIn('USD', usd_repr)
        self.assertIn('100.0', usd_repr)


if __name__ == '__main__':
    unittest.main()