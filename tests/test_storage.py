from pathlib import Path

import pytest
from starlette.responses import JSONResponse

from zeython.application import Application
from zeython.config import Config
from zeython.exceptions import ValidationException
from zeython.storage import LocalStorage, S3Storage, Storage, StorageServiceProvider, store_upload
from zeython.testing import client

# -- LocalStorage -----------------------------------------------------------------


async def test_put_get_roundtrip(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    await storage.put("hello.txt", b"hello world")

    assert await storage.get("hello.txt") == b"hello world"
    assert await storage.exists("hello.txt")


async def test_delete_removes_file(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    await storage.put("hello.txt", b"hello world")
    await storage.delete("hello.txt")

    assert not await storage.exists("hello.txt")


async def test_delete_is_idempotent(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    await storage.delete("never-existed.txt")  # must not raise


async def test_exists_false_for_missing_key(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    assert not await storage.exists("nope.txt")


async def test_url_uses_configured_prefix(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path, url_prefix="/files")
    assert storage.url("a/b.png") == "/files/a/b.png"


async def test_put_creates_nested_directories(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    await storage.put("a/b/c.txt", b"nested")
    assert await storage.get("a/b/c.txt") == b"nested"


def test_path_traversal_key_is_rejected(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        storage._resolve("../../etc/passwd")


def test_absolute_path_key_is_rejected(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        storage._resolve("/etc/passwd")


# -- LocalStorage.temporary_url ----------------------------------------------------


def test_temporary_url_without_secret_key_raises_helpful_error(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(RuntimeError, match="requires a secret_key"):
        storage.temporary_url("secret.pdf")


def test_verify_temporary_url_token_round_trips(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path, secret_key="test-secret")
    url = storage.temporary_url("secret.pdf", expires_in=3600)
    token = url.rsplit("/", 1)[-1]

    assert storage.verify_temporary_url_token(token) == "secret.pdf"


def test_verify_temporary_url_token_rejects_expired_token(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path, secret_key="test-secret")
    url = storage.temporary_url("secret.pdf", expires_in=-1)  # already expired
    token = url.rsplit("/", 1)[-1]

    assert storage.verify_temporary_url_token(token) is None


def test_verify_temporary_url_token_rejects_tampered_token(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path, secret_key="test-secret")
    url = storage.temporary_url("secret.pdf")
    token = url.rsplit("/", 1)[-1]

    assert storage.verify_temporary_url_token(token + "x") is None


def test_verify_temporary_url_token_rejects_garbage(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path, secret_key="test-secret")
    assert storage.verify_temporary_url_token("not-a-real-token") is None


def test_different_secret_keys_do_not_cross_verify(tmp_path: Path) -> None:
    signer = LocalStorage(tmp_path, secret_key="secret-a")
    verifier = LocalStorage(tmp_path, secret_key="secret-b")
    token = signer.temporary_url("secret.pdf").rsplit("/", 1)[-1]

    assert verifier.verify_temporary_url_token(token) is None


# -- Signed URL: full HTTP round-trip ------------------------------------------------


async def test_signed_url_serves_the_file_over_http(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"STORAGE_PATH={tmp_path / 'storage'}\nAPP_SECRET_KEY=test-secret\n")
    app = Application(Config.load(tmp_path))
    app.register(StorageServiceProvider)

    storage: Storage = app.container.make(Storage)
    await storage.put("private/report.txt", b"confidential contents")

    async with client(app) as http:
        url = storage.temporary_url("private/report.txt")  # type: ignore[union-attr]
        response = await http.get(url)

    assert response.status_code == 200
    assert response.content == b"confidential contents"


async def test_signed_url_rejects_expired_token_with_404(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"STORAGE_PATH={tmp_path / 'storage'}\nAPP_SECRET_KEY=test-secret\n")
    app = Application(Config.load(tmp_path))
    app.register(StorageServiceProvider)

    storage: Storage = app.container.make(Storage)
    await storage.put("private/report.txt", b"confidential contents")

    async with client(app) as http:
        url = storage.temporary_url("private/report.txt", expires_in=-1)  # type: ignore[union-attr]
        response = await http.get(url)

    assert response.status_code == 404


async def test_signed_url_rejects_unknown_token_with_404(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"STORAGE_PATH={tmp_path / 'storage'}\nAPP_SECRET_KEY=test-secret\n")
    app = Application(Config.load(tmp_path))
    app.register(StorageServiceProvider)

    async with client(app) as http:
        response = await http.get("/storage/signed/not-a-real-token")

    assert response.status_code == 404


async def test_signed_url_forces_download_for_browser_renderable_content(tmp_path: Path) -> None:
    # Defense in depth for a file that reached storage some other way than
    # store_upload()'s own extension check (a pre-existing file, an
    # explicit allowed_extensions opt-in) -- the signed-download endpoint
    # must never let a browser render stored content as HTML/SVG/JS
    # directly in this app's origin.
    (tmp_path / ".env").write_text(f"STORAGE_PATH={tmp_path / 'storage'}\nAPP_SECRET_KEY=test-secret\n")
    app = Application(Config.load(tmp_path))
    app.register(StorageServiceProvider)

    storage: Storage = app.container.make(Storage)
    await storage.put("uploaded.html", b"<script>alert(document.cookie)</script>")

    async with client(app) as http:
        url = storage.temporary_url("uploaded.html")  # type: ignore[union-attr]
        response = await http.get(url)

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment")


async def test_signed_url_route_is_not_shadowed_by_static_mount(tmp_path: Path) -> None:
    """The plain StaticFiles mount at /storage/* must not intercept /storage/signed/*."""
    (tmp_path / ".env").write_text(f"STORAGE_PATH={tmp_path / 'storage'}\nAPP_SECRET_KEY=test-secret\n")
    app = Application(Config.load(tmp_path))
    app.register(StorageServiceProvider)

    storage: Storage = app.container.make(Storage)
    await storage.put("public.txt", b"public contents")

    async with client(app) as http:
        # The plain static route still works alongside the signed one.
        plain = await http.get(storage.url("public.txt"))
        signed = await http.get(storage.temporary_url("public.txt"))  # type: ignore[union-attr]

    assert plain.status_code == 200
    assert signed.status_code == 200


# -- S3Storage (import guard only; no live AWS calls) -----------------------------


def test_s3_storage_without_boto3_raises_helpful_error() -> None:
    with pytest.raises(ImportError, match="pip install zeython\\[s3\\]"):
        S3Storage("some-bucket")


# -- store_upload -------------------------------------------------------------------


class _FakeUpload:
    def __init__(self, filename: str, data: bytes, content_type: str | None = None) -> None:
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self) -> bytes:
        return self._data


async def test_store_upload_writes_file_and_returns_metadata(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    upload = _FakeUpload("photo.png", b"\x89PNG-fake-bytes", content_type="image/png")

    stored = await store_upload(storage, upload, directory="avatars")

    assert stored.filename == "photo.png"
    assert stored.size == len(b"\x89PNG-fake-bytes")
    assert stored.key.startswith("avatars/")
    assert stored.key.endswith(".png")
    assert await storage.get(stored.key) == b"\x89PNG-fake-bytes"


async def test_store_upload_rejects_disallowed_extension(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    upload = _FakeUpload("payload.exe", b"data")

    with pytest.raises(ValidationException) as excinfo:
        await store_upload(storage, upload, allowed_extensions=("png", "jpg"))
    assert "file" in excinfo.value.errors


async def test_store_upload_rejects_dangerous_extensions_even_with_no_allowlist(tmp_path: Path) -> None:
    # Regression guard: allowed_extensions=None ("unrestricted") used to
    # mean genuinely unrestricted, including .html/.svg/.js -- a stored
    # XSS vector if the upload is ever served back and opened directly
    # (the static mount, a signed URL, a CDN in front of the same bucket).
    storage = LocalStorage(tmp_path)

    for filename in ("payload.html", "payload.svg", "payload.js"):
        upload = _FakeUpload(filename, b"<script>alert(1)</script>")
        with pytest.raises(ValidationException) as excinfo:
            await store_upload(storage, upload)
        assert "file" in excinfo.value.errors


async def test_store_upload_allows_a_dangerous_extension_when_explicitly_named(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    upload = _FakeUpload("icon.svg", b"<svg></svg>")

    stored = await store_upload(storage, upload, allowed_extensions=("svg",))

    assert stored.key.endswith(".svg")


async def test_store_upload_rejects_oversized_file(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    upload = _FakeUpload("big.txt", b"x" * 100)

    with pytest.raises(ValidationException):
        await store_upload(storage, upload, max_size=10)


async def test_store_upload_rejects_empty_file(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    upload = _FakeUpload("empty.txt", b"")

    with pytest.raises(ValidationException):
        await store_upload(storage, upload)


async def test_store_upload_sanitizes_directory_traversal_in_filename(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    upload = _FakeUpload("../../etc/passwd", b"data")

    stored = await store_upload(storage, upload)

    assert "/" not in stored.filename
    assert ".." not in stored.filename


# -- Full HTTP round-trip: upload then fetch back --------------------------------


async def test_upload_and_serve_over_http(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"STORAGE_PATH={tmp_path / 'storage'}\n")
    app = Application(Config.load(tmp_path))
    app.register(StorageServiceProvider)

    @app.post("/uploads")
    async def upload_route(request):
        storage: Storage = request.app.state.container.make(Storage)
        form = await request.form()
        stored = await store_upload(storage, form["file"], directory="uploads")
        return JSONResponse({"url": stored.url, "size": stored.size}, status_code=201)

    async with client(app) as http:
        response = await http.post(
            "/uploads",
            files={"file": ("note.txt", b"hello from a real multipart request", "text/plain")},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["size"] == len(b"hello from a real multipart request")

        download = await http.get(body["url"])
        assert download.status_code == 200
        assert download.content == b"hello from a real multipart request"
