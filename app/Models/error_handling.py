"""
Enhanced error handling and logging models for the MVC framework.

This module provides comprehensive error tracking, logging, and monitoring:
- Custom exception classes with detailed context
- Database-backed error logging
- Performance monitoring
- User activity tracking
- System health monitoring
"""

import traceback
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Union
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship
from enum import Enum

from .base_model import EnhancedBaseModel
from database.db import session

# Define logging for this module
logger = logging.getLogger(__name__)

# Enhanced exception classes
class MvcError(Exception):
    """Base exception class for MVC framework errors."""
    
    def __init__(self, message: str, code: str = None, context: Dict = None, 
                 user_id: int = None, request_id: str = None):
        self.message = message
        self.code = code or self.__class__.__name__
        self.context = context or {}
        self.user_id = user_id
        self.request_id = request_id
        self.timestamp = datetime.now(timezone.utc)
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging."""
        return {
            'error_type': self.__class__.__name__,
            'message': self.message,
            'code': self.code,
            'context': self.context,
            'user_id': self.user_id,
            'request_id': self.request_id,
            'timestamp': self.timestamp.isoformat(),
            'traceback': traceback.format_exc()
        }

class ValidationError(MvcError):
    """Validation error with field-specific information."""
    
    def __init__(self, field: str, message: str, value: Any = None, **kwargs):
        self.field = field
        self.value = value
        context = kwargs.get('context', {})
        context.update({'field': field, 'value': str(value) if value is not None else None})
        kwargs['context'] = context
        super().__init__(f"Validation error for '{field}': {message}", **kwargs)

class AuthenticationError(MvcError):
    """Authentication-related errors."""
    pass

class AuthorizationError(MvcError):
    """Authorization/permission-related errors."""
    pass

class ResourceNotFoundError(MvcError):
    """Resource not found errors."""
    
    def __init__(self, resource_type: str, resource_id: Any = None, **kwargs):
        self.resource_type = resource_type
        self.resource_id = resource_id
        context = kwargs.get('context', {})
        context.update({'resource_type': resource_type, 'resource_id': str(resource_id)})
        kwargs['context'] = context
        message = f"{resource_type} not found"
        if resource_id:
            message += f" (ID: {resource_id})"
        super().__init__(message, **kwargs)

class BusinessLogicError(MvcError):
    """Business logic violations."""
    pass

class ExternalServiceError(MvcError):
    """External service/vendor integration errors."""
    
    def __init__(self, service_name: str, operation: str, **kwargs):
        self.service_name = service_name
        self.operation = operation
        context = kwargs.get('context', {})
        context.update({'service_name': service_name, 'operation': operation})
        kwargs['context'] = context
        super().__init__(f"External service error: {service_name} ({operation})", **kwargs)

class RateLimitError(MvcError):
    """Rate limiting errors."""
    
    def __init__(self, limit_type: str, limit_value: int, **kwargs):
        self.limit_type = limit_type
        self.limit_value = limit_value
        context = kwargs.get('context', {})
        context.update({'limit_type': limit_type, 'limit_value': limit_value})
        kwargs['context'] = context
        super().__init__(f"Rate limit exceeded: {limit_type} ({limit_value})", **kwargs)

class DatabaseError(MvcError):
    """Database operation errors."""
    pass

class ConfigurationError(MvcError):
    """Configuration-related errors."""
    pass

# Logging level enumeration
class LogLevel(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class ErrorLog(EnhancedBaseModel):
    """
    Database-backed error logging system.
    
    Attributes:
        error_type: Type of error (exception class name)
        error_code: Error code for categorization
        message: Error message
        stack_trace: Full stack trace
        context: Additional context data (request data, user info, etc.)
        user_id: User associated with the error (if applicable)
        request_id: Request ID for tracing
        url: URL where error occurred
        user_agent: Browser user agent
        ip_address: IP address of the request
        severity: Error severity level
        is_resolved: Whether the error has been resolved
        resolved_by: Who resolved the error
        resolved_at: When the error was resolved
        resolution_notes: Notes about the resolution
        occurrence_count: How many times this exact error has occurred
        last_occurrence: Last time this error occurred
    """
    __tablename__ = 'error_logs'
    
    error_type = Column(String(100), nullable=False, index=True)
    error_code = Column(String(100), nullable=True, index=True)
    message = Column(Text, nullable=False)
    stack_trace = Column(Text, nullable=True)
    context = Column(JSON, default=dict)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    request_id = Column(String(100), nullable=True, index=True)
    url = Column(String(500), nullable=True)
    user_agent = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    severity = Column(String(20), default=LogLevel.ERROR.value, nullable=False, index=True)
    is_resolved = Column(Boolean, default=False, nullable=False)
    resolved_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    occurrence_count = Column(Integer, default=1, nullable=False)
    last_occurrence = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationships
    user = relationship('Users', foreign_keys=[user_id], backref='error_logs')
    resolver = relationship('Users', foreign_keys=[resolved_by])
    
    def __repr__(self):
        return f"<ErrorLog(type={self.error_type}, severity={self.severity}, count={self.occurrence_count})>"
    
    def resolve(self, resolver_id: int, notes: str = None):
        """Mark error as resolved."""
        self.is_resolved = True
        self.resolved_by = resolver_id
        self.resolved_at = datetime.now(timezone.utc)
        self.resolution_notes = notes
        session.commit()
    
    def increment_occurrence(self):
        """Increment occurrence count and update last occurrence."""
        self.occurrence_count += 1
        self.last_occurrence = datetime.now(timezone.utc)
        session.commit()
    
    @classmethod
    def log_error(cls, error: Exception, user_id: int = None, request_id: str = None,
                 url: str = None, user_agent: str = None, ip_address: str = None,
                 context: Dict = None) -> 'ErrorLog':
        """
        Log an error to the database.
        
        Args:
            error: Exception instance
            user_id: User ID associated with error
            request_id: Request ID for tracing
            url: URL where error occurred
            user_agent: Browser user agent
            ip_address: IP address
            context: Additional context data
            
        Returns:
            ErrorLog instance
        """
        # Extract error information
        error_type = error.__class__.__name__
        error_code = getattr(error, 'code', None)
        message = str(error)
        stack_trace = traceback.format_exc()
        
        # Merge context from exception if available
        error_context = getattr(error, 'context', {})
        if context:
            error_context.update(context)
        
        # Get user_id and request_id from exception if available
        if not user_id:
            user_id = getattr(error, 'user_id', None)
        if not request_id:
            request_id = getattr(error, 'request_id', None)
        
        # Check for existing similar error
        existing = cls._find_similar_error(error_type, message, user_id, url)
        if existing:
            existing.increment_occurrence()
            return existing
        
        # Determine severity
        severity = cls._determine_severity(error)
        
        return cls.create(
            error_type=error_type,
            error_code=error_code,
            message=message,
            stack_trace=stack_trace,
            context=error_context,
            user_id=user_id,
            request_id=request_id,
            url=url,
            user_agent=user_agent,
            ip_address=ip_address,
            severity=severity
        )
    
    @classmethod
    def _find_similar_error(cls, error_type: str, message: str, user_id: int = None, 
                          url: str = None) -> Optional['ErrorLog']:
        """Find similar error logged recently."""
        # Look for similar errors in the last hour
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        
        query = session.query(cls).filter(
            cls.error_type == error_type,
            cls.message == message,
            cls.created_at >= since,
            cls.is_resolved == False
        )
        
        if user_id:
            query = query.filter(cls.user_id == user_id)
        
        if url:
            query = query.filter(cls.url == url)
        
        return query.first()
    
    @staticmethod
    def _determine_severity(error: Exception) -> str:
        """Determine error severity based on exception type."""
        if isinstance(error, (ValidationError, AuthenticationError, AuthorizationError)):
            return LogLevel.WARNING.value
        elif isinstance(error, (ResourceNotFoundError, BusinessLogicError)):
            return LogLevel.ERROR.value
        elif isinstance(error, (ExternalServiceError, DatabaseError)):
            return LogLevel.CRITICAL.value
        elif isinstance(error, RateLimitError):
            return LogLevel.WARNING.value
        else:
            return LogLevel.ERROR.value
    
    @classmethod
    def get_error_summary(cls, hours: int = 24) -> Dict[str, Any]:
        """Get error summary for the specified time period."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        errors = session.query(cls).filter(cls.created_at >= since).all()
        
        total_errors = len(errors)
        resolved_errors = len([e for e in errors if e.is_resolved])
        
        by_type = {}
        by_severity = {}
        
        for error in errors:
            by_type[error.error_type] = by_type.get(error.error_type, 0) + 1
            by_severity[error.severity] = by_severity.get(error.severity, 0) + 1
        
        return {
            'total_errors': total_errors,
            'resolved_errors': resolved_errors,
            'unresolved_errors': total_errors - resolved_errors,
            'resolution_rate': (resolved_errors / total_errors * 100) if total_errors > 0 else 0,
            'by_type': by_type,
            'by_severity': by_severity,
            'period_hours': hours
        }
    
    @classmethod
    def get_frequent_errors(cls, limit: int = 10, hours: int = 24) -> List['ErrorLog']:
        """Get most frequent errors in the time period."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        return session.query(cls).filter(
            cls.created_at >= since,
            cls.is_resolved == False
        ).order_by(
            cls.occurrence_count.desc()
        ).limit(limit).all()

class ActivityLog(EnhancedBaseModel):
    """
    User activity and system event logging.
    
    Attributes:
        user_id: User who performed the activity
        activity_type: Type of activity (login, logout, create, update, etc.)
        resource_type: Type of resource involved (user, file, etc.)
        resource_id: ID of the resource
        action: Specific action performed
        details: Additional details about the activity
        ip_address: IP address of the user
        user_agent: Browser user agent
        request_id: Request ID for tracing
        session_id: Session ID
        result: Result of the activity (success, failure, etc.)
        duration: Time taken for the activity (milliseconds)
    """
    __tablename__ = 'activity_logs'
    
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    activity_type = Column(String(50), nullable=False, index=True)
    resource_type = Column(String(50), nullable=True, index=True)
    resource_id = Column(String(100), nullable=True)
    action = Column(String(100), nullable=False)
    details = Column(JSON, default=dict)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    request_id = Column(String(100), nullable=True, index=True)
    session_id = Column(String(255), nullable=True)
    result = Column(String(20), default='success', nullable=False)
    duration = Column(Float, nullable=True)  # Milliseconds
    
    # Relationship
    user = relationship('Users', backref='activity_logs')
    
    def __repr__(self):
        return f"<ActivityLog(user_id={self.user_id}, action={self.action}, result={self.result})>"
    
    @classmethod
    def log_activity(cls, activity_type: str, action: str, user_id: int = None,
                    resource_type: str = None, resource_id: str = None,
                    details: Dict = None, ip_address: str = None,
                    user_agent: str = None, request_id: str = None,
                    session_id: str = None, result: str = 'success',
                    duration: float = None) -> 'ActivityLog':
        """
        Log user activity.
        
        Args:
            activity_type: Type of activity
            action: Specific action
            user_id: User performing the action
            resource_type: Type of resource
            resource_id: Resource ID
            details: Additional details
            ip_address: IP address
            user_agent: User agent
            request_id: Request ID
            session_id: Session ID
            result: Result of activity
            duration: Duration in milliseconds
            
        Returns:
            ActivityLog instance
        """
        return cls.create(
            user_id=user_id,
            activity_type=activity_type,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            action=action,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            session_id=session_id,
            result=result,
            duration=duration
        )
    
    @classmethod
    def get_user_activity(cls, user_id: int, limit: int = 50, 
                         activity_type: str = None) -> List['ActivityLog']:
        """Get recent activity for a user."""
        query = session.query(cls).filter(cls.user_id == user_id)
        
        if activity_type:
            query = query.filter(cls.activity_type == activity_type)
        
        return query.order_by(cls.created_at.desc()).limit(limit).all()
    
    @classmethod
    def get_activity_summary(cls, hours: int = 24) -> Dict[str, Any]:
        """Get activity summary for the time period."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        activities = session.query(cls).filter(cls.created_at >= since).all()
        
        total_activities = len(activities)
        unique_users = len(set(a.user_id for a in activities if a.user_id))
        
        by_type = {}
        by_result = {}
        
        for activity in activities:
            by_type[activity.activity_type] = by_type.get(activity.activity_type, 0) + 1
            by_result[activity.result] = by_result.get(activity.result, 0) + 1
        
        return {
            'total_activities': total_activities,
            'unique_users': unique_users,
            'by_type': by_type,
            'by_result': by_result,
            'period_hours': hours
        }

