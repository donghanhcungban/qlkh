package main

# Policy hạ tầng QLKH (T-05, T-13, ADR-005, ADR-006).
# Chạy bằng: conftest test ./infra --policy ./policy --all-namespaces

required_tags := {"project", "env", "owner", "cost-center"}

admin_ports := {22, 3389, 5432, 6379}

vn_regions := {"asia-southeast-vn", "vn-hcm-1", "vn-han-1"}

resources[[type, name, body]] {
	some type, name
	body := input.resource[type][name]
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
	body.data_class == "pii"
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
	body.tags["data-class"] == "pii"
	not vn_regions[body.region]
	msg := sprintf("%s.%s: dữ liệu PII phải đặt trong vùng VN (T-13)", [type, name])
}
