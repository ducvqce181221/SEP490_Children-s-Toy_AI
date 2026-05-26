# MODERATION_COMMENT_PLAN.md

## 1) Scope and Principles
- Muc tieu: xay dung **AI Moderation Worker cho Blog comment/reply** (khong thay the .NET backend), chi xu ly moderation va cap nhat DB.
- Nguyen tac: **khong sua/xoa code khong lien quan**; implement theo huong bo sung module moi/tach module theo feature moderation comment.
- Rang buoc hien tai da xac nhan trong codebase:
  - .NET dang co entity/table cho `ReviewBlogs`, `ReviewBlogReplies`, `BlogCommentBanReasons`, `BlogCommentModerationLogs`, `BlogCommentViolationCount`.
  - Python AI hien tai dang xu ly `ReviewProducts` (review san pham), chua xu ly `ReviewBlogs`.

## 2) Current-State Discovery Summary
- Python:
  - Da co: `app/core/config.py`, `app/core/database.py`, `app/core/logging.py`, scheduler APScheduler, worker polling, repository pattern qua SQL Server (`aioodbc`).
  - Da co notification insert truc tiep vao `[Notification].[Deliveries]`.
  - Dang moderation cho `ReviewProducts` + `ReviewProductImages`.
- .NET:
  - API tao blog comment/reply: `CustomerBlogReviewsController` -> `BlogService.CreateBlogReviewAsync/CreateBlogReviewReplyAsync`.
  - Admin/Staff hien tai dang co luong an/hien (`Visible/Hidden`), chua la luong moderation approve/reject day du theo business moi.
  - DB schema da co truong moderation can thiet cho `ReviewBlogs/ReviewBlogReplies` (ModerationStatus, RetryCount, ManualReviewDeadline, LastRetryAt).

## 3) Target Folder Structure (Python AI service)

```text
SEP490_Children-s-Toy_AI/
  app/
    core/
      config.py                         # bo sung settings cho blog-comment moderation
      database.py                       # giu nguyen pool + helper transaction
      logging.py                        # giu nguyen
    features/
      moderation/
        blog_comment/                   # NEW feature scope (tach khoi review product)
          __init__.py
          schemas.py                    # DTO/domain model cho comment/reply moderation
          repository.py                 # SQL cho ReviewBlogs/ReviewBlogReplies/BlogComment*
          reason_mapper.py              # map AI category -> BanReasonID/Content
          service.py                    # orchestrator moderation cho comment/reply
          retry_policy.py               # retry 3 lan, cach 5 phut, state transition
          violation_service.py          # tinh vi pham 15 ngay, khoa 7 ngay
          lock_service.py               # khoa/mo khoa comment
          notification_service.py       # notification cho user/admin-staff
          worker.py                     # xu ly batch PENDING -> PROCESSING
          jobs.py                       # 2 hourly jobs (auto reject timeout + auto unlock)
    worker/
      scheduler.py                      # dang ky them jobs cho blog_comment worker
    tests/
      unit/
        test_blog_comment_reason_mapper.py
        test_blog_comment_retry_policy.py
        test_blog_comment_violation_service.py
      integration/
        test_blog_comment_worker_flow.py
        test_blog_comment_jobs.py
```

## 4) Purpose of Each New/Changed File
- `schemas.py`: chuan hoa enum/status (`PENDING`, `PROCESSING`, `APPROVED`, `REJECTED`, `MANUALREVIEW`, `FAILED`) va payload xu ly.
- `repository.py`: truy van/lock row pending, update status, retry count, write moderation logs, doc BanReasons, doc/ghi violation + lock.
- `reason_mapper.py`: map ket qua AI ve dung ly do trong `BlogCommentBanReasons` (theo Content).
- `service.py`: orchestration end-to-end cho 1 comment/reply.
- `retry_policy.py`: quan ly timeout/error, delay 5 phut, gioi han 3 retry, chuyen `FAILED` sau cung.
- `violation_service.py`: cong vi pham, dem 15 ngay, quyet dinh khoa 7 ngay.
- `lock_service.py`: cap nhat `BlogCommentViolationCount.IsCommentBanned/BanExpiresAt` va auto unlock.
- `notification_service.py`: ghi thong bao vao notification table theo 5 truong hop business.
- `worker.py`: xu ly batch moderation tu DB.
- `jobs.py`: 2 background jobs theo gio.
- `worker/scheduler.py`: hook them schedule cho worker blog comment + 2 hourly jobs.

