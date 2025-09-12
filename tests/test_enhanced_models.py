"""
Enhanced tests for the improved MVC models and features.
"""

import unittest
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set environment for testing
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app.Models.base_model import EnhancedBaseModel, ValidationError, ModelEvents, model_cache
from app.Models.users import Users
from app.Models.balance import Balance
from app.Models.auth import UserSession, AccessToken, PasswordReset, validate_password_strength, validate_email_format
from app.Models.error_handling import ErrorLog, ActivityLog, MvcError
from app.Models.service_layer import UserService, BalanceService


class TestEnhancedBaseModel(unittest.TestCase):
    """Test the enhanced base model functionality."""
    
    def setUp(self):
        """Set up test environment."""
        # Enable caching for tests
        model_cache.enable()
    
    def tearDown(self):
        """Clean up after tests."""
        model_cache.clear()
    
    def test_model_validation(self):
        """Test model validation functionality."""
        # Create a test model instance
        user = Users(
            name="Test User",
            email="test@example.com",
            password="weak"  # This should fail validation
        )
        
        # Add a validator
        Users.add_validator('password_hash', 
                           lambda x: len(x) > 10,  # Simple length check
                           "Password hash must be longer than 10 characters")
        
        # Test validation
        errors = user.validate()
        self.assertEqual(len(errors), 0)  # No errors because password is hashed
        
        # Test validation with invalid data
        user.name = ""  # Empty name should be invalid if we add a validator
        Users.add_validator('name', 
                           lambda x: x and len(x.strip()) > 0,
                           "Name cannot be empty")
        
        errors = user.validate()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].field, 'name')
    
    def test_model_caching(self):
        """Test model caching functionality."""
        # Create a user (this should be cached)
        user = Users.create(
            name="Cached User",
            email="cached@example.com",
            password="password123"
        )
        
        # Get the user again (should come from cache)
        cached_user = Users.get(user.id, use_cache=True)
        self.assertEqual(user.id, cached_user.id)
        
        # Verify cache contains the user
        cached_instance = model_cache.get(Users, user.id)
        self.assertIsNotNone(cached_instance)
        
        # Update user (should invalidate cache)
        user.update(name="Updated Name")
        
        # Verify cache was invalidated and new data is retrieved
        updated_user = Users.get(user.id, use_cache=True)
        self.assertEqual(updated_user.name, "Updated Name")
    
    def test_soft_delete(self):
        """Test soft delete functionality."""
        user = Users.create(
            name="To Delete",
            email="delete@example.com",
            password="password123"
        )
        
        # Soft delete the user
        user.soft_delete("test_user")
        
        # User should be marked as deleted
        self.assertTrue(user.is_deleted)
        self.assertIsNotNone(user.deleted_at)
        self.assertEqual(user.deleted_by, "test_user")
        
        # User should not be found in normal queries
        found_user = Users.get(user.id)
        self.assertIsNone(found_user)
        
        # User should be found in queries that include deleted
        found_user = Users.get(user.id, use_cache=False)  # Bypass cache
        with_deleted = Users.with_deleted().filter(Users.id == user.id).first()
        self.assertIsNotNone(with_deleted)
        self.assertTrue(with_deleted.is_deleted)
        
        # Test restore
        user.restore()
        self.assertFalse(user.is_deleted)
        self.assertIsNone(user.deleted_at)
    
    def test_json_serialization(self):
        """Test JSON serialization functionality."""
        user = Users.create(
            name="JSON User",
            email="json@example.com",
            password="password123"
        )
        
        # Test to_dict
        user_dict = user.to_dict()
        self.assertIn('id', user_dict)
        self.assertIn('name', user_dict)
        self.assertIn('email', user_dict)
        self.assertNotIn('password_hash', user_dict)  # Should be excluded by default
        
        # Test to_dict with excluded fields
        user_dict = user.to_dict(exclude=['email', 'created_at'])
        self.assertNotIn('email', user_dict)
        self.assertNotIn('created_at', user_dict)
        
        # Test to_json
        user_json = user.to_json()
        self.assertIsInstance(user_json, str)
        
        # Test from_dict
        new_user_data = {
            'name': 'Dict User',
            'email': 'dict@example.com',
            'password': 'password123'
        }
        new_user = Users.from_dict(new_user_data)
        self.assertEqual(new_user.name, 'Dict User')
        self.assertEqual(new_user.email, 'dict@example.com')


