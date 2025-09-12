# MVC Model Enhancements Documentation

## Overview

The MVC framework has been significantly enhanced with enterprise-level features that address all TODO items from the original README. These improvements make the framework production-ready with comprehensive authentication, file management, error handling, and vendor integration capabilities.

## Enhanced Base Model Features

### Validation Framework
```python
from app.Models.users import Users
from app.Models.base_model import ValidationError

# Add custom validators
Users.add_validator('email', 
                   lambda email: '@' in email, 
                   "Email must contain @ symbol")

# Validation is automatic on create/update
try:
    user = Users.create_user(name="John", email="invalid-email", password="pass123")
except ValidationError as e:
    print(f"Validation failed: {e.field} - {e.message}")
```

### Model Caching
```python
from app.Models.base_model import model_cache

# Enable/disable caching
model_cache.enable()
model_cache.disable()

# Automatic caching on get operations
user = Users.get(1, use_cache=True)  # Cached
updated_user = Users.get(1, use_cache=False)  # Fresh from DB
```

### Soft Delete & Audit Trails
```python
# Soft delete with audit information
user.soft_delete(user_id="admin_123")

# All models have automatic audit fields
print(f"Created: {user.created_at} by {user.created_by}")
print(f"Updated: {user.updated_at} by {user.updated_by}")

# Query including deleted records
deleted_users = Users.only_deleted().all()
all_users = Users.with_deleted().all()

# Restore soft deleted records
user.restore()
```

### JSON Serialization
```python
# Convert to dictionary/JSON
user_dict = user.to_dict(exclude=['password_hash'])
user_json = user.to_json(include_relationships=True)

# Create from dictionary/JSON
user_data = {'name': 'John', 'email': 'john@example.com', 'password': 'secure123'}
new_user = Users.from_dict(user_data)
```

### Model Events
```python
def log_user_creation(user, **kwargs):
    print(f"User {user.email} was created")

# Register event handlers
Users.add_event_handler(ModelEvents.AFTER_CREATE, log_user_creation)
```

## Authentication System

### User Session Management
```python
from app.Models.auth import UserSession

# Create user session
session = UserSession.create_session(
    user_id=user.id,
    ip_address="192.168.1.1",
    user_agent="Mozilla/5.0...",
    hours=24
)

# Validate session
if session.is_valid():
    session.update_activity(ip_address="192.168.1.2")

# Terminate session
session.terminate("manual_logout")

# Cleanup expired sessions
UserSession.cleanup_expired()
```

### JWT Token Management
```python
from app.Models.auth import AccessToken

# Create access token
token_string, token_record = AccessToken.create_token(
    user_id=user.id,
    scope='read write',
    hours=1
)

# Validate token
validated_token = AccessToken.validate_token(token_string)
if validated_token:
    print(f"Valid token for user {validated_token.user_id}")

# Revoke token
token_record.revoke()
```

### Password Reset
```python
from app.Models.auth import PasswordReset

# Create reset token
reset_token = PasswordReset.create_reset_token(
    user_id=user.id,
    ip_address="192.168.1.1"
)

# Validate and use token
if reset_token.is_valid():
    # Allow password reset
    reset_token.use_token()
```

### OAuth Integration
```python
from app.Models.auth import OAuthProvider

# Store OAuth provider data
oauth = OAuthProvider.create_or_update(
    user_id=user.id,
    provider='google',
    provider_user_id='google_123456',
    access_token='oauth_access_token',
    scope='profile email'
)

# Find user by OAuth provider
user = OAuthProvider.find_by_provider('google', 'google_123456')
```

### Security Audit Logging
```python
from app.Models.auth import SecurityAudit

# Log security events
SecurityAudit.log_event(
    event_type='login',
    success=True,
    user_id=user.id,
    ip_address="192.168.1.1",
    risk_score=SecurityAudit.calculate_risk_score(user_id=user.id)
)

# Get failed login attempts
failed_attempts = SecurityAudit.get_failed_attempts(
    ip_address="192.168.1.1",
    hours=1
)
```

## Enhanced User Model

### Password Management
```python
# Create user with strong password validation
user = Users.create_user(
    name="John Doe",
    email="john@example.com",
    password="SecurePassword123!"  # Automatically validated and hashed
)

# Check password
if user.check_password("SecurePassword123!"):
    print("Password correct")

# Change password
user.set_password("NewSecurePassword456!")
```

### Account Security
```python
# Check if account is locked
if user.is_account_locked():
    print("Account is locked")

# Record failed login (auto-locks after 5 attempts)
user.record_failed_login()

# Record successful login
user.record_successful_login()

# Manually lock/unlock account
user.lock_account(hours=1)
user.unlock_account()
```

