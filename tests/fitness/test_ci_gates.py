"""Test cho các cổng CI dạng script (QLKH-001).

Phủ tiêu chí chấp nhận 2 (SCA/license chặn) và 3 (SBOM CycloneDX), gồm cả đường lỗi.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.check_authz_tests import missing_authz_tests, pii_operations
from tools.check_licenses import check as check_licenses
from tools.check_sbom import main as sbom_main
from tools.check_sbom import validate as validate_sbom

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for job in ("lint:", "test:", "fitness:", "sast:", "sca:", "secrets:", "iac:", "license:", "sbom:"):
        assert job in workflow, job
