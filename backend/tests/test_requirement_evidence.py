"""Skąd „✓” przy wymaganiu: źródła i cytaty dla podglądu osoby (10.11.2026)."""

from datetime import date
from types import SimpleNamespace

from app.services.requirement_evidence import EvidenceNote, collect, plain_text


def _cand(**kw):
    base = dict(
        id=1,
        skills=None,
        verified_tech=None,
        tags=None,
        cv_extracted_data=None,
        raw_cv_text=None,
        experience=None,
        skills_manually_curated=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _note(content, *, kind=None, note_id=7, author="Ola Testowa"):
    return EvidenceNote(
        id=note_id,
        noted_on=date(2025, 10, 8),
        author=author,
        kind=kind,
        content=content,
    )


def test_angular_only_in_traffit_field_is_profile_without_cv():
    # Zgłoszenie DL 09.11.2026: „✓ angular” u osoby, która nie ma go w CV.
    cand = _cand(
        raw_cv_text="Java Developer. Spring Boot, Kafka, PostgreSQL.",
        cv_extracted_data={
            "traffit_technologie": "Java, Spring Boot, Angular, TypeScript"
        },
    )
    out = collect(cand, ["angular"], [])
    row = out["angular"]
    assert row["sources"] == ["profile"]
    assert row["cv"] is None
    assert row["profile"][0]["where"] == "Pola z Traffita"
    assert row["profile"][0]["via"] is None
    assert "Angular" in row["profile"][0]["snippet"]


def test_cv_note_and_profile_all_listed_in_order():
    cand = _cand(
        raw_cv_text="Certified Java Programmer with 7 years of experience.",
        skills=[{"name": "Java", "level": "senior", "years": 5}],
    )
    notes = [_note("<p>Technologie: <b>Java</b> (nowsze), Spring Boot</p>")]
    row = collect(cand, ["java"], notes)["java"]
    assert row["sources"] == ["cv", "profile", "note"]
    assert "Java Programmer" in row["cv"]["snippet"]
    assert row["profile"][0]["where"] == "Lista umiejętności"
    note = row["notes"][0]
    assert (
        note["id"] == 7
        and note["date"] == "2025-10-08"
        and note["author"] == "Ola Testowa"
    )
    # Cytat bez znaczników HTML z treści notatki.
    assert "<b>" not in note["snippet"] and "Java" in note["snippet"]


def test_whole_word_only_javascript_is_not_java():
    cand = _cand(raw_cv_text="JavaScript, TypeScript, React")
    row = collect(cand, ["java"], [])["java"]
    assert row["sources"] == []
    assert row["cv"] is None


def test_sql_family_is_a_direct_cv_quote():
    # Rodzina SQL należy do reguły słowa: PostgreSQL w CV to cytat z CV.
    cand = _cand(raw_cv_text="Bazy: PostgreSQL 15, Oracle")
    row = collect(cand, ["sql"], [])["sql"]
    assert "PostgreSQL" in row["cv"]["snippet"]
    assert row["cv"]["via"] == "postgresql"
    assert row["sources"] == ["cv"]


def test_related_form_from_knowledge_map(monkeypatch):
    # Powiązanie z mapy wiedzy (tu podstawione: Spring Boot ⇒ REST API):
    # dosłownej wzmianki nie ma, cytat mówi, którą nazwą wymaganie spełnione.
    from app.services import skill_normalize

    monkeypatch.setattr(
        skill_normalize,
        "implied_forms",
        lambda name, relations=True: ("spring boot",) if name == "rest api" else (),
    )
    cand = _cand(raw_cv_text="Backend w Spring Boot 3, Kafka")
    row = collect(cand, ["rest api"], [])["rest api"]
    assert "Spring Boot" in row["cv"]["snippet"]
    assert row["cv"]["via"] == "spring boot"
    assert row["sources"] == ["cv"]


def test_nothing_found_has_no_sources():
    cand = _cand(raw_cv_text="Python, Django")
    row = collect(cand, ["angular"], [])["angular"]
    assert row["sources"] == [] and row["cv"] is None and row["profile"] == []


def test_note_cap_and_more_count():
    cand = _cand()
    notes = [
        _note(f"Pracował z Apache Kafka w projekcie {i}", note_id=i) for i in range(5)
    ]
    row = collect(cand, ["apache kafka"], notes)["apache kafka"]
    assert len(row["notes"]) == 3
    assert row["notes_more"] == 2
    assert row["sources"] == ["note"]


def test_negated_card_answer_is_not_evidence():
    # Karta rekomendacji z przeczeniem nie jest dowodem (ta sama reguła co bramka).
    cand = _cand()
    notes = [_note("Kubernetes: nie zna, tylko teoretycznie", kind="card")]
    row = collect(cand, ["kubernetes"], notes)["kubernetes"]
    assert row["notes"] == []
    assert "note" not in row["sources"]


def test_sentence_requirement_is_skipped():
    cand = _cand(raw_cv_text="Java")
    out = collect(cand, ["Min. 5 lat doświadczenia w projektach bankowych"], [])
    assert out == {}


def test_plain_text_strips_tags_and_entities():
    assert plain_text("<p>A&nbsp;&amp;&nbsp;B</p><br>C") == "A & B C"
