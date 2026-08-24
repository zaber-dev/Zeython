# Operations

Health checks, maintenance mode, structured logging, error monitoring (Sentry), caching, and file storage.

## health

A `/up` health-check endpoint -- what load balancers, container orchestrators (Kubernetes liveness/readiness probes), and uptime monitors expect an app to expose. Nothing here is optional infrastructure a real deployment can skip; this is the one thing every one of them needs.

### HealthCheckServiceProvider

```python
HealthCheckServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Registers a health-check endpoint (`/up` by default).

Reports `{"status": "ok", "checks": {...}}` with a `200`, or `{"status": "error", "checks": {...}}` with a `503` if any check fails -- the status code is what a load balancer/orchestrator actually acts on, so a monitoring tool never needs to parse the body just to know whether to route traffic here.

Currently checks database connectivity (a real `SELECT 1`, not just "is a URL configured") when :class:`~zeython.db.Database` is bound in the container -- skipped entirely for an app with no database.

- `HEALTH_CHECK_ENABLED` -- default `true`; set `false` to turn the endpoint off entirely (e.g. if you don't want it publicly reachable and probe something else internally instead).
- `HEALTH_CHECK_PATH` -- default `/up`.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

## maintenance

Maintenance mode: take the whole app offline for a deploy or a risky migration without stopping the process. `zeython down` writes a flag file this middleware checks on every request; `zeython up` removes it. Mirrors Laravel's `artisan down`/`up` closely, including the bypass-secret mechanism for checking the site while it's "down" for everyone else.

### MaintenanceModeMiddleware

```python
MaintenanceModeMiddleware(
    app: Any, *, store_path: Path, secure: bool = False
)
```

Pure ASGI middleware: while the flag file is present, every request gets a `503` -- except one from an allowed IP, or one carrying a valid bypass (a cookie set by visiting `/<secret>` once).

Reads the flag file fresh on every request rather than caching its contents in memory: `zeython up` removing the file must take effect on the very next request, not after a process restart, and the read itself is cheap -- a single `Path.exists()` call is the entire cost once the app isn't down.

The bypass cookie is a bearer credential -- holding it skips maintenance mode entirely for as long as the cookie lives -- so `secure` should be set once the app is served over HTTPS (matches :class:`~zeython.csrf.CsrfMiddleware`/the session cookie's own `secure=` convention); left `False` by default only because a plain local `http://` dev server can't set a `Secure` cookie at all.

Source code in `src/zeython/maintenance.py`

```python
def __init__(self, app: Any, *, store_path: Path, secure: bool = False) -> None:
    self.app = app
    self.store_path = store_path
    self.secure = secure
```

### MaintenanceModeServiceProvider

```python
MaintenanceModeServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Registers :class:`MaintenanceModeMiddleware`.

Safe to always register, the same reasoning :class:`~zeython.request_id.RequestIdServiceProvider` relies on: with no flag file present (the default), every request pays one `Path.exists()` call and nothing else changes. `zeython down` creates that file; `zeython up` removes it -- no process restart needed either way, since the middleware reads it fresh every time.

Register this **last**, after every other provider that adds middleware (`DatabaseServiceProvider` included) -- the most recently registered middleware wraps outermost, and maintenance mode needs to intercept a request before anything else runs, including opening a database session. That matters most exactly when this feature is useful: a migration in progress, a database that's briefly down.

- `MAINTENANCE_STORE_PATH` -- default `storage/framework/down.json`, relative to the project root.
- `MAINTENANCE_SECURE_COOKIE` -- default `false`; set `true` once you're serving over HTTPS, the same convention `SESSION_HTTPS_ONLY`/`session.https_only` uses for the session cookie (see :class:`~zeython.auth.AuthServiceProvider`) -- set this independently since maintenance mode works without auth registered at all.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### maintenance_store_path

```python
maintenance_store_path(
    base_path: Path, configured: str | None
) -> Path
```

Resolve the flag-file path, relative to `base_path` unless already absolute.

Source code in `src/zeython/maintenance.py`

```python
def maintenance_store_path(base_path: Path, configured: str | None) -> Path:
    """Resolve the flag-file path, relative to ``base_path`` unless already absolute."""
    path = Path(configured or DEFAULT_STORE_PATH)
    return path if path.is_absolute() else base_path / path
