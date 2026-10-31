import pytest

from atlas_api.db import DB
from atlas_api.providers.demo import DemoProvider
from atlas_api.service import MarketService


@pytest.fixture
def db(tmp_path):
    return DB(str(tmp_path / "t.db"))


@pytest.fixture
def demo_service():
    return MarketService({"demo": DemoProvider()}, demo=True)
