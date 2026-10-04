"""
Offline check for whether a point is inside the USA.

A point counts as US if it is inside one of the US bounding boxes and outside every
foreign polygon below. The polygons follow the Canada and Mexico land borders only
where foreign land overlaps a US box, so no US coastline is needed. Accuracy is
about 1 mile along the borders.

Coordinates are (lat, lng) in degrees.
"""

from __future__ import annotations

US_BOUNDING_BOXES: tuple[tuple[float, float, float, float], ...] = (
    # (south, north, west, east)
    (24.3, 49.5, -125.0, -66.8),  # contiguous 48 states
    (51.0, 71.6, -180.0, -129.9),  # Alaska
    (51.0, 53.1, 172.0, 180.0),  # western Aleutians (east of the antimeridian)
    (18.8, 22.4, -160.4, -154.6),  # Hawaii
)

# British Columbia, Alberta, Saskatchewan, Manitoba: the 49th parallel, then
# down Haro Strait and the Strait of Juan de Fuca around southern Vancouver Island.
_CANADA_WEST = (
    (49.6, -95.153),
    (49.0, -95.153),
    (49.0, -123.322),
    (48.77, -123.03),
    (48.69, -123.22),
    (48.45, -123.18),
    (48.28, -123.25),
    (48.24, -123.55),
    (48.30, -124.0),
    (48.49, -124.73),
    (48.49, -125.5),
    (49.6, -125.5),
)

# Ontario, Quebec and New Brunswick: Lake of the Woods, Rainy River, the
# Boundary Waters, Lakes Superior/Huron/Erie/Ontario, the connecting rivers,
# the St. Lawrence, the 45th parallel and the Maine border.
_CANADA_EAST = (
    (49.6, -95.153),
    (49.384, -95.153),  # Northwest Angle
    (49.31, -94.83),
    (48.84, -94.68),  # Rainy River mouth
    (48.715, -94.59),  # Baudette / Rainy River
    (48.65, -94.10),
    (48.61, -93.75),
    (48.604, -93.40),  # International Falls / Fort Frances
    (48.625, -93.33),
    (48.62, -93.05),
    (48.43, -92.65),
    (48.35, -92.15),
    (48.20, -91.80),
    (48.08, -91.55),
    (48.13, -91.15),
    (48.24, -90.88),
    (48.09, -90.70),
    (48.05, -90.30),
    (48.00, -89.90),
    (48.00, -89.57),  # Pigeon River mouth
    (48.05, -89.30),
    (48.30, -88.60),  # north of Isle Royale
    (48.30, -88.30),
    (47.80, -87.00),
    (47.30, -85.80),
    (46.92, -84.95),
    (46.62, -84.62),
    (46.51, -84.45),
    (46.505, -84.35),  # Sault Ste. Marie
    (46.47, -84.10),
    (46.30, -84.05),
    (46.10, -83.95),
    (45.98, -83.55),
    (45.95, -83.45),
    (45.40, -82.55),
    (44.50, -82.25),
    (43.60, -82.25),
    (43.00, -82.41),  # Port Huron / Sarnia
    (42.95, -82.418),
    (42.80, -82.465),
    (42.72, -82.483),
    (42.62, -82.51),
    (42.55, -82.60),
    (42.47, -82.72),
    (42.345, -82.93),  # head of the Detroit River
    (42.33, -82.98),
    (42.322, -83.04),  # Detroit / Windsor
    (42.30, -83.09),
    (42.25, -83.12),
    (42.18, -83.135),
    (42.10, -83.125),
    (42.03, -83.13),
    (41.95, -83.10),
    (41.78, -82.93),
    (41.74, -82.80),
    (41.66, -82.68),  # south of Pelee and Middle Islands
    (41.70, -82.45),
    (41.73, -82.40),
    (42.00, -81.50),
    (42.27, -80.75),
    (42.55, -79.80),
    (42.78, -79.05),
    (42.87, -78.91),
    (42.92, -78.915),  # Buffalo / Fort Erie
    (42.97, -79.01),
    (43.06, -79.05),
    (43.08, -79.07),  # Niagara Falls
    (43.15, -79.045),
    (43.26, -79.06),  # Niagara River mouth
    (43.63, -78.68),
    (43.63, -77.00),
    (43.90, -76.50),
    (44.10, -76.45),
    (44.15, -76.33),
    (44.20, -76.18),
    (44.27, -76.07),
    (44.33, -76.04),
    (44.36, -75.97),  # around Wellesley Island
    (44.37, -75.93),  # Alexandria Bay / Rockport
    (44.45, -75.83),
    (44.57, -75.69),
    (44.60, -75.65),  # Morristown / Brockville
    (44.705, -75.50),  # Ogdensburg / Prescott
    (44.88, -75.19),
    (44.99, -74.80),
    (45.003, -74.67),
    (45.01, -73.35),
    (45.012, -71.50),
    (45.25, -71.40),
    (45.305, -71.08),
    (45.40, -70.82),
    (45.55, -70.72),
    (45.65, -70.48),
    (45.95, -70.25),
    (46.20, -70.05),
    (46.42, -70.03),
    (46.70, -69.85),
    (47.00, -69.60),
    (47.47, -69.22),  # Estcourt Station
    (47.18, -68.90),
    (47.265, -68.59),  # Fort Kent / Clair
    (47.30, -68.45),
    (47.36, -68.33),  # Madawaska / Edmundston
    (47.345, -68.23),
    (47.315, -68.15),
    (47.16, -67.935),
    (47.07, -67.79),
    (45.94, -67.78),
    (45.60, -67.43),
    (45.189, -67.28),  # Calais / St. Stephen
    (45.10, -67.10),
    (44.90, -66.96),  # Lubec / Campobello
    (44.60, -66.95),
    (44.60, -66.50),
    (49.6, -66.50),
)