class TestEnhancedUsers(unittest.TestCase):
    """Test enhanced Users model functionality."""
    
    def test_password_hashing(self):
        """Test password hashing and validation."""
        user = Users.create_user(
            name="Hash Test",
            email="hash@example.com", 
            password="password123"
        )
        
        # Password should be hashed
        self.assertNotEqual(user.password_hash, "password123")
        
        # Check password should work
        self.assertTrue(user.check_password("password123"))
        self.assertFalse(user.check_password("wrongpassword"))
        
        # Set new password
        user.set_password("newpassword123")
        self.assertTrue(user.check_password("newpassword123"))
        self.assertFalse(user.check_password("password123"))
    
    def test_account_locking(self):
        """Test account locking functionality."""
        user = Users.create_user(
            name="Lock Test",
            email="lock@example.com",
            password="password123"
        )
        
        # Account should not be locked initially
        self.assertFalse(user.is_account_locked())
        
        # Record failed login attempts
        for i in range(5):
            user.record_failed_login()
        
        # Account should be locked after 5 failed attempts
        self.assertTrue(user.is_account_locked())
        
        # Unlock account
        user.unlock_account()
        self.assertFalse(user.is_account_locked())
        self.assertEqual(user.failed_login_attempts, 0)
    
    def test_external_id_management(self):
        """Test external ID management."""
        user = Users.create_user(
            name="External Test",
            email="external@example.com",
            password="password123"
        )
        
        # Set external IDs
        user.set_external_id('discord', '123456789')
        user.set_external_id('github', 'user123')
        
        # Get external IDs
        self.assertEqual(user.get_external_id('discord'), '123456789')
        self.assertEqual(user.get_external_id('github'), 'user123')
        self.assertIsNone(user.get_external_id('twitter'))
        
        # Test Discord backward compatibility
        user.discord_id = '987654321'
        self.assertEqual(user.discord_id, '987654321')
        self.assertEqual(user.get_external_id('discord'), '987654321')
    
    def test_user_settings(self):
        """Test user settings management."""
        user = Users.create_user(
            name="Settings Test",
            email="settings@example.com",
            password="password123"
        )
        
        # Set settings
        user.set_setting('theme', 'dark')
        user.set_setting('notifications', True)
        
        # Get settings
        self.assertEqual(user.get_setting('theme'), 'dark')
        self.assertEqual(user.get_setting('notifications'), True)
        self.assertEqual(user.get_setting('nonexistent', 'default'), 'default')


class TestEnhancedBalance(unittest.TestCase):
    """Test enhanced Balance model functionality."""
    
    def test_balance_operations(self):
        """Test balance deposit, withdraw, and transfer operations."""
        # Create users
        user1 = Users.create_user(
            name="User One",
            email="user1@example.com",
            password="password123"
        )
        user2 = Users.create_user(
            name="User Two",
            email="user2@example.com",
            password="password123"
        )
        
        # Create balances
        balance1 = Balance.create_for_user(user1.id, initial_amount=100.0)
        balance2 = Balance.create_for_user(user2.id, initial_amount=0.0)
        
        # Test deposit
        balance1.deposit(50.0)
        self.assertEqual(balance1.amount, 150.0)
        
        # Test withdraw
        balance1.withdraw(25.0)
        self.assertEqual(balance1.amount, 125.0)
        
        # Test insufficient funds
        with self.assertRaises(ValidationError):
            balance1.withdraw(200.0)
        
        # Test transfer
        balance1.transfer_to(balance2, 25.0)
        self.assertEqual(balance1.amount, 100.0)
        self.assertEqual(balance2.amount, 25.0)
        
        # Test insufficient funds for transfer
        with self.assertRaises(ValidationError):
            balance1.transfer_to(balance2, 200.0)
    
    def test_balance_freezing(self):
        """Test balance freezing functionality."""
        user = Users.create_user(
            name="Freeze Test",
            email="freeze@example.com",
            password="password123"
        )
        
        balance = Balance.create_for_user(user.id, initial_amount=100.0)
        
        # Balance should allow transactions initially
        self.assertTrue(balance.can_transact())
        
        # Freeze balance
        balance.freeze()
        self.assertFalse(balance.can_transact())
        
        # Frozen balance should not allow transactions
        with self.assertRaises(ValidationError):
            balance.deposit(10.0)
        
        with self.assertRaises(ValidationError):
            balance.withdraw(10.0)
        
        # Unfreeze balance
        balance.unfreeze()
        self.assertTrue(balance.can_transact())
        
        # Should work after unfreezing
        balance.deposit(10.0)
        self.assertEqual(balance.amount, 110.0)


