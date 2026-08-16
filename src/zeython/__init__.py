"""Zeython: an async-first, batteries-included MVC framework for Python."""

from zeython.ai import AI, AIResponse, AIServiceProvider, AnthropicAI, EchoAI
from zeython.api_auth import (
    ApiAuthServiceProvider,
    TokenManager,
    current_api_user,
    require_api_auth,
)
from zeython.application import Application
from zeython.auth import (
    Authenticatable,
    AuthManager,
    AuthServiceProvider,
    current_user,
    login,
    logout,
    require_auth,
)
from zeython.authorization import AuthorizationServiceProvider, Gate, authorize
from zeython.cache import Cache, CacheServiceProvider, InMemoryCache, RedisCache
from zeython.config import Config
from zeython.console import Command
from zeython.container import Container
from zeython.db import Database, Model, Page
from zeython.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    HTTPException,
    MethodNotAllowedException,
    NotFoundException,
    TooManyRequestsException,
    UnauthorizedException,
    ValidationException,
)
from zeython.hashing import hash_password, verify_password
from zeython.mail import LogMailer, Mailer, MailServiceProvider, Message, SmtpMailer
from zeython.openapi import OpenApiServiceProvider, describe, generate_openapi, model_schema
from zeython.providers import (
    CorsServiceProvider,
    DatabaseServiceProvider,
    RouteServiceProvider,
    ServiceProvider,
    ViewServiceProvider,
)
from zeython.queue import (
    InMemoryQueue,
    Job,
    Queue,
    QueueServiceProvider,
    SyncQueue,
    dispatch,
)
from zeython.rate_limit import (
    InMemoryRateLimiter,
    RateLimiter,
    RateLimitResult,
    RateLimitServiceProvider,
    RedisRateLimiter,
    client_ip,
    throttle,
)
from zeython.routing import Controller, Router
from zeython.storage import (
    LocalStorage,
    S3Storage,
    Storage,
    StorageServiceProvider,
    StoredFile,
    store_upload,
)
from zeython.validation import Rule, email, matches, max_length, min_length, one_of, required
from zeython.views import Views, render

__version__ = "2.0.0a1"

__all__ = [
    "AI",
    "AIResponse",
    "AnthropicAI",
    "EchoAI",
    "AIServiceProvider",
    "Application",
    "Config",
    "Command",
    "Container",
    "Controller",
    "Database",
    "Model",
    "Page",
    "Router",
    "ServiceProvider",
    "DatabaseServiceProvider",
    "RouteServiceProvider",
    "ViewServiceProvider",
    "CorsServiceProvider",
    "Views",
    "render",
    "Cache",
    "InMemoryCache",
    "RedisCache",
    "CacheServiceProvider",
    "Storage",
    "LocalStorage",
    "S3Storage",
    "StoredFile",
    "store_upload",
    "StorageServiceProvider",
    "RateLimiter",
    "InMemoryRateLimiter",
    "RedisRateLimiter",
    "RateLimitResult",
    "throttle",
    "client_ip",
    "RateLimitServiceProvider",
    "Job",
    "Queue",
    "InMemoryQueue",
    "SyncQueue",
    "dispatch",
    "QueueServiceProvider",
    "Mailer",
    "Message",
    "LogMailer",
    "SmtpMailer",
    "MailServiceProvider",
    "describe",
    "model_schema",
    "generate_openapi",
    "OpenApiServiceProvider",
    "Authenticatable",
    "AuthManager",
    "AuthServiceProvider",
    "login",
    "logout",
    "current_user",
    "require_auth",
    "Gate",
    "authorize",
    "AuthorizationServiceProvider",
    "TokenManager",
    "current_api_user",
    "require_api_auth",
    "ApiAuthServiceProvider",
    "hash_password",
    "verify_password",
    "HTTPException",
    "BadRequestException",
    "UnauthorizedException",
    "ForbiddenException",
    "NotFoundException",
    "MethodNotAllowedException",
    "ConflictException",
    "ValidationException",
    "TooManyRequestsException",
    "Rule",
    "required",
    "email",
    "min_length",
    "max_length",
    "one_of",
    "matches",
    "__version__",
]
