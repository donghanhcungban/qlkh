"""Test cho các cổng CI dạng script (QLKH-001).

Phủ tiêu chí chấp nhận 2 (SCA/license chặn) và 3 (SBOM CycloneDX), gồm cả đường lỗi.
Bổ sung: cưỡng chế SD-01 (authz-gate không được warn khi đã có endpoint PII) và
SD-09 (nhị phân tải trong CI phải xác minh checksum).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.check_authz_tests import missing_authz_tests, pii_operations
from tools.check_licenses import check as check_licenses
from tools.check_sbom import main as sbom_main
from tools.check_sbom import validate as validate_sbom
from tools.ci_guard import authz_gate_violations, load_workflow, unverified_downloads
from tools.verify_download import UNPINNED, load_pins, verify

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/ci.yml"
SPEC_PATH = REPO_ROOT / "api/QLKH/openapi.yaml"
PINS_PATH = REPO_ROOT / "ci/tool-checksums.txt"

CURL_BLOCK = "- run: |\n    curl -sSL -o x.tar.gz https://example.com/x.tar.gz\n"


def _sbom(**overrides):
    document = {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []}
    document.update(overrides)
    return document


def test_sbom_hop_le():
    assert validate_sbom(_sbom()) == []


def test_sbom_sai_dinh_dang_bi_chan():
    errors = validate_sbom(_sbom(bomFormat="SPDX"))
    assert any("bomFormat" in e for e in errors)


def test_sbom_thieu_spec_version():
    document = _sbom()
    del document["specVersion"]
    assert any("specVersion" in e for e in validate_sbom(document))


def test_sbom_thieu_components():
    document = _sbom()
    del document["components"]
    assert any("components" in e for e in validate_sbom(document))


def test_sbom_main_bao_loi_khi_thieu_file(tmp_path):
    assert sbom_main([str(tmp_path / "khong-co.json")]) == 1


def test_sbom_main_xanh_khi_hop_le(tmp_path):
    path = tmp_path / "sbom.cdx.json"
    path.write_text(json.dumps(_sbom()), encoding="utf-8")
    assert sbom_main([str(path)]) == 0


def _component(name, license_id=None):
    component = {"name": name}
    if license_id is not None:
        component["licenses"] = [{"license": {"id": license_id}}]
    return component


def test_license_cho_phep_mit():
    assert check_licenses(_sbom(components=[_component("attrs", "MIT")])) == []


def test_license_agpl_bi_chan():
    problems = check_licenses(_sbom(components=[_component("x", "AGPL-3.0")]))
    assert problems == ["x: license bị cấm 'AGPL-3.0'"]


def test_goi_khong_khai_bao_license_bi_chan():
    problems = check_licenses(_sbom(components=[_component("mystery")]))
    assert problems == ["mystery: không khai báo license"]


def test_ngoai_le_license_duoc_bo_qua():
    document = _sbom(components=[_component("legacy", "GPL-2.0")])
    assert check_licenses(document, exceptions={"legacy"}) == []


def test_pii_operations_chi_lay_path_pii():
    spec = {
        "paths": {
            "/students/{id}": {"get": {"operationId": "getStudent"}},
            "/health": {"get": {"operationId": "health"}},
        }
    }
    assert pii_operations(spec) == ["getStudent"]


def test_authz_gate_bao_thieu_test():
    assert missing_authz_tests(["getStudent"], ["def test_khac(): pass"]) == ["getStudent"]


def test_authz_gate_xanh_khi_co_test():
    sources = ["def test_getstudent_tu_choi_khac_co_so(): pass"]
    assert missing_authz_tests(["getStudent"], sources) == []


def test_workflow_ci_co_du_cac_cong_bat_buoc():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    for job in ("lint:", "test:", "fitness:", "sast:", "sca:", "secrets:", "iac:", "license:", "sbom:"):
        assert job in workflow, job


# --- SD-01: authz-gate không được ở chế độ cảnh báo khi đã có endpoint PII ---


def _workflow_with_warn(flag: bool = True):
    return {"jobs": {"authz-gate": {"continue-on-error": flag, "steps": []}}}


def test_authz_gate_warn_duoc_phep_khi_chua_co_spec():
    assert authz_gate_violations(_workflow_with_warn(), None, []) == []


def test_authz_gate_warn_duoc_phep_khi_spec_chua_co_endpoint_pii():
    assert authz_gate_violations(_workflow_with_warn(), {"paths": {}}, []) == []


def test_authz_gate_warn_bi_chan_khi_da_co_endpoint_pii():
    problems = authz_gate_violations(_workflow_with_warn(), {"paths": {}}, ["getStudent"])
    assert len(problems) == 1
    assert "SD-01" in problems[0]


def test_authz_gate_khong_warn_thi_dat():
    assert authz_gate_violations(_workflow_with_warn(False), {"paths": {}}, ["getStudent"]) == []


def test_thieu_job_authz_gate_bi_bao_loi():
    assert authz_gate_violations({"jobs": {}}, None, []) == ["workflow thiếu job authz-gate"]


def test_workflow_that_tuan_thu_sd01():
    """Bất biến trên repo thật: có endpoint PII trong OpenAPI thì cờ warn phải biến mất."""
    workflow, _ = load_workflow(WORKFLOW_PATH)
    spec = None
    operations: list[str] = []
    if SPEC_PATH.exists():
        import yaml

        spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8")) or {}
        operations = pii_operations(spec)
    assert authz_gate_violations(workflow, spec, operations) == []


# --- SD-09: nhị phân tải trong CI phải xác minh checksum ---


def test_phat_hien_tai_ve_khong_xac_minh():
    assert len(unverified_downloads(CURL_BLOCK + "    ./x\n")) == 1


def test_tai_ve_co_verify_thi_dat():
    block = CURL_BLOCK + "    python tools/verify_download.py x.tar.gz url\n"
    assert unverified_downloads(block) == []


def test_workflow_that_khong_con_tai_ve_khong_xac_minh():
    assert unverified_downloads(WORKFLOW_PATH.read_text(encoding="utf-8")) == []


def test_pins_file_doc_duoc_va_phu_moi_url_trong_workflow():
    pins = load_pins(PINS_PATH.read_text(encoding="utf-8"))
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for url in pins:
        assert url in text, url
    assert pins


def test_pins_sai_dinh_dang_bao_loi():
    with pytest.raises(ValueError):
        load_pins("abc")


def test_verify_url_khong_khai_bao_bi_chan():
    problems = verify("aa", "https://x/y.tar.gz", {}, None)
    assert problems == ["https://x/y.tar.gz: chưa khai báo trong ci/tool-checksums.txt (fail-closed)"]


def test_verify_pin_khop():
    assert verify("aa", "u", {"u": "aa"}, None) == []


def test_verify_pin_lech_bi_chan():
    problems = verify("bb", "u", {"u": "aa"}, None)
    assert problems and "khác giá trị ghim" in problems[0]


def test_verify_unpinned_can_checksums_url():
    problems = verify("aa", "u", {"u": UNPINNED}, None)
    assert problems and "--checksums-url" in problems[0]


def test_verify_unpinned_khop_checksums_release():
    assert verify("aa", "u", {"u": UNPINNED}, "AA  file.tar.gz\n") == []


def test_verify_unpinned_khong_khop_checksums_release():
    problems = verify("aa", "u", {"u": UNPINNED}, "cc  file.tar.gz\n")
    assert problems and "không có trong tệp checksums" in problems[0]
