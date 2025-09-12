"""
File management models for handling uploads, storage, and file metadata.

This module provides comprehensive file management functionality including:
- File upload tracking with metadata
- Storage management and organization
- File permissions and access control
- Virus scanning integration
- File versioning support
- Thumbnail generation tracking
"""

import os
import hashlib
import mimetypes
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Union
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey, JSON, BigInteger
from sqlalchemy.orm import relationship

from .base_model import EnhancedBaseModel
from database.db import session

import logging
logger = logging.getLogger(__name__)

class FileCategory(EnhancedBaseModel):
    """
    File categories for organization and management.
    
    Attributes:
        name: Category name (documents, images, videos, etc.)
        description: Category description
        allowed_extensions: List of allowed file extensions
        max_file_size: Maximum file size in bytes
        storage_path: Storage path template
        requires_approval: Whether files need approval before being visible
        auto_scan: Whether to automatically scan files for viruses
    """
    __tablename__ = 'file_categories'
    
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    allowed_extensions = Column(JSON, default=list)  # ['.jpg', '.png', '.pdf']
    max_file_size = Column(BigInteger, default=10485760, nullable=False)  # 10MB default
    storage_path = Column(String(255), default='uploads/{category}/{year}/{month}', nullable=False)
    requires_approval = Column(Boolean, default=False, nullable=False)
    auto_scan = Column(Boolean, default=True, nullable=False)
    
    def __repr__(self):
        return f"<FileCategory(name={self.name})>"
    
    def is_extension_allowed(self, extension: str) -> bool:
        """Check if file extension is allowed for this category."""
        if not self.allowed_extensions:
            return True  # No restrictions
        return extension.lower() in [ext.lower() for ext in self.allowed_extensions]
    
    def is_size_allowed(self, size: int) -> bool:
        """Check if file size is within limits."""
        return size <= self.max_file_size
    
    def get_storage_path(self, filename: str = None) -> str:
        """Get the storage path for this category."""
        now = datetime.now()
        path = self.storage_path.format(
            category=self.name,
            year=now.year,
            month=f"{now.month:02d}",
            day=f"{now.day:02d}",
            filename=filename or ''
        )
        return path.strip('/')
    
    @classmethod
    def get_default_categories(cls) -> List['FileCategory']:
        """Create default file categories."""
        categories = [
            {
                'name': 'documents',
                'description': 'Document files (PDF, DOC, etc.)',
                'allowed_extensions': ['.pdf', '.doc', '.docx', '.txt', '.rtf'],
                'max_file_size': 50 * 1024 * 1024,  # 50MB
                'storage_path': 'uploads/documents/{year}/{month}'
            },
            {
                'name': 'images',
                'description': 'Image files (JPG, PNG, GIF, etc.)',
                'allowed_extensions': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'],
                'max_file_size': 10 * 1024 * 1024,  # 10MB
                'storage_path': 'uploads/images/{year}/{month}'
            },
            {
                'name': 'videos',
                'description': 'Video files (MP4, AVI, etc.)',
                'allowed_extensions': ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm'],
                'max_file_size': 100 * 1024 * 1024,  # 100MB
                'storage_path': 'uploads/videos/{year}/{month}'
            },
            {
                'name': 'audio',
                'description': 'Audio files (MP3, WAV, etc.)',
                'allowed_extensions': ['.mp3', '.wav', '.ogg', '.flac', '.aac'],
                'max_file_size': 25 * 1024 * 1024,  # 25MB
                'storage_path': 'uploads/audio/{year}/{month}'
            },
            {
                'name': 'archives',
                'description': 'Archive files (ZIP, RAR, etc.)',
                'allowed_extensions': ['.zip', '.rar', '.7z', '.tar', '.gz'],
                'max_file_size': 50 * 1024 * 1024,  # 50MB
                'storage_path': 'uploads/archives/{year}/{month}'
            }
        ]
        
        created_categories = []
        for cat_data in categories:
            existing = cls.find_one_by(name=cat_data['name'])
            if not existing:
                category = cls.create(**cat_data)
                created_categories.append(category)
            else:
                created_categories.append(existing)
        
        return created_categories

