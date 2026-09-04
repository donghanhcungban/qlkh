package main

# SD-02: policy phải có test (fixture âm/dương), chạy bằng `conftest verify`.
# SD-10: thêm fixture cho phân loại dữ liệu khai báo một phía / lệch nhau.

good_tags := {"project": "QLKH", "env": "dev", "owner": "platform", "cost-center": "CC-01", "data-class": "pii"}

good_bucket := {"resource": {"bucket": {"materials": {
	"acl": "private",
	"encryption_at_rest": true,
	"region": "vn-hcm-1",
	"tags": good_tags,
}}}}

test_bucket_dat_chuan_khong_bi_chan {
	count(deny) == 0 with input as good_bucket
}

test_bucket_public_bi_chan {
	bad := json.patch(good_bucket, [{"op": "replace", "path": "/resource/bucket/materials/acl", "value": "public-read"}])
	count(deny) > 0 with input as bad
}

test_thieu_ma_hoa_bi_chan {
	bad := json.patch(good_bucket, [{"op": "replace", "path": "/resource/bucket/materials/encryption_at_rest", "value": false}])
	count(deny) > 0 with input as bad
}

test_vung_ngoai_vn_bi_chan {
	bad := json.patch(good_bucket, [{"op": "replace", "path": "/resource/bucket/materials/region", "value": "us-east-1"}])
	count(deny) > 0 with input as bad
}

test_thieu_tag_bi_chan {
	bad := json.patch(good_bucket, [{"op": "replace", "path": "/resource/bucket/materials/tags", "value": {"project": "QLKH"}}])
	count(deny) > 0 with input as bad
}

test_cong_quan_tri_mo_bi_chan {
	bad := {"resource": {"security_group": {"db": {
		"tags": good_tags,
		"region": "vn-hcm-1",
		"encryption_at_rest": true,
		"ingress": [{"cidr": "0.0.0.0/0", "port": 5432}],
	}}}}
	count(deny) > 0 with input as bad
}

# SD-10 — PII khai báo bằng trường cũ `data_class`, KHÔNG có tag: vẫn phải chặn
# cả mã hóa lẫn vùng, và bị chặn vì thiếu tag data-class.
pii_chi_co_truong_cu := {"resource": {"bucket": {"materials": {
	"acl": "private",
	"data_class": "pii",
	"encryption_at_rest": false,
	"region": "us-east-1",
	"tags": {"project": "QLKH", "env": "dev", "owner": "platform", "cost-center": "CC-01"},
}}}}

test_pii_khai_bao_truong_cu_van_bi_chan_ma_hoa_va_vung {
	count(deny) > 0 with input as pii_chi_co_truong_cu
	deny["bucket.materials: tài nguyên PII phải mã hóa at-rest (ADR-006)"] with input as pii_chi_co_truong_cu
	deny["bucket.materials: dữ liệu PII phải đặt trong vùng VN (T-13)"] with input as pii_chi_co_truong_cu
	deny["bucket.materials: thiếu tag 'data-class' (fail-closed, SD-10)"] with input as pii_chi_co_truong_cu
}

# SD-10 — PII khai báo bằng tag, KHÔNG có trường cũ: quy tắc mã hóa vẫn phải bắt.
test_pii_khai_bao_bang_tag_van_bi_chan_ma_hoa {
	bad := json.patch(good_bucket, [{"op": "replace", "path": "/resource/bucket/materials/encryption_at_rest", "value": false}])
	deny["bucket.materials: tài nguyên PII phải mã hóa at-rest (ADR-006)"] with input as bad
}

# SD-10 — không khai báo phân loại nào thì fail-closed, không đi qua sạch.
test_khong_khai_bao_phan_loai_bi_chan {
	bad := {"resource": {"bucket": {"logs": {
		"acl": "private",
		"encryption_at_rest": true,
		"region": "vn-hcm-1",
		"tags": {"project": "QLKH", "env": "dev", "owner": "platform", "cost-center": "CC-01"},
	}}}}
	deny["bucket.logs: thiếu tag 'data-class' (fail-closed, SD-10)"] with input as bad
}

# Hai nguồn khai báo lệch nhau phải báo lỗi.
test_phan_loai_lech_nhau_bi_chan {
	bad := json.patch(good_bucket, [{"op": "add", "path": "/resource/bucket/materials/data_class", "value": "public"}])
	count(deny) > 0 with input as bad
}

# IAM principal '*' theo hình dạng Statement (terraform show -json).
test_principal_sao_trong_statement_bi_chan {
	bad := {"resource": {"bucket": {"materials": {
		"acl": "private",
		"encryption_at_rest": true,
		"region": "vn-hcm-1",
		"tags": good_tags,
		"policy": {"Statement": [{"Principal": {"AWS": "*"}}]},
	}}}}
	count(deny) > 0 with input as bad
}
