-- QLKH-009 / REQ-008 — lịch sử sửa điểm append-only + chặn UPDATE/DELETE ở tầng DB.
--
-- `grades` chưa có migration trước đó (QLKH-008 chỉ hiện thực ở tầng
-- application/Protocol, chưa có bảng thật) — migration này tạo bảng `grades`
-- tối thiểu để `grade_history.grade_id` có FK hợp lệ, cùng bảng lịch sử.
-- Không tạo bảng `attendance`/lịch sử điểm danh ở đây: attendance hiện chỉ có
-- `bulk_insert` (ghi thêm), chưa có endpoint sửa điểm danh đã ghi, nên chưa có
-- "sự kiện sửa" cần lịch sử — nợ lại cho ticket nào mở endpoint sửa điểm danh.
--
-- Append-only bằng TRIGGER (không phụ thuộc tên role ứng dụng, vì role DB
-- runtime chưa được ADR nào chốt tên cụ thể tại thời điểm này):
-- UPDATE/DELETE trên grade_history bị chặn ở tầng DB cho MỌI role, kể cả
-- superuser thường dùng của ứng dụng (RAISE EXCEPTION trong BEFORE trigger).
--
-- Idempotent, rollback: 0004_grade_history.down.sql

CREATE TABLE IF NOT EXISTS grades (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    branch_id   uuid NOT NULL REFERENCES branches (id) ON DELETE RESTRICT,
    class_id    uuid NOT NULL REFERENCES classes (id) ON DELETE RESTRICT,
    student_id  uuid NOT NULL REFERENCES students (id) ON DELETE RESTRICT,
    score       numeric(4, 2) NOT NULL CHECK (score >= 0 AND score <= 10),
    published   boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT grades_class_student_uniq UNIQUE (class_id, student_id)
);

CREATE INDEX IF NOT EXISTS grades_student_idx ON grades (student_id);
CREATE INDEX IF NOT EXISTS grades_class_idx ON grades (class_id);

-- Lịch sử append-only: mỗi lần sửa điểm ghi thêm một dòng, không bao giờ sửa
-- dòng cũ. `reason` bắt buộc (NOT NULL, non-empty) — service đã chặn 422 khi
-- thiếu reason lúc sửa điểm đã công bố; ràng buộc CHECK ở đây là lớp phòng
-- thủ thứ hai ở tầng dữ liệu, không tin tưởng riêng tầng ứng dụng.
CREATE TABLE IF NOT EXISTS grade_history (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    grade_id    uuid NOT NULL REFERENCES grades (id) ON DELETE RESTRICT,
    old_score   numeric(4, 2) NULL CHECK (old_score IS NULL OR (old_score >= 0 AND old_score <= 10)),
    new_score   numeric(4, 2) NOT NULL CHECK (new_score >= 0 AND new_score <= 10),
    actor_id    uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    changed_at  timestamptz NOT NULL DEFAULT now(),
    reason      text NOT NULL CHECK (btrim(reason) <> '')
);

CREATE INDEX IF NOT EXISTS grade_history_grade_idx
    ON grade_history (grade_id, changed_at DESC);

-- Chặn UPDATE/DELETE ở tầng DB (Gherkin: "cố UPDATE bản ghi lịch sử -> bị từ
-- chối ở tầng DB"), độc lập với quyền GRANT của role kết nối ứng dụng.
CREATE OR REPLACE FUNCTION grade_history_deny_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'grade_history là append-only: UPDATE/DELETE bị từ chối (QLKH-009, REQ-008)'
        USING ERRCODE = '23001'; -- restrict_violation
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS grade_history_deny_update ON grade_history;
CREATE TRIGGER grade_history_deny_update
    BEFORE UPDATE ON grade_history
    FOR EACH ROW EXECUTE FUNCTION grade_history_deny_mutation();

DROP TRIGGER IF EXISTS grade_history_deny_delete ON grade_history;
CREATE TRIGGER grade_history_deny_delete
    BEFORE DELETE ON grade_history
    FOR EACH ROW EXECUTE FUNCTION grade_history_deny_mutation();
