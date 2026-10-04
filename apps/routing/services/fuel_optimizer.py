"""
Fuel stop planning along a fixed route (the "gas station problem").

Model:

* Each station has a mile marker on the route, a price, and ``detour_miles``
  (its distance from the route). Stopping costs the detour twice, so the leg from
  stop i to stop j is ``mile_j - mile_i + detour_i + detour_j`` miles. Both the
  range limit and the fuel bill include detours.
* Tank capacity is ``max_range / mpg`` gallons (500 / 10 = 50).
* Fuel left at the destination is wasted, so plans arrive close to empty.

``plan_fuel_stops`` is the planner the API uses. ``plan_fuel_stops_greedy`` is the
classic greedy algorithm (Khuller, Malekian & Mestre, 2007), which is optimal when
there are no detours; the tests use it to check the DP.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

EPS = 1e-9


@dataclass(frozen=True, slots=True)
class Candidate:
    """A station on the route. ``ref`` is an opaque id (e.g. DB primary key)."""

    ref: int
    mile: float
    price: float
    detour_miles: float = 0.0


@dataclass(frozen=True, slots=True)
class FuelPurchase:
    candidate: Candidate
    fuel_on_arrival: float
    gallons: float
    cost: float
    is_origin: bool = False

    @property
    def fuel_on_departure(self) -> float:
        return self.fuel_on_arrival + self.gallons


@dataclass
class FuelPlan:
    purchases: list[FuelPurchase] = field(default_factory=list)
    total_miles: float = 0.0
    initial_fuel: float = 0.0
    final_fuel: float = 0.0
    mpg: float = 10.0
    detour_miles: float = 0.0  # extra miles driven off the route to reach the stations

    @property
    def total_cost(self) -> float:
        return sum(p.cost for p in self.purchases)

    @property
    def total_gallons_purchased(self) -> float:
        return sum(p.gallons for p in self.purchases)

    @property
    def total_miles_driven(self) -> float:
        return self.total_miles + self.detour_miles

    @property
    def total_gallons_consumed(self) -> float:
        return self.total_miles_driven / self.mpg


class InfeasibleRouteError(Exception):
    """Raised when a stretch of the route is longer than the vehicle range."""

    def __init__(self, gap_start_mile: float, gap_end_mile: float):
        self.gap_start_mile = gap_start_mile
        self.gap_end_mile = gap_end_mile
        super().__init__(f"No fuel station reachable between mile {gap_start_mile:.0f} and mile {gap_end_mile:.0f}.")


@dataclass(frozen=True, slots=True)
class _Node:
    mile: float
    price: float  # -inf for the destination; +inf when fuel cannot be bought
    candidate: Candidate | None
    is_origin: bool = False
    off: float = 0.0  # detour from the route to this station (one way)

    @property
    def can_buy(self) -> bool:
        return self.candidate is not None


def plan_fuel_stops_greedy(
    candidates: list[Candidate],
    total_miles: float,
    *,
    max_range_miles: float = 500.0,
    mpg: float = 10.0,
    initial_fuel_gallons: float = 0.0,
    origin_station: Candidate | None = None,
) -> FuelPlan:
    """
    Compute the minimum-cost plan on a line, ignoring ``detour_miles``.

    Reference implementation for the tests; the API uses :func:`plan_fuel_stops`.

    :param candidates: stations along the route (any order; mile in [0, total_miles]).
    :param total_miles: route length.
    :param initial_fuel_gallons: fuel already in the tank at the start (free).
    :param origin_station: optional station at the start where the truck may
        buy fuel before departing (treated as mile 0).
    :raises InfeasibleRouteError: if some gap between stations exceeds the range.
    """
    if mpg <= 0 or max_range_miles <= 0:
        raise ValueError("mpg and max_range_miles must be positive")
    capacity = max_range_miles / mpg
    fuel = min(max(initial_fuel_gallons, 0.0), capacity)

    origin = _Node(0.0, origin_station.price if origin_station else float("inf"), origin_station, is_origin=True)
    stations = sorted(
        (_Node(c.mile, c.price, c) for c in candidates if EPS < c.mile < total_miles - EPS),
        key=lambda n: (n.mile, n.price),
    )
    nodes = [origin, *stations, _Node(total_miles, float("-inf"), None)]
    miles = [n.mile for n in nodes]
    plan = FuelPlan(total_miles=total_miles, initial_fuel=fuel, mpg=mpg)

    i = 0
    last = len(nodes) - 1
    while i < last:
        node = nodes[i]
        reach_gallons = capacity if node.can_buy else fuel
        reach_mile = node.mile + reach_gallons * mpg
        k = bisect.bisect_right(miles, reach_mile + EPS) - 1  # farthest reachable node index
        if k <= i:
            next_mile = nodes[i + 1].mile
            raise InfeasibleRouteError(node.mile, next_mile)

        if not node.can_buy:
            # Can't buy here (e.g. origin with no nearby station): drive on the fuel we have.
            j = last if k == last else _cheapest(nodes, i + 1, k)
            fuel -= (nodes[j].mile - node.mile) / mpg
            i = j
            continue

        cheaper = next((j for j in range(i + 1, k + 1) if nodes[j].price < node.price - EPS), None)
        if cheaper is not None:
            need = (nodes[cheaper].mile - node.mile) / mpg
            buy = max(0.0, need - fuel)
            target = cheaper
        else:
            buy = capacity - fuel
            target = _cheapest(nodes, i + 1, k)

        if buy > EPS:
            plan.purchases.append(FuelPurchase(node.candidate, fuel, buy, buy * node.price, is_origin=node.is_origin))
            fuel += buy
        fuel -= (nodes[target].mile - node.mile) / mpg
        fuel = max(fuel, 0.0) if fuel > -EPS else fuel
        i = target

    plan.final_fuel = max(fuel, 0.0)
    return plan


def _cheapest(nodes: list[_Node], lo: int, hi: int) -> int:
    """Index of the cheapest node in ``nodes[lo..hi]``; ties resolved to the farthest."""
    best = lo
    for j in range(lo + 1, hi + 1):
        if nodes[j].price <= nodes[best].price + EPS:
            best = j
    return best


# Exact DP with a per-stop penalty (default planner)
def plan_fuel_stops(
    candidates: list[Candidate],
    total_miles: float,
    *,
    max_range_miles: float = 500.0,
    mpg: float = 10.0,
    initial_fuel_gallons: float = 0.0,
    origin_station: Candidate | None = None,
    stop_penalty: float = 0.0,
) -> FuelPlan:
    """
    Minimum-cost plan with a per-stop penalty.

    Without a penalty the cheapest plan can include tiny top-ups, e.g. buying
    0.2 gallons because the next station is a cent cheaper. This planner
    minimises ``fuel_cost + stop_penalty * stops``, with ties going to fewer stops.

    It is a dynamic program based on the fact that some optimal plan always
    either fills the tank or buys just enough to reach the next stop. The fuel
    on arrival at a station is therefore 0, ``capacity - d(k, i)`` for an earlier
    stop k, or ``initial_fuel - d(origin, i)``. Both purchase options reduce to
    minimising ``objective - fuel * price``, so prefix minima keep the work per
    station at O(states + reachable stations).

    ``d(i, j)`` includes the detours to both stations. The origin station's
    detour is counted once, since the truck starts there. With
    ``stop_penalty=0`` and no detours the cost matches the greedy planner.
    """
    if mpg <= 0 or max_range_miles <= 0:
        raise ValueError("mpg and max_range_miles must be positive")
    capacity = max_range_miles / mpg
    fuel0 = min(max(initial_fuel_gallons, 0.0), capacity)

    origin = _Node(
        0.0,
        origin_station.price if origin_station else float("inf"),
        origin_station,
        is_origin=True,
        off=origin_station.detour_miles if origin_station else 0.0,
    )
    stations = sorted(
        (_Node(c.mile, c.price, c, off=c.detour_miles) for c in candidates if EPS < c.mile < total_miles - EPS),
        key=lambda n: (n.mile, n.price),
    )
    nodes = [origin, *stations, _Node(total_miles, float("-inf"), None)]
    miles = [n.mile for n in nodes]
    last = len(nodes) - 1

    def gallons(i: int, j: int, *, from_station: bool = True) -> float:
        """Fuel to drive from node i (at its pump, or still on the route) to node j's pump."""
        start_off = nodes[i].off if from_station else 0.0
        return (nodes[j].mile - nodes[i].mile + start_off + nodes[j].off) / mpg

    # states[i]: arrival_fuel_key -> (objective, stops, fuel_cost, arrival_fuel, prev_i, prev_key, bought)
    states: list[dict[float, tuple]] = [dict() for _ in nodes]
    states[0][round(fuel0, 6)] = (0.0, 0, 0.0, fuel0, None, None, 0.0)

    def relax(j: int, fuel: float, obj: float, stops: int, cost: float, i: int, key_i: float, bought: float):
        key = round(max(fuel, 0.0), 6)
        current = states[j].get(key)
        if (
            current is None
            or (obj, stops) < (current[0] - EPS, current[1])
            or (abs(obj - current[0]) <= EPS and stops < current[1])
        ):
            states[j][key] = (obj, stops, cost, max(fuel, 0.0), i, key_i, bought)

    for i in range(last):
        if not states[i]:
            continue
        node = nodes[i]
        # (key, objective, stops, arrival_fuel) sorted by fuel ascending
        items = sorted(((key, st[0], st[1], st[3]) for key, st in states[i].items()), key=lambda t: t[3])

        if i == 0:
            # Origin: may drive on the fuel already in the tank without buying anything.
            for key, obj, stops, fuel in items:
                k = bisect.bisect_right(miles, node.mile + fuel * mpg + EPS) - 1
                for j in range(1, k + 1):
                    need = gallons(0, j, from_station=False)
                    if need <= fuel + EPS:
                        relax(j, fuel - need, obj, stops, states[0][key][2], 0, key, 0.0)
        if not node.can_buy:
            continue

        price = node.price
        # Buying x gallons from a state with fuel g costs obj + (x)*price. Both options below
        # reduce to minimising (obj - g * price) over states, so precompute prefix minima.
        adjusted = [((obj - fuel * price), stops, key, fuel) for key, obj, stops, fuel in items]
        prefix_best = []
        best = None
        for entry in adjusted:
            if best is None or (entry[0], entry[1]) < (best[0], best[1]):
                best = entry
            prefix_best.append(best)
        overall = prefix_best[-1]
        fuels = [entry[3] for entry in adjusted]

        # Mile markers only bound the reach; detours are checked per station.
        k = bisect.bisect_right(miles, node.mile + capacity * mpg + EPS) - 1
        for j in range(i + 1, k + 1):
            need = gallons(i, j)
            if need > capacity + EPS:
                continue
            # Option A: buy just enough to arrive at j empty (only states with fuel < need).
            n_below = bisect.bisect_left(fuels, need - EPS)
            if n_below:
                adj, stops, key, fuel = prefix_best[n_below - 1]
                buy = need - fuel
                paid = buy * price
                cost = states[i][key][2] + paid
                relax(j, 0.0, adj + need * price + stop_penalty, stops + 1, cost, i, key, buy)
            # Option B: fill the tank here (pointless right before the destination).
            if j != last:
                adj, stops, key, fuel = overall
                buy = capacity - fuel
                if buy > EPS:
                    cost = states[i][key][2] + buy * price
                    relax(j, capacity - need, adj + capacity * price + stop_penalty, stops + 1, cost, i, key, buy)

    if not states[last]:
        reached = max((n.mile for n, st in zip(nodes, states, strict=True) if st), default=0.0)
        nxt = next((m for m in miles if m > reached + EPS), total_miles)
        raise InfeasibleRouteError(reached, nxt)

    # Backtrack the best final state.
    key = min(states[last], key=lambda kk: (states[last][kk][0], states[last][kk][1]))
    j = last
    final_fuel = states[last][key][3]
    chain = []
    detour = 0.0
    while True:
        obj, stops, cost, fuel, prev_i, prev_key, bought = states[j][key]
        if prev_i is None:
            break
        prev_state = states[prev_i][prev_key]
        if bought > EPS:
            stop = nodes[prev_i]
            detour += stop.off if stop.is_origin else 2 * stop.off
            chain.append(
                FuelPurchase(
                    nodes[prev_i].candidate,
                    prev_state[3],
                    bought,
                    bought * nodes[prev_i].price,
                    is_origin=nodes[prev_i].is_origin,
                )
            )
        j, key = prev_i, prev_key
    chain.reverse()
    return FuelPlan(
        purchases=chain,
        total_miles=total_miles,
        initial_fuel=fuel0,
        final_fuel=final_fuel,
        mpg=mpg,
        detour_miles=detour,
    )
