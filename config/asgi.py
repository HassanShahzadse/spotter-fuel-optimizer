"""ASGI entrypoint."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()

from apps.core.warmup import warm_up  # noqa: E402  (needs the app registry loaded above)

warm_up()
