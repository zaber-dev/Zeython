"""
Enhanced BaseModel with validation, caching, audit trails, and event system.

This module provides an enhanced base class for all models in the MVC framework,
adding enterprise-level features like validation, caching, soft deletes, and
audit trails while maintaining backward compatibility.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Type, Callable, Union
from functools import wraps
from sqlalchemy import Column, Integer, Boolean, DateTime, String, Text, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy import create_engine, event
from database.db import Base, SessionLocal, session

logger = logging.getLogger(__name__)

# Model event types
class ModelEvents:
    BEFORE_CREATE = "before_create"
    AFTER_CREATE = "after_create"
    BEFORE_UPDATE = "before_update"
    AFTER_UPDATE = "after_update"
    BEFORE_DELETE = "before_delete"
    AFTER_DELETE = "after_delete"
    BEFORE_SAVE = "before_save"
    AFTER_SAVE = "after_save"

class ValidationError(Exception):
    """Custom exception for model validation errors."""
    
    def __init__(self, field: str, message: str, value: Any = None):
        self.field = field
        self.message = message
        self.value = value
        super().__init__(f"Validation error for '{field}': {message}")

class ModelCache:
    """Simple in-memory cache for model instances."""
    
    def __init__(self):
        self._cache: Dict[str, Dict[Any, Any]] = {}
        self._enabled = True
    
    def enable(self):
        """Enable caching."""
        self._enabled = True
    
    def disable(self):
        """Disable caching."""
        self._enabled = False
        self.clear()
    
    def get(self, model_class: Type, key: Any) -> Optional[Any]:
        """Get cached instance."""
        if not self._enabled:
            return None
        
        class_name = model_class.__name__
        return self._cache.get(class_name, {}).get(key)
    
    def set(self, model_class: Type, key: Any, instance: Any):
        """Cache instance."""
        if not self._enabled:
            return
        
        class_name = model_class.__name__
        if class_name not in self._cache:
            self._cache[class_name] = {}
        self._cache[class_name][key] = instance
    
    def invalidate(self, model_class: Type, key: Any = None):
        """Invalidate cached instance(s)."""
        class_name = model_class.__name__
        if key is None:
            # Clear all instances for this model
            self._cache.pop(class_name, None)
        else:
            # Clear specific instance
            self._cache.get(class_name, {}).pop(key, None)
    
    def clear(self):
        """Clear all cached instances."""
        self._cache.clear()

# Global model cache instance
model_cache = ModelCache()

class AuditMixin:
    """Mixin to add audit trail functionality to models."""
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, 
                       default=lambda: datetime.now(timezone.utc), 
                       onupdate=lambda: datetime.now(timezone.utc), 
                       nullable=False)
    created_by = Column(String(255), nullable=True)  # User ID who created the record
    updated_by = Column(String(255), nullable=True)  # User ID who last updated the record

class SoftDeleteMixin:
    """Mixin to add soft delete functionality to models."""
    
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(String(255), nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    
    def soft_delete(self, user_id: str = None):
        """Soft delete the record."""
        self.is_deleted = True
        self.deleted_at = datetime.now(timezone.utc)
        self.deleted_by = user_id
        session.commit()
    
    def restore(self):
        """Restore a soft deleted record."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        session.commit()
    
    @classmethod
    def with_deleted(cls):
        """Query including soft deleted records."""
        return session.query(cls)
    
    @classmethod
    def only_deleted(cls):
        """Query only soft deleted records."""
        return session.query(cls).filter(cls.is_deleted == True)

