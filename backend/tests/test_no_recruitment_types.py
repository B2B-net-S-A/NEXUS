"""Typów rekrutacji nie ma (decyzja Artura 25.09.2026).

Kolumna `jobs.recruitment_type` zostaje w bazie do osobnej migracji, ale
żaden kod aplikacji jej nie czyta: API jej nie przyjmuje ani nie oddaje,
a statystyki (liga DL, Insights DL, cele KPI) liczą każdą rekrutację.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.schemas.job import JobCreate, JobResponse, JobUpdate

pytestmark = pytest.mark.static

APP = Path(__file__).resolve().parents[1] / "app"

# Jedyne miejsce, które może jeszcze wymieniać kolumnę: definicja modelu.
_ALLOWED = {
    "models/job.py",
}


def test_job_schemas_carry_no_recruitment_type():
    for schema in (JobCreate, JobUpdate, JobResponse):
        assert "recruitment_type" not in schema.model_fields, schema.__name__


def test_no_application_code_reads_the_recruitment_type():
    pattern = re.compile(r"recruitment_type|RecruitmentType|RECRUITMENT_TYPE")
    offenders = [
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if str(path.relative_to(APP)) not in _ALLOWED
        and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
