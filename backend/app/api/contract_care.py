"""Opieka nad konsultantami i mapa technologii klienta.

Prefiks ``/api/care`` (wpięty w ``app/main.py``). Każda trasa ma nazwaną bramkę
``require_hr_*`` (``app/api/hr_gates.py`` albo własną w tym module) i sprawdza
przełącznik modułu w ``app_settings['hr_modules']``.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
