"""Zwykłe słowa w requeście nie są umiejętnościami (09.11.2026).

Pomiar „Szukaj z requestu” na stagingu: tytuł „Password-less Access
Infrastructure Modernization” dawał must „LeSS” i „Microsoft Access”, a
„Oracle Stabilization Project Technical lead” — „Microsoft Project”. Słownik
zna te słowa jako nazwy (hasło „LeSS”, aliasy „access” i „project”), ale
w requeście stoją jako zwykłe angielskie słowa. Bez bazy.
"""

from contextlib import contextmanager

from app.services import intake_requirements_refine as refine
from app.services import keyword_suggest
from app.services import scoring_service as scoring
from app.services.talent_radar_search import RadarQuery, build_ephemeral_job
from tests.taxonomy_fixture import PROD_LIKE_SKILLS, hydrated_taxonomy

SKILLS = {
    **PROD_LIKE_SKILLS,
    "Microsoft Access": ("database", ("access", "ms access")),
    "Microsoft Project": ("tools", ("project", "ms project")),
    "Microsoft Office": ("tools", ("office", "ms office")),
    "LeSS": ("methodology", ()),
    "SAFe": ("methodology", ()),
    "SOLID": ("practice", ()),
    "Swift": ("mobile", ()),
    "Cisco ISE": ("security", ("ise",)),
}

ISE_DUTIES = (
    "Projektowanie i wdrożenie Cisco ISE w środowisku klienta. "
    "Konfiguracja 802.1X i NAC dla dostępu do sieci. "
    "Identity & Access Management, privileged-access dla administratorów."
)


@contextmanager
def dictionary():
    saved = keyword_suggest.catalog()
    names = list(SKILLS.items())
    keyword_suggest.load_catalog(
        [(i, name, cat) for i, (name, (cat, _a)) in enumerate(names)],
        [
            (i, alias)
            for i, (_n, (_c, aliases)) in enumerate(names)
            for alias in aliases
        ],
    )
    try:
        with hydrated_taxonomy(SKILLS):
            yield
    finally:
        keyword_suggest._catalog = saved


def _radar_must(title: str, text: str) -> list[str]:
    job = build_ephemeral_job(RadarQuery(client_id=11, text=text, title=title))
    return scoring.job_skill_requirements(job)["must"]


# ── „Szukaj z requestu” (Talent Radar) ──────────────────────────────────────


def test_password_less_access_title_gives_no_false_skills():
    with dictionary():
        must = _radar_must(
            "Nordic->Poland - Password-less Access Infrastructure Modernization",
            ISE_DUTIES,
        )
    assert "less" not in must
    assert "microsoft access" not in must


def test_project_in_the_title_is_not_microsoft_project():
    with dictionary():
        must = _radar_must(
            "Oracle Stabilization Project Technical lead",
            "Wsparcie zespołów aplikacyjnych w analizie wydajności baz danych.",
        )
    assert must == ["oracle db"]


def test_plain_words_in_requirements_prose_are_not_skills():
    text = (
        "Wymagania:\n"
        "- solid understanding of networking\n"
        "- less than 3 years is fine\n"
        "- work from the office 3 days a week\n"
        "- swift on-boarding of new users"
    )
    with dictionary():
        must = _radar_must("", text)
    assert must == []


def test_names_written_as_names_still_count():
    text = (
        "Wymagania:\n- MS Access i MS Project\n- LeSS albo SAFe, zasady SOLID\n- Swift"
    )
    with dictionary():
        must = _radar_must("", text)
    for name in (
        "microsoft access",
        "microsoft project",
        "less",
        "safe",
        "solid",
        "swift",
    ):
        assert any(name in m for m in must), (name, must)


def test_lowercase_tail_of_a_hyphenated_word_is_not_a_name():
    with dictionary():
        assert _radar_must("", "Wymagania:\n- wdrożenia non-docker") == []
        assert _radar_must("", "Wymagania:\n- PL-Docker") == ["docker"]


# ── Odczyt maila na /jobs/new (M2 „W mailu są też”) ─────────────────────────


def test_mail_technologies_skip_plain_words():
    mail = (
        "Nordic->Poland - Password-less Access Infrastructure Modernization. "
        + ISE_DUTIES
        + " Praca z biura (office) 2 dni w tygodniu, solid experience."
    )
    rows = [{"words": ["Cisco ISE"], "level": "must"}]
    with dictionary():
        found = refine.mail_technologies(mail, rows)
    assert "LeSS" not in found
    assert "Microsoft Access" not in found
    assert "SOLID" not in found


def test_mail_technologies_keep_names_written_as_names():
    mail = "Zespół pracuje w LeSS, raporty w MS Access, kod według SOLID."
    rows = [{"words": ["Cisco ISE"], "level": "must"}]
    with dictionary():
        found = refine.mail_technologies(mail, rows)
    assert {"LeSS", "Microsoft Access", "SOLID"} <= set(found)
