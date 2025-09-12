"""
Models package for the Zeython framework.

This package contains all data models and related utilities for the application.
Models follow the Enhanced Active Record pattern with additional features for validation,
caching, audit trails, and relationships.

Key Components:
- BaseModel: Enhanced base class with validation, caching, and audit features
- Users: User management with authentication and profile data
- Balance: Financial balance tracking with enhanced security
- Auth: Authentication and session management (UserSession, AccessToken, PasswordReset, OAuthProvider, SecurityAudit)
- File Management: File upload and storage management (FileCategory, File, FilePermission, FileVersion)
- Vendor: Third-party service integration framework (Vendor, VendorApiCall, VendorRateLimit, VendorWebhook)
- Error Handling: Comprehensive error tracking and logging (ErrorLog, ActivityLog, PerformanceMetric)

Usage:
    from app.Models import Users, Balance
    from app.Models.auth import UserSession, AccessToken
    from app.Models.file_management import File, FileCategory
    from app.Models.vendor import Vendor, VendorPlugin
    from app.Models.error_handling import ErrorLog, ActivityLog
    
    user = Users.create_user(name="John", email="john@example.com", password="secret123")
    balance = user.get_balance()
    session = UserSession.create_session(user.id)
"""

# Import core models for easy access
from .users import Users
from .balance import Balance

# Import enhanced base model and validation utilities
from .base_model import EnhancedBaseModel, ValidationError, ModelEvents, model_cache

# Version info
__version__ = "2.1.0"
__author__ = "Zeython Contributors"

# Export commonly used models
__all__ = [
    # Core models
    "Users",
    "Balance",
    
    # Base model and utilities
    "EnhancedBaseModel",
    "ValidationError", 
    "ModelEvents",
    "model_cache",
]