```

### enable_maintenance_mode

```python
enable_maintenance_mode(
    store_path: Path,
    *,
    message: str | None = None,
    retry: int | None = None,
    allowed_ips: list[str] | None = None,
    secret: str | None = None,
) -> str
```

Write the maintenance flag file. Returns the bypass secret in effect (either the one passed in, or a freshly generated one).

Source code in `src/zeython/maintenance.py`

```python
def enable_maintenance_mode(
    store_path: Path,
    *,
    message: str | None = None,
    retry: int | None = None,
    allowed_ips: list[str] | None = None,
    secret: str | None = None,
) -> str:
    """Write the maintenance flag file. Returns the bypass secret in effect
    (either the one passed in, or a freshly generated one)."""
    secret = secret or secrets.token_urlsafe(16)
    payload: dict[str, Any] = {
        "message": message or "Be right back.",
        "retry": retry,
        "allowed_ips": allowed_ips or [],
        "secret": secret,
        "since": time.time(),
    }
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(payload))
    return secret
```

### disable_maintenance_mode

```python
disable_maintenance_mode(store_path: Path) -> bool
```

Remove the maintenance flag file. Returns `False` if it wasn't there.

Source code in `src/zeython/maintenance.py`

```python
def disable_maintenance_mode(store_path: Path) -> bool:
    """Remove the maintenance flag file. Returns ``False`` if it wasn't there."""
    if not store_path.exists():
        return False
    store_path.unlink()
    return True
```

## logging

Structured (JSON) logging -- an opt-in alternative to the framework's default human-readable log line, for shipping logs to something that parses JSON (Datadog, ELK/Logstash, CloudWatch Logs Insights, Splunk) instead of grepping text. See docs/observability.md.

### JsonFormatter

Bases: `Formatter`

Renders one JSON object per line: `timestamp`, `level`, `logger`, `message`, `request_id` (present whenever :class:`~zeython.request_id.RequestIdServiceProvider` is registered -- `"-"` outside a request, same convention as the default text format), `exception` (the formatted traceback, only when the record carries one), plus any extra fields passed via `logger.info(..., extra={...})`.

## error_monitoring

Optional error monitoring (Sentry): unhandled request exceptions, jobs that exhaust their retries, and scheduled tasks that raise all get reported automatically once configured -- not just logged and forgotten in a file nobody tails. Requires the `sentry` extra: `pip install zeython[sentry]`. See docs/error-monitoring.md.

Deliberately not a hard dependency: every call in this module is a no-op if `sentry_sdk` isn't installed or :func:`init_sentry` was never called, so :func:`report_exception` is always safe to call unconditionally from framework code (:mod:`zeython.exceptions`, :mod:`zeython.queue`, :mod:`zeython.schedule`) without those modules taking on a hard dependency on an optional extra.

### ErrorMonitoringServiceProvider

```python
ErrorMonitoringServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Initializes Sentry from `SENTRY_DSN` -- not registered by default, and a no-op `register()` if `SENTRY_DSN` isn't set, so it's safe to always register even in dev/test environments that don't have one::

```text
# main.py
app.register(ErrorMonitoringServiceProvider(app))
```

Configurable via `.env`:

- `SENTRY_DSN` -- required to do anything at all.
- `SENTRY_TRACES_SAMPLE_RATE` -- default `0.0` (errors only, no performance tracing).
- `APP_ENV`/`app.env` and a git-derived or manually-set release are passed through as `environment`/`release` if you set `SENTRY_RELEASE`.

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### init_sentry

```python
init_sentry(
    dsn: str,
    *,
    environment: str | None = None,
    release: str | None = None,
    traces_sample_rate: float = 0.0,
) -> None
```

Initialize the Sentry SDK. Raises `ImportError` with an install hint if `sentry_sdk` isn't installed -- unlike :func:`report_exception`, this is only ever called once you've explicitly opted in (a non-empty `SENTRY_DSN`), so failing loudly here is correct: a typo'd DSN with a silently-absent SDK would otherwise look like "no errors happened."

