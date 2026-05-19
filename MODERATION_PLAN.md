# MODERATION_PLAN.md

# AI Review Moderation Sidecar — Kế hoạch triển khai chi tiết

**Ngày tạo:** 2026-05-19  
**Phiên bản:** 1.0  
**Tác giả:** Antigravity (AI Architect)

---

## 1. PHÂN TÍCH HIỆN TRẠNG

### 1.1 Cấu trúc hiện tại của `SEP490_Children-s-Toy_AI`

```
SEP490_Children-s-Toy_AI/
├── .env                        # Rỗng — cần điền secrets
├── pyproject.toml              # Rỗng — cần cấu hình
├── requirements.txt            # Rỗng — cần liệt kê dependencies
├── Dockerfile                  # Có sẵn
├── app/
│   ├── main.py                 # Rỗng — entry point chưa có
│   ├── core/
│   │   ├── config.py           # Rỗng
│   │   ├── dependencies.py
│   │   └── security.py
│   ├── embeddings/             # Rỗng — dành cho chatbot embeddings
│   ├── features/
│   │   ├── chatbot/            # Feature chatbot (đã tách sẵn)
│   │   └── moderation/
│   │       ├── api.py          # Rỗng
│   │       ├── models.py       # Rỗng
│   │       ├── repository.py   # Rỗng
│   │       ├── schemas.py      # Rỗng
│   │       └── service.py      # Rỗng
│   ├── llm/
│   │   ├── client.py           # Rỗng — Groq client
│   │   └── prompts.py          # Rỗng
│   ├── schemas/                # Rỗng
│   ├── utils/                  # Rỗng
│   └── vector_db/              # Rỗng — dành cho chatbot RAG
└── tests/                      # Rỗng
```

### 1.2 Đánh giá cấu trúc hiện tại

**Vấn đề:** Cấu trúc hiện tại được thiết kế theo hướng **feature-based** nhưng chưa tách biệt đủ các concern quan trọng:

- Không có thư mục riêng cho **worker/scheduler**
- Không có thư mục riêng cho **external API clients** (Groq, Google Vision tách rời nhau)
- Không có **notification module** riêng
- Thiếu `shared/` để chứa utilities dùng chung (retry logic, logging)
- `moderation/` thiếu sub-module cho text pipeline và image pipeline riêng

**Quyết định:** Giữ nguyên cấu trúc feature-based cấp cao (`app/features/moderation/`) để nhất quán với coding convention của dự án, nhưng **mở rộng** thêm các sub-module còn thiếu.

---

## 2. CẤU TRÚC THƯ MỤC ĐỀ XUẤT (FINAL)

