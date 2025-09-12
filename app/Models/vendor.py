"""
Vendor integration models for third-party services and plugins.

This module provides a framework for integrating third-party services including:
- Plugin management and configuration
- API client abstractions
- Vendor-specific data storage
- Rate limiting and quota management
- Error tracking and retry logic
"""

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Union, Callable
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship
from enum import Enum

from .base_model import EnhancedBaseModel, ValidationError
from database.db import session

class VendorStatus(Enum):
    """Vendor integration status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    ERROR = "error"
    DEPRECATED = "deprecated"

class VendorType(Enum):
    """Types of vendor integrations."""
    PAYMENT = "payment"
    EMAIL = "email"
    SMS = "sms"
    SOCIAL = "social"
    ANALYTICS = "analytics"
    STORAGE = "storage"
    NOTIFICATION = "notification"
    API = "api"
    WEBHOOK = "webhook"
    OTHER = "other"

class Vendor(EnhancedBaseModel):
    """
    Vendor/Third-party service configuration and management.
    
    Attributes:
        name: Vendor name (unique identifier)
        display_name: Human-readable name
        vendor_type: Type of vendor service
        description: Vendor description
        website_url: Vendor website
        documentation_url: API documentation URL
        status: Current status of the integration
        api_version: API version being used
        configuration: Vendor-specific configuration
        credentials: Encrypted credentials (API keys, secrets, etc.)
        rate_limits: Rate limiting configuration
        webhook_config: Webhook configuration
        is_enabled: Whether vendor is currently enabled
        last_health_check: Last time vendor health was checked
        health_status: Current health status
    """
    __tablename__ = 'vendors'
    
    name = Column(String(100), unique=True, nullable=False, index=True)
    display_name = Column(String(200), nullable=False)
    vendor_type = Column(String(50), nullable=False)  # Use VendorType enum values
    description = Column(Text, nullable=True)
    website_url = Column(String(500), nullable=True)
    documentation_url = Column(String(500), nullable=True)
    status = Column(String(20), default=VendorStatus.INACTIVE.value, nullable=False)
    api_version = Column(String(50), nullable=True)
    configuration = Column(JSON, default=dict)
    credentials = Column(JSON, default=dict)  # Should be encrypted in production
    rate_limits = Column(JSON, default=dict)
    webhook_config = Column(JSON, default=dict)
    is_enabled = Column(Boolean, default=False, nullable=False)
    last_health_check = Column(DateTime, nullable=True)
    health_status = Column(String(20), default='unknown', nullable=False)
    
    def __repr__(self):
        return f"<Vendor(name={self.name}, type={self.vendor_type}, status={self.status})>"
    
    def enable(self):
        """Enable the vendor integration."""
        self.is_enabled = True
        self.status = VendorStatus.ACTIVE.value
        session.commit()
    
    def disable(self):
        """Disable the vendor integration."""
        self.is_enabled = False
        self.status = VendorStatus.INACTIVE.value
        session.commit()
    
    def set_maintenance(self):
        """Set vendor to maintenance mode."""
        self.status = VendorStatus.MAINTENANCE.value
        session.commit()
    
    def set_error(self):
        """Set vendor to error state."""
        self.status = VendorStatus.ERROR.value
        session.commit()
    
    def update_health_status(self, status: str, details: Dict = None):
        """Update vendor health status."""
        self.health_status = status
        self.last_health_check = datetime.now(timezone.utc)
        
        if details:
            if not self.configuration:
                self.configuration = {}
            self.configuration['last_health_details'] = details
        
        session.commit()
    
    def get_credential(self, key: str) -> Optional[str]:
        """Get a credential value (decrypt if necessary)."""
        if not self.credentials:
            return None
        # In production, this should decrypt the value
        return self.credentials.get(key)
    
    def set_credential(self, key: str, value: str):
        """Set a credential value (encrypt if necessary)."""
        if not self.credentials:
            self.credentials = {}
        # In production, this should encrypt the value
        self.credentials[key] = value
        session.commit()
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        if not self.configuration:
            return default
        return self.configuration.get(key, default)
    
    def set_config(self, key: str, value: Any):
        """Set configuration value."""
        if not self.configuration:
            self.configuration = {}
        self.configuration[key] = value
        session.commit()
    
    def get_rate_limit(self, endpoint: str = 'default') -> Dict[str, Any]:
        """Get rate limit configuration for an endpoint."""
        if not self.rate_limits:
            return {'requests_per_minute': 60, 'requests_per_hour': 1000}
        return self.rate_limits.get(endpoint, self.rate_limits.get('default', {}))
    
    def set_rate_limit(self, endpoint: str, requests_per_minute: int, requests_per_hour: int):
        """Set rate limit for an endpoint."""
        if not self.rate_limits:
            self.rate_limits = {}
        self.rate_limits[endpoint] = {
            'requests_per_minute': requests_per_minute,
            'requests_per_hour': requests_per_hour
        }
        session.commit()
    
    @classmethod
    def get_by_name(cls, name: str) -> Optional['Vendor']:
        """Get vendor by name."""
        return cls.find_one_by(name=name)
    
    @classmethod
    def get_by_type(cls, vendor_type: str) -> List['Vendor']:
        """Get all vendors of a specific type."""
        return cls.find_by(vendor_type=vendor_type)
    
    @classmethod
    def get_enabled(cls) -> List['Vendor']:
        """Get all enabled vendors."""
        return cls.find_by(is_enabled=True, is_deleted=False)
    
    @classmethod
    def create_vendor(cls, name: str, display_name: str, vendor_type: str,
                     description: str = None, **kwargs) -> 'Vendor':
        """
        Create a new vendor integration.
        
        Args:
            name: Unique vendor name
            display_name: Human-readable name
            vendor_type: Type of vendor
            description: Vendor description
            **kwargs: Additional vendor attributes
            
        Returns:
            Vendor instance
        """
        return cls.create(
            name=name,
            display_name=display_name,
            vendor_type=vendor_type,
            description=description,
            **kwargs
        )

class VendorApiCall(EnhancedBaseModel):
    """
    Track API calls to vendor services for monitoring and rate limiting.
    
    Attributes:
        vendor_id: Foreign key to Vendor
        endpoint: API endpoint called
        method: HTTP method (GET, POST, etc.)
        request_data: Request payload (sanitized)
        response_status: HTTP response status code
        response_time: Response time in milliseconds
        error_message: Error message if call failed
        user_id: User who initiated the call (if applicable)
        rate_limit_remaining: Rate limit remaining after call
        quota_used: API quota used
        retry_count: Number of retries attempted
    """
    __tablename__ = 'vendor_api_calls'
    
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=False, index=True)
    endpoint = Column(String(500), nullable=False)
    method = Column(String(10), nullable=False)
    request_data = Column(JSON, default=dict)  # Sanitized request data
    response_status = Column(Integer, nullable=True)
    response_time = Column(Float, nullable=True)  # Milliseconds
    error_message = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    rate_limit_remaining = Column(Integer, nullable=True)
    quota_used = Column(Float, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    
    # Relationships
    vendor = relationship('Vendor', backref='api_calls')
    user = relationship('Users', backref='vendor_api_calls')
    
    def __repr__(self):
        return f"<VendorApiCall(vendor={self.vendor.name if self.vendor else 'Unknown'}, endpoint={self.endpoint}, status={self.response_status})>"
    
    @classmethod
    def log_call(cls, vendor_id: int, endpoint: str, method: str,
                request_data: Dict = None, response_status: int = None,
                response_time: float = None, error_message: str = None,
                user_id: int = None, rate_limit_remaining: int = None,
                quota_used: float = None, retry_count: int = 0) -> 'VendorApiCall':
        """
        Log an API call to a vendor service.
        
        Args:
            vendor_id: Vendor ID
            endpoint: API endpoint
            method: HTTP method
            request_data: Request payload (will be sanitized)
            response_status: HTTP response status
            response_time: Response time in milliseconds
            error_message: Error message if failed
            user_id: User who made the call
            rate_limit_remaining: Rate limit remaining
            quota_used: API quota used
            retry_count: Number of retries
            
        Returns:
            VendorApiCall instance
        """
        # Sanitize request data (remove sensitive information)
        sanitized_data = cls._sanitize_request_data(request_data or {})
        
        return cls.create(
            vendor_id=vendor_id,
            endpoint=endpoint,
            method=method,
            request_data=sanitized_data,
            response_status=response_status,
            response_time=response_time,
            error_message=error_message,
            user_id=user_id,
            rate_limit_remaining=rate_limit_remaining,
            quota_used=quota_used,
            retry_count=retry_count
        )
    
    @staticmethod
    def _sanitize_request_data(data: Dict) -> Dict:
        """Remove sensitive data from request data."""
        sensitive_keys = [
            'password', 'token', 'api_key', 'secret', 'credential',
            'authorization', 'auth', 'key', 'private_key'
        ]
        
        sanitized = {}
        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                sanitized[key] = '[REDACTED]'
            elif isinstance(value, dict):
                sanitized[key] = cls._sanitize_request_data(value)
            else:
                sanitized[key] = value
        
        return sanitized
    
    @classmethod
    def get_vendor_stats(cls, vendor_id: int, hours: int = 24) -> Dict[str, Any]:
        """Get API call statistics for a vendor."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        calls = session.query(cls).filter(
            cls.vendor_id == vendor_id,
            cls.created_at >= since
        ).all()
        
        total_calls = len(calls)
        successful_calls = len([c for c in calls if c.response_status and c.response_status < 400])
        failed_calls = total_calls - successful_calls
        
        avg_response_time = None
        if calls:
            response_times = [c.response_time for c in calls if c.response_time]
            if response_times:
                avg_response_time = sum(response_times) / len(response_times)
        
        return {
            'total_calls': total_calls,
            'successful_calls': successful_calls,
            'failed_calls': failed_calls,
            'success_rate': (successful_calls / total_calls * 100) if total_calls > 0 else 0,
            'average_response_time': avg_response_time,
            'period_hours': hours
        }

