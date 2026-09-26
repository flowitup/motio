import os
import tempfile

# Dữ liệu test nằm trong thư mục tạm, không đụng data/ thật. Phải đặt trước khi import motio.
os.environ["MOTIO_DATA"] = tempfile.mkdtemp(prefix="motio-test-")

import pytest  # noqa: E402

from motio import settings  # noqa: E402


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    """Mỗi test bắt đầu không có settings.json và không có key trong môi trường."""
    settings.path().unlink(missing_ok=True)
    for k in settings.KEYS:
        monkeypatch.delenv(k, raising=False)
    yield
    settings.path().unlink(missing_ok=True)
