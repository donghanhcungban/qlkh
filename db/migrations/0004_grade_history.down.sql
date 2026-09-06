-- Rollback QLKH-009. Idempotent, thứ tự ngược phụ thuộc.
--
-- CẢNH BÁO: grade_history là bằng chứng audit ai/khi nào/vì sao sửa điểm đã
-- công bố. Xóa bảng này trên môi trường có dữ liệu thật = mất bằng chứng
-- audit không phục hồi được — sao lưu (pg_dump -t grade_history) trước khi
-- rollback trên môi trường có dữ liệu thật.

DROP TRIGGER IF EXISTS grade_history_deny_delete ON grade_history;
DROP TRIGGER IF EXISTS grade_history_deny_update ON grade_history;
DROP FUNCTION IF EXISTS grade_history_deny_mutation();

DROP INDEX IF EXISTS grade_history_grade_idx;
DROP TABLE IF EXISTS grade_history;

DROP INDEX IF EXISTS grades_class_idx;
DROP INDEX IF EXISTS grades_student_idx;
DROP TABLE IF EXISTS grades;
