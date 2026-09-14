import pytest

from backend.config import AppConfig


def test_watchlist_has_ten_per_market(cfg):
    assert sum(s.market == "TW" for s in cfg.stocks) == 10
    assert sum(s.market == "US" for s in cfg.stocks) == 10


def test_every_stock_has_supply_chain_links(cfg):
    linked = {l.source for l in cfg.industry.links} | {l.target for l in cfg.industry.links}
    assert [s.ticker for s in cfg.stocks if s.ticker not in linked] == []


def test_unknown_segment_is_rejected(cfg):
    data = cfg.model_dump()
    data["stocks"][0]["segment"] = "does_not_exist"
    with pytest.raises(ValueError, match="unknown segment"):
        AppConfig.model_validate(data)


def test_link_to_unknown_node_is_rejected(cfg):
    data = cfg.model_dump()
    data["industry"]["links"].append({"source": "NOPE", "target": "PLTR", "what": "x"})
    with pytest.raises(ValueError, match="unknown node"):
        AppConfig.model_validate(data)
