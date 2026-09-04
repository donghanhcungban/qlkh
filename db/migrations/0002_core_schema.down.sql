-- Rollback QLKH-002. Idempotent (IF EXISTS), thứ tự ngược phụ thuộc khóa ngoại.
-- Cảnh báo dữ liệu: chỉ chạy khi các bảng này chưa mang dữ liệu production;
-- quy trình yêu cầu snapshot logic trước khi rollback (xem docs trong PR).

DROP INDEX IF EXISTS user_branch_scope_branch_idx;
DROP INDEX IF EXISTS enrollments_student_idx;
DROP INDEX IF EXISTS enrollments_class_student_idx;
DROP INDEX IF EXISTS classes_branch_created_idx;
DROP INDEX IF EXISTS students_branch_created_idx;

DROP TABLE IF EXISTS enrollments;
DROP TABLE IF EXISTS classes;
DROP TABLE IF EXISTS parent_student;
DROP TABLE IF EXISTS parents;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS teachers;
DROP TABLE IF EXISTS user_branch_scope;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS roles;
DROP TABLE IF EXISTS branches;