### External Service Integration
```python
# Set external service IDs
user.set_external_id('discord', '123456789')
user.set_external_id('github', 'username123')

# Get external IDs
discord_id = user.get_external_id('discord')

# Backward compatibility for Discord
user.discord_id = '987654321'
print(user.discord_id)
```

### Profile & Settings Management
```python
# Manage profile data
user.set_profile_data('bio', 'Software developer')
user.set_profile_data('avatar_url', 'https://...')
bio = user.get_profile_data('bio')

# Manage user settings
user.set_setting('theme', 'dark')
user.set_setting('notifications', True)
theme = user.get_setting('theme', 'light')  # Default to 'light'
```

### User Search & Management
```python
# Find users
user = Users.find_by_email('john@example.com')
user = Users.find_by_username('johndoe')
user = Users.find_by_external_id('discord', '123456789')

# Search users
results = Users.search_users('john', limit=10)

# Authenticate user
authenticated_user = Users.authenticate('john@example.com', 'password123')
```

## Enhanced Balance Model

### Multi-Currency Support
```python
from app.Models.balance import Balance

# Create balance with currency
balance = Balance.create_for_user(
    user_id=user.id,
    initial_amount=100.0,
    currency='USD'
)

# Get balances by currency
usd_balances = Balance.get_balances_by_currency('USD')
total_usd = Balance.get_total_system_balance()
```

### Transaction Management
```python
# Check balance sufficiency
if balance.is_sufficient(50.0):
    balance.withdraw(50.0, user_id="admin_123")

# Deposit funds
balance.deposit(25.0, user_id="user_456")

# Transfer between users
from_balance = Balance.get_by_user_id(user1.id)
to_balance = Balance.get_by_user_id(user2.id)
from_balance.transfer_to(to_balance, 25.0, user_id="user1")
```

### Balance Controls
```python
# Freeze/unfreeze balance
balance.freeze(user_id="admin_123")
balance.unfreeze(user_id="admin_123")

# Check transaction capability
if balance.can_transact():
    # Perform transaction
    pass

# Set minimum balance
balance.minimum_balance = 10.0
balance.withdraw(95.0)  # Will fail if it would go below minimum
```

## File Management System

### File Categories
```python
from app.Models.file_management import FileCategory

# Create file categories
image_category = FileCategory.create(
    name='images',
    description='Image files',
    allowed_extensions=['.jpg', '.png', '.gif'],
    max_file_size=10 * 1024 * 1024,  # 10MB
    storage_path='uploads/images/{year}/{month}'
)

# Check file compatibility
if image_category.is_extension_allowed('.jpg'):
    if image_category.is_size_allowed(file_size):
        # Allow upload
        pass
```

### File Upload & Management
```python
from app.Models.file_management import File

# Create file record
file_record = File.create_file_record(
    user_id=user.id,
    original_filename='document.pdf',
    file_path='uploads/docs/2024/12/document.pdf',
    file_size=1024000,
    category_name='documents',
    is_public=False,
    expires_hours=24
)

# Check file accessibility
if file_record.is_accessible_by_user(requesting_user.id):
    # Allow access
    file_record.increment_download_count()

# Get file URL
file_url = file_record.get_url('https://mysite.com')
```

### File Permissions
```python
from app.Models.file_management import FilePermission

# Grant file permission
permission = FilePermission.grant_permission(
    file_id=file_record.id,
    granted_by=owner.id,
    user_id=recipient.id,
    permission_type='read',
    expires_hours=24
)

# Check permission
if FilePermission.check_permission(file_record.id, user.id, 'read'):
    # Allow access
    permission.use_permission()
```

### File Versioning
```python
from app.Models.file_management import FileVersion

# Create new version
new_version = FileVersion.create_version(
    file_id=file_record.id,
    file_path='uploads/docs/2024/12/document_v2.pdf',
    file_size=1024500,
    change_description='Updated content'
)
```

## Vendor Integration Framework

### Vendor Configuration
```python
from app.Models.vendor import Vendor

# Create vendor integration
stripe_vendor = Vendor.create_vendor(
    name='stripe',
    display_name='Stripe Payment Processing',
    vendor_type='payment',
    description='Payment processing service'
)

# Configure vendor
stripe_vendor.set_credential('api_key', 'sk_live_...')
stripe_vendor.set_config('webhook_endpoint', 'https://mysite.com/stripe/webhook')
stripe_vendor.enable()
```

