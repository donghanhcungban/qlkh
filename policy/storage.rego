package main

# Policy hạ tầng QLKH (T-05, T-13, SD-10, ADR-005, ADR-006).
# Chạy bằng: conftest test ./infra --policy ./policy --all-namespaces
#
# SD-10: phân loại dữ liệu chỉ có MỘT nguồn sự thật là tag `data-class`.
# Trường cũ `data_class` vẫn được chấp nhận nhưng phải khớp tag, và tài nguyên
# lưu trữ không khai báo phân loại thì bị chặn (fail-closed), không đi qua sạch.

required_tags := {"project", "env", "owner", "cost-center"}

admin_ports := {22, 3389, 5432, 6379}

vn_regions := {"asia-southeast-vn", "vn-hcm-1", "vn-han-1"}

# Loại tài nguyên có lưu dữ liệu → bắt buộc khai báo phân loại.
storage_types := {
	"bucket",
	"aws_s3_bucket",
	"database",
	"db_instance",
	"aws_db_instance",
	"object_store",
	"volume",
	"backup",
}

resources[[type, name, body]] {
	some type, name
	body := input.resource[type][name]
}

# Nguồn sự thật duy nhất cho phân loại dữ liệu.
data_class(body) = c {
	c := body.tags["data-class"]
} else = c {
	c := body.data_class
} else = "unclassified"

is_pii(body) {
	data_class(body) == "pii"
}

deny[msg] {
	[type, name, body] := resources[_]
	body.acl == "public-read"
	msg := sprintf("%s.%s: bucket công khai bị cấm (T-05)", [type, name])
}

deny[msg] {
	[type, name, body] := resources[_]
	body.policy.Principal == "*"
	msg := sprintf("%s.%s: principal '*' bị cấm (least privilege)", [type, name])
}

deny[msg] {
	[type, name, body] := resources[_]
	body.policy.Statement[_].Principal == "*"
	msg := sprintf("%s.%s: principal '*' bị cấm (least privilege)", [type, name])
}

deny[msg] {
	[type, name, body] := resources[_]
	body.policy.Statement[_].Principal.AWS == "*"
	msg := sprintf("%s.%s: principal '*' bị cấm (least privilege)", [type, name])
}

# Fail-closed: tài nguyên lưu dữ liệu phải khai báo tag data-class.
deny[msg] {
	[type, name, body] := resources[_]
	storage_types[type]
	data_class(body) == "unclassified"
	msg := sprintf("%s.%s: thiếu tag 'data-class' (fail-closed, SD-10)", [type, name])
}

# Hai nguồn khai báo lệch nhau là lỗi cấu hình, không được im lặng chọn một bên.
deny[msg] {
	[type, name, body] := resources[_]
	tag := body.tags["data-class"]
	field := body.data_class
	tag != field
	msg := sprintf("%s.%s: phân loại lệch nhau tags[data-class]=%v vs data_class=%v", [type, name, tag, field])
}

deny[msg] {
	[type, name, body] := resources[_]
	is_pii(body)
	not body.encryption_at_rest
	msg := sprintf("%s.%s: tài nguyên PII phải mã hóa at-rest (ADR-006)", [type, name])
}

deny[msg] {
	[type, name, body] := resources[_]
	rule := body.ingress[_]
	rule.cidr == "0.0.0.0/0"
	admin_ports[rule.port]
	msg := sprintf("%s.%s: cổng quản trị %d mở ra Internet", [type, name, rule.port])
}

deny[msg] {
	[type, name, body] := resources[_]
	missing := required_tags - {k | body.tags[k]}
	count(missing) > 0
	msg := sprintf("%s.%s: thiếu tag bắt buộc %v", [type, name, missing])
}

deny[msg] {
	[type, name, body] := resources[_]
	is_pii(body)
	not vn_regions[body.region]
	msg := sprintf("%s.%s: dữ liệu PII phải đặt trong vùng VN (T-13)", [type, name])
}
