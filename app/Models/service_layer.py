"""
Service layer for business logic and repository pattern implementation.

This module provides a clean separation between controllers and models,
implementing business logic in dedicated service classes and repository
pattern for data access abstraction.
"""

import os
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Type, Union
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import sessionmaker, scoped_session
from database.db import SessionLocal, session as default_session
from app.Models.base_model import EnhancedBaseModel
from app.Models.error_handling import ErrorHandler, PerformanceMonitor, ActivityLog

class Repository(ABC):
    """
    Abstract base repository class implementing repository pattern.
    
    Provides a consistent interface for data access operations
    while abstracting the underlying storage mechanism.
    """
    
    def __init__(self, model_class: Type[EnhancedBaseModel], db_session=None):
        self.model_class = model_class
        self.session = db_session or SessionLocal()
    
    def get_by_id(self, id: Any) -> Optional[EnhancedBaseModel]:
        """Get entity by ID."""
        return self.model_class.get(id, self.session)
    
    def get_all(self, include_deleted: bool = False) -> List[EnhancedBaseModel]:
        """Get all entities."""
        return self.model_class.all(self.session, include_deleted)
    
    def create(self, **kwargs) -> EnhancedBaseModel:
        """Create new entity."""
        return self.model_class.create(self.session, **kwargs)
    
    def update(self, entity: EnhancedBaseModel, **kwargs) -> EnhancedBaseModel:
        """Update entity."""
        return entity.update(self.session, **kwargs)
    
    def delete(self, entity: EnhancedBaseModel, soft: bool = True) -> EnhancedBaseModel:
        """Delete entity."""
        return entity.delete(self.session, soft=soft)
    
    def find_by(self, **filters) -> List[EnhancedBaseModel]:
        """Find entities by filters."""
        return self.model_class.find_by(self.session, **filters)
    
    def find_one_by(self, **filters) -> Optional[EnhancedBaseModel]:
        """Find single entity by filters."""
        return self.model_class.find_one_by(self.session, **filters)
    
    def exists(self, **filters) -> bool:
        """Check if entity exists."""
        return self.find_one_by(**filters) is not None
    
    def count(self, **filters) -> int:
        """Count entities matching filters."""
        query = self.session.query(self.model_class)
        for key, value in filters.items():
            if hasattr(self.model_class, key):
                query = query.filter(getattr(self.model_class, key) == value)
        return query.count()
    
    def paginate(self, page: int = 1, per_page: int = 20, **filters) -> Dict[str, Any]:
        """Paginate entities."""
        query = self.session.query(self.model_class)
        
        # Apply filters
        for key, value in filters.items():
            if hasattr(self.model_class, key):
                query = query.filter(getattr(self.model_class, key) == value)
        
        # Apply soft delete filter by default
        if not filters.get('include_deleted', False):
            query = query.filter(self.model_class.is_deleted == False)
        
        total = query.count()
        
        # Apply pagination
        offset = (page - 1) * per_page
        items = query.offset(offset).limit(per_page).all()
        
        return {
            'items': items,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': (total + per_page - 1) // per_page,
            'has_prev': page > 1,
            'has_next': page * per_page < total
        }

class UserRepository(Repository):
    """Repository for User operations."""
    
    def __init__(self, db_session=None):
        from app.Models.users import Users
        super().__init__(Users, db_session)
    
    def find_by_email(self, email: str) -> Optional['Users']:
        """Find user by email."""
        return self.find_one_by(email=email)
    
    def find_by_username(self, username: str) -> Optional['Users']:
        """Find user by username."""
        return self.find_one_by(username=username)
    
    def find_by_external_id(self, service: str, external_id: str) -> Optional['Users']:
        """Find user by external service ID."""
        users = self.get_all()
        for user in users:
            if user.get_external_id(service) == external_id:
                return user
        return None
    
    def search_users(self, query: str, limit: int = 10) -> List['Users']:
        """Search users by name, username, or email."""
        query = query.lower()
        users = self.get_all()
        
        matches = []
        for user in users:
            if (user.name and query in user.name.lower()) or \
               (user.username and query in user.username.lower()) or \
               (user.email and query in user.email.lower()):
                matches.append(user)
                
                if len(matches) >= limit:
                    break
        
        return matches
    
    def get_active_users(self, hours: int = 24) -> List['Users']:
        """Get users active in the last N hours."""
        from datetime import datetime, timedelta, timezone
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # This would need to be implemented with proper SQL query
        # For now, return all non-deleted users
        return self.find_by(is_deleted=False)