### API Call Tracking
```python
from app.Models.vendor import VendorApiCall

# Log API call
api_call = VendorApiCall.log_call(
    vendor_id=stripe_vendor.id,
    endpoint='/v1/charges',
    method='POST',
    request_data={'amount': 1000, 'currency': 'usd'},
    response_status=200,
    response_time=250,
    user_id=user.id
)

# Get vendor statistics
stats = VendorApiCall.get_vendor_stats(stripe_vendor.id, hours=24)
print(f"Success rate: {stats['success_rate']}%")
```

### Rate Limiting
```python
from app.Models.vendor import VendorRateLimit

# Check rate limits before API call
if VendorRateLimit.check_rate_limit(stripe_vendor.id, '/v1/charges', user.id):
    # Make API call
    pass
else:
    # Rate limited
    raise RateLimitError('Rate limit exceeded')
```

### Webhook Management
```python
from app.Models.vendor import VendorWebhook

# Configure webhook
webhook = VendorWebhook.create(
    vendor_id=stripe_vendor.id,
    webhook_url='https://mysite.com/webhooks/stripe',
    events=['payment_intent.succeeded', 'payment_intent.failed'],
    secret='webhook_secret'
)

# Process webhook
success = webhook.process_webhook(
    event_type='payment_intent.succeeded',
    payload={'id': 'pi_123', 'status': 'succeeded'}
)
```

### Custom Vendor Plugins
```python
from app.Models.vendor import VendorPlugin

class StripePlugin(VendorPlugin):
    def initialize(self):
        self.api_key = self.vendor.get_credential('api_key')
        return True
    
    def health_check(self):
        # Check Stripe API health
        return {'status': 'healthy', 'latency': 120}
    
    def _create_client(self):
        import stripe
        stripe.api_key = self.api_key
        return stripe
    
    def create_payment(self, amount, currency='usd'):
        return self.make_request(
            'POST', '/v1/payment_intents',
            data={'amount': amount, 'currency': currency}
        )
```

## Error Handling & Logging

### Custom Exceptions
```python
from app.Models.error_handling import (
    MvcError, ValidationError, AuthenticationError, 
    ResourceNotFoundError, BusinessLogicError
)

# Throw custom exceptions with context
raise ValidationError(
    field='email',
    message='Email already exists',
    value=email,
    context={'user_id': user.id}
)

raise ResourceNotFoundError(
    resource_type='User',
    resource_id=user_id,
    context={'requested_by': current_user.id}
)
```

### Error Logging
```python
from app.Models.error_handling import ErrorLog

# Errors are automatically logged
try:
    risky_operation()
except Exception as e:
    error_log = ErrorLog.log_error(
        error=e,
        user_id=current_user.id,
        url=request.url,
        ip_address=request.remote_addr,
        context={'operation': 'user_update'}
    )

# Get error summaries
summary = ErrorLog.get_error_summary(hours=24)
frequent_errors = ErrorLog.get_frequent_errors(limit=10)
```

### Activity Logging
```python
from app.Models.error_handling import ActivityLog

# Log user activities
ActivityLog.log_activity(
    activity_type='user_management',
    action='profile_updated',
    user_id=user.id,
    resource_type='user',
    resource_id=user.id,
    details={'fields_updated': ['name', 'email']},
    ip_address="192.168.1.1"
)

# Get user activity
activities = ActivityLog.get_user_activity(user.id, limit=50)
activity_summary = ActivityLog.get_activity_summary(hours=24)
```

### Performance Monitoring
```python
from app.Models.error_handling import PerformanceMetric

# Record performance metrics
PerformanceMetric.record_metric(
    metric_name='api_response_time',
    value=234.5,
    unit='ms',
    endpoint='/api/users',
    method='GET',
    user_id=user.id
)

# Get performance summaries
response_stats = PerformanceMetric.get_metric_summary('api_response_time', hours=24)
slow_endpoints = PerformanceMetric.get_slow_endpoints(limit=10)
```

### Context Managers
```python
from app.Models.error_handling import ErrorHandler, PerformanceMonitor

# Automatic error handling
with ErrorHandler(user_id=user.id, url='/api/endpoint'):
    potentially_failing_operation()

# Automatic performance monitoring
with PerformanceMonitor('database_query', user_id=user.id):
    slow_database_operation()
```

## Service Layer

### Repository Pattern
```python
from app.Models.service_layer import UserRepository, BalanceRepository

# Use repositories for data access
user_repo = UserRepository()

# Basic operations
user = user_repo.get_by_id(1)
users = user_repo.get_all()
new_user = user_repo.create(name='John', email='john@example.com')

# Specialized queries
user = user_repo.find_by_email('john@example.com')
results = user_repo.search_users('john', limit=10)

# Pagination
page_data = user_repo.paginate(page=1, per_page=20, is_admin=False)
print(f"Page {page_data['page']} of {page_data['pages']}")
```

