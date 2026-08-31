"""Reguły CV per klient — składanie nazwy pliku.

Wzory pochodzą z sekcji „7. STANDARDY REKRUTACJI KLIENTA" szablonów Profilu
Championa (Pomoc → „Profile Championa — per klient"). Ten test jest kontraktem
z tamtymi dokumentami: jeśli klient zmieni wymaganie, ma tu paść konkretna
asercja, a nie „coś się rozjechało" wykryte dopiero przez odbiorcę CV.
"""

from datetime import date

import pytest

from app.models.client_cv_rule import ClientCvRule
from app.services.cv_generator_b2b.client_rules import (
    CvRuleSnapshot,
    build_filename,
    describe_rule,
    snapshot_rule,
)


def _rule(pattern: str | None, *, underscores: bool = False, **kw) -> CvRuleSnapshot:
    """Snapshot reguły — dokładnie to, co dostaje synchroniczny pipeline."""
    return CvRuleSnapshot(
        filename_pattern=pattern,
        spaces_to_underscores=underscores,
        cv_language=kw.get("cv_language"),
        requires_en_copy=kw.get("requires_en_copy", False),
        requires_rodo_consent_block=kw.get("requires_rodo_consent_block", False),
    )


def test_snapshot_carries_every_field_the_pipeline_reads():
    """Snapshot istnieje po to, żeby wiersz ORM nie przekraczał granicy wątku
    (dostęp do atrybutu w threadpoolu = MissingGreenlet = 500 bez CORS)."""
    row = ClientCvRule(
        client_id=1,
        filename_pattern="B2B_{IMIE_NAZWISKO}",
        spaces_to_underscores=True,
        cv_language="en",
        requires_en_copy=True,
        requires_rodo_consent_block=True,
    )
    snap = snapshot_rule(row)
    assert snap == CvRuleSnapshot(
        filename_pattern="B2B_{IMIE_NAZWISKO}",
        spaces_to_underscores=True,
        cv_language="en",
        requires_en_copy=True,
        requires_rodo_consent_block=True,
    )
    assert snapshot_rule(None) is None


# (etykieta, wzór, spaces_to_underscores, oczekiwana nazwa)
# Kandydat: „Jan Kowalski", stanowisko: „Analityk Biznesowy", projekt: „4521".
_CASES = [
    (
        "ALIOR",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "B2B_Analityk Biznesowy_Jan Kowalski.docx",
    ),
    (
        "BIK",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "B2B_Analityk Biznesowy_Jan Kowalski.docx",
    ),
    (
        "BNP PARIBAS",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "B2B_Analityk Biznesowy_Jan Kowalski.docx",
    ),
    (
        "SANTANDER",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "B2B_Analityk Biznesowy_Jan Kowalski.docx",
    ),
    (
        "Nordea",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "B2B_Analityk Biznesowy_Jan Kowalski.docx",
    ),
    (
        "PFRON",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "B2B_Analityk Biznesowy_Jan Kowalski.docx",
    ),
    (
        "KIR",
        "B2B_{STANOWISKO}_{IMIE_NAZWISKO}",
        True,
        "B2B_Analityk_Biznesowy_Jan_Kowalski.docx",
    ),
    (
        "Bank Pocztowy",
        "Bank_Pocztowy_{STANOWISKO}_{IMIE_NAZWISKO}",
        True,
        "Bank_Pocztowy_Analityk_Biznesowy_Jan_Kowalski.docx",
    ),
    (
        "PANSA",
        "B2B_PANSA_{STANOWISKO}_{IMIE_NAZWISKO}",
        True,
        "B2B_PANSA_Analityk_Biznesowy_Jan_Kowalski.docx",
    ),
    (
        "Tauron",
        "B2B_Tauron_{STANOWISKO}_{IMIE_NAZWISKO}",
        True,
        "B2B_Tauron_Analityk_Biznesowy_Jan_Kowalski.docx",
    ),
    (
        "ENERGA",
        "ENERGA_{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "ENERGA_4521_Analityk Biznesowy_Jan Kowalski.docx",
    ),
    (
        "ORLEN",
        "ORLEN_{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "ORLEN_4521_Analityk Biznesowy_Jan Kowalski.docx",
    ),
    (
        "PKO BP",
        "ZOB-{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
        False,
        "ZOB-4521_Analityk Biznesowy_Jan Kowalski.docx",
    ),
]


