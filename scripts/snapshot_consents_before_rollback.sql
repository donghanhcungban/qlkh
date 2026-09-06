-- scripts/snapshot_consents_before_rollback.sql
-- Chạy TRƯỚC khi thực thi 0003_pii_key_and_consent.down.sql trên DB có dữ liệu thật.
-- Xem quy trình đầy đủ: docs/db/key-management.md, mục "Quy trình rollback".
--
-- Dùng: psql -h $HOST -U $USER -d $DB -v snapshot_suffix=$(date +%Y%m%d%H%M%S) \
--            -f scripts/snapshot_consents_before_rollback.sql
--
-- Biến: :snapshot_suffix — hậu tố timestamp (mặc định dùng 'manual' nếu không truyền).

\set suffix :snapshot_suffix
\if :{?snapshot_suffix}
\else
  \set suffix 'manual'
\endif

-- Bước 1: tạo bảng snapshot
DO $$
DECLARE
    tbl text := 'consents_snapshot_' || :'suffix';
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I AS SELECT *, now() AS snapshot_at FROM consents',
        tbl
    );
    RAISE NOTICE 'Snapshot created: %', tbl;
END $$;

-- Bước 2: xác nhận số dòng
DO $$
DECLARE
    tbl     text := 'consents_snapshot_' || :'suffix';
    src_cnt bigint;
    dst_cnt bigint;
BEGIN
    SELECT COUNT(*) INTO src_cnt FROM consents;
    EXECUTE format('SELECT COUNT(*) FROM %I', tbl) INTO dst_cnt;
    IF src_cnt <> dst_cnt THEN
        RAISE EXCEPTION 'Row count mismatch: consents=% vs snapshot=%', src_cnt, dst_cnt;
    END IF;
    RAISE NOTICE 'Row count verified: % rows', src_cnt;
END $$;

-- Bước 3: ghi audit
INSERT INTO audit_log (actor, action, detail, created_at)
SELECT
    current_user,
    'snapshot_consents_before_rollback',
    json_build_object(
        'snapshot_table', 'consents_snapshot_' || :'suffix',
        'row_count', (SELECT COUNT(*) FROM consents),
        'parents_with_key_version', (SELECT COUNT(*) FROM parents WHERE phone_key_version IS NOT NULL)
    )::text,
    now()
ON CONFLICT DO NOTHING;  -- audit_log có thể chưa tồn tại ở bước này; xem quy trình.

\echo 'Snapshot hoàn tất. Tiếp theo: pg_dump -t consents -Fc > consents_:suffix.dump'
\echo 'Sau đó xử lý phone_key_version theo docs/db/key-management.md trước khi chạy 0003.down.sql'