class BalanceRepository(Repository):
    """Repository for Balance operations."""
    
    def __init__(self, db_session=None):
        from app.Models.balance import Balance
        super().__init__(Balance, db_session)
    
    def get_by_user_id(self, user_id: int) -> Optional['Balance']:
        """Get balance by user ID."""
        return self.find_one_by(user_id=user_id)
    
    def get_balances_by_currency(self, currency: str = 'USD') -> List['Balance']:
        """Get all balances for a currency."""
        return self.find_by(currency=currency)
    
    def get_total_system_balance(self, currency: str = 'USD') -> float:
        """Get total balance across all users for a currency."""
        balances = self.get_balances_by_currency(currency)
        return sum(balance.amount for balance in balances)

class Service(ABC):
    """
    Abstract base service class for business logic operations.
    
    Services encapsulate business logic and coordinate between
    repositories and external services.
    """
    
    def __init__(self, db_session=None):
        self.session = db_session or SessionLocal()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.session.rollback()
        else:
            self.session.commit()
        self.session.close()

class UserService(Service):
    """Service for user-related business logic."""
    
    def __init__(self, db_session=None):
        super().__init__(db_session)
        self.user_repo = UserRepository(self.session)
        self.balance_repo = BalanceRepository(self.session)
    
    def create_user(self, name: str, email: str, password: str, 
                   username: str = None, initial_balance: float = 0.0,
                   user_id: int = None, ip_address: str = None,
                   user_agent: str = None, **kwargs) -> Dict[str, Any]:
        """
        Create a new user with business logic validation.
        
        Args:
            name: User's name
            email: User's email
            password: Plain text password
            username: Username (optional)
            initial_balance: Initial balance amount
            user_id: ID of user creating this user (for admin operations)
            ip_address: IP address for activity logging
            user_agent: User agent for activity logging
            **kwargs: Additional user attributes
            
        Returns:
            Dictionary with user data and operation result
        """
        with ErrorHandler(user_id=user_id, context={'operation': 'create_user'}):
            with PerformanceMonitor('user_creation', user_id=user_id):
                # Create user
                from app.Models.users import Users
                user = Users.create_user(
                    name=name,
                    email=email,
                    password=password,
                    username=username,
                    **kwargs
                )
                
                # Create initial balance if specified
                if initial_balance > 0:
                    from app.Models.balance import Balance
                    Balance.create_for_user(
                        user_id=user.id,
                        initial_amount=initial_balance
                    )
                
                # Log activity
                ActivityLog.log_activity(
                    activity_type='user_management',
                    action='user_created',
                    user_id=user_id,
                    resource_type='user',
                    resource_id=user.id,
                    details={
                        'created_user_email': email,
                        'initial_balance': initial_balance
                    },
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                
                return {
                    'success': True,
                    'user': user.to_dict(),
                    'message': 'User created successfully'
                }
    
    def authenticate_user(self, email: str, password: str, 
                         ip_address: str = None, user_agent: str = None,
                         remember_me: bool = False) -> Dict[str, Any]:
        """
        Authenticate user and create session.
        
        Args:
            email: User's email
            password: Plain text password
            ip_address: IP address for security logging
            user_agent: User agent for security logging
            remember_me: Whether to create long-lived session
            
        Returns:
            Dictionary with authentication result
        """
        with ErrorHandler(context={'operation': 'user_authentication'}):
            with PerformanceMonitor('user_authentication'):
                from app.Models.users import Users
                from app.Models.auth import UserSession, SecurityAudit
                
                # Attempt authentication
                user = Users.authenticate(email, password)
                
                if user:
                    # Create session
                    session_hours = 720 if remember_me else 24  # 30 days vs 1 day
                    session = UserSession.create_session(
                        user_id=user.id,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        hours=session_hours
                    )
                    
                    # Log successful authentication
                    SecurityAudit.log_event(
                        event_type='login',
                        success=True,
                        user_id=user.id,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        event_data={'remember_me': remember_me}
                    )
                    
                    ActivityLog.log_activity(
                        activity_type='authentication',
                        action='login_success',
                        user_id=user.id,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        session_id=session.session_token
                    )
                    
                    return {
                        'success': True,
                        'user': user.to_dict(),
                        'session_token': session.session_token,
                        'message': 'Authentication successful'
                    }
                else:
                    # Log failed authentication
                    SecurityAudit.log_event(
                        event_type='login',
                        success=False,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        event_data={'email': email}
                    )
                    
                    ActivityLog.log_activity(
                        activity_type='authentication',
                        action='login_failed',
                        ip_address=ip_address,
                        user_agent=user_agent,
                        result='failure',
                        details={'email': email}
                    )
                    
                    return {
                        'success': False,
                        'message': 'Invalid credentials'
                    }
    
    def get_user_profile(self, user_id: int, requesting_user_id: int = None) -> Dict[str, Any]:
        """
        Get user profile with permission checking.
        
        Args:
            user_id: ID of user to get profile for
            requesting_user_id: ID of user making the request
            
        Returns:
            Dictionary with user profile data
        """
        with ErrorHandler(user_id=requesting_user_id, context={'operation': 'get_user_profile'}):
            user = self.user_repo.get_by_id(user_id)
            
            if not user:
                from app.Models.error_handling import ResourceNotFoundError
                raise ResourceNotFoundError('User', user_id)
            
            # Check permissions (users can view their own profile, admins can view any)
            if requesting_user_id != user_id:
                requesting_user = self.user_repo.get_by_id(requesting_user_id)
                if not requesting_user or not requesting_user.is_admin:
                    from app.Models.error_handling import AuthorizationError
                    raise AuthorizationError('Insufficient permissions to view user profile')
            
            # Get balance
            balance = self.balance_repo.get_by_user_id(user_id)
            
            profile_data = user.to_dict()
            if balance:
                profile_data['balance'] = {
                    'amount': balance.amount,
                    'currency': balance.currency,
                    'is_frozen': balance.is_frozen
                }
            
            return {
                'success': True,
                'user': profile_data
            }
    
    def update_user_profile(self, user_id: int, updates: Dict[str, Any],
                           updating_user_id: int = None) -> Dict[str, Any]:
        """
        Update user profile with validation and permission checking.
        
        Args:
            user_id: ID of user to update
            updates: Dictionary of fields to update
            updating_user_id: ID of user making the update
            
        Returns:
            Dictionary with update result
        """
        with ErrorHandler(user_id=updating_user_id, context={'operation': 'update_user_profile'}):
            user = self.user_repo.get_by_id(user_id)
            
            if not user:
                from app.Models.error_handling import ResourceNotFoundError
                raise ResourceNotFoundError('User', user_id)
            
            # Check permissions
            if updating_user_id != user_id:
                updating_user = self.user_repo.get_by_id(updating_user_id)
                if not updating_user or not updating_user.is_admin:
                    from app.Models.error_handling import AuthorizationError
                    raise AuthorizationError('Insufficient permissions to update user profile')
            
            # Filter allowed updates (prevent updating sensitive fields)
            allowed_fields = ['name', 'username', 'profile_data', 'settings']
            if updating_user_id != user_id:  # Admins can update more fields
                allowed_fields.extend(['is_admin', 'is_verified'])
            
            filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields}
            
            if not filtered_updates:
                return {
                    'success': False,
                    'message': 'No valid fields to update'
                }
            
            # Update user
            updated_user = self.user_repo.update(user, **filtered_updates)
            
            # Log activity
            ActivityLog.log_activity(
                activity_type='user_management',
                action='profile_updated',
                user_id=updating_user_id,
                resource_type='user',
                resource_id=user_id,
                details={
                    'updated_fields': list(filtered_updates.keys()),
                    'self_update': updating_user_id == user_id
                }
            )
            
            return {
                'success': True,
                'user': updated_user.to_dict(),
                'message': 'Profile updated successfully'
            }

