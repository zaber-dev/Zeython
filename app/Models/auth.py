"""
Authentication models for user sessions, tokens, and security management.

This module provides comprehensive authentication functionality including:
- User sessions with automatic cleanup
- JWT token management
- Password reset tokens
- OAuth integration support
- Security audit logging
"""

import os
import secrets
import hashlib
import jwt
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey, JSON
from sqlalchemy.orm import relationship
from werkzeug.security import generate_password_hash, check_password_hash

from .base_model import EnhancedBaseModel
from database.db import session

class UserSession(EnhancedBaseModel):
    """
    User session management with automatic cleanup and security tracking.
    
    Attributes:
        user_id: Foreign key to Users table
        session_token: Unique session identifier
        device_info: Information about the device/browser
        ip_address: IP address of the session
        user_agent: Browser user agent string
        last_activity: Last time the session was used
        expires_at: When the session expires
        is_active: Whether the session is currently active
        logout_reason: Reason for session termination
    """
    __tablename__ = 'user_sessions'
    
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    session_token = Column(String(255), unique=True, nullable=False, index=True)
    device_info = Column(JSON, default=dict)  # Device/browser information
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(Text, nullable=True)
    last_activity = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    logout_reason = Column(String(100), nullable=True)  # manual, expired, forced, etc.
    
    # Relationship to user
    user = relationship('Users', backref='sessions')
    
    def __init__(self, **kwargs):
        # Generate session token if not provided
        if 'session_token' not in kwargs:
            kwargs['session_token'] = self.generate_session_token()
        
        # Set default expiration if not provided (24 hours)
        if 'expires_at' not in kwargs:
            kwargs['expires_at'] = datetime.now(timezone.utc) + timedelta(hours=24)
        
        super().__init__(**kwargs)
    
    @staticmethod
    def generate_session_token() -> str:
        """Generate a secure session token."""
        return secrets.token_urlsafe(64)
    
    def is_expired(self) -> bool:
        """Check if the session has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    def is_valid(self) -> bool:
        """Check if the session is valid (active and not expired)."""
        return self.is_active and not self.is_expired()
    
    def extend_session(self, hours: int = 24):
        """Extend the session expiration time."""
        self.expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        self.last_activity = datetime.now(timezone.utc)
        session.commit()
    
    def terminate(self, reason: str = "manual"):
        """Terminate the session."""
        self.is_active = False
        self.logout_reason = reason
        session.commit()
    
    def update_activity(self, ip_address: str = None, user_agent: str = None):
        """Update session activity information."""
        self.last_activity = datetime.now(timezone.utc)
        if ip_address:
            self.ip_address = ip_address
        if user_agent:
            self.user_agent = user_agent
        session.commit()
    
    @classmethod
    def create_session(cls, user_id: int, ip_address: str = None, 
                      user_agent: str = None, device_info: Dict = None, 
                      hours: int = 24):
        """
        Create a new user session.
        
        Args:
            user_id: ID of the user
            ip_address: IP address of the client
            user_agent: Browser user agent
            device_info: Additional device information
            hours: Session duration in hours
            
        Returns:
            UserSession instance
        """
        expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        
        return cls.create(
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            device_info=device_info or {},
            expires_at=expires_at
        )
    
    @classmethod
    def get_by_token(cls, token: str):
        """Get session by token."""
        return cls.find_one_by(session_token=token)
    
    @classmethod
    def cleanup_expired(cls):
        """Clean up expired sessions."""
        expired_sessions = session.query(cls).filter(
            cls.expires_at < datetime.now(timezone.utc),
            cls.is_active == True
        ).all()
        
        for sess in expired_sessions:
            sess.terminate("expired")
        
        return len(expired_sessions)
    
    @classmethod
    def terminate_user_sessions(cls, user_id: int, except_token: str = None):
        """Terminate all sessions for a user, optionally except one."""
        query = session.query(cls).filter(
            cls.user_id == user_id,
            cls.is_active == True
        )
        
        if except_token:
            query = query.filter(cls.session_token != except_token)
        
        sessions = query.all()
        for sess in sessions:
            sess.terminate("forced")
        
        return len(sessions)

class AccessToken(EnhancedBaseModel):
    """
    JWT access token management for API authentication.
    
    Attributes:
        user_id: Foreign key to Users table
        token_hash: SHA-256 hash of the token for security
        token_type: Type of token (access, refresh, api)
        scope: Token permissions scope
        expires_at: When the token expires
        is_revoked: Whether the token has been revoked
        client_id: Client application identifier
        last_used: Last time the token was used
    """
    __tablename__ = 'access_tokens'
    
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)  # SHA-256 hash
    token_type = Column(String(20), default='access', nullable=False)  # access, refresh, api
    scope = Column(String(255), default='read', nullable=False)  # Permissions scope
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)
    client_id = Column(String(100), nullable=True)  # OAuth client or app identifier
    last_used = Column(DateTime, nullable=True)
    
    # Relationship to user
    user = relationship('Users', backref='access_tokens')
    
    @staticmethod
    def generate_jwt_token(user_id: int, scope: str = 'read', 
                          hours: int = 1, token_type: str = 'access') -> str:
        """
        Generate a JWT token.
        
        Args:
            user_id: User ID to include in token
            scope: Token permissions scope
            hours: Token validity in hours
            token_type: Type of token
            
        Returns:
            JWT token string
        """
        secret_key = os.environ.get('JWT_SECRET_KEY', 'default-secret-change-me')
        
        payload = {
            'user_id': user_id,
            'scope': scope,
            'type': token_type,
            'iat': datetime.now(timezone.utc),
            'exp': datetime.now(timezone.utc) + timedelta(hours=hours)
        }
        
        return jwt.encode(payload, secret_key, algorithm='HS256')
    
    @staticmethod
    def decode_jwt_token(token: str) -> Dict[str, Any]:
        """
        Decode and validate a JWT token.
        
        Args:
            token: JWT token string
            
        Returns:
            Token payload dictionary
            
        Raises:
            jwt.ExpiredSignatureError: If token has expired
            jwt.InvalidTokenError: If token is invalid
        """
        secret_key = os.environ.get('JWT_SECRET_KEY', 'default-secret-change-me')
        return jwt.decode(token, secret_key, algorithms=['HS256'])
    
    @staticmethod
    def hash_token(token: str) -> str:
        """Create SHA-256 hash of token for storage."""
        return hashlib.sha256(token.encode()).hexdigest()
    
    @classmethod
    def create_token(cls, user_id: int, scope: str = 'read', 
                    hours: int = 1, token_type: str = 'access',
                    client_id: str = None) -> tuple[str, 'AccessToken']:
        """
        Create a new access token.
        
        Args:
            user_id: User ID
            scope: Token permissions
            hours: Token validity in hours
            token_type: Type of token
            client_id: Client application ID
            
        Returns:
            Tuple of (token_string, AccessToken_instance)
        """
        token = cls.generate_jwt_token(user_id, scope, hours, token_type)
        token_hash = cls.hash_token(token)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        
        token_record = cls.create(
            user_id=user_id,
            token_hash=token_hash,
            token_type=token_type,
            scope=scope,
            expires_at=expires_at,
            client_id=client_id
        )
        
        return token, token_record
    
    @classmethod
    def validate_token(cls, token: str) -> Optional['AccessToken']:
        """
        Validate a token and return the token record if valid.
        
        Args:
            token: JWT token string
            
        Returns:
            AccessToken instance if valid, None otherwise
        """
        try:
            # Decode JWT to check expiration and validity
            payload = cls.decode_jwt_token(token)
            
            # Get token record from database
            token_hash = cls.hash_token(token)
            token_record = cls.find_one_by(token_hash=token_hash)
            
            if not token_record or token_record.is_revoked:
                return None
            
            # Update last used time
            token_record.last_used = datetime.now(timezone.utc)
            session.commit()
            
            return token_record
            
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return None
    
    def revoke(self):
        """Revoke the token."""
        self.is_revoked = True
        session.commit()
    
    @classmethod
    def cleanup_expired(cls):
        """Clean up expired tokens."""
        expired_count = session.query(cls).filter(
            cls.expires_at < datetime.now(timezone.utc)
        ).delete()
        session.commit()
        return expired_count
    
    @classmethod
    def revoke_user_tokens(cls, user_id: int, token_type: str = None):
        """Revoke all tokens for a user."""
        query = session.query(cls).filter(
            cls.user_id == user_id,
            cls.is_revoked == False
        )
        
        if token_type:
            query = query.filter(cls.token_type == token_type)
        
        tokens = query.all()
        for token in tokens:
            token.revoke()
        
        return len(tokens)

class PasswordReset(EnhancedBaseModel):
    """
    Password reset token management.
    
    Attributes:
        user_id: Foreign key to Users table
        token: Secure reset token
        expires_at: When the token expires
        is_used: Whether the token has been used
        ip_address: IP address that requested the reset
        used_at: When the token was used
    """
    __tablename__ = 'password_resets'
    
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    token = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    ip_address = Column(String(45), nullable=True)
    used_at = Column(DateTime, nullable=True)
    
    # Relationship to user
    user = relationship('Users', backref='password_resets')
    
    def __init__(self, **kwargs):
        # Generate token if not provided
        if 'token' not in kwargs:
            kwargs['token'] = self.generate_reset_token()
        
        # Set default expiration (1 hour)
        if 'expires_at' not in kwargs:
            kwargs['expires_at'] = datetime.now(timezone.utc) + timedelta(hours=1)
        
        super().__init__(**kwargs)
    
    @staticmethod
    def generate_reset_token() -> str:
        """Generate a secure password reset token."""
        return secrets.token_urlsafe(32)
    
    def is_expired(self) -> bool:
        """Check if the token has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    def is_valid(self) -> bool:
        """Check if the token is valid (not used and not expired)."""
        return not self.is_used and not self.is_expired()
    
    def use_token(self):
        """Mark the token as used."""
        self.is_used = True
        self.used_at = datetime.now(timezone.utc)
        session.commit()
    
    @classmethod
    def create_reset_token(cls, user_id: int, ip_address: str = None, hours: int = 1):
        """
        Create a new password reset token.
        
        Args:
            user_id: User ID
            ip_address: IP address requesting the reset
            hours: Token validity in hours
            
        Returns:
            PasswordReset instance
        """
        # Invalidate any existing tokens for this user
        existing_tokens = cls.find_by(user_id=user_id, is_used=False)
        for token in existing_tokens:
            token.use_token()
        
        expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        
        return cls.create(
            user_id=user_id,
            ip_address=ip_address,
            expires_at=expires_at
        )
    
    @classmethod
    def get_by_token(cls, token: str):
        """Get password reset by token."""
        return cls.find_one_by(token=token)
    
    @classmethod
    def cleanup_expired(cls):
        """Clean up expired tokens."""
        expired_count = session.query(cls).filter(
            cls.expires_at < datetime.now(timezone.utc)
        ).delete()
        session.commit()
        return expired_count

