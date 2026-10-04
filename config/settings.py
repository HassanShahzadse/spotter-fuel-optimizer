"""
Django settings. Values come from environment variables or a local ``.env`` file
(see ``.env.example``).
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1", "0.0.0.0"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    CORS_ALLOWED_ORIGINS=(list, []),
)
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

# Core
DEBUG = env("DEBUG")
# A development fallback is allowed only with DEBUG on; production must set SECRET_KEY.
SECRET_KEY = env("SECRET_KEY", default="django-insecure-dev-only-change-me") if DEBUG else env("SECRET_KEY")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    # Local apps
    "apps.core",
    "apps.stations",
    "apps.routing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestTimingMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Database: SQLite by default, or any database via DATABASE_URL
DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache: Redis when REDIS_URL is set, otherwise a file cache on disk. Both are shared
# between worker processes, so map links and cached routes work with several workers.
REDIS_URL = env("REDIS_URL", default="")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "TIMEOUT": 60 * 60 * 24,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": env("CACHE_DIR", default=str(BASE_DIR / ".cache")),
            "TIMEOUT": 60 * 60 * 24,
            "OPTIONS": {"MAX_ENTRIES": 5000},
        }
    }

# Auth, i18n, static files
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Django REST Framework and OpenAPI
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": env("API_THROTTLE_RATE", default="120/min")},
    "UNAUTHENTICATED_USER": None,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Fuel Route Optimizer API",
    "DESCRIPTION": (
        "Plan a driving route between two US locations and get the most "
        "cost-effective fuel stops (500 mile range, 10 MPG) plus the total fuel cost."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")

# Vehicle, routing and geocoding
FUEL_ROUTE = {
    # Vehicle
    "VEHICLE_MAX_RANGE_MILES": env.float("VEHICLE_MAX_RANGE_MILES", default=500.0),
    "VEHICLE_MPG": env.float("VEHICLE_MPG", default=10.0),
    # Max distance (miles) a station may sit from the route line to be considered.
    "CORRIDOR_MILES": env.float("CORRIDOR_MILES", default=10.0),
    # Objective = fuel cost + STOP_PENALTY_USD per stop. Removes pointless "top-up" stops
    # that save only cents. Set to 0 for the strict cheapest-fuel plan.
    "STOP_PENALTY_USD": env.float("STOP_PENALTY_USD", default=3.0),
    # Tank level when the truck leaves (1.0 = full). Total cost = fuel bought at the stops on the way.
    "START_FUEL_LEVEL": env.float("START_FUEL_LEVEL", default=1.0),
    # Max points in the encoded route polyline returned by the API (the map page uses more).
    "RESPONSE_POLYLINE_POINTS": env.int("RESPONSE_POLYLINE_POINTS", default=500),
    # Radius (miles) around the start point in which the truck can fill up before departing.
    "ORIGIN_FUEL_RADIUS_MILES": env.float("ORIGIN_FUEL_RADIUS_MILES", default=15.0),
    # Routing: "auto" (ORS when a key is set, else OSRM), "ors" or "osrm".
    "ROUTING_PROVIDER": env("ROUTING_PROVIDER", default="auto"),
    "ORS_API_KEY": env("ORS_API_KEY", default=""),
    "ORS_BASE_URL": env("ORS_BASE_URL", default="https://api.openrouteservice.org"),
    "ORS_PROFILE": env("ORS_PROFILE", default="driving-car"),
    "OSRM_BASE_URL": env("OSRM_BASE_URL", default="https://router.project-osrm.org"),
    # Geocoding fallback for free-form addresses: "auto", "ors", "nominatim" or "none".
    "GEOCODER_PROVIDER": env("GEOCODER_PROVIDER", default="auto"),
    "NOMINATIM_BASE_URL": env("NOMINATIM_BASE_URL", default="https://nominatim.openstreetmap.org"),
    "HTTP_USER_AGENT": env("HTTP_USER_AGENT", default="fuel-route-optimizer/1.0"),
    # Fail fast: worst case is (1 + retries) x timeout before the API answers 502.
    "HTTP_TIMEOUT_SECONDS": env.float("HTTP_TIMEOUT_SECONDS", default=10.0),
    "HTTP_MAX_RETRIES": env.int("HTTP_MAX_RETRIES", default=1),
    # Caching
    "ROUTE_CACHE_TTL_SECONDS": env.int("ROUTE_CACHE_TTL_SECONDS", default=60 * 60 * 24),
    "GEOCODE_CACHE_TTL_SECONDS": env.int("GEOCODE_CACHE_TTL_SECONDS", default=60 * 60 * 24 * 30),
    # Max points kept in the returned route geometry (the full geometry is used for calculations).
    "MAX_GEOMETRY_POINTS": env.int("MAX_GEOMETRY_POINTS", default=2000),
}

FUEL_PRICES_CSV = env("FUEL_PRICES_CSV", default=str(BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"))

# Security (when DEBUG is off)
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
    SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)
    CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
    X_FRAME_OPTIONS = "DENY"

# Logging
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s [%(name)s] %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}