class TestAuthModels(unittest.TestCase):
    """Test authentication models."""
    
    def test_user_session(self):
        """Test user session management."""
        user = Users.create_user(
            name="Session Test",
            email="session@example.com",
            password="password123"
        )
        
        # Create session
        session = UserSession.create_session(
            user_id=user.id,
            ip_address="192.168.1.1",
            user_agent="Test Browser",
            hours=1
        )
        
        # Session should be valid
        self.assertTrue(session.is_valid())
        self.assertFalse(session.is_expired())
        
        # Update activity
        session.update_activity("192.168.1.2", "Updated Browser")
        self.assertEqual(session.ip_address, "192.168.1.2")
        
        # Terminate session
        session.terminate("manual")
        self.assertFalse(session.is_valid())
        self.assertEqual(session.logout_reason, "manual")
    
    def test_access_token(self):
        """Test JWT access token management."""
        user = Users.create_user(
            name="Token Test",
            email="token@example.com",
            password="password123"
        )
        
        # Create access token
        token_string, token_record = AccessToken.create_token(
            user_id=user.id,
            scope='read write',
            hours=1
        )
        
        # Token should be valid
        self.assertIsNotNone(token_string)
        self.assertEqual(token_record.user_id, user.id)
        self.assertEqual(token_record.scope, 'read write')
        
        # Validate token
        validated_token = AccessToken.validate_token(token_string)
        self.assertIsNotNone(validated_token)
        self.assertEqual(validated_token.id, token_record.id)
        
        # Revoke token
        token_record.revoke()
        validated_token = AccessToken.validate_token(token_string)
        self.assertIsNone(validated_token)
    
    def test_password_reset(self):
        """Test password reset token functionality."""
        user = Users.create_user(
            name="Reset Test",
            email="reset@example.com",
            password="password123"
        )
        
        # Create reset token
        reset_token = PasswordReset.create_reset_token(
            user_id=user.id,
            ip_address="192.168.1.1"
        )
        
        # Token should be valid
        self.assertTrue(reset_token.is_valid())
        self.assertFalse(reset_token.is_expired())
        
        # Use token
        reset_token.use_token()
        self.assertFalse(reset_token.is_valid())
        self.assertTrue(reset_token.is_used)


class TestServiceLayer(unittest.TestCase):
    """Test service layer functionality."""
    
    def test_user_service(self):
        """Test UserService operations."""
        service = UserService()
        
        # Create user through service
        result = service.create_user(
            name="Service User",
            email="service@example.com",
            password="password123",
            initial_balance=50.0
        )
        
        self.assertTrue(result['success'])
        self.assertIn('user', result)
        
        user_data = result['user']
        self.assertEqual(user_data['name'], "Service User")
        self.assertEqual(user_data['email'], "service@example.com")
        
        # Test authentication
        auth_result = service.authenticate_user(
            email="service@example.com",
            password="password123",
            ip_address="192.168.1.1"
        )
        
        self.assertTrue(auth_result['success'])
        self.assertIn('session_token', auth_result)
    
    def test_balance_service(self):
        """Test BalanceService operations."""
        # Create users first
        user_service = UserService()
        
        user1_result = user_service.create_user(
            name="Transfer User 1",
            email="transfer1@example.com",
            password="password123",
            initial_balance=100.0
        )
        
        user2_result = user_service.create_user(
            name="Transfer User 2", 
            email="transfer2@example.com",
            password="password123",
            initial_balance=0.0
        )
        
        user1_id = user1_result['user']['id']
        user2_id = user2_result['user']['id']
        
        # Test balance transfer
        balance_service = BalanceService()
        transfer_result = balance_service.transfer_balance(
            from_user_id=user1_id,
            to_user_id=user2_id,
            amount=25.0,
            initiated_by=user1_id,
            description="Test transfer"
        )
        
        self.assertTrue(transfer_result['success'])
        self.assertIn('transfer', transfer_result)
        
        transfer_data = transfer_result['transfer']
        self.assertEqual(transfer_data['from_balance'], 75.0)
        self.assertEqual(transfer_data['to_balance'], 25.0)


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
        self.assertFalse(validate_email_format("test..test@example.com"))


if __name__ == '__main__':
    unittest.main()