@pytest.mark.parametrize("label,pattern,underscores,expected", _CASES)
def test_all_fourteen_client_patterns(label, pattern, underscores, expected):
    result = build_filename(
        _rule(pattern, underscores=underscores),
        position="Analityk Biznesowy",
        candidate_name="Jan Kowalski",
        project="4521",
    )
    assert result is not None, label
    assert result.filename == expected, label
    assert result.warnings == (), label


def test_credit_agricole_appends_generation_date():
    """Jedyny klient wymagający daty w nazwie — «bieżąca_data» w szablonie."""
    result = build_filename(
        _rule("B2B.NET_{STANOWISKO}_{IMIE_NAZWISKO}_{DATA}", underscores=True),
        position="Analityk Biznesowy",
        candidate_name="Jan Kowalski",
        today=date(2026, 8, 31),
    )
    assert result is not None
    assert result.filename == (
        "B2B.NET_Analityk_Biznesowy_Jan_Kowalski_2026-08-31.docx"
    )
    # Kropka w „B2B.NET" NIE jest separatorem — nie wolno jej zwinąć.
    assert "B2B.NET" in result.filename


def test_polish_diacritics_survive():
    result = build_filename(
        _rule("B2B_{STANOWISKO}_{IMIE_NAZWISKO}", underscores=True),
        position="Główny Księgowy",
        candidate_name="Łukasz Żółć",
    )
    assert result is not None
    assert result.filename == "B2B_Główny_Księgowy_Łukasz_Żółć.docx"


def test_filesystem_reserved_characters_are_stripped():
    result = build_filename(
        _rule("B2B_{STANOWISKO}_{IMIE_NAZWISKO}"),
        position="DevOps / SRE",
        candidate_name="Jan Kowalski",
    )
    assert result is not None
    assert "/" not in result.filename
    assert result.filename == "B2B_DevOps  SRE_Jan Kowalski.docx"


class TestMissingTokenValues:
    """Brak wartości nie może wysadzić generacji ani zostawić „B2B__Jan"."""

    def test_missing_project_collapses_separator_and_warns(self):
        result = build_filename(
            _rule("ENERGA_{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}"),
            position="Analityk",
            candidate_name="Jan Kowalski",
            project=None,
        )
        assert result is not None
        assert result.filename == "ENERGA_Analityk_Jan Kowalski.docx"
        assert "__" not in result.filename
        assert len(result.warnings) == 1
        assert "numer projektu" in result.warnings[0]

    def test_missing_project_after_hyphen_prefix(self):
        """PKO BP: „ZOB-{PROJEKT}" bez projektu nie może dać „ZOB-_…"."""
        result = build_filename(
            _rule("ZOB-{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}"),
            position="Analityk",
            candidate_name="Jan Kowalski",
            project=None,
        )
        assert result is not None
        assert result.filename == "ZOB_Analityk_Jan Kowalski.docx"

    def test_missing_position_in_upload_mode(self):
        result = build_filename(
            _rule("B2B_{STANOWISKO}_{IMIE_NAZWISKO}"),
            position="",
            candidate_name="Jan Kowalski",
        )
        assert result is not None
        assert result.filename == "B2B_Jan Kowalski.docx"
        assert "stanowisko" in result.warnings[0]

    def test_name_must_survive_or_we_fall_back(self):
        """Nazwa bez tożsamości kandydata jest bezużyteczna → globalny fallback."""
        result = build_filename(
            _rule("B2B_{STANOWISKO}"),
            position="Analityk",
            candidate_name="Jan Kowalski",
        )
        assert result is None


class TestRuleGating:
    def test_no_rule_means_no_opinion(self):
        assert build_filename(None, position="X", candidate_name="Jan") is None

    def test_rule_without_pattern_means_no_opinion(self):
        assert build_filename(_rule(None), position="X", candidate_name="Jan") is None
        assert build_filename(_rule("   "), position="X", candidate_name="Jan") is None


