"""Dowody wymagań z CV (panel klienta): czyste funkcje, dane fikcyjne."""

from __future__ import annotations

from app.services.client_panel_evidence import (
    blocks_from_html,
    counts,
    evidence_for,
    evidence_map,
    requirement_key,
    requirements_from_job,
)

_RODO = (
    "Wyrażam zgodę na przetwarzanie moich danych osobowych zawartych w przekazanych "
    "przeze mnie dokumentach przez B2B.net S.A. w celach związanych z Kubernetes."
)

CV = f"""<article class="cv"><h1>Programista Python – Anna Przykładowa</h1><hr>
<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>
<ul><li>Zna <b>Scala</b> i <b>Rust</b>, a do tego <b>Gerrit</b></li></ul>
<h2 data-cv-section="education">EDUKACJA</h2>
<div class="edu"><span class="edu-dates">2010 - 2015</span> <span><b>Politechnika</b> — Informatyka, praca o Fortran</span></div>
<h2 data-cv-section="skills">UMIEJĘTNOŚCI</h2>
<p class="skill"><b>Języki: </b>Python, SQL</p>
<p class="skill"><b>Narzędzia: </b>GitLab CI/CD, GitHub Actions, Git, GCP (Cloud Run)</p>
<h2 data-cv-section="certifications">CERTYFIKATY</h2>
<ul><li>Linux Administrator LPIC-1 - Akademia Testowa (02.2018)</li></ul>
<h2 data-cv-section="languages">JĘZYKI</h2><p>Angielski - Advanced (C1)</p>
<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>
<div class="job"><p class="job-head" data-cv-section="role"><b>Python Backend Engineer</b> <span class="job-dates">02.2020 - obecnie</span></p>
<p class="job-co" data-cv-section="employer">Firma Testowa Sp. z o.o. · IT</p>
<p class="lbl" data-cv-section="duties_label">Zakres zadań:</p>
<ul><li>Zaprojektował mikroserwis webhook (FastAPI) z publikacją zdarzeń</li>
<li>Rozwijał kod według DDD oraz CQRS</li>
<li>Zbudował potok analiz w Jupyter z użyciem BigQuery i Pandas</li></ul>
<p class="lbl" data-cv-section="technologies">Technologie: <span class="tech">Python, FastAPI, Terraform</span></p></div>
<div class="job"><p class="job-head" data-cv-section="role"><b>Web Developer</b> <span class="job-dates">01.2018 - 01.2020</span></p>
<p class="job-co" data-cv-section="employer">Inna Firma · Handel</p>
<ul><li>Rozwój aplikacji webowych dla sklepów</li></ul></div>
<p class="rodo">{_RODO}</p></article>"""


def _status(label: str, document: str = CV) -> str:
    return evidence_for(blocks_from_html(document), label).status


def test_project_evidence_carries_company_and_dates() -> None:
    found = evidence_for(blocks_from_html(CV), "DDD")
    assert found.status == "project"
    item = found.items[0]
    assert item.term == "DDD"
    assert item.quote == "Rozwijał kod według DDD oraz CQRS"
    assert item.where == "Firma Testowa Sp. z o.o."
    assert item.dates == "02.2020 - obecnie"


def test_webhook_is_not_a_web_application() -> None:
    without_web_apps = CV.replace("Rozwój aplikacji webowych dla sklepów", "Rozwój API")
    assert _status("aplikacji webowych", without_web_apps) == "none"
    assert _status("aplikacji webowych") == "project"


def test_bigquery_for_analysis_is_not_the_cloud() -> None:
    no_gcp = CV.replace(", GCP (Cloud Run)", "")
    assert _status("AWS lub GCP lub Azure", no_gcp) == "none"
    assert _status("chmura", no_gcp) == "none"


def test_linux_from_a_certificate_alone_stays_on_the_list() -> None:
    found = evidence_for(blocks_from_html(CV), "Linux")
    assert found.status == "list"
    assert found.items[0].where == "Certyfikaty"
    assert found.weak is True


def test_any_alternative_on_the_skills_list_counts_as_list() -> None:
    found = evidence_for(blocks_from_html(CV), "AWS lub GCP lub Azure")
    assert found.status == "list"
    assert found.items[0].term == "GCP"
    assert found.items[0].where == "Umiejętności"


def test_git_is_not_gitlab_or_github() -> None:
    assert _status("Git") == "list"
    only_gitlab = CV.replace("GitHub Actions, Git, ", "GitHub Actions, ")
    assert _status("Git", only_gitlab) == "none"


def test_why_section_education_and_consent_are_not_evidence() -> None:
    assert _status("Gerrit") == "none"
    assert _status("Scala") == "none"
    assert _status("Fortran") == "none"
    assert _status("Kubernetes") == "none"


def test_microservice_synonyms_and_inflection() -> None:
    assert _status("mikro-usług") == "project"
    assert _status("microservices") == "project"
    assert _status("Doświadczenie w Pythonie") == "project"


def test_technologies_line_alone_is_project_but_weak() -> None:
    found = evidence_for(blocks_from_html(CV), "Terraform")
    assert found.status == "project"
    assert found.items[0].quote.startswith("Technologie:")
    assert found.weak is True


def test_description_of_work_beats_the_technologies_line() -> None:
    found = evidence_for(blocks_from_html(CV), "FastAPI")
    assert [item.quote for item in found.items] == [
        "Zaprojektował mikroserwis webhook (FastAPI) z publikacją zdarzeń"
    ]
    assert found.weak is False


def test_rejected_key_is_none_and_counts_follow() -> None:
    requirements = requirements_from_job(
        [{"name": "Python", "level": "senior"}, "DDD", "Linux", "Gerrit"], None
    )
    found = evidence_map(CV, requirements, rejected=[requirement_key("DDD")])
    assert found[requirement_key("DDD")].status == "none"
    assert found[requirement_key("DDD")].items == ()
    assert counts(found) == (1, 1, 2)


def test_requirements_merge_must_and_nice_without_repeats() -> None:
    requirements = requirements_from_job(
        [{"name": "Python"}, {"name": " python "}, {"name": ""}, {"nope": 1}],
        [{"name": "Mikro-usług"}],
    )
    assert [(r.key, r.label) for r in requirements] == [
        ("python", "Python"),
        ("mikro-uslug", "Mikro-usług"),
    ]


def test_long_description_gives_a_verbatim_fragment_with_the_term() -> None:
    long_line = (
        ("Odpowiadał za utrzymanie systemu " * 12)
        + "w Elixir "
        + ("oraz rozwój modułów " * 12)
    )
    document = (
        '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>'
        f"<ul><li>{long_line.strip()}</li></ul>"
    )
    item = evidence_for(blocks_from_html(document), "Elixir").items[0]
    assert "Elixir" in item.quote
    assert item.quote in " ".join(long_line.split())
    assert len(item.quote) <= 220


def test_editor_html_without_classes_still_reads_markers() -> None:
    document = (
        '<h2 data-cv-section="experience">Experience</h2>'
        '<p data-cv-section="role"><b>Engineer</b> 03.2021 - 04.2023</p>'
        '<p data-cv-section="employer">Example Ltd · IT</p>'
        "<ul><li>Built services in Golang</li></ul>"
    )
    item = evidence_for(blocks_from_html(document), "Golang").items[0]
    assert (item.where, item.dates) == ("Example Ltd", "03.2021 - 04.2023")


def test_no_document_means_no_evidence() -> None:
    assert blocks_from_html(None) == []
    assert blocks_from_html("   ") == []
    assert evidence_map(None, requirements_from_job(["Python"], None))[
        "python"
    ].status == ("none")