class BalanceService(Service):
    """Service for balance-related business logic."""
    
    def __init__(self, db_session=None):
        super().__init__(db_session)
        self.balance_repo = BalanceRepository(self.session)
        self.user_repo = UserRepository(self.session)
    
    def transfer_balance(self, from_user_id: int, to_user_id: int, amount: float,
                        initiated_by: int = None, description: str = None,
                        ip_address: str = None) -> Dict[str, Any]:
        """
        Transfer balance between users with comprehensive logging and validation.
        
        Args:
            from_user_id: Source user ID
            to_user_id: Target user ID
            amount: Amount to transfer
            initiated_by: User who initiated the transfer
            description: Transfer description
            ip_address: IP address for logging
            
        Returns:
            Dictionary with transfer result
        """
        with ErrorHandler(user_id=initiated_by, context={'operation': 'balance_transfer'}):
            with PerformanceMonitor('balance_transfer', user_id=initiated_by):
                # Validate users exist
                from_user = self.user_repo.get_by_id(from_user_id)
                to_user = self.user_repo.get_by_id(to_user_id)
                
                if not from_user:
                    from app.Models.error_handling import ResourceNotFoundError
                    raise ResourceNotFoundError('User', from_user_id)
                
                if not to_user:
                    from app.Models.error_handling import ResourceNotFoundError
                    raise ResourceNotFoundError('User', to_user_id)
                
                # Get balances
                from_balance = self.balance_repo.get_by_user_id(from_user_id)
                to_balance = self.balance_repo.get_by_user_id(to_user_id)
                
                if not from_balance:
                    from app.Models.balance import Balance
                    from_balance = Balance.create_for_user(from_user_id)
                
                if not to_balance:
                    from app.Models.balance import Balance
                    to_balance = Balance.create_for_user(to_user_id)
                
                # Perform transfer
                from_balance.transfer_to(to_balance, amount, str(initiated_by))
                
                # Log activity
                ActivityLog.log_activity(
                    activity_type='financial',
                    action='balance_transfer',
                    user_id=initiated_by,
                    resource_type='balance',
                    resource_id=from_balance.id,
                    details={
                        'from_user_id': from_user_id,
                        'to_user_id': to_user_id,
                        'amount': amount,
                        'description': description,
                        'from_balance_after': from_balance.amount,
                        'to_balance_after': to_balance.amount
                    },
                    ip_address=ip_address
                )
                
                return {
                    'success': True,
                    'message': 'Transfer completed successfully',
                    'transfer': {
                        'from_user': from_user.to_dict(include_sensitive=False),
                        'to_user': to_user.to_dict(include_sensitive=False),
                        'amount': amount,
                        'from_balance': from_balance.amount,
                        'to_balance': to_balance.amount
                    }
                }

