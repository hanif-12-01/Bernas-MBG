from __future__ import annotations

import hashlib
import io
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_QC_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
MIN_IMAGE_DIM_PX = 32
MAX_IMAGE_DIM_PX = 8192
MAX_IMAGE_PIXELS = 25_000_000

SERVICE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QC_STORAGE_DIR = SERVICE_ROOT / "private_uploads" / "qc_images"


class ImageSecurityError(ValueError):
    """Raised when an uploaded image fails signature, size, decode, or path containment checks."""


@dataclass(frozen=True)
class SanitizedStoredImage:
    storage_key: str
    original_filename_sanitized: str
    mime_type: str
    size_bytes: int
    width_px: int
    height_px: int
    sha256: str
    exif_stripped: bool


def get_qc_storage_dir() -> Path:
    env_dir = os.getenv("GIZIOPTIMA_QC_STORAGE_DIR")
    base = Path(env_dir) if env_dir else DEFAULT_QC_STORAGE_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


def get_qc_retention_days() -> int:
    raw = os.getenv("GIZIOPTIMA_QC_IMAGE_RETENTION_DAYS", "30")
    try:
        days = int(raw)
        return max(1, min(days, 365))
    except ValueError:
        return 30


def sanitize_filename(raw_name: str) -> str:
    """Strip any directory components and unsafe characters; never used as disk path."""
    leaf = (raw_name or "sample.jpg").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", leaf).strip("._")
    return (cleaned or "sample_image")[:120]


def detect_magic_mime(raw_bytes: bytes) -> str:
    """Validate image file signatures (magic bytes) rather than trusting client extensions."""
    if len(raw_bytes) < 12:
        raise ImageSecurityError("File gambar terlalu kecil atau rusak.")
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        return "image/webp"
    raise ImageSecurityError(
        "Format gambar tidak didukung. Hanya JPEG, PNG, dan WEBP dengan tanda tangan file valid yang diterima."
    )


def validate_strip_exif_and_store(
    raw_bytes: bytes,
    original_filename: str,
) -> SanitizedStoredImage:
    """Validate magic bytes, size, decode with Pillow, strip EXIF metadata, and write to private storage."""
    if not raw_bytes:
        raise ImageSecurityError("File gambar kosong.")
    if len(raw_bytes) > MAX_QC_IMAGE_BYTES:
        raise ImageSecurityError(
            f"Ukuran gambar melebihi batas maksimal ({MAX_QC_IMAGE_BYTES // (1024 * 1024)} MB)."
        )

    detected_mime = detect_magic_mime(raw_bytes)

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
                raise ImageSecurityError(
                    f"Dimensi gambar ({width}x{height}px) di luar batas 32–8192 px per sisi dan 25 megapiksel."
                )
            if getattr(img, "n_frames", 1) != 1:
                raise ImageSecurityError("Unggah satu foto diam untuk setiap sampel.")
            img.verify()
        with Image.open(io.BytesIO(raw_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            width, height = img.size

            # Re-create the image from pixels so format plugins cannot copy source metadata.
            out_buf = io.BytesIO()
            keep_alpha = detected_mime == "image/png" and (
                img.mode in ("RGBA", "LA") or "transparency" in img.info
            )
            mode = "RGBA" if keep_alpha else "RGB"
            clean = Image.new(mode, img.size)
            clean.paste(img.convert(mode))
            if detected_mime == "image/png":
                clean.save(out_buf, format="PNG")
                ext = "png"
                final_mime = "image/png"
            elif detected_mime == "image/webp":
                clean.save(out_buf, format="WEBP", quality=88)
                ext = "webp"
                final_mime = "image/webp"
            else:
                clean.save(out_buf, format="JPEG", quality=88, optimize=True)
                ext = "jpg"
                final_mime = "image/jpeg"
    except ImageSecurityError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageSecurityError("File bukan gambar yang valid atau rusak.") from exc

    sanitized_bytes = out_buf.getvalue()
    if len(sanitized_bytes) > MAX_QC_IMAGE_BYTES:
        raise ImageSecurityError("Foto setelah diproses melebihi 5 MB. Gunakan foto dengan resolusi lebih kecil.")
    sha256_hex = hashlib.sha256(sanitized_bytes).hexdigest()

    # Server-generated UUID filename — prevents any path traversal
    storage_key = f"{uuid4().hex}.{ext}"
    with qc_storage_path(storage_key).open("xb") as stream:
        stream.write(sanitized_bytes)

    return SanitizedStoredImage(
        storage_key=storage_key,
        original_filename_sanitized=sanitize_filename(original_filename),
        mime_type=final_mime,
        size_bytes=len(sanitized_bytes),
        width_px=width,
        height_px=height,
        sha256=sha256_hex,
        exif_stripped=True,
    )


def qc_storage_path(storage_key: str) -> Path:
    """Resolve a generated QC image key within its private storage directory."""
    if not re.fullmatch(r"[a-f0-9]{32}\.(jpg|png|webp)", storage_key):
        raise ImageSecurityError("Identifier file gambar tidak valid.")
    storage_dir = get_qc_storage_dir()
    target_path = (storage_dir / storage_key).resolve()
    if target_path.parent != storage_dir:
        raise ImageSecurityError("Path penyimpanan tidak valid.")
    return target_path


def read_stored_image_bytes(storage_key: str) -> bytes:
    return qc_storage_path(storage_key).read_bytes()


def image_expiry(created_at: datetime, retention_days: int) -> datetime:
    # SQLite may return a naive timestamp for a UTC value.
    timestamp = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    return timestamp + timedelta(days=retention_days)
