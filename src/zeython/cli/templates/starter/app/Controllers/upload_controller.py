from starlette.responses import JSONResponse

from zeython import Controller, ValidationException
from zeython.storage import Storage, store_upload

ALLOWED_EXTENSIONS = ("png", "jpg", "jpeg", "gif", "webp", "pdf")
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB


class UploadController(Controller):
    """Demonstrates zeython.storage: validated multipart upload, served back locally.

    See docs/storage.md — the file is written under a random key (never the
    client's filename) and validated for extension and size before anything
    touches disk.
    """

    async def store(self, request):
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise ValidationException({"file": ["No file was uploaded."]})

        storage: Storage = request.app.state.container.make(Storage)
        stored = await store_upload(
            storage,
            upload,
            directory="uploads",
            allowed_extensions=ALLOWED_EXTENSIONS,
            max_size=MAX_UPLOAD_SIZE,
        )
        return JSONResponse(
            {
                "filename": stored.filename,
                "url": stored.url,
                "size": stored.size,
                "content_type": stored.content_type,
            },
            status_code=201,
        )
