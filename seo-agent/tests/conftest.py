import pytest


@pytest.fixture(autouse=True)
def isolate_ci_environment(monkeypatch):
    """Tests must never read or write the workflow's real recovery folders: a fake article could otherwise be published."""
    for name in ("SEO_PENDING_DIR", "SEO_RECOVER_DIR", "GITHUB_OUTPUT"):
        monkeypatch.delenv(name, raising=False)
