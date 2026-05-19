Bạn là một Python backend architect senior. Nhiệm vụ của bạn là lên kế hoạch
triển khai service AI kiểm duyệt tự động cho tính năng review sản phẩm trên
website thương mại điện tử bán đồ chơi trẻ em.

## BỐI CẢNH

Ứng dụng .NET chính đã xử lý toàn bộ luồng review sản phẩm (gửi, hiển thị,
quản lý) và đang hoạt động bình thường. Service Python này đóng vai trò là
một "sidecar moderation worker" — KHÔNG thay thế .NET backend. Nó:

- Lắng nghe review mới (text + ảnh) qua queue hoặc polling DB
- Chạy pipeline kiểm duyệt AI
- Ghi kết quả ngược lại SQL Server (ReviewModerationLogs, cập nhật
  ModerationStatus trên ReviewProducts / ReviewProductImages)
- Gửi alert cho staff khi có review cần xem xét thủ công (ManualReview)

---

## DATABASE SCHEMA (Các bảng liên quan)

### ReviewProducts

- ReviewID, AccountID, ProductID, OrderID
- Rating (1-5), Comment (NVARCHAR 500)
- ModerationStatus: 'Pending' | 'Approved' | 'Rejected' | 'ManualReview'
- IsDeleted, CreatedAt, UpdatedAt

### ReviewProductImages

### ReviewModerationLogs

### Accounts

### System.DomainEventOutbox (cơ chế trigger tùy chọn)

---

## LOGIC KIỂM DUYỆT

### TEXT PIPELINE (3 bước, chạy tuần tự, dừng sớm nếu bị reject)

**Bước 1 — Rule-based Pre-filter (không dùng AI, < 1ms)**
Block ngay lập tức nếu:

- Số ký tự có nghĩa (chữ + số) < 5
- Spam ký tự lặp: hơn 70% là cùng 1 ký tự và độ dài > 10
- Chứa URL: https://, www., bit.ly, tinyurl
- Chứa số điện thoại Việt Nam: 0[0-9]{8,9} hoặc +84...
- Chứa số tài khoản ngân hàng: \b\d{9,14}\b
  → Kết quả: Rejected. KHÔNG gọi LLM.

**Bước 2 — LLM Classifier**

- Model: llama-3.1-8b-instant qua Groq
- temperature = 0 (kết quả ổn định, không random)
- max_tokens = 200
- Chỉ trả về JSON có cấu trúc:
  {
  "decision": "APPROVED" | "REJECTED" | "MANUAL_REVIEW",
  "confidence": float 0.0-1.0,
  "category": "clean" | "spam" | "offensive" | "competitor_ad" |
  "health_concern" | "fake_product" | "profanity_mild" | "ambiguous",
  "flags": [string],
  "reason": "Giải thích ngắn bằng tiếng Việt cho staff"
  }
- Nếu response của LLM không parse được JSON → mặc định MANUAL_REVIEW (an toàn)

Context cho system prompt: Nền tảng bán đồ chơi trẻ em Việt Nam, ưu tiên bảo
vệ trẻ em nhưng KHÔNG over-censor feedback thật của khách hàng. Chửi thề nhẹ
kèm feedback thật = MANUAL_REVIEW, không phải REJECTED.

**Bước 3 — Post-process Business Rules**
Override quyết định của AI nếu:

- confidence < 0.70 → ép về MANUAL_REVIEW
- flags chứa "health_concern" → ép về MANUAL_REVIEW (an toàn sức khỏe trẻ em)
- Tài khoản có >= 2 review bị Rejected trong 30 ngày gần nhất
  → hạ APPROVED xuống MANUAL_REVIEW
- Sản phẩm được tạo trong vòng 7 ngày gần nhất
  → hạ APPROVED xuống MANUAL_REVIEW

---

### IMAGE PIPELINE (3 bước, chạy tuần tự, dừng sớm nếu bị reject)

**Bước 1 — Pre-filter (không dùng AI, hoàn toàn local)**

- Validate định dạng file: chỉ chấp nhận jpg, jpeg, png, webp
- Validate kích thước: reject nếu < 10KB (ảnh trống/lỗi) hoặc > 10MB
- Dùng Pillow đọc và verify nội dung file thật (magic bytes):
  - Nếu file không đọc được hoặc không phải ảnh thật → Rejected
  - Gọi image.verify() để phát hiện file ảnh bị corrupt
- Dùng OpenCV kiểm tra chất lượng ảnh:
  - Chuyển sang grayscale, tính mean brightness và standard deviation
  - mean < 20 → ảnh đen → Rejected
  - std_dev < 10 → ảnh đồng màu, không có nội dung → Rejected
  - Resize ảnh về 512x512 trước khi tính Laplacian Variance để loại bỏ
    ảnh hưởng của độ phân giải gốc
  - Tính LV_normalized = Laplacian Variance / (mean_brightness + 1)
    để loại bỏ ảnh hưởng của độ sáng lên kết quả
  - LV_normalized < 1.0 → ảnh mờ/nhòe → Rejected
  - LV_normalized 1.0–2.5 → nghi mờ → MANUAL_REVIEW
  - Lưu ý: ngưỡng 1.0 và 2.5 là giá trị khởi đầu, cần calibrate lại
    sau khi có dữ liệu thật từ production, đặt vào config để dễ điều chỉnh
    mà không cần sửa code