class VendorRateLimit(EnhancedBaseModel):
    """
    Track rate limiting for vendor API calls.
    
    Attributes:
        vendor_id: Foreign key to Vendor
        endpoint: API endpoint (or 'global' for overall limits)
        user_id: User ID (for per-user limits, null for global limits)
        minute_count: Requests in current minute
        hour_count: Requests in current hour
        day_count: Requests in current day
        last_reset_minute: Last minute counter reset
        last_reset_hour: Last hour counter reset
        last_reset_day: Last day counter reset
        is_blocked: Whether requests are currently blocked
        blocked_until: When blocking expires
    """
    __tablename__ = 'vendor_rate_limits'
    
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=False, index=True)
    endpoint = Column(String(500), default='global', nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    minute_count = Column(Integer, default=0, nullable=False)
    hour_count = Column(Integer, default=0, nullable=False)
    day_count = Column(Integer, default=0, nullable=False)
    last_reset_minute = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_reset_hour = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_reset_day = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    is_blocked = Column(Boolean, default=False, nullable=False)
    blocked_until = Column(DateTime, nullable=True)
    
    # Relationships
    vendor = relationship('Vendor', backref='rate_limits')
    user = relationship('Users', backref='vendor_rate_limits')
    
    def reset_if_needed(self):
        """Reset counters if time periods have passed."""
        now = datetime.now(timezone.utc)
        
        # Reset minute counter
        if (now - self.last_reset_minute).total_seconds() >= 60:
            self.minute_count = 0
            self.last_reset_minute = now
        
        # Reset hour counter
        if (now - self.last_reset_hour).total_seconds() >= 3600:
            self.hour_count = 0
            self.last_reset_hour = now
        
        # Reset day counter
        if (now - self.last_reset_day).total_seconds() >= 86400:
            self.day_count = 0
            self.last_reset_day = now
        
        # Check if blocking has expired
        if self.is_blocked and self.blocked_until and now >= self.blocked_until:
            self.is_blocked = False
            self.blocked_until = None
        
        session.commit()
    
    def increment_and_check(self) -> bool:
        """
        Increment counters and check if rate limit is exceeded.
        
        Returns:
            True if request is allowed, False if rate limited
        """
        self.reset_if_needed()
        
        if self.is_blocked:
            return False
        
        # Get rate limits from vendor configuration
        vendor = self.vendor
        limits = vendor.get_rate_limit(self.endpoint)
        
        # Check limits
        if self.minute_count >= limits.get('requests_per_minute', 60):
            self._block_temporarily(minutes=1)
            return False
        
        if self.hour_count >= limits.get('requests_per_hour', 1000):
            self._block_temporarily(hours=1)
            return False
        
        if self.day_count >= limits.get('requests_per_day', 10000):
            self._block_temporarily(hours=24)
            return False
        
        # Increment counters
        self.minute_count += 1
        self.hour_count += 1
        self.day_count += 1
        session.commit()
        
        return True
    
    def _block_temporarily(self, minutes: int = 0, hours: int = 0):
        """Block requests temporarily."""
        self.is_blocked = True
        self.blocked_until = datetime.now(timezone.utc) + timedelta(minutes=minutes, hours=hours)
        session.commit()
    
    @classmethod
    def check_rate_limit(cls, vendor_id: int, endpoint: str = 'global', 
                        user_id: int = None) -> bool:
        """
        Check if request is within rate limits.
        
        Args:
            vendor_id: Vendor ID
            endpoint: API endpoint
            user_id: User ID (optional)
            
        Returns:
            True if request is allowed, False if rate limited
        """
        # Get or create rate limit record
        rate_limit = cls.find_one_by(
            vendor_id=vendor_id,
            endpoint=endpoint,
            user_id=user_id
        )
        
        if not rate_limit:
            rate_limit = cls.create(
                vendor_id=vendor_id,
                endpoint=endpoint,
                user_id=user_id
            )
        
        return rate_limit.increment_and_check()

class VendorWebhook(EnhancedBaseModel):
    """
    Manage webhook configurations and logs for vendor integrations.
    
    Attributes:
        vendor_id: Foreign key to Vendor
        webhook_url: URL to receive webhooks
        events: List of events to subscribe to
        secret: Webhook verification secret
        is_active: Whether webhook is active
        last_received: Last time a webhook was received
        total_received: Total webhooks received
        failed_count: Number of failed webhook deliveries
        retry_config: Retry configuration for failed webhooks
    """
    __tablename__ = 'vendor_webhooks'
    
    vendor_id = Column(Integer, ForeignKey('vendors.id'), nullable=False, index=True)
    webhook_url = Column(String(1000), nullable=False)
    events = Column(JSON, default=list)  # List of event types
    secret = Column(String(255), nullable=True)  # Webhook verification secret
    is_active = Column(Boolean, default=True, nullable=False)
    last_received = Column(DateTime, nullable=True)
    total_received = Column(Integer, default=0, nullable=False)
    failed_count = Column(Integer, default=0, nullable=False)
    retry_config = Column(JSON, default=dict)
    
    # Relationship
    vendor = relationship('Vendor', backref='webhooks')
    
    def process_webhook(self, event_type: str, payload: Dict) -> bool:
        """
        Process an incoming webhook.
        
        Args:
            event_type: Type of event
            payload: Webhook payload
            
        Returns:
            True if processed successfully, False otherwise
        """
        if not self.is_active:
            return False
        
        if self.events and event_type not in self.events:
            return False  # Not subscribed to this event
        
        try:
            # Log the webhook
            VendorWebhookLog.create(
                webhook_id=self.id,
                event_type=event_type,
                payload=payload,
                status='received'
            )
            
            # Update statistics
            self.last_received = datetime.now(timezone.utc)
            self.total_received += 1
            session.commit()
            
            return True
            
        except Exception as e:
            self.failed_count += 1
            session.commit()
            
            # Log the failure
            VendorWebhookLog.create(
                webhook_id=self.id,
                event_type=event_type,
                payload=payload,
                status='failed',
                error_message=str(e)
            )
            
            return False

class VendorWebhookLog(EnhancedBaseModel):
    """
    Log webhook deliveries and responses.
    
    Attributes:
        webhook_id: Foreign key to VendorWebhook
        event_type: Type of webhook event
        payload: Webhook payload (sanitized)
        status: Processing status (received, processed, failed, etc.)
        response_data: Response data if applicable
        error_message: Error message if processing failed
        processing_time: Time taken to process webhook
        retry_count: Number of retry attempts
    """
    __tablename__ = 'vendor_webhook_logs'
    
    webhook_id = Column(Integer, ForeignKey('vendor_webhooks.id'), nullable=False, index=True)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSON, default=dict)
    status = Column(String(50), nullable=False)
    response_data = Column(JSON, default=dict)
    error_message = Column(Text, nullable=True)
    processing_time = Column(Float, nullable=True)  # Milliseconds
    retry_count = Column(Integer, default=0, nullable=False)
    
    # Relationship
    webhook = relationship('VendorWebhook', backref='logs')

