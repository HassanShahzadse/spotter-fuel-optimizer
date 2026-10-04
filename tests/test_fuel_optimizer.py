import random

import pytest

from apps.routing.services.fuel_optimizer import (
    Candidate,
    InfeasibleRouteError,
    plan_fuel_stops,
    plan_fuel_stops_greedy,
)


def C(ref, mile, price, detour=0.0):
    return Candidate(ref=ref, mile=mile, price=price, detour_miles=detour)


def test_short_trip_with_full_tank_needs_no_stop():
    plan = plan_fuel_stops([C(1, 100, 3.0)], 400, initial_fuel_gallons=50)
    assert plan.purchases == []
    assert plan.total_cost == 0
    assert plan.final_fuel == pytest.approx(10)


def test_empty_tank_buys_exactly_what_the_trip_needs_at_origin():
    origin = C(99, 0, 3.0)
    plan = plan_fuel_stops([], 300, initial_fuel_gallons=0, origin_station=origin)
    assert len(plan.purchases) == 1
    assert plan.purchases[0].is_origin
    assert plan.total_gallons_purchased == pytest.approx(30)
    assert plan.total_cost == pytest.approx(90)


def test_buys_just_enough_to_reach_cheaper_station():
    origin = C(99, 0, 4.0)
    stations = [C(1, 200, 2.0)]
    plan = plan_fuel_stops(stations, 600, initial_fuel_gallons=0, origin_station=origin, stop_penalty=0)
    # 20 gal at $4 to reach the cheap station, then 40 gal at $2 to finish.
    assert [round(p.gallons, 2) for p in plan.purchases] == [20, 40]
    assert plan.total_cost == pytest.approx(20 * 4 + 40 * 2)


def test_fills_up_when_current_station_is_cheapest():
    origin = C(99, 0, 2.0)
    stations = [C(1, 450, 4.0), C(2, 700, 3.0)]
    plan = plan_fuel_stops(stations, 900, initial_fuel_gallons=0, origin_station=origin, stop_penalty=0)
    first = plan.purchases[0]
    assert first.gallons == pytest.approx(50)  # cheapest fuel on the route -> fill the tank
    assert plan.total_gallons_purchased == pytest.approx(90)


def test_never_exceeds_range():
    stations = [C(i, m, 3.0 + (i % 3) * 0.1) for i, m in enumerate(range(100, 3000, 150))]
    plan = plan_fuel_stops(stations, 3000, initial_fuel_gallons=50)
    fuel, pos = 50.0, 0.0
    for p in plan.purchases:
        fuel -= (p.candidate.mile - pos) / 10
        assert fuel >= -1e-6
        assert p.fuel_on_arrival == pytest.approx(fuel, abs=1e-6)
        fuel += p.gallons
        assert fuel <= 50 + 1e-6
        pos = p.candidate.mile
    assert fuel - (3000 - pos) / 10 >= -1e-6


def test_gap_longer_than_range_is_infeasible():
    with pytest.raises(InfeasibleRouteError):
        plan_fuel_stops([C(1, 300, 3.0), C(2, 900, 3.0)], 1200, initial_fuel_gallons=50)
    with pytest.raises(InfeasibleRouteError):
        plan_fuel_stops_greedy([C(1, 300, 3.0), C(2, 900, 3.0)], 1200, initial_fuel_gallons=50)


@pytest.mark.parametrize("seed", range(40))
def test_dp_without_penalty_matches_provably_optimal_greedy(seed):
    rng = random.Random(seed)
    total = rng.uniform(300, 3000)
    stations = [C(i, rng.uniform(1, total - 1), round(rng.uniform(2.7, 4.5), 3)) for i in range(rng.randint(20, 120))]
    origin = C(-1, 0, round(rng.uniform(2.7, 4.5), 3)) if rng.random() < 0.7 else None
    start = 0.0 if origin else rng.uniform(5, 50)
    try:
        greedy = plan_fuel_stops_greedy(stations, total, initial_fuel_gallons=start, origin_station=origin)
    except InfeasibleRouteError:
        with pytest.raises(InfeasibleRouteError):
            plan_fuel_stops(stations, total, initial_fuel_gallons=start, origin_station=origin)
        return
    dp = plan_fuel_stops(stations, total, initial_fuel_gallons=start, origin_station=origin, stop_penalty=0)
    assert dp.total_cost == pytest.approx(greedy.total_cost, rel=1e-9, abs=1e-6)