### Service Classes
```python
from app.Models.service_layer import UserService, BalanceService

# User service operations
with UserService() as user_service:
    # Create user with business logic
    result = user_service.create_user(
        name='John Doe',
        email='john@example.com',
        password='SecurePassword123!',
        initial_balance=100.0
    )
    
    # Authenticate user
    auth_result = user_service.authenticate_user(
        email='john@example.com',
        password='SecurePassword123!',
        ip_address='192.168.1.1'
    )
    
    # Update profile with permissions
    update_result = user_service.update_user_profile(
        user_id=user.id,
        updates={'name': 'John Smith'},
        updating_user_id=current_user.id
    )

# Balance service operations
with BalanceService() as balance_service:
    # Transfer with comprehensive validation
    transfer_result = balance_service.transfer_balance(
        from_user_id=user1.id,
        to_user_id=user2.id,
        amount=50.0,
        initiated_by=user1.id,
        description='Payment for services'
    )
```

### Service Factory
```python
from app.Models.service_layer import ServiceFactory, get_user_service

# Get service instances
user_service = ServiceFactory.create_user_service()
balance_service = ServiceFactory.create_balance_service()

# Convenience functions
user_service = get_user_service()
```

## Usage Examples

### Complete User Registration Flow
```python
from app.Models.service_layer import get_user_service
from app.Models.auth import UserSession

def register_user(name, email, password, ip_address):
    with get_user_service() as service:
        # Create user with validation
        result = service.create_user(
            name=name,
            email=email,
            password=password,
            initial_balance=0.0
        )
        
        if result['success']:
            user = Users.get(result['user']['id'])
            
            # Create session
            session = UserSession.create_session(
                user_id=user.id,
                ip_address=ip_address,
                hours=24
            )
            
            return {
                'success': True,
                'user': user.to_dict(),
                'session_token': session.session_token
            }
        
        return result
```

### File Upload with Security
```python
from app.Models.service_layer import get_file_service

def upload_user_file(user_id, file_data, filename, category='documents'):
    with get_file_service() as service:
        return service.upload_file(
            user_id=user_id,
            file_data=file_data,
            filename=filename,
            category=category,
            is_public=False
        )
```

### Payment Processing with Logging
```python
def process_payment(user_id, amount, vendor='stripe'):
    # Get vendor
    vendor = Vendor.get_by_name(vendor)
    
    # Check rate limits
    if not VendorRateLimit.check_rate_limit(vendor.id, '/charges', user_id):
        raise RateLimitError('Too many payment attempts')
    
    # Log payment attempt
    ActivityLog.log_activity(
        activity_type='financial',
        action='payment_attempt',
        user_id=user_id,
        details={'amount': amount, 'vendor': vendor.name}
    )
    
    try:
        # Process payment (implement vendor-specific logic)
        result = vendor_plugin.create_payment(amount)
        
        # Log success
        VendorApiCall.log_call(
            vendor_id=vendor.id,
            endpoint='/charges',
            method='POST',
            response_status=200,
            user_id=user_id
        )
        
        return {'success': True, 'charge_id': result['id']}
        
    except Exception as e:
        # Log error
        ErrorLog.log_error(e, user_id=user_id, context={'amount': amount})
        return {'success': False, 'error': str(e)}
```

## Migration Guide

### From Basic Models to Enhanced Models

1. **Update Imports**:
```python
# Old
from app.Models.users import Users
from app.Models.balance import Balance

# New (additional features available)
from app.Models import Users, Balance
from app.Models.auth import UserSession, AccessToken
from app.Models.service_layer import get_user_service
```

2. **Replace Direct Model Usage with Services**:
```python
# Old
user = Users.create(name='John', email='john@example.com', password='password')

# New (with validation and logging)
service = get_user_service()
result = service.create_user(name='John', email='john@example.com', password='SecurePassword123!')
user = Users.get(result['user']['id'])
```

3. **Update Password Handling**:
```python
# Old
user.password = 'newpassword'

# New
user.set_password('NewSecurePassword123!')
```

4. **Add Error Handling**:
```python
# Old
try:
    risky_operation()
except Exception as e:
    print(f"Error: {e}")

# New
from app.Models.error_handling import ErrorHandler
with ErrorHandler(user_id=current_user.id):
    risky_operation()
```

The enhanced MVC framework maintains full backward compatibility while providing powerful new features for production applications.