class OAuthProvider(EnhancedBaseModel):
    """
    OAuth provider integration support.
    
    Attributes:
        user_id: Foreign key to Users table
        provider: OAuth provider name (google, github, discord, etc.)
        provider_user_id: User ID from the OAuth provider
        access_token: OAuth access token (encrypted)
        refresh_token: OAuth refresh token (encrypted)
        token_expires_at: When the OAuth token expires
        scope: OAuth permissions granted
        provider_data: Additional data from the provider
        last_login: Last time this OAuth account was used to login
    """
    __tablename__ = 'oauth_providers'
    
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    provider = Column(String(50), nullable=False, index=True)  # google, github, discord
    provider_user_id = Column(String(255), nullable=False)  # User ID from provider
    access_token = Column(Text, nullable=True)  # Should be encrypted in production
    refresh_token = Column(Text, nullable=True)  # Should be encrypted in production
    token_expires_at = Column(DateTime, nullable=True)
    scope = Column(String(255), nullable=True)
    provider_data = Column(JSON, default=dict)  # Additional provider data
    last_login = Column(DateTime, nullable=True)
    
    # Relationship to user
    user = relationship('Users', backref='oauth_providers')
    
    def is_token_expired(self) -> bool:
        """Check if the OAuth token has expired."""
        if not self.token_expires_at:
            return False
        return datetime.now(timezone.utc) > self.token_expires_at
    
    def update_login(self):
        """Update the last login time."""
        self.last_login = datetime.now(timezone.utc)
        session.commit()
    
    @classmethod
    def find_by_provider(cls, provider: str, provider_user_id: str):
        """Find OAuth account by provider and provider user ID."""
        return cls.find_one_by(provider=provider, provider_user_id=provider_user_id)
    
    @classmethod
    def create_or_update(cls, user_id: int, provider: str, provider_user_id: str,
                        access_token: str = None, refresh_token: str = None,
                        expires_at: datetime = None, scope: str = None,
                        provider_data: Dict = None):
        """
        Create or update OAuth provider record.
        
        Args:
            user_id: User ID
            provider: Provider name
            provider_user_id: Provider's user ID
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            expires_at: Token expiration time
            scope: OAuth scope
            provider_data: Additional provider data
            
        Returns:
            OAuthProvider instance
        """
        existing = cls.find_by_provider(provider, provider_user_id)
        
        if existing:
            # Update existing record
            existing.update(
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=expires_at,
                scope=scope,
                provider_data=provider_data or {},
                last_login=datetime.now(timezone.utc)
            )
            return existing
        else:
            # Create new record
            return cls.create(
                user_id=user_id,
                provider=provider,
                provider_user_id=provider_user_id,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=expires_at,
                scope=scope,
                provider_data=provider_data or {},
                last_login=datetime.now(timezone.utc)
            )

