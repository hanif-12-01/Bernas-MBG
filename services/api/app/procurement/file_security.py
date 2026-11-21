from __future__ import annotations

import hashlib
import io
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from app.vision.image_security import (
    MAX_IMAGE_DIM_PX,
    MAX_IMAGE_PIXELS,
    MIN_IMAGE_DIM_PX,
    detect_magic_mime,
    get_qc_storage_dir,
    sanitize_filename,
)

MAX_PROCUREMENT_EVIDENCE_BYTES = 10 * 1024 * 1024  # 10 MB

_SUSPICIOUS_PDF_TOKENS = (
    b"/JavaScript",
    b"/JS",
    b"/Launch",
    b"/OpenAction",
    b"/AA",
    b"/EmbeddedFile",
    b"/RichMedia",
)


class ProcurementFileSecurityError(ValueError):
    """Raised when an uploaded receipt image or PDF fails signature, safety, or containment checks."""


@dataclass(frozen=True)
class SanitizedStoredEvidence:
    storage_key: str
    original_filename_sanitized: str
    mime_type: str
    size_bytes: int
    sha256: str
    exif_stripped: bool


def get_procurement_storage_dir() -> Path:
    env_dir = os.getenv("GIZIOPTIMA_PROCUREMENT_STORAGE_DIR")
    base = Path(env_dir) if env_dir else (get_qc_storage_dir().parent / "procurement_evidence")
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


def evidence_storage_path(storage_key: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", storage_key):
        raise ProcurementFileSecurityError("Storage key bukti pembelian tidak valid.")
    root = get_procurement_storage_dir()
    target = (root / storage_key).resolve()
    if target.parent != root:
        raise ProcurementFileSecurityError("Pelanggaran batas direktori penyimpanan bukti pembelian.")
    return target


def _validate_pdf_bytes(raw_bytes: bytes) -> bytes:
    stripped = raw_bytes.lstrip(b"\xef\xbb\xbf \t\r\n")
    if not stripped.startswith(b"%PDF-"):
        raise ProcurementFileSecurityError("Berkas PDF tidak memiliki header %PDF- yang valid.")
    if b"%%EOF" not in raw_bytes[-2048:] and b"%%EOF" not in raw_bytes:
        raise ProcurementFileSecurityError("Struktur berkas PDF tampak tidak lengkap atau rusak.")
    for token in _SUSPICIOUS_PDF_TOKENS:
        if re.search(rb"(?<![A-Za-z])" + re.escape(token) + rb"(?![A-Za-z])", raw_bytes):
            raise ProcurementFileSecurityError(
                f"Berkas PDF ditolak karena memuat elemen aktif tidak aman ({token.decode('ascii', errors='ignore')})."
            )
    if re.search(rb"(?<![A-Za-z])/Encrypt(?![A-Za-z])", raw_bytes):
        raise ProcurementFileSecurityError("Berkas PDF terenkripsi/terkunci kata sandi tidak didukung.")
    return raw_bytes


def validate_and_store_purchase_evidence(
    raw_bytes: bytes,
    original_filename: str,
) -> SanitizedStoredEvidence:
    """Validate receipt photo (JPEG/PNG/WEBP, EXIF-stripped) or structural-safe PDF up to 10 MB."""
    if not raw_bytes:
        raise ProcurementFileSecurityError("Berkas bukti pembelian kosong.")
    if len(raw_bytes) > MAX_PROCUREMENT_EVIDENCE_BYTES:
        raise ProcurementFileSecurityError("Ukuran bukti pembelian melebihi batas 10 MB.")

    safe_name = sanitize_filename(original_filename or "bukti_pembelian")

    if raw_bytes.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"%PDF-"):
        pdf_bytes = _validate_pdf_bytes(raw_bytes)
        sha = hashlib.sha256(pdf_bytes).hexdigest()
        storage_key = f"{uuid4().hex}.pdf"
        dest = evidence_storage_path(storage_key)
        dest.write_bytes(pdf_bytes)
        return SanitizedStoredEvidence(
            storage_key=storage_key,
            original_filename_sanitized=safe_name,
            mime_type="application/pdf",
            size_bytes=len(pdf_bytes),
            sha256=sha,
            exif_stripped=False,
        )

    try:
        detected_mime = detect_magic_mime(raw_bytes)
    except ValueError as exc:
        raise ProcurementFileSecurityError(
            "Format berkas tidak didukung. Unggah foto JPEG/PNG/WEBP atau PDF yang valid."
        ) from exc

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            width, height = img.size
            if (
                width < MIN_IMAGE_DIM_PX
                or height < MIN_IMAGE_DIM_PX
                or width > MAX_IMAGE_DIM_PX
                or height > MAX_IMAGE_DIM_PX
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise ProcurementFileSecurityError(
                    "Dimensi gambar bukti tidak memenuhi syarat (minimal 32x32 px)."
                )
            transposed = ImageOps.exif_transpose(img)
            out_buf = io.BytesIO()
            if detected_mime == "image/jpeg":
                clean = transposed.convert("RGB")
                clean.save(out_buf, format="JPEG", quality=90, optimize=True)
                ext = "jpg"
            elif detected_mime == "image/png":
                clean = transposed.convert("RGBA" if transposed.mode in ("RGBA", "LA", "P") else "RGB")
                clean.save(out_buf, format="PNG", optimize=True)
                ext = "png"
            else:
                clean = transposed.convert("RGBA" if transposed.mode in ("RGBA", "LA", "P") else "RGB")
                clean.save(out_buf, format="WEBP", quality=90)
                ext = "webp"
    except ProcurementFileSecurityError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ProcurementFileSecurityError("File gambar bukti pembelian rusak atau gagal diproses.") from exc

    sanitized_bytes = out_buf.getvalue()
    sha = hashlib.sha256(sanitized_bytes).hexdigest()
    storage_key = f"{uuid4().hex}.{ext}"
    dest = evidence_storage_path(storage_key)
    dest.write_bytes(sanitized_bytes)
    return SanitizedStoredEvidence(
        storage_key=storage_key,
        original_filename_sanitized=safe_name,
        mime_type=detected_mime,
        size_bytes=len(sanitized_bytes),
        sha256=sha,
        exif_stripped=True,
    )


def read_purchase_evidence_bytes(storage_key: str) -> bytes:
    path = evidence_storage_path(storage_key)
    if not path.is_file():
        raise ProcurementFileSecurityError("Berkas bukti pembelian tidak ditemukan di penyimpanan.")
    return path.read_bytes()