- Dùng OpenCV QRCodeDetector kiểm tra QR code:
  - Phát hiện QR → Rejected (chứa link đáng ngờ)
- Tính pHash của ảnh (dùng imagehash + Pillow)
- Query DB: nếu cùng pHash (hamming distance < 10) xuất hiện trong >= 5
  review khác nhau → Rejected (spam ảnh dùng lại)

**Bước 2 — Google Cloud Vision (2 unit, 1 API call duy nhất)**
Gộp SAFE_SEARCH_DETECTION và LABEL_DETECTION vào cùng 1 request để
tiết kiệm latency:

- Feature 1 — SafeSearch (1 unit):
  Rejected (Hard Violation) nếu:
  - adult >= LIKELY
  - violence >= LIKELY
  - racy >= VERY_LIKELY
    Lưu toàn bộ SafeSearch scores vào ModerationResult JSON.
    Nếu SafeSearch đã Rejected → không cần xử lý kết quả Label.

- Feature 2 — Label Detection, max 20 labels (1 unit):
  Kiểm tra relevance: nếu không có label nào khớp keyword đồ chơi
  với score > 0.6 → MANUAL_REVIEW (không Reject, để staff quyết định)
  Keywords: toy, game, child, play, doll, lego, puzzle, infant, kid,
  baby, figure, block, plush, stuffed, board game, educational

**Bước 3 — Post-process**

- Ảnh pass tất cả bước trên → Approved
- Lưu pHash vào DB sau khi có quyết định cuối (phục vụ duplicate
  detection về sau)

---

## YÊU CẦU KỸ THUẬT

**Ngôn ngữ & Runtime:** Python 3.10+

**Chế độ xử lý:** CHỈ ASYNC

- .NET backend lưu review với ModerationStatus = 'Pending'
- Python service lấy các record Pending và xử lý ngầm
- Tuyệt đối không block request của user
- Cơ chế trigger (implement cả 2, điều khiển bằng config):
  Option A: Poll DB mỗi 30 giây tìm ModerationStatus = 'Pending'
  Option B: Consume từ bảng DomainEventOutbox

**Xử lý lỗi:**

- Tất cả external API call phải có retry với exponential backoff (tối đa 3 lần)
- Pipeline crash giữa chừng → giữ nguyên Pending, worker sẽ retry
- Hết retry → set ManualReview, log lỗi
- Sau 5 lần thất bại trên cùng 1 record → đánh dấu, alert staff

**Cấu hình:** Toàn bộ secrets và settings qua environment variables

---

## YÊU CẦU THÔNG BÁO

Khi một review (text hoặc ảnh) bị set thành ManualReview:

- Query tất cả tài khoản có RoleID IN (2, 3) — Admin và Staff
  với điều kiện IsActive = 1 và IsDeleted = 0
- Insert vào bảng Notification.Deliveries một row cho mỗi tài khoản với:
  - NotificationType = 'SYSTEM'
  - Channel = 'WEB_BELL'
  - Title = "Cần kiểm duyệt review thủ công"
  - Message = mô tả ngắn kèm ReviewID và lý do
  - Status = 'Unread'
  - RecipientType: nếu RoleID = 2 → 'ADMIN', nếu RoleID = 3 → 'STAFF'

---

## NHIỆM VỤ CỦA BẠN

**Bước 1 — Khám phá project hiện tại**
Trước khi làm bất cứ điều gì, hãy đọc:

- Coding rules (CODING_RULES.md) của thư mục BE_SEP490_Children-s-Toy_Backend
- Đọc toàn bộ cấu trúc thư mục và các file hiện có trong SEP490_Children-s-Toy_AI
  trước khi làm bất cứ điều gì. Hiểu rõ những gì đã có.

**Bước 2 — Thiết kế cấu trúc thư mục tối ưu**
Nếu cấu trúc AI hiện tại chưa hợp lý hoặc không phù hợp với kế hoạch, đề xuất
và áp dụng cấu trúc tốt hơn kèm giải thích lý do thay đổi.

Cấu trúc kỳ vọng phải tách biệt rõ ràng:

- Config / settings management
- Database access layer (repository pattern)
- Moderation pipeline (text và image là 2 module riêng)
- External API clients (Groq, Google Vision)
- Worker / queue / scheduler
- Shared utilities (retry, logging, pHash)
- Notification module
- Tests

**Bước 3 — Tạo kế hoạch triển khai chi tiết**
Viết file MODERATION_PLAN.md bao gồm:

- Cấu trúc thư mục cuối cùng với mục đích của từng file
- Thứ tự implement (xây dựng gì trước, dependency giữa các module)
- Các quyết định thiết kế quan trọng và lý do lựa chọn
- Hướng dẫn setup môi trường (requirements.txt, .env.example)
- Cách service này tích hợp với .NET backend hiện có
- Chiến lược kiểm thử

**Bước 4 — CHƯA viết code implementation**
File MODERATION_PLAN.md là deliverable duy nhất ở bước này.
Code sẽ được viết ở các bước tiếp theo theo đúng kế hoạch này.

**Bước 5 — Nêu rõ các điểm còn mơ hồ**
Liệt kê những thông tin còn thiếu hoặc cần xác nhận trước khi bắt đầu
code.
