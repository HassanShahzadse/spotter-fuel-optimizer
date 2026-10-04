# Fuel Route Optimizer API

A Django REST API that takes a start and a finish location in the USA and returns the cheapest fuel stops
along the route, the total fuel cost and a link to an interactive map of the route.

- **Vehicle:** 500 mile range (50 gallon tank) at 10 MPG, leaves with a full tank
- **Fuel prices:** `data/fuel-prices-for-be-assessment.csv`
- **Routing:** [OpenRouteService](https://openrouteservice.org) (free key), or the public OSRM server without a key
- **Map:** OpenStreetMap via Leaflet

## Quick start

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                   # Windows: copy .env.example .env
python manage.py migrate
python manage.py import_fuel_stations  # loads and geocodes the CSV (offline, ~2 s)
python manage.py runserver
```

**Add your routing key:** set `ORS_API_KEY` in `.env` ([free signup](https://openrouteservice.org/dev/#/signup)).
Without a key the app still works, using the public OSRM demo server.

Then open http://127.0.0.1:8000/api/docs/ (Swagger), or import `fuel-route-optimizer.postman_collection.json`
into Postman (`base_url` defaults to `http://127.0.0.1:8000`).

## API

### `POST /api/v1/route/`

```json
{ "start": "New York, NY", "finish": "Los Angeles, CA" }
```

`start` and `finish` accept `"City, ST"`, a ZIP code, `"lat,lng"` or a street address.

| Optional field     | Default | Description                                            |
|--------------------|---------|--------------------------------------------------------|
| `start_fuel_level` | `1`     | Tank level at departure (`0` = empty, `1` = full)      |
| `corridor_miles`   | `10`    | Max distance between a station and the route           |
| `max_range_miles`  | `500`   | Vehicle range on a full tank                           |
| `mpg`              | `10`    | Fuel economy                                           |
| `stop_penalty_usd` | `3`     | Cost of one extra stop, to avoid tiny top-ups          |
| `include_geometry` | `false` | Also return the route as an encoded polyline           |

**Response**

```json
{
  "start": "New York, NY",
  "finish": "Los Angeles, CA",
  "distance_miles": 2792.4,
  "fuel_stops": [
    {
      "stop": 1,
      "station": "SHEETZ #791",
      "address": "I-76, Exit 57, North Jackson, OH",
      "mile": 401.8,
      "price_per_gallon": 3.066,
      "gallons": 35.79,
      "cost": 109.71
    }
  ],
  "total_gallons": 231.61,
  "total_fuel_cost": 706.22,
  "map_url": "http://127.0.0.1:8000/api/v1/route/3130d22e2e0786ebb654/map/",
  "meta": { "routing_api_calls": 1, "cached": false, "response_time_ms": 2400.0 }
}
```

The same endpoint also accepts `GET` with query parameters. Every error uses one format:

```json
{ "error": { "code": "location_outside_usa", "message": "...", "details": null } }
```

| Status | When                                                                   |
|--------|------------------------------------------------------------------------|
| 400    | Invalid input, or start and finish are the same place                  |
| 422    | Location not found or outside the USA, no route, or trip not feasible  |
| 502    | The routing or geocoding service failed                                |

### Other endpoints

| Endpoint                      | Purpose                                                  |
|-------------------------------|----------------------------------------------------------|
| `GET /api/v1/route/<id>/map/` | Interactive map of a computed route (the `map_url` link) |
| `GET /api/v1/stations/`       | Imported stations, filterable by `state` and `city`      |
| `GET /api/v1/health/`         | Database, station data and routing provider status       |
| `GET /api/docs/`              | Swagger UI (OpenAPI schema at `/api/schema/`)            |

## How it works

1. **Stations.** The CSV has no coordinates, so `import_fuel_stations` geocodes each station once, offline,
   from the bundled USPS ZIP database. Canadian rows and duplicates are dropped (the lowest price is kept),
   which leaves 6,626 US stations.
2. **Route.** One call to the routing API per new route. City and ZIP inputs are geocoded offline, and
   results are cached, so a repeated request makes no API call.
3. **Stations near the route.** Every station within `corridor_miles` of the route line, found with a KD-tree
   over an in-memory index.
4. **Optimal stops.** An exact dynamic program picks the stops with the lowest total fuel cost without
   ever going more than 500 miles between fill-ups. The detour to each station counts against the range.

## Project layout

```
apps/
  core/       offline gazetteer, US border check, geo helpers, error handling, health
  stations/   FuelStation model, CSV importer, in-memory station index
  routing/    API views, geocoding, routing providers, fuel optimizer, map page
config/       settings (all values from environment variables, see .env.example)
tests/        pytest suite; upstream HTTP calls are mocked
```

## Tests

```bash
python -m pytest            # full suite, no network needed
python -m pytest -m live    # optional smoke tests against the real routing/geocoding APIs
ruff check . && ruff format --check .
```

CI (`.github/workflows/ci.yml`) runs the linter, Django's deploy checks and the test suite.

## Assumptions

- The truck leaves with a full tank, so `total_fuel_cost` is the fuel bought along the way.
- Station locations are city-level, because the price file only has city and state.
