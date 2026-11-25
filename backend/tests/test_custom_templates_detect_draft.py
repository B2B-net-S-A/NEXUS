"""Wzory własne: wykrywanie pól we wgranym Wordzie, szkic asystenta,
sprawdzenia i cykl życia wersji (bez bazy — model podmieniony)."""

from __future__ import annotations

import io
from types import SimpleNamespace

import docx
import pytest

from app.services.custom_templates import checks, draft, sandbox
from app.services.custom_templates import service as svc
from app.services.custom_templates.detect import detect
from app.services.custom_templates.fields import (
    CustomField,
    fields_to_json,
    sample_values,
)


def _docx(*lines: str) -> bytes:
    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _text(data: bytes) -> str:
    return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)


WORD = _docx(
    "UMOWA O PRZEPROWADZENIE SZKOLENIA",
    "zawarta w dniu ____________ w Warszawie pomiędzy B2B.net S.A., a Panem/ią "
    "______________ prowadzącym/cą działalność gospodarczą pod firmą: ________, "
    "NIP: __________, REGON: ________, zwanym/ą dalej „Partnerem”.",
    "Wynagrodzenie wynosi kwotę ______ zł netto (słownie: ____________).",
    "Agenda szkolenia:",
    "______________________________",
    "Szkolenie odbędzie się w siedzibie Klienta: [nazwa klienta].",
    "Partner przyjmuje to do wiadomości (…).",
    "…………………",
    "(podpis Partnera)",
)


# ── Wykrywanie pól ──────────────────────────────────────────────────────────


def test_detect_turns_blanks_and_forms_into_fields() -> None:
    found = detect(WORD)
    by_key = {f.key: f for f in found.fields}
    assert by_key["partner.nip"].source == "ceidg"
    assert by_key["partner.regon"].source == "ceidg"
    assert by_key["partner.legal_name"].source == "ceidg"
    assert by_key["partner.name_instrumental"].source == "candidate"
    assert by_key["document_date"].kind == "date"
    assert by_key["partner.gender"].kind == "gender"
    assert by_key["client.name"].source == "clients"
    money = [f for f in found.fields if f.kind == "money"]
    assert len(money) == 1  # luka „słownie” to zapis kwoty, nie drugie pole
    assert by_key["tresc_1"].kind == "textarea"
    assert by_key["tresc_1"].label == "Agenda szkolenia"
    text = _text(found.docx)
    assert "{{ g.g_pan }}" in text and "{{ g.g_zwanym }}" in text
    assert "{{ " + money[0].key + "_words }}" in text
    # Wielokropek w zdaniu i kreski przy podpisie zostają.
    assert "(…)" in text and "…………………" in text
    assert sandbox.validate(found.docx, found.fields).problems == []


def test_detect_renders_filled_document_without_leftovers() -> None:
    found = detect(WORD)
    out = _text(sandbox.render(found.docx, found.fields, sample_values(found.fields)))
    assert "____" not in out
    assert "Panem/ią" not in out and "prowadzącym/cą" not in out
    assert "Panem Janem Przykładowym prowadzącym" in out
    assert (
        "1 234,50 zł netto (słownie: tysiąc dwieście trzydzieści cztery złote 50/100)"
        in out
    )


def test_detect_warns_about_personal_data_and_unknown_forms() -> None:
    found = detect(
        _docx("Kontakt: jan.kowalski@gmail.com, PESEL 90010112345.", "wykonał/a")
    )
    joined = " ".join(found.warnings)
    assert "adres e-mail" in joined
    assert "PESEL" in joined
    assert "wykonał/a" in joined


def test_detect_keeps_existing_placeholders() -> None:
    found = detect(_docx("Strona: {{ partner.nip }} i {{ fee }} ({{ fee_words }})."))
    by_key = {f.key: f for f in found.fields}
    assert by_key["fee"].kind == "money"
    assert "partner.nip" in by_key
    assert sandbox.validate(found.docx, found.fields).problems == []


def test_detect_rejects_non_docx() -> None:
    with pytest.raises(ValueError):
        detect(b"to nie jest word")


# ── Szkic asystenta (model podmieniony) ─────────────────────────────────────

BASE_FIELDS = [
    CustomField(key="partner.name", label="Imię i nazwisko", required=True),
    CustomField(key="fee", label="Wynagrodzenie", kind="money", required=True),
]
BASE = _docx(
    "Umowa o szkolenie",
    "§ 2. Szkolenie odbywa się w formie zdalnej.",
    "Partner {{ partner.name }} otrzyma {{ fee }} zł.",
)


