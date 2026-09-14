import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import get_config  # noqa: E402
from backend.db import Database  # noqa: E402


@pytest.fixture
def cfg():
    return get_config()


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")
