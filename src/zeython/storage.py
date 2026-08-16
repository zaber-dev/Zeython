"""File storage: a small backend-agnostic abstraction, local filesystem by
default, S3-compatible object storage as an opt-in extra.

The interesting part isn't the storage backend — it's :func:`store_upload`,
which is where uploads actually get dangerous if you're not careful: client
filenames are untrusted input, so the original name is never used as a
storage path (that's how you get path traversal or overwritten files), and
extension/size are checked before a single byte is written.
"""

from __future__ import annotations

import asyncio
import mimetypes
import re
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from starlette.datastructures import UploadFile

from zeython.exceptions import ValidationException
from zeython.providers import ServiceProvider


@dataclass(frozen=True)
class StoredFile:
    """Metadata returned after a file has been written to storage."""

    key: str  #: storage-relative key, e.g. ``"uploads/3f9a2b1c.png"``
    filename: str  #: original client-supplied filename, sanitized
    content_type: str
    size: int
    url: str  #: public URL, from ``Storage.url(key)``


class Storage(ABC):
    """Abstract file storage backend."""

    @abstractmethod
    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None: ...

    @abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    def url(self, key: str) -> str:
        """A URL clients can use to fetch this key. Does not guarantee it resolves publicly."""


class LocalStorage(Storage):
    """Stores files on the local filesystem, under ``root``.

    Every key is resolved against ``root`` and checked to still be inside
    it — a key like ``"../../etc/passwd"`` raises rather than escaping the
    storage directory.
    """

    def __init__(self, root: str | Path, *, url_prefix: str = "/storage") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.url_prefix = url_prefix.rstrip("/") or "/storage"

    def _resolve(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError(f"Invalid storage key (escapes storage root): {key!r}")
        return path

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._resolve(key).read_bytes)

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        await asyncio.to_thread(path.unlink, True)  # missing_ok=True

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._resolve(key).is_file)

    def url(self, key: str) -> str:
        return f"{self.url_prefix}/{key}"


class S3Storage(Storage):
    """S3-compatible object storage. Requires the ``s3`` extra: ``pip install zeython[s3]``.

    Works against AWS S3 and any S3-compatible service (MinIO, Cloudflare
    R2, DigitalOcean Spaces, ...) by passing ``endpoint_url``.
    """

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

    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )

    async def get(self, key: str) -> bytes:
        def _get() -> bytes:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()  # type: ignore[no-any-return]

        return await asyncio.to_thread(_get)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    async def exists(self, key: str) -> bool:
        def _exists() -> bool:
            from botocore.exceptions import ClientError

            try:
                self._client.head_object(Bucket=self.bucket, Key=key)
                return True
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                    return False
                raise

        return await asyncio.to_thread(_exists)

    def url(self, key: str) -> str:
        return f"{self.public_base_url}/{key}"


_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(filename: str) -> str:
    name = Path(filename).name  # drop any directory components the client sent
    name = _FILENAME_SAFE_RE.sub("_", name).strip("._") or "file"
    return name


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
    """
    filename = _safe_filename(upload.filename or "file")
    extension = Path(filename).suffix.lower().lstrip(".")

    if allowed_extensions is not None and extension not in allowed_extensions:
        allowed = ", ".join(allowed_extensions)
        raise ValidationException({"file": [f"File type '.{extension}' is not allowed. Allowed: {allowed}."]})

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


class StorageServiceProvider(ServiceProvider):
    """Binds a :class:`Storage` backend into the container — local filesystem by default.

    ``.env`` configuration:

    - ``STORAGE_PATH`` — local storage root (default: ``<project>/storage/app``)
    - ``STORAGE_URL_PREFIX`` — default: ``/storage``
    - ``STORAGE_SERVE_LOCALLY`` — mount the storage directory for direct GET
      access during development (default: ``true``; turn off once you serve
      uploads from a CDN/reverse proxy in production)

    For S3, construct and bind an :class:`S3Storage` yourself instead of
    registering this provider::

        app.container.singleton(Storage, lambda: S3Storage("my-bucket"))
    """

    def register(self) -> None:
        root = self.config.get("storage.path", str(self.app.base_path / "storage" / "app"))
        url_prefix = self.config.get("storage.url_prefix", "/storage")
        storage = LocalStorage(root, url_prefix=url_prefix)
        self.container.singleton(Storage, lambda: storage)

    def boot(self) -> None:
        storage = self.container.make(Storage)
        if isinstance(storage, LocalStorage) and bool(self.config.get("storage.serve_locally", True)):
            from starlette.staticfiles import StaticFiles

            self.app.router.mount(storage.url_prefix, StaticFiles(directory=str(storage.root)))


__all__ = [
    "Storage",
    "LocalStorage",
    "S3Storage",
    "StoredFile",
    "store_upload",
    "StorageServiceProvider",
]
