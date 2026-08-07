# ------------------------------------------------------------------------------
# app/core/logging.py
# ------------------------------------------------------------------------------
# Cấu hình nhật ký hệ thống dạng cấu trúc (Structured Logging) bằng thư viện structlog.
# Gọi hàm setup_logging() một lần duy nhất khi ứng dụng FastAPI khởi động.
# ------------------------------------------------------------------------------

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


# Hàm thiết lập cấu hình ghi log định dạng JSON hoặc Console tùy theo môi trường (DEBUG/INFO)
def setup_logging(log_level: str = "INFO") -> None:
    # Lấy level log tương ứng từ chuỗi cấu hình
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Cấu hình logging tiêu chuẩn xuất ra stdout
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    # Giảm bớt log thừa từ uvicorn.access và apscheduler
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    # Các bộ xử lý dữ liệu log chung (Processor Chain)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,  # Trích xuất biến ngữ cảnh async
        structlog.stdlib.add_logger_name,         # Thêm tên logger
        structlog.stdlib.add_log_level,           # Thêm mức độ log (INFO, ERROR...)
        structlog.processors.TimeStamper(fmt="iso"), # Đánh dấu thời gian chuẩn ISO 8601
        structlog.processors.StackInfoRenderer(),  # Hiển thị thông tin StackTrace nếu có
    ]

    # Cấu hình structlog gắn vào thư viện logging mặc định của Python
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Định dạng đầu ra: Dạng màu sắc Console khi DEBUG, dạng JSON khi chạy Production/INFO
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer()
        if log_level.upper() == "DEBUG"
        else structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level)


# Hàm tiện ích lấy logger theo tên module để sử dụng trong toàn bộ hệ thống
def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)