def test_stop_penalty_removes_tiny_top_ups():
    origin = C(99, 0, 3.10)
    # A chain of stations each one cent cheaper than the previous -> greedy tops up at each.
    stations = [C(i, 20 * i, 3.10 - 0.01 * i) for i in range(1, 8)] + [C(50, 520, 3.0)]
    strict = plan_fuel_stops(stations, 900, initial_fuel_gallons=0, origin_station=origin, stop_penalty=0)
    practical = plan_fuel_stops(stations, 900, initial_fuel_gallons=0, origin_station=origin, stop_penalty=3)
    assert len(practical.purchases) < len(strict.purchases)
    assert practical.total_cost - strict.total_cost < 3 * (len(strict.purchases) - len(practical.purchases))


def test_detour_counts_against_the_range():
    # 490 route miles + 8 miles off the road = 498: reachable on a full tank.
    plan = plan_fuel_stops([C(1, 490, 3.0, detour=8)], 900, initial_fuel_gallons=50)
    assert [p.candidate.ref for p in plan.purchases] == [1]
    # 490 + 12 = 502 miles: out of range, even though the mile marker alone is fine.
    with pytest.raises(InfeasibleRouteError):
        plan_fuel_stops([C(1, 490, 3.0, detour=12)], 900, initial_fuel_gallons=50)


def test_detours_are_paid_for():
    origin = C(99, 0, 3.0, detour=2)
    stations = [C(1, 300, 3.0, detour=5)]
    plan = plan_fuel_stops(stations, 600, initial_fuel_gallons=0, origin_station=origin, stop_penalty=0)
    # 600 route miles + 2 (origin, one way) + 2 x 5 (en-route stop) = 612 miles = 61.2 gal.
    assert plan.detour_miles == pytest.approx(12)
    assert plan.total_gallons_consumed == pytest.approx(61.2)
    assert plan.total_gallons_purchased == pytest.approx(61.2)
    assert plan.total_cost == pytest.approx(61.2 * 3.0)


def test_close_station_beats_far_off_one_at_the_same_price():
    # Same price, but the far-off station costs 2 x 9 extra miles: the planner avoids it.
    origin = C(99, 0, 3.0)
    stations = [C(1, 400, 3.0, detour=9), C(2, 410, 3.0, detour=0.5)]
    plan = plan_fuel_stops(stations, 800, initial_fuel_gallons=0, origin_station=origin)
    assert [p.candidate.ref for p in plan.purchases if not p.is_origin] == [2]


@pytest.mark.parametrize("seed", range(20))
def test_dp_with_detours_never_runs_dry(seed):
    rng = random.Random(seed)
    total = rng.uniform(500, 2500)
    stations = [
        C(i, rng.uniform(1, total - 1), round(rng.uniform(2.7, 4.5), 3), detour=rng.uniform(0, 10))
        for i in range(rng.randint(30, 120))
    ]
    origin = C(-1, 0, 3.5, detour=rng.uniform(0, 15))
    try:
        plan = plan_fuel_stops(stations, total, initial_fuel_gallons=0, origin_station=origin, stop_penalty=3)
    except InfeasibleRouteError:
        return
    fuel, pos, off = 0.0, 0.0, 0.0
    for p in plan.purchases:
        if not p.is_origin:
            fuel -= (p.candidate.mile - pos + off + p.candidate.detour_miles) / 10
        assert fuel >= -1e-6
        fuel += p.gallons
        assert fuel <= 50 + 1e-6
        pos, off = p.candidate.mile, p.candidate.detour_miles
    assert fuel - (total - pos + off) / 10 >= -1e-6
    assert plan.total_gallons_purchased == pytest.approx(plan.total_gallons_consumed, abs=1e-6)