class EnhancedBaseModel(Base, AuditMixin, SoftDeleteMixin):
    """
    Enhanced base model with validation, caching, audit trails, and events.
    
    Features:
    - Field validation with custom validators
    - In-memory caching for improved performance
    - Audit trails for tracking changes
    - Soft delete functionality
    - Model lifecycle events
    - JSON serialization support
    - Enhanced query methods
    """
    
    __abstract__ = True
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Class-level storage for validators and event handlers
    _validators: Dict[str, List[Callable]] = {}
    _event_handlers: Dict[str, List[Callable]] = {}
    _cache_enabled = True
    
    def __init__(self, **kwargs):
        # Remove audit fields from kwargs if present (they should be set automatically)
        audit_fields = ['created_at', 'updated_at', 'created_by', 'updated_by']
        clean_kwargs = {k: v for k, v in kwargs.items() if k not in audit_fields}
        super().__init__(**clean_kwargs)
        
        # Trigger before_create event
        self._trigger_event(ModelEvents.BEFORE_CREATE)
    
    @classmethod
    def add_validator(cls, field: str, validator: Callable[[Any], bool], message: str = None):
        """
        Add a validator for a specific field.
        
        Args:
            field: Field name to validate
            validator: Function that takes a value and returns True if valid
            message: Custom error message for validation failure
        """
        if cls.__name__ not in cls._validators:
            cls._validators[cls.__name__] = {}
        if field not in cls._validators[cls.__name__]:
            cls._validators[cls.__name__][field] = []
        
        cls._validators[cls.__name__][field].append({
            'validator': validator,
            'message': message or f"Validation failed for {field}"
        })
    
    @classmethod
    def add_event_handler(cls, event: str, handler: Callable):
        """
        Add an event handler for model lifecycle events.
        
        Args:
            event: Event name (use ModelEvents constants)
            handler: Function to call when event is triggered
        """
        if cls.__name__ not in cls._event_handlers:
            cls._event_handlers[cls.__name__] = {}
        if event not in cls._event_handlers[cls.__name__]:
            cls._event_handlers[cls.__name__][event] = []
        
        cls._event_handlers[cls.__name__][event].append(handler)
    
    def _trigger_event(self, event: str, **kwargs):
        """Trigger model lifecycle events."""
        class_name = self.__class__.__name__
        handlers = self._event_handlers.get(class_name, {}).get(event, [])
        
        for handler in handlers:
            try:
                handler(self, **kwargs)
            except Exception as e:
                logger.error(f"Error in event handler for {event}: {e}")
    
    def validate(self) -> List[ValidationError]:
        """
        Validate all fields using registered validators.
        
        Returns:
            List of ValidationError objects for any validation failures
        """
        errors = []
        class_name = self.__class__.__name__
        validators = self._validators.get(class_name, {})
        
        for field, field_validators in validators.items():
            if hasattr(self, field):
                value = getattr(self, field)
                for validator_info in field_validators:
                    validator = validator_info['validator']
                    message = validator_info['message']
                    
                    try:
                        if not validator(value):
                            errors.append(ValidationError(field, message, value))
                    except Exception as e:
                        errors.append(ValidationError(field, f"Validator error: {e}", value))
        
        return errors
    
    def is_valid(self) -> bool:
        """Check if the model passes all validation rules."""
        return len(self.validate()) == 0
    
    def validate_or_raise(self):
        """Validate and raise ValidationError if validation fails."""
        errors = self.validate()
        if errors:
            raise errors[0]  # Raise the first error
    
    @classmethod
    def create(cls, db_session=None, validate: bool = True, **kwargs):
        """
        Create a new instance with validation and events.
        
        Args:
            db_session: Database session to use
            validate: Whether to validate before saving
            **kwargs: Model attributes
        
        Returns:
            Created model instance
            
        Raises:
            ValidationError: If validation fails
        """
        if db_session is None:
            db_session = SessionLocal()
        
        instance = cls(**kwargs)
        
        if validate:
            instance.validate_or_raise()
        
        instance._trigger_event(ModelEvents.BEFORE_SAVE)
        
        db_session.add(instance)
        db_session.commit()
        db_session.refresh(instance)
        
        # Cache the instance
        if cls._cache_enabled:
            model_cache.set(cls, instance.id, instance)
        
        instance._trigger_event(ModelEvents.AFTER_CREATE)
        instance._trigger_event(ModelEvents.AFTER_SAVE)
        
        return instance
    
    @classmethod
    def get(cls, id, db_session=None, use_cache: bool = True):
        """
        Get an instance by ID with caching support.
        
        Args:
            id: Primary key value
            db_session: Database session to use
            use_cache: Whether to use cached instances
            
        Returns:
            Model instance or None if not found
        """
        # Check cache first
        if use_cache and cls._cache_enabled:
            cached = model_cache.get(cls, id)
            if cached and not cached.is_deleted:
                return cached
        
        if db_session is None:
            db_session = SessionLocal()
        
        instance = db_session.query(cls).filter(cls.id == id, cls.is_deleted == False).first()
        
        # Cache the instance
        if instance and use_cache and cls._cache_enabled:
            model_cache.set(cls, instance.id, instance)
        
        return instance
    
    @classmethod
    def all(cls, db_session=None, include_deleted: bool = False):
        """
        Get all instances, optionally including soft deleted ones.
        
        Args:
            db_session: Database session to use
            include_deleted: Whether to include soft deleted records
            
        Returns:
            List of model instances
        """
        if db_session is None:
            db_session = SessionLocal()
        
        query = db_session.query(cls)
        if not include_deleted:
            query = query.filter(cls.is_deleted == False)
        
        return query.all()
    
    def update(self, db_session=None, validate: bool = True, **kwargs):
        """
        Update instance with validation and events.
        
        Args:
            db_session: Database session to use
            validate: Whether to validate before saving
            **kwargs: Attributes to update
            
        Returns:
            Updated instance
            
        Raises:
            ValidationError: If validation fails
        """
        if db_session is None:
            db_session = SessionLocal()
        
        self._trigger_event(ModelEvents.BEFORE_UPDATE)
        
        # Update attributes
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        
        if validate:
            self.validate_or_raise()
        
        self._trigger_event(ModelEvents.BEFORE_SAVE)
        
        db_session.commit()
        db_session.refresh(self)
        
        # Invalidate cache
        model_cache.invalidate(self.__class__, self.id)
        
        self._trigger_event(ModelEvents.AFTER_UPDATE)
        self._trigger_event(ModelEvents.AFTER_SAVE)
        
        return self
    
    def delete(self, db_session=None, soft: bool = True, user_id: str = None):
        """
        Delete instance (soft delete by default).
        
        Args:
            db_session: Database session to use
            soft: Whether to use soft delete
            user_id: ID of user performing the deletion
            
        Returns:
            Deleted instance
        """
        if db_session is None:
            db_session = SessionLocal()
        
        self._trigger_event(ModelEvents.BEFORE_DELETE)
        
        if soft:
            self.soft_delete(user_id)
        else:
            db_session.delete(self)
            db_session.commit()
        
        # Invalidate cache
        model_cache.invalidate(self.__class__, self.id)
        
        self._trigger_event(ModelEvents.AFTER_DELETE)
        
        return self
    
    def to_dict(self, exclude: List[str] = None, include_relationships: bool = False) -> Dict[str, Any]:
        """
        Convert model instance to dictionary for JSON serialization.
        
        Args:
            exclude: List of field names to exclude
            include_relationships: Whether to include relationship data
            
        Returns:
            Dictionary representation of the model
        """
        exclude = exclude or []
        result = {}
        
        # Get column attributes
        mapper = inspect(self.__class__)
        for column in mapper.columns:
            if column.name not in exclude:
                value = getattr(self, column.name)
                if isinstance(value, datetime):
                    value = value.isoformat()
                result[column.name] = value
        
        # Get relationship attributes if requested
        if include_relationships:
            for relationship in mapper.relationships:
                if relationship.key not in exclude:
                    related_obj = getattr(self, relationship.key)
                    if related_obj is not None:
                        if hasattr(related_obj, '__iter__') and not isinstance(related_obj, str):
                            # One-to-many relationship
                            result[relationship.key] = [
                                obj.to_dict(exclude=exclude) if hasattr(obj, 'to_dict') else str(obj)
                                for obj in related_obj
                            ]
                        else:
                            # One-to-one relationship
                            result[relationship.key] = (
                                related_obj.to_dict(exclude=exclude) 
                                if hasattr(related_obj, 'to_dict') 
                                else str(related_obj)
                            )
        
        return result
    
    def to_json(self, exclude: List[str] = None, include_relationships: bool = False) -> str:
        """
        Convert model instance to JSON string.
        
        Args:
            exclude: List of field names to exclude
            include_relationships: Whether to include relationship data
            
        Returns:
            JSON string representation of the model
        """
        return json.dumps(self.to_dict(exclude, include_relationships), default=str)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], validate: bool = True):
        """
        Create model instance from dictionary data.
        
        Args:
            data: Dictionary with model data
            validate: Whether to validate the instance
            
        Returns:
            Model instance
            
        Raises:
            ValidationError: If validation fails
        """
        # Filter out None values and invalid columns
        mapper = inspect(cls)
        valid_columns = {col.name for col in mapper.columns}
        clean_data = {k: v for k, v in data.items() if k in valid_columns and v is not None}
        
        return cls.create(validate=validate, **clean_data)
    
    @classmethod
    def from_json(cls, json_str: str, validate: bool = True):
        """
        Create model instance from JSON string.
        
        Args:
            json_str: JSON string with model data
            validate: Whether to validate the instance
            
        Returns:
            Model instance
            
        Raises:
            ValidationError: If validation fails
            json.JSONDecodeError: If JSON is invalid
        """
        data = json.loads(json_str)
        return cls.from_dict(data, validate)
    
    @classmethod
    def find_by(cls, db_session=None, include_deleted: bool = False, **filters):
        """
        Find instances by arbitrary field filters.
        
        Args:
            db_session: Database session to use
            include_deleted: Whether to include soft deleted records
            **filters: Field filters
            
        Returns:
            List of matching instances
        """
        if db_session is None:
            db_session = SessionLocal()
        
        query = db_session.query(cls)
        
        if not include_deleted:
            query = query.filter(cls.is_deleted == False)
        
        for field, value in filters.items():
            if hasattr(cls, field):
                query = query.filter(getattr(cls, field) == value)
        
        return query.all()
    
    @classmethod
    def find_one_by(cls, db_session=None, include_deleted: bool = False, **filters):
        """
        Find single instance by arbitrary field filters.
        
        Args:
            db_session: Database session to use
            include_deleted: Whether to include soft deleted records
            **filters: Field filters
            
        Returns:
            Single matching instance or None
        """
        results = cls.find_by(db_session, include_deleted, **filters)
        return results[0] if results else None
    
    @classmethod
    def exists(cls, id, db_session=None):
        """
        Check if an instance exists by ID (excluding soft deleted).
        
        Args:
            id: Primary key value
            db_session: Database session to use
            
        Returns:
            True if instance exists and is not soft deleted
        """
        if db_session is None:
            db_session = SessionLocal()
        
        return db_session.query(cls).filter(
            cls.id == id, 
            cls.is_deleted == False
        ).first() is not None
    
    def __repr__(self):
        """String representation of the model."""
        return f"<{self.__class__.__name__}(id={self.id})>"