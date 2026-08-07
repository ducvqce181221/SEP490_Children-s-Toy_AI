"""
app/utils/image_utils.py
------------------------
Tiện ích tải ảnh từ URL công cộng (Cloudinary/S3) bất đồng bộ và kiểm tra định dạng/dung lượng ảnh cho hệ thống kiểm duyệt AI.
"""

from __future__ import annotations

import io
from typing import NamedTuple

import httpx
from PIL import Image, UnidentifiedImageError

from app.core.logging import get_logger
from app.utils.retry import async_retry

logger = get_logger(__name__)

# Tập hợp các định dạng hình ảnh hợp lệ được phép xử lý
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
# Thời gian chờ tải ảnh tối đa (giây)
DOWNLOAD_TIMEOUT_S = 10


class ImageLoadResult(NamedTuple):
    """NamedTuple đại diện cho kết quả tải và xác thực hình ảnh."""
    image: Image.Image | None  # Đối tượng ảnh Pillow (None nếu tải thất bại hoặc ảnh lỗi)
    raw_bytes: bytes | None  # Mảng byte nguyên bản của tệp ảnh
    size_bytes: int  # Kích thước tệp tính theo bytes
    error: str | None  # Chuỗi mô tả thông báo lỗi (None nếu nạp ảnh thành công)


@async_retry(
    max_attempts=3, min_wait=1.0, max_wait=4.0,
    exceptions=(httpx.HTTPError, httpx.TimeoutException),
)
async def download_image(url: str) -> bytes:
    """
    Tải dữ liệu byte của tệp ảnh từ URL công cộng bằng httpx bất đồng bộ.
    Tự động thử lại tối đa 3 lần nếu gặp sự cố mạng hoặc Timeout (Async Retry Decorator).
    """
    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_S) as client:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        return response.content


async def load_image_from_url(
    url: str,
    min_size_kb: int = 10,
    max_size_mb: int = 10,
) -> ImageLoadResult:
    """
    Tải ảnh từ URL và thực hiện kiểm tra xác thực toàn diện:
    1. Tải mảng byte ảnh bất đồng bộ.
    2. Kiểm tra dung lượng tệp: Tối thiểu (Mặc định >= 10 KB) và Tối đa (Mặc định <= 10 MB).
    3. Xác thực cấu trúc tệp ảnh bằng Pillow (Verify Magic Bytes & File Integrity).
    4. Kiểm tra định dạng đuôi ảnh có thuộc tập hợp hợp lệ (JPEG, PNG, WEBP).
    5. Nạp toàn bộ dữ liệu pixel vào bộ nhớ (`img.load()`).
    
    Returns:
        ImageLoadResult chứa đối tượng Pillow Image và thông tin trạng thái lỗi.
    """
    min_bytes = min_size_kb * 1024
    max_bytes = max_size_mb * 1024 * 1024

    # Bước 1: Tải dữ liệu byte nguyên bản từ URL
    try:
        raw = await download_image(url)
    except Exception as exc:
        logger.warning("Image download failed", url=url, error=str(exc))
        return ImageLoadResult(image=None, raw_bytes=None, size_bytes=0, error=str(exc))

    size = len(raw)

    # Bước 2: Kiểm tra dung lượng tệp tối thiểu và tối đa
    if size < min_bytes:
        return ImageLoadResult(image=None, raw_bytes=raw, size_bytes=size,
                               error=f"Image too small: {size / 1024:.1f} KB < {min_size_kb} KB")
    if size > max_bytes:
        return ImageLoadResult(image=None, raw_bytes=raw, size_bytes=size,
                               error=f"Image too large: {size / 1024 / 1024:.1f} MB > {max_size_mb} MB")

    # Bước 3: Đọc và xác thực cấu trúc tệp bằng thư viện Pillow
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()  # Kiểm tra tính toàn vẹn của tệp mà chưa đọc dữ liệu pixel
        img = Image.open(io.BytesIO(raw))  # Mở lại stream để sử dụng sau verify
        if img.format not in ALLOWED_FORMATS:
            return ImageLoadResult(image=None, raw_bytes=raw, size_bytes=size,
                                   error=f"Unsupported format: {img.format}. Allowed: {ALLOWED_FORMATS}")
        img.load()  # Nạp dữ liệu pixel vào bộ nhớ
    except UnidentifiedImageError:
        return ImageLoadResult(image=None, raw_bytes=raw, size_bytes=size,
                               error="Cannot identify image file (invalid magic bytes)")
    except Exception as exc:
        return ImageLoadResult(image=None, raw_bytes=raw, size_bytes=size,
                               error=f"Image file corrupt or unreadable: {exc}")

    return ImageLoadResult(image=img, raw_bytes=raw, size_bytes=size, error=None)

