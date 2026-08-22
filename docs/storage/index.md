# File Storage

`zeython.storage` gives you a small backend-agnostic `Storage` interface (`put`/`get`/`delete`/`exists`/`url`), a local-filesystem implementation used by default, and `store_upload()` — the part that actually matters — which validates and safely persists an uploaded file.

## Why `store_upload()` exists

Client-supplied filenames are untrusted input. Writing a file to `f"uploads/{upload.filename}"` is how you get path traversal (`../../etc/passwd`) or one user silently overwriting another's file. `store_upload()` sanitizes the filename for **display only**, generates a random key for the **actual storage path**, and validates extension/size *before* writing anything.

```python
# app/Controllers/upload_controller.py
from starlette.responses import JSONResponse
from zeython import Controller, ValidationException
from zeython.storage import Storage, store_upload

class UploadController(Controller):
    async def store(self, request):
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise ValidationException({"file": ["No file was uploaded."]})

        storage: Storage = request.app.state.container.make(Storage)
        stored = await store_upload(
            storage, upload,
            directory="uploads",
            allowed_extensions=("png", "jpg", "jpeg", "gif", "webp", "pdf"),
            max_size=5 * 1024 * 1024,   # 5 MB
        )
        return JSONResponse({"url": stored.url, "size": stored.size}, status_code=201)
```

`store_upload()` raises `ValidationException` (→ 422 JSON) for a disallowed extension, an oversized file, or an empty file — same pattern as model validation, so your existing error handling covers it for free.

## Setup

```python
# main.py
from zeython import Application, StorageServiceProvider

app = Application()
app.register(StorageServiceProvider)
```

By default this binds a `LocalStorage` rooted at `storage/app/` and — in development — mounts it for direct `GET` access at `/storage/...` so `stored.url` resolves immediately. Turn that off once uploads are served by a CDN/reverse proxy in production (`STORAGE_SERVE_LOCALLY=false`).

| `.env` key              | Default                 | Meaning                                                            |
| ----------------------- | ----------------------- | ------------------------------------------------------------------ |
| `STORAGE_PATH`          | `<project>/storage/app` | Local storage root.                                                |
| `STORAGE_URL_PREFIX`    | `/storage`              | Prefix used both for `Storage.url()` and the mounted static route. |
| `STORAGE_SERVE_LOCALLY` | `true`                  | Mount the storage directory for direct GET access.                 |

## S3-compatible object storage

Requires the `s3` extra (`pip install zeython[s3]`, adds `boto3`). Works against AWS S3 and anything S3-compatible (MinIO, Cloudflare R2, DigitalOcean Spaces) via `endpoint_url`. Bind it directly instead of registering `StorageServiceProvider`:

```python
from zeython import Application, Storage
from zeython.storage import S3Storage

app = Application()
app.container.singleton(
    Storage,
    lambda: S3Storage("my-bucket", region="us-east-1"),
)
```

## Writing your own backend

Subclass `Storage` and implement `put`/`get`/`delete`/`exists`/`url` — five async methods (`url` is sync, since it's typically pure string formatting). Bind an instance the same way as `S3Storage` above.