## 5) Implementation Order
1. Finalize status constants + DB compatibility check (`ReviewBlogs`, `ReviewBlogReplies`).
2. Implement `schemas.py` + `reason_mapper.py`.
3. Implement `repository.py` (read/write SQL + transaction boundaries).
4. Implement `retry_policy.py`.
5. Implement `notification_service.py`.
6. Implement `violation_service.py` + `lock_service.py`.
7. Implement `service.py` orchestration.
8. Implement `worker.py` batch handling.
9. Implement `jobs.py` hourly jobs.
10. Wire scheduler and config flags.
11. Write unit/integration tests.

## 6) Key Design Decisions
- **Decision A - Khong thay doi luong .NET tao comment**:
  - .NET tiep tuc tao `PENDING`; Python chi pick-up va moderation.
- **Decision B - DB-first integration**:
  - Python thao tac truc tiep SQL Server cung DB chung voi .NET de giam coupling API.
- **Decision C - Idempotent worker claim**:
  - Claim record bang update status `PENDING -> PROCESSING` trong 1 cau lenh atomic (`UPDATE ... OUTPUT`) de tranh double-processing.
- **Decision D - Ban reason source of truth**:
  - Khong hardcode reason text; map qua `BlogCommentBanReasons`.
- **Decision E - Retry theo business**:
  - Retry toi da 3 lan, moi lan cach 5 phut; that bai cuoi -> `FAILED` + manual queue.
- **Decision F - Violation/ban persistence**:
  - Tai su dung bang `BlogCommentViolationCount` hien co de quan ly vi pham + lock window.

## 7) Integration with .NET Backend
- Python worker se dung cac bang sau:
  - Input queue: `ReviewBlogs`, `ReviewBlogReplies` (status `PENDING`).
  - Reason source: `BlogCommentBanReasons`.
  - Audit/log: `BlogCommentModerationLogs`.
  - Violation/lock: `BlogCommentViolationCount`.
  - Notification: notification table hien tai (theo convention dang dung trong AI service hien tai).
- .NET backend van giu trach nhiem:
  - UI/API tao comment/reply.
  - Man hinh Admin/Staff duyet thu cong.
  - Cac logic ngoai moderation worker.

## 8) Comment Status Flow
- Creation: `.NET` luu `PENDING`.
- Worker claim: `PENDING -> PROCESSING`.
- AI outcome:
  - Approved -> `APPROVED`.
  - Rejected -> `REJECTED` + reason + notify user + violation flow.
  - Uncertain -> `MANUALREVIEW` + set deadline 24h + vao queue manual.
  - AI error timeout -> retry flow.
- Retry exhausted:
  - `PROCESSING -> FAILED`, reason = "AI moderation is currently unavailable...", vao queue manual.
- Public visibility:
  - Chi `APPROVED` duoc hien thi cong khai.

## 9) AI Retry Flow
- Khi AI call loi/timeout:
  - Tang `RetryCount`, set `LastRetryAt`.
  - Neu `RetryCount < 3`: dua ve `PENDING` sau khi dat lich retry +5 phut (hoac bo qua den chu ky phu hop dua tren `LastRetryAt`).
  - Neu `RetryCount >= 3`: set `FAILED`, ghi moderation log, map ly do "AI moderation is currently unavailable. Your comment will be sent for manual review".

## 10) Admin/Staff Manual Review Flow (integration point)
- Python worker khong thay the thao tac tay.
- Python dam bao danh sach cho duyet thu cong co du lieu:
  - `MANUALREVIEW` (AI uncertain)
  - `FAILED` (AI unavailable sau 3 retry)
- Admin/Staff xu ly APPROVE/REJECT tren .NET nhu hien tai; neu REJECT thi he thong goi violation flow.

