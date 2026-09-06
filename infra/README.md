# infra/

Chưa có tài nguyên: DEF-01 (nhà cung cấp cloud vùng VN) chưa quyết nên không có
`terraform plan` trong PR này. Policy trong `policy/` đã chạy sẵn trong CI để mọi
PR hạ tầng đầu tiên bị chặn tự động nếu vi phạm (public bucket, IAM `*`, cổng
quản trị mở, thiếu mã hóa at-rest, thiếu tag, vùng ngoài VN với `data-class=pii`).

Khi DEF-01 chốt: khởi tạo backend state từ xa (khóa + mã hóa), rồi mới thêm module.
