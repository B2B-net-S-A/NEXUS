"""Snapshot rejestru klauzul: ponowne pobranie nie może zmienić treści umowy.

Rejestr klauzul (`CLIENT_OVERRIDES`) jest ŻYWY — needle'e i treść bywają
zmieniane. Ponowne pobranie DOCX rozstrzygało go od nowa po zapisanej nazwie
Klienta, więc dwa commity w pięć tygodni po cichu zmieniły treść już wydanych,
podpisanych umów: § 4 banku zniknął z umów BNP Paribas Cardif, a § 10 z zakazem
konkurencji i karami umownymi doszedł umowom e-Zdrowia. Regresja jest CICHA —
plik pobiera się z kodem 200 i wygląda na kompletny — więc pilnują jej testy.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from docx import Document

from app.api.b2b_contract_generator import (
    _CLAUSE_SNAPSHOT_FIELD,
    _clause_snapshot,
    _pinned_clause_key,
)
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.schemas.b2b_contract_generator import B2BRenderRequest
from app.services.b2b_contract_generator.clause_overrides import (
    ClauseOverrideError,
    apply_ops_html_counted,
    ops_fingerprint,
    overrides_for_key,
    resolve_override,
)
from app.services.b2b_contract_generator.docx_renderer import (
    RESOLVE_BY_CLIENT_NAME,
    render_from_context,
)
from app.services.b2b_contract_generator.render_context import build_render_context

# Fraza z podmienionego § 4 BNP — obecna tylko wtedy, gdy override wszedł.
_BNP_MARKER = "15. Postanowienia ust. 13"


def _context(client_name: str) -> dict:
    req = B2BRenderRequest(
        language="pl",
        partner_name="Jan Kowalski",
        client_name=client_name,
        project_city="Warszawa",
        project_description="Usługi QA.",
        contract_number="1472/2026",
        signing_date=date(2026, 7, 23),
        start_date=date(2026, 8, 1),
        rate_candidate=150,
    )
    return build_render_context(req, None)


def _docx_text(data: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)


def test_pinned_key_beats_current_client_name():
    """Dokument idzie za SNAPSHOTEM, nie za bieżącym rozstrzygnięciem nazwy.

    To jest cała ochrona przed „ten sam wiersz, inna umowa": nazwa w payloadzie
    może dziś nie trafiać rejestru (needle zmieniony), a wydany dokument i tak
    musi wyjść taki, jaki wyszedł pierwotnie.
    """
    ctx = _context("Nordea Bank Abp")  # dziś: żaden override
    assert resolve_override("Nordea Bank Abp", "pl") == (None, [])

    default = _docx_text(render_from_context(ctx, language="pl"))
    assert _BNP_MARKER not in default

    pinned = _docx_text(
        render_from_context(ctx, language="pl", clause_override_key="bnp")
    )
    assert _BNP_MARKER in pinned, "przypięty wpis rejestru nie został zastosowany"


def test_pin_none_means_no_override_even_when_name_now_matches():
    """``None`` w snapshocie ≠ „rozstrzygnij po nazwie".

    Umowa wydana zanim needle dopisano (np. „e-zdrowie") nie miała § 10; po
    dopisaniu needle'a ponowne pobranie dokładało go do dokumentu, którego nikt
    w tej postaci nie podpisywał.
    """
    ctx = _context("BNP Paribas Bank Polska S.A.")
    assert resolve_override(ctx["client"]["name"], "pl")[0] == "bnp"

    out = _docx_text(render_from_context(ctx, language="pl", clause_override_key=None))
    assert _BNP_MARKER not in out


def test_unknown_pinned_key_renders_clean_template():
    """Wpis usunięty z rejestru → czysty szablon, nie zgadywanie po nazwie."""
    ctx = _context("BNP Paribas Bank Polska S.A.")
    out = _docx_text(
        render_from_context(ctx, language="pl", clause_override_key="skasowany_wpis")
    )
    assert _BNP_MARKER not in out


def test_render_fails_loudly_when_anchor_is_missing(monkeypatch):
    """Brak kotwicy § w szablonie = 500, nie umowa bez wynegocjowanej klauzuli.

    Wcześniej `apply_ops_docx` zwracał licznik, który jedyny wołający wyrzucał,
    więc przetytułowanie nagłówka przez prawnika dawało umowę bez klauzuli,
    wydaną z kodem 200 i bez jednej linii w logach.
    """
    import app.services.b2b_contract_generator.docx_renderer as dr

    bogus = [("replace_section", 999, (("p", "klauzula, której nie da się wstawić"),))]
    monkeypatch.setattr(dr, "overrides_for_key", lambda key, lang: bogus)

    with pytest.raises(ClauseOverrideError) as exc:
        render_from_context(
            _context("Nordea Bank Abp"), language="pl", clause_override_key="x"
        )
    assert "0 z 1" in str(exc.value)


def test_html_arm_counts_skips_and_honours_table_index():
    """Podgląd HTML ma licznik i tę samą semantykę indeksu tabeli co DOCX.

    Bez licznika podgląd nie ma JAK zgłosić pominięcia; bez indeksu tabeli
    podgląd i plik pokazują to samo w dwóch różnych miejscach dokumentu.
    """
    sample = "<h2>§ 3</h2>\n<p>a</p>\n<table><tr><td>1</td></tr></table>\n<table><tr><td>2</td></tr></table>\n"
    _, applied = apply_ops_html_counted(
        sample, [("replace_section", 99, (("p", "x"),))]
    )
    assert applied == 0

    out, applied = apply_ops_html_counted(
        sample, [("after_table", 1, (("p", "ZNACZNIK"),))]
    )
    assert applied == 1
    # Wstawka musi wylądować po DRUGIEJ tabeli (indeks 1), nie po pierwszej.
    assert out.index("ZNACZNIK") > out.index("<td>2</td>")

    _, applied = apply_ops_html_counted(sample, [("after_table", 5, (("p", "x"),))])
    assert applied == 0, "nieistniejąca tabela musi być raportowana jako pominięcie"


def test_snapshot_pins_content_not_only_the_registry_entry():
    """Odcisk treści wykrywa zmianę brzmienia klauzul pod tym samym kluczem."""
    key, ops = resolve_override("Alior Bank S.A.", "pl")
    snap = _clause_snapshot(key, ops)
    assert snap["key"] == "alior" and snap["ops"] == len(ops)
    assert snap["fingerprint"] == ops_fingerprint(overrides_for_key("alior", "pl"))
    assert snap["fingerprint"] != ops_fingerprint(overrides_for_key("bik", "pl"))


def test_pinned_key_from_row_and_drift_warning(caplog):
    """Wiersz bez snapshotu → zachowanie historyczne; rozjazd treści → ostrzeżenie."""
    legacy = B2BGeneratedContract(
        id=1, contract_number="1/2026", render_payload={"client_name": "Alior Bank"}
    )
    assert _pinned_clause_key(legacy, "pl") == RESOLVE_BY_CLIENT_NAME

    key, ops = resolve_override("Alior Bank S.A.", "pl")
    fresh = B2BGeneratedContract(
        id=2,
        contract_number="2/2026",
        render_payload={
            "client_name": "Alior Bank S.A.",
            _CLAUSE_SNAPSHOT_FIELD: _clause_snapshot(key, ops),
        },
    )
    with caplog.at_level("WARNING"):
        assert _pinned_clause_key(fresh, "pl") == "alior"
    assert "b2b_clause_registry_drift" not in caplog.text

    stale = B2BGeneratedContract(
        id=3,
        contract_number="3/2026",
        render_payload={
            "client_name": "Alior Bank S.A.",
            _CLAUSE_SNAPSHOT_FIELD: {
                **_clause_snapshot(key, ops),
                "fingerprint": "0" * 16,
            },
        },
    )
    with caplog.at_level("WARNING"):
        assert _pinned_clause_key(stale, "pl") == "alior"
    assert "b2b_clause_registry_drift" in caplog.text
