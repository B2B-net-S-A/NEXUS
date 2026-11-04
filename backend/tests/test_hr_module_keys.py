"""Klucze modułów „Ludzi”: ``HrModule`` to te same wartości co ``HR_MODULE_KEYS``."""

from __future__ import annotations

from app.services.hr.modules import HrModule, normalize
from app.services.hr_foundation_schema import HR_MODULE_KEYS


def test_hr_module_enum_matches_schema_keys_in_order() -> None:
    assert tuple(HrModule) == HR_MODULE_KEYS


def test_enum_member_reads_the_switch_like_its_key() -> None:
    switches = normalize({"equipment": True})
    assert switches[HrModule.equipment] is True
    assert switches.get(HrModule.care) is False
