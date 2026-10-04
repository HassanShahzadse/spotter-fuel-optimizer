"""WSGI entrypoint (used by gunicorn and runserver)."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

from apps.core.warmup import warm_up  # noqa: E402  (needs the app registry loaded above)

warm_up()