# Yukon and northern British Columbia next to Alaska: the 141st meridian,
# the Panhandle border and the Dixon Entrance.
_CANADA_ALASKA = (
    (72.0, -141.0),
    (60.31, -141.0),
    (60.0, -139.05),
    (59.90, -138.70),
    (59.27, -137.48),
    (59.45, -136.30),
    (59.62, -135.15),  # White Pass
    (59.40, -134.30),
    (58.95, -133.85),
    (58.60, -133.40),
    (57.95, -133.00),
    (57.50, -132.30),
    (56.80, -131.85),
    (56.40, -131.10),
    (56.10, -130.10),
    (55.98, -130.00),
    (55.90, -130.01),  # Hyder / Stewart
    (55.70, -130.12),
    (55.30, -130.05),
    (54.72, -130.62),
    (54.67, -133.50),
    (51.0, -133.50),
    (51.0, -129.0),
    (72.0, -129.0),
)

# Northern Mexico: the straight-line borders of California, Arizona and New
# Mexico, then the Rio Grande to the Gulf.
_MEXICO = (
    (32.534, -118.5),
    (32.534, -117.124),  # Pacific end of the border
    (32.718, -114.719),  # Colorado River (Yuma)
    (32.60, -114.78),
    (32.49, -114.81),
    (31.332, -111.074),  # Nogales
    (31.332, -108.208),
    (31.784, -108.208),
    (31.784, -106.528),
    (31.765, -106.515),
    (31.748, -106.49),  # El Paso / Ciudad Juarez
    (31.752, -106.475),
    (31.764, -106.452),
    (31.735, -106.40),
    (31.672, -106.336),
    (31.60, -106.30),
    (31.52, -106.24),
    (31.42, -106.13),
    (31.10, -105.60),
    (30.65, -104.98),
    (30.25, -104.70),
    (29.60, -104.45),
    (29.53, -104.33),  # Presidio / Ojinaga
    (29.27, -103.85),
    (29.05, -103.40),
    (28.97, -103.15),  # Big Bend
    (29.20, -102.85),
    (29.55, -102.70),
    (29.80, -102.30),
    (29.75, -101.65),
    (29.45, -101.05),
    (29.335, -100.92),  # Del Rio / Ciudad Acuna
    (28.95, -100.65),
    (28.705, -100.51),  # Eagle Pass / Piedras Negras
    (28.20, -100.20),
    (27.75, -99.80),
    (27.497, -99.51),  # Laredo / Nuevo Laredo
    (27.00, -99.45),
    (26.60, -99.20),
    (26.40, -99.025),  # Roma / Miguel Aleman
    (26.25, -98.65),
    (26.17, -98.42),
    (26.10, -98.30),
    (26.093, -98.27),  # Hidalgo / Reynosa
    (26.05, -98.10),
    (26.07, -97.95),
    (26.03, -97.75),
    (25.95, -97.60),
    (25.885, -97.49),  # Brownsville / Matamoros
    (25.955, -97.145),  # Rio Grande mouth
    (25.96, -96.5),
    (24.0, -96.5),
    (24.0, -118.5),
)

# The Bahamas sit inside the contiguous-US box east of Florida.
_BAHAMAS = (
    (27.4, -79.4),
    (27.4, -72.0),
    (20.0, -72.0),
    (20.0, -79.4),
)

FOREIGN_POLYGONS: tuple[tuple[str, tuple[tuple[float, float], ...]], ...] = (
    ("Canada", _CANADA_WEST),
    ("Canada", _CANADA_EAST),
    ("Canada", _CANADA_ALASKA),
    ("Mexico", _MEXICO),
    ("The Bahamas", _BAHAMAS),
)


def _in_polygon(lat: float, lng: float, polygon: tuple[tuple[float, float], ...]) -> bool:
    """Ray casting point-in-polygon test (polygon edges are straight lines in lat/lng)."""
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        lat_i, lng_i = polygon[i]
        lat_j, lng_j = polygon[j]
        if (lat_i > lat) != (lat_j > lat):
            cross_lng = lng_i + (lat - lat_i) * (lng_j - lng_i) / (lat_j - lat_i)
            if lng < cross_lng:
                inside = not inside
        j = i
    return inside


def foreign_country_at(lat: float, lng: float) -> str | None:
    """Name of the neighbouring country at this point, if it falls on a foreign polygon."""
    for country, polygon in FOREIGN_POLYGONS:
        if _in_polygon(lat, lng, polygon):
            return country
    return None


def is_within_usa(lat: float, lng: float) -> bool:
    in_box = any(s <= lat <= n and w <= lng <= e for s, n, w, e in US_BOUNDING_BOXES)
    return in_box and foreign_country_at(lat, lng) is None
