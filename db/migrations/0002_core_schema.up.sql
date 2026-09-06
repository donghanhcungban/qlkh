-- QLKH-002 / REQ-002 — schema lõi: identity, people, teaching.
-- Idempotent: mọi lệnh dùng IF NOT EXISTS. Tương thích ngược: chỉ thêm mới,
-- không sửa/xóa đối tượng có sẵn (expand phase của expand–contract).
-- Rollback: db/migrations/0002_core_schema.down.sql

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS branches (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code        text NOT NULL UNIQUE CHECK (code ~ '^[A-Z0-9_-]{2,16}$'),
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS roles (
    code        text PRIMARY KEY CHECK (code IN ('parent', 'teacher', 'staff', 'admin')),
    description text NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email          text NOT NULL UNIQUE,
    password_hash  text NOT NULL,
    role_code      text NOT NULL REFERENCES roles (code),
    mfa_enabled    boolean NOT NULL DEFAULT false,
    is_active      boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    version        integer NOT NULL DEFAULT 0
);

-- Phạm vi cơ sở của tài khoản; P3 lấy branch_id từ phiên, không từ client (ADR-004).
CREATE TABLE IF NOT EXISTS user_branch_scope (
    user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    branch_id  uuid NOT NULL REFERENCES branches (id) ON DELETE RESTRICT,
    PRIMARY KEY (user_id, branch_id)
);

CREATE TABLE IF NOT EXISTS teachers (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL UNIQUE REFERENCES users (id) ON DELETE RESTRICT,
    branch_id  uuid NOT NULL REFERENCES branches (id) ON DELETE RESTRICT,
    full_name  text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS students (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    branch_id     uuid NOT NULL REFERENCES branches (id) ON DELETE RESTRICT,
    full_name     text NOT NULL,
    date_of_birth date NOT NULL CHECK (date_of_birth > DATE '1900-01-01'),
    created_at    timestamptz NOT NULL DEFAULT now(),
    deleted_at    timestamptz NULL
);

CREATE TABLE IF NOT EXISTS parents (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NULL UNIQUE REFERENCES users (id) ON DELETE SET NULL,
    branch_id   uuid NOT NULL REFERENCES branches (id) ON DELETE RESTRICT,
    full_name   text NOT NULL,
    phone_enc   bytea NOT NULL,
    phone_last4 text NOT NULL CHECK (phone_last4 ~ '^[0-9]{3,4}$'),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS parent_student (
    parent_id   uuid NOT NULL REFERENCES parents (id) ON DELETE CASCADE,
    student_id  uuid NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    relation    text NOT NULL CHECK (relation IN ('father', 'mother', 'guardian')),
    PRIMARY KEY (parent_id, student_id)
);

CREATE TABLE IF NOT EXISTS classes (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    branch_id  uuid NOT NULL REFERENCES branches (id) ON DELETE RESTRICT,
    teacher_id uuid NULL REFERENCES teachers (id) ON DELETE SET NULL,
    name       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT classes_branch_name_uniq UNIQUE (branch_id, name)
);

CREATE TABLE IF NOT EXISTS enrollments (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    class_id    uuid NOT NULL REFERENCES classes (id) ON DELETE RESTRICT,
    student_id  uuid NOT NULL REFERENCES students (id) ON DELETE RESTRICT,
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'left')),
    enrolled_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT enrollments_class_student_uniq UNIQUE (class_id, student_id)
);

-- Index: danh sách học viên theo cơ sở, phân trang cursor theo (created_at, id).
-- Truy vấn: SELECT ... FROM students WHERE branch_id = $1 AND deleted_at IS NULL
--           ORDER BY created_at DESC, id DESC LIMIT 50;
CREATE INDEX IF NOT EXISTS students_branch_created_idx
    ON students (branch_id, created_at DESC, id DESC)
    WHERE deleted_at IS NULL;

-- Truy vấn: danh sách lớp theo cơ sở (GET /classes).
CREATE INDEX IF NOT EXISTS classes_branch_created_idx
    ON classes (branch_id, created_at DESC, id DESC);

-- Truy vấn: danh sách học viên theo lớp (điểm danh, ghi danh).
CREATE INDEX IF NOT EXISTS enrollments_class_student_idx
    ON enrollments (class_id, student_id) WHERE status = 'active';

-- Truy vấn ngược: lớp của một học viên (màn hình phụ huynh).
CREATE INDEX IF NOT EXISTS enrollments_student_idx ON enrollments (student_id);

CREATE INDEX IF NOT EXISTS user_branch_scope_branch_idx ON user_branch_scope (branch_id);
