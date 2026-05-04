from app.models import ComponentType
from app.patterns import alerting


def test_rdbms_and_mcp_get_p0() -> None:
    assert alerting.alerter_for(ComponentType.RDBMS).tier == "P0"
    assert alerting.alerter_for(ComponentType.MCP).tier == "P0"


def test_api_and_queue_get_p1() -> None:
    assert alerting.alerter_for(ComponentType.API).tier == "P1"
    assert alerting.alerter_for(ComponentType.QUEUE).tier == "P1"


def test_cache_and_nosql_get_p2() -> None:
    assert alerting.alerter_for(ComponentType.CACHE).tier == "P2"
    assert alerting.alerter_for(ComponentType.NOSQL).tier == "P2"


def test_strategy_pattern_swappable() -> None:
    # Demonstrate the strategy is hot-swappable: rebind CACHE to P0.
    original = alerting.ALERT_MAP[ComponentType.CACHE]
    try:
        alerting.ALERT_MAP[ComponentType.CACHE] = alerting.P0Alerter()
        assert alerting.alerter_for(ComponentType.CACHE).tier == "P0"
    finally:
        alerting.ALERT_MAP[ComponentType.CACHE] = original
    assert alerting.alerter_for(ComponentType.CACHE).tier == "P2"
