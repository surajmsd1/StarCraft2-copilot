from sc2copilot.replay.benchmarks import (
    distance,
    earliest_order_near,
    is_proxy_location,
)


def test_distance():
    assert distance((0, 0), (3, 4)) == 5.0


def test_proxy_location_detection():
    own = (20.0, 20.0)
    enemy = (140.0, 140.0)
    assert is_proxy_location((120.0, 130.0), own, enemy)          # in their face
    assert is_proxy_location((80.0, 80.0), own, enemy) is False    # exact midpoint; tie -> not proxy
    assert not is_proxy_location((25.0, 22.0), own, enemy)         # in main


def test_earliest_order_near_picks_first_send():
    site = (120.0, 130.0)
    commands = [
        (5.0, (30.0, 30.0)),     # early move in main
        (19.0, (118.0, 128.0)),  # the proxy send
        (30.0, (121.0, 131.0)),  # follow-up click at site
        (60.0, (119.0, 129.0)),  # after building started - excluded by `before`
    ]
    assert earliest_order_near(commands, site, before=48.0) == 19.0


def test_earliest_order_near_none_when_no_hits():
    assert earliest_order_near([(5.0, (0.0, 0.0))], (100.0, 100.0), before=50.0) is None