# Plugin system base classes
class VendorPlugin:
    """
    Base class for vendor plugins.
    
    All vendor integrations should inherit from this class to ensure
    consistent interface and functionality.
    """
    
    def __init__(self, vendor: Vendor):
        self.vendor = vendor
        self.client = None
    
    def initialize(self) -> bool:
        """Initialize the plugin with vendor configuration."""
        raise NotImplementedError("Subclasses must implement initialize()")
    
    def health_check(self) -> Dict[str, Any]:
        """Perform health check on the vendor service."""
        raise NotImplementedError("Subclasses must implement health_check()")
    
    def get_client(self):
        """Get the vendor API client."""
        if not self.client:
            self.client = self._create_client()
        return self.client
    
    def _create_client(self):
        """Create vendor-specific API client."""
        raise NotImplementedError("Subclasses must implement _create_client()")
    
    def make_request(self, method: str, endpoint: str, data: Dict = None,
                    user_id: int = None) -> Dict[str, Any]:
        """
        Make a rate-limited request to the vendor API.
        
        Args:
            method: HTTP method
            endpoint: API endpoint
            data: Request data
            user_id: User making the request
            
        Returns:
            Response data
        """
        # Check rate limits
        if not VendorRateLimit.check_rate_limit(self.vendor.id, endpoint, user_id):
            raise ValidationError('rate_limit', 'Rate limit exceeded')
        
        start_time = time.time()
        response_status = None
        error_message = None
        
        try:
            # Make the actual request (implement in subclass)
            response = self._make_api_request(method, endpoint, data)
            response_status = getattr(response, 'status_code', 200)
            return response
            
        except Exception as e:
            error_message = str(e)
            raise
            
        finally:
            # Log the API call
            response_time = (time.time() - start_time) * 1000  # Convert to milliseconds
            VendorApiCall.log_call(
                vendor_id=self.vendor.id,
                endpoint=endpoint,
                method=method,
                request_data=data,
                response_status=response_status,
                response_time=response_time,
                error_message=error_message,
                user_id=user_id
            )
    
    def _make_api_request(self, method: str, endpoint: str, data: Dict = None):
        """Make the actual API request (implement in subclass)."""
        raise NotImplementedError("Subclasses must implement _make_api_request()")

