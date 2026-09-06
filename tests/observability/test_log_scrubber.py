import pytest

from qlkh.infrastructure.observability.log_scrubber import (
    ForbiddenFieldError,
    mask_email,
    mask_phone,
    scrub_for_external_sink,
    scrub_log_record,
)


class TestMask:
    def test_mask_phone_vn_0_prefix(self):
        masked = mask_phone("0987654321")
        assert masked.startswith("09")
        assert masked.endswith("21")
        assert "87654321" not in masked

    def test_mask_phone_vn_plus84_prefix(self):
        masked = mask_phone("+84987654321")
        assert masked.startswith("+84")
        assert "987654321" not in masked
        assert masked.endswith("21")

    def test_mask_email(self):
        masked = mask_email("nguyen.van.a@example.com")
        assert masked != "nguyen.van.a@example.com"
        assert masked.endswith("@example.com")
        assert "nguyen.van.a" not in masked


class TestScrubLogRecordAcceptance1:
    """Given payload đăng nhập, When ghi log, Then không xuất hiện mật khẩu,
    OTP hay SĐT chưa mask."""

    def test_password_field_raises(self):
        with pytest.raises(ForbiddenFieldError):
            scrub_log_record({"event": "login_attempt", "password": "hunter2"})

    def test_otp_field_raises(self):
        with pytest.raises(ForbiddenFieldError):
            scrub_log_record({"event": "otp_verify", "otp": "123456"})

    def test_token_field_raises(self):
        with pytest.raises(ForbiddenFieldError):
            scrub_log_record({"event": "login_ok", "access_token": "abc.def.ghi"})

    def test_phone_field_is_masked_not_dropped_raw(self):
        out = scrub_log_record({"event": "login_attempt", "phone": "0987654321"})
        assert "0987654321" not in str(out)
        assert out["phone"] != "0987654321"

    def test_unallowlisted_field_is_dropped(self):
        out = scrub_log_record({"event": "login_attempt", "some_unexpected_field": "raw pii maybe"})
        assert "some_unexpected_field" not in out

    def test_message_free_text_phone_and_email_masked(self):
        out = scrub_log_record(
            {"event": "err", "message": "user 0987654321 with email a@b.com failed"}
        )
        assert "0987654321" not in out["message"]
        assert "a@b.com" not in out["message"]


class TestScrubForExternalSinkAcceptance2:
    """Given log gửi ra dịch vụ giám sát, When kiểm mẫu PII (SĐT VN, email),
    Then không khớp."""

    def test_no_pii_pattern_in_external_payload(self):
        record = {
            "event": "attendance_marked",
            "user_id": "u-123",
            "branch_id": "b-1",
            "phone": "0912345678",
            "message": "contact a@b.com or 0912345678",
        }
        out = scrub_for_external_sink(record)
        text = str(out)
        assert "0912345678" not in text
        assert "a@b.com" not in text
        assert "user_id" not in out  # định danh nội bộ không đi ra E5

    def test_forbidden_field_never_reaches_external_sink(self):
        with pytest.raises(ForbiddenFieldError):
            scrub_for_external_sink({"event": "login", "password": "x"})