```
SEP490_Children-s-Toy_AI/
├── .env                            # Secrets — KHÔNG commit
├── .env.example                    # Template env — commit được
├── pyproject.toml                  # Project metadata, tool config (pytest, ruff)
├── requirements.txt                # Python dependencies
├── Dockerfile                      # Container build
├── docker-compose.yml              # Local dev stack (app + SQL Server nếu cần)
│
├── app/
│   ├── main.py                     # Entry point: FastAPI app + lifespan (startup/shutdown worker)
│   │
│   ├── core/                       # Cross-cutting concerns
│   │   ├── config.py               # Settings từ env vars (pydantic-settings BaseSettings)
│   │   ├── database.py             # [NEW] pyodbc async connection pool (aioodbc)
│   │   ├── logging.py              # [NEW] Structured logging setup (structlog)
│   │   ├── dependencies.py         # FastAPI DI providers
│   │   └── security.py             # API key / auth middleware
│   │
│   ├── features/
│   │   ├── chatbot/                # Feature chatbot — KHÔNG thay đổi
│   │   └── moderation/             # Feature kiểm duyệt AI
│   │       ├── __init__.py
│   │       ├── api.py              # FastAPI router: health check, manual trigger, webhook
│   │       ├── schemas.py          # Pydantic models: ModerationDecision, ReviewRecord, etc.
│   │       ├── repository.py       # DB layer: fetch Pending, update status, insert logs, notifications
│   │       ├── service.py          # Orchestrator: điều phối text + image pipeline
│   │       │
│   │       ├── text_pipeline/      # [NEW] Sub-module text moderation
│   │       │   ├── __init__.py
│   │       │   ├── prefilter.py    # Bước 1: Rule-based (regex, URL, phone, bank account)
│   │       │   ├── llm_classifier.py  # Bước 2: Groq LLM classifier
│   │       │   └── post_processor.py  # Bước 3: Business rules override
│   │       │
│   │       └── image_pipeline/     # [NEW] Sub-module image moderation
│   │           ├── __init__.py
│   │           ├── prefilter.py    # Bước 1: Pillow + OpenCV + pHash + QR detect
│   │           ├── vision_client.py   # Bước 2: Google Cloud Vision API client
│   │           └── post_processor.py  # Bước 3: Tổng hợp kết quả
│   │
│   ├── llm/
│   │   ├── client.py               # Groq async client wrapper (with retry)
│   │   └── prompts.py              # System prompt templates
│   │
│   ├── worker/                     # [NEW] Background processing
│   │   ├── __init__.py
│   │   ├── scheduler.py            # APScheduler: poll DB mỗi 30s (Option A)
│   │   ├── outbox_consumer.py      # [NEW] Outbox pattern consumer (Option B)
│   │   └── moderation_worker.py    # Worker chính: lấy Pending → chạy pipeline → ghi kết quả
│   │
│   ├── notification/               # [NEW] Notification module
│   │   ├── __init__.py
│   │   └── service.py              # Insert Notification.Deliveries cho Admin/Staff khi ManualReview
│   │
│   └── utils/                      # Shared utilities
│       ├── __init__.py
│       ├── retry.py                # [NEW] Exponential backoff decorator (asyncio)
│       ├── phash.py                # [NEW] pHash computation (imagehash + Pillow)
│       └── image_utils.py          # [NEW] Download image từ URL, format/size check
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Pytest fixtures (mock DB, mock Groq, mock Vision)
│   ├── unit/
│   │   ├── test_text_prefilter.py
│   │   ├── test_text_llm.py
│   │   ├── test_text_postprocess.py
│   │   ├── test_image_prefilter.py
│   │   └── test_image_postprocess.py
│   └── integration/
│       ├── test_moderation_service.py
│       └── test_repository.py
│
└── scripts/
    └── seed_test_data.sql          # [NEW] SQL script tạo data test
```

---

## 3. THỨ TỰ IMPLEMENT (Dependency Order)

### Phase 0 — Nền tảng (không có dependency)

1. `pyproject.toml` — cấu hình project, tools
2. `requirements.txt` — lock dependencies
3. `.env.example` — template env vars
4. `app/core/config.py` — Settings class
5. `app/core/logging.py` — Structured logging
6. `app/core/database.py` — DB connection pool

### Phase 1 — Utilities (phụ thuộc Phase 0)

7. `app/utils/retry.py` — Retry với exponential backoff
8. `app/utils/phash.py` — pHash computation
9. `app/utils/image_utils.py` — Download + validate image từ URL

### Phase 2 — External API Clients (phụ thuộc Phase 0 + 1)

10. `app/llm/prompts.py` — System prompt cho LLM
11. `app/llm/client.py` — Groq async client
12. `app/features/moderation/image_pipeline/vision_client.py` — Google Vision client

### Phase 3 — Moderation Schemas (phụ thuộc Phase 0)

13. `app/features/moderation/schemas.py` — Pydantic models

### Phase 4 — Pipeline Logic (phụ thuộc Phase 1, 2, 3)

14. `app/features/moderation/text_pipeline/prefilter.py`
15. `app/features/moderation/text_pipeline/llm_classifier.py`
16. `app/features/moderation/text_pipeline/post_processor.py`
17. `app/features/moderation/image_pipeline/prefilter.py`
18. `app/features/moderation/image_pipeline/post_processor.py`

### Phase 5 — Repository (phụ thuộc Phase 3 + DB)

19. `app/features/moderation/repository.py` — SQL queries

### Phase 6 — Notification (phụ thuộc Phase 5)

20. `app/notification/service.py` — Insert Deliveries

### Phase 7 — Orchestration (phụ thuộc Phase 4, 5, 6)

21. `app/features/moderation/service.py` — ModerationOrchestrator

### Phase 8 — Worker (phụ thuộc Phase 7)

