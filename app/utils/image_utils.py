"""
app/utils/image_utils.py
------------------------
Download images from public URLs (Cloudinary) and basic format/size validation.
"""

from __future__ import annotations

import io
from typing import NamedTuple

import httpx
from PIL import Image, UnidentifiedImageError

from app.core.logging import get_logger
from app.utils.retry import async_retry

logger = get_logger(__name__)

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
DOWNLOAD_TIMEOUT_S = 10


class ImageLoadResult(NamedTuple):
    image: Image.Image | None
    raw_bytes: bytes | None
    size_bytes: int
    error: str | None


@async_retry(
    max_attempts=3, min_wait=1.0, max_wait=4.0,
    exceptions=(httpx.HTTPError, httpx.TimeoutException),
)
async def download_image(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_S) as client:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        return response.content


async def load_image_from_url(
    url: str,
    min_size_kb: int = 10,
    max_size_mb: int = 10,
) -> ImageLoadResult:
    min_bytes = min_size_kb * 1024
    max_bytes = max_size_mb * 1024 * 1024

    try:
        raw = await download_image(url)
    except Exception as exc:
        logger.warning("Image download failed", url=url, error=str(exc))
        return ImageLoadResult(image=None, raw_bytes=None, size_bytes=0, error=str(exc))

    size = len(raw)

    if size < min_bytes:
        return ImageLoadResult(image=None, raw_bytes=raw, size_bytes=size,
                               error=f"Image too small: {size / 1024:.1f} KB < {min_size_kb} KB")
    if size > max_bytes:
        return ImageLoadResult(image=None, raw_bytes=raw, size_bytes=size,
                               error=f"Image too large: {size / 1024 / 1024:.1f} MB > {max_size_mb} MB")

    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
        img = Image.open(io.BytesIO(raw))
        if img.format not in ALLOWED_FORMATS:
            return ImageLoadResult(image=None, raw_bytes=raw, size_bytes=size,
                                   error=f"Unsupported format: {img.format}. Allowed: {ALLOWED_FORMATS}")
        img.load()
    except UnidentifiedImageError:
        return ImageLoadResult(image=None, raw_bytes=raw, size_bytes=size,
                               error="Cannot identify image file (invalid magic bytes)")
    except Exception as exc:
        return ImageLoadResult(image=None, raw_bytes=raw, size_bytes=size,
                               error=f"Image file corrupt or unreadable: {exc}")

    return ImageLoadResult(image=img, raw_bytes=raw, size_bytes=size, error=None)