def test_apply_changes_replaces_inserts_and_deletes() -> None:
    result = draft.apply_changes(
        BASE,
        BASE_FIELDS,
        {
            "summary": "Szkolenie stacjonarne.",
            "changes": [
                {
                    "op": "replace",
                    "i": 1,
                    "text": "§ 2. Szkolenie odbywa się stacjonarnie w {{ training.place }}.",
                    "reason": "forma stacjonarna",
                },
                {
                    "op": "insert_after",
                    "i": 2,
                    "text": "Zwrot kosztów dojazdu do {{ travel_limit }} zł.",
                },
                {"op": "delete", "i": 0},
            ],
            "new_fields": [
                {"key": "training.place", "label": "Miejsce szkolenia", "kind": "text"},
                {"key": "travel_limit", "label": "Limit kosztów", "kind": "money"},
            ],
        },
        title="Wzór",
    )
    text = _text(result.docx)
    assert "stacjonarnie w {{ training.place }}" in text
    assert "Zwrot kosztów dojazdu do {{ travel_limit }} zł." in text
    assert "Umowa o szkolenie" not in text
    assert {f.key for f in result.fields} >= {"training.place", "travel_limit"}
    assert [c["op"] for c in result.changes] == ["delete", "replace", "insert_after"]
    assert result.changes[1]["before"] == "§ 2. Szkolenie odbywa się w formie zdalnej."
    assert sandbox.validate(result.docx, result.fields).problems == []


@pytest.mark.parametrize(
    "text",
    [
        "{{ ''.__class__ }}",
        "{{ partner.name.__class__ }}",
        "{% for x in range(9) %}x{% endfor %}",
        "{{ nieznane }}",
        "{{ partner.name",
    ],
)
def test_model_cannot_smuggle_template_code(text: str) -> None:
    result = draft.apply_changes(
        BASE,
        BASE_FIELDS,
        {"changes": [{"op": "replace", "i": 1, "text": text}]},
        title="W",
    )
    assert result.changes == []
    assert result.warnings
    assert "formie zdalnej" in _text(result.docx)
    assert sandbox.validate(result.docx, result.fields).problems == []


def test_model_new_field_with_reserved_key_is_skipped() -> None:
    result = draft.apply_changes(
        BASE,
        BASE_FIELDS,
        {"new_fields": [{"key": "company.nip", "label": "x"}], "changes": []},
        title="W",
    )
    assert "company.nip" not in {f.key for f in result.fields}
    assert result.warnings


def test_prompt_has_no_personal_data() -> None:
    prompt = draft.change_prompt(
        _docx("Kontakt jan.kowalski@gmail.com, PESEL 90010112345."), [], "zmień"
    )
    assert "gmail" not in prompt and "90010112345" not in prompt


def test_build_from_brief_makes_valid_template() -> None:
    result = draft.build_from_brief(
        {
            "title": "Umowa o poprowadzenie szkolenia",
            "paragraphs": [
                {"style": "title", "text": "Umowa o poprowadzenie szkolenia"},
                {
                    "style": "body",
                    "text": "{{ g.g_pan }} {{ partner.name_instrumental }}",
                },
                {"style": "body", "text": "Wynagrodzenie {{ fee }} ({{ fee_words }})."},
                {"style": "body", "text": "Zła {{ obca.rzecz }} luka."},
            ],
            "new_fields": [
                {"key": "partner.name_instrumental", "label": "Imię", "kind": "text"},
                {"key": "fee", "label": "Wynagrodzenie", "kind": "money"},
            ],
        }
    )
    assert result.title == "Umowa o poprowadzenie szkolenia"
    assert "Zła …… luka." in _text(result.docx)
    assert sandbox.validate(result.docx, result.fields).problems == []


# ── Sprawdzenia ─────────────────────────────────────────────────────────────


def test_checks_flag_employment_copyright_and_gdpr() -> None:
    fields = [CustomField(key="partner.name", label="Imię")]
    found = checks.run_checks(
        "Partner pracuje pod kierownictwem Zamawiającego. Przenosi autorskie prawa "
        "majątkowe, czyli przeniesienie praw.",
        fields,
        signature_form="any",
    )
    by_key = {c.key: c for c in found}
    assert by_key["art22_kp"].state == "warn"
    assert by_key["art53_pr_aut"].state == "block"
    assert by_key["art13_rodo"].state == "warn"
    assert checks.blocking([c.to_public() for c in found])
    written = checks.run_checks(
        "Przeniesienie praw autorskich. Klauzula RODO.",
        fields,
        signature_form="written",
    )
    assert {c.key: c.state for c in written} == {
        "art22_kp": "ok",
        "art53_pr_aut": "ok",
        "art13_rodo": "ok",
    }
    assert all(c.cite_state in ("ok", "missing", "unverified") for c in written)