22. `app/worker/moderation_worker.py`
23. `app/worker/scheduler.py` (Option A — poll)
24. `app/worker/outbox_consumer.py` (Option B — outbox)

### Phase 9 — API + Entry Point (phụ thuộc Phase 8)

25. `app/features/moderation/api.py` — FastAPI router
26. `app/main.py` — App lifespan + router registration

### Phase 10 — Tests

27. Unit tests (text_pipeline, image_pipeline)
28. Integration tests (service + repository)

---

## 4. QUYẾT ĐỊNH THIẾT KẾ QUAN TRỌNG

### 4.1 Framework chính: FastAPI + APScheduler

- **FastAPI** làm web server: cung cấp endpoint health check, manual trigger, webhook (tương lai)
- **APScheduler** chạy trong cùng process để poll DB mỗi 30 giây (Option A)
- Không dùng Celery vì overhead lớn, không cần distributed queue ở giai đoạn này
- Cả 2 Option (poll và outbox) điều khiển bằng `TRIGGER_MODE` trong config

### 4.2 Database Connectivity: aioodbc (async ODBC)

- SQL Server — dùng `aioodbc` (async wrapper của pyodbc) thay vì SQLAlchemy
- Lý do: Đây là sidecar worker đơn giản, không cần ORM nặng; raw SQL dễ debug và optimize hơn
- Connection string từ env: `MSSQL_CONNECTION_STRING`

### 4.3 Xử lý ảnh: Download từ Cloudinary URL

- `ReviewProductImages.ImageURL` trỏ đến Cloudinary URL
- Worker download ảnh về memory (không lưu disk), xử lý bằng Pillow + OpenCV
- Timeout download: 10 giây

### 4.4 Concurrency: Asyncio + semaphore

- Worker xử lý concurrent nhưng có giới hạn: `MAX_CONCURRENT_REVIEWS = 5`
- Dùng `asyncio.Semaphore` để tránh overwhelm external APIs

### 4.5 Idempotency: Lock cơ bản bằng cột `ModerationStatus`

- Trước khi xử lý: UPDATE SET ModerationStatus = 'Processing' WHERE ModerationStatus = 'Pending'
- Nếu UPDATE trả về 0 rows → record đã bị lock bởi instance khác → skip
- Đây là optimistic locking đơn giản, đủ cho MVP

> **Lưu ý:** Column `ModerationStatus` trong DB hiện chỉ có 4 giá trị: Pending, Approved, Rejected, ManualReview. Cần thêm giá trị 'Processing' để lock record khi đang xử lý — **hoặc** dùng một column phụ `IsLocked BIT`. Xem thêm ở Mục 7 (Điểm còn mơ hồ).

### 4.6 Retry Strategy

- External API calls (Groq, Google Vision, image download): tối đa 3 lần, exponential backoff (1s, 2s, 4s)
- Implement bằng `tenacity` library (async-compatible)
- Sau 5 lần thất bại trên cùng 1 record → set ManualReview + ghi log + gửi alert

### 4.7 Image Pipeline — Google Vision gọi 1 lần

- Gộp `SAFE_SEARCH_DETECTION` và `LABEL_DETECTION` trong 1 API call duy nhất (2 units)
- Dùng `google-cloud-vision` SDK async

### 4.8 pHash Storage

- pHash (64-char hex string) lưu vào `ReviewProductImages.PHash`
- Duplicate check: query DB tìm records có pHash giống (hamming distance < 10)
- Hamming distance tính bằng imagehash library

### 4.9 Notification

- Python worker insert trực tiếp vào `Notification.Deliveries` (không qua .NET API)
- Lý do: Tránh coupling — .NET backend không expose internal notification endpoint cho external service
- Cần cẩn thận với FK constraints: `CampaignID`, `TemplateCode` đều NULL (gửi system notification không cần campaign)

---

## 5. HƯỚNG DẪN SETUP MÔI TRƯỜNG

### 5.1 Python Version

```
Python 3.10+
```

### 5.2 Dependencies (requirements.txt sẽ có)