Source code in `src/zeython/error_monitoring.py`

```python
def init_sentry(
    dsn: str,
    *,
    environment: str | None = None,
    release: str | None = None,
    traces_sample_rate: float = 0.0,
) -> None:
    """Initialize the Sentry SDK. Raises ``ImportError`` with an install
    hint if ``sentry_sdk`` isn't installed -- unlike :func:`report_exception`,
    this is only ever called once you've explicitly opted in (a non-empty
    ``SENTRY_DSN``), so failing loudly here is correct: a typo'd DSN with a
    silently-absent SDK would otherwise look like "no errors happened."
    """
    global _initialized
    try:
        import sentry_sdk
    except ImportError as exc:
        raise ImportError(
            "Sentry error monitoring requires sentry-sdk. Install it with: pip install zeython[sentry]"
        ) from exc

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_sample_rate,
    )
    _initialized = True
```

### report_exception

```python
report_exception(exc: BaseException, **tags: Any) -> None
```

Report `exc` to Sentry, tagged with `tags` -- a no-op if :func:`init_sentry` was never called (including if `sentry_sdk` isn't installed at all), so every call site here is safe regardless of whether error monitoring is configured.

Source code in `src/zeython/error_monitoring.py`

```python
def report_exception(exc: BaseException, **tags: Any) -> None:
    """Report ``exc`` to Sentry, tagged with ``tags`` -- a no-op if
    :func:`init_sentry` was never called (including if ``sentry_sdk`` isn't
    installed at all), so every call site here is safe regardless of
    whether error monitoring is configured.
    """
    if not _initialized:
        return
    import sentry_sdk

    with sentry_sdk.new_scope() as scope:
        for key, value in tags.items():
            if value is not None:
                scope.set_tag(key, value)
        sentry_sdk.capture_exception(exc)
```

## cache

Caching: an in-memory TTL cache by default, and `remember()` for the common "check cache, else compute and store" pattern.

Like :class:`~zeython.rate_limit.RateLimiter`, the default backend is process-local — correct for a single worker, and a real (if common) limitation once you run multiple processes or machines, where each would cache independently. :class:`RedisCache` is the opt-in, shared alternative.

### Cache

Bases: `ABC`

Get/put/forget keyed values, with optional per-entry expiry.

#### get

```python
get(key: str, default: Any = None) -> Any
```

The value stored for `key`, or `default` if missing or expired.

Source code in `src/zeython/cache.py`

```python
@abstractmethod
async def get(self, key: str, default: Any = None) -> Any:
    """The value stored for ``key``, or ``default`` if missing or expired."""
```

#### put

```python
put(
    key: str, value: Any, *, ttl: float | None = None
) -> None
```

Store `value` under `key`. `ttl` is seconds until expiry; `None` never expires.

Source code in `src/zeython/cache.py`

```python
@abstractmethod
async def put(self, key: str, value: Any, *, ttl: float | None = None) -> None:
    """Store ``value`` under ``key``. ``ttl`` is seconds until expiry; ``None`` never expires."""
```

#### forget

```python
forget(key: str) -> None
```

Remove `key`, if present. A no-op if it isn't.

Source code in `src/zeython/cache.py`

```python
@abstractmethod
async def forget(self, key: str) -> None:
    """Remove ``key``, if present. A no-op if it isn't."""
```

#### has

```python
has(key: str) -> bool
```

Whether `key` currently holds an unexpired value.

Source code in `src/zeython/cache.py`

```python
@abstractmethod
async def has(self, key: str) -> bool:
    """Whether ``key`` currently holds an unexpired value."""
```

#### flush

```python
flush() -> None
```

Remove everything.

Source code in `src/zeython/cache.py`

```python
@abstractmethod
async def flush(self) -> None:
    """Remove everything."""
```

#### remember

```python
remember(
    key: str,
    ttl: float | None,
    callback: Callable[[], Awaitable[Any]],
) -> Any
```

Return the cached value for `key`, computing and storing it via `callback` on a miss.

The common get-or-compute pattern in one call::

```text
posts = await cache.remember("posts:recent", 60, lambda: Post.all())
```

`callback` only runs on a miss — a cache hit never calls it.

Source code in `src/zeython/cache.py`

```python
async def remember(self, key: str, ttl: float | None, callback: Callable[[], Awaitable[Any]]) -> Any:
    """Return the cached value for ``key``, computing and storing it via ``callback`` on a miss.

    The common get-or-compute pattern in one call::

        posts = await cache.remember("posts:recent", 60, lambda: Post.all())

    ``callback`` only runs on a miss — a cache hit never calls it.
    """
    value = await self.get(key, _MISSING)
    if value is not _MISSING:
        return value
    value = await callback()
    await self.put(key, value, ttl=ttl)
    return value
```

### InMemoryCache

```python
InMemoryCache(
    *, clock: Callable[[], float] = time.monotonic
)
```

Bases: `Cache`

A process-local dict cache, correct and simple.

Expired entries are evicted lazily, on access — there's no background sweep, so an entry that's put and never read again sits in memory until the process restarts. Fine for typical cache sizes (route/query results, computed aggregates); not a fit for caching unboundedly many distinct keys.

Source code in `src/zeython/cache.py`

```python
def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
    self._entries: dict[str, _Entry] = {}
    self._lock = asyncio.Lock()
    self._clock = clock
```

### RedisCache

```python
RedisCache(url: str, *, prefix: str = 'zeython:cache:')
```

Bases: `Cache`

A Redis-backed :class:`Cache`, shared across every process/machine pointed at the same Redis — the limitation :class:`InMemoryCache`'s docstring names. Requires the `redis` extra (`pip install zeython[redis]`).

Values are JSON-encoded to cross the network as bytes. Unlike `InMemoryCache`, which can hold any Python object in process memory, only JSON-safe values (`dict`/`list`/`str`/`int`/`float`/ `bool`/`None`) survive the round trip here — cache a model's `to_dict()`, not the model instance itself.

All keys are namespaced under `prefix` (default `"zeython:cache:"`), and :meth:`flush` only clears that namespace (via `SCAN`, not `FLUSHDB`) — safe to point at a Redis instance shared with other subsystems (sessions, rate limiting) without wiping their data too.

Source code in `src/zeython/cache.py`

```python
def __init__(self, url: str, *, prefix: str = "zeython:cache:") -> None:
    try:
        from redis.asyncio import Redis
    except ImportError as exc:
        raise ImportError(
            "RedisCache requires the redis package. Install it with: pip install zeython[redis]"
        ) from exc

    self._client = Redis.from_url(url)
    self._prefix = prefix
```

### CacheServiceProvider

```python
CacheServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Binds a :class:`Cache` into the container. :class:`InMemoryCache` (process-local) by default.

For a shared cache, bind :class:`RedisCache` instead of registering this provider::

```text
app.container.singleton(Cache, lambda: RedisCache(config.get("redis.url")))
```

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

## storage

File storage: a small backend-agnostic abstraction, local filesystem by default, S3-compatible object storage as an opt-in extra.

The interesting part isn't the storage backend — it's :func:`store_upload`, which is where uploads actually get dangerous if you're not careful: client filenames are untrusted input, so the original name is never used as a storage path (that's how you get path traversal or overwritten files), and extension/size are checked before a single byte is written.

### StoredFile

```python
StoredFile(
    key: str,
    filename: str,
    content_type: str,
    size: int,
    url: str,
)
```

Metadata returned after a file has been written to storage.

### Storage

Bases: `ABC`

Abstract file storage backend.

#### url

```python
url(key: str) -> str
```

A URL clients can use to fetch this key. Does not guarantee it resolves publicly.

Source code in `src/zeython/storage.py`

```python
@abstractmethod
def url(self, key: str) -> str:
    """A URL clients can use to fetch this key. Does not guarantee it resolves publicly."""
```

#### temporary_url

```python
temporary_url(key: str, *, expires_in: float = 3600) -> str
```

A signed URL that grants access to `key` for `expires_in` seconds, then stops working -- for a private file (an invoice, a user upload) you don't want reachable from :meth:`url` forever, without standing up your own auth check in front of it.

Source code in `src/zeython/storage.py`

```python
@abstractmethod
def temporary_url(self, key: str, *, expires_in: float = 3600) -> str:
    """A signed URL that grants access to ``key`` for ``expires_in`` seconds, then stops
    working -- for a private file (an invoice, a user upload) you don't want reachable
    from :meth:`url` forever, without standing up your own auth check in front of it.
    """
```

### LocalStorage

```python
LocalStorage(
    root: str | Path,
    *,
    url_prefix: str = "/storage",
    secret_key: str | None = None,
)
```

Bases: `Storage`

Stores files on the local filesystem, under `root`.

Every key is resolved against `root` and checked to still be inside it — a key like `"../../etc/passwd"` raises rather than escaping the storage directory.

Source code in `src/zeython/storage.py`

```python
def __init__(self, root: str | Path, *, url_prefix: str = "/storage", secret_key: str | None = None) -> None:
    self.root = Path(root).resolve()
    self.root.mkdir(parents=True, exist_ok=True)
    self.url_prefix = url_prefix.rstrip("/") or "/storage"
    self._secret_key = secret_key
```

#### verify_temporary_url_token

```python
verify_temporary_url_token(token: str) -> str | None
```

The storage key `token` grants access to, or `None` if it's missing, tampered with, or past its `expires_in`. Used by the `.../signed/{token}` route :class:`StorageServiceProvider` registers -- not meant to be called directly in application code.

Source code in `src/zeython/storage.py`

```python
def verify_temporary_url_token(self, token: str) -> str | None:
    """The storage key ``token`` grants access to, or ``None`` if it's missing,
    tampered with, or past its ``expires_in``. Used by the ``.../signed/{token}``
    route :class:`StorageServiceProvider` registers -- not meant to be called
    directly in application code.
    """
    try:
        data = self._signer().loads(token)
    except BadSignature:
        return None
    if not isinstance(data, dict) or data.get("exp", 0) < time.time():
        return None
    key = data.get("key")
    return key if isinstance(key, str) else None
```

### S3Storage

```python
S3Storage(
    bucket: str,
    *,
    region: str | None = None,
    endpoint_url: str | None = None,
    public_base_url: str | None = None,
)
```

Bases: `Storage`

S3-compatible object storage. Requires the `s3` extra: `pip install zeython[s3]`.

Works against AWS S3 and any S3-compatible service (MinIO, Cloudflare R2, DigitalOcean Spaces, ...) by passing `endpoint_url`.

Source code in `src/zeython/storage.py`

```python
def __init__(
    self,
    bucket: str,
    *,
    region: str | None = None,
    endpoint_url: str | None = None,
    public_base_url: str | None = None,
) -> None:
    try:
        import boto3
    except ImportError as exc:
        raise ImportError(
            "S3Storage requires boto3. Install it with: pip install zeython[s3]"
        ) from exc

    self.bucket = bucket
    self._client = boto3.client("s3", region_name=region, endpoint_url=endpoint_url)
    self.public_base_url = (public_base_url or f"https://{bucket}.s3.amazonaws.com").rstrip("/")
```

### StorageServiceProvider

```python
StorageServiceProvider(app: Application)
```

Bases: `ServiceProvider`

Binds a :class:`Storage` backend into the container — local filesystem by default.

`.env` configuration:

- `STORAGE_PATH` — local storage root (default: `<project>/storage/app`)
- `STORAGE_URL_PREFIX` — default: `/storage`
- `STORAGE_SERVE_LOCALLY` — mount the storage directory for direct GET access during development (default: `true`; turn off once you serve uploads from a CDN/reverse proxy in production)

Also registers the route :meth:`LocalStorage.temporary_url` links point at (`<url_prefix>/signed/<token>`) — independent of `STORAGE_SERVE_LOCALLY`, since that's the point of a signed URL: a way to hand out time-limited access to a specific file without making the whole storage directory public. Requires `APP_SECRET_KEY` to be set (only enforced the first time you actually call `temporary_url()`, not at boot).

For S3, construct and bind an :class:`S3Storage` yourself instead of registering this provider::

```text
app.container.singleton(Storage, lambda: S3Storage("my-bucket"))
```

Source code in `src/zeython/providers.py`

```python
def __init__(self, app: Application) -> None:
    self.app = app
    self.container = app.container
    self.config = app.config
```

### store_upload

```python
store_upload(
    storage: Storage,
    upload: UploadFile,
    *,
    directory: str = "",
    allowed_extensions: tuple[str, ...] | None = None,
    max_size: int | None = None,
) -> StoredFile
```

Validate and persist an uploaded file, returning its stored metadata.

The storage key is a random token, never the client-supplied filename — that's what keeps this safe against path traversal and same-name overwrites. The original filename is preserved in the returned :class:`StoredFile` if you want to show/restore it.

Raises :class:`~zeython.exceptions.ValidationException` (422) if the extension isn't in `allowed_extensions`, the file exceeds `max_size`, or the file is empty.

`allowed_extensions=None` (the default) means unrestricted -- *except* for a small denylist of extensions that are active content a browser will execute if the stored file is ever opened directly (`.html`, `.svg`, `.js`, etc. -- see :data:`_DANGEROUS_EXTENSIONS`), rejected even then. Naming one of those explicitly in `allowed_extensions` opts back in, if you genuinely need it (e.g. user-supplied SVG icons) -- make sure whatever serves it back sets a safe `Content-Type` and `Content-Disposition` first.

Source code in `src/zeython/storage.py`

```python
async def store_upload(
    storage: Storage,
    upload: UploadFile,
    *,
    directory: str = "",
    allowed_extensions: tuple[str, ...] | None = None,
    max_size: int | None = None,
) -> StoredFile:
    """Validate and persist an uploaded file, returning its stored metadata.

    The storage key is a random token, never the client-supplied filename —
    that's what keeps this safe against path traversal and same-name
    overwrites. The original filename is preserved in the returned
    :class:`StoredFile` if you want to show/restore it.

    Raises :class:`~zeython.exceptions.ValidationException` (422) if the
    extension isn't in ``allowed_extensions``, the file exceeds ``max_size``,
    or the file is empty.

    ``allowed_extensions=None`` (the default) means unrestricted -- *except*
    for a small denylist of extensions that are active content a browser
    will execute if the stored file is ever opened directly (``.html``,
    ``.svg``, ``.js``, etc. -- see :data:`_DANGEROUS_EXTENSIONS`), rejected
    even then. Naming one of those explicitly in ``allowed_extensions`` opts
    back in, if you genuinely need it (e.g. user-supplied SVG icons) --
    make sure whatever serves it back sets a safe ``Content-Type`` and
    ``Content-Disposition`` first.
    """
    filename = _safe_filename(upload.filename or "file")
    extension = Path(filename).suffix.lower().lstrip(".")

    if allowed_extensions is not None:
        if extension not in allowed_extensions:
            allowed = ", ".join(allowed_extensions)
            raise ValidationException({"file": [f"File type '.{extension}' is not allowed. Allowed: {allowed}."]})
    elif extension in _DANGEROUS_EXTENSIONS:
        raise ValidationException(
            {
                "file": [
                    f"File type '.{extension}' is not allowed by default because a browser would "
                    "run it as active content. Pass allowed_extensions explicitly to allow it."
                ]
            }
        )

    data = await upload.read()
    size = len(data)

    if size == 0:
        raise ValidationException({"file": ["The uploaded file is empty."]})

    if max_size is not None and size > max_size:
        raise ValidationException({"file": [f"File exceeds the maximum size of {max_size} bytes."]})

    key = f"{secrets.token_hex(16)}.{extension}" if extension else secrets.token_hex(16)
    if directory:
        key = f"{directory.strip('/')}/{key}"

    content_type = upload.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    await storage.put(key, data, content_type=content_type)

    return StoredFile(key=key, filename=filename, content_type=content_type, size=size, url=storage.url(key))
```
