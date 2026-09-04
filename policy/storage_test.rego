package main

# SD-02: policy phải có test (fixture âm/dương), chạy bằng `conftest verify`.

good_tags := {"project": "QLKH", "env": "dev", "owner": "platform", "cost-center": "CC-01", "data-class": "pii"}

good_bucket := {"resource": {"bucket": {"materials": {
	"acl": "private",
	"data_class": "pii",
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