class FileService(Service):
    """Service for file management operations."""
    
    def __init__(self, db_session=None):
        super().__init__(db_session)
    
    def upload_file(self, user_id: int, file_data: bytes, filename: str,
                   category: str = None, is_public: bool = False,
                   expires_hours: int = None) -> Dict[str, Any]:
        """
        Handle file upload with validation and storage management.
        
        Args:
            user_id: User uploading the file
            file_data: File binary data
            filename: Original filename
            category: File category
            is_public: Whether file should be public
            expires_hours: Hours until file expires
            
        Returns:
            Dictionary with upload result
        """
        with ErrorHandler(user_id=user_id, context={'operation': 'file_upload'}):
            from app.Models.file_management import File, FileCategory, StorageManager
            import hashlib
            
            # Get or create category
            if category:
                file_category = FileCategory.find_one_by(name=category)
                if not file_category:
                    from app.Models.error_handling import ResourceNotFoundError
                    raise ResourceNotFoundError('FileCategory', category)
            else:
                file_category = None
            
            # Validate file
            file_size = len(file_data)
            file_extension = os.path.splitext(filename)[1].lower()
            
            if file_category:
                if not file_category.is_extension_allowed(file_extension):
                    from app.Models.error_handling import ValidationError
                    raise ValidationError('file_extension', f'File type {file_extension} not allowed for category {category}')
                
                if not file_category.is_size_allowed(file_size):
                    from app.Models.error_handling import ValidationError
                    raise ValidationError('file_size', f'File size exceeds limit for category {category}')
            
            # Generate storage path
            if file_category:
                storage_path = file_category.get_storage_path(filename)
            else:
                storage_path = f"uploads/misc/{datetime.now().year}/{datetime.now().month:02d}"
            
            # Ensure directory exists
            full_storage_path = os.path.join(StorageManager.get_storage_root(), storage_path)
            StorageManager.ensure_directory(full_storage_path)
            
            # Generate unique filename
            safe_filename = File.sanitize_filename(filename)
            unique_filename = StorageManager.generate_unique_filename(safe_filename, full_storage_path)
            
            # Write file
            file_path = os.path.join(storage_path, unique_filename)
            full_file_path = os.path.join(StorageManager.get_storage_root(), file_path)
            
            with open(full_file_path, 'wb') as f:
                f.write(file_data)
            
            # Create file record
            file_record = File.create_file_record(
                user_id=user_id,
                original_filename=filename,
                file_path=file_path,
                file_size=file_size,
                category_name=category,
                is_public=is_public,
                expires_hours=expires_hours
            )
            
            # Log activity
            ActivityLog.log_activity(
                activity_type='file_management',
                action='file_uploaded',
                user_id=user_id,
                resource_type='file',
                resource_id=file_record.id,
                details={
                    'filename': filename,
                    'file_size': file_size,
                    'category': category,
                    'is_public': is_public
                }
            )
            
            return {
                'success': True,
                'file': file_record.to_dict(),
                'message': 'File uploaded successfully'
            }

# Service factory for dependency injection
class ServiceFactory:
    """Factory for creating service instances with proper dependency injection."""
    
    @staticmethod
    def create_user_service(db_session=None) -> UserService:
        """Create UserService instance."""
        return UserService(db_session)
    
    @staticmethod
    def create_balance_service(db_session=None) -> BalanceService:
        """Create BalanceService instance."""
        return BalanceService(db_session)
    
    @staticmethod
    def create_file_service(db_session=None) -> FileService:
        """Create FileService instance."""
        return FileService(db_session)

# Convenience functions for common operations
def get_user_service() -> UserService:
    """Get UserService instance."""
    return ServiceFactory.create_user_service()

def get_balance_service() -> BalanceService:
    """Get BalanceService instance."""
    return ServiceFactory.create_balance_service()

def get_file_service() -> FileService:
    """Get FileService instance."""
    return ServiceFactory.create_file_service()