class File(EnhancedBaseModel):
    """
    File metadata and management.
    
    Attributes:
        user_id: User who uploaded the file
        category_id: File category
        original_filename: Original filename from upload
        filename: Stored filename (may be different from original)
        file_path: Full path to the stored file
        file_size: File size in bytes
        mime_type: MIME type of the file
        file_hash: SHA-256 hash of file content
        upload_session: Session ID for chunked uploads
        is_public: Whether file is publicly accessible
        is_approved: Whether file has been approved (for categories requiring approval)
        download_count: Number of times file has been downloaded
        last_accessed: Last time file was accessed
        expires_at: File expiration date (if temporary)
        metadata: Additional file metadata (EXIF, dimensions, etc.)
        scan_status: Virus scan status
        scan_result: Virus scan result details
    """
    __tablename__ = 'files'
    
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey('file_categories.id'), nullable=True, index=True)
    original_filename = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    mime_type = Column(String(100), nullable=True)
    file_hash = Column(String(64), nullable=False, index=True)  # SHA-256
    upload_session = Column(String(255), nullable=True)  # For chunked uploads
    is_public = Column(Boolean, default=False, nullable=False)
    is_approved = Column(Boolean, default=True, nullable=False)
    download_count = Column(Integer, default=0, nullable=False)
    last_accessed = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    metadata = Column(JSON, default=dict)
    scan_status = Column(String(20), default='pending', nullable=False)  # pending, clean, infected, error
    scan_result = Column(JSON, default=dict)
    
    # Relationships
    user = relationship('Users', backref='files')
    category = relationship('FileCategory', backref='files')
    
    def __repr__(self):
        return f"<File(filename={self.filename}, user_id={self.user_id})>"
    
    @staticmethod
    def calculate_file_hash(file_path: str) -> str:
        """Calculate SHA-256 hash of file content."""
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()
    
    @staticmethod
    def get_mime_type(filename: str) -> str:
        """Get MIME type from filename."""
        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type or 'application/octet-stream'
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename for safe storage."""
        # Remove dangerous characters
        import re
        filename = re.sub(r'[^\w\-_\.]', '_', filename)
        
        # Limit length
        name, ext = os.path.splitext(filename)
        if len(name) > 100:
            name = name[:100]
        
        return f"{name}{ext}"
    
    def get_full_path(self) -> str:
        """Get full filesystem path to the file."""
        storage_root = os.environ.get('STORAGE_ROOT', './storage')
        return os.path.join(storage_root, self.file_path)
    
    def get_url(self, base_url: str = None) -> str:
        """Get URL to access the file."""
        if not base_url:
            base_url = os.environ.get('BASE_URL', 'http://localhost:5000')
        return f"{base_url}/files/{self.id}"
    
    def increment_download_count(self):
        """Increment download counter and update last accessed time."""
        self.download_count += 1
        self.last_accessed = datetime.now(timezone.utc)
        session.commit()
    
    def is_expired(self) -> bool:
        """Check if file has expired."""
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at
    
    def is_accessible_by_user(self, user_id: int) -> bool:
        """Check if user can access this file."""
        # Owner can always access
        if self.user_id == user_id:
            return True
        
        # Public files can be accessed by anyone
        if self.is_public and self.is_approved:
            return True
        
        # Add more permission logic here (groups, shares, etc.)
        return False
    
    def update_scan_status(self, status: str, result: Dict = None):
        """Update virus scan status and result."""
        self.scan_status = status
        if result:
            self.scan_result = result
        session.commit()
    
    @classmethod
    def create_file_record(cls, user_id: int, original_filename: str, 
                          file_path: str, file_size: int, 
                          category_name: str = None, is_public: bool = False,
                          expires_hours: int = None, metadata: Dict = None):
        """
        Create a file record with proper validation and setup.
        
        Args:
            user_id: User uploading the file
            original_filename: Original filename
            file_path: Storage path
            file_size: File size in bytes
            category_name: File category name
            is_public: Whether file is public
            expires_hours: Hours until file expires
            metadata: Additional metadata
            
        Returns:
            File instance
        """
        # Get category
        category = None
        if category_name:
            category = FileCategory.find_one_by(name=category_name)
        
        # Sanitize filename
        filename = cls.sanitize_filename(original_filename)
        
        # Calculate file hash
        full_path = os.path.join(os.environ.get('STORAGE_ROOT', './storage'), file_path)
        file_hash = cls.calculate_file_hash(full_path)
        
        # Get MIME type
        mime_type = cls.get_mime_type(original_filename)
        
        # Check for duplicates
        existing = cls.find_one_by(file_hash=file_hash, user_id=user_id)
        if existing and not existing.is_deleted:
            raise ValueError("File already exists")
        
        # Set expiration
        expires_at = None
        if expires_hours:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
        
        # Determine approval status
        is_approved = True
        if category and category.requires_approval:
            is_approved = False
        
        return cls.create(
            user_id=user_id,
            category_id=category.id if category else None,
            original_filename=original_filename,
            filename=filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=mime_type,
            file_hash=file_hash,
            is_public=is_public,
            is_approved=is_approved,
            expires_at=expires_at,
            metadata=metadata or {}
        )
    
    @classmethod
    def find_by_hash(cls, file_hash: str):
        """Find file by hash."""
        return cls.find_one_by(file_hash=file_hash)
    
    @classmethod
    def find_user_files(cls, user_id: int, category_name: str = None, 
                       include_deleted: bool = False):
        """Find all files for a user."""
        filters = {'user_id': user_id}
        
        if category_name:
            category = FileCategory.find_one_by(name=category_name)
            if category:
                filters['category_id'] = category.id
        
        return cls.find_by(include_deleted=include_deleted, **filters)
    
    @classmethod
    def cleanup_expired(cls):
        """Clean up expired files."""
        expired_files = session.query(cls).filter(
            cls.expires_at < datetime.now(timezone.utc),
            cls.is_deleted == False
        ).all()
        
        cleaned_count = 0
        for file_record in expired_files:
            try:
                # Delete file from filesystem
                full_path = file_record.get_full_path()
                if os.path.exists(full_path):
                    os.remove(full_path)
                
                # Soft delete the record
                file_record.soft_delete()
                cleaned_count += 1
                
            except Exception as e:
                logger.error(f"Error cleaning up expired file {file_record.id}: {e}")
        
        return cleaned_count

class FilePermission(EnhancedBaseModel):
    """
    File permissions for sharing and access control.
    
    Attributes:
        file_id: File being shared
        user_id: User being granted access (null for public permissions)
        granted_by: User who granted the permission
        permission_type: Type of permission (read, write, admin)
        expires_at: When permission expires
        is_active: Whether permission is currently active
        access_count: Number of times permission has been used
        last_used: Last time permission was used
    """
    __tablename__ = 'file_permissions'
    
    file_id = Column(Integer, ForeignKey('files.id'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)  # null = public
    granted_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    permission_type = Column(String(20), default='read', nullable=False)  # read, write, admin
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    access_count = Column(Integer, default=0, nullable=False)
    last_used = Column(DateTime, nullable=True)
    
    # Relationships
    file = relationship('File', backref='permissions')
    user = relationship('Users', foreign_keys=[user_id], backref='file_permissions')
    granter = relationship('Users', foreign_keys=[granted_by])
    
    def is_expired(self) -> bool:
        """Check if permission has expired."""
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at
    
    def is_valid(self) -> bool:
        """Check if permission is valid."""
        return self.is_active and not self.is_expired()
    
    def use_permission(self):
        """Record permission usage."""
        self.access_count += 1
        self.last_used = datetime.now(timezone.utc)
        session.commit()
    
    @classmethod
    def grant_permission(cls, file_id: int, granted_by: int, user_id: int = None,
                        permission_type: str = 'read', expires_hours: int = None):
        """
        Grant file permission to a user.
        
        Args:
            file_id: File ID
            granted_by: User granting permission
            user_id: User receiving permission (null for public)
            permission_type: Type of permission
            expires_hours: Hours until permission expires
            
        Returns:
            FilePermission instance
        """
        expires_at = None
        if expires_hours:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
        
        # Check if permission already exists
        existing = cls.find_one_by(
            file_id=file_id,
            user_id=user_id,
            permission_type=permission_type,
            is_active=True
        )
        
        if existing:
            # Update expiration if needed
            if expires_at and (not existing.expires_at or expires_at > existing.expires_at):
                existing.expires_at = expires_at
                session.commit()
            return existing
        
        return cls.create(
            file_id=file_id,
            user_id=user_id,
            granted_by=granted_by,
            permission_type=permission_type,
            expires_at=expires_at
        )
    
    @classmethod
    def check_permission(cls, file_id: int, user_id: int, permission_type: str = 'read') -> bool:
        """Check if user has permission to access file."""
        # Check specific user permission
        user_permission = cls.find_one_by(
            file_id=file_id,
            user_id=user_id,
            permission_type=permission_type,
            is_active=True
        )
        
        if user_permission and user_permission.is_valid():
            return True
        
        # Check public permission
        public_permission = cls.find_one_by(
            file_id=file_id,
            user_id=None,
            permission_type=permission_type,
            is_active=True
        )
        
        return public_permission and public_permission.is_valid()

class FileVersion(EnhancedBaseModel):
    """
    File versioning for tracking file changes.
    
    Attributes:
        file_id: Original file
        version_number: Version number (1, 2, 3, etc.)
        filename: Filename for this version
        file_path: Storage path for this version
        file_size: File size in bytes
        file_hash: SHA-256 hash of file content
        mime_type: MIME type
        change_description: Description of changes in this version
        replaced_by: ID of version that replaced this one
        is_current: Whether this is the current version
    """
    __tablename__ = 'file_versions'
    
    file_id = Column(Integer, ForeignKey('files.id'), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    file_hash = Column(String(64), nullable=False)
    mime_type = Column(String(100), nullable=True)
    change_description = Column(Text, nullable=True)
    replaced_by = Column(Integer, ForeignKey('file_versions.id'), nullable=True)
    is_current = Column(Boolean, default=False, nullable=False)
    
    # Relationships
    file = relationship('File', backref='versions')
    
    @classmethod
    def create_version(cls, file_id: int, file_path: str, file_size: int,
                      change_description: str = None):
        """
        Create a new version of a file.
        
        Args:
            file_id: Original file ID
            file_path: Path to new version
            file_size: File size
            change_description: Description of changes
            
        Returns:
            FileVersion instance
        """
        # Get the file record
        file_record = File.get(file_id)
        if not file_record:
            raise ValueError("File not found")
        
        # Get current version number
        current_version = session.query(cls).filter(
            cls.file_id == file_id
        ).order_by(cls.version_number.desc()).first()
        
        version_number = (current_version.version_number + 1) if current_version else 1
        
        # Calculate file hash
        full_path = os.path.join(os.environ.get('STORAGE_ROOT', './storage'), file_path)
        file_hash = File.calculate_file_hash(full_path)
        
        # Get MIME type
        mime_type = File.get_mime_type(file_record.filename)
        
        # Mark previous version as not current
        if current_version:
            current_version.is_current = False
            session.commit()
        
        # Create new version
        new_version = cls.create(
            file_id=file_id,
            version_number=version_number,
            filename=file_record.filename,
            file_path=file_path,
            file_size=file_size,
            file_hash=file_hash,
            mime_type=mime_type,
            change_description=change_description,
            is_current=True
        )
        
        # Update main file record
        file_record.file_path = file_path
        file_record.file_size = file_size
        file_record.file_hash = file_hash
        session.commit()
        
        return new_version

# Storage utilities
class StorageManager:
    """Utility class for managing file storage operations."""
    
    @staticmethod
    def ensure_directory(path: str):
        """Ensure directory exists, create if not."""
        Path(path).mkdir(parents=True, exist_ok=True)
    
    @staticmethod
    def get_storage_root() -> str:
        """Get the storage root directory."""
        storage_root = os.environ.get('STORAGE_ROOT', './storage')
        StorageManager.ensure_directory(storage_root)
        return storage_root
    
    @staticmethod
    def generate_unique_filename(original_filename: str, directory: str) -> str:
        """Generate a unique filename to avoid conflicts."""
        name, ext = os.path.splitext(original_filename)
        counter = 1
        
        filename = original_filename
        while os.path.exists(os.path.join(directory, filename)):
            filename = f"{name}_{counter}{ext}"
            counter += 1
        
        return filename
    
    @staticmethod
    def get_file_size(file_path: str) -> int:
        """Get file size in bytes."""
        return os.path.getsize(file_path)
    
    @staticmethod
    def delete_file_safely(file_path: str) -> bool:
        """Safely delete a file."""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            return True
        except Exception:
            return False