class TestDescribeRule:
    def test_empty_string_when_client_has_no_rule(self):
        """Pusty string ≠ None — front rozróżnia „nie wybrano klienta" od
        „wybrano, ale brak reguł", bo to drugie wymaga uwagi rekrutera."""
        assert describe_rule(None) == ""

    def test_lists_what_actually_applies(self):
        rule = _rule("B2B_{IMIE_NAZWISKO}", cv_language="en")
        assert describe_rule(rule) == "nazwa pliku, język EN"

    def test_mentions_rodo_block(self):
        rule = _rule("ZOB-{PROJEKT}_{IMIE_NAZWISKO}", requires_rodo_consent_block=True)
        assert "blok zgody RODO" in describe_rule(rule)


class TestLanguageEnforcement:
    """Reguła z `cv_language` odmawia JAWNIE, zamiast po cichu przestawiać język.

    Ciche przestawienie dałoby rekruterowi dokument w języku, którego nie
    wybrał, bez żadnego śladu — a to jest plik wysyłany do klienta.
    """

    def test_matching_language_passes(self):
        from app.api.cv_generator_b2b import _enforce_client_language

        _enforce_client_language(_rule("B2B_{IMIE_NAZWISKO}", cv_language="en"), "en")

    def test_mismatch_is_refused_with_polish_reason(self):
        import pytest as _pytest
        from fastapi import HTTPException

        from app.api.cv_generator_b2b import _enforce_client_language

        with _pytest.raises(HTTPException) as err:
            _enforce_client_language(
                _rule("B2B_{IMIE_NAZWISKO}", cv_language="en"), "pl"
            )
        assert err.value.status_code == 422
        assert "angielskim" in str(err.value.detail)

    def test_rule_without_language_never_blocks(self):
        """Czterej klienci wymagający OBU wersji mają `cv_language = NULL`.

        Wymuszenie u nich jednego języka zablokowałoby wygenerowanie drugiej
        wersji — czyli dokładnie tego, czego ci klienci oczekują.
        """
        from app.api.cv_generator_b2b import _enforce_client_language

        rule = _rule("B2B_{IMIE_NAZWISKO}", requires_en_copy=True)
        _enforce_client_language(rule, "pl")
        _enforce_client_language(rule, "en")

    def test_no_rule_never_blocks(self):
        from app.api.cv_generator_b2b import _enforce_client_language

        _enforce_client_language(None, "pl")


class TestReminders:
    """Wymogi, których generator NIE MOŻE spełnić za rekrutera, wracają jako
    ostrzeżenia — nie jako cicha zmiana dokumentu."""

    def test_rodo_block_is_a_reminder_not_a_document_change(self):
        from app.services.cv_generator_b2b.client_rules import rule_reminders

        out = rule_reminders(
            _rule("ZOB-{IMIE_NAZWISKO}", requires_rodo_consent_block=True)
        )
        assert len(out) == 1
        assert "zrzutu ekranu" in out[0]

    def test_en_copy_reminder(self):
        from app.services.cv_generator_b2b.client_rules import rule_reminders

        out = rule_reminders(_rule("B2B_{IMIE_NAZWISKO}", requires_en_copy=True))
        assert any("angielsku" in w for w in out)

    def test_quiet_when_client_requires_nothing_extra(self):
        from app.services.cv_generator_b2b.client_rules import rule_reminders

        assert rule_reminders(_rule("B2B_{IMIE_NAZWISKO}")) == ()
        assert rule_reminders(None) == ()


def test_empty_candidate_name_falls_back_instead_of_naming_a_file_after_nobody():
    """Pusty kandydat MUSI zdegradować do globalnej nazwy.

    Regresja: strażnik tożsamości opierał się wyłącznie na
    ``values[TOKEN_FULL_NAME] not in stem``, a ``"" in cokolwiek`` jest zawsze
    prawdą — więc przepuszczał dokładnie ten przypadek, przed którym miał
    chronić. Plik nazwany „B2B_Analityk.docx" nie niesie tożsamości i jest
    nie do odróżnienia w folderze „Pobrane".
    """
    assert (
        build_filename(
            _rule("B2B_{STANOWISKO}_{IMIE_NAZWISKO}"),
            position="Analityk",
            candidate_name="",
        )
        is None
    )
    # Same białe znaki to ta sama sytuacja — normalizacja zwija je do pustki.
    assert (
        build_filename(
            _rule("B2B_{STANOWISKO}_{IMIE_NAZWISKO}"),
            position="Analityk",
            candidate_name="   ",
        )
        is None
    )