class SecurityAudit(EnhancedBaseModel):
    """
    Security audit log for tracking authentication events.
    
    Attributes:
        user_id: Foreign key to Users table (nullable for anonymous events)
        event_type: Type of security event
        event_data: Additional event data
        ip_address: IP address of the event
        user_agent: Browser user agent
        success: Whether the event was successful
        risk_score: Risk assessment score (0-100)
        location: Geographical location if available
    """
    __tablename__ = 'security_audits'
    
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    event_type = Column(String(50), nullable=False, index=True)  # login, logout, failed_login, etc.
    event_data = Column(JSON, default=dict)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False)
    risk_score = Column(Integer, default=0, nullable=False)  # 0-100
    location = Column(JSON, default=dict)  # Country, city, etc.
    
    # Relationship to user
    user = relationship('Users', backref='security_audits')
    
    @classmethod
    def log_event(cls, event_type: str, success: bool, user_id: int = None,
                  ip_address: str = None, user_agent: str = None,
                  event_data: Dict = None, risk_score: int = 0,
                  location: Dict = None):
        """
        Log a security event.
        
        Args:
            event_type: Type of event
            success: Whether the event was successful
            user_id: User ID (if applicable)
            ip_address: IP address
            user_agent: Browser user agent
            event_data: Additional event data
            risk_score: Risk assessment score
            location: Geographical location data
            
        Returns:
            SecurityAudit instance
        """
        return cls.create(
            user_id=user_id,
            event_type=event_type,
            success=success,
            ip_address=ip_address,
            user_agent=user_agent,
            event_data=event_data or {},
            risk_score=risk_score,
            location=location or {}
        )
    
    @classmethod
    def get_failed_attempts(cls, ip_address: str = None, user_id: int = None, 
                           hours: int = 1) -> List['SecurityAudit']:
        """
        Get failed login attempts within a time window.
        
        Args:
            ip_address: Filter by IP address
            user_id: Filter by user ID
            hours: Time window in hours
            
        Returns:
            List of SecurityAudit records
        """
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        query = session.query(cls).filter(
            cls.event_type.in_(['login', 'api_auth']),
            cls.success == False,
            cls.created_at >= since
        )
        
        if ip_address:
            query = query.filter(cls.ip_address == ip_address)
        
        if user_id:
            query = query.filter(cls.user_id == user_id)
        
        return query.all()
    
    @classmethod
    def calculate_risk_score(cls, user_id: int = None, ip_address: str = None) -> int:
        """
        Calculate risk score based on recent activity.
        
        Args:
            user_id: User ID
            ip_address: IP address
            
        Returns:
            Risk score (0-100)
        """
        score = 0
        
        # Check failed attempts in last hour
        failed_attempts = cls.get_failed_attempts(ip_address, user_id, hours=1)
        score += min(len(failed_attempts) * 10, 50)  # Max 50 points for failed attempts
        
        # Check for suspicious patterns (could be enhanced)
        if len(failed_attempts) > 5:
            score += 30
        
        # Check for new IP/location (would need additional data)
        # This is a placeholder for more sophisticated risk assessment
        
        return min(score, 100)

# Add some basic validators to enhance security
def validate_password_strength(password: str) -> bool:
    """Validate password meets minimum security requirements."""
    if not password or len(password) < 8:
        return False
    
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password)
    
    return sum([has_upper, has_lower, has_digit, has_special]) >= 3

def validate_email_format(email: str) -> bool:
    """Basic email format validation."""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email)) if email else False