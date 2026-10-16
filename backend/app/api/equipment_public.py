"""Publiczny link do podpisu protokołu wydania/zwrotu sprzętu.

Prefiks ``/api/public/equipment-protocols`` (wpięty w ``app/main.py``). Trasy
mają ``@limiter.limit`` — dlatego moduł NIE ma ``from __future__ import
annotations`` (ciało żądania lądowałoby jako parametr query → 422).
Token w adresie jest porównywany z hashem w bazie; bez logowania.
"""

from fastapi import APIRouter

router = APIRouter()
