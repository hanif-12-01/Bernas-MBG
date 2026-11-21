from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.ingestion.csv_parser import MAX_CSV_BYTES
from app.procurement.file_security import MAX_PROCUREMENT_EVIDENCE_BYTES
from app.vision.image_security import MAX_QC_IMAGE_BYTES

MAX_QC_UPLOAD_BODY = MAX_QC_IMAGE_BYTES + 128 * 1024
MAX_PROCUREMENT_UPLOAD_BODY = MAX_PROCUREMENT_EVIDENCE_BYTES + 128 * 1024
MAX_SINGLE_CSV_UPLOAD_BODY = MAX_CSV_BYTES + 128 * 1024
MAX_DATASET_UPLOAD_BODY = 4 * MAX_CSV_BYTES + 128 * 1024


class UploadBodyLimitMiddleware:
    """Bound the multipart request before the form parser can spool its files."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "").rstrip("/")
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        if (path.startswith("/api/v1/qc/inspections/") or path.startswith("/api/v1/incidents/")) and path.endswith("/images"):
            limit = MAX_QC_UPLOAD_BODY
            message = "Permintaan unggah terlalu besar. Pilih satu foto hingga 5 MB."
        elif path.startswith("/api/v1/procurement/documents/") and path.endswith("/evidence"):
            limit = MAX_PROCUREMENT_UPLOAD_BODY
            message = "Permintaan unggah bukti pembelian terlalu besar. Batas maksimal 10 MB."
        elif path in {"/api/v1/inventory/transactions/import", "/api/v1/market-references/import"}:
            limit = MAX_SINGLE_CSV_UPLOAD_BODY
            message = "Permintaan unggah CSV terlalu besar. Batasnya 2 MB."
        elif path == "/api/v1/datasets/import":
            limit = MAX_DATASET_UPLOAD_BODY
            message = "Permintaan unggah terlalu besar. Batasnya 2 MB untuk setiap berkas CSV."
        else:
            await self.app(scope, receive, send)
            return

        length = Headers(scope=scope).get("content-length", "")
        if length.isascii() and length.isdecimal() and (len(length) > 12 or int(length) > limit):
            await JSONResponse({"detail": message}, status_code=413)(scope, receive, send)
            return

        received_bytes = 0

        async def limited_receive() -> Message:
            nonlocal received_bytes
            event = await receive()
            if event["type"] == "http.request":
                received_bytes += len(event.get("body", b""))
                if received_bytes > limit:
                    raise HTTPException(status_code=413, detail=message)
            return event

        await self.app(scope, limited_receive, send)
