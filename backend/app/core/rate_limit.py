"""Rate limiter shared across routers.

Uses slowapi's `Limiter`. The shared instance is attached to the FastAPI
app state in ``main.py``; individual routers import ``limiter`` from here
and apply decorators like ``@limiter.limit("5/minute")``.

Key function is ``get_remote_address`` (client IP). When deployed behind a
reverse proxy (Coolify/Traefik/Cloudflare), ensure ``X-Forwarded-For`` is
trusted by the ASGI server for accurate client IPs.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=[])