```
# Web framework
fastapi>=0.111.0
uvicorn[standard]>=0.29.0

# Settings management
pydantic-settings>=2.2.0
pydantic>=2.7.0

# Database (SQL Server async)
aioodbc>=0.5.0
pyodbc>=5.1.0

# Scheduling
apscheduler>=3.10.4

# LLM (Groq)
groq>=0.9.0

# Google Cloud Vision
google-cloud-vision>=3.7.0

# Image processing
Pillow>=10.3.0
opencv-python-headless>=4.9.0
imagehash>=4.3.1
httpx>=0.27.0          # Async HTTP client (download images)

# Retry
tenacity>=8.3.0

# Logging
structlog>=24.1.0

# Testing
pytest>=8.2.0
pytest-asyncio>=0.23.0
pytest-mock>=3.14.0

# Dev tools
ruff>=0.4.0             # Linter + formatter
```

### 5.3 .env.example

```env
# === Database ===
MSSQL_CONNECTION_STRING=DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost;DATABASE=SEP490_ToyStore;UID=sa;PWD=yourpassword

# === Groq LLM ===
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.1-8b-instant
GROQ_TEMPERATURE=0
GROQ_MAX_TOKENS=200

# === Google Cloud Vision ===
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# === Worker Config ===
TRIGGER_MODE=POLL                # POLL | OUTBOX
POLL_INTERVAL_SECONDS=30
MAX_CONCURRENT_REVIEWS=5
MAX_RETRY_ATTEMPTS=3
MAX_FAILURE_COUNT_BEFORE_ALERT=5

# === Image Processing Thresholds (calibrate after production data) ===
IMAGE_MIN_SIZE_KB=10
IMAGE_MAX_SIZE_MB=10
IMAGE_BLUR_LV_REJECT_THRESHOLD=1.0
IMAGE_BLUR_LV_MANUAL_REVIEW_THRESHOLD=2.5
IMAGE_PHASH_HAMMING_DISTANCE=10
IMAGE_PHASH_DUPLICATE_MIN_REVIEWS=5

# === Business Rules ===
ACCOUNT_REJECTED_REVIEW_DAYS=30
ACCOUNT_REJECTED_REVIEW_MAX=2
NEW_PRODUCT_DAYS=7
LLM_CONFIDENCE_THRESHOLD=0.70

# === App ===
APP_ENV=development              # development | production
LOG_LEVEL=INFO
```

### 5.4 Cài đặt ODBC Driver (SQL Server)

```bash
# Ubuntu/Debian (trong Docker)
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/ubuntu/20.04/prod.list > /etc/apt/sources.list.d/mssql-release.list
apt-get update
ACCEPT_EULA=Y apt-get install -y msodbcsql17

# macOS
brew tap microsoft/mssql-release
brew install msodbcsql17
```

### 5.5 Chạy local

```bash
# Cài dependencies
pip install -r requirements.txt

# Tạo .env từ template
cp .env.example .env
# Điền secrets vào .env

# Chạy service
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

# Chạy tests
pytest tests/ -v
```

---

## 6. TÍCH HỢP VỚI .NET BACKEND

### 6.1 Luồng hoạt động (Async Sidecar)

```
Customer gửi review
        │
        ▼
.NET Backend API
  - Lưu ReviewProducts (ModerationStatus = 'Pending')
  - Lưu ReviewProductImages (ModerationStatus = 'Pending')
  - Trả response 200 cho customer NGAY LẬP TỨC
  - (Option B): Insert event vào System.DomainEventOutbox
        │
        ▼
Python Sidecar Worker (chạy nền, không chặn user)
  - Poll DB mỗi 30s (Option A) HOẶC consume Outbox (Option B)
  - Chạy text pipeline + image pipeline
  - Cập nhật ModerationStatus trên ReviewProducts/ReviewProductImages
  - Ghi ReviewModerationLogs
  - Nếu ManualReview → Insert Notification.Deliveries cho Admin/Staff
```

### 6.2 Shared Database

- Python service và .NET backend kết nối **cùng SQL Server instance**, **cùng database** `SEP490_ToyStore`
- Python service chỉ đọc/ghi các bảng:
  - **Đọc:** `ReviewProducts`, `ReviewProductImages`, `Accounts`, `Products`, `System.DomainEventOutbox`
  - **Ghi:** `ReviewProducts.ModerationStatus`, `ReviewProductImages.ModerationStatus`, `ReviewProductImages.PHash`, `ReviewModerationLogs`, `Notification.Deliveries`