@pytest.mark.parametrize(
    "text",
    [
        "Partner przenosi autorskie prawa majątkowe do utworów.",
        "przeniesienie praw autorskich do materiałów",
        "z chwilą przeniesienia majątkowych praw autorskich",
        "Partner przenosi na Zamawiającego prawa do utworów.",
    ],
)
def test_copyright_check_catches_inflections(text: str) -> None:
    found = {c.key for c in checks.run_checks(text, [], signature_form="any")}
    assert "art53_pr_aut" in found


# ── Cykl życia wersji (obiekty bez bazy) ────────────────────────────────────


def _version(**extra) -> SimpleNamespace:
    data = _docx("Umowa z {{ partner.name }} na kwotę {{ fee }} zł.")
    base = dict(
        id=7,
        status="draft",
        name="Umowa o szkolenie",
        docx=data,
        fields=fields_to_json(BASE_FIELDS),
        signature_form="any",
        client_scope="all",
        client_ids=[],
        created_by=10,
        submitted_by=None,
        submitted_at=None,
        reviewed_by=None,
        reviewed_at=None,
        review_note=None,
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _user(uid: int, *, admin: bool = False) -> SimpleNamespace:
    return SimpleNamespace(id=uid, has_role=lambda role: admin)


def test_submit_problems_block_until_ready() -> None:
    assert svc.submit_problems(_version()) == []
    assert svc.submit_problems(_version(fields=[]))
    assert svc.submit_problems(_version(client_scope="selected"))
    broken = _version(docx=_docx("{{ ''.__class__ }}"))
    assert any("atrybutu" in p for p in svc.submit_problems(broken))
    rights = _version(
        docx=_docx("Przeniesienie praw autorskich na {{ partner.name }} {{ fee }}")
    )
    assert svc.submit_problems(rights)
    assert (
        svc.submit_problems(_version(docx=rights.docx, signature_form="written")) == []
    )


def test_lifecycle_approve_return_withdraw() -> None:
    template = SimpleNamespace(
        active_version_id=None,
        withdrawn_at=None,
        withdrawn_by=None,
        withdrawn_reason=None,
    )
    version = _version()
    author, admin = _user(10), _user(1, admin=True)
    svc.mark_submitted(version, author)
    assert version.status == "pending" and version.submitted_by == 10
    svc.mark_returned(version, admin, "Popraw § 3")
    assert version.status == "draft" and version.review_note == "Popraw § 3"
    svc.mark_submitted(version, author)
    assert version.review_note is None
    svc.mark_approved(template, version, admin, None)
    assert version.status == "approved" and template.active_version_id == 7
    svc.mark_withdrawn(template, version, admin, "nieaktualny")
    assert version.status == "withdrawn" and template.withdrawn_at is not None


def test_draft_visible_to_author_and_admin_only() -> None:
    version = _version()
    assert svc.may_see_working(_user(10), version)
    assert svc.may_see_working(_user(1, admin=True), version)
    assert not svc.may_see_working(_user(99), version)
    with pytest.raises(Exception) as exc:
        svc.assert_author(_user(99), version)
    assert getattr(exc.value, "status_code", None) == 403


def test_client_scope_and_issued_version_key() -> None:
    selected = _version(client_scope="selected", client_ids=[5, 8])
    assert svc.offered_to(selected, 5)
    assert not svc.offered_to(selected, 6)
    assert not svc.offered_to(selected, None)
    assert svc.offered_to(_version(), None)
    assert svc.version_id_from_key(svc.template_key_for(42)) == 42
    assert svc.version_id_from_key("preliminary_cez_pl") is None
    assert svc.version_id_from_key("custom_v1/../x") is None


def test_issued_document_type_has_no_contract_effects() -> None:
    from app.services.b2b_documents.effects import contract_effect_permission

    doc_type = svc.document_type_for(
        {
            "custom_template": {
                "name": "Umowa o szkolenie stacjonarne",
                "signatories": "partner_and_company",
                "fields": fields_to_json(
                    [
                        *BASE_FIELDS,
                        CustomField(key="pesel", label="PESEL", sensitive=True),
                    ]
                ),
            }
        }
    )
    assert doc_type.family == "custom"
    assert doc_type.label == "Umowa o szkolenie stacjonarne"
    assert doc_type.carries_money
    assert doc_type.sensitive_keys == frozenset({"pesel"})
    assert contract_effect_permission(doc_type) is None


def test_preview_html_shows_field_labels_escaped() -> None:
    fields = [CustomField(key="x", label="<b>Etykieta</b>")]
    html = svc.preview_html(_docx("A {{ x }} B {{ g.g_pan }}"), fields)
    assert "&lt;b&gt;Etykieta&lt;/b&gt;" in html
    assert 'data-field="x"' in html and "forma Pan/Pani" in html