class PerformanceMetric(EnhancedBaseModel):
    """
    Performance monitoring and metrics collection.
    
    Attributes:
        metric_name: Name of the metric (response_time, memory_usage, etc.)
        metric_type: Type of metric (gauge, counter, histogram, etc.)
        value: Metric value
        unit: Unit of measurement
        tags: Tags for filtering and grouping
        endpoint: API endpoint (if applicable)
        method: HTTP method (if applicable)
        user_id: User associated with metric (if applicable)
        request_id: Request ID for tracing
        additional_data: Additional metric data
    """
    __tablename__ = 'performance_metrics'
    
    metric_name = Column(String(100), nullable=False, index=True)
    metric_type = Column(String(50), nullable=False)  # gauge, counter, histogram, timer
    value = Column(Float, nullable=False)
    unit = Column(String(20), nullable=True)  # ms, bytes, count, percent, etc.
    tags = Column(JSON, default=dict)
    endpoint = Column(String(500), nullable=True, index=True)
    method = Column(String(10), nullable=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    request_id = Column(String(100), nullable=True, index=True)
    additional_data = Column(JSON, default=dict)
    
    # Relationship
    user = relationship('Users', backref='performance_metrics')
    
    def __repr__(self):
        return f"<PerformanceMetric(name={self.metric_name}, value={self.value}, unit={self.unit})>"
    
    @classmethod
    def record_metric(cls, metric_name: str, value: float, metric_type: str = 'gauge',
                     unit: str = None, tags: Dict = None, endpoint: str = None,
                     method: str = None, user_id: int = None, request_id: str = None,
                     additional_data: Dict = None) -> 'PerformanceMetric':
        """
        Record a performance metric.
        
        Args:
            metric_name: Name of the metric
            value: Metric value
            metric_type: Type of metric
            unit: Unit of measurement
            tags: Tags for filtering
            endpoint: API endpoint
            method: HTTP method
            user_id: User ID
            request_id: Request ID
            additional_data: Additional data
            
        Returns:
            PerformanceMetric instance
        """
        return cls.create(
            metric_name=metric_name,
            metric_type=metric_type,
            value=value,
            unit=unit,
            tags=tags or {},
            endpoint=endpoint,
            method=method,
            user_id=user_id,
            request_id=request_id,
            additional_data=additional_data or {}
        )
    
    @classmethod
    def get_metric_summary(cls, metric_name: str, hours: int = 24) -> Dict[str, Any]:
        """Get summary statistics for a metric."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        metrics = session.query(cls).filter(
            cls.metric_name == metric_name,
            cls.created_at >= since
        ).all()
        
        if not metrics:
            return {'count': 0, 'period_hours': hours}
        
        values = [m.value for m in metrics]
        
        return {
            'count': len(values),
            'min': min(values),
            'max': max(values),
            'avg': sum(values) / len(values),
            'sum': sum(values),
            'period_hours': hours
        }
    
    @classmethod
    def get_slow_endpoints(cls, limit: int = 10, hours: int = 24) -> List[Dict[str, Any]]:
        """Get slowest endpoints by average response time."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # This is a simplified version - in production, use proper aggregation
        metrics = session.query(cls).filter(
            cls.metric_name == 'response_time',
            cls.created_at >= since,
            cls.endpoint.isnot(None)
        ).all()
        
        endpoint_stats = {}
        for metric in metrics:
            endpoint = metric.endpoint
            if endpoint not in endpoint_stats:
                endpoint_stats[endpoint] = {'values': [], 'count': 0}
            endpoint_stats[endpoint]['values'].append(metric.value)
            endpoint_stats[endpoint]['count'] += 1
        
        # Calculate averages and sort
        results = []
        for endpoint, stats in endpoint_stats.items():
            avg_time = sum(stats['values']) / len(stats['values'])
            results.append({
                'endpoint': endpoint,
                'avg_response_time': avg_time,
                'request_count': stats['count'],
                'max_response_time': max(stats['values']),
                'min_response_time': min(stats['values'])
            })
        
        return sorted(results, key=lambda x: x['avg_response_time'], reverse=True)[:limit]

# Context manager for automatic error logging
class ErrorHandler:
    """Context manager for automatic error logging and handling."""
    
    def __init__(self, user_id: int = None, request_id: str = None,
                 url: str = None, user_agent: str = None, ip_address: str = None,
                 context: Dict = None, reraise: bool = True):
        self.user_id = user_id
        self.request_id = request_id
        self.url = url
        self.user_agent = user_agent
        self.ip_address = ip_address
        self.context = context or {}
        self.reraise = reraise
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type and exc_val:
            # Log the error
            ErrorLog.log_error(
                error=exc_val,
                user_id=self.user_id,
                request_id=self.request_id,
                url=self.url,
                user_agent=self.user_agent,
                ip_address=self.ip_address,
                context=self.context
            )
            
            # Re-raise if configured to do so
            if self.reraise:
                return False
            else:
                return True  # Suppress the exception

# Performance monitoring context manager
class PerformanceMonitor:
    """Context manager for automatic performance monitoring."""
    
    def __init__(self, operation_name: str, user_id: int = None,
                 request_id: str = None, endpoint: str = None,
                 method: str = None, tags: Dict = None):
        self.operation_name = operation_name
        self.user_id = user_id
        self.request_id = request_id
        self.endpoint = endpoint
        self.method = method
        self.tags = tags or {}
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.now(timezone.utc)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = (datetime.now(timezone.utc) - self.start_time).total_seconds() * 1000
            
            PerformanceMetric.record_metric(
                metric_name=f"{self.operation_name}_duration",
                value=duration,
                metric_type='timer',
                unit='ms',
                tags=self.tags,
                endpoint=self.endpoint,
                method=self.method,
                user_id=self.user_id,
                request_id=self.request_id
            )