## 11) Violation Counting Flow
- Trigger sau moi `REJECTED` (AI reject, manual reject, auto-timeout reject).
- Thao tac:
  - Ghi nhan 1 vi pham cho account.
  - Dem tong vi pham trong 15 ngay gan nhat.
  - Neu < 3: ket thuc.
  - Neu >= 3: khoa quyen comment 7 ngay.

## 12) Lock/Unlock Flow
- Lock:
  - Set flag ban comment + `BanExpiresAt = now + 7 days` tren `BlogCommentViolationCount`.
  - Gui thong bao "Tai khoan bi khoa comment 7 ngay do vi pham nhieu lan".
- Hourly unlock job:
  - Quet account dang ban va het han.
  - Mo khoa quyen comment.
  - Giu nguyen so lan vi pham (khong reset).
  - Gui thong bao mo khoa.

## 13) Notification Flow
- Can gui cho 5 case:
  1. AI reject comment.
  2. Admin/Staff reject comment.
  3. Auto reject do qua 24h chua duyet.
  4. Account bi khoa 7 ngay.
  5. Account duoc mo khoa.
- Message reject phai dung ly do tu `BlogCommentBanReasons`.
- Notification service can idempotency key de tranh spam duplicate.

## 14) Using BlogCommentBanReasons Correctly
- Chien luoc map:
  - AI classifier tra ve category code noi bo (vd `UNSUITABLE_FOR_CHILDREN`).
  - `reason_mapper.py` map category code -> content text canonical.
  - Repository query `BlogCommentBanReasons` theo `Content` de lay `BanReasonID` + `Content` chinh xac.
- Special fallback:
  - Neu AI loi sau 3 retry, bat buoc dung reason:
    - `AI moderation is currently unavailable. Your comment will be sent for manual review`.

## 15) Background Jobs
- Job 1 (hourly): auto reject `MANUALREVIEW` qua 24h
  - Dieu kien: `ManualReviewDeadline <= now`.
  - Action: -> `REJECTED`, notify user, +1 violation.
- Job 2 (hourly): auto unlock accounts het 7 ngay
  - Dieu kien: dang bi ban va `BanExpiresAt <= now`.
  - Action: unban, notify user.

## 16) Test Strategy
- Unit tests:
  - status transition matrix.
  - retry window logic (5 phut, max 3).
  - reason mapping + fallback.
  - violation threshold logic (15 ngay, nguong 3).
- Integration tests (SQL test db):
  - pending -> processing -> approved/rejected/manualreview/failed.
  - retry exhaust path.
  - hourly job timeout reject.
  - hourly job unlock path.
  - notification idempotency.
- Non-functional:
  - concurrency claim test (nhieu worker cung claim khong double-process).
  - transaction rollback test khi loi giua luong.

## 17) Deliverable Boundaries for This Step
- Buoc hien tai chi tao ke hoach.
- **Khong viet implementation code moderation**.

## 18) Open Questions to Confirm Before Coding
1. Trang thai string chinh xac trong DB cho blog comment/reply la `MANUALREVIEW` hay `ManualReview` (can exact casing/value theo CHECK constraint).
2. Co cho phep them trang thai `PROCESSING` cho `ReviewBlogs/ReviewBlogReplies` trong DB hay da co san?
3. Violation history chi luu trong `BlogCommentViolationCount` aggregate hay can bang log rieng nhu `CommentViolation` nhu mo ta business?
4. Nguon du lieu cho thong bao user: tiep tuc ghi truc tiep vao `[Notification].[Deliveries]` (giong service hien tai) hay phai publish qua outbox/event cua .NET?
5. Luong Admin/Staff reject hien tai cua blog comments da co save `BanReasonID` + note chua, hay can bo sung de worker tinh vi pham day du?
6. `ReviewBlogReplies` co can worker moderation rieng nhu comment goc hay tam thoi chi moderation `ReviewBlogs`?
7. Chinh sach rate-limit (>=5 comment/1 phut) duoc enforce o .NET da day du chua, hay can Python job ho tro detect bo sung?
8. Timezone business cho deadline 24h va ban 7 ngay dung UTC toan he thong hay theo local timezone VN?