# Default vendor configurations
DEFAULT_VENDORS = [
    {
        'name': 'stripe',
        'display_name': 'Stripe',
        'vendor_type': VendorType.PAYMENT.value,
        'description': 'Payment processing service',
        'website_url': 'https://stripe.com',
        'documentation_url': 'https://stripe.com/docs/api',
        'rate_limits': {
            'default': {'requests_per_minute': 100, 'requests_per_hour': 1000}
        }
    },
    {
        'name': 'sendgrid',
        'display_name': 'SendGrid',
        'vendor_type': VendorType.EMAIL.value,
        'description': 'Email delivery service',
        'website_url': 'https://sendgrid.com',
        'documentation_url': 'https://docs.sendgrid.com',
        'rate_limits': {
            'default': {'requests_per_minute': 600, 'requests_per_hour': 10000}
        }
    },
    {
        'name': 'twilio',
        'display_name': 'Twilio',
        'vendor_type': VendorType.SMS.value,
        'description': 'SMS and voice communication',
        'website_url': 'https://twilio.com',
        'documentation_url': 'https://www.twilio.com/docs',
        'rate_limits': {
            'default': {'requests_per_minute': 60, 'requests_per_hour': 1000}
        }
    }
]

def create_default_vendors():
    """Create default vendor configurations if they don't exist."""
    created = []
    for vendor_config in DEFAULT_VENDORS:
        existing = Vendor.get_by_name(vendor_config['name'])
        if not existing:
            vendor = Vendor.create_vendor(**vendor_config)
            created.append(vendor)
    return created