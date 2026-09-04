"""SD-09: nhị phân CI phải ghim SHA-256 thật; `unpinned` là lỗi cứng."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.verify_download import UNPINNED, load_pins, verify

REPO_ROOT = Path(__file__).resolve().parents[2]
PINS_PATH = REPO_ROOT / "ci/tool-checksums.txt"


def test_url_khong_khai_bao_bi_chan():
    assert verify("aa", "u", {}, None) == [
        "u: chưa khai báo trong ci/tool-checksums.txt (fail-closed)"
    ]


def test_unpinned_bi_chan_du_co_checksums_release():
    problems = verify("aa", "u", {"u": UNPINNED}, "aa  file.tar.gz\n")
    assert problems and "SD-09" in problems[0]


def test_pin_khop_thi_dat():
    assert verify("aa", "u", {"u": "aa"}, None) == []


def test_pin_lech_bi_chan():
    problems = verify("bb", "u", {"u": "aa"}, None)
    assert problems and "khác giá trị ghim" in problems[0]


def test_checksums_release_la_lop_kiem_bo_sung():
    problems = verify("aa", "u", {"u": "aa"}, "cc  file.tar.gz\n")
    assert problems and "không có trong tệp checksums" in problems[0]


def test_pins_sai_dinh_dang_bao_loi():
    with pytest.raises(ValueError):
        load_pins("abc")


def test_repo_khong_con_pin_unpinned():
    pins = load_pins(PINS_PATH.read_text(encoding="utf-8"))
    assert pins and all(digest != UNPINNED for digest in pins.values())
