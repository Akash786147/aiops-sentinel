from app import victim


def test_orders_endpoint_returns_orders_without_detail_lookup():
    before = victim.request_count
    response = victim.list_orders(include_customer_profile=False)
    assert len(response) == 30
    assert victim.request_count == before + 1


def test_orders_endpoint_stays_under_latency_budget():
    """Generated guard test candidate: the non-detailed endpoint should remain fast."""
    victim.list_orders(include_customer_profile=False)
    assert victim.latencies[-1] < 100
