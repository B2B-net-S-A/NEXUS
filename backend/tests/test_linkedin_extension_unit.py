"""Wtyczka LinkedIn (28.10.2026) — logika bez bazy: klucz, limit, rozpoznanie
osoby, szkic wiadomości. Dane fikcyjne."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.schemas.linkedin_extension import ExperienceItem, ProfileRead
from app.services import linkedin_extension_auth as auth
from app.services import linkedin_extension_lookup as lookup
from app.services import linkedin_message_draft as draft


# ── Wersja wtyczki ───────────────────────────────────────────────────────────


def test_latest_version_matches_extension_manifest() -> None:
    """Panel pokazuje „Jest nowa wersja”, gdy jego wersja < tej z NEXUSA.
    Podbicie wersji w extension/manifest.json bez tej stałej = brak banera."""
    import json
    from pathlib import Path

    manifest = Path(__file__).resolve().parents[2] / "extension" / "manifest.json"
    version = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    assert auth.LATEST_EXTENSION_VERSION == version


# ── Klucz ────────────────────────────────────────────────────────────────────


def test_key_round_trip_and_shape() -> None:
    wire, key_id, secret_hash = auth.generate_extension_key()
    assert wire.startswith("nxe_v1_")
    parsed_id, secret = auth.parse_extension_key(wire)
    assert parsed_id == key_id
    assert auth._sha256_hex(secret) == secret_hash


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "nxs_v2_" + "a" * 24 + "_" + "b" * 43,  # klucz konta serwisowego to nie klucz wtyczki
        "nxe_v1_" + "A" * 24 + "_" + "b" * 43,
        "nxe_v1_" + "a" * 24 + "_short",
        "Bearer nxe_v1_" + "a" * 24 + "_" + "b" * 43,
    ],
)
def test_malformed_keys_are_rejected_before_db(raw: str) -> None:
    with pytest.raises(auth.ExtensionKeyError):
        auth.parse_extension_key(raw)


def test_allowed_extension_ids_empty_means_nobody(monkeypatch) -> None:
    monkeypatch.setattr(auth.settings, "LINKEDIN_EXTENSION_IDS", "")
    assert auth.allowed_extension_ids() == frozenset()
    monkeypatch.setattr(auth.settings, "LINKEDIN_EXTENSION_IDS", " abc , def ,")
    assert auth.allowed_extension_ids() == frozenset({"abc", "def"})


# ── Limit dzienny (liczony atomowo w bazie — testy w test_linkedin_extension_api.py)


def _connection(**kw):
    base = dict(usage_day=None, reads_today=0, adds_today=0, last_used_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_last_used_is_throttled() -> None:
    recent = datetime.now(timezone.utc) - timedelta(seconds=10)
    conn = _connection(last_used_at=recent)
    auth.stamp_last_used(conn)
    assert conn.last_used_at == recent
    conn.last_used_at = recent - timedelta(minutes=5)
    auth.stamp_last_used(conn)
    assert conn.last_used_at > recent


# ── Rozpoznanie osoby ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("full", "expected"),
    [
        ("Anna Przykładowa", ("Anna", "Przykładowa")),
        ("Jan Testowy, PhD", ("Jan", "Testowy")),
        ("Jan Maria Testowy (he/him)", ("Jan", "Maria Testowy")),
        ("Anna Przykładowa | Java Developer", ("Anna", "Przykładowa")),
        ("Anna Przykładowa 🚀", ("Anna", "Przykładowa")),
        ("Anna", ("Anna", "")),
        ("", ("", "")),
    ],
)
def test_split_full_name(full: str, expected: tuple[str, str]) -> None:
    assert lookup.split_full_name(full) == expected


def test_profile_link_prefers_public_url_and_ignores_recruiter_ids() -> None:
    recruiter = ProfileRead(
        full_name="Anna Przykładowa",
        page_url="https://www.linkedin.com/talent/profile/AEMAAABCDEF",
    )
    assert lookup.profile_link(recruiter) is None
    with_public = recruiter.model_copy(
        update={"public_url": "https://pl.linkedin.com/in/anna-przykladowa-123/?trk=x"}
    )
    assert lookup.profile_link(with_public) == "https://linkedin.com/in/anna-przykladowa-123"


def _cand(cid: int, *, slug: str | None = None, company: str | None = None, experience=None):
    return SimpleNamespace(
        id=cid,
        name="Anna",
        lastname="Przykładowa",
        linkedin_slug=slug,
        linkedin_current_company=company,
        experience=experience,
    )


def test_resolve_by_link_wins() -> None:
    hit = _cand(1, slug="anna-przykladowa-123")
    result = lookup._resolve(
        "https://linkedin.com/in/anna-przykladowa-123",
        ("Anna", "Przykładowa"),
        "Firma Testowa",
        {"anna-przykladowa-123": hit},
        {},
    )
    assert (result.status, result.matched_by, result.candidate) == ("found", "linkedin", hit)


def test_resolve_name_needs_matching_company() -> None:
    same = _cand(2, company="Firma Testowa Sp. z o.o.")
    other = _cand(3, company="Inna Firma")
    by_name = {("anna", "przykładowa"): [same, other]}
    found = lookup._resolve(None, ("Anna", "Przykładowa"), "Firma Testowa", {}, by_name)
    assert (found.status, found.matched_by, found.candidate) == ("found", "name_company", same)

    unsure = lookup._resolve(None, ("Anna", "Przykładowa"), "Trzecia Firma", {}, by_name)
    assert unsure.status == "ambiguous"
    assert {c.id for c in unsure.ambiguous} == {2, 3}


def test_resolve_unknown_link_and_name_without_company_is_new_person() -> None:
    namesake = _cand(7, company=None)
    by_name = {("anna", "przykładowa"): [namesake]}
    with_link = lookup._resolve(
        "https://linkedin.com/in/anna-przykladowa-123",
        ("Anna", "Przykładowa"),
        "Firma Testowa",
        {},
        by_name,
    )
    assert with_link.status == "not_found"
    recruiter = lookup._resolve(None, ("Anna", "Przykładowa"), "Firma Testowa", {}, by_name)
    assert recruiter.status == "ambiguous"


def test_resolve_same_name_with_other_link_is_someone_else() -> None:
    other_person = _cand(4, slug="anna-przykladowa-999", company="Firma Testowa")
    by_name = {("anna", "przykładowa"): [other_person]}
    result = lookup._resolve(
        "https://linkedin.com/in/anna-przykladowa-123",
        ("Anna", "Przykładowa"),
        "Firma Testowa",
        {},
        by_name,
    )
    assert result.status == "not_found"


def test_job_change_only_when_companies_differ() -> None:
    profile = ProfileRead(full_name="Anna Przykładowa", current_company="Nowa Firma")
    moved = _cand(5, company="Stara Firma")
    assert lookup.job_change_out(profile, moved).nexus_company == "Stara Firma"
    stayed = _cand(6, company="Nowa Firma S.A.")
    assert lookup.job_change_out(profile, stayed) is None


def test_years_from_experience_uses_earliest_start() -> None:
    profile = ProfileRead(
        full_name="Anna Przykładowa",
        experience=[
            ExperienceItem(title="Dev", company="A", start="2019-06"),
            ExperienceItem(title="Junior", company="B", start="2016"),
        ],
    )
    years = lookup.years_from_experience(profile)
    assert years is not None and years >= 10


# ── Szkic wiadomości ─────────────────────────────────────────────────────────


def test_invitation_fallback_fits_in_300_characters() -> None:
    profile = ProfileRead(full_name="Jan Testowy")
    job = {
        "title": "Senior Java Developer " + "x" * 200,
        "client": "Klient Testowy",
        "skills": ["Java", "Spring", "Kafka"],
    }
    user = SimpleNamespace(name="Anna Przykładowa")
    text = draft.fallback_text(profile, job, user, "invitation")
    assert len(text) <= 300
    assert text.startswith("Cześć Jan,")


def test_inmail_fallback_has_signature() -> None:
    text = draft.fallback_text(
        ProfileRead(full_name="Jan Testowy"),
        {"title": "Tester", "client": None, "skills": []},
        SimpleNamespace(name="Anna Przykładowa"),
        "inmail",
    )
    assert text.endswith("Anna, B2B Network")
