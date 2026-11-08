"""Runda 7 audytu — nagrobki usuniętych kandydatów i okna fazy cv_fields (bez bazy).

* R7-V2-2 — nagrobek maila (druga kartoteka Traffita tej samej osoby);
* R7-V2-3 — INSERT kandydata sam sprawdza nagrobek (usunięcie w trakcie fazy);
* R7-V2-4 — import Talent Radar czyta nagrobki;
* R7-V2-5 — okno fazy ``candidates_cv_fields`` nie gubi kandydata, któremu coś
  spoza syncu przesunęło ``updated_at``.

Testy z bazą: ``test_candidate_erasure_leftovers.py``.
"""

from __future__ import annotations


import pytest


@pytest.fixture
def hmac_key(monkeypatch):
    from app.services import candidate_audit

    monkeypatch.setattr(
        candidate_audit.settings, "CANDIDATE_IDENTITY_FINGERPRINT_KEY", "k" * 40
    )


# ── R7-V2-2: nagrobek maila ──────────────────────────────────────────────────


def test_email_tombstone_is_normalized_keyed_and_separate_from_id(hmac_key):
    from app.services.candidate_audit import (
        candidate_email_tombstone,
        candidate_source_tombstone,
    )

    first = candidate_email_tombstone("Jan.Kowalski@Example.com")
    assert first == candidate_email_tombstone("  jan.kowalski@example.com ")
    assert len(first) == 64 and "kowalski" not in first
    assert first != candidate_email_tombstone("jan.kowalski2@example.com")
    # Inna domena HMAC niż nagrobek identyfikatora.
    assert first != candidate_source_tombstone("email", "jan.kowalski@example.com")
    assert candidate_email_tombstone(None) is None
    assert candidate_email_tombstone("   ") is None


def test_email_tombstone_fails_closed_without_key(monkeypatch):
    from app.services import candidate_audit

    monkeypatch.setattr(
        candidate_audit.settings, "CANDIDATE_IDENTITY_FINGERPRINT_KEY", " "
    )
    with pytest.raises(RuntimeError):
        candidate_audit.candidate_email_tombstone("a@b.pl")


# ── R7-V2-3: INSERT sprawdza nagrobek w chwili zapisu ────────────────────────


# ── R7-V2-4: Talent Radar czyta nagrobki ─────────────────────────────────────


def _tr_importer():
    from app.services.talent_radar_importer import TalentRadarImporter

    return TalentRadarImporter("postgresql://x", target_db=None)


def test_talent_radar_skips_tombstoned_traffit_id_and_email(hmac_key):
    from app.services.candidate_audit import (
        candidate_email_tombstone,
        candidate_source_tombstone,
    )

    imp = _tr_importer()
    imp._tombstones = {
        "traffit": {candidate_source_tombstone("traffit", "48895")},
        "tr_legacy": set(),
        "email": {candidate_email_tombstone("gone@example.com")},
    }
    assert imp._is_tombstoned({"external_id": "48895", "email": None})
    assert imp._is_tombstoned({"external_id": "1", "email": "GONE@example.com"})
    assert not imp._is_tombstoned({"external_id": "1", "email": "live@example.com"})
    # Żywy właściciel identyfikatora nie jest usuniętą osobą.
    imp._ext_id_to_id = {"1": 7}
    assert not imp._is_tombstoned({"external_id": "1", "email": "gone@example.com"})
    # Żywy wiersz z tym mailem — osoba wróciła, CV łączy się z nią.
    imp._email_to_id = {"gone@example.com": 9}
    assert not imp._is_tombstoned({"external_id": "2", "email": "Gone@example.com"})


def test_talent_radar_without_tombstones_checks_nothing():
    imp = _tr_importer()
    assert not imp._is_tombstoned({"external_id": "1", "email": "a@b.pl"})


@pytest.mark.asyncio
async def test_talent_radar_upsert_does_not_touch_a_tombstoned_person(hmac_key):
    from app.services.candidate_audit import candidate_source_tombstone

    class CommitOnlyDb:
        async def commit(self):
            return None

        def __getattr__(self, name):
            raise AssertionError(f"import dotknął bazy przez .{name}")

    imp = _tr_importer()
    imp.target_db = CommitOnlyDb()
    imp._tombstones = {"tr_legacy": {candidate_source_tombstone("tr_legacy", "5")}}

    async def must_not_run(p):
        raise AssertionError("usunięta osoba doszła do dopasowania")

    imp._find_existing_id = must_not_run
    inserted, updated = await imp._upsert([{"external_id": "5", "email": None}])
    assert (inserted, updated) == (0, 0)
    assert imp.tombstoned == 1


# ── R7-V2-5: okna fazy cv_fields ─────────────────────────────────────────────


class _NoopSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _fake_backfill(calls, *, stop_on_call=None, stop_at=None):
    async def fake(
        db,
        *,
        after_id=0,
        until_id=None,
        updated_since=None,
        updated_before=None,
        limit=None,
        progress=None,
        **kw,
    ):
        calls.append(
            {
                "after_id": after_id,
                "until_id": until_id,
                "since": updated_since,
                "until": updated_before,
            }
        )
        stats = progress if progress is not None else {}
        stats.setdefault("processed", 0)
        if stop_on_call is not None and len(calls) == stop_on_call:
            stats["last_id"] = stop_at
            stats["stopped_reason"] = "limit"
            return stats
        stats["stopped_reason"] = "done"
        return stats

    return fake


# ── R8-V2-4: import Traffita czyta nagrobek `tr_legacy` ──────────────────────


class _TombstoneDb:
    """Atrapa bazy: zwraca nagrobki `purged_candidates` dla podanych źródeł."""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, statement, params=None):
        from unittest.mock import MagicMock

        result = MagicMock()
        sql = str(statement)
        if "to_regclass" in sql:
            result.fetchone.return_value = (True,)
        else:
            sources = set((params or {}).get("sources") or [])
            result.fetchall.return_value = [r for r in self._rows if r[0] in sources]
        return result