- Python service **KHÔNG** touch các bảng business logic khác

### 6.3 Option B — DomainEventOutbox

.NET backend cần insert event khi review được tạo:

```sql
INSERT INTO [System].[DomainEventOutbox]
  (EventID, AggregateType, AggregateId, EventType, Payload, OccurredOn)
VALUES
  (NEWID(), 'ReviewProduct', '123', 'ReviewCreated',
   '{"reviewId": 123, "hasImages": true}', GETUTCDATE())
```

Python worker consume bằng cách:

1. Query records chưa được xử lý (`ProcessedOn IS NULL`)
2. Lock với `ProcessingLockId = NEWID()` (optimistic locking)
3. Xử lý → cập nhật `ProcessedOn`

### 6.4 API Endpoints của Python Service

Python service expose các endpoint phụ trợ (không phải critical path):

```
GET  /health                    → Health check (dùng cho Docker/k8s readiness probe)
GET  /moderation/stats          → Thống kê: pending, approved, rejected count
POST /moderation/trigger        → Manual trigger (dùng để test, chỉ gọi được từ internal)
```

---

## 7. CHIẾN LƯỢC KIỂM THỬ

### 7.1 Unit Tests

| Module                             | Test Cases                                                                                            |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `text_pipeline/prefilter.py`       | URL detection, phone regex, bank account regex, short text, spam chars                                |
| `text_pipeline/llm_classifier.py`  | Mock Groq response, invalid JSON fallback, timeout handling                                           |
| `text_pipeline/post_processor.py`  | Confidence threshold, health_concern flag, account rejected count, new product                        |
| `image_pipeline/prefilter.py`      | Invalid format, too small/large, black image, uniform image, blur detection, QR code, pHash duplicate |
| `image_pipeline/post_processor.py` | Adult/violence detection, no toy label                                                                |
| `utils/retry.py`                   | Max retries exceeded, backoff timing                                                                  |

### 7.2 Integration Tests

- Mock DB connection + mock external APIs
- Test full pipeline end-to-end: Pending → Approved/Rejected/ManualReview
- Test notification insert khi ManualReview

### 7.3 Manual Testing

1. Insert review `Pending` trực tiếp vào DB
2. Gọi `POST /moderation/trigger` để trigger worker ngay
3. Kiểm tra `ModerationStatus` đã cập nhật
4. Kiểm tra `ReviewModerationLogs` đã có entry
5. Kiểm tra `Notification.Deliveries` nếu là ManualReview

---

## 8. ĐIỂM CÒN MƠ HỒ — CẦN XÁC NHẬN

### ❓ Câu hỏi 1: Lock record khi xử lý

**Vấn đề:** `ReviewProducts.ModerationStatus` chỉ có 4 giá trị hợp lệ theo DB constraint: `Pending`, `Approved`, `Rejected`, `ManualReview`. Không có `Processing`.

**Phương án A:** Thêm `'Processing'` vào CHECK constraint (cần ALTER TABLE → migration)

```sql
ALTER TABLE ReviewProducts
DROP CONSTRAINT CK_ReviewProducts_ModerationStatus;

ALTER TABLE ReviewProducts
ADD CONSTRAINT CK_ReviewProducts_ModerationStatus CHECK (
    ModerationStatus IN ('Pending', 'Approved', 'Rejected', 'ManualReview', 'Processing')
);
```

**Phương án B:** Thêm cột `IsLocked BIT DEFAULT 0` + `LockedAt DATETIME2` vào `ReviewProducts`

**Phương án C:** Không lock ở DB — dùng in-memory set trong Python worker để track đang xử lý (chỉ an toàn khi chạy single instance)

> **→ Cần xác nhận trước khi code Repository layer**

> **Trả lời:** Tôi đã làm phương án A, đã thêm CHECK constraint vào db rồi

---

### ❓ Câu hỏi 2: Cơ chế trigger mặc định

**Vấn đề:** Plan yêu cầu implement cả Option A (poll) và Option B (outbox), điều khiển bằng config.

**Câu hỏi:** Option B (Outbox) có yêu cầu .NET backend phải insert vào `System.DomainEventOutbox` không? .NET backend hiện đã insert chưa hay cần thêm code phía .NET?

