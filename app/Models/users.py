from sqlalchemy import Column, String, Integer, Float, ForeignKey, Boolean, DateTime, Text, Date, JSON
from database.db import BaseModel, session
from sqlalchemy.orm import relationship
from app.Models.balance import Balance  # Import the Balance model
from app.Models.base_model import EnhancedBaseModel, ValidationError
from app.Models.auth import validate_password_strength, validate_email_format
from datetime import datetime
from typing import Dict, Any, Optional, List
from werkzeug.security import generate_password_hash, check_password_hash
import logging

logger = logging.getLogger(__name__)

# Define the Users model class, inheriting from EnhancedBaseModel for enhanced features
class Users(EnhancedBaseModel):
    """
    Users model representing the users of the application.

    This enhanced model provides comprehensive user management with:
    - Enhanced validation and security features
    - Audit trails and soft delete functionality
    - Improved password management with hashing
    - External service integration (Discord, OAuth, etc.)
    - Profile data management
    - Balance management integration
    - Session and token management support

    Attributes:
        __tablename__ (str): The name of the table in the database.
        name (str): The name of the user.
        username (str): The unique username of the user.
        email (str): The unique email of the user (validated format).
        password_hash (str): The hashed password of the user.
        is_admin (bool): Indicates if the user is an admin.
        is_verified (bool): Indicates if the user's email has been verified.
        external_ids (dict): Dictionary to store external service IDs (Discord, etc.)
        profile_data (dict): Additional profile information
        settings (dict): User preferences and settings
        last_login (datetime): Last time the user logged in
        last_active (datetime): Last time the user was active
        failed_login_attempts (int): Number of failed login attempts
        locked_until (datetime): Account lock expiration time
        balances (relationship): The relationship to the Balance model.
        
    Inherited from EnhancedBaseModel:
        id (int): Primary key
        created_at (datetime): When the user was created
        updated_at (datetime): When the user was last updated  
        created_by (str): Who created the user
        updated_by (str): Who last updated the user
        deleted_at (datetime): When the user was soft deleted
        deleted_by (str): Who deleted the user
        is_deleted (bool): Whether the user is soft deleted
    """
    __tablename__ = 'users'  # Define the table name

    # Define the columns of the Users model
    name = Column(String, index=True, nullable=True)  # Define the name column
    username = Column(String, unique=True, index=True, nullable=True)  # Define the username column
    email = Column(String, unique=True, index=True, nullable=False)  # Define the email column
    password_hash = Column(String, nullable=False)  # Define the password_hash column (renamed for security)
    is_admin = Column(Boolean, default=False)  # Define the is_admin column
    is_verified = Column(Boolean, default=False)  # Email verification status
    external_ids = Column(JSON, default=dict)  # Store external service IDs (Discord, etc.)
    profile_data = Column(JSON, default=dict)  # Additional profile information
    settings = Column(JSON, default=dict)  # User preferences and settings
    last_login = Column(DateTime, nullable=True)  # Last login time
    last_active = Column(DateTime, nullable=True)  # Last activity time
    failed_login_attempts = Column(Integer, default=0, nullable=False)  # Failed login counter
    locked_until = Column(DateTime, nullable=True)  # Account lock expiration

    # Define a relationship to the Balance model
    balances = relationship('Balance', backref='user', cascade='all, delete-orphan')

    def __init__(self, **kwargs):
        # Hash password if provided as 'password' instead of 'password_hash'
        if 'password' in kwargs:
            plain_password = kwargs.pop('password')
            kwargs['password_hash'] = self.hash_password(plain_password)
        
        super().__init__(**kwargs)
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password for storing."""
        return generate_password_hash(password)
    
    def check_password(self, password: str) -> bool:
        """Check if provided password matches the hash."""
        return check_password_hash(self.password_hash, password)
    
    def set_password(self, password: str):
        """Set a new password (with validation)."""
        if not validate_password_strength(password):
            raise ValidationError('password', 'Password does not meet security requirements')
        self.password_hash = self.hash_password(password)
        session.commit()
    
    def is_account_locked(self) -> bool:
        """Check if account is currently locked."""
        if not self.locked_until:
            return False
        return datetime.now() < self.locked_until
    
    def lock_account(self, hours: int = 1):
        """Lock the account for specified hours."""
        from datetime import timedelta
        self.locked_until = datetime.now() + timedelta(hours=hours)
        session.commit()
    
    def unlock_account(self):
        """Unlock the account."""
        self.locked_until = None
        self.failed_login_attempts = 0
        session.commit()
    
    def record_failed_login(self):
        """Record a failed login attempt."""
        self.failed_login_attempts += 1
        
        # Lock account after 5 failed attempts
        if self.failed_login_attempts >= 5:
            self.lock_account(1)  # Lock for 1 hour
        
        session.commit()
    
    def record_successful_login(self):
        """Record a successful login."""
        self.last_login = datetime.now()
        self.failed_login_attempts = 0
        self.locked_until = None
        session.commit()
    
    def update_activity(self):
        """Update last activity timestamp."""
        self.last_active = datetime.now()
        session.commit()

    def __repr__(self):
        """
        String representation of the Users model.

        Returns:
            str: A string representation of the Users instance.
        """
        return f"<User(id={self.id}, name={self.name}, email={self.email})>"

    def get_balance(self):
        """
        Get the user's balance model instance, creating one if it doesn't exist.

        Returns:
            Balance: The user's balance model instance.
        """
        if not self.balances:
            new_balance = Balance(user_id=self.id, amount=0.0)
            session.add(new_balance)
            session.commit()
            return new_balance
        return self.balances[0]
    
    def balance(self):
        """
        Get the user's balance amount, creating one if it doesn't exist.

        Returns:
            float: The user's balance amount.
        """
        if not self.balances:
            new_balance = Balance(user_id=self.id, amount=0.0)
            session.add(new_balance)
            session.commit()
            return new_balance.amount
        return self.balances[0].amount

    def deposit(self, amount):
        """
        Deposit an amount to the user's balance.

        Args:
            amount (float): The amount to deposit.
        """
        balance = self.get_balance()
        balance.amount += amount
        session.commit()

    def withdraw(self, amount):
        """
        Withdraw an amount from the user's balance.

        Args:
            amount (float): The amount to withdraw.

        Raises:
            ValueError: If the balance is insufficient.
        """
        balance = self.get_balance()
        if balance.amount >= amount:
            balance.amount -= amount
            session.commit()
        else:
            raise ValueError("Insufficient balance")
        
        
    def transfer(self, recipient, amount):
        """
        Transfer an amount from the user's balance to the recipient's balance.

        Args:
            recipient (Users): The recipient user.
            amount (float): The amount to transfer.

        Raises:
            ValueError: If the balance is insufficient.
        """
        balance = self.get_balance()
        if balance.amount >= amount:
            balance.amount -= amount
            recipient_balance = recipient.get_balance()
            recipient_balance.amount += amount
            session.commit()
        else:
            raise ValueError("Insufficient balance")

    def set_external_id(self, service: str, external_id: str):
        """
        Set an external service ID for the user.
        
        Args:
            service (str): The name of the external service (e.g., 'discord', 'github')
            external_id (str): The external ID from that service
        """
        if not self.external_ids:
            self.external_ids = {}
        self.external_ids[service] = external_id
        session.commit()
    
    def get_external_id(self, service: str) -> Optional[str]:
        """
        Get an external service ID for the user.
        
        Args:
            service (str): The name of the external service
            
        Returns:
            Optional[str]: The external ID or None if not found
        """
        if not self.external_ids:
            return None
        return self.external_ids.get(service)
    
    def set_profile_data(self, key: str, value: Any):
        """
        Set profile data for the user.
        
        Args:
            key (str): The profile data key
            value (Any): The profile data value
        """
        if not self.profile_data:
            self.profile_data = {}
        self.profile_data[key] = value
        session.commit()
    
    def get_profile_data(self, key: str, default: Any = None) -> Any:
        """
        Get profile data for the user.
        
        Args:
            key (str): The profile data key
            default (Any): Default value if key not found
            
        Returns:
            Any: The profile data value or default
        """
        if not self.profile_data:
            return default
        return self.profile_data.get(key, default)

    # Backward compatibility properties for Discord
    @property
    def discord_id(self) -> Optional[str]:
        """
        Backward compatibility property for Discord ID.
        
        Returns:
            Optional[str]: Discord ID or None
        """
        return self.get_external_id('discord')
    
    @discord_id.setter
    def discord_id(self, value: str):
        """
        Backward compatibility setter for Discord ID.
        
        Args:
            value (str): Discord ID to set
        """
        if value:
            self.set_external_id('discord', str(value))
    
    def verify_email(self):
        """Mark email as verified."""
        self.is_verified = True
        session.commit()
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Get user setting.
        
        Args:
            key: Setting key
            default: Default value if key not found
            
        Returns:
            Setting value or default
        """
        if not self.settings:
            return default
        return self.settings.get(key, default)
    
    def set_setting(self, key: str, value: Any):
        """
        Set user setting.
        
        Args:
            key: Setting key
            value: Setting value
        """
        if not self.settings:
            self.settings = {}
        self.settings[key] = value
        session.commit()
    
    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        """
        Convert user to dictionary (excluding sensitive data by default).
        
        Args:
            include_sensitive: Whether to include sensitive data like password_hash
            
        Returns:
            Dictionary representation
        """
        exclude = ['password_hash'] if not include_sensitive else []
        return super().to_dict(exclude=exclude)
    
    @classmethod
    def create_user(cls, name: str, email: str, password: str, username: str = None,
                   validate: bool = True, **kwargs):
        """
        Create a new user with validation.
        
        Args:
            name: User's name
            email: User's email
            password: Plain text password
            username: Username (optional)
            validate: Whether to validate input
            **kwargs: Additional user attributes
            
        Returns:
            Users instance
            
        Raises:
            ValidationError: If validation fails
        """
        if validate:
            if not validate_email_format(email):
                raise ValidationError('email', 'Invalid email format')
            
            if not validate_password_strength(password):
                raise ValidationError('password', 'Password does not meet security requirements')
            
            # Check for existing email
            if cls.find_one_by(email=email):
                raise ValidationError('email', 'Email already exists')
            
            # Check for existing username if provided
            if username and cls.find_one_by(username=username):
                raise ValidationError('username', 'Username already exists')
        
        return cls.create(
            name=name,
            email=email,
            password=password,  # Will be hashed in __init__
            username=username,
            validate=validate,
            **kwargs
        )
    
    @classmethod
    def authenticate(cls, email: str, password: str) -> Optional['Users']:
        """
        Authenticate user with email and password.
        
        Args:
            email: User's email
            password: Plain text password
            
        Returns:
            User instance if authentication succeeds, None otherwise
        """
        user = cls.find_one_by(email=email)
        
        if not user or user.is_deleted:
            return None
        
        if user.is_account_locked():
            return None
        
        if user.check_password(password):
            user.record_successful_login()
            return user
        else:
            user.record_failed_login()
            return None
    
    @classmethod
    def find_by_email(cls, email: str) -> Optional['Users']:
        """Find user by email."""
        return cls.find_one_by(email=email)
    
    @classmethod
    def find_by_username(cls, username: str) -> Optional['Users']:
        """Find user by username."""
        return cls.find_one_by(username=username)
    
    @classmethod
    def find_by_external_id(cls, service: str, external_id: str) -> Optional['Users']:
        """Find user by external service ID."""
        # This is more complex due to JSON column - we'll use raw SQL for now
        # In production, consider using PostgreSQL JSONB for better querying
        users = cls.all()
        for user in users:
            if user.get_external_id(service) == external_id:
                return user
        return None
    
    @classmethod
    def search_users(cls, query: str, limit: int = 10) -> List['Users']:
        """
        Search users by name, username, or email.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of matching users
        """
        # This is a simple implementation - in production use full-text search
        query = query.lower()
        users = cls.all()
        
        matches = []
        for user in users:
            if (user.name and query in user.name.lower()) or \
               (user.username and query in user.username.lower()) or \
               (user.email and query in user.email.lower()):
                matches.append(user)
                
                if len(matches) >= limit:
                    break
        
        return matches
     
# Example usage of the Users model

# Create two user instances
# user1 = Users.create(name="Zaber", email="zaber@example.com", password="password123")
# user2 = Users.create(name="Mahedi", email="mahedi@example.com", password="password456")

# Deposit money into user1's account
# user1.deposit(100.0)

# Withdraw money from user1's account
# try:
#     user1.withdraw(50.0)
# except ValueError as e:
#     print(e)

# Transfer money from user1 to user2
# try:
#     user1.transfer(user2, 25.0)
# except ValueError as e:
#     print(e)

# Print the balances of both users
# print(f"User1's balance: {user1.balance()}")
# print(f"User2's balance: {user2.balance()}")

# Get Balance model instance which have id, user_id, amount
# Balance1 = user1.get_balance()
# Balance2 = user2.get_balance()