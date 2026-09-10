# Khảo sát timebox SD-29 (TCK-ADRDEBT-03)

- Ngày: 2026-09-10
- Kết luận: **SD-29 đã được đóng bằng code từ trước** (đã ship qua REL-047/048,
  cùng `integration_sha 4ae8597e8bfbfe357bcc75b62bc83f84fb94036d`). Ticket này
  không cần sửa code mới.

## Bằng chứng đã tìm ở đâu

1. `security/QLKH/threat-model.md` trên shared-context (blackboard, v1.49) hiện
   chỉ mang mục 41 (release-check REL-049) — bản đầy đủ mục 1-40 KHÔNG có trong
   nội dung đọc được ở blackboard (đúng như ticket đã lường trước: "threat-model
   v1.45 chỉ có mục 37 trong bản rút gọn"). Không tìm thấy chuỗi "SD-29" trong
   phần shared-context đọc được.
2. Tìm trực tiếp trong worktree (`search pattern="SD-29"`) ra origin thật:
   `tests/auth/test_shared_attempt_store.py` dòng 1-7 trích dẫn nguyên văn
   "Điều kiện đóng SD-29 trong threat-model mục 6":
   - Adapter `AttemptStore` trên session store dùng chung (P2/Redis), đếm nguyên tử.
   - Cấu hình sản xuất fail-fast khi store không dùng chung (không âm thầm chạy
     bộ đếm trong RAM).
   - Hai instance `AuthService` dùng chung store thì lần sai thứ 5 TỔNG CỘNG
     gây khóa (không lệch đếm giữa các worker).
3. Mô tả bản chất debt (từ `qlkh/application/auth_service.py` dòng 14,
   `qlkh/infrastructure/attempt_store_redis.py` dòng 1): bộ đếm đăng nhập sai
   ban đầu chỉ nằm trong RAM tiến trình (`InMemoryAttemptStore`) — sai khi chạy
   nhiều worker/replica vì mỗi tiến trình đếm riêng, khóa tài khoản có thể bị
   bỏ qua hoặc lệch giữa các worker (liên quan T-04/T-13 trong threat-model).

## Trạng thái đóng — đã có đủ 3 mảnh bằng chứng thật trong code hiện tại

1. **Adapter dùng chung**: `qlkh/infrastructure/attempt_store_redis.py`
   (`RedisAttemptStore`) + `qlkh/infrastructure/redis_counter_client.py`
   (INCR + EXPIRE-nếu-chưa-có-TTL nguyên tử — đóng luôn phần "TTL chưa nguyên
   tử" ghi trong docstring `rate_limiter.py`).
2. **Fail-fast sản xuất**: `qlkh/application/auth_wiring.py`
   (`build_auth_service`, `require_shared_store=environment == PRODUCTION`) —
   dựng `AuthService` ở môi trường `production` với `InMemoryAttemptStore`
   (không `shared=True`) sẽ raise lúc khởi động, không lúc người dùng đăng nhập.
3. **Test xác nhận cả 3 điều kiện đóng**: `tests/auth/test_shared_attempt_store.py`
   (đủ 3 khối test theo đúng 3 điều kiện mục 6), cộng
   `tests/auth/test_auth_service.py` dòng 296+313 (bộ đếm không tăng vô hạn
   theo email/IP lạ; nhiều replica mà đếm RAM là cấu hình sai) và
   `tests/auth/test_redis_counter_client.py` (bằng chứng INCR+TTL nguyên tử).

`run test tests/auth/` (worktree này): **49/49 PASS**, exit=0.
`run lint`: PASS, exit=0.
`git_status`: sạch — không có thay đổi nào chưa commit; toàn bộ code đóng SD-29
đã tồn tại và được commit từ trước khi ticket này được giao.

## Vì sao không cần code mới, không cần ADR mới trong ticket này

- SD-29 không phải một quyết định kiến trúc còn TREO chờ ký — nó là một quyết
  định vận hành/bảo mật đã được RA và HIỆN THỰC xong (adapter Redis + fail-fast
  + test), đúng khớp với ghi chú `hint` của ticket: nội dung này đã được giao
  qua REL-047/048 ở cùng `integration_sha`, không có code mới nào phát sinh từ
  lần redeploy REL-038.
- Vì không có quyết định kiến trúc/bảo mật nào còn MỚI cần ghi nhận (mọi ràng
  buộc đã ENFORCE bằng code + test, xem `auth_wiring.py` dòng 1-20), viết một
  ADR draft ở đây sẽ là tài liệu hoá một quyết định đã áp dụng xong — không sai
  nhưng không phải việc `architecture` cần làm lại; nếu delivery-lead/architect
  muốn có ADR hồi tố cho SD-29 thì đây là namespace `infra` cung cấp đủ bằng
  chứng để họ tự soạn (builder không ghi vào `architecture`).
- Threat-model mục 41 (v1.49) hiện đang BLOCK release REL-049 vì hai lý do
  KHÁC hoàn toàn SD-29 (RISK-6 DPIA, SD-08 DAST/license/SBOM) — SD-29 không
  nằm trong danh sách phát hiện block/warn của mục 41.

## Việc bàn giao (ngoài phạm vi/thẩm quyền namespace platform)

- Nếu security-engineer/architect xác nhận threat-model mục 6 hiện ghi SD-29 ở
  trạng thái "open"/"in-progress", đề nghị cập nhật sang "closed" kèm tham
  chiếu 3 bằng chứng ở trên (namespace `threat-model`, ngoài quyền ghi của
  `builder`/platform).

| version | ngày | thay đổi |
|---|---|---|
| 1 | 2026-09-10 | Khảo sát timebox SD-29 (TCK-ADRDEBT-03): xác định nguồn gốc (threat-model mục 6, via test docstring), xác nhận đã đóng bằng code có sẵn (RedisAttemptStore + fail-fast wiring + test), không cần sửa code/ADR mới trong ticket này. |
