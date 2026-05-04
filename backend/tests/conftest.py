import pytest


@pytest.fixture(autouse=True)
def _isolate_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
