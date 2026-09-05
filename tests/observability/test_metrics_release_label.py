from qlkh.infrastructure.observability.metrics import release_version, with_release_label


def test_release_version_default_unknown(monkeypatch):
    monkeypatch.delenv("QLKH_RELEASE_VERSION", raising=False)
    assert release_version() == "unknown"


def test_release_version_from_env(monkeypatch):
    monkeypatch.setenv("QLKH_RELEASE_VERSION", "v1.2.3")
    assert release_version() == "v1.2.3"


def test_with_release_label_adds_label(monkeypatch):
    monkeypatch.setenv("QLKH_RELEASE_VERSION", "v1.2.3")
    labels = with_release_label({"service": "orders-api"})
    assert labels["release_version"] == "v1.2.3"
    assert labels["service"] == "orders-api"


def test_with_release_label_does_not_override_existing(monkeypatch):
    monkeypatch.setenv("QLKH_RELEASE_VERSION", "v1.2.3")
    labels = with_release_label({"release_version": "explicit"})
    assert labels["release_version"] == "explicit"