> **→ Nếu .NET chưa insert → Phase đầu chỉ implement Option A (poll), Option B implement sau**
> **Trả lời:** Tạm thời thì cứ implement option A trước

---

### ❓ Câu hỏi 3: Google Cloud Vision credentials

**Vấn đề:** Google Vision dùng service account JSON. Trong môi trường production (Docker container), file JSON phải được mount hoặc dùng environment variable `GOOGLE_APPLICATION_CREDENTIALS_JSON` (base64 encoded).

**Câu hỏi:** Project đã có Google Cloud project và service account chưa? Hay cần tạo mới?

> **Trả lời:** Tôi đã có rồi

---

### ❓ Câu hỏi 4: Xử lý ảnh — Source URL

**Vấn đề:** `ReviewProductImages.ImageURL` là Cloudinary URL. Worker cần download ảnh về để xử lý bằng Pillow/OpenCV.

**Câu hỏi:** Cloudinary URL có cần authenticated access không, hay là public URL?

> **→ Nếu public → download bằng httpx đơn giản**  
> **→ Nếu cần auth → cần Cloudinary API credentials**
> **Trả lời:** Cloudinary URL là public

---

### ❓ Câu hỏi 5: Notification — `CampaignID` và `TemplateCode`

**Vấn đề:** `Notification.Deliveries` có FK đến `Notification.Campaigns` (nullable) và `Notification.Templates` (nullable). Notification cho ManualReview là system-generated, không thuộc campaign nào.

**Câu hỏi:** Có template sẵn trong DB với TemplateCode như `REVIEW_MANUAL_REVIEW` không? Hay insert với `CampaignID = NULL` và `TemplateCode = NULL`, chỉ dùng `Title` + `Message` trực tiếp?

> **→ Nếu không có template sẵn → insert với NULL, dùng TitleOverride/MessageOverride pattern**
> **Trả lời:** Chọn insert với NULL. Ngoài ra tôi có tìm hiểu về IdempotencyKey - quan trọng để tránh spam notification.

---

### ❓ Câu hỏi 6: Threshold calibration

**Vấn đề:** Plan đã ghi rõ "ngưỡng 1.0 và 2.5 cho Laplacian Variance là giá trị khởi đầu, cần calibrate sau production".

**Câu hỏi:** Hiện tại có dataset ảnh review thật để chạy calibration thử không? Hay dùng giá trị mặc định từ config trước?

> **Trả lời:** Dùng giá trị mặc định từ config trước

---

### ❓ Câu hỏi 7: Port và deployment

**Vấn đề:** Python service chạy trên port nào? Có reverse proxy (nginx) không?

**Câu hỏi:** Service này deploy standalone Docker container hay cùng docker-compose với .NET backend?

> **Trả lời:**
> Python service chạy port 8001, .NET backend chạy port khác (https: 7083 / http: 5216).
> Deploy bằng docker-compose riêng, không chung với .NET backend.
> Không có reverse proxy ở giai đoạn này (dev/staging).
> Chỉ .NET backend và Python service cùng network để share SQL Server.

---

## 9. TIMELINE ƯỚC TÍNH

| Phase     | Nội dung                              | Ước tính       |
| --------- | ------------------------------------- | -------------- |
| 0         | Nền tảng (config, DB, logging)        | 0.5 ngày       |
| 1         | Utilities (retry, phash, image_utils) | 0.5 ngày       |
| 2         | External API clients (Groq, Vision)   | 1 ngày         |
| 3         | Schemas                               | 0.5 ngày       |
| 4         | Text pipeline (3 bước)                | 1.5 ngày       |
| 5         | Image pipeline (3 bước)               | 2 ngày         |
| 6         | Repository + Notification             | 1 ngày         |
| 7         | Orchestration (service.py)            | 1 ngày         |
| 8         | Worker + Scheduler                    | 1 ngày         |
| 9         | API + Entry point                     | 0.5 ngày       |
| 10        | Unit + Integration tests              | 2 ngày         |
| **Total** |                                       | **~11.5 ngày** |

---

_Kế hoạch này là deliverable duy nhất của Bước 3. Code implementation sẽ được viết ở các bước tiếp theo theo đúng thứ tự Phase 0 → 10 ở trên._
