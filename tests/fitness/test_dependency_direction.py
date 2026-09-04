"""Test cho fitness function hướng phụ thuộc (QLKH-001, NFR-003, ADR-003).

Tiêu chí Gherkin 1: "Given PR có domain import ORM, When CI chạy, Then build fail
với thông báo vi phạm hướng phụ thuộc".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.fitness import check_package, main

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_package(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "qlkh"
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def test_repo_hien_tai_khong_vi_pham():
    assert check_package(REPO_ROOT / "qlkh") == []


def test_domain_import_orm_bi_chan(tmp_path):
    root = _make_package(
        tmp_path,
        {
            "domain/student.py": "import sqlalchemy\n",
            "application/__init__.py": "",
            "infrastructure/__init__.py": "",
        },
    )
    violations = check_package(root)
    assert len(violations) == 1
    assert "sqlalchemy" in violations[0].message
    assert "domain không được import" in violations[0].message


def test_domain_import_http_client_bi_chan(tmp_path):
    root = _make_package(tmp_path, {"domain/notify.py": "from httpx import Client\n"})
    assert [v.message for v in check_package(root)] == [
        "domain không được import framework/ORM/HTTP: 'httpx'"
    ]


def test_domain_import_nguoc_len_application_bi_chan(tmp_path):
    root = _make_package(
        tmp_path,
        {
            "domain/rules.py": "from qlkh.application.enroll import do\n",
            "application/enroll.py": "def do():\n    return None\n",
        },
    )
    messages = [v.message for v in check_package(root)]
    assert messages == ["sai hướng phụ thuộc: 'domain' không được import 'application'"]


def test_application_import_infrastructure_bi_chan(tmp_path):
    root = _make_package(
        tmp_path,
        {
            "application/use_case.py": "import qlkh.infrastructure.orm\n",
            "infrastructure/orm.py": "",
        },
    )
    assert len(check_package(root)) == 1


def test_infrastructure_duoc_import_xuong_duoi(tmp_path):
    root = _make_package(
        tmp_path,
        {
            "infrastructure/repo.py": "from qlkh.application.use_case import run\nfrom qlkh.domain import rules\n",
            "application/use_case.py": "from qlkh.domain import rules\n",
            "domain/rules.py": "",
        },
    )
    assert check_package(root) == []


def test_import_tuong_doi_trong_cung_lop_khong_bi_bat(tmp_path):
    root = _make_package(
        tmp_path,
        {"domain/a.py": "from .b import x\n", "domain/b.py": "x = 1\n"},
    )
    assert check_package(root) == []


def test_file_ngoai_ba_lop_duoc_bo_qua(tmp_path):
    root = _make_package(tmp_path, {"scripts/seed.py": "import sqlalchemy\n"})
    assert check_package(root) == []


@pytest.mark.parametrize(
    ("files", "expected_exit"),
    [
        ({"domain/ok.py": "x = 1\n"}, 0),
        ({"domain/bad.py": "import django\n"}, 1),
    ],
)
def test_main_tra_ve_exit_code_dung(tmp_path, files, expected_exit):
    root = _make_package(tmp_path, files)
    assert main([str(root)]) == expected_exit
